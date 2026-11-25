"""Earring and necklace PASS / WARNING / FAIL / NOT_TESTABLE rules.

Uses landmark-relative predicted positions (earlobe / neckline). Absolute
calibration coordinates are warped by the current face and only applied as a
secondary check on near-frontal head angles.
"""

from __future__ import annotations

import math
from typing import Iterable

from app.cv.necklace_lay import neck_geometry, necklace_tip_span
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult

# Euclidean error in normalized image coordinates (section 4).
EUCLIDEAN_PASS = 0.02
EUCLIDEAN_WARNING = 0.05

# Absolute band checks only when |yaw| is within this frontal cone.
FRONTAL_YAW_DEG = 35.0

# Snap angles used by the dashboard / jewel-lay automation.
SNAP_ANGLES_DEG: tuple[int, ...] = (0, 15, 30, 45, 60, 75, 90)

# Earring pass tracking points (local attachment offsets as worn).
# Replaces the previous screen-space angle PASS centers for earrings.
EARRING_PASS_TRACKING_POINTS: dict[str, dict[str, float | str]] = {
    "left": {"ear": "Left, as worn", "x": -0.8, "y": -3.8, "z": -0.4},
    "right": {"ear": "Right, as worn", "x": -0.9, "y": -2.5, "z": -2.0},
}

# Absolute tolerance in the same units as EARRING_PASS_TRACKING_POINTS.
EARRING_PASS_TRACKING_TOLERANCE = 0.35
EARRING_PASS_TRACKING_WARNING = 0.70

# Necklace angle PASS centers (normalized x,y). Earring centers are no longer used.
ANGLE_PASS_POINTS: dict[int, dict[str, tuple[float, float]]] = {
    0: {
        "necklace_center": (0.50, 0.61),
        "necklace_left": (0.40, 0.58),
        "necklace_right": (0.60, 0.58),
    },
    15: {
        "necklace_center": (0.50, 0.60),
        "necklace_left": (0.39, 0.57),
        "necklace_right": (0.61, 0.59),
    },
    30: {
        "necklace_center": (0.50, 0.59),
        "necklace_left": (0.38, 0.56),
        "necklace_right": (0.62, 0.60),
    },
    45: {
        "necklace_center": (0.50, 0.58),
        "necklace_left": (0.37, 0.55),
        "necklace_right": (0.63, 0.61),
    },
    60: {
        "necklace_center": (0.50, 0.57),
        "necklace_left": (0.36, 0.54),
        "necklace_right": (0.64, 0.62),
    },
    75: {
        "necklace_center": (0.50, 0.56),
        "necklace_left": (0.35, 0.53),
        "necklace_right": (0.65, 0.63),
    },
    90: {
        "necklace_center": (0.50, 0.55),
        "necklace_left": (0.34, 0.52),
        "necklace_right": (0.66, 0.64),
    },
}

# Earring refs = pass tracking x,y (local offsets). Necklace refs stay screen-space.
LEFT_EARRING_REF = (
    float(EARRING_PASS_TRACKING_POINTS["left"]["x"]),
    float(EARRING_PASS_TRACKING_POINTS["left"]["y"]),
)
RIGHT_EARRING_REF = (
    float(EARRING_PASS_TRACKING_POINTS["right"]["x"]),
    float(EARRING_PASS_TRACKING_POINTS["right"]["y"]),
)
NECKLACE_CENTER_REF = ANGLE_PASS_POINTS[0]["necklace_center"]
NECKLACE_LEFT_REF = ANGLE_PASS_POINTS[0]["necklace_left"]
NECKLACE_RIGHT_REF = ANGLE_PASS_POINTS[0]["necklace_right"]

# Absolute PASS / FAIL bands cover typical face crops (ears can sit near y≈0.30).
# Landmark attachment is primary; absolute bands are a secondary screen-space guard.
EARRING_PASS_X = (0.22, 0.78)
EARRING_PASS_Y = (0.22, 0.62)
EARRING_FAIL_X = (0.10, 0.90)
EARRING_FAIL_Y = (0.10, 0.78)

