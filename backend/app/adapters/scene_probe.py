"""Read-only probe for the live try-on 3D scene.

The storefront does not publish a QA debug bridge, so the attachment anchor has
to be read from the renderer itself. This walks the existing scene graph, reads
the transform the placement script already produced, and projects it with the
page's own camera. It never writes to the scene, the models, or the physics.
"""

from __future__ import annotations

from app.adapters.browser_adapter import BrowserAdapter

# Stage names reported back so a missing anchor can be attributed precisely.
STAGE_RENDERER = "renderer_found"
STAGE_SCENE = "scene_found"
STAGE_CAMERA = "camera_found"
STAGE_MODEL = "glb_loaded"
STAGE_VISIBLE = "mesh_visible"
STAGE_TRANSFORM = "transform_computed"
STAGE_PROJECTED = "anchor_projected"

_KEYWORDS = {
    "earring": ["earring", "ear_", "jhumka", "stud", "lobe"],
    "necklace": ["necklace", "pendant", "chain", "neck"],
    "ring": ["ring", "finger"],
    "bracelet": ["bracelet", "wrist"],
    "bangle": ["bangle", "wrist"],
}

_SCRIPT = """
({ keywords, side }) => {
  const report = {
    renderer_found: false, scene_found: false, camera_found: false,
    glb_loaded: false, mesh_visible: false, transform_computed: false,
    anchor_projected: false, candidates: [], notes: [],
  };

  const windows = [window];
  try {
    for (const frame of document.querySelectorAll('iframe')) {
      if (frame.contentWindow) windows.push(frame.contentWindow);
    }
  } catch (error) {
    report.notes.push('cross_origin_iframe');
  }

  // Collect scene/camera/renderer triples without touching them.
  const found = [];
  for (const page of windows) {
    let devtools = null;
    try { devtools = page.__THREE_DEVTOOLS__; } catch (error) { devtools = null; }
    if (devtools && devtools.scenes) {
      for (const scene of devtools.scenes) found.push({ scene, camera: null, renderer: null, page });
    }
    let canvases = [];
    try { canvases = Array.from(page.document.querySelectorAll('canvas')); } catch (error) { canvases = []; }
    for (const canvas of canvases) {
      const store = canvas.__r3f && canvas.__r3f.store;
      if (store && typeof store.getState === 'function') {
        const state = store.getState();
        found.push({ scene: state.scene, camera: state.camera, renderer: state.gl, page, canvas });
      }
    }
    // Last resort: a small scan of globals the app may have exposed itself.
    let names = [];
    try { names = Object.getOwnPropertyNames(page); } catch (error) { names = []; }
    for (const name of names) {
      if (name.length > 40) continue;
      let value = null;
      try { value = page[name]; } catch (error) { continue; }
      if (!value || typeof value !== 'object') continue;
      if (value.isScene) found.push({ scene: value, camera: null, renderer: null, page });
      else if (value.isWebGLRenderer) found.push({ scene: null, camera: null, renderer: value, page });
      else if (value.scene && value.scene.isScene) {
        found.push({ scene: value.scene, camera: value.camera || null, renderer: value.renderer || null, page });
      }
    }
  }
  if (!found.length) {
    report.notes.push('no_three_scene_reachable');
    return report;
  }

  const matches = (name) => {
    const lower = String(name || '').toLowerCase();
    return keywords.some((word) => lower.includes(word));
  };

  for (const entry of found) {
    if (entry.renderer) report.renderer_found = true;
    const scene = entry.scene;
    if (!scene || typeof scene.traverse !== 'function') continue;
    report.scene_found = true;

    let camera = entry.camera;
    if (!camera) {
      scene.traverse((node) => { if (!camera && node.isCamera) camera = node; });
    }
    if (camera) report.camera_found = true;

    scene.traverse((node) => {
      const named = matches(node.name) || matches(node.userData && node.userData.type)
        || matches(node.userData && node.userData.category);
      if (!named) return;
      report.glb_loaded = true;

      let hasGeometry = false;
      node.traverse((child) => { if (child.isMesh) hasGeometry = true; });
      if (!hasGeometry && !node.isMesh) return;

      let visible = node.visible !== false;
      let walker = node.parent;
      while (visible && walker) { visible = walker.visible !== false; walker = walker.parent; }
      if (visible) report.mesh_visible = true;

      const candidate = {
        name: node.name || '(unnamed)',
        visible,
        side: null,
        world: null,
        screen: null,
        scale: null,
        rotation_deg: null,
      };
      const lower = String(node.name || '').toLowerCase();
      if (lower.includes('left')) candidate.side = 'left';
      else if (lower.includes('right')) candidate.side = 'right';

      try {
        node.updateWorldMatrix(true, false);
        const position = new node.position.constructor();
        node.getWorldPosition(position);
        candidate.world = { x: position.x, y: position.y, z: position.z };
        const worldScale = new node.scale.constructor();
        node.getWorldScale(worldScale);
        candidate.scale = (worldScale.x + worldScale.y + worldScale.z) / 3;
        candidate.rotation_deg = (node.rotation.z * 180) / Math.PI;
        report.transform_computed = true;

        if (camera && typeof position.project === 'function') {
          camera.updateMatrixWorld();
          const projected = position.clone().project(camera);
          const canvas = entry.canvas
            || (entry.renderer && entry.renderer.domElement)
            || entry.page.document.querySelector('canvas');
          if (canvas) {
            const rect = canvas.getBoundingClientRect();
            const px = rect.left + ((projected.x + 1) / 2) * rect.width;
            const py = rect.top + ((1 - projected.y) / 2) * rect.height;
            const vw = window.innerWidth || rect.width;
            const vh = window.innerHeight || rect.height;
            const inFront = projected.z < 1;
            candidate.screen = { x: px / vw, y: py / vh, in_front: inFront };
            if (inFront && px >= 0 && py >= 0 && px <= vw && py <= vh) report.anchor_projected = true;
          } else {
            report.notes.push('no_canvas_for_projection');
          }
        }
      } catch (error) {
        report.notes.push('transform_read_failed');
      }
      report.candidates.push(candidate);
    });
  }
  if (!report.glb_loaded) report.notes.push('no_jewelry_node_matched_keywords');
  return report;
}
"""


