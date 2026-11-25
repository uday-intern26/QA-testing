from app.cv.jewelry_profiles import profile_for
from app.cv.types import FaceLandmarkResult, FrameQuality, HandLandmarkResult, Landmark
from app.services.frame_selector import FrameSelector, RawFrame, SelectedFrame


def _selector(jewelry_type: str, ear_side: str = "left") -> FrameSelector:
    return FrameSelector(
        min_blur_variance=1.0,
        blur_norm_variance=100.0,
        duplicate_hash_distance=2,
        head_pose_max_delta_deg=30.0,
        head_pose_max_yaw_deg=90.0,
        min_ear_width=0.01,
        minimum_confidence=0.1,
        ear_side=ear_side,
        jewelry_type=jewelry_type,
    )


def _frame(index: int, quality: FrameQuality) -> SelectedFrame:
    return SelectedFrame(
        raw=RawFrame(index=index, timestamp_ms=index * 100, path=__file__),  # path unused by select()
        quality=quality,
        face=FaceLandmarkResult(face_detected="face" in quality.detected_body_parts),
        hand=HandLandmarkResult(
            hand_detected="hand" in quality.detected_body_parts,
            wrist_visible=quality.wrist_visible,
            fingers_visible=["ring"] if quality.fingers_visible else [],
        ),
    )


def _quality(**kwargs) -> FrameQuality:
    base = dict(
        face_detected=False,
        left_ear_visible=False,
        right_ear_visible=False,
        blur_score=0.8,
        landmark_confidence=0.9,
        head_pose_stable=True,
        rejection_reasons=[],
        jewelry_category="earring",
        required_body_parts=[],
        detected_body_parts=[],
        body_confidence=0.9,
        hand_detected=False,
        neck_visible=False,
        wrist_visible=False,
        fingers_visible=False,
        quality_score=1.0,
        selection_status="pending",
    )
    base.update(kwargs)
    return FrameQuality(**base)


def test_profiles_define_distinct_body_parts():
    assert "ear" in profile_for("earring").required_body_parts
    assert "neck" in profile_for("necklace").required_body_parts
    assert "fingers" in profile_for("ring").required_body_parts
    assert "wrist" in profile_for("bracelet").required_body_parts
    assert "wrist" in profile_for("bangle").required_body_parts


def test_earring_rejects_face_without_ear():
    selector = _selector("earring", ear_side="left")
    frames = [
        _frame(
            0,
            _quality(
                jewelry_category="earring",
                face_detected=True,
                detected_body_parts=["face"],
                rejection_reasons=["ear_not_visible"],
                required_body_parts=["face", "ear", "earlobe"],
            ),
        ),
        _frame(
            1,
            _quality(
                jewelry_category="earring",
                face_detected=True,
                left_ear_visible=True,
                detected_body_parts=["face", "ear", "earlobe"],
                required_body_parts=["face", "ear", "earlobe"],
            ),
        ),
    ]
    selected = selector.select(frames, max_frames=5)
    assert [item.raw.index for item in selected] == [1]


def test_ring_rejects_frames_without_hand():
    selector = _selector("ring")
    frames = [
        _frame(
            0,
            _quality(
                jewelry_category="ring",
                face_detected=True,
                detected_body_parts=["face"],
                rejection_reasons=["hand_not_detected", "fingers_not_visible"],
                required_body_parts=["hand", "fingers"],
            ),
        ),
        _frame(
            1,
            _quality(
                jewelry_category="ring",
                hand_detected=True,
                fingers_visible=True,
                detected_body_parts=["hand", "fingers"],
                required_body_parts=["hand", "fingers"],
                rejection_reasons=["face_not_detected"],  # soft for ring
            ),
        ),
    ]
    selected = selector.select(frames, max_frames=5)
    assert [item.raw.index for item in selected] == [1]


def test_necklace_rejects_without_neck():
    selector = _selector("necklace")
    frames = [
        _frame(
            0,
            _quality(
                jewelry_category="necklace",
                face_detected=True,
                detected_body_parts=["face"],
                rejection_reasons=["neck_not_visible"],
                required_body_parts=["face", "neck", "upper_chest"],
            ),
        ),
        _frame(
            1,
            _quality(
                jewelry_category="necklace",
                face_detected=True,
                neck_visible=True,
                detected_body_parts=["face", "neck", "upper_chest"],
                required_body_parts=["face", "neck", "upper_chest"],
            ),
        ),
    ]
    selected = selector.select(frames, max_frames=5)
    assert [item.raw.index for item in selected] == [1]


def test_bracelet_requires_wrist():
    selector = _selector("bracelet")
    frames = [
        _frame(
            0,
            _quality(
                jewelry_category="bracelet",
                hand_detected=True,
                detected_body_parts=["hand"],
                rejection_reasons=["wrist_not_visible"],
                required_body_parts=["hand", "wrist"],
            ),
        ),
        _frame(
            1,
            _quality(
                jewelry_category="bracelet",
                hand_detected=True,
                wrist_visible=True,
                detected_body_parts=["hand", "wrist"],
                required_body_parts=["hand", "wrist"],
            ),
        ),
    ]
    selected = selector.select(frames, max_frames=5)
    assert [item.raw.index for item in selected] == [1]


def test_bangle_same_body_rules_as_bracelet():
    selector = _selector("bangle")
    frames = [
        _frame(
            0,
            _quality(
                jewelry_category="bangle",
                hand_detected=True,
                detected_body_parts=["hand"],
                rejection_reasons=["wrist_not_visible"],
                required_body_parts=["hand", "wrist"],
            ),
        ),
        _frame(
            1,
            _quality(
                jewelry_category="bangle",
                hand_detected=True,
                wrist_visible=True,
                detected_body_parts=["hand", "wrist"],
                required_body_parts=["hand", "wrist"],
            ),
        ),
    ]
    selected = selector.select(frames, max_frames=5)
    assert [item.raw.index for item in selected] == [1]


def test_ring_does_not_fail_for_missing_face_alone():
    selector = _selector("ring")
    frames = [
        _frame(
            0,
            _quality(
                jewelry_category="ring",
                hand_detected=True,
                fingers_visible=True,
                detected_body_parts=["hand", "fingers"],
                required_body_parts=["hand", "fingers"],
                rejection_reasons=["face_not_detected", "ear_not_visible"],
            ),
        ),
    ]
    selected = selector.select(frames, max_frames=5)
    assert len(selected) == 1
    assert selected[0].quality.selection_status == "selected"
