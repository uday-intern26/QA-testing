"""Layer 1. Extract frames and keep a representative, quality-filtered set."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.cv.ear_geometry import EarlobeAnchorEstimator
from app.cv.image_processing import average_hash, blur_score, blur_variance, hamming, read_bgr
from app.cv.types import FaceLandmarkResult, FrameQuality, HeadPose


@dataclass
class RawFrame:
    index: int
    timestamp_ms: int
    path: Path
    debug_state: dict | None = None


@dataclass
class SelectedFrame:
    raw: RawFrame
    quality: FrameQuality
    face: FaceLandmarkResult | None = None
    image_bgr: np.ndarray | None = field(default=None, repr=False)


class FrameSelector:
    def __init__(
        self,
        *,
        min_blur_variance: float,
        blur_norm_variance: float,
        duplicate_hash_distance: int,
        head_pose_max_delta_deg: float,
        head_pose_max_yaw_deg: float,
        min_ear_width: float,
        minimum_confidence: float,
        ear_side: str,
        require_ear_visibility: bool = True,
    ) -> None:
        self.min_blur_variance = min_blur_variance
        self.blur_norm_variance = blur_norm_variance
        self.duplicate_hash_distance = duplicate_hash_distance
        self.head_pose_max_delta_deg = head_pose_max_delta_deg
        self.head_pose_max_yaw_deg = head_pose_max_yaw_deg
        self.min_ear_width = min_ear_width
        self.minimum_confidence = minimum_confidence
        self.ear_side = ear_side
        self.require_ear_visibility = require_ear_visibility
        self._ears = EarlobeAnchorEstimator()

    def extract_video(self, video_path: Path, target_fps: int, output_dir: Path) -> list[RawFrame]:
        output_dir.mkdir(parents=True, exist_ok=True)
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError(f"Corrupted or unreadable video: {video_path.name}")
        native_fps = capture.get(cv2.CAP_PROP_FPS) or float(target_fps)
        if native_fps <= 0:
            native_fps = float(target_fps)
        step = max(1, int(round(native_fps / target_fps)))
        frames: list[RawFrame] = []
        index = 0
        kept = 0
        while True:
            ok, image = capture.read()
            if not ok:
                break
            if index % step == 0:
                timestamp_ms = int(round((index / native_fps) * 1000))
                path = output_dir / f"frame_{kept:04d}.png"
                if not cv2.imwrite(str(path), image):
                    capture.release()
                    raise ValueError(f"Unable to write extracted frame {path.name}")
                frames.append(RawFrame(index=kept, timestamp_ms=timestamp_ms, path=path))
                kept += 1
            index += 1
        capture.release()
        if not frames:
            raise ValueError("The video did not contain any readable frames.")
        return frames

    def evaluate(self, raw_frames: list[RawFrame], faces: list[FaceLandmarkResult]) -> list[SelectedFrame]:
        if len(raw_frames) != len(faces):
            raise ValueError("Face results must align with extracted frames.")
        evaluated: list[SelectedFrame] = []
        previous_pose: HeadPose | None = None
        previous_hash = None
        for raw, face in zip(raw_frames, faces):
            image = read_bgr(raw.path)
            quality = self._quality(image, face, previous_pose, previous_hash)
            frame_hash = average_hash(image)
            if previous_hash is not None and hamming(frame_hash, previous_hash) <= self.duplicate_hash_distance:
                quality.rejection_reasons.append("near_duplicate")
            previous_hash = frame_hash
            if face.head_pose is not None:
                previous_pose = face.head_pose
            evaluated.append(SelectedFrame(raw=raw, quality=quality, face=face, image_bgr=image))
        return evaluated

    def select(self, evaluated: list[SelectedFrame], max_frames: int) -> list[SelectedFrame]:
        accepted = [frame for frame in evaluated if not frame.quality.rejection_reasons]
        accepted.sort(key=lambda frame: frame.raw.timestamp_ms)
        if len(accepted) <= max_frames:
            return accepted
        if max_frames <= 1:
            return [max(accepted, key=self._score)]
        chosen: list[SelectedFrame] = []
        last = len(accepted) - 1
        for slot in range(max_frames):
            position = round(slot * last / (max_frames - 1))
            candidate = accepted[position]
            if not candidate.quality.head_pose_stable:
                window = accepted[max(0, position - 2) : position + 3]
                stable = [item for item in window if item.quality.head_pose_stable]
                if stable:
                    candidate = max(stable, key=self._score)
            chosen.append(candidate)
        unique: dict[int, SelectedFrame] = {}
        for frame in chosen:
            unique[frame.raw.index] = frame
        return [unique[key] for key in sorted(unique)]

    def _score(self, frame: SelectedFrame) -> float:
        quality = frame.quality
        return (
            quality.blur_score
            + quality.landmark_confidence
            + (0.4 if quality.head_pose_stable else 0.0)
        )

    def _quality(
        self,
        image: np.ndarray,
        face: FaceLandmarkResult,
        previous_pose: HeadPose | None,
        previous_hash,
    ) -> FrameQuality:
        del previous_hash
        variance = blur_variance(image)
        score = blur_score(image, self.blur_norm_variance)
        reasons: list[str] = []
        left_visible = False
        right_visible = False
        pose_stable = True
        occluded = False
        confidence = face.confidence

        if not face.face_detected or not face.landmarks:
            reasons.append("face_not_detected")
        else:
            outside = sum(
                1
                for landmark in face.landmarks
                if landmark.x < 0 or landmark.x > 1 or landmark.y < 0 or landmark.y > 1
            )
            if outside / max(len(face.landmarks), 1) > 0.15:
                occluded = True
                reasons.append("face_occluded")
            left_visible = self._ears.visibility(face.landmarks, "left", self.min_ear_width)
            right_visible = self._ears.visibility(face.landmarks, "right", self.min_ear_width)
            required = self._required_sides() if self.require_ear_visibility else []
            if required and (
                any(side == "left" and not left_visible for side in required)
                or any(side == "right" and not right_visible for side in required)
            ):
                reasons.append("ear_not_visible")
            confidences = []
            for side in required:
                if (side == "left" and left_visible) or (side == "right" and right_visible):
                    try:
                        anchor = self._ears.estimate(face.landmarks, side, min_ear_width=self.min_ear_width)
                        confidences.append(anchor.confidence)
                    except Exception:
                        confidences.append(0.0)
            if confidences:
                confidence = min(confidences)
            elif not self.require_ear_visibility:
                confidence = float(face.confidence or 0.0)
            if confidence < self.minimum_confidence:
                reasons.append("low_landmark_confidence")

        if variance < self.min_blur_variance:
            reasons.append("excessive_blur")

        pose = face.head_pose
        if pose is not None:
            if abs(pose.yaw) > self.head_pose_max_yaw_deg:
                pose_stable = False
                reasons.append("head_pose_unstable")
            if previous_pose is not None:
                delta = max(
                    abs(pose.yaw - previous_pose.yaw),
                    abs(pose.pitch - previous_pose.pitch),
                    abs(pose.roll - previous_pose.roll),
                )
                if delta > self.head_pose_max_delta_deg:
                    pose_stable = False
                    if "head_pose_unstable" not in reasons:
                        reasons.append("head_pose_unstable")

        # Preserve order while dropping duplicates.
        unique_reasons: list[str] = []
        for reason in reasons:
            if reason not in unique_reasons:
                unique_reasons.append(reason)

        return FrameQuality(
            face_detected=face.face_detected,
            left_ear_visible=left_visible,
            right_ear_visible=right_visible,
            blur_score=score,
            landmark_confidence=confidence,
            head_pose_stable=pose_stable,
            occluded=occluded,
            rejection_reasons=unique_reasons,
        )

    def _required_sides(self) -> list[str]:
        if self.ear_side == "both":
            return ["left", "right"]
        return [self.ear_side]
