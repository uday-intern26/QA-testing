"""Per-category debug visualization and landmark-validation tolerances.

Tolerances live here so the validation engine stays jewelry-agnostic: it reads a
profile instead of branching on the jewelry type.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class DebugDisplayOptions:
    """What the debug renderer draws. All default to the documented debug view."""

    show_face_mesh: bool = True
    show_landmark_numbers: bool = True
    highlight_selected_landmark: bool = True
    show_expected_point: bool = True
    show_actual_point: bool = True
    show_deviation: bool = True
    show_confidence: bool = True
    show_frame_validation: bool = True
    landmark_number_step: int = 12


@dataclass(frozen=True)
class ValidationTolerances:
    """Deterministic pass bands.

    `position_tolerance_normalized` is a distance in normalized image space (0..1),
    the same space as the project's Euclidean pass bands in `tryon_placement_rules`.
    It is not a multiple of the body-part width. `position_tolerance_px` is optional
    because a pixel budget only means something at a known capture resolution; when
    it is None the normalized band decides on its own.
    """

    position_tolerance_px: float | None = None
    position_tolerance_normalized: float = 0.05
    # Rotation in degrees against the expected hang/orientation.
    rotation_tolerance_deg: float = 15.0
    # Scale as a multiple of the expected jewelry size.
    scale_min_ratio: float = 0.6
    scale_max_ratio: float = 1.6
    # Landmark gates.
    minimum_landmark_confidence: float = 0.5
    # Temporal gates.
    minimum_valid_frame_percentage: float = 90.0
    max_consecutive_tracking_failures: int = 2
    minimum_stable_frames: int = 3
    max_interframe_jump_normalized: float = 0.25


@dataclass(frozen=True)
class CategoryDebugProfile:
    jewelry_type: str
    label: str
    body_region: str
    # Landmark indices that must exist for this category, resolved at runtime.
    tolerances: ValidationTolerances = field(default_factory=ValidationTolerances)
    display: DebugDisplayOptions = field(default_factory=DebugDisplayOptions)

    def as_dict(self) -> dict:
        return {
            "jewelry_type": self.jewelry_type,
            "label": self.label,
            "body_region": self.body_region,
            "tolerances": asdict(self.tolerances),
            "display": asdict(self.display),
        }


DEBUG_PROFILES: dict[str, CategoryDebugProfile] = {
    "earring": CategoryDebugProfile(
        jewelry_type="earring",
        label="Earring",
        body_region="earlobe",
        tolerances=ValidationTolerances(
            # Matches EUCLIDEAN_WARNING in app/cv/tryon_placement_rules.py.
            position_tolerance_normalized=0.05,
            rotation_tolerance_deg=15.0,
            scale_min_ratio=0.6,
            scale_max_ratio=1.6,
        ),
    ),
    "necklace": CategoryDebugProfile(
        jewelry_type="necklace",
        label="Necklace",
        body_region="neckline",
        tolerances=ValidationTolerances(
            position_tolerance_normalized=0.05,
            rotation_tolerance_deg=20.0,
            scale_min_ratio=0.5,
            scale_max_ratio=1.8,
        ),
    ),
    "ring": CategoryDebugProfile(
        jewelry_type="ring",
        label="Ring",
        body_region="finger",
        tolerances=ValidationTolerances(
            position_tolerance_normalized=0.04,
            rotation_tolerance_deg=25.0,
            scale_min_ratio=0.5,
            scale_max_ratio=1.7,
        ),
    ),
    "bracelet": CategoryDebugProfile(
        jewelry_type="bracelet",
        label="Bracelet",
        body_region="wrist",
        tolerances=ValidationTolerances(
            position_tolerance_normalized=0.06,
            rotation_tolerance_deg=25.0,
            scale_min_ratio=0.5,
            scale_max_ratio=1.8,
        ),
    ),
    "bangle": CategoryDebugProfile(
        jewelry_type="bangle",
        label="Bangle",
        body_region="wrist",
        tolerances=ValidationTolerances(
            position_tolerance_normalized=0.06,
            rotation_tolerance_deg=25.0,
            scale_min_ratio=0.5,
            scale_max_ratio=1.8,
        ),
    ),
}

_TOLERANCE_FIELDS = set(ValidationTolerances.__dataclass_fields__)
_DISPLAY_FIELDS = set(DebugDisplayOptions.__dataclass_fields__)


def debug_profile_for(jewelry_type: str | None, overrides: dict | None = None) -> CategoryDebugProfile:
    """Return the category profile with optional per-test overrides applied."""
    key = (jewelry_type or "earring").lower().strip()
    profile = DEBUG_PROFILES.get(key, DEBUG_PROFILES["earring"])
    if not overrides:
        return profile

    nested_tolerances = overrides.get("tolerances") if isinstance(overrides.get("tolerances"), dict) else {}
    nested_display = overrides.get("display") if isinstance(overrides.get("display"), dict) else {}

    _INT_FIELDS = {"max_consecutive_tracking_failures", "minimum_stable_frames"}
    tolerance_updates: dict = {}
    display_updates: dict = {}
    for source in (overrides, nested_tolerances):
        for name, value in (source or {}).items():
            if name not in _TOLERANCE_FIELDS:
                continue
            if value is None or value == "":
                # Only the optional pixel budget can be cleared back to "unset".
                if name == "position_tolerance_px":
                    tolerance_updates[name] = None
                continue
            tolerance_updates[name] = int(value) if name in _INT_FIELDS else float(value)
    for source in (overrides, nested_display):
        for name, value in (source or {}).items():
            if name in _DISPLAY_FIELDS and value is not None:
                display_updates[name] = int(value) if name == "landmark_number_step" else bool(value)

    tolerances = replace(profile.tolerances, **tolerance_updates) if tolerance_updates else profile.tolerances
    display = replace(profile.display, **display_updates) if display_updates else profile.display
    return replace(profile, tolerances=tolerances, display=display)
