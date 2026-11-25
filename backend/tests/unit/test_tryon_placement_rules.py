from app.cv.necklace_lay import neck_geometry, necklace_tip_span
from app.cv.tryon_placement_rules import (
    ANGLE_PASS_POINTS,
    EARRING_PASS_TRACKING_POINTS,
    EARRING_PASS_X,
    EARRING_PASS_Y,
    LEFT_EARRING_REF,
    NECKLACE_CENTER_REF,
    RIGHT_EARRING_REF,
    aggregate_placement_panel,
    calibration_for_angle,
    classify_euclidean,
    combine_component_statuses,
    earring_pass_tracking,
    euclidean_error,
    snap_angle_key,
    validate_earring_side,
    validate_necklace_frame,
)
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, HeadPose, Landmark


def _face(yaw: float = 0.0) -> FaceLandmarkResult:
    face = FaceLandmarkResult(
        face_detected=True,
        confidence=0.95,
        landmarks=[Landmark(x=0.5, y=0.5) for _ in range(500)],
        head_pose=HeadPose(yaw=yaw, pitch=0.0, roll=0.0),
    )
    face.landmarks[33] = Landmark(x=0.35, y=0.4)
    face.landmarks[263] = Landmark(x=0.65, y=0.4)
    face.landmarks[152] = Landmark(x=0.5, y=0.72, confidence=0.95)
    face.landmarks[234] = Landmark(x=0.32, y=0.55)
    face.landmarks[454] = Landmark(x=0.68, y=0.55)
    return face


def test_euclidean_bands():
    assert classify_euclidean(0.01) == "PASS"
    assert classify_euclidean(0.03) == "WARNING"
    assert classify_euclidean(0.06) == "FAIL"
    assert abs(euclidean_error(0.5, 0.5, 0.5, 0.52) - 0.02) < 1e-9


def test_overall_never_passes_when_any_fail():
    assert combine_component_statuses(["PASS", "FAIL"]) == "FAIL"
    assert combine_component_statuses(["PASS", "WARNING"]) == "WARNING"
    assert combine_component_statuses(["PASS", "PASS"]) == "PASS"
    assert combine_component_statuses(["NOT_TESTABLE", "NOT_TESTABLE"]) == "NOT_TESTABLE"


def test_earring_pass_tracking_points():
    """Earring PASS tracking uses the as-worn local offsets (previous screen centers removed)."""
    assert EARRING_PASS_TRACKING_POINTS["left"]["x"] == -0.8
    assert EARRING_PASS_TRACKING_POINTS["left"]["y"] == -3.8
    assert EARRING_PASS_TRACKING_POINTS["left"]["z"] == -0.4
    assert EARRING_PASS_TRACKING_POINTS["right"]["x"] == -0.9
    assert EARRING_PASS_TRACKING_POINTS["right"]["y"] == -2.5
    assert EARRING_PASS_TRACKING_POINTS["right"]["z"] == -2.0
    assert LEFT_EARRING_REF == (-0.8, -3.8)
    assert RIGHT_EARRING_REF == (-0.9, -2.5)
    assert "left_earring" not in ANGLE_PASS_POINTS[0]
    assert "right_earring" not in ANGLE_PASS_POINTS[0]
    assert ANGLE_PASS_POINTS[0]["necklace_center"] == (0.50, 0.61)
    assert NECKLACE_CENTER_REF == ANGLE_PASS_POINTS[0]["necklace_center"]
    assert earring_pass_tracking("left")["ear"] == "Left, as worn"
    # Absolute bands still cover typical face crops.
    assert EARRING_PASS_X[0] <= 0.38 <= EARRING_PASS_X[1]
    assert EARRING_PASS_Y[0] <= 0.49 <= EARRING_PASS_Y[1]
    assert EARRING_PASS_X[0] <= 0.63 <= EARRING_PASS_X[1]
    assert EARRING_PASS_Y[0] <= 0.32 <= EARRING_PASS_Y[1]


def test_calibration_for_angle_snaps():
    assert snap_angle_key(0) == 0
    assert snap_angle_key(14) == 15
    assert snap_angle_key(None) == 0
    assert calibration_for_angle("left_earring", 0) == (-0.8, -3.8)
    assert calibration_for_angle("right_earring", 15) == (-0.9, -2.5)
    assert calibration_for_angle("necklace_center", 15) == (0.50, 0.60)


def test_earring_pass_and_fail_samples():
    face = _face()
    lobe = EarlobeAnchor(side="left", x=0.38, y=0.49, confidence=1.0, ear_width=0.05, ear_height=0.04)
    good = EarringAnchor(
        side="left",
        x=0.385,
        y=0.492,
        confidence=0.9,
        visible=True,
        source="debug",
        local_x=-0.8,
        local_y=-3.8,
        local_z=-0.4,
    )
    bad = EarringAnchor(
        side="left",
        x=0.55,
        y=0.80,
        confidence=0.9,
        visible=True,
        source="debug",
        local_x=2.0,
        local_y=2.0,
        local_z=2.0,
    )
    passed = validate_earring_side("left", face, lobe, good)
    failed = validate_earring_side("left", face, lobe, bad)
    assert passed["status"] == "PASS"
    assert failed["status"] == "FAIL"
    assert passed["head_angle_deg"] == 0.0


