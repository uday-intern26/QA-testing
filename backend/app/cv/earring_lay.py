"""Earring lay detection: earlobe attachment checks used only for jewelry_type=earring."""

from __future__ import annotations

from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, Landmark, PlacementMeasurement
from app.utils.geometry import distance, normalize_distance, offset

NOSE = 1
LEFT_EYE = 33
RIGHT_EYE = 263
CHIN = 152
LEFT_CHEEK = 234
RIGHT_CHEEK = 454


def _point(landmarks: list[Landmark], index: int) -> Landmark | None:
    if index < 0 or index >= len(landmarks):
        return None
    return landmarks[index]


def _status_from_error(error: float, pass_threshold: float, fail_threshold: float) -> str:
    if error <= pass_threshold:
        return "PASS"
    if error <= fail_threshold:
        return "WARNING"
    return "FAIL"


def _accuracy_from_error(error: float, fail_threshold: float) -> float:
    """Geometric accuracy vs expected piercing/earlobe model. Not detection confidence."""
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


def _face_regions(face: FaceLandmarkResult | None) -> dict[str, tuple[float, float]] | None:
    if face is None or not face.face_detected or not face.landmarks:
        return None
    nose = _point(face.landmarks, NOSE)
    left_eye = _point(face.landmarks, LEFT_EYE)
    right_eye = _point(face.landmarks, RIGHT_EYE)
    chin = _point(face.landmarks, CHIN)
    left_cheek = _point(face.landmarks, LEFT_CHEEK)
    right_cheek = _point(face.landmarks, RIGHT_CHEEK)
    if not all([nose, left_eye, right_eye, chin]):
        return None
    assert nose and left_eye and right_eye and chin
    regions = {
        "nose": (float(nose.x), float(nose.y)),
        "left_eye": (float(left_eye.x), float(left_eye.y)),
        "right_eye": (float(right_eye.x), float(right_eye.y)),
        "chin": (float(chin.x), float(chin.y)),
    }
    if left_cheek is not None:
        regions["left_cheek"] = (float(left_cheek.x), float(left_cheek.y))
    if right_cheek is not None:
        regions["right_cheek"] = (float(right_cheek.x), float(right_cheek.y))
    return regions


