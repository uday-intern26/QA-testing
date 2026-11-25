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
        local_x = _first_float(block, ("local_x", "localX", "offset_x", "offsetX"))
        local_y = _first_float(block, ("local_y", "localY", "offset_y", "offsetY"))
        local_z = _first_float(block, ("local_z", "localZ", "offset_z", "offsetZ"))
        # Some try-on builds publish local worn offsets as x/y outside 0..1 (not pixel coords).
        looks_like_local = (
            (not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0)
            and abs(x) <= 50.0
            and abs(y) <= 50.0
        )
        if looks_like_local and local_x is None and local_y is None:
            local_x, local_y = x, y
            local_z = local_z if local_z is not None else _first_float(block, ("z",))
            return EarringAnchor(
                side=side,
                visible=visible,
                source="debug",
                jewelry_id=jewelry_id,
                confidence=0.99 if visible else 0.0,
                local_x=local_x,
                local_y=local_y,
                local_z=local_z,
                rotation=_first_float(block, ("rotation",)),
                scale=_first_float(block, ("scale",)),
                reason=(
                    None
                    if visible
                    else "Debug anchor reports the earring as not visible."
                ),
            )
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            return EarringAnchor(
                side=side,
                visible=False,
                source="debug",
                jewelry_id=jewelry_id,
                reason="Debug anchor coordinates were outside the 0..1 viewport range.",
            )
        source = str(block.get("source") or "debug")
        confidence = _first_float(block, ("confidence", "score"))
        if confidence is None:
            confidence = 0.99 if visible else 0.0
        return EarringAnchor(
            side=side,
            x=x,
            y=y,
            confidence=float(confidence if visible else 0.0),
            visible=visible,
            source=source,
            rotation=_first_float(block, ("rotation",)),
            scale=_first_float(block, ("scale",)),
            jewelry_id=jewelry_id,
            local_x=local_x,
            local_y=local_y,
            local_z=local_z,
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
        radius = int(max(10, ear_px * 1.35))
        # Search mostly at/below the piercing so hanging jhumkas win over helix highlights.
        # Keep the window on the outer ear side (away from nose) so cheek gold is ignored.
        outward = -1.0 if ax < width * 0.5 else 1.0
        # Bias outward, but keep enough inward span for a hanging jhumka near the cheek.
        if outward < 0:
            x0 = max(0, ax - radius)
            x1 = min(width, ax + int(radius * 0.9))
        else:
            x0 = max(0, ax - int(radius * 0.9))
            x1 = min(width, ax + radius)
        y0 = max(0, ay - int(radius * 0.5))
        y1 = min(height, ay + int(radius * 1.8))
        crop = frame_bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Bare ears have bright lobe peaks — require gold jewelry evidence to accept a blob.
        gold = cv2.inRange(hsv, (5, 50, 60), (40, 255, 255))
        earlobe_local = np.array([ax - x0, ay - y0], dtype=float)
        gold_hit = self._piercing_attachment(
            gold, earlobe_local, ear_px, min_area=10, max_scale=3.5, outward_sign=outward
        )
        if gold_hit is None or gold_hit[0] > ear_px * 1.15:
            return None
        best_distance, best = gold_hit
        gold_area = int(cv2.countNonZero(gold))
        if gold_area < max(18, int(ear_px * 0.35)):
            return None
        return EarringAnchor(
            side=side,
            x=float((x0 + best[0]) / width),
            y=float((y0 + best[1]) / height),
            confidence=0.72,
            visible=True,
            source="blob",
            reason="Fallback gold blob near the piercing (not pass-tracking verified).",
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

    @staticmethod
    def _piercing_attachment(
        mask: np.ndarray,
        earlobe_local: np.ndarray,
        ear_px: float,
        *,
        min_area: float,
        max_scale: float,
        outward_sign: float = 0.0,
    ) -> tuple[float, np.ndarray] | None:
        """Pick the jewelry attachment near the piercing, not helix / cheek highlights.

        For hanging pieces, prefer the top of a gold blob that reaches the lobe band.
        Points far above the lobe or drifting inward across the cheek are penalized.
        """
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        max_area = (ear_px * max_scale) ** 2
        lobe_x, lobe_y = float(earlobe_local[0]), float(earlobe_local[1])
        best_point = None
        best_score = 1e9
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            points = contour.reshape(-1, 2).astype(float)
            ys = points[:, 1]
            min_y = float(ys.min())
            max_y = float(ys.max())
            # Ignore tiny specular dots that sit only above the piercing.
            crosses_lobe = min_y <= lobe_y + 0.2 * ear_px and max_y >= lobe_y - 0.25 * ear_px
            top_idx = int(np.argmin(ys))
            top = points[top_idx]
            band = points[(ys >= lobe_y - 0.4 * ear_px) & (ys <= lobe_y + 1.3 * ear_px)]
            if band.size:
                band_dist = np.hypot(band[:, 0] - lobe_x, band[:, 1] - lobe_y)
                candidate = band[int(np.argmin(band_dist))]
            elif crosses_lobe:
                candidate = np.array([top[0], max(top[1], lobe_y - 0.12 * ear_px)], dtype=float)
            else:
                distances = np.hypot(points[:, 0] - lobe_x, points[:, 1] - lobe_y)
                candidate = points[int(np.argmin(distances))]
                if candidate[1] < lobe_y - 0.55 * ear_px:
                    continue
            dx = float(candidate[0] - lobe_x)
            dy = float(candidate[1] - lobe_y)
            # Reject extreme cheek drift, but allow slight inward hang.
            if outward_sign != 0.0 and (-outward_sign * dx) > 0.85 * ear_px:
                continue
            upward_penalty = 2.8 * max(0.0, -dy)
            inward_penalty = 1.2 * max(0.0, -outward_sign * dx) if outward_sign != 0.0 else 0.0
            hang_relief = 0.45 * min(max(dy, 0.0), 1.4 * ear_px)
            size_bonus = 0.12 * ear_px * min(1.0, area / max(1.0, ear_px * ear_px))
            score = float(np.hypot(dx, dy) + upward_penalty + inward_penalty - hang_relief - size_bonus)
            if not crosses_lobe:
                score += 0.55 * ear_px
            if score < best_score:
                best_score = score
                best_point = candidate
        if best_point is None:
            return None
        # Snap attachment up to the piercing when the chosen blob hangs below it.
        attach = best_point.copy()
        if attach[1] > lobe_y + 0.15 * ear_px:
            attach[1] = lobe_y + 0.05 * ear_px
        distance = float(np.hypot(attach[0] - lobe_x, attach[1] - lobe_y))
        return distance, attach


def _side_block(state: dict, side: str) -> dict | None:
    keys = {
        "left": (
            "left",
            "left_earring",
            "leftEarring",
            "left_ring",
            "leftRing",
            "ring",
            "ring_left",
        ),
        "right": (
            "right",
            "right_earring",
            "rightEarring",
            "right_ring",
            "rightRing",
            "ring_right",
        ),
        "center": (
            "center",
            "necklace",
            "pendant",
            "middle",
            "neck",
            "ring",
            "bracelet",
            "bangle",
        ),
    }.get(side, (side,))
    for key in keys:
        value = state.get(key)
        if isinstance(value, dict):
            return value
    # Top-level ring / jewelry attachment payloads without a side wrapper.
    if side in {"left", "right", "center"}:
        for key in ("ring", "rings", "jewelry", "attachment"):
            value = state.get(key)
            if isinstance(value, dict):
                nested_side = str(value.get("side") or "").lower()
                if not nested_side or nested_side == side or side == "center":
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
