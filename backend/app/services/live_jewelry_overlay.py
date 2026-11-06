"""Place the selected jewelry on the live try-on video before pass or fail is decided."""

from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np

from app.core.config import Settings, get_settings
from app.cv.face_landmarks import FaceLandmarkError, MediaPipeFaceLandmarker
from app.cv.image_processing import bgr_to_rgb, read_bgr
from app.cv.types import FaceLandmarkResult
from app.cv.visualization import (
    catalog_sprite_layout,
    composite_catalog_earring,
    draw_placed_earring,
    prepare_catalog_sprite,
    save_image,
)
from app.services.earlobe_detector import EarlobeDetector

OVERLAY_SCRIPT = """({ box, items, sprite, aspect, hang, widthRatio }) => {
  let root = document.getElementById("qa-live-jewelry");
  if (!root) {
    root = document.createElement("div");
    root.id = "qa-live-jewelry";
    root.setAttribute("data-qa", "live-jewelry");
    root.style.position = "fixed";
    root.style.pointerEvents = "none";
    root.style.zIndex = "2147483646";
    root.style.overflow = "visible";
    document.body.appendChild(root);
  }
  root.style.left = `${box.x}px`;
  root.style.top = `${box.y}px`;
  root.style.width = `${box.width}px`;
  root.style.height = `${box.height}px`;
  root.replaceChildren();
  if (!sprite) return 0;
  const ratio = aspect > 0 ? aspect : 1;
  const scale = widthRatio > 0 ? widthRatio : 1;
  for (const item of items) {
    const width = Math.max(22, Math.min((item.ear_width || 0.08) * box.width * scale, box.width * 0.18));
    const height = width * ratio;
    const image = document.createElement("img");
    image.alt = "";
    image.src = sprite;
    image.style.position = "absolute";
    image.style.left = `${item.x * box.width - width / 2}px`;
    image.style.top = `${item.y * box.height - (hang ? 0 : height / 2)}px`;
    image.style.width = `${width}px`;
    image.style.height = `${height}px`;
    image.style.objectFit = "contain";
    image.style.filter = "drop-shadow(0 3px 4px rgba(0,0,0,0.35))";
    root.appendChild(image);
  }
  return items.length;
}"""


def sprite_data_url(sprite_path: Path | None) -> str:
    sprite = _load_sprite(sprite_path)
    return _encode_png_data_url(sprite)