def _evaluate_side(
    side: str,
    face: FaceLandmarkResult | None,
    earlobe: EarlobeAnchor | None,
    jewelry: EarringAnchor | None,
    *,
    config: dict,
    required: bool,
) -> dict:
    minimum_confidence = float(config.get("minimum_confidence", 0.80))
    pass_threshold = float(config.get("pass_threshold", 0.08))
    fail_threshold = float(config.get("fail_threshold", 0.15))
    zone_y_scale = float(config.get("zone_y_scale", 1.0))

    checks: dict[str, dict] = {}

    # 1. Ear detection
    if earlobe is None:
        checks["ear_detection"] = {
            "status": "FAIL" if required else "WARNING",
            "accuracy": 0.0,
            "detail": f"{side.capitalize()} ear was not detected from facial landmarks.",
        }
    elif earlobe.confidence < minimum_confidence:
        # Spec: insufficient ear confidence is WARNING (partial / hard conditions)
        checks["ear_detection"] = {
            "status": "WARNING",
            "accuracy": 0.0,
            "detail": (
                f"{side.capitalize()} ear confidence {earlobe.confidence:.2f} is below "
                f"{minimum_confidence:.2f} (partial visibility or occlusion)."
            ),
            "confidence": earlobe.confidence,
        }
    else:
        checks["ear_detection"] = {
            "status": "PASS",
            "accuracy": 1.0,
            "detail": f"{side.capitalize()} ear detected with confidence {earlobe.confidence:.2f}.",
            "confidence": earlobe.confidence,
        }

    jewelry_ok = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
    if not jewelry_ok:
        status = "FAIL" if required else "WARNING"
        detail = (
            f"{side.capitalize()} earring is missing when required."
            if required
            else f"{side.capitalize()} earring was not detected."
        )
        fail = {"status": status, "accuracy": 0.0, "detail": detail}
        for key in (
            "earring_attachment",
            "earlobe_alignment",
            "earring_placement",
            "hanging_alignment",
            "stud_alignment",
            "face_clearance",
            "earring_distance",
        ):
            checks[key] = dict(fail)
        return {
            "side": side,
            "status": _combine(*(item["status"] for item in checks.values())),
            "checks": {key: value["status"] for key, value in checks.items()},
            "check_details": checks,
            "accuracies": {
                "ear_detection_accuracy": float(checks["ear_detection"]["accuracy"]),
                "earring_placement_accuracy": 0.0,
                "earlobe_alignment_accuracy": 0.0,
                "hanging_alignment_accuracy": 0.0,
            },
            "normalized_distance": None,
            "reason": detail,
        }

    assert jewelry is not None and jewelry.x is not None and jewelry.y is not None
    jx, jy = float(jewelry.x), float(jewelry.y)

    if earlobe is None:
        fail = {
            "status": "FAIL",
            "accuracy": 0.0,
            "detail": f"Cannot score {side} earring lay without an ear estimate.",
        }
        for key in (
            "earring_attachment",
            "earlobe_alignment",
            "earring_placement",
            "hanging_alignment",
            "stud_alignment",
            "face_clearance",
            "earring_distance",
        ):
            checks[key] = dict(fail)
        return {
            "side": side,
            "status": "FAIL",
            "checks": {key: value["status"] for key, value in checks.items()},
            "check_details": checks,
            "accuracies": {
                "ear_detection_accuracy": 0.0,
                "earring_placement_accuracy": 0.0,
                "earlobe_alignment_accuracy": 0.0,
                "hanging_alignment_accuracy": 0.0,
            },
            "normalized_distance": None,
            "reason": fail["detail"],
        }

    ear_width = max(0.012, float(earlobe.ear_width))
    dx, dy = offset(jx, jy, earlobe.x, earlobe.y)
    raw = distance(dx, dy)
    # Natural hang (downward dy) is allowed for drops/danglers; score attachment on horizontal
    # drift plus any upward float. Ignore downward hang within 1.6 ear-widths.
    hang_allowance = 1.6 * ear_width
    if dy >= 0:
        adj_dy = max(0.0, dy - hang_allowance)
    else:
        adj_dy = dy
    normalized = normalize_distance(dx, adj_dy, ear_width, zone_y_scale)

    # Hard FAIL zones relative to the ear
    floating = normalized > fail_threshold and (abs(dx) > 0.35 * ear_width or dy < -0.2 * ear_width)
    # Cheek: inward toward face midline
    face_mid_x = 0.5
    regions = _face_regions(face)
    if regions:
        face_mid_x = (regions["left_eye"][0] + regions["right_eye"][0]) / 2.0
    # For image coords, left ear is typically at smaller x; "inward" toward center is +x for left, -x for right
    if side == "left":
        toward_face = jx > earlobe.x + 0.55 * ear_width
    else:
        toward_face = jx < earlobe.x - 0.55 * ear_width
    on_cheek = toward_face and abs(jy - earlobe.y) < 1.2 * ear_width and normalized > pass_threshold
    on_neck = jy > earlobe.y + 2.2 * ear_width
    wrong_side = (side == "left" and jx > face_mid_x + 0.02) or (side == "right" and jx < face_mid_x - 0.02)

    # Face clearance (eyes / nose)
    face_hit = False
    face_detail = f"{side.capitalize()} earring clears eyes, nose, and face interior."
    if regions:
        for name, (fx, fy) in regions.items():
            if name.endswith("cheek"):
                continue
            if distance(jx - fx, jy - fy) < 0.7 * ear_width:
                face_hit = True
                face_detail = f"{side.capitalize()} earring incorrectly overlaps the {name.replace('_', ' ')}."
                break
    checks["face_clearance"] = {
        "status": "FAIL" if face_hit else "PASS",
        "accuracy": 0.0 if face_hit else 1.0,
        "detail": face_detail,
    }

    # 2. Earring attachment to correct ear
    attachment_status = "PASS"
    attachment_detail = f"{side.capitalize()} earring is attached to the correct ear."
    if wrong_side and normalized > pass_threshold:
        attachment_status = "FAIL"
        attachment_detail = f"{side.capitalize()} earring is attached to the wrong location."
    elif on_cheek:
        attachment_status = "FAIL"
        attachment_detail = f"{side.capitalize()} earring is positioned on the cheek."
    elif on_neck:
        attachment_status = "FAIL"
        attachment_detail = f"{side.capitalize()} earring is positioned on the neck."
    elif floating:
        attachment_status = "FAIL"
        attachment_detail = f"{side.capitalize()} earring is floating away from the ear."
    elif normalized > fail_threshold:
        attachment_status = "FAIL"
        attachment_detail = f"{side.capitalize()} earring placement error exceeds the fail threshold."
    elif normalized > pass_threshold:
        attachment_status = "WARNING"
        attachment_detail = f"{side.capitalize()} earring is slightly misaligned with the ear."
    checks["earring_attachment"] = {
        "status": attachment_status,
        "accuracy": _accuracy_from_error(normalized, fail_threshold),
        "detail": attachment_detail,
    }

    # 3. Earlobe / piercing alignment
    earlobe_status = _status_from_error(normalized, pass_threshold, fail_threshold)
    if on_cheek or on_neck or floating:
        earlobe_status = "FAIL"
    checks["earlobe_alignment"] = {
        "status": earlobe_status,
        "accuracy": _accuracy_from_error(normalized, fail_threshold),
        "detail": (
            f"{side.capitalize()} earring aligns with the intended piercing / earlobe."
            if earlobe_status == "PASS"
            else f"{side.capitalize()} earring is significantly misaligned with the earlobe."
            if earlobe_status == "FAIL"
            else f"{side.capitalize()} earring is slightly off the piercing point."
        ),
        "error": normalized,
    }

    # 4/5. Side placement
    placement_status = _combine(attachment_status, earlobe_status, checks["face_clearance"]["status"])
    checks["earring_placement"] = {
        "status": placement_status,
        "accuracy": _accuracy_from_error(normalized, fail_threshold),
        "detail": (
            f"{side.capitalize()} earring is positioned correctly."
            if placement_status == "PASS"
            else attachment_detail
        ),
        "normalized_distance": normalized,
    }

    # 7. Hanging alignment — drops/danglers should fall downward from attachment (dy >= 0 in image space)
    # Studs (near-zero dy) also PASS. Large upward float fails.
    hang_error = 0.0
    if dy < -0.35 * ear_width:
        hang_error = abs(dy) / ear_width
        hang_status = "FAIL"
        hang_detail = f"{side.capitalize()} hanging earring does not fall naturally downward."
    elif dy < -0.15 * ear_width:
        hang_error = abs(dy) / ear_width
        hang_status = "WARNING"
        hang_detail = f"{side.capitalize()} earring hangs slightly upward (possible tracking noise)."
    else:
        hang_status = "PASS"
        hang_detail = f"{side.capitalize()} earring hangs naturally from the attachment point."
    # Rotation hint from debug anchor when present
    if jewelry.rotation is not None and abs(float(jewelry.rotation)) > 45 and hang_status == "PASS":
        hang_status = "WARNING"
        hang_detail = f"{side.capitalize()} earring rotation is unusually high for a natural hang."
        hang_error = max(hang_error, abs(float(jewelry.rotation)) / 90.0)
    checks["hanging_alignment"] = {
        "status": hang_status,
        "accuracy": _accuracy_from_error(hang_error, fail_threshold * 2.0),
        "detail": hang_detail,
        "error": hang_error,
    }

    # 8. Stud alignment — tight to piercing when scale suggests stud / small displacement
    is_likely_stud = (jewelry.scale is not None and float(jewelry.scale) < 1.15) or normalized <= pass_threshold * 1.5
    if is_likely_stud:
        stud_status = _status_from_error(normalized, pass_threshold, fail_threshold)
        stud_detail = (
            f"{side.capitalize()} stud sits on the intended piercing point."
            if stud_status == "PASS"
            else f"{side.capitalize()} stud is off the intended piercing point."
        )
    else:
        # Hoop / drop: stud check mirrors earlobe alignment loosely
        stud_status = earlobe_status if earlobe_status != "FAIL" else "WARNING"
        stud_detail = f"{side.capitalize()} piece treated as hoop/drop/dangler; piercing check uses earlobe alignment."
    checks["stud_alignment"] = {
        "status": stud_status,
        "accuracy": _accuracy_from_error(normalized, fail_threshold),
        "detail": stud_detail,
    }

    # 10. Earring distance
    distance_status = _status_from_error(normalized, pass_threshold, fail_threshold)
    checks["earring_distance"] = {
        "status": distance_status,
        "accuracy": _accuracy_from_error(normalized, fail_threshold),
        "detail": f"Normalized {side} earring-to-earlobe distance is {normalized:.3f}.",
        "normalized_distance": normalized,
        "raw_distance": raw,
        "ear_width": ear_width,
    }

    status = _combine(
        checks["ear_detection"]["status"] if checks["ear_detection"]["status"] != "WARNING" else "PASS",
        attachment_status,
        earlobe_status,
        placement_status,
        checks["face_clearance"]["status"],
        distance_status,
    )
    # Keep WARNING visibility from ear detection / hang / slight misalign
    soft = [checks["ear_detection"]["status"], hang_status, stud_status]
    if status == "PASS" and any(item == "WARNING" for item in soft):
        status = "WARNING"
    if status == "PASS" and any(item == "FAIL" for item in soft):
        status = "FAIL"

    reasons = [
        checks[key]["detail"]
        for key in ("ear_detection", "earring_attachment", "earlobe_alignment", "face_clearance", "earring_distance")
        if checks[key]["status"] == "FAIL"
    ]
    if not reasons and status == "WARNING":
        reasons = [
            checks[key]["detail"]
            for key in checks
            if checks[key]["status"] == "WARNING"
        ]

    return {
        "side": side,
        "status": status,
        "checks": {key: value["status"] for key, value in checks.items()},
        "check_details": checks,
        "accuracies": {
            "ear_detection_accuracy": float(checks["ear_detection"]["accuracy"]),
            "earring_placement_accuracy": float(checks["earring_placement"]["accuracy"]),
            "earlobe_alignment_accuracy": float(checks["earlobe_alignment"]["accuracy"]),
            "hanging_alignment_accuracy": float(checks["hanging_alignment"]["accuracy"]),
        },
        "normalized_distance": normalized,
        "dx": dx,
        "dy": dy,
        "reason": (
            f"{side.capitalize()} earring is attached at the intended earlobe / piercing."
            if status == "PASS"
            else " ".join(reasons) or f"{side.capitalize()} earring lay failed."
        ),
    }


