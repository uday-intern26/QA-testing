"""Bracelet lay detection: wrist placement checks used only for jewelry_type=bracelet."""

from __future__ import annotations

from dataclasses import dataclass

from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, PlacementMeasurement
from app.utils.geometry import distance, normalize_distance, offset

BRACELET_STYLES = ("chain", "bangle", "tennis", "cuff", "default")


@dataclass
class WristGeometry:
    side: str
    confidence: float
    center_x: float
    center_y: float
    width: float
    height: float
    left_x: float
    right_x: float
    top_y: float
    bottom_y: float
    forearm_x: float
    forearm_y: float
    palm_x: float
    palm_y: float
    finger_x: float
    finger_y: float
    direction_x: float
    direction_y: float
    source: str
    style: str


def _status_from_error(error: float, pass_threshold: float, fail_threshold: float) -> str:
    if error <= pass_threshold:
        return "PASS"
    if error <= fail_threshold:
        return "WARNING"
    return "FAIL"


def _accuracy_from_error(error: float, fail_threshold: float) -> float:
    if fail_threshold <= 0:
        return 1.0 if error <= 0 else 0.0
    return float(max(0.0, min(1.0, 1.0 - (error / fail_threshold))))


def _combine(*statuses: str) -> str:
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if any(status == "WARNING" for status in statuses):
        return "WARNING"
    if statuses and all(status == "PASS" for status in statuses):
        return "PASS"
    return "FAIL"


def infer_bracelet_style(jewelry_id: str | None, config: dict | None = None) -> str:
    configured = (config or {}).get("bracelet_style")
    if isinstance(configured, str) and configured.lower() in BRACELET_STYLES:
        return configured.lower()
    text = (jewelry_id or "").strip().lower()
    if "tennis" in text:
        return "tennis"
    if "cuff" in text:
        return "cuff"
    if "bangle" in text:
        return "bangle"
    if "chain" in text or "link" in text:
        return "chain"
    return "default"


def _style_tolerances(style: str) -> dict[str, float]:
    """Per-style wrist seat tolerances. Not identical for every bracelet type."""
    if style == "tennis":
        return {"along_allow": 0.35, "across_allow": 0.55, "coverage_min": 0.25, "coverage_max": 0.85}
    if style == "chain":
        return {"along_allow": 0.45, "across_allow": 0.65, "coverage_min": 0.20, "coverage_max": 0.90}
    if style == "bangle":
        return {"along_allow": 0.55, "across_allow": 0.80, "coverage_min": 0.30, "coverage_max": 1.05}
    if style == "cuff":
        return {"along_allow": 0.70, "across_allow": 0.95, "coverage_min": 0.35, "coverage_max": 1.20}
    return {"along_allow": 0.50, "across_allow": 0.70, "coverage_min": 0.25, "coverage_max": 0.95}


def _point_from_block(block: dict, names: tuple[str, ...]) -> tuple[float, float] | None:
    for name in names:
        value = block.get(name)
        if isinstance(value, dict) and value.get("x") is not None and value.get("y") is not None:
            return float(value["x"]), float(value["y"])
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return float(value[0]), float(value[1])
    return None


def _hand_from_debug(debug_state: dict | None, side: str) -> dict | None:
    if not isinstance(debug_state, dict):
        return None
    hands = debug_state.get("hands")
    if isinstance(hands, list):
        for hand in hands:
            if not isinstance(hand, dict):
                continue
            hand_side = str(hand.get("side") or hand.get("handedness") or "").lower()
            if side in hand_side or hand_side in {side, side[0], f"{side}_hand"}:
                return hand
        if hands and isinstance(hands[0], dict):
            return hands[0]
    for key in ("hand", "wrist", "bracelet_hand", "hand_landmarks"):
        value = debug_state.get(key)
        if isinstance(value, dict) and value:
            return value
    return None


