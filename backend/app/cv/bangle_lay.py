"""Bangle lay detection: rigid wrist-circle checks used only for jewelry_type=bangle."""

from __future__ import annotations

from app.cv.bracelet_lay import resolve_wrist_geometry
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, PlacementMeasurement
from app.utils.geometry import distance, normalize_distance, offset


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


def _collect_bangle_points(
    jewelry: EarringAnchor,
    debug_state: dict | None,
) -> list[tuple[float, float, float]]:
    """Return (x, y, confidence) for primary + any additional published bangles."""
    points: list[tuple[float, float, float]] = []
    if jewelry.x is not None and jewelry.y is not None and jewelry.visible:
        points.append((float(jewelry.x), float(jewelry.y), float(jewelry.confidence or 0.9)))
    if not isinstance(debug_state, dict):
        return points
    for key in ("bangles", "bangle_attachments", "jewelry_attachments", "attachments"):
        raw = debug_state.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            x = item.get("x", item.get("anchor_x"))
            y = item.get("y", item.get("anchor_y"))
            if x is None or y is None:
                continue
            conf = float(item.get("confidence") or 0.85)
            visible = bool(item.get("visible", True))
            if not visible:
                continue
            points.append((float(x), float(y), conf))
    # Nested under jewelry/hand payloads
    for nest_key in ("jewelry", "hand", "tryon"):
        nest = debug_state.get(nest_key)
        if not isinstance(nest, dict):
            continue
        for key in ("bangles", "attachments", "jewelry_attachments"):
            raw = nest.get(key)
            if not isinstance(raw, list):
                continue
            for item in raw:
                if not isinstance(item, dict):
                    continue
                x = item.get("x", item.get("anchor_x"))
                y = item.get("y", item.get("anchor_y"))
                if x is None or y is None:
                    continue
                conf = float(item.get("confidence") or 0.85)
                if not bool(item.get("visible", True)):
                    continue
                points.append((float(x), float(y), conf))
    # Drop only exact republishes of the same point; near-overlap is a spacing FAIL.
    unique: list[tuple[float, float, float]] = []
    for x, y, conf in points:
        if any(distance(x - ux, y - uy) < 0.001 for ux, uy, _ in unique):
            continue
        unique.append((x, y, conf))
    return unique