def evaluate_earring_lay(
    face: FaceLandmarkResult | None,
    side_items: list[tuple[str, EarlobeAnchor | None, EarringAnchor | None]],
    *,
    config: dict,
    required_sides: list[str],
) -> dict:
    """
    Measure earring lay for required ear sides.

    Only intended for jewelry_type == \"earring\". Accuracy scores are geometric
    agreement with the expected piercing/earlobe model, not detection confidence.
    """
    required = {side for side in required_sides}
    by_side = {side: (earlobe, jewelry) for side, earlobe, jewelry in side_items}
    side_results: dict[str, dict] = {}
    for side in ("left", "right"):
        if side not in required and side not in by_side:
            continue
        earlobe, jewelry = by_side.get(side, (None, None))
        side_results[side] = _evaluate_side(
            side,
            face,
            earlobe,
            jewelry,
            config=config,
            required=side in required,
        )

    # 6. Left/right symmetry (when both required / both measured)
    symmetry = {
        "status": "PASS",
        "accuracy": 1.0,
        "detail": "Symmetry not required for this single-ear test.",
        "error": 0.0,
    }
    if "left" in side_results and "right" in side_results:
        left = side_results["left"]
        right = side_results["right"]
        if left.get("normalized_distance") is None or right.get("normalized_distance") is None:
            symmetry = {
                "status": "FAIL" if ("left" in required and "right" in required) else "WARNING",
                "accuracy": 0.0,
                "detail": "Cannot compare left/right symmetry because one earring is missing.",
                "error": None,
            }
        else:
            # Compare relative offsets accounting for mirrored X and shared vertical hang.
            ldx, ldy = float(left.get("dx") or 0.0), float(left.get("dy") or 0.0)
            rdx, rdy = float(right.get("dx") or 0.0), float(right.get("dy") or 0.0)
            # Mirror right dx so both are "outward positive"
            mirror_error = distance((-ldx) - rdx, ldy - rdy)
            # Normalize by mean ear width proxy from distances
            left_n = float(left["normalized_distance"])
            right_n = float(right["normalized_distance"])
            # Symmetry error from mirrored offset difference relative to fail scale
            pass_threshold = float(config.get("pass_threshold", 0.08))
            fail_threshold = float(config.get("fail_threshold", 0.15))
            # Use difference of normalized distances + vertical hang mismatch
            sym_error = abs(left_n - right_n) + abs(ldy - rdy) * 0.5
            # Prefer mirrored vector when both ears present
            if left.get("check_details") and right.get("check_details"):
                left_w = float(
                    ((left.get("check_details") or {}).get("earring_distance") or {}).get("ear_width") or 0.04
                )
                right_w = float(
                    ((right.get("check_details") or {}).get("earring_distance") or {}).get("ear_width") or 0.04
                )
                mean_w = max(0.012, (left_w + right_w) / 2.0)
                sym_error = mirror_error / mean_w
            sym_status = _status_from_error(sym_error, pass_threshold * 2.0, fail_threshold * 2.5)
            symmetry = {
                "status": sym_status,
                "accuracy": _accuracy_from_error(sym_error, fail_threshold * 2.5),
                "detail": (
                    "Left and right earrings are symmetrically placed for the current head pose."
                    if sym_status == "PASS"
                    else "Left and right earrings are uneven after accounting for head rotation."
                ),
                "error": sym_error,
            }

    statuses = [item["status"] for item in side_results.values()]
    if symmetry["status"] == "FAIL":
        statuses.append("FAIL")
    elif symmetry["status"] == "WARNING":
        statuses.append("WARNING")
    status = _combine(*statuses) if statuses else "FAIL"

    # Detection alone is never enough
    for side, result in side_results.items():
        if side in required and result.get("checks", {}).get("earring_placement") == "FAIL":
            status = "FAIL"

    left_acc = float((side_results.get("left") or {}).get("accuracies", {}).get("ear_detection_accuracy", 0.0))
    right_acc = float((side_results.get("right") or {}).get("accuracies", {}).get("ear_detection_accuracy", 0.0))
    left_place = float((side_results.get("left") or {}).get("accuracies", {}).get("earring_placement_accuracy", 0.0))
    right_place = float((side_results.get("right") or {}).get("accuracies", {}).get("earring_placement_accuracy", 0.0))
    earlobe_vals = [
        float(item.get("accuracies", {}).get("earlobe_alignment_accuracy", 0.0)) for item in side_results.values()
    ]
    hang_vals = [
        float(item.get("accuracies", {}).get("hanging_alignment_accuracy", 0.0)) for item in side_results.values()
    ]
    earlobe_acc = sum(earlobe_vals) / len(earlobe_vals) if earlobe_vals else 0.0
    hang_acc = sum(hang_vals) / len(hang_vals) if hang_vals else 0.0
    components = []
    if "left" in required or "left" in side_results:
        components.extend([left_acc, left_place])
    if "right" in required or "right" in side_results:
        components.extend([right_acc, right_place])
    components.extend([earlobe_acc, float(symmetry["accuracy"]), hang_acc])
    overall = sum(components) / len(components) if components else 0.0

    checks = {
        "left_ear_detection": (side_results.get("left") or {}).get("checks", {}).get("ear_detection", "FAIL"),
        "right_ear_detection": (side_results.get("right") or {}).get("checks", {}).get("ear_detection", "FAIL"),
        "left_earring_placement": (side_results.get("left") or {}).get("checks", {}).get("earring_placement", "FAIL"),
        "right_earring_placement": (side_results.get("right") or {}).get("checks", {}).get("earring_placement", "FAIL"),
        "earlobe_alignment": _combine(
            *[
                str((side_results.get(side) or {}).get("checks", {}).get("earlobe_alignment", "FAIL"))
                for side in side_results
            ]
        )
        if side_results
        else "FAIL",
        "symmetry": symmetry["status"],
        "hanging_alignment": _combine(
            *[
                str((side_results.get(side) or {}).get("checks", {}).get("hanging_alignment", "FAIL"))
                for side in side_results
            ]
        )
        if side_results
        else "FAIL",
    }
    # Mark non-required sides as not applicable rather than FAIL noise
    if "left" not in required and "left" not in side_results:
        checks["left_ear_detection"] = "PASS"
        checks["left_earring_placement"] = "PASS"
    if "right" not in required and "right" not in side_results:
        checks["right_ear_detection"] = "PASS"
        checks["right_earring_placement"] = "PASS"

    reasons = [item.get("reason") for item in side_results.values() if item.get("status") == "FAIL"]
    if status == "PASS":
        reason = "Earrings are attached to the ears at the intended piercing / earlobe positions."
    elif status == "WARNING":
        reason = " ".join(
            str(item.get("reason")) for item in side_results.values() if item.get("status") == "WARNING"
        ) or symmetry["detail"]
    else:
        reason = " ".join(str(item) for item in reasons if item) or "Earring lay validation failed."

    return {
        "status": status,
        "final_result": status,
        "reason": reason,
        "checks": checks,
        "side_results": side_results,
        "symmetry": symmetry,
        "accuracies": {
            "left_ear_detection_accuracy": left_acc,
            "right_ear_detection_accuracy": right_acc,
            "left_earring_placement_accuracy": left_place,
            "right_earring_placement_accuracy": right_place,
            "earlobe_alignment_accuracy": earlobe_acc,
            "left_right_symmetry_accuracy": float(symmetry["accuracy"]),
            "hanging_alignment_accuracy": hang_acc,
            "overall_earring_lay_accuracy": overall,
        },
        "overall_earring_lay_accuracy_pct": round(overall * 100.0, 1),
        "thresholds": {
            "pass_threshold": float(config.get("pass_threshold", 0.08)),
            "fail_threshold": float(config.get("fail_threshold", 0.15)),
            "minimum_confidence": float(config.get("minimum_confidence", 0.80)),
        },
        "note": (
            "Accuracy values are geometric agreement with the expected piercing/earlobe model, "
            "not detection confidence. When manual frame reviews exist they are scored separately."
        ),
    }