def wrist_geometry_from_hand(hand: dict, side: str, style: str) -> WristGeometry | None:
    wrist = _point_from_block(hand, ("wrist", "wrist_center", "center"))
    if wrist is None:
        return None
    confidence = float(hand.get("confidence") or hand.get("score") or 0.85)
    index_mcp = _point_from_block(hand, ("index_mcp", "index"))
    pinky_mcp = _point_from_block(hand, ("little_mcp", "pinky_mcp", "pinky"))
    middle_tip = _point_from_block(hand, ("middle_tip", "middle"))
    elbow = _point_from_block(hand, ("elbow", "forearm", "forearm_point"))
    palm = _point_from_block(hand, ("palm", "palm_center")) or (
        ((index_mcp[0] + pinky_mcp[0]) / 2.0, (index_mcp[1] + pinky_mcp[1]) / 2.0)
        if index_mcp and pinky_mcp
        else (wrist[0], wrist[1] - 0.04)
    )
    finger = middle_tip or (palm[0], palm[1] - 0.06)
    if elbow is None:
        # Forearm opposite the fingers relative to wrist
        elbow = (wrist[0] * 2 - palm[0], wrist[1] * 2 - palm[1])
    dx, dy = palm[0] - elbow[0], palm[1] - elbow[1]
    length = max(1e-6, distance(dx, dy))
    direction = (dx / length, dy / length)
    if index_mcp and pinky_mcp:
        width = max(0.03, distance(index_mcp[0] - pinky_mcp[0], index_mcp[1] - pinky_mcp[1]) * 0.85)
        left_x, right_x = sorted([index_mcp[0], pinky_mcp[0]])
    else:
        width = max(0.03, float(hand.get("wrist_width") or 0.06))
        left_x, right_x = wrist[0] - width * 0.5, wrist[0] + width * 0.5
    height = width * 0.55
    return WristGeometry(
        side=side,
        confidence=confidence,
        center_x=float(wrist[0]),
        center_y=float(wrist[1]),
        width=float(width),
        height=float(height),
        left_x=float(left_x),
        right_x=float(right_x),
        top_y=float(wrist[1] - height * 0.5),
        bottom_y=float(wrist[1] + height * 0.5),
        forearm_x=float(elbow[0]),
        forearm_y=float(elbow[1]),
        palm_x=float(palm[0]),
        palm_y=float(palm[1]),
        finger_x=float(finger[0]),
        finger_y=float(finger[1]),
        direction_x=float(direction[0]),
        direction_y=float(direction[1]),
        source="hand_landmarks",
        style=style,
    )


def wrist_geometry_from_proxy(wrist_anchor: EarlobeAnchor | None, side: str, style: str) -> WristGeometry | None:
    if wrist_anchor is None:
        return None
    width = max(0.03, float(wrist_anchor.ear_width))
    height = max(0.02, float(wrist_anchor.ear_height or width * 0.55))
    cx, cy = float(wrist_anchor.x), float(wrist_anchor.y)
    # Hand direction roughly upward (toward smaller y) in typical try-on framing.
    direction = (0.0, -1.0)
    palm = (cx, cy - width * 0.9)
    fingers = (cx, cy - width * 1.5)
    forearm = (cx, cy + width * 1.1)
    return WristGeometry(
        side=side,
        confidence=float(wrist_anchor.confidence),
        center_x=cx,
        center_y=cy,
        width=width,
        height=height,
        left_x=cx - width * 0.5,
        right_x=cx + width * 0.5,
        top_y=cy - height * 0.5,
        bottom_y=cy + height * 0.5,
        forearm_x=float(forearm[0]),
        forearm_y=float(forearm[1]),
        palm_x=float(palm[0]),
        palm_y=float(palm[1]),
        finger_x=float(fingers[0]),
        finger_y=float(fingers[1]),
        direction_x=direction[0],
        direction_y=direction[1],
        source="wrist_proxy",
        style=style,
    )


def resolve_wrist_geometry(
    *,
    wrist_anchor: EarlobeAnchor | None,
    face: FaceLandmarkResult | None,
    debug_state: dict | None,
    side: str,
    style: str,
) -> WristGeometry | None:
    hand = _hand_from_debug(debug_state, side)
    if hand is not None:
        geometry = wrist_geometry_from_hand(hand, side, style)
        if geometry is not None:
            return geometry
    _ = face
    return wrist_geometry_from_proxy(wrist_anchor, side, style)