def evaluate_bangle_lay(
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
    Measure bangle lay around the wrist.

    Only intended for jewelry_type == \"bangle\". Accuracy scores are geometric
    agreement with the expected wrist circle/oval model, not detection confidence.
    """
    minimum_confidence = float(config.get("minimum_confidence", 0.80))
    pass_threshold = float(config.get("pass_threshold", 0.08))
    fail_threshold = float(config.get("fail_threshold", 0.15))
    zone_y_scale = float(config.get("zone_y_scale", 1.0))
    wrist_side = side if side in {"left", "right"} else "left"
    _ = jewelry_id

    geometry = resolve_wrist_geometry(
        wrist_anchor=wrist_anchor,
        face=face,
        debug_state=debug_state,
        side=wrist_side,
        style="bangle",
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

    # 2. Wrist landmarks
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
        }

    jewelry_ok = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
    if not jewelry_ok or geometry is None:
        fail = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": (
                "Bangle attachment point was not detected."
                if geometry
                else "Cannot score bangle lay without a wrist estimate."
            ),
        }
        for key in (
            "bangle_placement",
            "wrist_alignment",
            "circular_oval_alignment",
            "bangle_center_alignment",
            "wrist_coverage",
            "bangle_to_wrist_distance",
            "hand_clearance",
            "forearm_clearance",
            "bangle_orientation",
            "multiple_bangle_spacing",
            "bangle_visibility",
        ):
            checks[key] = dict(fail)
        if not jewelry_ok:
            checks["bangle_visibility"] = {
                "status": "FAIL",
                "accuracy": 0.0,
                "detail": "Bangle is not sufficiently visible for accurate detection.",
            }
        checks["multiple_bangle_spacing"] = {
            "status": "N/A",
            "accuracy": 1.0,
            "detail": "Multiple bangle spacing not evaluated.",
        }
        return _finalize(checks, geometry, jewelry, wrist_side, pass_threshold, fail_threshold, bangle_count=0)

    assert jewelry is not None and jewelry.x is not None and jewelry.y is not None
    jx, jy = float(jewelry.x), float(jewelry.y)
    width = max(0.03, geometry.width)
    expected_radius = width * 0.42

    dx, dy = offset(jx, jy, geometry.center_x, geometry.center_y)
    raw = distance(dx, dy)
    along = dx * geometry.direction_x + dy * geometry.direction_y
    across = dx * (-geometry.direction_y) + dy * geometry.direction_x
    # Rigid bangle: published point may be band center OR a point on the circle.
    center_fit = raw / width
    rim_fit = abs(raw - expected_radius) / width
    ring_fit = min(center_fit, rim_fit)
    # Along-arm residual only outside the wrist joint band.
    along_allow = 0.55 * width
    residual_along = 0.0 if abs(along) <= along_allow else abs(along) - along_allow
    bangle_to_wrist = max(ring_fit, residual_along / width)

    palm_dist = distance(jx - geometry.palm_x, jy - geometry.palm_y) / width
    finger_dist = distance(jx - geometry.finger_x, jy - geometry.finger_y) / width
    forearm_dist = distance(jx - geometry.forearm_x, jy - geometry.forearm_y) / width
    on_palm = palm_dist < 0.85 and along > 0.55 * width and center_fit > 0.55
    on_fingers = finger_dist < 0.75 and along > 1.0 * width and center_fit > 0.7
    too_far_forearm = along < -0.95 * width or (forearm_dist < 0.7 and along < -0.55 * width and center_fit > 0.55)
    floating = bangle_to_wrist > fail_threshold and center_fit > 0.85 and rim_fit > fail_threshold

    # 13. Visibility
    if not jewelry.visible:
        vis_status, vis_detail, vis_acc = "FAIL", "Bangle is not visible.", 0.0
    elif jewelry.confidence < minimum_confidence:
        vis_status = "WARNING"
        vis_detail = "Bangle detection confidence is insufficient or clothing partially covers it."
        vis_acc = 0.5
    elif jx < 0.02 or jx > 0.98 or jy < 0.02 or jy > 0.98:
        vis_status, vis_detail, vis_acc = "WARNING", "Bangle is partially outside the camera frame.", 0.5
    else:
        vis_status, vis_detail, vis_acc = "PASS", "Bangle is sufficiently visible for detection.", 1.0
    checks["bangle_visibility"] = {"status": vis_status, "accuracy": vis_acc, "detail": vis_detail}

    # 3. Placement
    placement_status = "PASS"
    placement_detail = f"Bangle is positioned around the {wrist_side} wrist."
    if on_palm:
        placement_status = "FAIL"
        placement_detail = "Bangle is positioned on the palm."
    elif on_fingers:
        placement_status = "FAIL"
        placement_detail = "Bangle is positioned on the fingers."
    elif too_far_forearm:
        placement_status = "FAIL"
        placement_detail = "Bangle is incorrectly positioned too far up the forearm."
    elif floating:
        placement_status = "FAIL"
        placement_detail = "Bangle is floating above or away from the wrist."
    elif bangle_to_wrist > fail_threshold:
        placement_status = "FAIL"
        placement_detail = "Bangle placement error exceeds the fail threshold."
    elif bangle_to_wrist > pass_threshold:
        placement_status = "WARNING"
        placement_detail = "Bangle is near the wrist but outside the pass threshold."
    checks["bangle_placement"] = {
        "status": placement_status,
        "accuracy": _accuracy_from_error(bangle_to_wrist, fail_threshold),
        "detail": placement_detail,
        "normalized_distance": bangle_to_wrist,
    }

    # 4. Wrist alignment — for rigid bangles, fit to center or rim (not axis-only)
    align_error = ring_fit
    if jewelry.rotation is not None:
        rot = abs(float(jewelry.rotation)) % 180.0
        tilt = min(rot, 180.0 - rot) / 90.0
        align_error = max(align_error, tilt * 0.5)
    align_status = _status_from_error(align_error, pass_threshold, fail_threshold)
    if floating or on_palm or on_fingers:
        align_status = "FAIL"
    checks["wrist_alignment"] = {
        "status": align_status,
        "accuracy": _accuracy_from_error(align_error, fail_threshold),
        "detail": (
            "Bangle follows the natural wrist orientation."
            if align_status == "PASS"
            else "Bangle is significantly misaligned with the wrist."
            if align_status == "FAIL"
            else "Bangle is slightly off the wrist axis."
        ),
        "error": align_error,
    }

    # 5. Circular / oval alignment — accept band-center OR rim-on-circle publications
    radial = raw
    radial_error = ring_fit
    circle_status = _status_from_error(radial_error, pass_threshold * 1.5, fail_threshold * 1.8)
    if floating:
        circle_status = "FAIL"
    if jewelry.scale is not None:
        scale_dev = abs(float(jewelry.scale) - 1.0)
        if scale_dev > 0.55:
            circle_status = "FAIL"
            radial_error = max(radial_error, scale_dev)
        elif scale_dev > 0.30 and circle_status == "PASS":
            circle_status = "WARNING"
            radial_error = max(radial_error, scale_dev * 0.5)
    checks["circular_oval_alignment"] = {
        "status": circle_status,
        "accuracy": _accuracy_from_error(radial_error, fail_threshold * 1.8),
        "detail": (
            "Bangle maintains its natural circular or oval shape around the wrist."
            if circle_status == "PASS"
            else "Bangle is unnaturally distorted."
            if circle_status == "FAIL"
            else "Bangle shape is slightly off a natural circle/oval."
        ),
        "error": radial_error,
        "expected_radius": expected_radius,
        "actual_radius": radial,
    }

    # 6. Center alignment
    center_status = _status_from_error(bangle_to_wrist, pass_threshold, fail_threshold)
    checks["bangle_center_alignment"] = {
        "status": center_status,
        "accuracy": _accuracy_from_error(bangle_to_wrist, fail_threshold),
        "detail": (
            "Bangle center aligns with the wrist center."
            if center_status == "PASS"
            else "Bangle center is significantly misaligned with the wrist center."
            if center_status == "FAIL"
            else "Bangle center is slightly off the wrist center."
        ),
        "error": bangle_to_wrist,
    }

    # 7. Wrist coverage
    coverage = max(0.0, 1.0 - bangle_to_wrist)
    if coverage < 0.35 or floating:
        coverage_status = "FAIL"
        coverage_detail = "Bangle is not positioned within the wrist region."
    elif coverage < 0.55:
        coverage_status = "WARNING"
        coverage_detail = "Bangle only partially sits in the wrist region."
    else:
        coverage_status = "PASS"
        coverage_detail = "Bangle is positioned within the wrist region."
    checks["wrist_coverage"] = {
        "status": coverage_status,
        "accuracy": float(max(0.0, min(1.0, coverage))),
        "detail": coverage_detail,
        "coverage": coverage,
    }

    # 8. Distance
    distance_status = _status_from_error(bangle_to_wrist, pass_threshold, fail_threshold)
    checks["bangle_to_wrist_distance"] = {
        "status": distance_status,
        "accuracy": _accuracy_from_error(bangle_to_wrist, fail_threshold),
        "detail": f"Normalized bangle-to-wrist distance is {bangle_to_wrist:.3f}.",
        "normalized_distance": bangle_to_wrist,
        "raw_distance": raw,
        "wrist_width": width,
    }

    # 9 / 10. Clearances
    checks["hand_clearance"] = {
        "status": "FAIL" if (on_palm or on_fingers) else "PASS",
        "accuracy": 0.0 if (on_palm or on_fingers) else 1.0,
        "detail": (
            "Bangle incorrectly sits on the palm or fingers."
            if (on_palm or on_fingers)
            else "Bangle clears the palm and fingers."
        ),
    }
    checks["forearm_clearance"] = {
        "status": "FAIL" if too_far_forearm else "PASS",
        "accuracy": 0.0 if too_far_forearm else 1.0,
        "detail": (
            "Bangle is too far up the forearm."
            if too_far_forearm
            else "Bangle clears the upper forearm and stays near the wrist joint."
        ),
    }

    # 11. Orientation
    orient_error = 0.0
    orient_status = "PASS"
    orient_detail = "Bangle is naturally aligned around the wrist."
    if jewelry.rotation is not None:
        rot = abs(float(jewelry.rotation)) % 180.0
        tilt = min(rot, 180.0 - rot)
        orient_error = tilt / 90.0
        if tilt > 50:
            orient_status = "FAIL"
            orient_detail = "Bangle is unnaturally tilted, floating, or distorted."
        elif tilt > 28:
            orient_status = "WARNING"
            orient_detail = "Bangle is slightly tilted."
    elif floating:
        orient_status = "FAIL"
        orient_detail = "Bangle is unnaturally tilted, floating, or distorted."
        orient_error = bangle_to_wrist
    elif align_error > fail_threshold:
        orient_status = "FAIL"
        orient_detail = "Bangle orientation does not follow the wrist."
        orient_error = align_error
    elif align_error > pass_threshold:
        orient_status = "WARNING"
        orient_detail = "Bangle is slightly tilted relative to the wrist."
        orient_error = align_error
    checks["bangle_orientation"] = {
        "status": orient_status,
        "accuracy": _accuracy_from_error(orient_error, fail_threshold * 2.0),
        "detail": orient_detail,
        "error": orient_error,
    }

    # 12. Multiple bangle spacing — N/A for a single bangle
    bangle_points = _collect_bangle_points(jewelry, debug_state)
    if len(bangle_points) <= 1:
        checks["multiple_bangle_spacing"] = {
            "status": "N/A",
            "accuracy": 1.0,
            "detail": "Single bangle — spacing rules are not applied.",
            "bangle_count": len(bangle_points) or 1,
        }
    else:
        # Project onto forearm→hand axis and sort
        projected = []
        for x, y, conf in bangle_points:
            pdx, pdy = offset(x, y, geometry.center_x, geometry.center_y)
            proj = pdx * geometry.direction_x + pdy * geometry.direction_y
            projected.append((proj, x, y, conf))
        projected.sort(key=lambda item: item[0])
        gaps = [projected[i + 1][0] - projected[i][0] for i in range(len(projected) - 1)]
        min_gap = min(gaps)
        max_gap = max(gaps)
        mean_gap = sum(gaps) / len(gaps)
        # Gaps are image-normalized; scale relative to wrist width for style-agnostic rules.
        # Single-bangle path never enters here — spacing rules apply only to stacks.
        overlap_fail = 0.10 * width   # stacked / colliding
        near_overlap = 0.22 * width
        natural_min = 0.28 * width
        if min_gap < overlap_fail:
            space_status = "FAIL"
            space_detail = "Multiple bangles overlap unnaturally."
            space_error = abs(overlap_fail - min_gap) / width
        else:
            uneven = (max_gap - min_gap) / max(mean_gap, 1e-6)
            space_error = uneven * 0.15
            if uneven > 1.35:
                space_status = "WARNING"
                space_detail = "Multiple bangles have uneven spacing."
            elif min_gap < near_overlap:
                space_status = "WARNING"
                space_detail = "Multiple bangles are nearly overlapping."
            elif min_gap < natural_min and uneven > 0.85:
                space_status = "WARNING"
                space_detail = "Multiple bangles have uneven spacing."
            else:
                space_status = "PASS"
                space_detail = "Multiple bangles are spaced naturally along the wrist."
        checks["multiple_bangle_spacing"] = {
            "status": space_status,
            "accuracy": 1.0 if space_status == "PASS" else _accuracy_from_error(space_error, fail_threshold),
            "detail": space_detail,
            "bangle_count": len(bangle_points),
            "gaps": gaps,
            "error": space_error if space_status != "PASS" else 0.0,
        }

    return _finalize(
        checks,
        geometry,
        jewelry,
        wrist_side,
        pass_threshold,
        fail_threshold,
        bangle_count=max(1, len(bangle_points)),
    )


def _finalize(
    checks: dict[str, dict],
    geometry,
    jewelry: EarringAnchor | None,
    side: str,
    pass_threshold: float,
    fail_threshold: float,
    *,
    bangle_count: int,
) -> dict:
    required = [
        "wrist_detection",
        "wrist_landmark_detection",
        "bangle_placement",
        "wrist_alignment",
        "circular_oval_alignment",
        "bangle_center_alignment",
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
    # Spacing WARNING should soften PASS; FAIL forces overall FAIL
    spacing = checks.get("multiple_bangle_spacing", {}).get("status", "N/A")
    if spacing == "FAIL":
        hard.append("FAIL")
    status = _combine(*hard) if hard else "FAIL"
    if checks.get("wrist_detection", {}).get("status") == "WARNING" and status == "PASS":
        status = "WARNING"
    if checks.get("bangle_visibility", {}).get("status") == "WARNING" and status == "PASS":
        status = "WARNING"
    if spacing == "WARNING" and status == "PASS":
        status = "WARNING"
    if checks.get("bangle_placement", {}).get("status") == "FAIL":
        status = "FAIL"

    accuracies = {
        "wrist_detection_accuracy": float(checks.get("wrist_detection", {}).get("accuracy", 0.0)),
        "wrist_landmark_accuracy": float(checks.get("wrist_landmark_detection", {}).get("accuracy", 0.0)),
        "bangle_placement_accuracy": float(checks.get("bangle_placement", {}).get("accuracy", 0.0)),
        "wrist_alignment_accuracy": float(checks.get("wrist_alignment", {}).get("accuracy", 0.0)),
        "circular_oval_alignment_accuracy": float(checks.get("circular_oval_alignment", {}).get("accuracy", 0.0)),
        "bangle_center_alignment_accuracy": float(checks.get("bangle_center_alignment", {}).get("accuracy", 0.0)),
        "wrist_coverage_accuracy": float(checks.get("wrist_coverage", {}).get("accuracy", 0.0)),
        "multiple_bangle_spacing_accuracy": float(checks.get("multiple_bangle_spacing", {}).get("accuracy", 1.0)),
    }
    # Overall excludes N/A spacing as a free 1.0 only when single — still include but it's 1.0
    overall = sum(accuracies.values()) / len(accuracies)

    reasons = [checks[key]["detail"] for key in required if checks.get(key, {}).get("status") == "FAIL"]
    if spacing == "FAIL":
        reasons.append(str(checks["multiple_bangle_spacing"]["detail"]))
    if not reasons and status == "WARNING":
        reasons = [
            checks[key]["detail"]
            for key in checks
            if checks[key]["status"] == "WARNING"
        ]
    if status == "PASS":
        reason = (
            f"Bangle is positioned around the {side} wrist, aligned with the wrist center, "
            "and maintains a natural circular or oval shape."
        )
    else:
        reason = " ".join(reasons) or "Bangle lay validation failed."

    return {
        "status": status,
        "final_result": status,
        "reason": reason,
        "wrist_side": side,
        "bangle_count": bangle_count,
        "checks": {
            "wrist_detection": checks.get("wrist_detection", {}).get("status", "FAIL"),
            "wrist_landmark_detection": checks.get("wrist_landmark_detection", {}).get("status", "FAIL"),
            "bangle_placement": checks.get("bangle_placement", {}).get("status", "FAIL"),
            "wrist_alignment": checks.get("wrist_alignment", {}).get("status", "FAIL"),
            "circular_oval_alignment": checks.get("circular_oval_alignment", {}).get("status", "FAIL"),
            "bangle_center_alignment": checks.get("bangle_center_alignment", {}).get("status", "FAIL"),
            "wrist_coverage": checks.get("wrist_coverage", {}).get("status", "FAIL"),
            "bangle_to_wrist_distance": checks.get("bangle_to_wrist_distance", {}).get("status", "FAIL"),
            "hand_clearance": checks.get("hand_clearance", {}).get("status", "FAIL"),
            "forearm_clearance": checks.get("forearm_clearance", {}).get("status", "FAIL"),
            "bangle_orientation": checks.get("bangle_orientation", {}).get("status", "FAIL"),
            "multiple_bangle_spacing": checks.get("multiple_bangle_spacing", {}).get("status", "N/A"),
            "bangle_visibility": checks.get("bangle_visibility", {}).get("status", "FAIL"),
        },
        "check_details": checks,
        "accuracies": {
            **accuracies,
            "overall_bangle_lay_accuracy": overall,
        },
        "overall_bangle_lay_accuracy_pct": round(overall * 100.0, 1),
        "geometry": None
        if geometry is None
        else {
            "side": geometry.side,
            "center": {"x": geometry.center_x, "y": geometry.center_y},
            "width": geometry.width,
            "source": geometry.source,
        },
        "thresholds": {
            "pass_threshold": pass_threshold,
            "fail_threshold": fail_threshold,
        },
        "jewelry_visible": bool(jewelry and jewelry.visible),
        "note": (
            "Accuracy values are geometric agreement with the expected wrist circle/oval model, "
            "not detection confidence. Multiple-bangle spacing is N/A for a single bangle. "
            "Manual reviews feed ground-truth accuracy separately."
        ),
    }


def measurement_from_bangle_lay(lay: dict, base: PlacementMeasurement | None = None) -> PlacementMeasurement:
    details = (lay.get("check_details") or {}).get("bangle_to_wrist_distance") or {}
    normalized = details.get("normalized_distance")
    return PlacementMeasurement(
        dx=base.dx if base else None,
        dy=base.dy if base else None,
        distance=details.get("raw_distance", base.distance if base else None),
        normalized_distance=normalized if normalized is not None else (base.normalized_distance if base else None),
        status=str(lay.get("status") or "FAIL"),
        reason=str(lay.get("reason") or "Bangle lay failed."),
        earlobe_confidence=base.earlobe_confidence if base else 0.0,
        earring_confidence=base.earring_confidence if base else 0.0,
        inside_zone=bool(
            normalized is not None
            and normalized <= float((lay.get("thresholds") or {}).get("fail_threshold", 0.15))
        ),
    )


def aggregate_bangle_lay(frame_lays: list[dict], *, manual_statuses: list[str] | None = None) -> dict:
    empty_checks = {
        "wrist_detection": "FAIL",
        "wrist_landmark_detection": "FAIL",
        "bangle_placement": "FAIL",
        "wrist_alignment": "FAIL",
        "circular_oval_alignment": "FAIL",
        "bangle_center_alignment": "FAIL",
        "wrist_coverage": "FAIL",
        "hand_clearance": "FAIL",
        "forearm_clearance": "FAIL",
        "multiple_bangle_spacing": "N/A",
    }
    if not frame_lays:
        return {
            "status": "FAIL",
            "final_result": "FAIL",
            "overall_bangle_lay_accuracy_pct": 0.0,
            "checks": empty_checks,
            "accuracies": {
                "wrist_detection_accuracy": 0.0,
                "wrist_landmark_accuracy": 0.0,
                "bangle_placement_accuracy": 0.0,
                "wrist_alignment_accuracy": 0.0,
                "circular_oval_alignment_accuracy": 0.0,
                "bangle_center_alignment_accuracy": 0.0,
                "wrist_coverage_accuracy": 0.0,
                "multiple_bangle_spacing_accuracy": 0.0,
                "overall_bangle_lay_accuracy": 0.0,
            },
            "reason": "No bangle frames were evaluated.",
            "ground_truth_accuracy_pct": None,
            "wrist_side": "left",
            "bangle_count": 0,
            "note": "Accuracy is geometric vs expected wrist circle/oval, not confidence.",
        }

    def worst(values: list[str]) -> str:
        useful = [value for value in values if value != "N/A"]
        if not useful:
            return "N/A"
        if any(value == "FAIL" for value in useful):
            return "FAIL"
        if any(value == "WARNING" for value in useful):
            return "WARNING"
        return "PASS"

    check_keys = list(empty_checks.keys())
    checks = {
        key: worst([str((item.get("checks") or {}).get(key, "FAIL")) for item in frame_lays]) for key in check_keys
    }
    accuracy_keys = [
        "wrist_detection_accuracy",
        "wrist_landmark_accuracy",
        "bangle_placement_accuracy",
        "wrist_alignment_accuracy",
        "circular_oval_alignment_accuracy",
        "bangle_center_alignment_accuracy",
        "wrist_coverage_accuracy",
        "multiple_bangle_spacing_accuracy",
        "overall_bangle_lay_accuracy",
    ]
    accuracies = {}
    for key in accuracy_keys:
        values = [float((item.get("accuracies") or {}).get(key, 0.0)) for item in frame_lays]
        accuracies[key] = sum(values) / len(values) if values else 0.0

    status = worst([str(item.get("status", "FAIL")) for item in frame_lays])
    if checks["bangle_placement"] == "FAIL" or checks["wrist_detection"] == "FAIL":
        status = "FAIL"
    if checks["multiple_bangle_spacing"] == "FAIL":
        status = "FAIL"

    ground_truth_pct = None
    if manual_statuses:
        paired = [(auto.get("status"), manual) for auto, manual in zip(frame_lays, manual_statuses) if manual]
        if paired:
            matches = sum(1 for auto, manual in paired if auto == manual)
            ground_truth_pct = round(100.0 * matches / len(paired), 1)

    wrist_side = next((str(item.get("wrist_side")) for item in frame_lays if item.get("wrist_side")), "left")
    bangle_count = max(int(item.get("bangle_count") or 1) for item in frame_lays)
    reason = (
        f"Bangle is positioned around the {wrist_side} wrist and keeps a natural circular or oval shape."
        if status == "PASS"
        else next(
            (str(item.get("reason")) for item in frame_lays if item.get("status") == "FAIL"),
            "Bangle lay did not meet wrist placement rules.",
        )
    )
    return {
        "status": status,
        "final_result": status,
        "wrist_side": wrist_side,
        "bangle_count": bangle_count,
        "checks": checks,
        "accuracies": accuracies,
        "overall_bangle_lay_accuracy_pct": round(accuracies["overall_bangle_lay_accuracy"] * 100.0, 1),
        "ground_truth_accuracy_pct": ground_truth_pct,
        "frames_evaluated": len(frame_lays),
        "reason": reason,
        "note": (
            "Overall bangle lay accuracy is the mean geometric agreement with the expected wrist circle/oval model. "
            "Detection confidence is not used as accuracy. Multiple-bangle spacing is N/A for a single bangle. "
            "ground_truth_accuracy_pct is set only when manual frame reviews exist."
        ),
    }
