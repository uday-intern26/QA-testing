"""Ring lay detection: finger placement checks used only for jewelry_type=ring."""

from __future__ import annotations

from dataclasses import dataclass

from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, PlacementMeasurement
from app.utils.geometry import distance, normalize_distance, offset

FINGER_NAMES = ("thumb", "index", "middle", "ring", "little")

# Relative placement along a hand-proxy axis (0=wrist/base, 1=fingertip).
FINGER_SLOT = {
    "thumb": {"along": 0.35, "across": -0.85, "span": 0.55},
    "index": {"along": 0.55, "across": -0.45, "span": 0.45},
    "middle": {"along": 0.58, "across": -0.05, "span": 0.45},
    "ring": {"along": 0.55, "across": 0.35, "span": 0.45},
    "little": {"along": 0.48, "across": 0.75, "span": 0.40},
}


@dataclass
class FingerGeometry:
    finger: str
    hand_confidence: float
    base_x: float
    base_y: float
    mid_x: float
    mid_y: float
    tip_x: float
    tip_y: float
    center_x: float
    center_y: float
    knuckle_x: float
    knuckle_y: float
    direction_x: float
    direction_y: float
    width: float
    palm_x: float
    palm_y: float
    adjacent: list[tuple[float, float]]
    source: str


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


def _normalize_finger(selected_finger: str | None) -> str:
    value = (selected_finger or "ring").strip().lower().replace(" finger", "").replace("-", "_")
    aliases = {
        "thumb": "thumb",
        "index": "index",
        "pointer": "index",
        "middle": "middle",
        "ring": "ring",
        "little": "little",
        "pinky": "little",
        "pinkie": "little",
    }
    return aliases.get(value, "ring")


def _hand_from_debug(debug_state: dict | None) -> dict | None:
    if not isinstance(debug_state, dict):
        return None
    for key in ("hand", "hands", "hand_landmarks", "ring_hand"):
        value = debug_state.get(key)
        if isinstance(value, dict) and value:
            return value
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                return first
    return None


def _finger_point(hand: dict, names: tuple[str, ...]) -> tuple[float, float] | None:
    for name in names:
        point = hand.get(name)
        if isinstance(point, dict) and point.get("x") is not None and point.get("y") is not None:
            return float(point["x"]), float(point["y"])
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            return float(point[0]), float(point[1])
    fingers = hand.get("fingers")
    if isinstance(fingers, dict):
        for name in names:
            point = fingers.get(name)
            if isinstance(point, dict) and point.get("x") is not None and point.get("y") is not None:
                return float(point["x"]), float(point["y"])
    return None


def finger_geometry_from_hand(
    hand: dict,
    selected_finger: str,
) -> FingerGeometry | None:
    finger = _normalize_finger(selected_finger)
    confidence = float(hand.get("confidence") or hand.get("score") or 0.85)
    wrist = _finger_point(hand, ("wrist", "palm", "palm_center"))
    tips = {
        "thumb": _finger_point(hand, ("thumb_tip", "thumb")),
        "index": _finger_point(hand, ("index_tip", "index")),
        "middle": _finger_point(hand, ("middle_tip", "middle")),
        "ring": _finger_point(hand, ("ring_tip", "ring")),
        "little": _finger_point(hand, ("little_tip", "pinky_tip", "pinky", "little")),
    }
    pip = {
        "thumb": _finger_point(hand, ("thumb_ip", "thumb_pip")),
        "index": _finger_point(hand, ("index_pip",)),
        "middle": _finger_point(hand, ("middle_pip",)),
        "ring": _finger_point(hand, ("ring_pip",)),
        "little": _finger_point(hand, ("little_pip", "pinky_pip")),
    }
    mcp = {
        "thumb": _finger_point(hand, ("thumb_mcp", "thumb_cmc")),
        "index": _finger_point(hand, ("index_mcp",)),
        "middle": _finger_point(hand, ("middle_mcp",)),
        "ring": _finger_point(hand, ("ring_mcp",)),
        "little": _finger_point(hand, ("little_mcp", "pinky_mcp")),
    }
    tip = tips.get(finger)
    base = mcp.get(finger) or wrist
    mid = pip.get(finger)
    if tip is None or base is None:
        return None
    if mid is None:
        mid = ((base[0] + tip[0]) / 2.0, (base[1] + tip[1]) / 2.0)
    # Natural ring seat: between base (MCP) and middle knuckle (PIP)
    center = (
        base[0] * 0.55 + mid[0] * 0.45,
        base[1] * 0.55 + mid[1] * 0.45,
    )
    knuckle = mid
    dx, dy = tip[0] - base[0], tip[1] - base[1]
    length = max(1e-6, distance(dx, dy))
    direction = (dx / length, dy / length)
    width = max(0.02, length * 0.18)
    palm = wrist or ((base[0] + tip[0]) / 2.0, (base[1] + tip[1]) / 2.0)
    adjacent = []
    order = list(FINGER_NAMES)
    idx = order.index(finger)
    for neighbor in order[max(0, idx - 1) : idx] + order[idx + 1 : idx + 2]:
        point = mcp.get(neighbor) or tips.get(neighbor)
        if point:
            adjacent.append(point)
    return FingerGeometry(
        finger=finger,
        hand_confidence=confidence,
        base_x=float(base[0]),
        base_y=float(base[1]),
        mid_x=float(mid[0]),
        mid_y=float(mid[1]),
        tip_x=float(tip[0]),
        tip_y=float(tip[1]),
        center_x=float(center[0]),
        center_y=float(center[1]),
        knuckle_x=float(knuckle[0]),
        knuckle_y=float(knuckle[1]),
        direction_x=float(direction[0]),
        direction_y=float(direction[1]),
        width=float(width),
        palm_x=float(palm[0]),
        palm_y=float(palm[1]),
        adjacent=adjacent,
        source="hand_landmarks",
    )