def evaluate_bracelet_lay(
    face: FaceLandmarkResult | None,
    wrist_anchor: EarlobeAnchor | None,
    jewelry: EarringAnchor | None,
    *,
    config: dict,
    side: str = "left",
    jewelry_id: str | None = None,
    debug_state: dict | None = None,
) -> dict:
    """
    Measure bracelet lay around the wrist.

    Only intended for jewelry_type == \"bracelet\". Accuracy scores are geometric
    agreement with the expected wrist model, not detection confidence.
    """
    minimum_confidence = float(config.get("minimum_confidence", 0.80))
    pass_threshold = float(config.get("pass_threshold", 0.10))
    fail_threshold = float(config.get("fail_threshold", 0.18))
    zone_y_scale = float(config.get("zone_y_scale", 1.0))
    wrist_side = side if side in {"left", "right"} else "left"
    style = infer_bracelet_style(jewelry_id, config)
    tolerances = _style_tolerances(style)

    geometry = resolve_wrist_geometry(
        wrist_anchor=wrist_anchor,
        face=face,
        debug_state=debug_state,
        side=wrist_side,
        style=style,
    )
    checks: dict[str, dict] = {}

    # 1. Wrist detection
    if geometry is None:
        checks["wrist_detection"] = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": f"{wrist_side.capitalize()} wrist was not detected.",
        }
    elif geometry.confidence < minimum_confidence:
        checks["wrist_detection"] = {
            "status": "WARNING",
            "accuracy": 0.0,
            "detail": (
                f"{wrist_side.capitalize()} wrist confidence {geometry.confidence:.2f} is below "
                f"{minimum_confidence:.2f} (partial visibility or occlusion)."
            ),
            "confidence": geometry.confidence,
        }
    else:
        checks["wrist_detection"] = {
            "status": "PASS",
            "accuracy": 1.0,
            "detail": (
                f"{wrist_side.capitalize()} wrist detected ({geometry.source}) "
                f"with confidence {geometry.confidence:.2f}."
            ),
            "confidence": geometry.confidence,
        }

    # 2. Wrist landmark detection
    if geometry is None:
        checks["wrist_landmark_detection"] = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": "Wrist landmarks (center, boundaries, forearm direction) were not identified.",
        }
    else:
        checks["wrist_landmark_detection"] = {
            "status": "PASS",
            "accuracy": 1.0,
            "detail": "Wrist center, boundaries, hand connection, and forearm direction identified.",
            "landmarks": {
                "center": {"x": geometry.center_x, "y": geometry.center_y},
                "left": geometry.left_x,
                "right": geometry.right_x,
                "forearm": {"x": geometry.forearm_x, "y": geometry.forearm_y},
                "palm": {"x": geometry.palm_x, "y": geometry.palm_y},
            },
        }

    jewelry_ok = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
    if not jewelry_ok or geometry is None:
        fail = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": (
                "Bracelet attachment point was not detected."
                if geometry
                else "Cannot score bracelet lay without a wrist estimate."
            ),
        }
        for key in (
            "bracelet_placement",
            "wrist_alignment",
            "bracelet_center_alignment",
            "wrist_coverage",
            "bracelet_to_wrist_distance",
            "hand_clearance",
            "forearm_clearance",
            "bracelet_orientation",
            "bracelet_visibility",
        ):
            checks[key] = dict(fail)
        if not jewelry_ok:
            checks["bracelet_visibility"] = {
                "status": "FAIL",
                "accuracy": 0.0,
                "detail": "Bracelet is not sufficiently visible for accurate detection.",
            }
        return _finalize(checks, geometry, jewelry, wrist_side, style, pass_threshold, fail_threshold)

    assert jewelry is not None and jewelry.x is not None and jewelry.y is not None
    jx, jy = float(jewelry.x), float(jewelry.y)
    width = max(0.03, geometry.width)

    dx, dy = offset(jx, jy, geometry.center_x, geometry.center_y)
    raw = distance(dx, dy)
    along = dx * geometry.direction_x + dy * geometry.direction_y
    across = dx * (-geometry.direction_y) + dy * geometry.direction_x
    # Seat around wrist joint: small travel toward hand/forearm allowed by style
    along_allow = tolerances["along_allow"] * width
    across_allow = tolerances["across_allow"] * width
    residual_along = 0.0 if abs(along) <= along_allow else abs(along) - along_allow
    residual_across = 0.0 if abs(across) <= across_allow else abs(across) - across_allow
    bracelet_to_wrist = normalize_distance(residual_across, residual_along, width, zone_y_scale)

    palm_dist = distance(jx - geometry.palm_x, jy - geometry.palm_y) / width
    finger_dist = distance(jx - geometry.finger_x, jy - geometry.finger_y) / width
    forearm_dist = distance(jx - geometry.forearm_x, jy - geometry.forearm_y) / width
    on_palm = palm_dist < 0.85 and along > 0.55 * width
    on_fingers = finger_dist < 0.75 and along > 1.0 * width
    too_far_forearm = along < -0.95 * width or (forearm_dist < 0.7 and along < -0.55 * width)
    floating = bracelet_to_wrist > fail_threshold and (abs(across) > 0.7 * width or abs(along) > 1.1 * width)

    # 11. Visibility
    if not jewelry.visible:
        vis_status, vis_detail, vis_acc = "FAIL", "Bracelet is not visible.", 0.0
    elif jewelry.confidence < minimum_confidence:
        vis_status = "WARNING"
        vis_detail = "Bracelet detection confidence is insufficient or clothing partially covers it."
        vis_acc = 0.5
    elif jx < 0.02 or jx > 0.98 or jy < 0.02 or jy > 0.98:
        vis_status, vis_detail, vis_acc = "WARNING", "Bracelet is partially outside the camera frame.", 0.5
    else:
        vis_status, vis_detail, vis_acc = "PASS", "Bracelet is sufficiently visible for detection.", 1.0
    checks["bracelet_visibility"] = {"status": vis_status, "accuracy": vis_acc, "detail": vis_detail}

    # 3. Bracelet placement
    placement_status = "PASS"
    placement_detail = f"Bracelet is positioned around the {wrist_side} wrist."
    if on_palm:
        placement_status = "FAIL"
        placement_detail = "Bracelet is positioned on the palm."
    elif on_fingers:
        placement_status = "FAIL"
        placement_detail = "Bracelet is positioned on the fingers."
    elif too_far_forearm:
        placement_status = "FAIL"
        placement_detail = "Bracelet is incorrectly placed too far up the forearm."
    elif floating:
        placement_status = "FAIL"
        placement_detail = "Bracelet is floating above or away from the wrist."
    elif bracelet_to_wrist > fail_threshold:
        placement_status = "FAIL"
        placement_detail = "Bracelet placement error exceeds the fail threshold."
    elif bracelet_to_wrist > pass_threshold:
        placement_status = "WARNING"
        placement_detail = "Bracelet is near the wrist but outside the pass threshold."
    checks["bracelet_placement"] = {
        "status": placement_status,
        "accuracy": _accuracy_from_error(bracelet_to_wrist, fail_threshold),
        "detail": placement_detail,
        "normalized_distance": bracelet_to_wrist,
        "style": style,
    }

    # 4. Wrist alignment
    align_error = abs(across) / width
    align_status = _status_from_error(align_error, pass_threshold, fail_threshold)
    if floating or on_palm or on_fingers:
        align_status = "FAIL"
    checks["wrist_alignment"] = {
        "status": align_status,
        "accuracy": _accuracy_from_error(align_error, fail_threshold),
        "detail": (
            "Bracelet follows the natural wrist orientation."
            if align_status == "PASS"
            else "Bracelet is significantly misaligned with the wrist."
            if align_status == "FAIL"
            else "Bracelet is slightly off the wrist axis."
        ),
        "error": align_error,
    }

    # 5. Center alignment
    center_status = _status_from_error(bracelet_to_wrist, pass_threshold, fail_threshold)
    checks["bracelet_center_alignment"] = {
        "status": center_status,
        "accuracy": _accuracy_from_error(bracelet_to_wrist, fail_threshold),
        "detail": (
            "Bracelet center aligns with the wrist center."
            if center_status == "PASS"
            else "Bracelet center is significantly misaligned with the wrist center."
            if center_status == "FAIL"
            else "Bracelet center is slightly off the wrist center."
        ),
        "error": bracelet_to_wrist,
        "raw_center_distance": raw / width,
    }

    # 6. Wrist coverage
    coverage = max(0.0, 1.0 - bracelet_to_wrist)
    cov_min, cov_max = tolerances["coverage_min"], tolerances["coverage_max"]
    if coverage < cov_min - 0.25 or floating:
        coverage_status = "FAIL"
        coverage_detail = "Bracelet appears detached and does not cover the wrist."
    elif coverage < cov_min:
        coverage_status = "WARNING"
        coverage_detail = "Bracelet only partially covers the wrist area."
    elif coverage > cov_max and abs(across) > across_allow:
        coverage_status = "WARNING"
        coverage_detail = "Bracelet coverage is unusually wide for this style."
    else:
        coverage_status = "PASS"
        coverage_detail = "Bracelet appropriately covers the wrist area."
    checks["wrist_coverage"] = {
        "status": coverage_status,
        "accuracy": float(max(0.0, min(1.0, coverage))),
        "detail": coverage_detail,
        "coverage": coverage,
    }

    # 7. Bracelet-to-wrist distance
    distance_status = _status_from_error(bracelet_to_wrist, pass_threshold, fail_threshold)
    checks["bracelet_to_wrist_distance"] = {
        "status": distance_status,
        "accuracy": _accuracy_from_error(bracelet_to_wrist, fail_threshold),
        "detail": f"Normalized bracelet-to-wrist distance is {bracelet_to_wrist:.3f} (style={style}).",
        "normalized_distance": bracelet_to_wrist,
        "raw_distance": raw,
        "wrist_width": width,
    }

    # 8. Hand clearance
    checks["hand_clearance"] = {
        "status": "FAIL" if (on_palm or on_fingers) else "PASS",
        "accuracy": 0.0 if (on_palm or on_fingers) else 1.0,
        "detail": (
            "Bracelet incorrectly sits on the palm or fingers."
            if (on_palm or on_fingers)
            else "Bracelet clears the palm and fingers."
        ),
    }

    # 9. Forearm clearance
    checks["forearm_clearance"] = {
        "status": "FAIL" if too_far_forearm else "PASS",
        "accuracy": 0.0 if too_far_forearm else 1.0,
        "detail": (
            "Bracelet is too far up the forearm."
            if too_far_forearm
            else "Bracelet clears the upper forearm and stays near the wrist joint."
        ),
    }

    # 10. Orientation
    orient_error = 0.0
    orient_status = "PASS"
    orient_detail = "Bracelet is naturally aligned around the wrist."
    if jewelry.rotation is not None:
        rot = abs(float(jewelry.rotation)) % 180.0
        tilt = min(rot, 180.0 - rot)
        orient_error = tilt / 90.0
        if tilt > 55:
            orient_status = "FAIL"
            orient_detail = "Bracelet is floating or unnaturally tilted."
        elif tilt > 30:
            orient_status = "WARNING"
            orient_detail = "Bracelet is slightly tilted."
    elif floating:
        orient_status = "FAIL"
        orient_detail = "Bracelet is floating or unnaturally tilted."
        orient_error = bracelet_to_wrist
    elif align_error > fail_threshold:
        orient_status = "FAIL"
        orient_detail = "Bracelet orientation does not follow the wrist."
        orient_error = align_error
    elif align_error > pass_threshold:
        orient_status = "WARNING"
        orient_detail = "Bracelet is slightly tilted relative to the wrist."
        orient_error = align_error
    checks["bracelet_orientation"] = {
        "status": orient_status,
        "accuracy": _accuracy_from_error(orient_error, fail_threshold * 2.0),
        "detail": orient_detail,
        "error": orient_error,
    }

    return _finalize(checks, geometry, jewelry, wrist_side, style, pass_threshold, fail_threshold)


