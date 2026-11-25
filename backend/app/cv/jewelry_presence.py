"""Decide whether a captured frame shows the jewelry on the body.

Storefront AR often draws the piece without publishing an attachment point.
A bare frame must not be shown as a result.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.adapters.earring_anchor_adapter import state_has_attachment


def frame_wears_jewelry(
    image_bgr: np.ndarray | None,
    jewelry_type: str,
    debug_state: dict | None = None,
) -> bool:
    """True when the try-on published an attachment or the piece is visible on the body."""
    state = debug_state if isinstance(debug_state, dict) else None
    if state_has_attachment(state):
        return True
    # Cross-origin storefront AR draws the piece but does not publish an attachment.
    # Those frames are worn; dropping them leaves Layer 1 with too few samples.
    if state and state.get("anchor_source") == "storefront_ar" and str(state.get("qa_status") or "") == "ready":
        return True
    if image_bgr is None or image_bgr.size == 0:
        return False
    return jewelry_visible_in_image(image_bgr, jewelry_type)


def keep_capture_frame(
    image_bgr: np.ndarray | None,
    jewelry_type: str,
    *,
    storefront_ar: bool = False,
    jewelry_confirmed: bool = False,
) -> bool:
    """Whether this screenshot is worth keeping for Layer 1.

    After the jewel is already laid on the video, keep any frame that still
    shows the body. A tiny bracelet / thin necklace must not wipe out Layer 1.
    Blank shots stay rejected.
    """
    if image_bgr is None or image_bgr.size == 0:
        return False
    if jewelry_visible_in_image(image_bgr, jewelry_type):
        return True
    if (storefront_ar or jewelry_confirmed) and subject_visible(image_bgr):
        return True
    return False


def subject_visible(image_bgr: np.ndarray) -> bool:
    """True when a body is in frame, even if the jewelry itself is only a few pixels."""
    height, width = image_bgr.shape[:2]
    if height < 20 or width < 20:
        return False
    roi = _crop(image_bgr, 0.02, 0.98, 0.08, 0.95)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    if edges.size == 0:
        return False
    density = float((edges > 0).mean())
    span = float((edges > 0).any(axis=0).mean())
    # A limb on a plain backdrop has a wide, sparse outline. A blank shot does not.
    return span >= 0.35 and density >= 0.004


def jewelry_visible_in_image(image_bgr: np.ndarray, jewelry_type: str) -> bool:
    """True when the body region for this jewelry contains a worn piece, not bare skin or cloth."""
    height, width = image_bgr.shape[:2]
    if height < 20 or width < 20:
        return False
    kind = (jewelry_type or "earring").lower()
    if kind == "necklace":
        # Stay on the shirt, not the beige background at the sides.
        # A worn necklace is a horizontal band whose color differs from the cloth.
        return any(
            _necklace_band(_crop(image_bgr, 0.36, 0.64, top, bottom))
            for top, bottom in ((0.42, 0.62), (0.48, 0.70), (0.54, 0.78))
        )
    if kind == "earring":
        left = _crop(image_bgr, 0.08, 0.32, 0.22, 0.62)
        right = _crop(image_bgr, 0.68, 0.92, 0.22, 0.62)
        return _worn_band(left, min_density=0.06, min_span=0.12) or _worn_band(
            right, min_density=0.06, min_span=0.12
        )
    # Ring, bracelet, and bangle follow the hand. A rotated wrist is often
    # above the lower half, so search the whole try-on view.
    return any(
        _worn_band(_crop(image_bgr, x0, x1, y0, y1), min_density=0.05, min_span=0.12)
        for x0, x1, y0, y1 in (
            (0.04, 0.96, 0.10, 0.52),
            (0.04, 0.96, 0.28, 0.78),
            (0.10, 0.90, 0.45, 0.96),
        )
    )


def _crop(image: np.ndarray, x0: float, x1: float, y0: float, y1: float) -> np.ndarray:
    height, width = image.shape[:2]
    left = max(0, min(width - 1, int(width * x0)))
    right = max(left + 1, min(width, int(width * x1)))
    top = max(0, min(height - 1, int(height * y0)))
    bottom = max(top + 1, min(height, int(height * y1)))
    return image[top:bottom, left:right]


def _necklace_band(roi: np.ndarray) -> bool:
    """True when a horizontal run of pixels differs from the shirt color."""
    if roi.size == 0 or roi.shape[0] < 8 or roi.shape[1] < 8:
        return False
    flat = roi.reshape(-1, 3).astype(np.int16)
    median = np.median(flat, axis=0)
    distance = np.linalg.norm(roi.astype(np.int16) - median, axis=2)
    mask = distance > 48
    span = float(mask.any(axis=0).mean())
    row_density = mask.mean(axis=1)
    window = max(3, int(round(roi.shape[0] * 0.12)))
    if row_density.size < window:
        row_frac = float(row_density.max()) if row_density.size else 0.0
    else:
        kernel = np.ones(window, dtype=np.float32) / window
        row_frac = float(np.convolve(row_density, kernel, mode="valid").max())
    return span >= 0.42 and row_frac >= 0.45


def _worn_band(roi: np.ndarray, *, min_density: float, min_span: float) -> bool:
    """Jewelry adds edges and colors that bare skin or a plain shirt do not span."""
    if roi.size == 0:
        return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 140)
    density = float((edges > 0).mean())
    columns = (edges > 0).any(axis=0)
    span = float(columns.mean()) if columns.size else 0.0
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    # Skin and the plain orange shirt sit in a narrow hue band. Beads and metal do not.
    colorful = ((hue < 4) | (hue > 30)) & (sat > 45)
    color_span = float(colorful.any(axis=0).mean()) if colorful.size else 0.0
    return (density >= min_density and span >= min_span) or color_span >= min_span