def finger_geometry_from_proxy(
    finger_anchor: EarlobeAnchor | None,
    selected_finger: str,
    side: str = "left",
) -> FingerGeometry | None:
    """Build finger geometry from the face/hand proxy when MediaPipe Hands is unavailable."""
    if finger_anchor is None:
        return None
    finger = _normalize_finger(selected_finger)
    slot = FINGER_SLOT[finger]
    width = max(0.02, float(finger_anchor.ear_width))
    # Proxy hand occupies a band below/ beside the face estimate.
    palm_x = float(finger_anchor.x)
    palm_y = float(finger_anchor.y)
    across = slot["across"] if side != "right" else -slot["across"]
    tip_x = palm_x + across * width * 1.1
    tip_y = palm_y + slot["along"] * width * 2.2
    base_x = palm_x + across * width * 0.35
    base_y = palm_y + slot["along"] * width * 0.55
    mid_x = (base_x + tip_x) / 2.0
    mid_y = (base_y + tip_y) / 2.0
    center_x = base_x * 0.55 + mid_x * 0.45
    center_y = base_y * 0.55 + mid_y * 0.45
    dx, dy = tip_x - base_x, tip_y - base_y
    length = max(1e-6, distance(dx, dy))
    direction = (dx / length, dy / length)
    adjacent = []
    order = list(FINGER_NAMES)
    idx = order.index(finger)
    for neighbor in order[max(0, idx - 1) : idx] + order[idx + 1 : idx + 2]:
        nslot = FINGER_SLOT[neighbor]
        nacross = nslot["across"] if side != "right" else -nslot["across"]
        adjacent.append((palm_x + nacross * width * 0.35, palm_y + nslot["along"] * width * 0.55))
    return FingerGeometry(
        finger=finger,
        hand_confidence=float(finger_anchor.confidence),
        base_x=base_x,
        base_y=base_y,
        mid_x=mid_x,
        mid_y=mid_y,
        tip_x=tip_x,
        tip_y=tip_y,
        center_x=center_x,
        center_y=center_y,
        knuckle_x=mid_x,
        knuckle_y=mid_y,
        direction_x=float(direction[0]),
        direction_y=float(direction[1]),
        width=width * float(slot["span"]),
        palm_x=palm_x,
        palm_y=palm_y,
        adjacent=adjacent,
        source="hand_proxy",
    )


def resolve_finger_geometry(
    *,
    selected_finger: str,
    finger_anchor: EarlobeAnchor | None,
    face: FaceLandmarkResult | None,
    debug_state: dict | None,
    side: str,
) -> FingerGeometry | None:
    hand = _hand_from_debug(debug_state)
    if hand is not None:
        geometry = finger_geometry_from_hand(hand, selected_finger)
        if geometry is not None:
            return geometry
    _ = face  # reserved for future hand-from-face refinements
    return finger_geometry_from_proxy(finger_anchor, selected_finger, side=side)


