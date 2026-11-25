import math

from app.cv.debug_config import DEBUG_PROFILES, debug_profile_for
from app.cv.debug_landmarks import contour_indices, selected_landmark_index, uses_hand_landmarks
from app.cv.ear_geometry import LOBE_LANDMARK
from app.cv.landmark_validation import (
    ATTACHMENT_ANCHOR_MISSING,
    EARRING_MODEL_NOT_LOADED,
    LOW_LANDMARK_CONFIDENCE,
    NORMALIZED_DISTANCE_EXCEEDED,
    REQUIRED_LANDMARK_NOT_DETECTED,
    ROTATION_OUT_OF_TOLERANCE,
    SCALE_OUT_OF_RANGE,
    TEMPORAL_DRIFT,
    TRACKING_LOST,
    evaluate_frame,
    reason_for_missing_anchor,
    summarize_validation,
)
from app.cv.tryon_placement_rules import EUCLIDEAN_WARNING
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult, HandLandmarkResult, Landmark

FRAME = (1000, 1000)


def _face(detected: bool = True, count: int = 468) -> FaceLandmarkResult:
    return FaceLandmarkResult(
        face_detected=detected,
        landmarks=[Landmark(x=0.5, y=0.5) for _ in range(count)],
        confidence=0.9,
    )


def _expected(x: float = 0.245, y: float = 0.310, confidence: float = 0.9) -> EarlobeAnchor:
    return EarlobeAnchor(side="left", x=x, y=y, confidence=confidence, ear_width=0.05, ear_height=0.09)


def _jewelry(x: float, y: float, **kwargs) -> EarringAnchor:
    payload = {"side": "left", "x": x, "y": y, "visible": True, "confidence": 0.95, "source": "debug_state"}
    payload.update(kwargs)
    return EarringAnchor(**payload)


def _run(jewelry, expected=None, face=None, hand=None, profile=None, frame_number=0, diagnostics=None):
    return evaluate_frame(
        frame_number=frame_number,
        timestamp_ms=frame_number * 100,
        side="left",
        profile=profile or debug_profile_for("earring"),
        face=_face() if face is None else face,
        hand=hand,
        expected=_expected() if expected is None else expected,
        jewelry=jewelry,
        frame_size=FRAME,
        landmark_index=LOBE_LANDMARK["left"],
        diagnostics=diagnostics,
    )


def test_landmark_mapping_matches_production_estimators():
    assert selected_landmark_index("earring", "left") == LOBE_LANDMARK["left"]
    assert selected_landmark_index("earring", "right") == LOBE_LANDMARK["right"]
    assert contour_indices("earring", "left")[0] == 234
    assert contour_indices("ring", "left") is None
    assert uses_hand_landmarks("bracelet") is True
    assert uses_hand_landmarks("necklace") is False


def test_position_within_tolerance_passes():
    # Expected (245, 310) px, actual (247, 312) px -> 2.83 px error on a 1000x1000 frame.
    result = _run(_jewelry(0.247, 0.312, rotation=0.0, scale=1.0))
    assert result.position_error_px is not None
    assert math.isclose(result.position_error_px, 2.8284, rel_tol=1e-3)
    # Normalized error is in image space, the same space as the project's Euclidean bands.
    assert math.isclose(result.position_error_normalized, 0.0028284, rel_tol=1e-3)
    assert result.checks["position"].status == "PASS"
    assert result.status == "PASS"
    assert result.failure_reason is None


def test_body_relative_error_is_reported_but_does_not_gate_the_band():
    result = _run(_jewelry(0.247, 0.312, rotation=0.0, scale=1.0))
    # 0.0028 normalized over a 0.05 ear width is 0.057 ear-widths; this is context only.
    assert math.isclose(result.position_error_body_relative, 0.0566, rel_tol=1e-2)
    assert result.checks["position"].status == "PASS"


def test_position_outside_normalized_tolerance_fails():
    result = _run(_jewelry(0.32, 0.37, rotation=0.0, scale=1.0))
    assert result.checks["position"].status == "FAIL"
    assert result.status == "FAIL"
    assert result.failure_reason == NORMALIZED_DISTANCE_EXCEEDED


def test_pixel_tolerance_only_gates_when_it_is_set():
    jewelry = _jewelry(0.2485, 0.3135, rotation=0.0, scale=1.0)
    # ~4.9 px: inside the normalized band, so it passes with no pixel budget set.
    assert _run(jewelry).checks["position"].status == "PASS"
    strict = debug_profile_for("earring", {"position_tolerance_px": 2.0})
    assert _run(jewelry, profile=strict).checks["position"].status == "FAIL"


