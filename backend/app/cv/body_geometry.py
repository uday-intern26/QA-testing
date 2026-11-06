"""Body attachment anchors for non-earring jewelry types."""

from __future__ import annotations

from app.cv.types import EarlobeAnchor, FaceLandmarkResult, Landmark

# MediaPipe Face Mesh indices used as placement anchors.
CHIN = 152
LEFT_CHEEK = 234
RIGHT_CHEEK = 454
NOSE = 1


def _point(landmarks: list[Landmark], index: int) -> Landmark | None:
    if index < 0 or index >= len(landmarks):
        return None
    return landmarks[index]


def neck_anchor(face: FaceLandmarkResult) -> EarlobeAnchor | None:
    """Base-of-neck anchor for necklace lay. Returned as EarlobeAnchor for shared placement math."""
    if not face.face_detected or not face.landmarks:
        return None
    chin = _point(face.landmarks, CHIN)
    left = _point(face.landmarks, LEFT_CHEEK)
    right = _point(face.landmarks, RIGHT_CHEEK)
    if chin is None:
        return None
    face_width = 0.08
    if left is not None and right is not None:
        face_width = max(0.04, abs(right.x - left.x))
    center_x = float(chin.x)
    if left is not None and right is not None:
        center_x = float((left.x + right.x) / 2.0)
    return EarlobeAnchor(
        side="center",
        x=center_x,
        y=float(min(0.98, chin.y + face_width * 0.32)),
        confidence=float(min(face.confidence or 0.9, chin.confidence or 0.9)),
        ear_width=float(face_width * 0.55),
        ear_height=float(face_width * 0.35),
    )


def wrist_anchor(face: FaceLandmarkResult, side: str = "center") -> EarlobeAnchor | None:
    """Bracelet/bangle proxy from face scale when hand landmarks are unavailable."""
    if not face.face_detected or not face.landmarks:
        return None
    chin = _point(face.landmarks, CHIN)
    left = _point(face.landmarks, LEFT_CHEEK)
    right = _point(face.landmarks, RIGHT_CHEEK)
    nose = _point(face.landmarks, NOSE)
    if chin is None or nose is None:
        return None
    face_width = 0.08
    if left is not None and right is not None:
        face_width = max(0.04, abs(right.x - left.x))
    x = float(chin.x)
    if side == "left":
        x = float(max(0.02, chin.x - face_width * 0.9))
    elif side == "right":
        x = float(min(0.98, chin.x + face_width * 0.9))
    return EarlobeAnchor(
        side=side,
        x=x,
        y=float(min(0.98, chin.y + face_width * 1.2)),
        confidence=float(min(face.confidence or 0.85, 0.85)),
        ear_width=float(face_width * 0.45),
        ear_height=float(face_width * 0.35),
    )


def finger_anchor(face: FaceLandmarkResult, side: str = "center") -> EarlobeAnchor | None:
    """Ring proxy zone near the lower face/hand area when hand landmarks are unavailable."""
    wrist = wrist_anchor(face, side=side)
    if wrist is None:
        return None
    return EarlobeAnchor(
        side=side,
        x=wrist.x,
        y=float(min(0.98, wrist.y + wrist.ear_width * 0.4)),
        confidence=wrist.confidence,
        ear_width=float(wrist.ear_width * 0.7),
        ear_height=float(wrist.ear_height * 0.7),
    )


def body_anchor_for(jewelry_type: str, face: FaceLandmarkResult | None, side: str) -> tuple[EarlobeAnchor | None, str | None]:
    if face is None or not face.face_detected:
        return None, f"Unable to detect the {jewelry_type} body anchor because the face was not found."
    if jewelry_type == "necklace":
        anchor = neck_anchor(face)
        return (anchor, None) if anchor else (None, "Unable to estimate the neck attachment point.")
    if jewelry_type in {"bracelet", "bangle"}:
        anchor = wrist_anchor(face, side=side if side in {"left", "right"} else "center")
        return (anchor, None) if anchor else (None, "Unable to estimate the wrist attachment point.")
    if jewelry_type == "ring":
        anchor = finger_anchor(face, side=side if side in {"left", "right"} else "center")
        return (anchor, None) if anchor else (None, "Unable to estimate the finger attachment point.")
    return None, f"Jewellery type '{jewelry_type}' has no body anchor."
