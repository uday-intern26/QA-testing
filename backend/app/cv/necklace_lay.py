"""Necklace lay detection: neckline placement checks used only for jewelry_type=necklace."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, Landmark, PlacementMeasurement
from app.utils.geometry import distance, normalize_distance

CHIN = 152
LEFT_CHEEK = 234
RIGHT_CHEEK = 454
NOSE = 1
# Approximate outer face points used as shoulder-direction proxies.
LEFT_FACE = 127
RIGHT_FACE = 356

# Product necklace trace. Centimetre offsets are y-up. Image y grows downward.
# Cheek-to-cheek face width is treated as 14 cm so those offsets land in normalized image space.
NECKLACE_TRACING: dict = {
    "chinToNeckOffsetCm": (0.0, -7.5, -4.5),
    "shoulderToNeckOffsetCm": (0.0, 3.5, 0.0),
    "widthToFaceWidth": 1.05,
    "widthToShoulderWidth": 0.42,
    "tipSpanToNeckWidth": 1.06,
    "displayScale": 1.12,
    "liveNudge": {"rightCm": -1.4, "upCm": -0.6, "stretch": 0.895},
}
REFERENCE_FACE_WIDTH_CM = 14.0
# The shared live-overlay script multiplies width by 0.55 for every jewelry type.
_OVERLAY_SCRIPT_WIDTH_FACTOR = 0.55


@dataclass
class NeckGeometry:
    center_x: float
    center_y: float
    neckline_y: float
    neck_width: float
    shoulder_width: float
    left_shoulder_x: float
    right_shoulder_x: float
    pendant_x: float
    pendant_y: float
    face_top_y: float
    confidence: float
    shoulder_line_y: float = 0.0


def necklace_overlay_width_ratio() -> float:
    """Live sprite scale. displayScale is the on-screen scale after the shared 0.55 factor."""
    return float(NECKLACE_TRACING["displayScale"]) / _OVERLAY_SCRIPT_WIDTH_FACTOR


def necklace_tip_span(neck_width: float) -> float:
    return float(neck_width) * float(NECKLACE_TRACING["tipSpanToNeckWidth"])


def _span_and_shoulder(neck_width: float) -> tuple[float, float]:
    span = necklace_tip_span(neck_width)
    shoulder = span / float(NECKLACE_TRACING["widthToShoulderWidth"])
    return span, max(0.06, shoulder)


def trace_necklace_neckline(
    chin_x: float,
    chin_y: float,
    face_width: float,
    yaw_deg: float = 0.0,
) -> tuple[float, float, float, float, float]:
    """Neck point, neck width, shoulder width, and shoulder line from the necklace trace.

    Returns center_x, neckline_y, neck_width, shoulder_width, shoulder_line_y.
    """
    nudge = NECKLACE_TRACING["liveNudge"]
    chin_offset = NECKLACE_TRACING["chinToNeckOffsetCm"]
    shoulder_offset = NECKLACE_TRACING["shoulderToNeckOffsetCm"]
    cm = face_width / REFERENCE_FACE_WIDTH_CM
    # Depth offset shifts sideways only as the head yaws. Frontal yaw leaves x unchanged.
    right_cm = float(chin_offset[0]) + float(nudge["rightCm"]) + float(chin_offset[2]) * math.sin(math.radians(yaw_deg))
    down_cm = -float(chin_offset[1]) - float(nudge["upCm"])
    center_x = min(0.98, max(0.02, chin_x + right_cm * cm))
    neckline_y = max(chin_y + 0.02, min(0.90, chin_y + down_cm * cm))
    span = face_width * float(NECKLACE_TRACING["widthToFaceWidth"]) * float(nudge["stretch"])
    neck_width = max(0.04, span / float(NECKLACE_TRACING["tipSpanToNeckWidth"]))
    shoulder_width = max(0.06, span / float(NECKLACE_TRACING["widthToShoulderWidth"]))
    # shoulderToNeckOffsetCm is y-up, so a positive y puts the shoulder line below the neck.
    nudge_down = -float(nudge["upCm"]) * cm
    anatomical_neck_y = neckline_y - nudge_down
    shoulder_line_y = min(0.98, anatomical_neck_y + float(shoulder_offset[1]) * cm)
    return center_x, neckline_y, neck_width, shoulder_width, shoulder_line_y


def _point(landmarks: list[Landmark], index: int) -> Landmark | None:
    if index < 0 or index >= len(landmarks):
        return None
    return landmarks[index]


def neck_geometry(face: FaceLandmarkResult | None, neck: EarlobeAnchor | None) -> NeckGeometry | None:
    """Estimate neckline, shoulders, and natural pendant hang from face landmarks."""
    if face is None or not face.face_detected or not face.landmarks:
        if neck is None:
            return None
        width = max(0.04, float(neck.ear_width))
        _span, shoulder_width = _span_and_shoulder(width)
        half = shoulder_width * 0.5
        face_width = _span / (
            float(NECKLACE_TRACING["widthToFaceWidth"]) * float(NECKLACE_TRACING["liveNudge"]["stretch"])
        )
        shoulder_drop = float(NECKLACE_TRACING["shoulderToNeckOffsetCm"][1]) * (face_width / REFERENCE_FACE_WIDTH_CM)
        return NeckGeometry(
            center_x=float(neck.x),
            center_y=float(neck.y),
            neckline_y=float(neck.y),
            neck_width=width,
            shoulder_width=shoulder_width,
            left_shoulder_x=float(max(0.02, neck.x - half)),
            right_shoulder_x=float(min(0.98, neck.x + half)),
            pendant_x=float(neck.x),
            pendant_y=float(min(0.98, neck.y + width * 0.55)),
            face_top_y=float(max(0.02, neck.y - width * 1.4)),
            confidence=float(neck.confidence),
            shoulder_line_y=float(min(0.98, neck.y + shoulder_drop)),
        )

    chin = _point(face.landmarks, CHIN)
    left = _point(face.landmarks, LEFT_CHEEK)
    right = _point(face.landmarks, RIGHT_CHEEK)
    nose = _point(face.landmarks, NOSE)
    left_face = _point(face.landmarks, LEFT_FACE)
    right_face = _point(face.landmarks, RIGHT_FACE)
    if chin is None:
        return None

    face_width = 0.08
    if left is not None and right is not None:
        face_width = max(0.04, abs(right.x - left.x))
    center_x = float(chin.x)
    if left is not None and right is not None:
        center_x = float((left.x + right.x) / 2.0)
    yaw = float(face.head_pose.yaw) if face.head_pose is not None else 0.0
    center_x, neckline_y, neck_width, shoulder_width, shoulder_line_y = trace_necklace_neckline(
        center_x, float(chin.y), face_width, yaw
    )
    if neck is not None:
        center_x = float(neck.x)
        neckline_y = float(neck.y)
        neck_width = max(neck_width, float(neck.ear_width))
        _span, shoulder_width = _span_and_shoulder(neck_width)
    left_shoulder = float(max(0.02, center_x - shoulder_width * 0.5))
    right_shoulder = float(min(0.98, center_x + shoulder_width * 0.5))
    if left_face is not None and right_face is not None:
        left_shoulder = float(min(left_shoulder, left_face.x - face_width * 0.15))
        right_shoulder = float(max(right_shoulder, right_face.x + face_width * 0.15))
    face_top = float(nose.y - face_width * 0.9) if nose is not None else float(chin.y - face_width * 1.5)
    confidence = float(min(face.confidence or 0.9, chin.confidence or 0.9))
    if neck is not None:
        confidence = float(min(confidence, neck.confidence))
    pendant_y = float(min(0.97, neckline_y + neck_width * 0.75))
    if pendant_y <= neckline_y + 0.01:
        pendant_y = float(min(0.97, neckline_y + 0.04))
    return NeckGeometry(
        center_x=center_x,
        center_y=neckline_y,
        neckline_y=neckline_y,
        neck_width=float(max(0.04, neck_width)),
        shoulder_width=float(max(0.06, shoulder_width)),
        left_shoulder_x=left_shoulder,
        right_shoulder_x=right_shoulder,
        pendant_x=center_x,
        pendant_y=pendant_y,
        face_top_y=float(max(0.01, face_top)),
        confidence=confidence,
        shoulder_line_y=shoulder_line_y,
    )


def _status_from_error(error: float, pass_threshold: float, fail_threshold: float) -> str:
    if error <= pass_threshold:
        return "PASS"
    if error <= fail_threshold:
        return "WARNING"
    return "FAIL"


def _accuracy_from_error(error: float, fail_threshold: float) -> float:
    """Geometric accuracy vs expected neckline model. Not detection confidence."""
    if fail_threshold <= 0:
        return 1.0 if error <= 0 else 0.0
    return float(max(0.0, min(1.0, 1.0 - (error / fail_threshold))))


def _combine(*statuses: str) -> str:
    from app.cv.tryon_placement_rules import combine_component_statuses

    return combine_component_statuses(statuses)


def evaluate_necklace_lay(
    face: FaceLandmarkResult | None,
    neck: EarlobeAnchor | None,
    jewelry: EarringAnchor | None,
    *,
    config: dict,
    left_jewelry: EarringAnchor | None = None,
    right_jewelry: EarringAnchor | None = None,
) -> dict:
    """
    Measure necklace lay around the neck.

    Only intended for jewelry_type == \"necklace\". Accuracy scores are geometric
    agreement with the expected neckline model, not detection confidence.
    """
    minimum_confidence = float(config.get("minimum_confidence", 0.80))
    # Spec section 4 defaults: PASS <= 0.02, WARNING <= 0.05, FAIL > 0.05
    pass_threshold = float(config.get("pass_threshold", 0.02))
    fail_threshold = float(config.get("fail_threshold", 0.05))
    zone_y_scale = float(config.get("zone_y_scale", 1.0))

    geometry = neck_geometry(face, neck)
    checks: dict[str, dict] = {}

    # 1. Neck detection — occluded / missing is NOT TESTABLE.
    if geometry is None or neck is None:
        checks["neck_detection"] = {
            "status": "NOT_TESTABLE",
            "accuracy": 0.0,
            "detail": "Neck / shoulder anchors are not visible / not testable.",
        }
    elif geometry.confidence < minimum_confidence:
        checks["neck_detection"] = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": f"Neck confidence {geometry.confidence:.2f} is below {minimum_confidence:.2f}.",
            "confidence": geometry.confidence,
        }
    else:
        checks["neck_detection"] = {
            "status": "PASS",
            "accuracy": 1.0,
            "detail": f"Neck detected with confidence {geometry.confidence:.2f}.",
            "confidence": geometry.confidence,
        }

    jewelry_ok = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
    if geometry is None or neck is None:
        not_testable = {
            "status": "NOT_TESTABLE",
            "accuracy": 0.0,
            "detail": "Neck / shoulder anchors are not visible / not testable.",
        }
        for key in (
            "necklace_placement",
            "neckline_alignment",
            "center_alignment",
            "left_right_alignment",
            "pendant_position",
            "shoulder_clearance",
            "necklace_to_neck_distance",
        ):
            checks[key] = dict(not_testable)
        return _finalize(checks, geometry, jewelry if jewelry_ok else None, pass_threshold, fail_threshold)

    if not jewelry_ok:
        fail_rest = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": "Necklace is detached from its anchors.",
        }
        for key in (
            "necklace_placement",
            "neckline_alignment",
            "center_alignment",
            "left_right_alignment",
            "pendant_position",
            "shoulder_clearance",
            "necklace_to_neck_distance",
        ):
            checks[key] = dict(fail_rest)
        return _finalize(checks, geometry, None, pass_threshold, fail_threshold)

    assert jewelry is not None and jewelry.x is not None and jewelry.y is not None
    jx, jy = float(jewelry.x), float(jewelry.y)

    # Landmark-relative Euclidean error vs neckline center (spec section 4).
    from app.cv.tryon_placement_rules import classify_euclidean, euclidean_error

    norm_width = max(geometry.neck_width, geometry.shoulder_width * 0.45)
    band_x_min = geometry.center_x - 0.65 * norm_width
    band_x_max = geometry.center_x + 0.65 * norm_width
    band_y_min = geometry.neckline_y - 0.25 * norm_width
    band_y_max = geometry.pendant_y + 0.45 * norm_width
    clamped_x = min(max(jx, band_x_min), band_x_max)
    clamped_y = min(max(jy, band_y_min), band_y_max)
    band_dx, band_dy = jx - clamped_x, jy - clamped_y
    band_raw = distance(band_dx, band_dy)
    # Outside-band distance kept for zone messaging; primary score is Euclidean to neckline.
    necklace_to_neck = euclidean_error(geometry.center_x, geometry.neckline_y, jx, jy)

    # Face / shoulder / chest zones for hard FAIL placement rules
    on_face = jy < geometry.face_top_y + geometry.neck_width * 0.55 and abs(jx - geometry.center_x) < geometry.neck_width * 1.2
    floating_above = jy < geometry.neckline_y - 0.45 * norm_width
    on_chest_too_low = jy > geometry.pendant_y + 0.9 * norm_width
    left_shoulder_hit = (
        abs(jx - geometry.left_shoulder_x) <= 0.4 * norm_width and abs(jy - geometry.shoulder_line_y) <= 0.55 * norm_width
    )
    right_shoulder_hit = (
        abs(jx - geometry.right_shoulder_x) <= 0.4 * norm_width and abs(jy - geometry.shoulder_line_y) <= 0.55 * norm_width
    )
    on_shoulder = left_shoulder_hit or right_shoulder_hit

    # 2. Necklace placement around neck
    placement_status = "PASS"
    placement_detail = "Necklace is positioned around the neck near the base of the neck."
    if on_face:
        placement_status = "FAIL"
        placement_detail = "Necklace is incorrectly positioned on the face."
    elif on_shoulder:
        placement_status = "FAIL"
        placement_detail = "Necklace is positioned across the shoulder."
    elif floating_above:
        placement_status = "FAIL"
        placement_detail = "Necklace is floating above or away from the neck."
    elif on_chest_too_low:
        placement_status = "FAIL"
        placement_detail = "Necklace is incorrectly positioned too low on the chest."
    elif necklace_to_neck > fail_threshold:
        placement_status = "FAIL"
        placement_detail = "Necklace placement error exceeds the fail threshold."
    elif necklace_to_neck > pass_threshold:
        placement_status = "WARNING"
        placement_detail = "Necklace is near the neck but outside the pass threshold."
    elif jewelry.confidence < minimum_confidence:
        placement_status = "WARNING"
        placement_detail = "Necklace is only partially visible or low-confidence."
    checks["necklace_placement"] = {
        "status": placement_status,
        "accuracy": _accuracy_from_error(necklace_to_neck, fail_threshold),
        "detail": placement_detail,
        "normalized_distance": necklace_to_neck,
    }

    # 3. Neckline alignment — allow natural hang between neckline and pendant; penalize leave of that band.
    above = max(0.0, band_y_min - jy) / norm_width
    below = max(0.0, jy - band_y_max) / norm_width
    neckline_error = above + below
    neckline_status = _status_from_error(neckline_error, pass_threshold, fail_threshold)
    if floating_above or on_face:
        neckline_status = "FAIL"
    checks["neckline_alignment"] = {
        "status": neckline_status,
        "accuracy": _accuracy_from_error(neckline_error, fail_threshold),
        "detail": (
            "Necklace chain follows the natural neckline."
            if neckline_status == "PASS"
            else "Necklace chain does not follow the natural neckline."
        ),
        "error": neckline_error,
    }

    # 4. Center alignment
    center_error = abs(jx - geometry.center_x) / norm_width
    center_status = _status_from_error(center_error, pass_threshold * 2.0, fail_threshold * 2.5)
    checks["center_alignment"] = {
        "status": center_status,
        "accuracy": _accuracy_from_error(center_error, fail_threshold * 2.5),
        "detail": (
            "Necklace center is aligned with the neck center."
            if center_status == "PASS"
            else "Necklace center is significantly misaligned."
            if center_status == "FAIL"
            else "Necklace center is slightly off the neck center."
        ),
        "error": center_error,
    }

    # 5. Left / right alignment
    left_pt = left_jewelry if left_jewelry and left_jewelry.x is not None and left_jewelry.y is not None else None
    right_pt = right_jewelry if right_jewelry and right_jewelry.x is not None and right_jewelry.y is not None else None
    if left_pt is not None and right_pt is not None:
        left_y = float(left_pt.y)  # type: ignore[arg-type]
        right_y = float(right_pt.y)  # type: ignore[arg-type]
        side_error = abs(left_y - right_y) / norm_width
        side_status = _status_from_error(side_error, pass_threshold, fail_threshold)
        detail = (
            "Left and right necklace sides are even."
            if side_status == "PASS"
            else "One side of the necklace is uneven."
        )
    else:
        side_error = center_error
        side_status = (
            "PASS" if center_error <= pass_threshold * 2.0 else "WARNING" if center_error <= fail_threshold * 2.5 else "FAIL"
        )
        detail = (
            "Single necklace attachment is centered; left/right chain ends were not published separately."
            if side_status == "PASS"
            else "Necklace appears uneven toward one side."
        )
    checks["left_right_alignment"] = {
        "status": side_status,
        "accuracy": _accuracy_from_error(side_error, fail_threshold * 2.5),
        "detail": detail,
        "error": side_error,
    }

    # 6. Pendant position (should hang below neckline toward upper chest)
    pendant_error = normalize_distance(
        jx - geometry.pendant_x,
        jy - geometry.pendant_y,
        norm_width,
        zone_y_scale,
    )
    pendant_status = _status_from_error(pendant_error, pass_threshold * 2.0, fail_threshold * 2.5)
    if jy < geometry.neckline_y - 0.2 * norm_width:
        pendant_status = "FAIL"
    elif on_chest_too_low:
        pendant_status = "FAIL"
    checks["pendant_position"] = {
        "status": pendant_status,
        "accuracy": _accuracy_from_error(pendant_error, fail_threshold * 2.5),
        "detail": (
            "Pendant hangs naturally below the neck toward the upper chest."
            if pendant_status == "PASS"
            else "Pendant is slightly misaligned."
            if pendant_status == "WARNING"
            else "Pendant does not hang naturally below the neck."
        ),
        "error": pendant_error,
    }

    # 7. Shoulder clearance
    if on_shoulder:
        shoulder_status = "FAIL"
        shoulder_detail = "Necklace crosses a shoulder instead of sitting on the neckline."
        shoulder_acc = 0.0
    else:
        left_gap = abs(jx - geometry.left_shoulder_x) / norm_width
        right_gap = abs(jx - geometry.right_shoulder_x) / norm_width
        shoulder_clear = min(left_gap, right_gap)
        shoulder_acc = float(max(0.0, min(1.0, shoulder_clear / max(fail_threshold * 2.0, 1e-6))))
        shoulder_status = "PASS" if shoulder_clear >= pass_threshold else "WARNING"
        shoulder_detail = "Necklace clears both shoulders." if shoulder_status == "PASS" else "Necklace is close to a shoulder."
    checks["shoulder_clearance"] = {
        "status": shoulder_status,
        "accuracy": shoulder_acc,
        "detail": shoulder_detail,
    }

    # 8. Necklace-to-neck distance (outside the natural neckline/pendant band)
    distance_status = _status_from_error(necklace_to_neck, pass_threshold, fail_threshold)
    checks["necklace_to_neck_distance"] = {
        "status": distance_status,
        "accuracy": _accuracy_from_error(necklace_to_neck, fail_threshold),
        "detail": (
            f"Normalized distance outside the neckline band is {necklace_to_neck:.3f} "
            "(normalized by neck/shoulder width)."
        ),
        "normalized_distance": necklace_to_neck,
        "raw_distance": band_raw,
        "normalization_width": norm_width,
    }

    return _finalize(checks, geometry, jewelry, pass_threshold, fail_threshold)


def _finalize(
    checks: dict[str, dict],
    geometry: NeckGeometry | None,
    jewelry: EarringAnchor | None,
    pass_threshold: float,
    fail_threshold: float,
) -> dict:
    required = [
        "neck_detection",
        "necklace_placement",
        "neckline_alignment",
        "center_alignment",
        "pendant_position",
        "shoulder_clearance",
    ]
    status = _combine(*(checks[key]["status"] for key in required if key in checks))
    # Hard rule: detection alone is never enough
    if checks.get("necklace_placement", {}).get("status") != "PASS" and status == "PASS":
        status = checks["necklace_placement"]["status"]

    accuracies = {
        "neck_detection_accuracy": float(checks.get("neck_detection", {}).get("accuracy", 0.0)),
        "necklace_placement_accuracy": float(checks.get("necklace_placement", {}).get("accuracy", 0.0)),
        "neckline_alignment_accuracy": float(checks.get("neckline_alignment", {}).get("accuracy", 0.0)),
        "center_alignment_accuracy": float(checks.get("center_alignment", {}).get("accuracy", 0.0)),
        "pendant_positioning_accuracy": float(checks.get("pendant_position", {}).get("accuracy", 0.0)),
    }
    # Overall excludes confidence; mean of geometric accuracies + shoulder
    overall_components = list(accuracies.values()) + [float(checks.get("shoulder_clearance", {}).get("accuracy", 0.0))]
    overall_accuracy = sum(overall_components) / len(overall_components) if overall_components else 0.0

    reasons = [checks[key]["detail"] for key in required if checks.get(key, {}).get("status") == "FAIL"]
    if not reasons and status == "WARNING":
        reasons = [checks[key]["detail"] for key in required if checks.get(key, {}).get("status") == "WARNING"]
    if status == "PASS":
        reason = (
            "Necklace is naturally positioned around the neck, follows the neckline, "
            "and hangs toward the upper chest."
        )
    else:
        reason = " ".join(reasons) or "Necklace lay validation failed."

    return {
        "status": status,
        "reason": reason,
        "checks": {
            "neck_detection": checks.get("neck_detection", {}).get("status", "FAIL"),
            "necklace_placement": checks.get("necklace_placement", {}).get("status", "FAIL"),
            "neckline_alignment": checks.get("neckline_alignment", {}).get("status", "FAIL"),
            "center_alignment": checks.get("center_alignment", {}).get("status", "FAIL"),
            "left_right_alignment": checks.get("left_right_alignment", {}).get("status", "FAIL"),
            "pendant_position": checks.get("pendant_position", {}).get("status", "FAIL"),
            "shoulder_clearance": checks.get("shoulder_clearance", {}).get("status", "FAIL"),
            "necklace_to_neck_distance": checks.get("necklace_to_neck_distance", {}).get("status", "FAIL"),
        },
        "check_details": checks,
        "accuracies": {
            **accuracies,
            "overall_necklace_lay_accuracy": overall_accuracy,
        },
        "overall_necklace_lay_accuracy_pct": round(overall_accuracy * 100.0, 1),
        "final_result": status,
        "geometry": None
        if geometry is None
        else {
            "center": {"x": geometry.center_x, "y": geometry.center_y},
            "neckline_y": geometry.neckline_y,
            "neck_width": geometry.neck_width,
            "shoulder_width": geometry.shoulder_width,
            "pendant": {"x": geometry.pendant_x, "y": geometry.pendant_y},
        },
        "thresholds": {
            "pass_threshold": pass_threshold,
            "fail_threshold": fail_threshold,
        },
        "jewelry_visible": bool(jewelry and jewelry.visible),
        "note": (
            "Accuracy values are geometric agreement with the expected neckline model, "
            "not detection confidence. When manual frame reviews exist they are scored separately."
        ),
    }


def measurement_from_necklace_lay(lay: dict, base: PlacementMeasurement | None = None) -> PlacementMeasurement:
    """Map necklace lay result onto PlacementMeasurement for temporal aggregation."""
    details = (lay.get("check_details") or {}).get("necklace_to_neck_distance") or {}
    normalized = details.get("normalized_distance")
    return PlacementMeasurement(
        dx=base.dx if base else None,
        dy=base.dy if base else None,
        distance=details.get("raw_distance", base.distance if base else None),
        normalized_distance=normalized if normalized is not None else (base.normalized_distance if base else None),
        status=str(lay.get("status") or "FAIL"),
        reason=str(lay.get("reason") or "Necklace lay failed."),
        earlobe_confidence=base.earlobe_confidence if base else 0.0,
        earring_confidence=base.earring_confidence if base else 0.0,
        inside_zone=bool(normalized is not None and normalized <= float(lay.get("thresholds", {}).get("fail_threshold", 0.15))),
    )


def aggregate_necklace_lay(frame_lays: list[dict], *, manual_statuses: list[str] | None = None) -> dict:
    """Aggregate per-frame necklace lay into a run-level QA result."""
    if not frame_lays:
        return {
            "status": "FAIL",
            "final_result": "FAIL",
            "overall_necklace_lay_accuracy_pct": 0.0,
            "checks": {
                "neck_detection": "FAIL",
                "necklace_placement": "FAIL",
                "neckline_alignment": "FAIL",
                "center_alignment": "FAIL",
                "pendant_position": "FAIL",
                "shoulder_clearance": "FAIL",
            },
            "accuracies": {
                "neck_detection_accuracy": 0.0,
                "necklace_placement_accuracy": 0.0,
                "neckline_alignment_accuracy": 0.0,
                "center_alignment_accuracy": 0.0,
                "pendant_positioning_accuracy": 0.0,
                "overall_necklace_lay_accuracy": 0.0,
            },
            "reason": "No necklace frames were evaluated.",
            "ground_truth_accuracy_pct": None,
            "note": "Accuracy is geometric vs expected neckline, not confidence.",
        }

    check_keys = [
        "neck_detection",
        "necklace_placement",
        "neckline_alignment",
        "center_alignment",
        "pendant_position",
        "shoulder_clearance",
        "left_right_alignment",
        "necklace_to_neck_distance",
    ]

    def worst(values: list[str]) -> str:
        if any(value == "FAIL" for value in values):
            return "FAIL"
        if any(value == "WARNING" for value in values):
            return "WARNING"
        return "PASS"

    checks = {
        key: worst([str((item.get("checks") or {}).get(key, "FAIL")) for item in frame_lays]) for key in check_keys
    }
    accuracy_keys = [
        "neck_detection_accuracy",
        "necklace_placement_accuracy",
        "neckline_alignment_accuracy",
        "center_alignment_accuracy",
        "pendant_positioning_accuracy",
        "overall_necklace_lay_accuracy",
    ]
    accuracies = {}
    for key in accuracy_keys:
        values = [float((item.get("accuracies") or {}).get(key, 0.0)) for item in frame_lays]
        accuracies[key] = sum(values) / len(values) if values else 0.0

    status = worst([str(item.get("status", "FAIL")) for item in frame_lays])
    # Must be around the neck — placement FAIL forces overall FAIL
    if checks["necklace_placement"] == "FAIL" or checks["neck_detection"] == "FAIL":
        status = "FAIL"

    ground_truth_pct = None
    if manual_statuses:
        paired = [(auto.get("status"), manual) for auto, manual in zip(frame_lays, manual_statuses) if manual]
        if paired:
            matches = sum(1 for auto, manual in paired if auto == manual)
            ground_truth_pct = round(100.0 * matches / len(paired), 1)

    reason = (
        "Necklace lay follows the neckline and hangs naturally."
        if status == "PASS"
        else next(
            (
                str(item.get("reason"))
                for item in frame_lays
                if item.get("status") == "FAIL"
            ),
            "Necklace lay did not meet neckline placement rules.",
        )
    )
    return {
        "status": status,
        "final_result": status,
        "checks": {
            "neck_detection": checks["neck_detection"],
            "necklace_placement": checks["necklace_placement"],
            "neckline_alignment": checks["neckline_alignment"],
            "center_alignment": checks["center_alignment"],
            "pendant_position": checks["pendant_position"],
            "shoulder_clearance": checks["shoulder_clearance"],
            "left_right_alignment": checks["left_right_alignment"],
            "necklace_to_neck_distance": checks["necklace_to_neck_distance"],
        },
        "accuracies": accuracies,
        "overall_necklace_lay_accuracy_pct": round(accuracies["overall_necklace_lay_accuracy"] * 100.0, 1),
        "ground_truth_accuracy_pct": ground_truth_pct,
        "frames_evaluated": len(frame_lays),
        "reason": reason,
        "note": (
            "Overall necklace lay accuracy is the mean geometric agreement with the expected neckline model. "
            "Detection confidence is not used as accuracy. "
            "ground_truth_accuracy_pct is set only when manual frame reviews exist."
        ),
    }
