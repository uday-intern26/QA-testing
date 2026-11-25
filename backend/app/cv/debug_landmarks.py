"""Maps each jewelry category to the landmark it is attached to.

These are the same indices the production anchor estimators use, re-exported so
the debug view highlights the landmark that actually drives placement.
"""

from __future__ import annotations

from app.cv.body_geometry import CHIN, FINGER_KEYPOINTS
from app.cv.ear_geometry import CONTOURS, LOBE_LANDMARK
from app.cv.hand_landmarks import WRIST


def selected_landmark_index(jewelry_type: str, side: str, selected_finger: str = "ring") -> int | None:
    """Index of the landmark the attachment point is computed from.

    Face-mesh index for earrings and necklaces, hand index for wrist and finger
    categories. Returns None when the category has no single driving landmark.
    """
    kind = (jewelry_type or "earring").lower()
    if kind == "earring":
        return LOBE_LANDMARK.get(side)
    if kind == "necklace":
        return CHIN
    if kind in {"bracelet", "bangle"}:
        return WRIST
    if kind == "ring":
        keypoints = FINGER_KEYPOINTS.get((selected_finger or "ring").lower())
        return keypoints[0] if keypoints else None
    return None


def contour_indices(jewelry_type: str, side: str) -> tuple[int, ...] | None:
    """Face-mesh contour to outline for this category, when one applies."""
    if (jewelry_type or "earring").lower() != "earring":
        return None
    return CONTOURS.get(side)


def uses_hand_landmarks(jewelry_type: str) -> bool:
    return (jewelry_type or "earring").lower() in {"ring", "bracelet", "bangle"}