def measurement_from_earring_lay(
    lay: dict, side: str, base: PlacementMeasurement | None = None
) -> PlacementMeasurement:
    side_result = (lay.get("side_results") or {}).get(side) or {}
    normalized = side_result.get("normalized_distance")
    if normalized is None and base is not None:
        normalized = base.normalized_distance
    status = str(side_result.get("status") or lay.get("status") or "FAIL")
    reason = str(side_result.get("reason") or lay.get("reason") or "Earring lay failed.")
    return PlacementMeasurement(
        dx=side_result.get("dx", base.dx if base else None),
        dy=side_result.get("dy", base.dy if base else None),
        distance=base.distance if base else None,
        normalized_distance=normalized,
        status=status,
        reason=reason,
        earlobe_confidence=base.earlobe_confidence if base else 0.0,
        earring_confidence=base.earring_confidence if base else 0.0,
        inside_zone=bool(
            normalized is not None
            and normalized <= float((lay.get("thresholds") or {}).get("fail_threshold", 0.15))
        ),
    )


def aggregate_earring_lay(frame_lays: list[dict], *, manual_statuses: list[str] | None = None) -> dict:
    """Aggregate per-frame earring lay into a run-level QA result."""
    empty_checks = {
        "left_ear_detection": "FAIL",
        "right_ear_detection": "FAIL",
        "left_earring_placement": "FAIL",
        "right_earring_placement": "FAIL",
        "earlobe_alignment": "FAIL",
        "symmetry": "FAIL",
        "hanging_alignment": "FAIL",
    }
    if not frame_lays:
        return {
            "status": "FAIL",
            "final_result": "FAIL",
            "overall_earring_lay_accuracy_pct": 0.0,
            "checks": empty_checks,
            "accuracies": {
                "left_ear_detection_accuracy": 0.0,
                "right_ear_detection_accuracy": 0.0,
                "left_earring_placement_accuracy": 0.0,
                "right_earring_placement_accuracy": 0.0,
                "earlobe_alignment_accuracy": 0.0,
                "left_right_symmetry_accuracy": 0.0,
                "hanging_alignment_accuracy": 0.0,
                "overall_earring_lay_accuracy": 0.0,
            },
            "reason": "No earring frames were evaluated.",
            "ground_truth_accuracy_pct": None,
            "note": "Accuracy is geometric vs expected piercing/earlobe, not confidence.",
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
        "left_ear_detection_accuracy",
        "right_ear_detection_accuracy",
        "left_earring_placement_accuracy",
        "right_earring_placement_accuracy",
        "earlobe_alignment_accuracy",
        "left_right_symmetry_accuracy",
        "hanging_alignment_accuracy",
        "overall_earring_lay_accuracy",
    ]
    accuracies = {}
    for key in accuracy_keys:
        values = [float((item.get("accuracies") or {}).get(key, 0.0)) for item in frame_lays]
        accuracies[key] = sum(values) / len(values) if values else 0.0

    status = worst([str(item.get("status", "FAIL")) for item in frame_lays])
    if checks["left_earring_placement"] == "FAIL" or checks["right_earring_placement"] == "FAIL":
        # Only force FAIL when that side was actually evaluated as FAIL across frames
        status = "FAIL"
    if checks["left_ear_detection"] == "FAIL" and checks["left_earring_placement"] == "FAIL":
        status = "FAIL"

    ground_truth_pct = None
    if manual_statuses:
        paired = [(auto.get("status"), manual) for auto, manual in zip(frame_lays, manual_statuses) if manual]
        if paired:
            matches = sum(1 for auto, manual in paired if auto == manual)
            ground_truth_pct = round(100.0 * matches / len(paired), 1)

    reason = (
        "Earrings are attached to the ears at the intended piercing / earlobe positions."
        if status == "PASS"
        else next(
            (str(item.get("reason")) for item in frame_lays if item.get("status") == "FAIL"),
            "Earring lay did not meet earlobe attachment rules.",
        )
    )
    return {
        "status": status,
        "final_result": status,
        "checks": checks,
        "accuracies": accuracies,
        "overall_earring_lay_accuracy_pct": round(accuracies["overall_earring_lay_accuracy"] * 100.0, 1),
        "ground_truth_accuracy_pct": ground_truth_pct,
        "frames_evaluated": len(frame_lays),
        "reason": reason,
        "note": (
            "Overall earring lay accuracy is the mean geometric agreement with the expected piercing/earlobe model. "
            "Detection confidence is not used as accuracy. "
            "ground_truth_accuracy_pct is set only when manual frame reviews exist."
        ),
    }