def evaluate_ring_lay(
    face: FaceLandmarkResult | None,
    finger_anchor: EarlobeAnchor | None,
    jewelry: EarringAnchor | None,
    *,
    config: dict,
    selected_finger: str = "ring",
    side: str = "left",
    debug_state: dict | None = None,
) -> dict:
    """
    Measure ring lay around the selected finger.

    Only intended for jewelry_type == \"ring\". Accuracy scores are geometric
    agreement with the expected finger-base model, not detection confidence.
    """
    minimum_confidence = float(config.get("minimum_confidence", 0.80))
    pass_threshold = float(config.get("pass_threshold", 0.08))
    fail_threshold = float(config.get("fail_threshold", 0.15))
    zone_y_scale = float(config.get("zone_y_scale", 1.0))
    finger = _normalize_finger(selected_finger or config.get("selected_finger"))

    geometry = resolve_finger_geometry(
        selected_finger=finger,
        finger_anchor=finger_anchor,
        face=face,
        debug_state=debug_state,
        side=side if side in {"left", "right"} else "left",
    )
    checks: dict[str, dict] = {}

    # 1. Hand detection
    if geometry is None:
        checks["hand_detection"] = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": "Hand was not detected.",
        }
    elif geometry.hand_confidence < minimum_confidence:
        checks["hand_detection"] = {
            "status": "WARNING",
            "accuracy": 0.0,
            "detail": (
                f"Hand confidence {geometry.hand_confidence:.2f} is below {minimum_confidence:.2f} "
                "(partial visibility or occlusion)."
            ),
            "confidence": geometry.hand_confidence,
        }
    else:
        checks["hand_detection"] = {
            "status": "PASS",
            "accuracy": 1.0,
            "detail": f"Hand detected ({geometry.source}) with confidence {geometry.hand_confidence:.2f}.",
            "confidence": geometry.hand_confidence,
        }

    # 2. Finger identification
    if geometry is None:
        checks["selected_finger_detection"] = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": f"Selected finger '{finger}' could not be identified.",
        }
    else:
        checks["selected_finger_detection"] = {
            "status": "PASS",
            "accuracy": 1.0,
            "detail": f"Selected finger identified as {finger}.",
            "finger": finger,
        }

    jewelry_ok = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
    if not jewelry_ok or geometry is None:
        fail = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": "Ring attachment point was not detected." if geometry else "Cannot score ring lay without a hand/finger estimate.",
        }
        for key in (
            "ring_placement",
            "finger_alignment",
            "ring_center_alignment",
            "finger_base_position",
            "knuckle_clearance",
            "ring_to_finger_distance",
            "ring_visibility",
            "adjacent_finger_clearance",
            "ring_orientation",
        ):
            checks[key] = dict(fail)
        if jewelry_ok is False:
            checks["ring_visibility"] = {
                "status": "FAIL",
                "accuracy": 0.0,
                "detail": "Ring is not sufficiently visible for accurate detection.",
            }
        return _finalize(checks, geometry, jewelry, finger, pass_threshold, fail_threshold)

    assert jewelry is not None and jewelry.x is not None and jewelry.y is not None
    jx, jy = float(jewelry.x), float(jewelry.y)
    width = max(0.02, geometry.width)

    dx, dy = offset(jx, jy, geometry.center_x, geometry.center_y)
    raw = distance(dx, dy)
    # Allow small travel along the finger axis between base and mid-knuckle.
    along = dx * geometry.direction_x + dy * geometry.direction_y
    across = dx * (-geometry.direction_y) + dy * geometry.direction_x
    # Clamp along-finger to natural seat band, then residual error is outside the band.
    seat_min = -0.15 * width
    seat_max = distance(geometry.mid_x - geometry.base_x, geometry.mid_y - geometry.base_y) * 0.85
    along_clamped = min(max(along, seat_min), seat_max)
    residual_along = along - along_clamped
    ring_to_finger = normalize_distance(across, residual_along, width, zone_y_scale)

    # Palm / fingertip / wrong-finger zones
    palm_dist = distance(jx - geometry.palm_x, jy - geometry.palm_y) / width
    tip_dist = distance(jx - geometry.tip_x, jy - geometry.tip_y) / width
    knuckle_dist = distance(jx - geometry.knuckle_x, jy - geometry.knuckle_y) / width
    base_dist = distance(jx - geometry.base_x, jy - geometry.base_y) / width
    on_palm = palm_dist < 0.85 and along < -0.35 * width
    floating = ring_to_finger > fail_threshold and abs(across) > 0.55 * width
    over_knuckle = knuckle_dist < 0.35 and abs(along - seat_max) < 0.25 * width and ring_to_finger > pass_threshold
    near_tip = tip_dist < 0.45 and along > seat_max

    # Adjacent finger overlap
    adjacent_hit = False
    for ax, ay in geometry.adjacent:
        if distance(jx - ax, jy - ay) < 0.55 * width and abs(across) > 0.45 * width:
            adjacent_hit = True
            break

    # 9. Visibility
    if not jewelry.visible:
        vis_status, vis_detail = "FAIL", "Ring is not visible."
        vis_acc = 0.0
    elif jewelry.confidence < minimum_confidence:
        vis_status, vis_detail = "WARNING", "Ring detection confidence is insufficient or the ring is partially covered."
        vis_acc = 0.5
    elif jx < 0.02 or jx > 0.98 or jy < 0.02 or jy > 0.98:
        vis_status, vis_detail = "WARNING", "Ring is partially outside the camera frame."
        vis_acc = 0.5
    else:
        vis_status, vis_detail = "PASS", "Ring is sufficiently visible for detection."
        vis_acc = 1.0
    checks["ring_visibility"] = {"status": vis_status, "accuracy": vis_acc, "detail": vis_detail}

    # 3. Ring placement
    placement_status = "PASS"
    placement_detail = f"Ring is positioned around the {finger} finger."
    if on_palm:
        placement_status = "FAIL"
        placement_detail = "Ring is placed on the palm."
    elif adjacent_hit:
        placement_status = "FAIL"
        placement_detail = "Ring is placed across multiple fingers / overlaps an adjacent finger."
    elif floating:
        placement_status = "FAIL"
        placement_detail = "Ring is floating above or away from the finger."
    elif near_tip:
        placement_status = "FAIL"
        placement_detail = "Ring is incorrectly positioned toward the fingertip instead of the finger base."
    elif over_knuckle:
        placement_status = "FAIL"
        placement_detail = "Ring is incorrectly positioned over the knuckle."
    elif ring_to_finger > fail_threshold:
        placement_status = "FAIL"
        placement_detail = "Ring placement error exceeds the fail threshold."
    elif ring_to_finger > pass_threshold:
        placement_status = "WARNING"
        placement_detail = "Ring is near the selected finger but outside the pass threshold."
    checks["ring_placement"] = {
        "status": placement_status,
        "accuracy": _accuracy_from_error(ring_to_finger, fail_threshold),
        "detail": placement_detail,
        "normalized_distance": ring_to_finger,
    }

    # 4. Finger alignment (follow finger direction)
    # Across-finger error dominates alignment; along-seat is tolerated.
    align_error = abs(across) / width
    align_status = _status_from_error(align_error, pass_threshold, fail_threshold)
    if floating or adjacent_hit:
        align_status = "FAIL"
    checks["finger_alignment"] = {
        "status": align_status,
        "accuracy": _accuracy_from_error(align_error, fail_threshold),
        "detail": (
            "Ring follows the natural direction of the finger."
            if align_status == "PASS"
            else "Ring is significantly misaligned with the finger."
            if align_status == "FAIL"
            else "Ring is slightly off the finger axis."
        ),
        "error": align_error,
    }

    # 5. Ring center alignment
    center_error = raw / width
    # Prefer residual outside seat, not raw distance to center for dangly gem offsets
    center_metric = ring_to_finger
    center_status = _status_from_error(center_metric, pass_threshold, fail_threshold)
    checks["ring_center_alignment"] = {
        "status": center_status,
        "accuracy": _accuracy_from_error(center_metric, fail_threshold),
        "detail": (
            "Ring center aligns with the selected finger center."
            if center_status == "PASS"
            else "Ring center is significantly misaligned with the finger center."
            if center_status == "FAIL"
            else "Ring center is slightly off the finger center."
        ),
        "error": center_metric,
        "raw_center_distance": center_error,
    }

    # 6. Finger base position
    base_status = "PASS"
    base_detail = "Ring sits naturally near the base of the selected finger."
    if along < -0.4 * width or on_palm:
        base_status = "FAIL"
        base_detail = "Ring is not near the natural base of the finger."
    elif along > seat_max + 0.35 * width:
        base_status = "FAIL"
        base_detail = "Ring is too far from the finger base toward the tip."
    elif abs(residual_along) / width > pass_threshold and abs(residual_along) / width <= fail_threshold:
        base_status = "WARNING"
        base_detail = "Ring is slightly away from the natural base seat."
    base_error = abs(residual_along) / width
    checks["finger_base_position"] = {
        "status": base_status,
        "accuracy": _accuracy_from_error(base_error, fail_threshold),
        "detail": base_detail,
        "error": base_error,
    }

    # 7. Knuckle clearance
    if over_knuckle:
        knuckle_status, knuckle_detail, knuckle_acc = "FAIL", "Ring sits on the knuckle.", 0.0
    else:
        # Higher distance from knuckle (while still on finger) is better once past the seat
        knuckle_clear = max(0.0, knuckle_dist - 0.25)
        knuckle_acc = float(max(0.0, min(1.0, knuckle_clear / max(fail_threshold * 2.0, 1e-6))))
        knuckle_status = "PASS" if knuckle_dist >= 0.35 or base_dist <= knuckle_dist else "WARNING"
        knuckle_detail = (
            "Ring clears the knuckle and sits on the finger shaft."
            if knuckle_status == "PASS"
            else "Ring is close to the knuckle."
        )
    checks["knuckle_clearance"] = {
        "status": knuckle_status,
        "accuracy": knuckle_acc,
        "detail": knuckle_detail,
    }

    # 8. Ring-to-finger distance
    distance_status = _status_from_error(ring_to_finger, pass_threshold, fail_threshold)
    checks["ring_to_finger_distance"] = {
        "status": distance_status,
        "accuracy": _accuracy_from_error(ring_to_finger, fail_threshold),
        "detail": f"Normalized ring-to-finger distance is {ring_to_finger:.3f}.",
        "normalized_distance": ring_to_finger,
        "raw_distance": raw,
        "finger_width": width,
    }

    # 10. Adjacent finger clearance
    checks["adjacent_finger_clearance"] = {
        "status": "FAIL" if adjacent_hit else "PASS",
        "accuracy": 0.0 if adjacent_hit else 1.0,
        "detail": (
            "Ring incorrectly overlaps an adjacent finger."
            if adjacent_hit
            else "Ring clears adjacent fingers."
        ),
    }

    # 11. Ring orientation
    orient_error = 0.0
    orient_status = "PASS"
    orient_detail = "Ring is aligned naturally around the finger."
    if jewelry.rotation is not None:
        # Expect band roughly perpendicular to finger; treat huge tilt as warning/fail
        rot = abs(float(jewelry.rotation)) % 180.0
        tilt = min(rot, 180.0 - rot)
        # Ideal ~90° to finger axis is unknown in 2D; use small absolute tilt from published rotation
        orient_error = tilt / 90.0
        if tilt > 55:
            orient_status = "FAIL"
            orient_detail = "Ring is rotated or tilted incorrectly."
        elif tilt > 30:
            orient_status = "WARNING"
            orient_detail = "Ring is slightly tilted."
    elif abs(across) / width > fail_threshold:
        orient_status = "FAIL"
        orient_detail = "Ring orientation does not follow the finger."
        orient_error = abs(across) / width
    elif abs(across) / width > pass_threshold:
        orient_status = "WARNING"
        orient_detail = "Ring is slightly tilted relative to the finger."
        orient_error = abs(across) / width
    checks["ring_orientation"] = {
        "status": orient_status,
        "accuracy": _accuracy_from_error(orient_error, fail_threshold * 2.0),
        "detail": orient_detail,
        "error": orient_error,
    }

    return _finalize(checks, geometry, jewelry, finger, pass_threshold, fail_threshold)