NECKLACE_PASS_X = (0.35, 0.65)
NECKLACE_PASS_Y = (0.40, 0.78)
NECKLACE_FAIL_X = (0.22, 0.78)
NECKLACE_FAIL_Y = (0.28, 0.88)


def euclidean_error(xp: float, yp: float, xa: float, ya: float) -> float:
    return float(math.sqrt((xp - xa) ** 2 + (yp - ya) ** 2))


def classify_euclidean(
    error: float,
    *,
    pass_threshold: float = EUCLIDEAN_PASS,
    fail_threshold: float = EUCLIDEAN_WARNING,
) -> str:
    if error <= pass_threshold:
        return "PASS"
    if error <= fail_threshold:
        return "WARNING"
    return "FAIL"


def combine_component_statuses(statuses: Iterable[str | None]) -> str:
    """Overall rule from section 5. Never promotes FAIL/WARNING to PASS."""
    values = [str(status).upper() for status in statuses if status]
    testable = [status for status in values if status not in {"NOT_TESTABLE", "NOT_RUN", "WAITING", "SKIPPED"}]
    if any(status == "FAIL" for status in testable):
        return "FAIL"
    if any(status == "WARNING" for status in testable):
        return "WARNING"
    if testable and all(status == "PASS" for status in testable):
        return "PASS"
    return "NOT_TESTABLE"


def head_angle_deg(face: FaceLandmarkResult | None) -> float | None:
    if face is None or face.head_pose is None:
        return None
    yaw = float(face.head_pose.yaw)
    # Snap to the nearest supported reporting angle for the dashboard.
    abs_yaw = abs(yaw)
    nearest = min(SNAP_ANGLES_DEG, key=lambda value: abs(value - abs_yaw))
    return float(nearest if abs(nearest - abs_yaw) <= 8 else round(abs_yaw))


def snap_angle_key(angle: float | None) -> int:
    """Map a measured / snapped head angle onto ANGLE_PASS_POINTS."""
    if angle is None:
        return 0
    abs_angle = abs(float(angle))
    return int(min(SNAP_ANGLES_DEG, key=lambda value: abs(value - abs_angle)))


def earring_pass_tracking(side: str) -> dict[str, float | str]:
    """Return the earring pass tracking point for left/right as worn."""
    key = "left" if str(side).lower().startswith("left") else "right"
    return dict(EARRING_PASS_TRACKING_POINTS[key])


def tracking_offset_error(
    local_x: float | None,
    local_y: float | None,
    local_z: float | None,
    side: str,
) -> float | None:
    """3D Euclidean error vs fed pass-tracking point. None if locals are missing."""
    if local_x is None or local_y is None:
        return None
    point = earring_pass_tracking(side)
    dz = 0.0 if local_z is None else float(local_z) - float(point["z"])
    return float(
        math.sqrt(
            (float(local_x) - float(point["x"])) ** 2
            + (float(local_y) - float(point["y"])) ** 2
            + dz**2
        )
    )


def classify_tracking_error(error: float | None) -> str:
    if error is None:
        return "FAIL"
    if error <= EARRING_PASS_TRACKING_TOLERANCE:
        return "PASS"
    if error <= EARRING_PASS_TRACKING_WARNING:
        return "WARNING"
    return "FAIL"


def calibration_for_angle(component: str, angle: float | None) -> tuple[float, float]:
    """Return the PASS-center calibration point for a jewelry component at this angle.

    Earrings use fixed local pass-tracking offsets (x, y), not screen-space angle centers.
    """
    if component in {"left_earring", "right_earring"}:
        side = "left" if component.startswith("left") else "right"
        point = earring_pass_tracking(side)
        return float(point["x"]), float(point["y"])
    key = snap_angle_key(angle)
    table = ANGLE_PASS_POINTS.get(key) or ANGLE_PASS_POINTS[0]
    if component in table:
        return table[component]
    defaults = {
        "necklace_center": NECKLACE_CENTER_REF,
        "necklace_left": NECKLACE_LEFT_REF,
        "necklace_right": NECKLACE_RIGHT_REF,
    }
    return defaults.get(component, NECKLACE_CENTER_REF)


