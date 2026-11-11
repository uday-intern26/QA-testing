"""Earring attachment-anchor detection.

Preferred source: AIJewel debug state (Unity projection or browser bridge).
Fallback: template match against the reference, then a local contrast blob.
The attachment point is the point closest to the earlobe, not the blob center.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import cv2
import numpy as np

from app.cv.types import EarlobeAnchor, EarringAnchor, ReferenceVector


class EarringAnchorDetector(ABC):
    @abstractmethod
    def detect(
        self,
        frame_bgr: np.ndarray,
        earlobe: EarlobeAnchor | None,
        *,
        side: str,
        reference: ReferenceVector | None = None,
        reference_bgr: np.ndarray | None = None,
    ) -> EarringAnchor:
        raise NotImplementedError


class DebugStateEarringDetector:
    """Parses the preferred try-on debug payload. This is not a pixel guess."""

    def detect_from_state(self, state: dict | None, side: str) -> EarringAnchor | None:
        if not state:
            return None
        jewelry_id = state.get("jewelry_id") or state.get("jewelryId")
        block = _side_block(state, side)
        if not block:
            return None
        visible = bool(block.get("visible", True))
        x = _first_float(block, ("x", "anchor_x", "anchorX"))
        y = _first_float(block, ("y", "anchor_y", "anchorY"))
        if x is None or y is None:
            return EarringAnchor(
                side=side,
                visible=False,
                source="debug",
                jewelry_id=jewelry_id,
                reason="Debug anchor payload did not include normalized coordinates.",
            )
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            return EarringAnchor(
                side=side,
                visible=False,
                source="debug",
                jewelry_id=jewelry_id,
                reason="Debug anchor coordinates were outside the 0..1 viewport range.",
            )
        return EarringAnchor(
            side=side,
            x=x,
            y=y,
            confidence=0.99 if visible else 0.0,
            visible=visible,
            source="debug",
            rotation=_first_float(block, ("rotation",)),
            scale=_first_float(block, ("scale",)),
            jewelry_id=jewelry_id,
            reason=None if visible else "Debug anchor reports the earring as not visible.",
        )


class FallbackEarringAnchorDetector(EarringAnchorDetector):
    def detect(
        self,
        frame_bgr: np.ndarray,
        earlobe: EarlobeAnchor | None,
        *,
        side: str,
        reference: ReferenceVector | None = None,
        reference_bgr: np.ndarray | None = None,
    ) -> EarringAnchor:
        if earlobe is None:
            return EarringAnchor(
                side=side,
                source="missing",
                reason="Fallback earring detection needs an earlobe anchor.",
            )
        if reference is not None and reference_bgr is not None:
            matched = self._template_attachment(frame_bgr, earlobe, reference, reference_bgr, side)
            if matched is not None:
                return matched
        if side == "center" or earlobe.side == "center":
            blob = self._necklace_blob_attachment(frame_bgr, earlobe, side="center")
        else:
            blob = self._blob_attachment(frame_bgr, earlobe, side)
        if blob is not None:
            return blob
        return EarringAnchor(
            side=side,
            source="missing",
            reason=(
                "Earring attachment anchor was not available from the debug interface "
                "and the fallback detector could not find it."
            ),
        )

    def _template_attachment(
        self,
        frame_bgr: np.ndarray,
        earlobe: EarlobeAnchor,
        reference: ReferenceVector,
        reference_bgr: np.ndarray,
        side: str,
    ) -> EarringAnchor | None:
        ref_h, ref_w = reference_bgr.shape[:2]
        cx = int(reference.earring_x * ref_w)
        cy = int(reference.earring_y * ref_h)
        box = max(12, int(max(reference.ear_width * ref_w, reference.ear_height * ref_h)))
        x0 = max(0, cx - box)
        y0 = max(0, cy - box)
        x1 = min(ref_w, cx + box)
        y1 = min(ref_h, cy + box)
        template = reference_bgr[y0:y1, x0:x1]
        if template.size == 0 or template.shape[0] < 8 or template.shape[1] < 8:
            return None
        frame_h, frame_w = frame_bgr.shape[:2]
        search = int(max(box * 3, earlobe.ear_width * frame_w * 4))
        ax = int(earlobe.x * frame_w)
        ay = int(earlobe.y * frame_h)
        sx0 = max(0, ax - search)
        sy0 = max(0, ay - search)
        sx1 = min(frame_w, ax + search)
        sy1 = min(frame_h, ay + search)
        window = frame_bgr[sy0:sy1, sx0:sx1]
        if window.shape[0] < template.shape[0] or window.shape[1] < template.shape[1]:
            return None
        result = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, top_left = cv2.minMaxLoc(result)
        if score < 0.45:
            return None
        attach_x = sx0 + top_left[0] + (cx - x0)
        attach_y = sy0 + top_left[1] + (cy - y0)
        return EarringAnchor(
            side=side,
            x=float(attach_x / frame_w),
            y=float(attach_y / frame_h),
            confidence=float(max(0.5, min(0.9, score))),
            visible=True,
            source="template",
            reason=None,
        )

    def _blob_attachment(
        self,
        frame_bgr: np.ndarray,
        earlobe: EarlobeAnchor,
        side: str,
    ) -> EarringAnchor | None:
        height, width = frame_bgr.shape[:2]
        ax = int(earlobe.x * width)
        ay = int(earlobe.y * height)
        ear_px = max(8.0, earlobe.ear_width * width)
        radius = int(max(10, ear_px * 1.25))
        x0 = max(0, ax - radius)
        y0 = max(0, ay - int(radius * 0.85))
        x1 = min(width, ax + radius)
        y1 = min(height, ay + int(radius * 1.15))
        crop = frame_bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2].astype(np.int16)
        local = cv2.blur(value, (11, 11))
        # A stud is a local bright peak. A hoop is a gold region in the same window.
        peak = np.where((value > local + 22) & (hsv[:, :, 1] > 35), 255, 0).astype(np.uint8)
        gold = cv2.inRange(hsv, (5, 50, 60), (40, 255, 255))
        earlobe_local = np.array([ax - x0, ay - y0], dtype=float)
        peak_hit = self._nearest_contour(peak, earlobe_local, ear_px, min_area=3, max_scale=1.6)
        gold_hit = self._nearest_contour(gold, earlobe_local, ear_px, min_area=8, max_scale=3.0)
        best = None
        best_distance = 1e9
        if peak_hit is not None and peak_hit[0] <= ear_px * 0.25:
            best_distance, best = peak_hit
        elif gold_hit is not None:
            best_distance, best = gold_hit
        elif peak_hit is not None:
            best_distance, best = peak_hit
        if best is None or best_distance > ear_px * 1.1:
            return None
        return EarringAnchor(
            side=side,
            x=float((x0 + best[0]) / width),
            y=float((y0 + best[1]) / height),
            confidence=0.62,
            visible=True,
            source="blob",
        )

    def _necklace_blob_attachment(
        self,
        frame_bgr: np.ndarray,
        neck: EarlobeAnchor,
        side: str = "center",
    ) -> EarringAnchor | None:
        """Search a neckline band for gold/bright jewelry instead of an earlobe window."""
        height, width = frame_bgr.shape[:2]
        ax = int(neck.x * width)
        ay = int(neck.y * height)
        neck_px = max(16.0, neck.ear_width * width)
        x0 = max(0, ax - int(neck_px * 2.4))
        x1 = min(width, ax + int(neck_px * 2.4))
        y0 = max(0, ay - int(neck_px * 0.55))
        y1 = min(height, ay + int(neck_px * 1.8))
        crop = frame_bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2].astype(np.int16)
        local = cv2.blur(value, (15, 15))
        peak = np.where((value > local + 18) & (hsv[:, :, 1] > 30), 255, 0).astype(np.uint8)
        gold = cv2.inRange(hsv, (5, 40, 55), (45, 255, 255))
        neck_local = np.array([ax - x0, ay - y0], dtype=float)
        gold_hit = self._nearest_contour(gold, neck_local, neck_px, min_area=12, max_scale=4.5)
        peak_hit = self._nearest_contour(peak, neck_local, neck_px, min_area=6, max_scale=3.5)
        best = None
        best_distance = 1e9
        if gold_hit is not None:
            best_distance, best = gold_hit
        elif peak_hit is not None:
            best_distance, best = peak_hit
        if best is None or best_distance > neck_px * 2.2:
            return None
        return EarringAnchor(
            side=side,
            x=float((x0 + best[0]) / width),
            y=float((y0 + best[1]) / height),
            confidence=0.72,
            visible=True,
            source="blob",
        )

    @staticmethod
    def _nearest_contour(
        mask: np.ndarray,
        earlobe_local: np.ndarray,
        ear_px: float,
        *,
        min_area: float,
        max_scale: float,
    ) -> tuple[float, np.ndarray] | None:
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_area = (ear_px * max_scale) ** 2
        best = None
        best_distance = 1e9
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            points = contour.reshape(-1, 2).astype(float)
            distances = np.hypot(points[:, 0] - earlobe_local[0], points[:, 1] - earlobe_local[1])
            nearest_index = int(np.argmin(distances))
            nearest = float(distances[nearest_index])
            if nearest < best_distance:
                best_distance = nearest
                best = points[nearest_index]
        if best is None:
            return None
        return best_distance, best


def _side_block(state: dict, side: str) -> dict | None:
    keys = {
        "left": ("left", "left_earring", "leftEarring"),
        "right": ("right", "right_earring", "rightEarring"),
        "center": ("center", "necklace", "pendant", "middle", "neck"),
    }.get(side, (side,))
    for key in keys:
        value = state.get(key)
        if isinstance(value, dict):
            return value
    return None


def _first_float(block: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in block and block[key] is not None:
            try:
                return float(block[key])
            except (TypeError, ValueError):
                return None
    return None