def _finalize(
    checks: dict[str, dict],
    geometry: FingerGeometry | None,
    jewelry: EarringAnchor | None,
    finger: str,
    pass_threshold: float,
    fail_threshold: float,
) -> dict:
    required = [
        "hand_detection",
        "selected_finger_detection",
        "ring_placement",
        "finger_alignment",
        "ring_center_alignment",
        "knuckle_clearance",
        "ring_orientation",
    ]
    hard = [checks[key]["status"] for key in required if key in checks]
    # Treat hand WARNING as soft unless placement fails
    normalized = []
    for key, status in zip(required, hard):
        if key == "hand_detection" and status == "WARNING":
            continue
        normalized.append(status)
    status = _combine(*normalized) if normalized else "FAIL"
    if checks.get("hand_detection", {}).get("status") == "WARNING" and status == "PASS":
        status = "WARNING"
    if checks.get("ring_visibility", {}).get("status") == "WARNING" and status == "PASS":
        status = "WARNING"
    if checks.get("ring_placement", {}).get("status") == "FAIL":
        status = "FAIL"

    accuracies = {
        "hand_detection_accuracy": float(checks.get("hand_detection", {}).get("accuracy", 0.0)),
        "finger_detection_accuracy": float(checks.get("selected_finger_detection", {}).get("accuracy", 0.0)),
        "ring_placement_accuracy": float(checks.get("ring_placement", {}).get("accuracy", 0.0)),
        "finger_alignment_accuracy": float(checks.get("finger_alignment", {}).get("accuracy", 0.0)),
        "ring_center_alignment_accuracy": float(checks.get("ring_center_alignment", {}).get("accuracy", 0.0)),
        "knuckle_clearance_accuracy": float(checks.get("knuckle_clearance", {}).get("accuracy", 0.0)),
        "ring_orientation_accuracy": float(checks.get("ring_orientation", {}).get("accuracy", 0.0)),
    }
    overall = sum(accuracies.values()) / len(accuracies)

    reasons = [checks[key]["detail"] for key in required if checks.get(key, {}).get("status") == "FAIL"]
    if not reasons and status == "WARNING":
        reasons = [checks[key]["detail"] for key in checks if checks[key]["status"] == "WARNING"]
    if status == "PASS":
        reason = (
            f"Ring is worn around the {finger} finger, aligned with the finger center, "
            "and seated naturally near the finger base."
        )
    else:
        reason = " ".join(reasons) or "Ring lay validation failed."

    return {
        "status": status,
        "final_result": status,
        "reason": reason,
        "selected_finger": finger,
        "checks": {
            "hand_detection": checks.get("hand_detection", {}).get("status", "FAIL"),
            "selected_finger_detection": checks.get("selected_finger_detection", {}).get("status", "FAIL"),
            "ring_placement": checks.get("ring_placement", {}).get("status", "FAIL"),
            "finger_alignment": checks.get("finger_alignment", {}).get("status", "FAIL"),
            "ring_center_alignment": checks.get("ring_center_alignment", {}).get("status", "FAIL"),
            "finger_base_position": checks.get("finger_base_position", {}).get("status", "FAIL"),
            "knuckle_clearance": checks.get("knuckle_clearance", {}).get("status", "FAIL"),
            "ring_to_finger_distance": checks.get("ring_to_finger_distance", {}).get("status", "FAIL"),
            "ring_visibility": checks.get("ring_visibility", {}).get("status", "FAIL"),
            "adjacent_finger_clearance": checks.get("adjacent_finger_clearance", {}).get("status", "FAIL"),
            "ring_orientation": checks.get("ring_orientation", {}).get("status", "FAIL"),
        },
        "check_details": checks,
        "accuracies": {
            **accuracies,
            "overall_ring_lay_accuracy": overall,
        },
        "overall_ring_lay_accuracy_pct": round(overall * 100.0, 1),
        "geometry": None
        if geometry is None
        else {
            "finger": geometry.finger,
            "center": {"x": geometry.center_x, "y": geometry.center_y},
            "base": {"x": geometry.base_x, "y": geometry.base_y},
            "knuckle": {"x": geometry.knuckle_x, "y": geometry.knuckle_y},
            "source": geometry.source,
        },
        "thresholds": {
            "pass_threshold": pass_threshold,
            "fail_threshold": fail_threshold,
            "minimum_confidence": float(checks.get("hand_detection", {}).get("confidence") or 0.8),
        },
        "jewelry_visible": bool(jewelry and jewelry.visible),
        "note": (
            "Accuracy values are geometric agreement with the expected finger-base model, "
            "not detection confidence. When manual frame reviews exist they are scored separately."
        ),
    }


