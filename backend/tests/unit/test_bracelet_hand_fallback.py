from app.adapters.tryon_application import PlaywrightTryOnAdapter
from app.cv.bracelet_lay import resolve_wrist_geometry
from app.cv.types import EarlobeAnchor, FaceLandmarkResult, HandLandmarkResult, Landmark
from app.services.live_jewelry_overlay import body_placements, hand_body_placements
from app.services.earlobe_detector import EarlobeDetector


def test_hand_body_placements_for_bracelet_use_wrist():
    landmarks = [Landmark(x=0.40, y=0.50) for _ in range(21)]
    landmarks[0] = Landmark(x=0.35, y=0.55)  # wrist
    landmarks[5] = Landmark(x=0.42, y=0.48)  # index MCP
    landmarks[17] = Landmark(x=0.30, y=0.50)  # pinky MCP
    hand = HandLandmarkResult(
        hand_detected=True,
        landmarks=landmarks,
        confidence=0.94,
        wrist_visible=True,
        fingers_visible=["index", "ring"],
    )
    placements = hand_body_placements(hand, "bracelet")
    assert len(placements) == 1
    assert abs(placements[0]["x"] - 0.35) < 0.02
    assert placements[0]["ear_width"] >= 0.12


def test_bracelet_resolve_prefers_mediapipe_hand():
    landmarks = [Landmark(x=0.40, y=0.50) for _ in range(21)]
    landmarks[0] = Landmark(x=0.33, y=0.60)
    landmarks[5] = Landmark(x=0.40, y=0.52)
    landmarks[9] = Landmark(x=0.38, y=0.50)
    landmarks[17] = Landmark(x=0.28, y=0.54)
    hand = HandLandmarkResult(
        hand_detected=True,
        landmarks=landmarks,
        confidence=0.95,
        wrist_visible=True,
        fingers_visible=["index"],
    )
    proxy = EarlobeAnchor(side="left", x=0.1, y=0.1, confidence=1.0, ear_width=0.08, ear_height=0.05)
    geometry = resolve_wrist_geometry(
        wrist_anchor=proxy,
        face=None,
        debug_state=None,
        side="left",
        style="chain",
        hand_landmarks=hand,
    )
    assert geometry is not None
    assert geometry.source == "hand_landmarks"
    assert abs(geometry.center_x - 0.33) < 0.02


def test_necklace_supports_qa_fallback():
    assert PlaywrightTryOnAdapter._supports_qa_jewelry_fallback("necklace") is True


def test_necklace_body_placements_use_neckline():
    face = FaceLandmarkResult(
        face_detected=True,
        confidence=0.95,
        landmarks=[Landmark(x=0.5, y=0.5) for _ in range(500)],
    )
    face.landmarks[152] = Landmark(x=0.5, y=0.72, confidence=0.9)
    face.landmarks[234] = Landmark(x=0.35, y=0.55)
    face.landmarks[454] = Landmark(x=0.65, y=0.55)
    placements = body_placements(face, "necklace", EarlobeDetector(0.01))
    assert len(placements) == 1
    assert placements[0]["side"] == "center"
    assert placements[0]["y"] > 0.72
