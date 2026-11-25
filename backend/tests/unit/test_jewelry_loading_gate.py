import asyncio

from app.adapters.tryon_application import PlaywrightTryOnAdapter
from app.cv.jewelry_profiles import profile_for
from app.cv.ring_lay import evaluate_ring_lay
from app.cv.types import EarlobeAnchor, EarringAnchor, FaceLandmarkResult
from app.services.frame_selector import FrameSelector


class _FakeBrowser:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)
        self.waits = 0

    async def evaluate(self, *_args, **_kwargs):
        if not self.statuses:
            return "ready"
        return self.statuses.pop(0)

    async def wait_for_timeout(self, _ms: int) -> None:
        self.waits += 1


def test_ring_profile_rejects_jewelry_not_loaded():
    assert "jewelry_not_loaded" in profile_for("ring").hard_reject_reasons


def test_frame_selector_marks_loading_debug_state():
    selector = FrameSelector(
        min_blur_variance=1.0,
        blur_norm_variance=100.0,
        duplicate_hash_distance=2,
        head_pose_max_delta_deg=30.0,
        head_pose_max_yaw_deg=90.0,
        min_ear_width=0.01,
        minimum_confidence=0.1,
        ear_side="left",
        jewelry_type="ring",
    )
    assert selector._jewelry_still_loading({"qa_status": "loading"}) is True
    assert selector._jewelry_still_loading({"qa_status": "ready"}) is False
    assert selector._jewelry_still_loading(None) is False


def test_weak_blob_does_not_count_as_placed_ring():
    finger = EarlobeAnchor(side="left", x=0.5, y=0.5, confidence=1.0, ear_width=0.08, ear_height=0.06)
    jewelry = EarringAnchor(
        side="left",
        x=0.51,
        y=0.49,
        confidence=0.72,
        visible=True,
        source="blob",
    )
    result = evaluate_ring_lay(
        FaceLandmarkResult(face_detected=False),
        finger,
        jewelry,
        config={
            "pass_threshold": 0.08,
            "fail_threshold": 0.15,
            "minimum_confidence": 0.8,
            "zone_y_scale": 1.0,
        },
        selected_finger="ring",
        side="left",
    )
    assert result["checks"]["ring_visibility"] == "FAIL"
    assert result["final_result"] == "FAIL"


def test_ring_lay_prefers_mediapipe_hand_over_proxy():
    from app.cv.ring_lay import resolve_finger_geometry
    from app.cv.types import HandLandmarkResult, Landmark

    # Synthetic hand: wrist at left, ring finger pointing down-right.
    landmarks = [Landmark(x=0.40, y=0.50) for _ in range(21)]
    landmarks[0] = Landmark(x=0.30, y=0.55)  # wrist
    landmarks[13] = Landmark(x=0.48, y=0.52)  # ring MCP
    landmarks[14] = Landmark(x=0.52, y=0.56)  # ring PIP
    landmarks[16] = Landmark(x=0.58, y=0.62)  # ring tip
    hand = HandLandmarkResult(
        hand_detected=True,
        landmarks=landmarks,
        confidence=0.95,
        wrist_visible=True,
        fingers_visible=["ring"],
    )
    # Deliberately wrong proxy so proxy-only geometry would disagree.
    proxy = EarlobeAnchor(side="left", x=0.10, y=0.10, confidence=1.0, ear_width=0.08, ear_height=0.06)
    geometry = resolve_finger_geometry(
        selected_finger="ring",
        finger_anchor=proxy,
        face=None,
        debug_state=None,
        side="left",
        hand_landmarks=hand,
    )
    assert geometry is not None
    assert geometry.source == "hand_landmarks"
    assert abs(geometry.base_x - 0.48) < 0.01
    assert abs(geometry.tip_x - 0.58) < 0.01


def test_wait_for_jewelry_ready_requires_loading_to_clear():
    adapter = object.__new__(PlaywrightTryOnAdapter)
    browser = _FakeBrowser(["loading", "loading", "ready", "ready"])
    adapter.browser = browser

    async def _leave():
        return None

    adapter._leave_photo_matching = _leave  # type: ignore[method-assign]
    ready = asyncio.run(adapter._wait_for_jewelry_ready(timeout_ms=5000))
    assert ready is True
    assert browser.waits >= 1


def test_wait_for_jewelry_ready_times_out_while_loading():
    adapter = object.__new__(PlaywrightTryOnAdapter)
    browser = _FakeBrowser(["loading"] * 20)
    adapter.browser = browser
    adapter._leave_photo_matching = lambda: asyncio.sleep(0)  # type: ignore[method-assign]
    ready = asyncio.run(adapter._wait_for_jewelry_ready(timeout_ms=1000))
    assert ready is False