def test_missing_face_reports_landmark_not_detected():
    result = _run(_jewelry(0.247, 0.312), face=_face(detected=False), expected=None)
    assert result.status == "FAIL"
    assert result.failure_reason == REQUIRED_LANDMARK_NOT_DETECTED
    assert result.checks["position"].status == "NOT_TESTABLE"


def test_low_landmark_confidence_is_its_own_reason():
    result = _run(_jewelry(0.247, 0.312), expected=_expected(confidence=0.2))
    assert result.failure_reason == LOW_LANDMARK_CONFIDENCE


def test_unplaced_jewelry_never_passes():
    result = _run(EarringAnchor(side="left", visible=False, source="missing"))
    assert result.status == "FAIL"
    assert result.failure_reason == TRACKING_LOST
    assert result.checks["visibility"].status == "FAIL"


def test_missing_anchor_names_the_pipeline_stage_that_broke():
    missing = EarringAnchor(side="left", visible=False, source="missing")

    not_loaded = _run(missing, diagnostics={"anchor_stage": "EARRING_MODEL_NOT_LOADED"})
    assert not_loaded.failure_reason == EARRING_MODEL_NOT_LOADED

    hidden = _run(missing, diagnostics={"anchor_stage": "JEWELRY_MESH_HIDDEN"})
    assert hidden.failure_reason == EARRING_MODEL_NOT_LOADED

    no_anchor = _run(missing, diagnostics={"anchor_stage": "ATTACHMENT_ANCHOR_MISSING"})
    assert no_anchor.failure_reason == ATTACHMENT_ANCHOR_MISSING

    # With no diagnostic at all we must not claim a specific stage.
    assert _run(missing).failure_reason == TRACKING_LOST
    assert reason_for_missing_anchor(None) == TRACKING_LOST


def test_summary_reports_where_the_actual_coordinates_came_from():
    profile = debug_profile_for("earring")
    frames = [
        _run(_jewelry(0.247, 0.312, rotation=0.0, scale=1.0, source="scene_probe"), frame_number=0),
        _run(_jewelry(0.247, 0.312, rotation=0.0, scale=1.0, source="blob"), frame_number=1),
        _run(
            EarringAnchor(side="left", visible=False, source="missing"),
            frame_number=2,
            diagnostics={"anchor_stage": "EARRING_MODEL_NOT_LOADED"},
        ),
    ]
    summary = summarize_validation(frames, profile)
    assert summary["anchor_sources"] == {"scene_probe": 1, "blob": 1, "missing": 1}
    assert summary["anchor_stages"] == {"EARRING_MODEL_NOT_LOADED": 1}


def test_rotation_and_scale_are_separate_checks():
    rotated = _run(_jewelry(0.247, 0.312, rotation=40.0, scale=1.0))
    assert rotated.checks["position"].status == "PASS"
    assert rotated.failure_reason == ROTATION_OUT_OF_TOLERANCE

    oversized = _run(_jewelry(0.247, 0.312, rotation=0.0, scale=3.0))
    assert oversized.checks["rotation"].status == "PASS"
    assert oversized.failure_reason == SCALE_OUT_OF_RANGE


def test_missing_rotation_is_not_testable_not_pass():
    result = _run(_jewelry(0.247, 0.312))
    assert result.checks["rotation"].status == "NOT_TESTABLE"
    assert result.checks["scale"].status == "NOT_TESTABLE"


def test_one_good_frame_does_not_pass_the_video():
    profile = debug_profile_for("earring")
    frames = [_run(_jewelry(0.247, 0.312, rotation=0.0, scale=1.0), frame_number=0)]
    frames += [
        _run(EarringAnchor(side="left", visible=False, source="missing"), frame_number=index)
        for index in range(1, 10)
    ]
    summary = summarize_validation(frames, profile)
    assert summary["overall_status"] == "FAIL"
    assert summary["metrics"]["valid_frames"] == 1
    assert summary["metrics"]["tracking_failures"] == 9
    assert summary["metrics"]["max_consecutive_failures"] == 9


def test_summary_reports_ignored_frames_and_error_statistics():
    profile = debug_profile_for("earring")
    frames = [
        _run(_jewelry(0.247, 0.312, rotation=0.0, scale=1.0), frame_number=index) for index in range(5)
    ]
    summary = summarize_validation(frames, profile)
    assert summary["overall_status"] == "PASS"
    assert summary["failure_reason"] is None
    assert summary["metrics"]["ignored_frames"] == 0
    assert summary["metrics"]["valid_frame_percentage"] == 100.0
    assert math.isclose(summary["metrics"]["average_position_error_px"], 2.828, abs_tol=1e-3)
    assert math.isclose(summary["metrics"]["max_position_error_px"], 2.828, abs_tol=1e-3)


