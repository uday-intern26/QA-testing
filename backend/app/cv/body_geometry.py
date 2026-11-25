"""Body attachment anchors for each jewelry category."""

from __future__ import annotations

from app.cv.hand_landmarks import (
    INDEX_MCP,
    INDEX_TIP,
    MIDDLE_MCP,
    MIDDLE_TIP,
    PINKY_MCP,
    PINKY_TIP,
    RING_MCP,
    RING_TIP,
    THUMB_TIP,
    WRIST,
)
from app.cv.types import EarlobeAnchor, FaceLandmarkResult, HandLandmarkResult, Landmark

# MediaPipe Face Mesh indices used as placement anchors.
CHIN = 152
LEFT_CHEEK = 234
RIGHT_CHEEK = 454
NOSE = 1

FINGER_KEYPOINTS: dict[str, tuple[int, int]] = {
    "thumb": (2, THUMB_TIP),
    "index": (INDEX_MCP, INDEX_TIP),
    "middle": (MIDDLE_MCP, MIDDLE_TIP),
    "ring": (RING_MCP, RING_TIP),
    "little": (PINKY_MCP, PINKY_TIP),
}


def _point(landmarks: list[Landmark], index: int) -> Landmark | None:
    if index < 0 or index >= len(landmarks):
        return None
    return landmarks[index]


def neck_anchor(face: FaceLandmarkResult) -> EarlobeAnchor | None:
    """Base-of-neck anchor for necklace lay."""
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
    from app.cv.necklace_lay import trace_necklace_neckline

    yaw = float(face.head_pose.yaw) if face.head_pose is not None else 0.0
    center_x, neckline_y, neck_width, _shoulder_width, _shoulder_line_y = trace_necklace_neckline(
        center_x, float(chin.y), face_width, yaw
    )
    return EarlobeAnchor(
        side="center",
        x=center_x,
        y=neckline_y,
        confidence=float(min(face.confidence or 0.9, chin.confidence or 0.9)),
        ear_width=float(neck_width),
        ear_height=float(neck_width * 0.56),
    )


def wrist_anchor_from_hand(hand: HandLandmarkResult, side: str = "center") -> EarlobeAnchor | None:
    if not hand.hand_detected or not hand.landmarks:
        return None
    wrist = _point(hand.landmarks, WRIST)
    if wrist is None:
        return None
    # Approximate wrist width from MCP spread.
    index_mcp = _point(hand.landmarks, INDEX_MCP)
    pinky_mcp = _point(hand.landmarks, PINKY_MCP)
    width = 0.08
    if index_mcp is not None and pinky_mcp is not None:
        width = max(0.04, abs(pinky_mcp.x - index_mcp.x) * 1.1)
    resolved_side = side
    if side == "center":
        resolved_side = "left" if hand.handedness == "left" else "right" if hand.handedness == "right" else "center"
    return EarlobeAnchor(
        side=resolved_side,
        x=float(wrist.x),
        y=float(wrist.y),
        confidence=float(min(hand.confidence or 0.85, wrist.confidence or 0.85)),
        ear_width=float(width),
        ear_height=float(width * 0.7),
    )


def finger_anchor_from_hand(
    hand: HandLandmarkResult,
    *,
    side: str = "center",
    selected_finger: str = "ring",
) -> EarlobeAnchor | None:
    if not hand.hand_detected or not hand.landmarks:
        return None
    finger = (selected_finger or "ring").lower()
    if finger not in FINGER_KEYPOINTS:
        finger = "ring"
    mcp_idx, tip_idx = FINGER_KEYPOINTS[finger]
    mcp = _point(hand.landmarks, mcp_idx)
    tip = _point(hand.landmarks, tip_idx)
    if mcp is None or tip is None:
        # Fall back to wrist-relative ring zone if the chosen finger is incomplete.
        return wrist_anchor_from_hand(hand, side=side)
    # Ring seat sits near the base of the finger (closer to MCP than tip).
    x = float(mcp.x * 0.65 + tip.x * 0.35)
    y = float(mcp.y * 0.65 + tip.y * 0.35)
    width = max(0.03, abs(tip.x - mcp.x) * 0.9 + abs(tip.y - mcp.y) * 0.35)
    resolved_side = side
    if side == "center":
        resolved_side = "left" if hand.handedness == "left" else "right" if hand.handedness == "right" else "center"
    return EarlobeAnchor(
        side=resolved_side,
        x=x,
        y=y,
        confidence=float(min(hand.confidence or 0.85, mcp.confidence or 0.85, tip.confidence or 0.85)),
        ear_width=float(width),
        ear_height=float(width * 0.75),
    )


def wrist_anchor(face: FaceLandmarkResult, side: str = "center") -> EarlobeAnchor | None:
    """Legacy face-proxy wrist when hand landmarks are unavailable."""
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
    """Legacy face-proxy finger when hand landmarks are unavailable."""
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


def body_anchor_for(
    jewelry_type: str,
    face: FaceLandmarkResult | None,
    side: str,
    *,
    hand: HandLandmarkResult | None = None,
    selected_finger: str = "ring",
) -> tuple[EarlobeAnchor | None, str | None]:
    jewelry_type = (jewelry_type or "earring").lower()
    if jewelry_type == "necklace":
        if face is None or not face.face_detected:
            return None, "Unable to detect the necklace body anchor because the face/neck was not found."
        anchor = neck_anchor(face)
        return (anchor, None) if anchor else (None, "Unable to estimate the neck attachment point.")

    if jewelry_type in {"bracelet", "bangle"}:
        if hand is not None and hand.hand_detected:
            anchor = wrist_anchor_from_hand(hand, side=side if side in {"left", "right", "center"} else "center")
            if anchor is not None:
                return anchor, None
            return None, "Unable to estimate the wrist attachment point from the hand landmarks."
        if face is not None and face.face_detected:
            anchor = wrist_anchor(face, side=side if side in {"left", "right"} else "center")
            return (anchor, None) if anchor else (None, "Unable to estimate the wrist attachment point.")
        return None, "Unable to detect the wrist because neither hand nor face landmarks were found."

    if jewelry_type == "ring":
        if hand is not None and hand.hand_detected:
            anchor = finger_anchor_from_hand(
                hand,
                side=side if side in {"left", "right", "center"} else "center",
                selected_finger=selected_finger,
            )
            if anchor is not None:
                return anchor, None
            return None, "Unable to estimate the finger attachment point from the hand landmarks."
        if face is not None and face.face_detected:
            anchor = finger_anchor(face, side=side if side in {"left", "right"} else "center")
            return (anchor, None) if anchor else (None, "Unable to estimate the finger attachment point.")
        return None, "Unable to detect the finger because neither hand nor face landmarks were found."

    return None, f"Jewellery type '{jewelry_type}' has no body anchor."
