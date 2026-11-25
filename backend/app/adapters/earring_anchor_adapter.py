"""Reads the jewelry attachment anchor from the live try-on page.

Two sources, in order of trust:
1. A QA debug bridge the page publishes itself (`window.__AIJEWEL_QA__` or a
   `/debug/tryon-state` endpoint).
2. The renderer's own scene graph, read through `JewelrySceneProbe`.

When neither yields an anchor the adapter still returns a diagnostic so the
report can name the stage that failed instead of showing a bare 0.00.
"""

from __future__ import annotations

from app.adapters.browser_adapter import BrowserAdapter
from app.adapters.scene_probe import JewelrySceneProbe, failure_stage, state_from_report

_SCRIPT = """
async () => {
  const pages = [window];
  const frame = document.querySelector('iframe');
  try {
    if (frame && frame.contentWindow) pages.push(frame.contentWindow);
  } catch (error) {
    // A cross-origin try-on frame has no readable debug state.
  }
  for (const page of pages) {
    const bridged = page.__AIJEWEL_QA__ || page.AIJewelQA || null;
    if (bridged) return bridged;
  }
  const paths = ['/debug/tryon-state', '/api/debug/tryon-state'];
  for (const path of paths) {
    try {
      const response = await fetch(path, { credentials: 'include' });
      const contentType = response.headers.get('content-type') || '';
      if (response.ok && contentType.includes('json')) {
        return await response.json();
      }
    } catch (error) {
      continue;
    }
  }
  return null;
}
"""


_ANCHOR_KEYS = (
    "left",
    "right",
    "center",
    "necklace",
    "ring",
    "bracelet",
    "bangle",
    "jewelry",
    "attachment",
)


def _block_has_point(block) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("visible") is False:
        return False
    return block.get("x") is not None and block.get("y") is not None


def state_has_attachment(state: dict | None) -> bool:
    """True when the debug payload carries at least one usable attachment point."""
    if not isinstance(state, dict):
        return False
    if any(_block_has_point(state.get(key)) for key in _ANCHOR_KEYS):
        return True
    # Nested shapes some bridges publish: { jewelry: { left: {...} } }.
    for nested_key in ("jewelry", "attachment", "earrings", "rings"):
        nested = state.get(nested_key)
        if isinstance(nested, dict) and any(_block_has_point(nested.get(key)) for key in _ANCHOR_KEYS):
            return True
    return False


class EarringAnchorPageAdapter:
    def __init__(self, browser: BrowserAdapter) -> None:
        self.browser = browser
        self.scene_probe = JewelrySceneProbe(browser)

    async def read_state(
        self,
        jewelry_type: str = "earring",
        sides: tuple[str, ...] = ("left", "right", "center"),
    ) -> dict | None:
        bridged = await self.browser.evaluate(_SCRIPT)
        # An empty or incomplete bridge must not block the scene probe — that was
        # the broken connection behind jewelry confidence 0.00 / distance N/A.
        if isinstance(bridged, dict) and state_has_attachment(bridged):
            return {**bridged, "anchor_source": "debug_bridge", "anchor_stage": "ANCHOR_AVAILABLE"}

        report = await self.scene_probe.read(jewelry_type, sides[0] if sides else "left")
        stage = failure_stage(report)
        probed = state_from_report(report, jewelry_type, sides)
        if probed is not None:
            merged = {**probed, "anchor_source": "scene_probe", "anchor_stage": stage}
            if isinstance(bridged, dict):
                merged["bridge_present_but_empty"] = True
            return merged
        # No anchor, but say exactly why rather than reporting nothing at all.
        result = {
            "anchor_source": "unavailable",
            "anchor_stage": stage,
            "scene_diagnostics": report,
        }
        if isinstance(bridged, dict):
            result["bridge_present_but_empty"] = True
            result["bridge_keys"] = sorted(str(key) for key in bridged.keys())
        return result
