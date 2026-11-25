"""MediaPipe Hand Landmarker wrapper for ring / bracelet / bangle body detection."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.cv.types import HandLandmarkResult, Landmark

# MediaPipe hand landmark indices.
WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_MCP = 13
RING_TIP = 16
PINKY_MCP = 17
PINKY_TIP = 20

FINGER_LANDMARKS: dict[str, tuple[int, ...]] = {
    "thumb": (1, 2, 3, 4),
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "little": (17, 18, 19, 20),
}


class HandLandmarkError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.recommended_action = (
            "Download the hand landmarker model with backend/scripts/download_model.py, "
            "or set HAND_MODEL_PATH to an existing hand_landmarker.task file."
        )


def _landmark_confidence(raw) -> float:
    presence = float(getattr(raw, "presence", 0.0) or 0.0)
    visibility = float(getattr(raw, "visibility", 0.0) or 0.0)
    if presence > 0:
        return presence
    if visibility > 0:
        return visibility
    x = float(raw.x)
    y = float(raw.y)
    if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
        return 1.0
    return 0.0


def _in_frame(landmark: Landmark, margin: float = 0.02) -> bool:
    return margin <= landmark.x <= 1.0 - margin and margin <= landmark.y <= 1.0 - margin


class MediaPipeHandLandmarker:
    def __init__(self, model_path: Path, *, max_hands: int = 2) -> None:
        self.model_path = Path(model_path)
        self.max_hands = max_hands
        self._landmarker = None

    def _load(self):
        if self._landmarker is not None:
            return self._landmarker
        if not self.model_path.is_file():
            raise HandLandmarkError(
                "Hand landmarker model is missing at "
                f"{self.model_path}. Run backend/scripts/download_model.py."
            )
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions
        except ImportError as exc:
            raise HandLandmarkError("MediaPipe is not installed.") from exc

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(self.model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_hands=self.max_hands,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        return self._landmarker

    def detect(self, image_rgb: np.ndarray) -> HandLandmarkResult:
        landmarker = self._load()
        import mediapipe as mp

        if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
            raise HandLandmarkError("Hand landmarker expects an RGB image.")
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(image_rgb))
        result = landmarker.detect(mp_image)
        hands = getattr(result, "hand_landmarks", None) or []
        handedness_list = getattr(result, "handedness", None) or []
        if not hands:
            return HandLandmarkResult(hand_detected=False, reason="hand_not_detected")

        # Prefer the largest / most confident hand in frame.
        best_idx = 0
        best_score = -1.0
        parsed: list[tuple[list[Landmark], str, float]] = []
        for index, raw_hand in enumerate(hands):
            landmarks = [
                Landmark(x=float(item.x), y=float(item.y), z=float(item.z), confidence=_landmark_confidence(item))
                for item in raw_hand
            ]
            label = "unknown"
            score = 0.5
            if index < len(handedness_list) and handedness_list[index]:
                category = handedness_list[index][0]
                label = str(getattr(category, "category_name", "unknown")).lower()
                score = float(getattr(category, "score", 0.5) or 0.5)
            # MediaPipe "Left" means the person's left hand as seen by them;
            # for mirrored webcams this often maps to the right side of the image.
            mean_conf = sum(item.confidence for item in landmarks) / max(len(landmarks), 1)
            spread = 0.0
            if landmarks:
                xs = [item.x for item in landmarks]
                ys = [item.y for item in landmarks]
                spread = max(xs) - min(xs) + max(ys) - min(ys)
            ranking = mean_conf + score + spread
            parsed.append((landmarks, label, mean_conf))
            if ranking > best_score:
                best_score = ranking
                best_idx = index

        landmarks, handedness, confidence = parsed[best_idx]
        wrist = landmarks[WRIST] if len(landmarks) > WRIST else None
        wrist_visible = bool(wrist and _in_frame(wrist))
        visible_fingers: list[str] = []
        for finger, indices in FINGER_LANDMARKS.items():
            tips_ok = True
            for idx in indices:
                if idx >= len(landmarks) or not _in_frame(landmarks[idx], margin=0.0):
                    tips_ok = False
                    break
            if tips_ok:
                visible_fingers.append(finger)

        return HandLandmarkResult(
            hand_detected=True,
            landmarks=landmarks,
            confidence=float(confidence),
            handedness=handedness,
            wrist_visible=wrist_visible,
            fingers_visible=visible_fingers,
            reason=None,
        )

    def close(self) -> None:
        if self._landmarker is not None:
            close = getattr(self._landmarker, "close", None)
            if close:
                close()
            self._landmarker = None