def measurement_from_ring_lay(lay: dict, base: PlacementMeasurement | None = None) -> PlacementMeasurement:
    details = (lay.get("check_details") or {}).get("ring_to_finger_distance") or {}
    normalized = details.get("normalized_distance")
    return PlacementMeasurement(
        dx=base.dx if base else None,
        dy=base.dy if base else None,
        distance=details.get("raw_distance", base.distance if base else None),
        normalized_distance=normalized if normalized is not None else (base.normalized_distance if base else None),
        status=str(lay.get("status") or "FAIL"),
        reason=str(lay.get("reason") or "Ring lay failed."),
        earlobe_confidence=base.earlobe_confidence if base else 0.0,
        earring_confidence=base.earring_confidence if base else 0.0,
        inside_zone=bool(
            normalized is not None
            and normalized <= float((lay.get("thresholds") or {}).get("fail_threshold", 0.15))
        ),
    )


def aggregate_ring_lay(frame_lays: list[dict], *, manual_statuses: list[str] | None = None) -> dict:
    empty_checks = {
        "hand_detection": "FAIL",
        "selected_finger_detection": "FAIL",
        "ring_placement": "FAIL",
        "finger_alignment": "FAIL",
        "ring_center_alignment": "FAIL",
        "knuckle_clearance": "FAIL",
        "ring_orientation": "FAIL",
    }
    if not frame_lays:
        return {
            "status": "FAIL",
            "final_result": "FAIL",
            "overall_ring_lay_accuracy_pct": 0.0,
            "checks": empty_checks,
            "accuracies": {
                "hand_detection_accuracy": 0.0,
                "finger_detection_accuracy": 0.0,
                "ring_placement_accuracy": 0.0,
                "finger_alignment_accuracy": 0.0,
                "ring_center_alignment_accuracy": 0.0,
                "knuckle_clearance_accuracy": 0.0,
                "ring_orientation_accuracy": 0.0,
                "overall_ring_lay_accuracy": 0.0,
            },
            "reason": "No ring frames were evaluated.",
            "ground_truth_accuracy_pct": None,
            "selected_finger": "ring",
            "note": "Accuracy is geometric vs expected finger-base, not confidence.",
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
        "hand_detection_accuracy",
        "finger_detection_accuracy",
        "ring_placement_accuracy",
        "finger_alignment_accuracy",
        "ring_center_alignment_accuracy",
        "knuckle_clearance_accuracy",
        "ring_orientation_accuracy",
        "overall_ring_lay_accuracy",
    ]
    accuracies = {}
    for key in accuracy_keys:
        values = [float((item.get("accuracies") or {}).get(key, 0.0)) for item in frame_lays]
        accuracies[key] = sum(values) / len(values) if values else 0.0

    status = worst([str(item.get("status", "FAIL")) for item in frame_lays])
    if checks["ring_placement"] == "FAIL" or checks["selected_finger_detection"] == "FAIL":
        status = "FAIL"

    ground_truth_pct = None
    if manual_statuses:
        paired = [(auto.get("status"), manual) for auto, manual in zip(frame_lays, manual_statuses) if manual]
        if paired:
            matches = sum(1 for auto, manual in paired if auto == manual)
            ground_truth_pct = round(100.0 * matches / len(paired), 1)

    selected = next((str(item.get("selected_finger")) for item in frame_lays if item.get("selected_finger")), "ring")
    reason = (
        f"Ring is worn around the {selected} finger and seated naturally near the finger base."
        if status == "PASS"
        else next(
            (str(item.get("reason")) for item in frame_lays if item.get("status") == "FAIL"),
            "Ring lay did not meet finger placement rules.",
        )
    )
    return {
        "status": status,
        "final_result": status,
        "selected_finger": selected,
        "checks": checks,
        "accuracies": accuracies,
        "overall_ring_lay_accuracy_pct": round(accuracies["overall_ring_lay_accuracy"] * 100.0, 1),
        "ground_truth_accuracy_pct": ground_truth_pct,
        "frames_evaluated": len(frame_lays),
        "reason": reason,
        "note": (
            "Overall ring lay accuracy is the mean geometric agreement with the expected finger-base model. "
            "Detection confidence is not used as accuracy. "
            "ground_truth_accuracy_pct is set only when manual frame reviews exist."
        ),
    }