def _encode_png_data_url(sprite: np.ndarray) -> str:
    encoded, buffer = cv2.imencode(".png", sprite)
    if not encoded:
        raise ValueError("Unable to encode the jewelry overlay.")
    payload = base64.b64encode(buffer.tobytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def _read_catalog_sprite(sprite_path: Path) -> np.ndarray | None:
    sprite = cv2.imread(str(sprite_path), cv2.IMREAD_UNCHANGED)
    if sprite is None or sprite.size == 0:
        return None
    return prepare_catalog_sprite(sprite)


def paint_preview(frame_path: Path, placements: list[dict], sprite_path: Path | None, destination: Path) -> None:
    image = read_bgr(frame_path)
    for item in placements:
        ear_width = item.get("ear_width")
        if sprite_path is not None and sprite_path.is_file():
            image = composite_catalog_earring(image, sprite_path, float(item["x"]), float(item["y"]), ear_width)
        else:
            image = draw_placed_earring(image, float(item["x"]), float(item["y"]), ear_width)
    save_image(destination, image)


def earlobe_placements(face: FaceLandmarkResult | None, detector: EarlobeDetector) -> list[dict]:
    placements = []
    for side in ("left", "right"):
        anchor, _error = detector.detect(face, side)
        if anchor is None:
            continue
        placements.append(
            {
                "side": side,
                "x": anchor.x,
                "y": anchor.y,
                "ear_width": anchor.ear_width,
            }
        )
    return placements


class LiveJewelryOverlay:
    def __init__(self, browser, output_dir: Path, settings: Settings | None = None) -> None:
        self.browser = browser
        self.output_dir = output_dir
        self.settings = settings or get_settings()
        self.shown = False
        self._detector = EarlobeDetector(self.settings.min_ear_width)
        self._landmarker: MediaPipeFaceLandmarker | None = None
        self._unavailable = False
        self._sprite_url: str | None = None
        self._sprite_stamp: int | None = None
        self._layout: dict | None = None
        self._last_placements: list[dict] = []

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None

    def placements_for(self, frame_path: Path) -> list[dict]:
        landmarker = self._face_landmarker()
        if landmarker is None:
            return []
        face = landmarker.detect(bgr_to_rgb(read_bgr(frame_path)))
        return earlobe_placements(face, self._detector)

    async def update(self, frame_path: Path) -> bool:
        """Hang the selected jewelry on the visible ears. Measurement screenshots stay clean."""
        try:
            return await self._update(frame_path)
        except Exception:
            return False

    async def _update(self, frame_path: Path) -> bool:
        try:
            placements = self.placements_for(frame_path)
        except Exception:
            placements = []
        if placements:
            self._last_placements = placements
        placements = placements or self._last_placements
        if not placements:
            return False
        box = await self.browser.tryon_box()
        if not box:
            return False
        sprite_path = self.output_dir / "selected_earring.png"
        paint_preview(frame_path, placements, sprite_path, self.output_dir / "live_preview.png")
        sprite = self._sprite()
        layout = self._layout or {}
        await self.browser.evaluate(
            OVERLAY_SCRIPT,
            {
                "box": box,
                "items": placements,
                "sprite": sprite or "",
                "aspect": float(layout.get("aspect", 1)),
                "hang": bool(layout.get("hang", True)),
                "widthRatio": float(layout.get("width_ratio", 1)),
            },
        )
        self.shown = bool(sprite)
        return self.shown

    def _sprite(self) -> str | None:
        path = self.output_dir / "selected_earring.png"
        if not path.is_file():
            self._sprite_url = None
            self._sprite_stamp = None
            self._layout = None
            return None
        stamp = path.stat().st_mtime_ns
        if self._sprite_url is None or self._sprite_stamp != stamp:
            sprite = _read_catalog_sprite(path)
            if sprite is None:
                self._sprite_url = None
                self._sprite_stamp = None
                self._layout = None
                return None
            self._sprite_url = _encode_png_data_url(sprite)
            self._sprite_stamp = stamp
            self._layout = catalog_sprite_layout(sprite)
        return self._sprite_url

    def _face_landmarker(self) -> MediaPipeFaceLandmarker | None:
        if self._unavailable:
            return None
        if self._landmarker is None:
            try:
                self._landmarker = MediaPipeFaceLandmarker(self.settings.resolved_face_model_path)
            except FaceLandmarkError:
                self._unavailable = True
                return None
        return self._landmarker


def _load_sprite(sprite_path: Path | None) -> np.ndarray:
    if sprite_path is not None and sprite_path.is_file():
        sprite = cv2.imread(str(sprite_path), cv2.IMREAD_UNCHANGED)
        if sprite is not None and sprite.size:
            return _with_alpha(sprite)
    return _drawn_drop()


def _with_alpha(sprite: np.ndarray) -> np.ndarray:
    if sprite.ndim == 2:
        sprite = cv2.cvtColor(sprite, cv2.COLOR_GRAY2BGRA)
    elif sprite.shape[2] == 3:
        gray = cv2.cvtColor(sprite, cv2.COLOR_BGR2GRAY)
        alpha = np.where(gray > 245, 0, 255).astype(np.uint8)
        sprite = np.dstack([sprite, alpha])
    return sprite


def _drawn_drop() -> np.ndarray:
    canvas = np.zeros((180, 80, 4), dtype=np.uint8)
    gold = (40, 190, 230, 235)
    gem = (70, 150, 210, 235)
    cv2.circle(canvas, (40, 16), 7, gold, -1, lineType=cv2.LINE_AA)
    cv2.line(canvas, (40, 16), (40, 58), gold, 2, lineType=cv2.LINE_AA)
    cv2.ellipse(canvas, (40, 108), (18, 42), 0, 0, 360, gem, -1, lineType=cv2.LINE_AA)
    return canvas