def test_temporal_drift_is_reported_when_frames_jump():
    profile = debug_profile_for("earring")
    frames = []
    for index in range(10):
        x = 0.247 if index % 2 == 0 else 0.9
        frames.append(_run(_jewelry(x, 0.312, rotation=0.0, scale=1.0), frame_number=index))
    summary = summarize_validation(frames, profile)
    assert summary["overall_status"] == "FAIL"
    assert summary["checks"]["temporal_stability"].get("status") == "FAIL"
    assert summary["metrics"]["position_jumps"] > 0
    assert summary["failure_reason"] in {NORMALIZED_DISTANCE_EXCEEDED, TEMPORAL_DRIFT}


def test_results_are_deterministic_for_identical_input():
    profile = debug_profile_for("earring")
    first = summarize_validation(
        [_run(_jewelry(0.251, 0.315, rotation=5.0, scale=1.1), frame_number=i) for i in range(4)], profile
    )
    second = summarize_validation(
        [_run(_jewelry(0.251, 0.315, rotation=5.0, scale=1.1), frame_number=i) for i in range(4)], profile
    )
    assert first == second


def test_tolerances_are_per_category_and_overridable():
    assert set(DEBUG_PROFILES) == {"earring", "necklace", "ring", "bracelet", "bangle"}
    assert (
        DEBUG_PROFILES["ring"].tolerances.position_tolerance_normalized
        != DEBUG_PROFILES["bracelet"].tolerances.position_tolerance_normalized
    )
    # The earring band matches the project's existing Euclidean warning band.
    assert DEBUG_PROFILES["earring"].tolerances.position_tolerance_normalized == EUCLIDEAN_WARNING

    overridden = debug_profile_for("ring", {"position_tolerance_px": 12.0, "show_face_mesh": False})
    assert overridden.tolerances.position_tolerance_px == 12.0
    assert overridden.display.show_face_mesh is False
    # Overrides must not leak into the shared profile table.
    assert DEBUG_PROFILES["ring"].tolerances.position_tolerance_px is None
    assert DEBUG_PROFILES["ring"].display.show_face_mesh is True

    nested = debug_profile_for("bracelet", {"tolerances": {"rotation_tolerance_deg": 40.0}})
    assert nested.tolerances.rotation_tolerance_deg == 40.0


def test_debug_renderer_draws_on_a_copy_and_leaves_geometry_untouched():
    import numpy as np

    from app.cv.debug_overlay import render_debug_frame

    profile = debug_profile_for("earring")
    expected = _expected()
    jewelry = _jewelry(0.247, 0.312, rotation=0.0, scale=1.0)
    validation = _run(jewelry, expected=expected)
    source = np.zeros((400, 400, 3), dtype=np.uint8)

    rendered = render_debug_frame(
        source,
        profile=profile,
        validation=validation,
        face=_face(),
        expected=expected,
        jewelry=jewelry,
        contour_indices=contour_indices("earring", "left"),
        selected_landmark_index=LOBE_LANDMARK["left"],
    )
    assert rendered is not source
    assert source.sum() == 0
    assert rendered.sum() > 0
    assert (expected.x, expected.y) == (_expected().x, _expected().y)
    assert (jewelry.x, jewelry.y) == (0.247, 0.312)


def test_hand_category_uses_hand_detection_for_landmark_check():
    profile = debug_profile_for("bracelet")
    hand = HandLandmarkResult(hand_detected=True, landmarks=[Landmark(x=0.4, y=0.6) for _ in range(21)], confidence=0.9)
    result = evaluate_frame(
        frame_number=0,
        timestamp_ms=0,
        side="left",
        profile=profile,
        face=None,
        hand=hand,
        expected=EarlobeAnchor(side="left", x=0.4, y=0.6, confidence=0.9, ear_width=0.08, ear_height=0.08),
        jewelry=_jewelry(0.4005, 0.6005, rotation=0.0, scale=1.0),
        frame_size=FRAME,
        landmark_index=selected_landmark_index("bracelet", "left"),
    )
    assert result.checks["landmark_detection"].status == "PASS"
    assert result.status == "PASS"

    without_hand = evaluate_frame(
        frame_number=1,
        timestamp_ms=100,
        side="left",
        profile=profile,
        face=_face(),
        hand=HandLandmarkResult(hand_detected=False),
        expected=None,
        jewelry=_jewelry(0.4, 0.6),
        frame_size=FRAME,
        landmark_index=selected_landmark_index("bracelet", "left"),
    )
    assert without_hand.failure_reason == REQUIRED_LANDMARK_NOT_DETECTED
