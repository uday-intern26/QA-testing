"""Per-jewelry-category detection and frame-selection rules."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JewelryCategoryProfile:
    jewelry_type: str
    label: str
    required_body_parts: tuple[str, ...]
    body_region: str
    requires_face: bool
    requires_ears: bool
    requires_neck: bool
    requires_hand: bool
    requires_wrist: bool
    requires_fingers: bool
    # Hard reject reasons for this category (beyond blur).
    hard_reject_reasons: frozenset[str] = field(default_factory=frozenset)
    soft_reject_reasons: frozenset[str] = field(
        default_factory=lambda: frozenset({"near_duplicate", "head_pose_unstable"})
    )


PROFILES: dict[str, JewelryCategoryProfile] = {
    "earring": JewelryCategoryProfile(
        jewelry_type="earring",
        label="Earring",
        required_body_parts=("face", "ear", "earlobe"),
        body_region="ear",
        requires_face=True,
        requires_ears=True,
        requires_neck=False,
        requires_hand=False,
        requires_wrist=False,
        requires_fingers=False,
        hard_reject_reasons=frozenset(
            {"face_not_detected", "ear_not_visible", "face_occluded", "excessive_blur", "low_landmark_confidence"}
        ),
        soft_reject_reasons=frozenset({"near_duplicate", "head_pose_unstable"}),
    ),
    "necklace": JewelryCategoryProfile(
        jewelry_type="necklace",
        label="Necklace",
        required_body_parts=("face", "neck", "upper_chest"),
        body_region="neck",
        requires_face=True,
        requires_ears=False,
        requires_neck=True,
        requires_hand=False,
        requires_wrist=False,
        requires_fingers=False,
        hard_reject_reasons=frozenset(
            {"face_not_detected", "neck_not_visible", "face_occluded", "excessive_blur", "low_landmark_confidence"}
        ),
        soft_reject_reasons=frozenset({"near_duplicate", "head_pose_unstable", "ear_not_visible"}),
    ),
    "ring": JewelryCategoryProfile(
        jewelry_type="ring",
        label="Ring",
        required_body_parts=("hand", "fingers"),
        body_region="finger",
        requires_face=False,
        requires_ears=False,
        requires_neck=False,
        requires_hand=True,
        requires_wrist=False,
        requires_fingers=True,
        hard_reject_reasons=frozenset(
            {
                "hand_not_detected",
                "fingers_not_visible",
                "excessive_blur",
                "low_landmark_confidence",
                "jewelry_not_loaded",
            }
        ),
        soft_reject_reasons=frozenset(
            {
                "near_duplicate",
                "head_pose_unstable",
                "face_not_detected",
                "ear_not_visible",
                "face_occluded",
                "neck_not_visible",
            }
        ),
    ),
    "bracelet": JewelryCategoryProfile(
        jewelry_type="bracelet",
        label="Bracelet",
        required_body_parts=("hand", "wrist"),
        body_region="wrist",
        requires_face=False,
        requires_ears=False,
        requires_neck=False,
        requires_hand=True,
        requires_wrist=True,
        requires_fingers=False,
        hard_reject_reasons=frozenset(
            {
                "hand_not_detected",
                "wrist_not_visible",
                "excessive_blur",
                "low_landmark_confidence",
                "jewelry_not_loaded",
            }
        ),
        soft_reject_reasons=frozenset(
            {
                "near_duplicate",
                "head_pose_unstable",
                "face_not_detected",
                "ear_not_visible",
                "face_occluded",
                "neck_not_visible",
                "fingers_not_visible",
            }
        ),
    ),
    "bangle": JewelryCategoryProfile(
        jewelry_type="bangle",
        label="Bangle",
        required_body_parts=("hand", "wrist"),
        body_region="wrist",
        requires_face=False,
        requires_ears=False,
        requires_neck=False,
        requires_hand=True,
        requires_wrist=True,
        requires_fingers=False,
        hard_reject_reasons=frozenset(
            {
                "hand_not_detected",
                "wrist_not_visible",
                "excessive_blur",
                "low_landmark_confidence",
                "jewelry_not_loaded",
            }
        ),
        soft_reject_reasons=frozenset(
            {
                "near_duplicate",
                "head_pose_unstable",
                "face_not_detected",
                "ear_not_visible",
                "face_occluded",
                "neck_not_visible",
                "fingers_not_visible",
            }
        ),
    ),
}


def profile_for(jewelry_type: str | None) -> JewelryCategoryProfile:
    key = (jewelry_type or "earring").lower().strip()
    return PROFILES.get(key, PROFILES["earring"])