def fail_radius_for_component(_component: str = "") -> float:
    """Normalized Euclidean radius outside which jewel lay is FAIL."""
    return EUCLIDEAN_WARNING


def pass_radius_for_component(_component: str = "") -> float:
    """Normalized Euclidean radius inside which jewel lay is PASS."""
    return EUCLIDEAN_PASS


def _band_status(value: float, pass_band: tuple[float, float], fail_band: tuple[float, float]) -> str:
    lo_pass, hi_pass = pass_band
    lo_fail, hi_fail = fail_band
    if lo_pass <= value <= hi_pass:
        return "PASS"
    if value < lo_fail or value > hi_fail:
        return "FAIL"
    return "WARNING"


def _warp_calibration(
    face: FaceLandmarkResult | None,
    calib: tuple[float, float],
    landmark: EarlobeAnchor | None,
) -> tuple[float, float]:
    """Blend calibration lightly with the live landmark.

    Attachment scoring uses the landmark itself. Calibration is only a soft prior so
    different face crops do not invent a far-away predicted point that false-fails.
    """
    if landmark is None:
        return calib
    if face is None or face.head_pose is None:
        return (0.92 * landmark.x + 0.08 * calib[0], 0.92 * landmark.y + 0.08 * calib[1])
    yaw = abs(float(face.head_pose.yaw))
    # Stay landmark-dominant at every angle (0° ≈ 0.90 landmark, 90° ≈ landmark only).
    landmark_weight = min(1.0, max(0.90, 0.90 + 0.10 * (yaw / 90.0)))
    calib_weight = 1.0 - landmark_weight
    return (
        landmark_weight * landmark.x + calib_weight * calib[0],
        landmark_weight * landmark.y + calib_weight * calib[1],
    )