class JewelrySceneProbe:
    """Reads the live jewelry transform and reports which stage failed."""

    def __init__(self, browser: BrowserAdapter) -> None:
        self.browser = browser

    async def read(self, jewelry_type: str, side: str = "left") -> dict:
        keywords = _KEYWORDS.get((jewelry_type or "earring").lower(), [jewelry_type or "earring"])
        try:
            report = await self.browser.evaluate(_SCRIPT, {"keywords": keywords, "side": side})
        except Exception as exc:  # the page may navigate mid-probe
            return _empty_report(f"probe_failed: {type(exc).__name__}")
        if not isinstance(report, dict):
            return _empty_report("probe_returned_no_report")
        report.setdefault("candidates", [])
        report.setdefault("notes", [])
        return report


def _empty_report(note: str) -> dict:
    return {
        STAGE_RENDERER: False,
        STAGE_SCENE: False,
        STAGE_CAMERA: False,
        STAGE_MODEL: False,
        STAGE_VISIBLE: False,
        STAGE_TRANSFORM: False,
        STAGE_PROJECTED: False,
        "candidates": [],
        "notes": [note],
    }


def pick_candidate(report: dict, side: str) -> dict | None:
    """Choose the candidate for this side, preferring an explicitly named one."""
    candidates = [item for item in (report.get("candidates") or []) if isinstance(item, dict)]
    usable = [item for item in candidates if item.get("visible") and (item.get("screen") or {}).get("in_front")]
    if not usable:
        return None
    for item in usable:
        if item.get("side") == side:
            return item
    if side == "center" and len(usable) == 1:
        return usable[0]
    if side in {"left", "right"} and len(usable) == 1 and usable[0].get("side") is None:
        return usable[0]
    # Two unnamed candidates: the left ear sits on the smaller screen x.
    unnamed = [item for item in usable if item.get("side") is None]
    if side in {"left", "right"} and len(unnamed) >= 2:
        ordered = sorted(unnamed, key=lambda item: item["screen"]["x"])
        return ordered[0] if side == "left" else ordered[-1]
    return None


def state_from_report(report: dict, jewelry_type: str, sides: tuple[str, ...]) -> dict | None:
    """Convert a probe report into the debug-state shape the detectors already read."""
    state: dict = {"source": "scene_probe", "scene_diagnostics": report}
    placed = False
    for side in sides:
        candidate = pick_candidate(report, side)
        if candidate is None:
            continue
        placed = True
        screen = candidate["screen"]
        block = {
            "x": float(screen["x"]),
            "y": float(screen["y"]),
            "visible": True,
            # Read straight off the scene graph, so this is a measurement, not a guess.
            "confidence": 0.99,
            "source": "scene_probe",
            "rotation": candidate.get("rotation_deg"),
            "scale": candidate.get("scale"),
        }
        state[side] = block
        if jewelry_type == "necklace":
            state["necklace"] = block
    return state if placed else None


def failure_stage(report: dict) -> str:
    """Name the first stage of the pipeline that did not complete."""
    if not report.get(STAGE_SCENE):
        return "SCENE_NOT_REACHABLE"
    if not report.get(STAGE_MODEL):
        return "EARRING_MODEL_NOT_LOADED"
    if not report.get(STAGE_VISIBLE):
        return "JEWELRY_MESH_HIDDEN"
    if not report.get(STAGE_TRANSFORM):
        return "TRANSFORM_NOT_COMPUTED"
    if not report.get(STAGE_CAMERA):
        return "CAMERA_NOT_FOUND"
    if not report.get(STAGE_PROJECTED):
        return "ATTACHMENT_ANCHOR_MISSING"
    return "ANCHOR_AVAILABLE"
