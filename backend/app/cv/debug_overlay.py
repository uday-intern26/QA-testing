"""Debug-mode visualization layer.

This renderer only reads geometry that the tracking and placement pipelines
already produced; it never writes back into them. It draws on a copy of the
frame, so the normal annotated output is untouched.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.cv.debug_config import CategoryDebugProfile
from app.cv.landmark_validation import FrameValidation
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, HandLandmarkResult

# Distinct marker colors so each point type is identifiable (BGR).
MESH_COLOR = (90, 90, 90)
MESH_INDEX_COLOR = (170, 170, 170)
SELECTED_LANDMARK_COLOR = (0, 215, 255)
EXPECTED_COLOR = (0, 255, 0)
ACTUAL_COLOR = (0, 0, 255)
ANCHOR_COLOR = (255, 160, 0)
DEVIATION_COLOR = (255, 0, 255)
PANEL_BG = (24, 24, 24)
TEXT_COLOR = (240, 240, 240)

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _point(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    return (int(round(x * width)), int(round(y * height)))


def _draw_cross(canvas: np.ndarray, center: tuple[int, int], color, size: int = 8, thickness: int = 2) -> None:
    x, y = center
    cv2.line(canvas, (x - size, y - size), (x + size, y + size), color, thickness)
    cv2.line(canvas, (x - size, y + size), (x + size, y - size), color, thickness)


def _draw_square(canvas: np.ndarray, center: tuple[int, int], color, size: int = 7, thickness: int = 2) -> None:
    x, y = center
    cv2.rectangle(canvas, (x - size, y - size), (x + size, y + size), color, thickness)


def _draw_diamond(canvas: np.ndarray, center: tuple[int, int], color, size: int = 8, thickness: int = 2) -> None:
    x, y = center
    points = np.array([[x, y - size], [x + size, y], [x, y + size], [x - size, y]], dtype=np.int32)
    cv2.polylines(canvas, [points], True, color, thickness)


def _draw_face_mesh(
    canvas: np.ndarray,
    face: FaceLandmarkResult,
    profile: CategoryDebugProfile,
    contour_indices: tuple[int, ...] | None,
) -> None:
    height, width = canvas.shape[:2]
    display = profile.display
    for index, landmark in enumerate(face.landmarks):
        center = _point(landmark.x, landmark.y, width, height)
        cv2.circle(canvas, center, 1, MESH_COLOR, -1)
        if display.show_landmark_numbers and index % max(1, display.landmark_number_step) == 0:
            cv2.putText(canvas, str(index), (center[0] + 2, center[1] - 2), _FONT, 0.22, MESH_INDEX_COLOR, 1, cv2.LINE_AA)

    if not contour_indices:
        return
    polyline = [
        _point(face.landmarks[index].x, face.landmarks[index].y, width, height)
        for index in contour_indices
        if index < len(face.landmarks)
    ]
    if len(polyline) > 1:
        cv2.polylines(canvas, [np.array(polyline, dtype=np.int32)], False, SELECTED_LANDMARK_COLOR, 1)
    if display.show_landmark_numbers:
        for index in contour_indices:
            if index >= len(face.landmarks):
                continue
            center = _point(face.landmarks[index].x, face.landmarks[index].y, width, height)
            cv2.circle(canvas, center, 2, SELECTED_LANDMARK_COLOR, -1)
            cv2.putText(canvas, str(index), (center[0] + 3, center[1] - 3), _FONT, 0.3, SELECTED_LANDMARK_COLOR, 1, cv2.LINE_AA)


def _draw_hand_mesh(canvas: np.ndarray, hand: HandLandmarkResult, profile: CategoryDebugProfile) -> None:
    height, width = canvas.shape[:2]
    display = profile.display
    for index, landmark in enumerate(hand.landmarks):
        center = _point(landmark.x, landmark.y, width, height)
        cv2.circle(canvas, center, 3, MESH_COLOR, -1)
        if display.show_landmark_numbers:
            cv2.putText(canvas, str(index), (center[0] + 4, center[1] - 4), _FONT, 0.32, MESH_INDEX_COLOR, 1, cv2.LINE_AA)


def _draw_panel(canvas: np.ndarray, lines: list[str]) -> None:
    """Text panel sized so it never covers more than the top-left corner of the frame."""
    if not lines:
        return
    height, width = canvas.shape[:2]
    longest = max(len(line) for line in lines)
    # Fit the widest line into 55% of the frame, within readable bounds.
    scale = min(0.5, max(0.26, (0.55 * width) / (longest * 10.0)))
    pad = max(4, int(6 * scale / 0.4))
    line_height = max(9, int(round(16 * scale / 0.4)))
    box_width = min(width - 8, int(longest * 10.0 * scale) + pad * 2)
    box_height = min(height - 8, line_height * len(lines) + pad * 2)

    overlay = canvas.copy()
    cv2.rectangle(overlay, (4, 4), (4 + box_width, 4 + box_height), PANEL_BG, -1)
    cv2.addWeighted(overlay, 0.72, canvas, 0.28, 0, canvas)
    for row, text in enumerate(lines):
        y = 4 + pad + line_height * (row + 1) - max(2, line_height // 5)
        if y > 4 + box_height:
            break
        cv2.putText(canvas, text, (4 + pad, y), _FONT, scale, TEXT_COLOR, 1, cv2.LINE_AA)


def render_debug_frame(
    image_bgr: np.ndarray,
    *,
    profile: CategoryDebugProfile,
    validation: FrameValidation,
    face: FaceLandmarkResult | None = None,
    hand: HandLandmarkResult | None = None,
    expected: EarlobeAnchor | None = None,
    jewelry: EarringAnchor | None = None,
    contour_indices: tuple[int, ...] | None = None,
    selected_landmark_index: int | None = None,
    selected_landmark_source: str = "face",
) -> np.ndarray:
    """Draw the debug view on a copy of the frame and return it."""
    canvas = image_bgr.copy()
    height, width = canvas.shape[:2]
    display = profile.display

    if display.show_face_mesh:
        if face is not None and face.face_detected and face.landmarks:
            _draw_face_mesh(canvas, face, profile, contour_indices)
        if hand is not None and hand.hand_detected and hand.landmarks:
            _draw_hand_mesh(canvas, hand, profile)

    source = hand if selected_landmark_source == "hand" else face
    if (
        display.highlight_selected_landmark
        and selected_landmark_index is not None
        and source is not None
        and selected_landmark_index < len(source.landmarks)
    ):
        landmark = source.landmarks[selected_landmark_index]
        center = _point(landmark.x, landmark.y, width, height)
        cv2.circle(canvas, center, 10, SELECTED_LANDMARK_COLOR, 2)
        cv2.putText(
            canvas,
            f"#{selected_landmark_index} {profile.body_region}",
            (center[0] + 12, center[1] + 4),
            _FONT,
            0.4,
            SELECTED_LANDMARK_COLOR,
            1,
            cv2.LINE_AA,
        )

    expected_point: tuple[int, int] | None = None
    actual_point: tuple[int, int] | None = None

    if display.show_expected_point and expected is not None:
        expected_point = _point(expected.x, expected.y, width, height)
        _draw_cross(canvas, expected_point, EXPECTED_COLOR)
        cv2.putText(canvas, "expected", (expected_point[0] + 10, expected_point[1] - 8), _FONT, 0.38, EXPECTED_COLOR, 1, cv2.LINE_AA)

    if display.show_actual_point and jewelry is not None and jewelry.x is not None and jewelry.y is not None:
        actual_point = _point(jewelry.x, jewelry.y, width, height)
        _draw_square(canvas, actual_point, ACTUAL_COLOR)
        cv2.putText(canvas, "actual", (actual_point[0] + 10, actual_point[1] + 14), _FONT, 0.38, ACTUAL_COLOR, 1, cv2.LINE_AA)
        if jewelry.local_x is not None and jewelry.local_y is not None:
            _draw_diamond(canvas, actual_point, ANCHOR_COLOR, size=12, thickness=1)

    if display.show_deviation and expected_point and actual_point:
        cv2.line(canvas, expected_point, actual_point, DEVIATION_COLOR, 1, cv2.LINE_AA)
        midpoint = ((expected_point[0] + actual_point[0]) // 2, (expected_point[1] + actual_point[1]) // 2)
        label_bits = []
        if validation.position_error_px is not None:
            label_bits.append(f"{validation.position_error_px:.2f}px")
        if validation.position_error_normalized is not None:
            label_bits.append(f"{validation.position_error_normalized:.3f}n")
        if label_bits:
            cv2.putText(canvas, " / ".join(label_bits), (midpoint[0] + 6, midpoint[1]), _FONT, 0.4, DEVIATION_COLOR, 1, cv2.LINE_AA)

    lines: list[str] = []
    if display.show_frame_validation:
        lines.append(f"DEBUG {profile.label} f{validation.frame_number} [{validation.side}]")
        lines.append(f"status: {validation.status}")
        if validation.failure_reason:
            lines.append(f"reason: {validation.failure_reason}")
        for name, check in validation.checks.items():
            lines.append(f"  {name}: {check.status}")
    if display.show_confidence:
        if validation.landmark_confidence is not None:
            lines.append(f"landmark conf: {validation.landmark_confidence:.2f}")
        if validation.jewelry_confidence is not None:
            lines.append(f"jewelry conf: {validation.jewelry_confidence:.2f}")
    if display.show_deviation and validation.position_error_px is not None:
        lines.append(
            f"deviation: {validation.position_error_px:.2f} px / "
            f"{(validation.position_error_normalized or 0.0):.3f} norm"
        )
    _draw_panel(canvas, lines)
    return canvas