def validate_earring_side(
    side: str,
    face: FaceLandmarkResult | None,
    earlobe: EarlobeAnchor | None,
    jewelry: EarringAnchor | None,
    *,
    required: bool = True,
    pass_threshold: float = EUCLIDEAN_PASS,
    fail_threshold: float = EUCLIDEAN_WARNING,
) -> dict:
    angle = head_angle_deg(face)
    component = f"{side}_earring"
    tracking = earring_pass_tracking(side)

    if earlobe is None:
        status = "NOT_TESTABLE" if required else "NOT_TESTABLE"
        return {
            "component": f"{side}_earring",
            "side": side,
            "status": status,
            "x": None,
            "y": None,
            "predicted_x": None,
            "predicted_y": None,
            "placement_error": None,
            "head_angle_deg": angle,
            "reason": f"{side.capitalize()} ear is not visible / not testable.",
            "checks": {"visibility": status, "euclidean": "NOT_TESTABLE", "absolute_band": "NOT_TESTABLE"},
        }

    # Predicted attachment = live earlobe. PASS requires a real placed earring on the
    # fed pass-tracking offsets — bare ears / guessed blobs must not PASS.
    predicted = (float(earlobe.x), float(earlobe.y))
    has_viewport = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
    has_local = bool(
        jewelry
        and jewelry.visible
        and jewelry.local_x is not None
        and jewelry.local_y is not None
    )
    jewelry_ok = has_viewport or has_local
    if not jewelry_ok:
        return {
            "component": f"{side}_earring",
            "side": side,
            "status": "FAIL" if required else "NOT_TESTABLE",
            "x": None,
            "y": None,
            "predicted_x": predicted[0],
            "predicted_y": predicted[1],
            "placement_error": None,
            "head_angle_deg": angle,
            "pass_tracking": tracking,
            "tracking_error": None,
            "reason": (
                f"{side.capitalize()} earring is not placed — PASS requires jewelry on the "
                f"pass tracking point ({tracking['x']}, {tracking['y']}, {tracking['z']})."
                if required
                else f"{side.capitalize()} earring is not visible / not testable."
            ),
            "checks": {
                "visibility": "FAIL" if required else "NOT_TESTABLE",
                "euclidean": "FAIL" if required else "NOT_TESTABLE",
                "pass_tracking": "FAIL" if required else "NOT_TESTABLE",
                "absolute_band": "NOT_TESTABLE",
            },
        }

    assert jewelry is not None
    # Local-only debug payloads still score against fed pass-tracking points.
    if not has_viewport:
        track_err = tracking_offset_error(jewelry.local_x, jewelry.local_y, jewelry.local_z, side)
        tracking_status = classify_tracking_error(track_err)
        status = tracking_status if required else ("PASS" if tracking_status == "PASS" else tracking_status)
        return {
            "component": f"{side}_earring",
            "side": side,
            "status": status if required else status,
            "x": None,
            "y": None,
            "predicted_x": predicted[0],
            "predicted_y": predicted[1],
            "placement_error": track_err,
            "head_angle_deg": angle,
            "pass_tracking": tracking,
            "tracking_error": track_err,
            "reason": (
                f"{side.capitalize()} earring is placed on the pass tracking point "
                f"({tracking['x']}, {tracking['y']}, {tracking['z']})."
                if tracking_status == "PASS"
                else (
                    f"{side.capitalize()} earring is off the pass tracking point "
                    f"(error {track_err:.2f}; pass ≤ {EARRING_PASS_TRACKING_TOLERANCE})."
                    if track_err is not None
                    else f"{side.capitalize()} earring is not placed on the pass tracking point."
                )
            ),
            "checks": {
                "visibility": "PASS",
                "euclidean": "NOT_TESTABLE",
                "pass_tracking": tracking_status,
                "absolute_band": "NOT_TESTABLE",
            },
        }

    jx, jy = float(jewelry.x), float(jewelry.y)
    ear_w = max(0.012, float(earlobe.ear_width))
    dx, dy = jx - earlobe.x, jy - earlobe.y
    # Natural hang may sit below the piercing; ignore downward hang within 1.4 ear-widths.
    hang_allowance = 1.4 * ear_w
    adj_dy = max(0.0, dy - hang_allowance) if dy >= 0 else dy
    error = float(math.hypot(dx, adj_dy))
    raw_error = euclidean_error(predicted[0], predicted[1], jx, jy)
    euclid_status = classify_euclidean(error, pass_threshold=pass_threshold, fail_threshold=fail_threshold)

    reasons: list[str] = []
    source = str(jewelry.source or "missing").lower()
    # Pixel guesses on a bare ear must never become PASS.
    if source in {"blob", "template", "missing"} and float(jewelry.confidence or 0.0) < 0.85:
        return {
            "component": f"{side}_earring",
            "side": side,
            "status": "FAIL",
            "x": jx,
            "y": jy,
            "predicted_x": predicted[0],
            "predicted_y": predicted[1],
            "placement_error": error,
            "head_angle_deg": angle,
            "pass_tracking": tracking,
            "tracking_error": None,
            "reason": (
                f"{side.capitalize()} earring was not confidently detected as placed jewelry. "
                f"PASS requires placement on pass tracking "
                f"({tracking['x']}, {tracking['y']}, {tracking['z']})."
            ),
            "checks": {
                "visibility": "FAIL",
                "euclidean": euclid_status,
                "pass_tracking": "FAIL",
                "absolute_band": "NOT_TESTABLE",
            },
        }

    track_err = tracking_offset_error(jewelry.local_x, jewelry.local_y, jewelry.local_z, side)
    tracking_status = classify_tracking_error(track_err)
    if track_err is None:
        # Without local offsets we cannot confirm the fed pass-tracking values.
        tracking_status = "FAIL"
        reasons.append(
            f"{side.capitalize()} earring pass tracking offsets were not reported; "
            f"PASS requires ({tracking['x']}, {tracking['y']}, {tracking['z']})."
        )
    elif tracking_status == "FAIL":
        reasons.append(
            f"{side.capitalize()} earring is off the pass tracking point "
            f"(error {track_err:.2f}; pass ≤ {EARRING_PASS_TRACKING_TOLERANCE})."
        )
    elif tracking_status == "WARNING":
        reasons.append(
            f"{side.capitalize()} earring is near but not on the pass tracking point "
            f"(error {track_err:.2f})."
        )

    absolute_status = "PASS"
    yaw = abs(float(face.head_pose.yaw)) if face and face.head_pose else 0.0
    # If the piece is on the lobe, absolute screen bands must not override PASS.
    if error <= pass_threshold:
        absolute_status = "PASS"
    elif yaw <= FRONTAL_YAW_DEG:
        x_status = _band_status(jx, EARRING_PASS_X, EARRING_FAIL_X)
        y_status = _band_status(jy, EARRING_PASS_Y, EARRING_FAIL_Y)
        absolute_status = combine_component_statuses([x_status, y_status])
        if absolute_status == "FAIL":
            reasons.append(f"{side.capitalize()} earring absolute position is outside the fail band.")
        elif absolute_status == "WARNING":
            reasons.append(f"{side.capitalize()} earring absolute position is outside the pass band.")
    else:
        absolute_status = "PASS"  # landmark-relative only at large angles

    # Attachment / float / swap heuristics relative to the earlobe.
    attachment_status = "PASS"
    if dy < -0.55 * ear_w and raw_error > pass_threshold:
        attachment_status = "FAIL"
        reasons.append(f"{side.capitalize()} earring floats above the earlobe.")
    elif abs(dx) > 1.4 * ear_w and abs(dy) > 1.6 * ear_w:
        attachment_status = "FAIL"
        reasons.append(f"{side.capitalize()} earring floats away from the ear.")
    elif error > fail_threshold:
        attachment_status = "FAIL"
        reasons.append(f"{side.capitalize()} earring is not attached to the earlobe.")
    elif error > pass_threshold:
        attachment_status = "WARNING"
        reasons.append(f"{side.capitalize()} earring is slightly off the earlobe.")

    if jewelry.rotation is not None and abs(float(jewelry.rotation)) > 55:
        attachment_status = "FAIL" if attachment_status != "WARNING" else "FAIL"
        reasons.append(f"{side.capitalize()} earring is incorrectly rotated.")

    face_mid = 0.5
    if face and face.landmarks and len(face.landmarks) > 263:
        face_mid = (face.landmarks[33].x + face.landmarks[263].x) / 2.0
    swapped = (side == "left" and jx > face_mid + 0.04) or (side == "right" and jx < face_mid - 0.04)
    if swapped and error > pass_threshold:
        attachment_status = "FAIL"
        reasons.append("Left and right earrings appear incorrectly swapped.")

    status = combine_component_statuses(
        [euclid_status, absolute_status, attachment_status, tracking_status]
    )
    if status == "PASS":
        reason = (
            f"{side.capitalize()} earring is placed on the pass tracking point "
            f"({tracking['x']}, {tracking['y']}, {tracking['z']})."
        )
    elif status == "WARNING":
        reason = " ".join(reasons) or f"{side.capitalize()} earring placement is near the tolerance edge."
    else:
        reason = " ".join(reasons) or f"{side.capitalize()} earring placement failed."

    return {
        "component": f"{side}_earring",
        "side": side,
        "status": status,
        "x": jx,
        "y": jy,
        "predicted_x": predicted[0],
        "predicted_y": predicted[1],
        "placement_error": error,
        "head_angle_deg": angle,
        "pass_tracking": tracking,
        "tracking_error": track_err,
        "reason": reason,
        "checks": {
            "visibility": "PASS",
            "euclidean": euclid_status,
            "pass_tracking": tracking_status,
            "absolute_band": absolute_status,
            "attachment": attachment_status,
        },
    }


