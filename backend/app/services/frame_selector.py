"""Layer 1. Extract frames and keep a category-specific quality-filtered set."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.cv.ear_geometry import EarlobeAnchorEstimator
from app.cv.image_processing import average_hash, blur_score, blur_variance, hamming, read_bgr
from app.cv.jewelry_profiles import JewelryCategoryProfile, profile_for
from app.cv.types import FaceLandmarkResult, FrameQuality, HandLandmarkResult, HeadPose, Landmark


# Which pipeline stage each rejection reason comes from. Reported verbatim so a
# frame skipped by duplicate filtering is not mistaken for a placement failure.
REJECTION_SOURCES: dict[str, str] = {
    "face_not_detected": "body_detection",
    "face_occluded": "body_detection",
    "ear_not_visible": "body_detection",
    "neck_not_visible": "body_detection",
    "hand_not_detected": "body_detection",
    "wrist_not_visible": "body_detection",
    "fingers_not_visible": "body_detection",
    "low_landmark_confidence": "body_detection",
    "jewelry_not_loaded": "jewelry_detection",
    "near_duplicate": "duplicate_filter",
    "not_selected_as_representative": "candidate_selection",
    "excessive_blur": "frame_quality",
    "head_pose_unstable": "frame_quality",
}


def rejection_source(reason: str) -> str:
    return REJECTION_SOURCES.get(reason, "frame_quality")


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
    hand: HandLandmarkResult | None = None
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
        jewelry_type: str = "earring",
        require_ear_visibility: bool | None = None,
        require_face: bool | None = None,
    ) -> None:
        self.profile: JewelryCategoryProfile = profile_for(jewelry_type)
        self.min_blur_variance = min_blur_variance
        self.blur_norm_variance = blur_norm_variance
        self.duplicate_hash_distance = duplicate_hash_distance
        self.head_pose_max_delta_deg = head_pose_max_delta_deg
        self.head_pose_max_yaw_deg = head_pose_max_yaw_deg
        self.min_ear_width = min_ear_width
        self.minimum_confidence = minimum_confidence
        self.ear_side = ear_side
        # Allow explicit overrides while defaulting to the category profile.
        self.require_ear_visibility = (
            self.profile.requires_ears if require_ear_visibility is None else require_ear_visibility
        )
        self.require_face = self.profile.requires_face if require_face is None else require_face
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

    def evaluate(
        self,
        raw_frames: list[RawFrame],
        faces: list[FaceLandmarkResult],
        hands: list[HandLandmarkResult] | None = None,
    ) -> list[SelectedFrame]:
        if len(raw_frames) != len(faces):
            raise ValueError("Face results must align with extracted frames.")
        if hands is not None and len(hands) != len(raw_frames):
            raise ValueError("Hand results must align with extracted frames.")
        evaluated: list[SelectedFrame] = []
        previous_pose: HeadPose | None = None
        previous_hash = None
        empty_hand = HandLandmarkResult(hand_detected=False, reason="hand_not_detected")
        for index, (raw, face) in enumerate(zip(raw_frames, faces)):
            hand = hands[index] if hands is not None else empty_hand
            image = read_bgr(raw.path)
            quality = self._quality(image, face, hand, previous_pose, debug_state=raw.debug_state)
            frame_hash = average_hash(image)
            if previous_hash is not None and hamming(frame_hash, previous_hash) <= self.duplicate_hash_distance:
                if "near_duplicate" not in quality.rejection_reasons:
                    quality.rejection_reasons.append("near_duplicate")
            previous_hash = frame_hash
            if face.head_pose is not None:
                previous_pose = face.head_pose
            quality.rejection_sources = {
                reason: rejection_source(reason) for reason in quality.rejection_reasons
            }
            quality.quality_score = self._score_from_quality(quality)
            evaluated.append(SelectedFrame(raw=raw, quality=quality, face=face, hand=hand, image_bgr=image))
        return evaluated

    def select(self, evaluated: list[SelectedFrame], max_frames: int) -> list[SelectedFrame]:
        soft = self.profile.soft_reject_reasons
        hard = self.profile.hard_reject_reasons

        def hard_rejected(frame: SelectedFrame) -> bool:
            reasons = set(frame.quality.rejection_reasons)
            # Category hard reasons always reject.
            if reasons & hard:
                return True
            # Any non-soft reason also rejects.
            return any(reason not in soft for reason in reasons)

        accepted = [frame for frame in evaluated if not hard_rejected(frame)]
        if len(accepted) < max(1, min(5, max_frames)):
            # Fallback: keep frames that still have the required body region for this category.
            body_ok = [frame for frame in evaluated if self._has_required_body(frame.quality)]
            if body_ok:
                accepted = [frame for frame in body_ok if "excessive_blur" not in frame.quality.rejection_reasons] or body_ok

        accepted.sort(key=lambda frame: frame.raw.timestamp_ms)
        if not accepted:
            for frame in evaluated:
                frame.quality.selection_status = "rejected"
            return []

        if len(accepted) <= max_frames:
            chosen = accepted
        elif max_frames <= 1:
            chosen = [max(accepted, key=self._score)]
        else:
            # Prefer frames whose body tracing points are visible, then keep the
            # requested count spread across the clip.
            traced = [frame for frame in accepted if self._has_required_body(frame.quality)]
            if len(traced) >= max_frames:
                accepted = traced
            chosen = []
            last = len(accepted) - 1
            for slot in range(max_frames):
                position = round(slot * last / (max_frames - 1))
                candidate = accepted[position]
                if not candidate.quality.head_pose_stable and self.profile.requires_face:
                    window = accepted[max(0, position - 2) : position + 3]
                    stable = [item for item in window if item.quality.head_pose_stable]
                    if stable:
                        candidate = max(stable, key=self._score)
                chosen.append(candidate)
            unique: dict[int, SelectedFrame] = {}
            for frame in chosen:
                unique[frame.raw.index] = frame
            chosen = [unique[key] for key in sorted(unique)]

        selected_ids = {frame.raw.index for frame in chosen}
        for frame in evaluated:
            frame.quality.selection_status = "selected" if frame.raw.index in selected_ids else "rejected"
            if frame.raw.index not in selected_ids and not frame.quality.rejection_reasons:
                frame.quality.rejection_reasons.append("not_selected_as_representative")
            frame.quality.rejection_sources = {
                reason: rejection_source(reason) for reason in frame.quality.rejection_reasons
            }
        return chosen

    def _score(self, frame: SelectedFrame) -> float:
        return self._score_from_quality(frame.quality)

    def _score_from_quality(self, quality: FrameQuality) -> float:
        soft = self.profile.soft_reject_reasons
        soft_penalty = 0.15 * sum(1 for reason in quality.rejection_reasons if reason in soft)
        body_bonus = 0.5 * float(quality.body_confidence or 0.0)
        return (
            quality.blur_score
            + quality.landmark_confidence
            + body_bonus
            + (0.4 if quality.head_pose_stable else 0.0)
            - soft_penalty
        )

    def _has_required_body(self, quality: FrameQuality) -> bool:
        detected = set(quality.detected_body_parts or [])
        required = set(self.profile.required_body_parts)
        # Earlobe implies ear for earring; upper_chest implies neck for necklace.
        if "earlobe" in required and "ear" in detected:
            detected.add("earlobe")
        if "upper_chest" in required and "neck" in detected:
            detected.add("upper_chest")
        return required.issubset(detected)

    def _quality(
        self,
        image: np.ndarray,
        face: FaceLandmarkResult,
        hand: HandLandmarkResult,
        previous_pose: HeadPose | None,
        debug_state: dict | None = None,
    ) -> FrameQuality:
        variance = blur_variance(image)
        score = blur_score(image, self.blur_norm_variance)
        reasons: list[str] = []
        left_visible = False
        right_visible = False
        neck_visible = False
        pose_stable = True
        occluded = False
        confidence = float(face.confidence or 0.0)
        detected_parts: list[str] = []
        body_confidence = 0.0

        profile = self.profile
        if self._jewelry_still_loading(debug_state) and profile.jewelry_type in {
            "ring",
            "bracelet",
            "bangle",
        }:
            reasons.append("jewelry_not_loaded")

        if face.face_detected and face.landmarks:
            detected_parts.append("face")
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
            if left_visible or right_visible:
                detected_parts.append("ear")
            if left_visible and (self.ear_side in {"left", "both"}):
                detected_parts.append("earlobe")
            if right_visible and (self.ear_side in {"right", "both"}):
                if "earlobe" not in detected_parts:
                    detected_parts.append("earlobe")
            neck_visible = self._neck_visible(face.landmarks)
            if neck_visible:
                detected_parts.extend(["neck", "upper_chest"])
            confidences: list[float] = []
            if self.require_ear_visibility:
                for side in self._required_sides():
                    if (side == "left" and left_visible) or (side == "right" and right_visible):
                        try:
                            anchor = self._ears.estimate(face.landmarks, side, min_ear_width=self.min_ear_width)
                            confidences.append(anchor.confidence)
                        except Exception:
                            confidences.append(0.0)
            if confidences:
                confidence = min(confidences)
            else:
                confidence = float(face.confidence or 0.0)
            body_confidence = max(body_confidence, confidence)
        elif profile.requires_face:
            reasons.append("face_not_detected")
        else:
            # Face missing is expected for hand jewelry; keep reason as soft signal only.
            reasons.append("face_not_detected")

        if profile.requires_ears:
            required = self._required_sides()
            if any(
                (side == "left" and not left_visible) or (side == "right" and not right_visible) for side in required
            ):
                reasons.append("ear_not_visible")

        if profile.requires_neck and not neck_visible:
            reasons.append("neck_not_visible")

        hand_detected = bool(hand and hand.hand_detected)
        wrist_visible = bool(hand and hand.wrist_visible)
        fingers_visible = bool(hand and hand.fingers_visible)
        if hand_detected:
            detected_parts.append("hand")
            body_confidence = max(body_confidence, float(hand.confidence or 0.0))
            confidence = max(confidence, float(hand.confidence or 0.0))
            if wrist_visible:
                detected_parts.append("wrist")
            if fingers_visible:
                detected_parts.append("fingers")

        if profile.requires_hand and not hand_detected:
            reasons.append("hand_not_detected")
        if profile.requires_wrist and not wrist_visible:
            reasons.append("wrist_not_visible")
        if profile.requires_fingers and not fingers_visible:
            reasons.append("fingers_not_visible")

        if confidence < self.minimum_confidence and (
            profile.requires_face or profile.requires_hand or profile.requires_ears or profile.requires_neck
        ):
            # Only flag low confidence when the category actually needs landmarks.
            if face.face_detected or hand_detected:
                reasons.append("low_landmark_confidence")

        if variance < self.min_blur_variance:
            reasons.append("excessive_blur")

        pose = face.head_pose if face else None
        if pose is not None and profile.requires_face:
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

        unique_reasons: list[str] = []
        for reason in reasons:
            if reason not in unique_reasons:
                unique_reasons.append(reason)

        # Deduplicate detected parts while preserving order.
        unique_parts: list[str] = []
        for part in detected_parts:
            if part not in unique_parts:
                unique_parts.append(part)

        return FrameQuality(
            face_detected=bool(face.face_detected),
            left_ear_visible=left_visible,
            right_ear_visible=right_visible,
            blur_score=score,
            landmark_confidence=float(confidence),
            head_pose_stable=pose_stable,
            occluded=occluded,
            rejection_reasons=unique_reasons,
            jewelry_category=profile.jewelry_type,
            required_body_parts=list(profile.required_body_parts),
            detected_body_parts=unique_parts,
            body_confidence=float(body_confidence),
            hand_detected=hand_detected,
            neck_visible=neck_visible,
            wrist_visible=wrist_visible,
            fingers_visible=fingers_visible,
            quality_score=0.0,
            selection_status="pending",
        )

    def _neck_visible(self, landmarks: list[Landmark]) -> bool:
        """Neck / upper-chest band is visible below the chin within the frame."""
        if len(landmarks) <= 152:
            return False
        chin = landmarks[152]
        left = landmarks[234] if len(landmarks) > 234 else None
        right = landmarks[454] if len(landmarks) > 454 else None
        if not (0.0 <= chin.x <= 1.0 and 0.0 <= chin.y <= 0.95):
            return False
        face_width = 0.08
        if left is not None and right is not None:
            face_width = max(0.04, abs(right.x - left.x))
        neck_y = chin.y + face_width * 0.18
        return neck_y <= 0.98

    def _jewelry_still_loading(self, debug_state: dict | None) -> bool:
        if not isinstance(debug_state, dict):
            return False
        status = str(debug_state.get("qa_status") or "").lower()
        if status in {"loading", "loading_jewelry", "jewelry_loading"}:
            return True
        if debug_state.get("loading") or debug_state.get("jewelry_loading"):
            return True
        return False

    def _required_sides(self) -> list[str]:
        if self.ear_side == "both":
            return ["left", "right"]
        return [self.ear_side]