def _finalize(
    checks: dict[str, dict],
    geometry: WristGeometry | None,
    jewelry: EarringAnchor | None,
    side: str,
    style: str,
    pass_threshold: float,
    fail_threshold: float,
) -> dict:
    required = [
        "wrist_detection",
        "wrist_landmark_detection",
        "bracelet_placement",
        "wrist_alignment",
        "bracelet_center_alignment",
        "wrist_coverage",
        "hand_clearance",
        "forearm_clearance",
    ]
    hard = []
    for key in required:
        status = checks.get(key, {}).get("status", "FAIL")
        if key == "wrist_detection" and status == "WARNING":
            continue
        hard.append(status)
    status = _combine(*hard) if hard else "FAIL"
    if checks.get("wrist_detection", {}).get("status") == "WARNING" and status == "PASS":
        status = "WARNING"
    if checks.get("bracelet_visibility", {}).get("status") == "WARNING" and status == "PASS":
        status = "WARNING"
    if checks.get("bracelet_placement", {}).get("status") == "FAIL":
        status = "FAIL"

    accuracies = {
        "wrist_detection_accuracy": float(checks.get("wrist_detection", {}).get("accuracy", 0.0)),
        "wrist_landmark_accuracy": float(checks.get("wrist_landmark_detection", {}).get("accuracy", 0.0)),
        "bracelet_placement_accuracy": float(checks.get("bracelet_placement", {}).get("accuracy", 0.0)),
        "wrist_alignment_accuracy": float(checks.get("wrist_alignment", {}).get("accuracy", 0.0)),
        "bracelet_center_alignment_accuracy": float(checks.get("bracelet_center_alignment", {}).get("accuracy", 0.0)),
        "wrist_coverage_accuracy": float(checks.get("wrist_coverage", {}).get("accuracy", 0.0)),
        "bracelet_orientation_accuracy": float(checks.get("bracelet_orientation", {}).get("accuracy", 0.0)),
    }
    overall = sum(accuracies.values()) / len(accuracies)

    reasons = [checks[key]["detail"] for key in required if checks.get(key, {}).get("status") == "FAIL"]
    if not reasons and status == "WARNING":
        reasons = [checks[key]["detail"] for key in checks if checks[key]["status"] == "WARNING"]
    if status == "PASS":
        reason = (
            f"{style.capitalize()} bracelet is positioned around the {side} wrist, "
            "aligned with the wrist center, and naturally fitted."
        )
    else:
        reason = " ".join(reasons) or "Bracelet lay validation failed."

    return {
        "status": status,
        "final_result": status,
        "reason": reason,
        "wrist_side": side,
        "bracelet_style": style,
        "checks": {
            "wrist_detection": checks.get("wrist_detection", {}).get("status", "FAIL"),
            "wrist_landmark_detection": checks.get("wrist_landmark_detection", {}).get("status", "FAIL"),
            "bracelet_placement": checks.get("bracelet_placement", {}).get("status", "FAIL"),
            "wrist_alignment": checks.get("wrist_alignment", {}).get("status", "FAIL"),
            "bracelet_center_alignment": checks.get("bracelet_center_alignment", {}).get("status", "FAIL"),
            "wrist_coverage": checks.get("wrist_coverage", {}).get("status", "FAIL"),
            "bracelet_to_wrist_distance": checks.get("bracelet_to_wrist_distance", {}).get("status", "FAIL"),
            "hand_clearance": checks.get("hand_clearance", {}).get("status", "FAIL"),
            "forearm_clearance": checks.get("forearm_clearance", {}).get("status", "FAIL"),
            "bracelet_orientation": checks.get("bracelet_orientation", {}).get("status", "FAIL"),
            "bracelet_visibility": checks.get("bracelet_visibility", {}).get("status", "FAIL"),
        },
        "check_details": checks,
        "accuracies": {
            **accuracies,
            "overall_bracelet_lay_accuracy": overall,
        },
        "overall_bracelet_lay_accuracy_pct": round(overall * 100.0, 1),
        "geometry": None
        if geometry is None
        else {
            "side": geometry.side,
            "center": {"x": geometry.center_x, "y": geometry.center_y},
            "width": geometry.width,
            "source": geometry.source,
            "style": geometry.style,
        },
        "thresholds": {
            "pass_threshold": pass_threshold,
            "fail_threshold": fail_threshold,
        },
        "jewelry_visible": bool(jewelry and jewelry.visible),
        "note": (
            "Accuracy values are geometric agreement with the expected wrist model, "
            "not detection confidence. Style-specific tolerances are applied for chain, "
            "bangle, tennis, and cuff bracelets. Manual reviews feed ground-truth accuracy separately."
        ),
    }