def validate_necklace_frame(
    face: FaceLandmarkResult | None,
    neck: EarlobeAnchor | None,
    center_jewelry: EarringAnchor | None,
    left_jewelry: EarringAnchor | None = None,
    right_jewelry: EarringAnchor | None = None,
    *,
    pass_threshold: float = EUCLIDEAN_PASS,
    fail_threshold: float = EUCLIDEAN_WARNING,
) -> dict:
    angle = head_angle_deg(face)
    geometry = neck_geometry(face, neck)
    center_ref = calibration_for_angle("necklace_center", angle)
    left_ref = calibration_for_angle("necklace_left", angle)
    right_ref = calibration_for_angle("necklace_right", angle)

    if neck is None or geometry is None:
        not_testable = {
            "status": "NOT_TESTABLE",
            "x": None,
            "y": None,
            "placement_error": None,
            "reason": "Neck / shoulder anchors are not visible / not testable.",
        }
        return {
            "status": "NOT_TESTABLE",
            "head_angle_deg": angle,
            "center": {**not_testable, "component": "necklace_center"},
            "left_anchor": {**not_testable, "component": "necklace_left_anchor"},
            "right_anchor": {**not_testable, "component": "necklace_right_anchor"},
            "pendant_alignment": "NOT_TESTABLE",
            "placement_error": None,
            "reason": not_testable["reason"],
        }

    center_pred = _warp_calibration(face, center_ref, neck)
    half_span = necklace_tip_span(geometry.neck_width) * 0.5
    left_pred = (geometry.center_x - half_span, geometry.neckline_y)
    right_pred = (geometry.center_x + half_span, geometry.neckline_y)
    # Soft blend with angle-specific calibration for near-frontal views.
    left_calib = _warp_calibration(
        face,
        left_ref,
        EarlobeAnchor(side="left", x=left_pred[0], y=left_pred[1], confidence=geometry.confidence, ear_width=geometry.neck_width, ear_height=geometry.neck_width * 0.5),
    )
    right_calib = _warp_calibration(
        face,
        right_ref,
        EarlobeAnchor(side="right", x=right_pred[0], y=right_pred[1], confidence=geometry.confidence, ear_width=geometry.neck_width, ear_height=geometry.neck_width * 0.5),
    )

    def _point_result(name: str, predicted: tuple[float, float], jewelry: EarringAnchor | None, required: bool) -> dict:
        ok = bool(jewelry and jewelry.visible and jewelry.x is not None and jewelry.y is not None)
        if not ok:
            return {
                "component": name,
                "status": "FAIL" if required else "NOT_TESTABLE",
                "x": None,
                "y": None,
                "predicted_x": predicted[0],
                "predicted_y": predicted[1],
                "placement_error": None,
                "reason": (
                    "Necklace is detached from its anchors."
                    if required
                    else f"{name.replace('_', ' ')} is not visible / not testable."
                ),
            }
        assert jewelry is not None and jewelry.x is not None and jewelry.y is not None
        jx, jy = float(jewelry.x), float(jewelry.y)
        error = euclidean_error(predicted[0], predicted[1], jx, jy)
        status = classify_euclidean(error, pass_threshold=pass_threshold, fail_threshold=fail_threshold)
        reason = (
            f"{name.replace('_', ' ').capitalize()} is within tolerance."
            if status == "PASS"
            else (
                f"{name.replace('_', ' ').capitalize()} is slightly misaligned."
                if status == "WARNING"
                else f"{name.replace('_', ' ').capitalize()} floats away from the neck or chest."
            )
        )
        return {
            "component": name,
            "status": status,
            "x": jx,
            "y": jy,
            "predicted_x": predicted[0],
            "predicted_y": predicted[1],
            "placement_error": error,
            "reason": reason,
        }

    center = _point_result("necklace_center", center_pred, center_jewelry, required=True)
    left_anchor = _point_result("necklace_left_anchor", left_calib, left_jewelry or center_jewelry, required=False)
    right_anchor = _point_result("necklace_right_anchor", right_calib, right_jewelry or center_jewelry, required=False)

    # Absolute band on center when frontal.
    absolute_status = "PASS"
    if center.get("x") is not None and face and face.head_pose and abs(float(face.head_pose.yaw)) <= FRONTAL_YAW_DEG:
        x_status = _band_status(float(center["x"]), NECKLACE_PASS_X, NECKLACE_FAIL_X)
        y_status = _band_status(float(center["y"]), NECKLACE_PASS_Y, NECKLACE_FAIL_Y)
        absolute_status = combine_component_statuses([x_status, y_status])
        if absolute_status != "PASS":
            center["status"] = combine_component_statuses([center["status"], absolute_status])
            if absolute_status == "FAIL":
                center["reason"] = "Necklace is incorrectly positioned outside the fail band."

    pendant_status = "PASS"
    if center.get("x") is not None and center.get("y") is not None:
        pendant_error = abs(float(center["x"]) - geometry.pendant_x)
        if pendant_error > fail_threshold * 2.5:
            pendant_status = "FAIL"
            center["reason"] = "Necklace pendant is significantly off-center."
            center["status"] = combine_component_statuses([center["status"], "FAIL"])
        elif pendant_error > pass_threshold * 2.0:
            pendant_status = "WARNING"
            center["status"] = combine_component_statuses([center["status"], "WARNING"])

    status = combine_component_statuses(
        [center["status"], left_anchor["status"], right_anchor["status"], pendant_status, absolute_status]
    )
    errors = [
        value
        for value in (center.get("placement_error"), left_anchor.get("placement_error"), right_anchor.get("placement_error"))
        if isinstance(value, (int, float))
    ]
    placement_error = max(errors) if errors else None
    if status == "PASS":
        reason = "Necklace center and anchors are correctly positioned."
    elif status == "NOT_TESTABLE":
        reason = "Necklace anchors are not visible / not testable."
    else:
        reason = center.get("reason") or left_anchor.get("reason") or right_anchor.get("reason") or "Necklace placement failed."

    return {
        "status": status,
        "head_angle_deg": angle,
        "center": center,
        "left_anchor": left_anchor,
        "right_anchor": right_anchor,
        "pendant_alignment": pendant_status,
        "placement_error": placement_error,
        "reason": reason,
    }


