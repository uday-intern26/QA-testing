"""Place the selected jewelry on the live try-on video before pass or fail is decided."""

from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np

from app.core.config import Settings, get_settings
from app.cv.face_landmarks import FaceLandmarkError, MediaPipeFaceLandmarker
from app.cv.hand_landmarks import HandLandmarkError, MediaPipeHandLandmarker
from app.cv.image_processing import bgr_to_rgb, read_bgr
from app.cv.types import FaceLandmarkResult, HandLandmarkResult
from app.cv.visualization import (
    catalog_sprite_layout,
    composite_catalog_earring,
    draw_placed_earring,
    prepare_catalog_sprite,
    save_image,
)
from app.services.earlobe_detector import EarlobeDetector

OVERLAY_SCRIPT = """({ box, items, sprite, aspect, hang, widthRatio, maxWidthRatio }) => {
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
  const maxRatio = maxWidthRatio > 0 ? maxWidthRatio : 0.08;
  for (const item of items) {
    const width = Math.max(
      14,
      Math.min((item.ear_width || 0.04) * box.width * scale * 0.55, box.width * maxRatio)
    );
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


def necklace_placements(face: FaceLandmarkResult | None) -> list[dict]:
    """One necklace sits on the neckline — never on the earlobes."""
    if face is None or not face.face_detected:
        return []
    from app.cv.body_geometry import neck_anchor
    from app.cv.necklace_lay import necklace_tip_span

    anchor = neck_anchor(face)
    if anchor is None:
        return []
    return [
        {
            "side": "center",
            "x": anchor.x,
            "y": anchor.y,
            "ear_width": max(necklace_tip_span(float(anchor.ear_width)), 0.14),
        }
    ]


def hand_body_placements(
    hand: HandLandmarkResult | None,
    jewelry_type: str,
    *,
    selected_finger: str = "ring",
) -> list[dict]:
    """Place ring/bracelet/bangle from MediaPipe hand landmarks (not face proxies)."""
    jewelry_type = (jewelry_type or "earring").lower()
    if jewelry_type not in {"bracelet", "bangle", "ring"} or hand is None or not hand.hand_detected:
        return []
    from app.cv.body_geometry import body_anchor_for

    anchor, _error = body_anchor_for(
        jewelry_type,
        None,
        "center",
        hand=hand,
        selected_finger=selected_finger,
    )
    if anchor is None:
        return []
    # Wrist pieces need a wider on-screen footprint than earrings.
    min_width = 0.12 if jewelry_type in {"bracelet", "bangle"} else 0.07
    return [
        {
            "side": anchor.side,
            "x": anchor.x,
            "y": anchor.y,
            "ear_width": max(float(anchor.ear_width), min_width),
        }
    ]


def body_placements(
    face: FaceLandmarkResult | None,
    jewelry_type: str,
    detector: EarlobeDetector,
    *,
    hand: HandLandmarkResult | None = None,
    selected_finger: str = "ring",
) -> list[dict]:
    jewelry_type = (jewelry_type or "earring").lower()
    if jewelry_type == "necklace":
        return necklace_placements(face)
    if jewelry_type == "earring":
        return earlobe_placements(face, detector)
    if jewelry_type in {"bracelet", "bangle", "ring"}:
        hand_placements = hand_body_placements(hand, jewelry_type, selected_finger=selected_finger)
        if hand_placements:
            return hand_placements
        from app.cv.body_geometry import body_anchor_for

        anchor, _error = body_anchor_for(jewelry_type, face, "center", hand=hand, selected_finger=selected_finger)
        if anchor is None:
            return []
        min_width = 0.12 if jewelry_type in {"bracelet", "bangle"} else 0.07
        return [
            {
                "side": anchor.side,
                "x": anchor.x,
                "y": anchor.y,
                "ear_width": max(float(anchor.ear_width), min_width),
            }
        ]
    return earlobe_placements(face, detector)


class LiveJewelryOverlay:
    def __init__(
        self,
        browser,
        output_dir: Path,
        settings: Settings | None = None,
        jewelry_type: str = "earring",
    ) -> None:
        self.browser = browser
        self.output_dir = output_dir
        self.settings = settings or get_settings()
        self.jewelry_type = jewelry_type or "earring"
        self.shown = False
        self._detector = EarlobeDetector(self.settings.min_ear_width)
        self._landmarker: MediaPipeFaceLandmarker | None = None
        self._hand_landmarker: MediaPipeHandLandmarker | None = None
        self._unavailable = False
        self._hand_unavailable = False
        self._sprite_url: str | None = None
        self._sprite_stamp: int | None = None
        self._layout: dict | None = None
        self._last_placements: list[dict] = []
        self.selected_finger = "ring"

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
        if self._hand_landmarker is not None:
            self._hand_landmarker.close()
            self._hand_landmarker = None

    def placements_for(self, frame_path: Path) -> list[dict]:
        image = bgr_to_rgb(read_bgr(frame_path))
        face = None
        landmarker = self._face_landmarker()
        if landmarker is not None:
            try:
                face = landmarker.detect(image)
            except Exception:
                face = None
        hand = None
        if self.jewelry_type in {"bracelet", "bangle", "ring"}:
            hand_landmarker = self._hand_detector()
            if hand_landmarker is not None:
                try:
                    hand = hand_landmarker.detect(image)
                except Exception:
                    hand = None
        return body_placements(
            face,
            self.jewelry_type,
            self._detector,
            hand=hand,
            selected_finger=self.selected_finger,
        )

    async def clear(self) -> None:
        """Remove any QA sprite overlay so the try-on AR is the only jewelry on screen."""
        self.shown = False
        self._last_placements = []
        try:
            await self.browser.evaluate(
                """() => {
                  const root = document.getElementById("qa-live-jewelry");
                  if (root) root.remove();
                  return true;
                }"""
            )
        except Exception:
            pass

    async def update(self, frame_path: Path) -> bool:
        """QA never paints jewelry on the live try-on when AR already shows it.

        Painting a catalog sprite on top caused a second, oversized earring/necklace.
        """
        del frame_path
        await self.clear()
        return False

    async def force_place(self, frame_path: Path) -> bool:
        """Place the catalog sprite on the body when AR stays on Loading jewelry."""
        return await self._update(frame_path, force=True)

    async def _update(self, frame_path: Path, *, force: bool = False) -> bool:
        jewelry_type = (self.jewelry_type or "earring").lower()
        # Only paint when forced (AR stuck loading). Otherwise AR is the single jewelry source.
        if not force:
            await self.clear()
            return False
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
        layout = dict(self._layout or {})
        hang = bool(layout.get("hang", True))
        width_ratio = float(layout.get("width_ratio", 1))
        max_width_ratio = 0.08
        if jewelry_type == "necklace":
            from app.cv.necklace_lay import necklace_overlay_width_ratio

            hang = False
            width_ratio = necklace_overlay_width_ratio()
            max_width_ratio = 0.70
        elif jewelry_type in {"bracelet", "bangle"}:
            hang = False
            width_ratio = max(width_ratio, 1.45)
            max_width_ratio = 0.22
        elif jewelry_type == "ring":
            hang = False
            width_ratio = max(width_ratio, 0.9)
            max_width_ratio = 0.12
        await self.browser.evaluate(
            OVERLAY_SCRIPT,
            {
                "box": box,
                "items": placements,
                "sprite": sprite or "",
                "aspect": float(layout.get("aspect", 1)),
                "hang": hang,
                "widthRatio": width_ratio,
                "maxWidthRatio": max_width_ratio,
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

    def _hand_detector(self) -> MediaPipeHandLandmarker | None:
        if self._hand_unavailable:
            return None
        if self._hand_landmarker is None:
            try:
                self._hand_landmarker = MediaPipeHandLandmarker(self.settings.resolved_hand_model_path)
            except HandLandmarkError:
                self._hand_unavailable = True
                return None
        return self._hand_landmarker


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