def test_earring_no_placement_is_fail():
    face = _face()
    lobe = EarlobeAnchor(side="left", x=0.38, y=0.49, confidence=1.0, ear_width=0.05, ear_height=0.04)
    missing = EarringAnchor(side="left", visible=False, source="missing")
    # Bare-ear blob near the lobe must not PASS without fed tracking offsets.
    fake_blob = EarringAnchor(side="left", x=0.381, y=0.491, confidence=0.62, visible=True, source="blob")
    assert validate_earring_side("left", face, lobe, missing)["status"] == "FAIL"
    assert validate_earring_side("left", face, lobe, fake_blob)["status"] == "FAIL"


def test_earring_pass_requires_tracking_offsets():
    face = _face(yaw=-12.0)
    lobe = EarlobeAnchor(side="right", x=0.63, y=0.50, confidence=1.0, ear_width=0.05, ear_height=0.04)
    without_local = EarringAnchor(side="right", x=0.632, y=0.501, confidence=0.9, visible=True, source="debug")
    with_local = EarringAnchor(
        side="right",
        x=0.632,
        y=0.501,
        confidence=0.9,
        visible=True,
        source="debug",
        local_x=-0.9,
        local_y=-2.5,
        local_z=-2.0,
    )
    assert validate_earring_side("right", face, lobe, without_local)["status"] == "FAIL"
    result = validate_earring_side("right", face, lobe, with_local)
    assert result["status"] == "PASS"
    assert result["head_angle_deg"] == 15.0
    assert abs(result["predicted_x"] - 0.63) < 0.05
    assert abs(result["predicted_y"] - 0.50) < 0.05


def test_missing_ear_is_not_testable():
    face = _face()
    jewel = EarringAnchor(
        side="left",
        x=0.38,
        y=0.49,
        confidence=0.9,
        visible=True,
        source="debug",
        local_x=-0.8,
        local_y=-3.8,
        local_z=-0.4,
    )
    result = validate_earring_side("left", face, None, jewel)
    assert result["status"] == "NOT_TESTABLE"


def test_necklace_center_fail_when_far():
    face = _face()
    neck = EarlobeAnchor(side="center", x=0.50, y=0.61, confidence=1.0, ear_width=0.12, ear_height=0.08)
    jewel = EarringAnchor(side="center", x=0.20, y=0.40, confidence=0.9, visible=True, source="blob")
    result = validate_necklace_frame(face, neck, jewel)
    assert result["status"] == "FAIL"
    assert result["center"]["status"] == "FAIL"


def test_necklace_pass_at_0deg_center():
    face = _face()
    neck = EarlobeAnchor(side="center", x=0.50, y=0.61, confidence=1.0, ear_width=0.12, ear_height=0.08)
    geometry = neck_geometry(face, neck)
    assert geometry is not None
    half_span = necklace_tip_span(geometry.neck_width) * 0.5
    center = EarringAnchor(side="center", x=0.502, y=0.612, confidence=0.9, visible=True, source="debug")
    left = EarringAnchor(
        side="left", x=geometry.center_x - half_span, y=geometry.neckline_y, confidence=0.9, visible=True, source="debug"
    )
    right = EarringAnchor(
        side="right", x=geometry.center_x + half_span, y=geometry.neckline_y, confidence=0.9, visible=True, source="debug"
    )
    result = validate_necklace_frame(face, neck, center, left, right)
    assert result["center"]["status"] == "PASS"
    assert result["status"] == "PASS"
    assert result["head_angle_deg"] == 0.0


def test_panel_summary_counts():
    panel = aggregate_placement_panel(
        jewelry_type="earring",
        frame_panels=[
            {
                "left": {"status": "PASS", "x": 0.38, "y": 0.49, "placement_error": 0.01, "head_angle_deg": 0},
                "right": {"status": "PASS", "x": 0.63, "y": 0.49, "placement_error": 0.01, "head_angle_deg": 0},
            },
            {
                "left": {"status": "FAIL", "x": 0.1, "y": 0.9, "placement_error": 0.2, "head_angle_deg": 15, "reason": "floats"},
                "right": {"status": "WARNING", "x": 0.65, "y": 0.52, "placement_error": 0.03, "head_angle_deg": 15},
            },
            {
                "left": {"status": "NOT_TESTABLE"},
                "right": {"status": "NOT_TESTABLE"},
            },
        ],
    )
    assert panel["overall_status"] == "FAIL"
    assert panel["summary"]["passed_frames"] == 1
    assert panel["summary"]["failed_frames"] == 1
    assert panel["summary"]["not_testable_frames"] == 1
    assert panel["summary"]["testable_frames"] == 2
    assert panel["thresholds"]["earring_pass_tracking_points"]["left"] == {
        "ear": "Left, as worn",
        "x": -0.8,
        "y": -3.8,
        "z": -0.4,
    }
    assert panel["thresholds"]["earring_pass_tracking_points"]["right"]["z"] == -2.0
    assert "left_earring" not in panel["thresholds"]["angle_pass_points"]["0"]
    assert panel["thresholds"]["angle_pass_points"]["15"]["necklace_center"] == [0.50, 0.60]