def aggregate_placement_panel(
    *,
    jewelry_type: str,
    frame_panels: list[dict],
) -> dict:
    """Build the dashboard validation panel + video test summary."""
    total = len(frame_panels)
    if jewelry_type == "earring":
        left_statuses = [str((item.get("left") or {}).get("status") or "NOT_TESTABLE") for item in frame_panels]
        right_statuses = [str((item.get("right") or {}).get("status") or "NOT_TESTABLE") for item in frame_panels]
        frame_statuses = [combine_component_statuses([left, right]) for left, right in zip(left_statuses, right_statuses)]
        latest_left = next((item.get("left") for item in reversed(frame_panels) if item.get("left")), None)
        latest_right = next((item.get("right") for item in reversed(frame_panels) if item.get("right")), None)
        components = {
            "left_earring": _summarize_component(left_statuses, latest_left),
            "right_earring": _summarize_component(right_statuses, latest_right),
        }
    else:
        frame_statuses = [str(item.get("status") or "NOT_TESTABLE") for item in frame_panels]
        latest = frame_panels[-1] if frame_panels else {}
        components = {
            "necklace_center": _summarize_component(
                [str((item.get("center") or {}).get("status") or "NOT_TESTABLE") for item in frame_panels],
                latest.get("center"),
            ),
            "left_anchor": _summarize_component(
                [str((item.get("left_anchor") or {}).get("status") or "NOT_TESTABLE") for item in frame_panels],
                latest.get("left_anchor"),
            ),
            "right_anchor": _summarize_component(
                [str((item.get("right_anchor") or {}).get("status") or "NOT_TESTABLE") for item in frame_panels],
                latest.get("right_anchor"),
            ),
            "pendant_alignment": {
                "status": combine_component_statuses(
                    [str(item.get("pendant_alignment") or "NOT_TESTABLE") for item in frame_panels]
                ),
                "reason": latest.get("reason"),
            },
        }

    passed = sum(1 for status in frame_statuses if status == "PASS")
    warnings = sum(1 for status in frame_statuses if status == "WARNING")
    failed = sum(1 for status in frame_statuses if status == "FAIL")
    not_testable = sum(1 for status in frame_statuses if status == "NOT_TESTABLE")
    testable = passed + warnings + failed
    overall = combine_component_statuses(frame_statuses)
    pass_pct = (100.0 * passed / testable) if testable else 0.0
    earring_accuracy = None
    necklace_accuracy = None
    if jewelry_type == "earring":
        earring_accuracy = pass_pct
    else:
        necklace_accuracy = pass_pct

    return {
        "jewelry_type": jewelry_type,
        "overall_status": overall,
        "components": components,
        "summary": {
            "total_frames": total,
            "passed_frames": passed,
            "warning_frames": warnings,
            "failed_frames": failed,
            "not_testable_frames": not_testable,
            "testable_frames": testable,
            "overall_result": overall,
            "pass_percentage": round(pass_pct, 1),
            "earring_accuracy": None if earring_accuracy is None else round(earring_accuracy, 1),
            "necklace_accuracy": None if necklace_accuracy is None else round(necklace_accuracy, 1),
        },
        "thresholds": {
            "euclidean_pass": EUCLIDEAN_PASS,
            "euclidean_warning": EUCLIDEAN_WARNING,
            "euclidean_fail_above": EUCLIDEAN_WARNING,
            "frontal_yaw_deg": FRONTAL_YAW_DEG,
            "earring_pass_band": {"x": list(EARRING_PASS_X), "y": list(EARRING_PASS_Y)},
            "earring_fail_band": {"x": list(EARRING_FAIL_X), "y": list(EARRING_FAIL_Y)},
            "necklace_pass_band": {"x": list(NECKLACE_PASS_X), "y": list(NECKLACE_PASS_Y)},
            "necklace_fail_band": {"x": list(NECKLACE_FAIL_X), "y": list(NECKLACE_FAIL_Y)},
            "earring_pass_tracking_points": {
                side: {
                    "ear": point["ear"],
                    "x": float(point["x"]),
                    "y": float(point["y"]),
                    "z": float(point["z"]),
                }
                for side, point in EARRING_PASS_TRACKING_POINTS.items()
            },
            "earring_pass_tracking_tolerance": EARRING_PASS_TRACKING_TOLERANCE,
            "earring_pass_tracking_warning": EARRING_PASS_TRACKING_WARNING,
            "angle_pass_points": {
                str(angle): {key: list(point) for key, point in points.items()}
                for angle, points in ANGLE_PASS_POINTS.items()
            },
        },
        "frames": frame_panels,
    }


def _summarize_component(statuses: list[str], latest: dict | None) -> dict:
    status = combine_component_statuses(statuses)
    latest = latest or {}
    return {
        "status": status,
        "x": latest.get("x"),
        "y": latest.get("y"),
        "placement_error": latest.get("placement_error"),
        "head_angle_deg": latest.get("head_angle_deg"),
        "reason": latest.get("reason"),
        "predicted_x": latest.get("predicted_x"),
        "predicted_y": latest.get("predicted_y"),
    }