def measurement_from_bracelet_lay(lay: dict, base: PlacementMeasurement | None = None) -> PlacementMeasurement:
    details = (lay.get("check_details") or {}).get("bracelet_to_wrist_distance") or {}
    normalized = details.get("normalized_distance")
    return PlacementMeasurement(
        dx=base.dx if base else None,
        dy=base.dy if base else None,
        distance=details.get("raw_distance", base.distance if base else None),
        normalized_distance=normalized if normalized is not None else (base.normalized_distance if base else None),
        status=str(lay.get("status") or "FAIL"),
        reason=str(lay.get("reason") or "Bracelet lay failed."),
        earlobe_confidence=base.earlobe_confidence if base else 0.0,
        earring_confidence=base.earring_confidence if base else 0.0,
        inside_zone=bool(
            normalized is not None
            and normalized <= float((lay.get("thresholds") or {}).get("fail_threshold", 0.18))
        ),
    )


def aggregate_bracelet_lay(frame_lays: list[dict], *, manual_statuses: list[str] | None = None) -> dict:
    empty_checks = {
        "wrist_detection": "FAIL",
        "wrist_landmark_detection": "FAIL",
        "bracelet_placement": "FAIL",
        "wrist_alignment": "FAIL",
        "bracelet_center_alignment": "FAIL",
        "wrist_coverage": "FAIL",
        "hand_clearance": "FAIL",
        "forearm_clearance": "FAIL",
    }
    if not frame_lays:
        return {
            "status": "FAIL",
            "final_result": "FAIL",
            "overall_bracelet_lay_accuracy_pct": 0.0,
            "checks": empty_checks,
            "accuracies": {
                "wrist_detection_accuracy": 0.0,
                "wrist_landmark_accuracy": 0.0,
                "bracelet_placement_accuracy": 0.0,
                "wrist_alignment_accuracy": 0.0,
                "bracelet_center_alignment_accuracy": 0.0,
                "wrist_coverage_accuracy": 0.0,
                "bracelet_orientation_accuracy": 0.0,
                "overall_bracelet_lay_accuracy": 0.0,
            },
            "reason": "No bracelet frames were evaluated.",
            "ground_truth_accuracy_pct": None,
            "wrist_side": "left",
            "bracelet_style": "default",
            "note": "Accuracy is geometric vs expected wrist model, not confidence.",
        }

    def worst(values: list[str]) -> str:
        if any(value == "FAIL" for value in values):
            return "FAIL"
        if any(value == "WARNING" for value in values):
            return "WARNING"
        return "PASS"

    check_keys = list(empty_checks.keys())
    checks = {
        key: worst([str((item.get("checks") or {}).get(key, "FAIL")) for item in frame_lays]) for key in check_keys
    }
    accuracy_keys = [
        "wrist_detection_accuracy",
        "wrist_landmark_accuracy",
        "bracelet_placement_accuracy",
        "wrist_alignment_accuracy",
        "bracelet_center_alignment_accuracy",
        "wrist_coverage_accuracy",
        "bracelet_orientation_accuracy",
        "overall_bracelet_lay_accuracy",
    ]
    accuracies = {}
    for key in accuracy_keys:
        values = [float((item.get("accuracies") or {}).get(key, 0.0)) for item in frame_lays]
        accuracies[key] = sum(values) / len(values) if values else 0.0

    status = worst([str(item.get("status", "FAIL")) for item in frame_lays])
    if checks["bracelet_placement"] == "FAIL" or checks["wrist_detection"] == "FAIL":
        status = "FAIL"

    ground_truth_pct = None
    if manual_statuses:
        paired = [(auto.get("status"), manual) for auto, manual in zip(frame_lays, manual_statuses) if manual]
        if paired:
            matches = sum(1 for auto, manual in paired if auto == manual)
            ground_truth_pct = round(100.0 * matches / len(paired), 1)

    wrist_side = next((str(item.get("wrist_side")) for item in frame_lays if item.get("wrist_side")), "left")
    style = next((str(item.get("bracelet_style")) for item in frame_lays if item.get("bracelet_style")), "default")
    reason = (
        f"{style.capitalize()} bracelet is positioned around the {wrist_side} wrist and naturally fitted."
        if status == "PASS"
        else next(
            (str(item.get("reason")) for item in frame_lays if item.get("status") == "FAIL"),
            "Bracelet lay did not meet wrist placement rules.",
        )
    )
    return {
        "status": status,
        "final_result": status,
        "wrist_side": wrist_side,
        "bracelet_style": style,
        "checks": checks,
        "accuracies": accuracies,
        "overall_bracelet_lay_accuracy_pct": round(accuracies["overall_bracelet_lay_accuracy"] * 100.0, 1),
        "ground_truth_accuracy_pct": ground_truth_pct,
        "frames_evaluated": len(frame_lays),
        "reason": reason,
        "note": (
            "Overall bracelet lay accuracy is the mean geometric agreement with the expected wrist model. "
            "Detection confidence is not used as accuracy. Style-specific tolerances apply. "
            "ground_truth_accuracy_pct is set only when manual frame reviews exist."
        ),
    }
