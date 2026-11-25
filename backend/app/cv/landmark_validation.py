"""Deterministic landmark-based jewelry placement validation.

The engine never guesses from pixels. It compares the expected attachment point
derived from the existing landmark pipeline with the actual jewelry anchor
produced by the existing placement pipeline, both in the same normalized space.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from app.cv.debug_config import CategoryDebugProfile
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, HandLandmarkResult

PASS = "PASS"
FAIL = "FAIL"
NOT_TESTABLE = "NOT_TESTABLE"

# Failure reason codes exposed in reports.
REQUIRED_LANDMARK_NOT_DETECTED = "REQUIRED_LANDMARK_NOT_DETECTED"
LANDMARK_NOT_DETECTED = "LANDMARK_NOT_DETECTED"
LOW_LANDMARK_CONFIDENCE = "LOW_LANDMARK_CONFIDENCE"
ATTACHMENT_POSITION_OUT_OF_TOLERANCE = "ATTACHMENT_POSITION_OUT_OF_TOLERANCE"
ATTACHMENT_POSITION_MISMATCH = "ATTACHMENT_POSITION_MISMATCH"
NORMALIZED_DISTANCE_EXCEEDED = "NORMALIZED_DISTANCE_EXCEEDED"
ROTATION_OUT_OF_TOLERANCE = "ROTATION_OUT_OF_TOLERANCE"
SCALE_OUT_OF_RANGE = "SCALE_OUT_OF_RANGE"
TEMPORAL_DRIFT = "TEMPORAL_DRIFT"
TRACKING_LOST = "TRACKING_LOST"
INVALID_FRAME = "INVALID_FRAME"
EARRING_MODEL_NOT_LOADED = "EARRING_MODEL_NOT_LOADED"
ATTACHMENT_ANCHOR_MISSING = "ATTACHMENT_ANCHOR_MISSING"
DUPLICATE_FRAME_SKIPPED = "DUPLICATE_FRAME_SKIPPED"

# Stage codes the scene probe reports, mapped onto validation failure codes so a
# missing jewelry anchor always names the pipeline stage that broke.
_STAGE_TO_REASON = {
    "SCENE_NOT_REACHABLE": ATTACHMENT_ANCHOR_MISSING,
    "EARRING_MODEL_NOT_LOADED": EARRING_MODEL_NOT_LOADED,
    "JEWELRY_MESH_HIDDEN": EARRING_MODEL_NOT_LOADED,
    "TRANSFORM_NOT_COMPUTED": ATTACHMENT_ANCHOR_MISSING,
    "CAMERA_NOT_FOUND": ATTACHMENT_ANCHOR_MISSING,
    "ATTACHMENT_ANCHOR_MISSING": ATTACHMENT_ANCHOR_MISSING,
    "NO_ANCHOR_IN_DEBUG_STATE": ATTACHMENT_ANCHOR_MISSING,
    "NO_DEBUG_STATE": ATTACHMENT_ANCHOR_MISSING,
}


def reason_for_missing_anchor(diagnostics: dict | None) -> str:
    """Name why the jewelry anchor is absent instead of defaulting to TRACKING_LOST."""
    if not isinstance(diagnostics, dict):
        return TRACKING_LOST
    stage = str(diagnostics.get("anchor_stage") or "")
    return _STAGE_TO_REASON.get(stage, TRACKING_LOST)


@dataclass
class CheckResult:
    status: str
    detail: str
    measured: float | None = None
    tolerance: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FrameValidation:
    frame_number: int
    timestamp_ms: int
    side: str
    jewelry_type: str
    landmark_index: int | None = None
    expected_x: float | None = None
    expected_y: float | None = None
    actual_x: float | None = None
    actual_y: float | None = None
    expected_px: tuple[float, float] | None = None
    actual_px: tuple[float, float] | None = None
    position_error_px: float | None = None
    position_error_normalized: float | None = None
    position_error_body_relative: float | None = None
    landmark_confidence: float | None = None
    jewelry_confidence: float | None = None
    rotation_deg: float | None = None
    scale_ratio: float | None = None
    checks: dict[str, CheckResult] = field(default_factory=dict)
    status: str = NOT_TESTABLE
    failure_reason: str | None = None
    anchor_source: str | None = None
    diagnostics: dict | None = None

    def to_dict(self) -> dict:
        return {
            "frame_number": self.frame_number,
            "timestamp_ms": self.timestamp_ms,
            "side": self.side,
            "jewelry_type": self.jewelry_type,
            "landmark_index": self.landmark_index,
            "expected": None
            if self.expected_x is None
            else {"x": self.expected_x, "y": self.expected_y},
            "actual": None if self.actual_x is None else {"x": self.actual_x, "y": self.actual_y},
            "expected_px": list(self.expected_px) if self.expected_px else None,
            "actual_px": list(self.actual_px) if self.actual_px else None,
            "position_error_px": self.position_error_px,
            "position_error_normalized": self.position_error_normalized,
            "position_error_body_relative": self.position_error_body_relative,
            "landmark_confidence": self.landmark_confidence,
            "jewelry_confidence": self.jewelry_confidence,
            "rotation_deg": self.rotation_deg,
            "scale_ratio": self.scale_ratio,
            "checks": {name: check.to_dict() for name, check in self.checks.items()},
            "status": self.status,
            "failure_reason": self.failure_reason,
            "anchor_source": self.anchor_source,
            "diagnostics": self.diagnostics,
        }


def _combine(*statuses: str) -> str:
    if any(status == FAIL for status in statuses):
        return FAIL
    if statuses and all(status == PASS for status in statuses):
        return PASS
    return NOT_TESTABLE


def _landmark_check(
    face: FaceLandmarkResult | None,
    hand: HandLandmarkResult | None,
    expected: EarlobeAnchor | None,
    profile: CategoryDebugProfile,
) -> tuple[CheckResult, float | None]:
    """A. Is the required body landmark detected, confident, and in frame?"""
    tolerances = profile.tolerances
    uses_hand = profile.body_region in {"wrist", "finger"}
    detected = bool(hand and hand.hand_detected) if uses_hand else bool(face and face.face_detected)
    if not detected or expected is None:
        return (
            CheckResult(
                status=FAIL,
                detail=f"Required {profile.body_region} landmark was not detected.",
            ),
            None,
        )
    confidence = float(expected.confidence or 0.0)
    if confidence < tolerances.minimum_landmark_confidence:
        return (
            CheckResult(
                status=FAIL,
                detail=(
                    f"{profile.body_region.capitalize()} landmark confidence {confidence:.2f} is below "
                    f"the required {tolerances.minimum_landmark_confidence:.2f}."
                ),
                measured=confidence,
                tolerance=tolerances.minimum_landmark_confidence,
            ),
            confidence,
        )
    in_frame = 0.0 <= expected.x <= 1.0 and 0.0 <= expected.y <= 1.0
    if not in_frame:
        return (
            CheckResult(
                status=FAIL,
                detail=f"{profile.body_region.capitalize()} landmark is outside the frame.",
                measured=confidence,
                tolerance=tolerances.minimum_landmark_confidence,
            ),
            confidence,
        )
    return (
        CheckResult(
            status=PASS,
            detail=(
                f"{profile.body_region.capitalize()} landmark detected with confidence {confidence:.2f}."
            ),
            measured=confidence,
            tolerance=tolerances.minimum_landmark_confidence,
        ),
        confidence,
    )


def _visibility_check(jewelry: EarringAnchor | None, profile: CategoryDebugProfile) -> CheckResult:
    """E. Is the jewelry model actually placed and inside the frame?"""
    if jewelry is None or jewelry.x is None or jewelry.y is None or not jewelry.visible:
        return CheckResult(status=FAIL, detail=f"{profile.label} is not visible in this frame.")
    if not (0.0 <= jewelry.x <= 1.0 and 0.0 <= jewelry.y <= 1.0):
        return CheckResult(
            status=FAIL,
            detail=f"{profile.label} moved outside the frame region.",
        )
    confidence = float(jewelry.confidence or 0.0)
    return CheckResult(
        status=PASS,
        detail=f"{profile.label} is visible with confidence {confidence:.2f}.",
        measured=confidence,
    )


def _position_check(
    expected: EarlobeAnchor,
    jewelry: EarringAnchor,
    profile: CategoryDebugProfile,
    frame_size: tuple[int, int] | None,
) -> tuple[CheckResult, float | None, float | None, float | None]:
    """B. Geometric deviation between expected and actual attachment points.

    Both points are already in the same normalized image space (0..1), which is
    the space the project's Euclidean pass bands are defined in. The body-relative
    value is reported alongside for context but is never mixed into the band.
    """
    tolerances = profile.tolerances
    dx = float(jewelry.x) - float(expected.x)
    dy = float(jewelry.y) - float(expected.y)
    error_normalized = math.hypot(dx, dy)

    body_width = float(expected.ear_width or 0.0)
    error_body_relative = error_normalized / body_width if body_width > 1e-6 else None

    error_px: float | None = None
    if frame_size:
        width, height = frame_size
        error_px = math.hypot(dx * float(width), dy * float(height))

    within_normalized = error_normalized <= tolerances.position_tolerance_normalized
    # The pixel budget is resolution dependent, so it only gates when it was set
    # explicitly. Otherwise the normalized band alone decides.
    within_px = True
    if tolerances.position_tolerance_px is not None and error_px is not None:
        within_px = error_px <= tolerances.position_tolerance_px

    status = PASS if within_normalized and within_px else FAIL
    detail_parts = [
        f"Position error {error_normalized:.4f} normalized "
        f"(allowed {tolerances.position_tolerance_normalized:.4f})"
    ]
    if error_px is not None:
        if tolerances.position_tolerance_px is not None:
            detail_parts.append(f"{error_px:.2f} px (allowed {tolerances.position_tolerance_px:.2f} px)")
        else:
            detail_parts.append(f"{error_px:.2f} px")
    if error_body_relative is not None:
        detail_parts.append(f"{error_body_relative:.2f}x {profile.body_region} width")
    return (
        CheckResult(
            status=status,
            detail="; ".join(detail_parts) + ".",
            measured=error_normalized,
            tolerance=tolerances.position_tolerance_normalized,
        ),
        error_px,
        error_normalized,
        error_body_relative,
    )


def _rotation_check(
    jewelry: EarringAnchor,
    profile: CategoryDebugProfile,
    expected_rotation_deg: float = 0.0,
) -> tuple[CheckResult, float | None]:
    """C. Orientation against the configured angular tolerance."""
    if jewelry.rotation is None:
        return (
            CheckResult(
                status=NOT_TESTABLE,
                detail="Rotation was not published by the try-on pipeline.",
            ),
            None,
        )
    rotation = float(jewelry.rotation)
    error = abs(((rotation - expected_rotation_deg) + 180.0) % 360.0 - 180.0)
    tolerance = profile.tolerances.rotation_tolerance_deg
    status = PASS if error <= tolerance else FAIL
    return (
        CheckResult(
            status=status,
            detail=f"Rotation error {error:.1f}° (allowed {tolerance:.1f}°).",
            measured=error,
            tolerance=tolerance,
        ),
        rotation,
    )


def _scale_check(jewelry: EarringAnchor, profile: CategoryDebugProfile) -> tuple[CheckResult, float | None]:
    """D. Size within the configured expected range."""
    if jewelry.scale is None:
        return (
            CheckResult(
                status=NOT_TESTABLE,
                detail="Scale was not published by the try-on pipeline.",
            ),
            None,
        )
    ratio = float(jewelry.scale)
    low = profile.tolerances.scale_min_ratio
    high = profile.tolerances.scale_max_ratio
    status = PASS if low <= ratio <= high else FAIL
    return (
        CheckResult(
            status=status,
            detail=f"Scale ratio {ratio:.2f} (allowed {low:.2f}–{high:.2f}).",
            measured=ratio,
            tolerance=high,
        ),
        ratio,
    )


def evaluate_frame(
    *,
    frame_number: int,
    timestamp_ms: int,
    side: str,
    profile: CategoryDebugProfile,
    face: FaceLandmarkResult | None,
    hand: HandLandmarkResult | None,
    expected: EarlobeAnchor | None,
    jewelry: EarringAnchor | None,
    frame_size: tuple[int, int] | None = None,
    landmark_index: int | None = None,
    expected_rotation_deg: float = 0.0,
    diagnostics: dict | None = None,
) -> FrameValidation:
    """Run every per-frame check. Checks stay independent and are never merged."""
    result = FrameValidation(
        frame_number=frame_number,
        timestamp_ms=timestamp_ms,
        side=side,
        jewelry_type=profile.jewelry_type,
        landmark_index=landmark_index,
        anchor_source=jewelry.source if jewelry is not None else None,
        diagnostics=diagnostics,
    )

    landmark_check, landmark_confidence = _landmark_check(face, hand, expected, profile)
    result.checks["landmark_detection"] = landmark_check
    result.landmark_confidence = landmark_confidence

    if expected is not None:
        result.expected_x = float(expected.x)
        result.expected_y = float(expected.y)
        if frame_size:
            result.expected_px = (expected.x * frame_size[0], expected.y * frame_size[1])

    visibility_check = _visibility_check(jewelry, profile)
    result.checks["visibility"] = visibility_check

    if landmark_check.status == FAIL:
        result.status = FAIL
        result.failure_reason = (
            LOW_LANDMARK_CONFIDENCE
            if landmark_check.measured is not None and landmark_check.tolerance is not None
            and landmark_check.measured < landmark_check.tolerance
            else REQUIRED_LANDMARK_NOT_DETECTED
        )
        for name in ("position", "rotation", "scale"):
            result.checks[name] = CheckResult(
                status=NOT_TESTABLE,
                detail="Skipped because the required landmark was not usable.",
            )
        return result

    if visibility_check.status == FAIL or jewelry is None or jewelry.x is None or jewelry.y is None:
        result.status = FAIL
        result.failure_reason = reason_for_missing_anchor(diagnostics)
        for name in ("position", "rotation", "scale"):
            result.checks[name] = CheckResult(
                status=NOT_TESTABLE,
                detail="Skipped because the jewelry anchor was not placed.",
            )
        return result

    assert expected is not None
    result.actual_x = float(jewelry.x)
    result.actual_y = float(jewelry.y)
    result.jewelry_confidence = float(jewelry.confidence or 0.0)
    if frame_size:
        result.actual_px = (jewelry.x * frame_size[0], jewelry.y * frame_size[1])

    position_check, error_px, error_normalized, error_body = _position_check(
        expected, jewelry, profile, frame_size
    )
    result.checks["position"] = position_check
    result.position_error_px = error_px
    result.position_error_normalized = error_normalized
    result.position_error_body_relative = error_body

    rotation_check, rotation = _rotation_check(jewelry, profile, expected_rotation_deg)
    result.checks["rotation"] = rotation_check
    result.rotation_deg = rotation

    scale_check, scale_ratio = _scale_check(jewelry, profile)
    result.checks["scale"] = scale_check
    result.scale_ratio = scale_ratio

    result.status = _combine(
        landmark_check.status,
        visibility_check.status,
        position_check.status,
        rotation_check.status,
        scale_check.status,
    )
    if result.status == FAIL:
        if position_check.status == FAIL:
            result.failure_reason = NORMALIZED_DISTANCE_EXCEEDED
        elif rotation_check.status == FAIL:
            result.failure_reason = ROTATION_OUT_OF_TOLERANCE
        elif scale_check.status == FAIL:
            result.failure_reason = SCALE_OUT_OF_RANGE
        else:
            result.failure_reason = INVALID_FRAME
    return result


def _temporal_check(
    frames: list[FrameValidation],
    profile: CategoryDebugProfile,
) -> tuple[CheckResult, dict]:
    """F. Stability across consecutive frames: drift, jumps, tracking loss."""
    tolerances = profile.tolerances
    total = len(frames)
    valid = [frame for frame in frames if frame.status != NOT_TESTABLE]
    passed = [frame for frame in frames if frame.status == PASS]
    ignored = total - len(valid)

    consecutive = 0
    max_consecutive = 0
    for frame in frames:
        if frame.status == FAIL:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    jumps = 0
    previous: FrameValidation | None = None
    for frame in frames:
        if frame.actual_x is None or frame.actual_y is None:
            previous = None
            continue
        if previous is not None and previous.actual_x is not None and previous.actual_y is not None:
            jump = math.hypot(frame.actual_x - previous.actual_x, frame.actual_y - previous.actual_y)
            if jump > tolerances.max_interframe_jump_normalized:
                jumps += 1
        previous = frame

    longest_stable = 0
    streak = 0
    for frame in frames:
        if frame.status == PASS:
            streak += 1
            longest_stable = max(longest_stable, streak)
        else:
            streak = 0

    testable = len(valid)
    valid_percentage = (100.0 * len(passed) / testable) if testable else 0.0

    metrics = {
        "total_frames": total,
        "valid_frames": len(passed),
        "testable_frames": testable,
        "ignored_frames": ignored,
        "tracking_failures": sum(1 for frame in frames if frame.failure_reason == TRACKING_LOST),
        "max_consecutive_failures": max_consecutive,
        "position_jumps": jumps,
        "longest_stable_frames": longest_stable,
        "valid_frame_percentage": round(valid_percentage, 2),
    }

    if not frames:
        return CheckResult(status=NOT_TESTABLE, detail="No frames were evaluated."), metrics

    problems: list[str] = []
    if valid_percentage < tolerances.minimum_valid_frame_percentage:
        problems.append(
            f"Only {valid_percentage:.1f}% of evaluated frames passed "
            f"(minimum {tolerances.minimum_valid_frame_percentage:.1f}%)"
        )
    if max_consecutive > tolerances.max_consecutive_tracking_failures:
        problems.append(
            f"{max_consecutive} consecutive failing frames exceed the limit of "
            f"{tolerances.max_consecutive_tracking_failures}"
        )
    if longest_stable < min(tolerances.minimum_stable_frames, total):
        problems.append(
            f"Longest stable run is {longest_stable} frames (minimum {tolerances.minimum_stable_frames})"
        )
    if jumps:
        problems.append(f"{jumps} sudden position jumps between consecutive frames")

    status = FAIL if problems else PASS
    detail = "; ".join(problems) + "." if problems else (
        f"Placement stayed attached across {len(passed)}/{total} frames."
    )
    return CheckResult(status=status, detail=detail, measured=valid_percentage,
                       tolerance=tolerances.minimum_valid_frame_percentage), metrics


def _aggregate_check(frames: list[FrameValidation], name: str) -> CheckResult:
    statuses = [frame.checks[name].status for frame in frames if name in frame.checks]
    testable = [status for status in statuses if status != NOT_TESTABLE]
    if not testable:
        return CheckResult(status=NOT_TESTABLE, detail=f"{name} was not testable on any frame.")
    failures = sum(1 for status in testable if status == FAIL)
    if failures:
        return CheckResult(
            status=FAIL,
            detail=f"{failures} of {len(testable)} evaluated frames failed the {name} check.",
            measured=float(failures),
        )
    return CheckResult(status=PASS, detail=f"All {len(testable)} evaluated frames passed the {name} check.")


def summarize_validation(
    frames: list[FrameValidation],
    profile: CategoryDebugProfile,
) -> dict:
    """Run-level deterministic result with explicit failure reason codes."""
    checks = {
        name: _aggregate_check(frames, name)
        for name in ("landmark_detection", "visibility", "position", "rotation", "scale")
    }
    temporal, metrics = _temporal_check(frames, profile)
    checks["temporal_stability"] = temporal

    errors_px = [frame.position_error_px for frame in frames if frame.position_error_px is not None]
    errors_norm = [
        frame.position_error_normalized for frame in frames if frame.position_error_normalized is not None
    ]
    # Where the "actual" coordinates came from, so a measured anchor is never
    # confused with a pixel guess or a missing one.
    anchor_sources: dict[str, int] = {}
    for frame in frames:
        key = frame.anchor_source or "missing"
        anchor_sources[key] = anchor_sources.get(key, 0) + 1
    anchor_stages: dict[str, int] = {}
    for frame in frames:
        stage = (frame.diagnostics or {}).get("anchor_stage") if frame.diagnostics else None
        if stage:
            anchor_stages[str(stage)] = anchor_stages.get(str(stage), 0) + 1

    # A measured deviation is more actionable than "lost on some frames", so the
    # position/rotation/scale codes win when any frame was testable at all.
    order = [
        ("landmark_detection", REQUIRED_LANDMARK_NOT_DETECTED),
        ("position", NORMALIZED_DISTANCE_EXCEEDED),
        ("rotation", ROTATION_OUT_OF_TOLERANCE),
        ("scale", SCALE_OUT_OF_RANGE),
        ("visibility", TRACKING_LOST),
        ("temporal_stability", TEMPORAL_DRIFT),
    ]
    missing_anchor_codes = {
        EARRING_MODEL_NOT_LOADED,
        ATTACHMENT_ANCHOR_MISSING,
        TRACKING_LOST,
    }
    failure_reason: str | None = None
    for name, code in order:
        if checks[name].status != FAIL:
            continue
        if name == "landmark_detection":
            code = next(
                (
                    frame.failure_reason
                    for frame in frames
                    if frame.failure_reason in {LOW_LANDMARK_CONFIDENCE, REQUIRED_LANDMARK_NOT_DETECTED}
                ),
                REQUIRED_LANDMARK_NOT_DETECTED,
            )
        elif name == "visibility":
            # Keep the specific stage the scene probe reported.
            code = next(
                (frame.failure_reason for frame in frames if frame.failure_reason in missing_anchor_codes),
                TRACKING_LOST,
            )
        failure_reason = code
        break

    if not frames:
        overall = NOT_TESTABLE
        failure_reason = INVALID_FRAME
    elif failure_reason is not None:
        overall = FAIL
    elif all(check.status == NOT_TESTABLE for check in checks.values()):
        overall = NOT_TESTABLE
        failure_reason = INVALID_FRAME
    else:
        overall = PASS

    return {
        "jewelry_type": profile.jewelry_type,
        "overall_status": overall,
        "failure_reason": failure_reason,
        "checks": {name: check.to_dict() for name, check in checks.items()},
        "metrics": {
            **metrics,
            "average_position_error_px": round(sum(errors_px) / len(errors_px), 3) if errors_px else None,
            "max_position_error_px": round(max(errors_px), 3) if errors_px else None,
            "average_position_error_normalized": round(sum(errors_norm) / len(errors_norm), 4)
            if errors_norm
            else None,
            "max_position_error_normalized": round(max(errors_norm), 4) if errors_norm else None,
        },
        "anchor_sources": anchor_sources,
        "anchor_stages": anchor_stages,
        "tolerances": asdict(profile.tolerances),
        "frames": [frame.to_dict() for frame in frames],
    }
