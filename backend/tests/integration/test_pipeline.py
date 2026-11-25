"""Runs capture → frames → landmarks → anchors → placement → report without AWS."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.config import get_settings
from app.cv.ear_geometry import LEFT_EAR_CONTOUR
from app.cv.types import FaceLandmarkResult, HeadPose, Landmark
from app.db.database import session_scope
from app.db.repositories import runs as run_repo
from app.models.application import Application
from app.models.test import TestDefinition
from app.services.test_runner import TestRunner, initial_steps
from app.utils.files import write_json

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _landmarks() -> list[Landmark]:
    landmarks = [Landmark(x=0.5, y=0.45, confidence=1) for _ in range(478)]
    for index, contour_index in enumerate(LEFT_EAR_CONTOUR):
        if index < 15:
            landmarks[contour_index] = Landmark(
                x=0.30 + (index % 5) * 0.015,
                y=0.42 + (index % 3) * 0.04,
                confidence=1,
            )
        else:
            landmarks[contour_index] = Landmark(x=0.328 + (index - 15) * 0.004, y=0.60, confidence=1)
    return landmarks


class FixedLandmarks:
    def __init__(self, face_detected: bool = True) -> None:
        self.face_detected = face_detected

    def detect(self, _image):
        if not self.face_detected:
            return FaceLandmarkResult(face_detected=False, reason="face_not_detected")
        return FaceLandmarkResult(
            face_detected=True,
            landmarks=_landmarks(),
            confidence=0.95,
            head_pose=HeadPose(yaw=2, pitch=1, roll=0),
        )


def _frame_image(index: int) -> np.ndarray:
    palette = [
        (18, 22, 90),
        (90, 22, 18),
        (18, 90, 22),
        (90, 90, 18),
        (18, 90, 90),
        (90, 18, 90),
        (40, 40, 40),
        (120, 50, 20),
    ]
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[:] = palette[index % len(palette)]
    cv2.rectangle(image, (12, 12), (308, 228), (240, 240, 240), 2)
    cv2.rectangle(image, (20 + index * 28, 24), (110 + index * 28, 110), (40, 40 + index * 20, 200), -1)
    cv2.ellipse(image, (110, 120), (22, 48), 0, 0, 360, (90, 160, 220), -1)
    cv2.putText(image, f"F{index}", (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    cv2.line(image, (20, 30 + index * 12), (300, 200 - index * 10), (0, 220, 180), 2)
    return image


def _write_video(path: Path, frames: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    reference = FIXTURES / "sample_reference.png"
    if not reference.exists():
        cv2.imwrite(str(reference), _frame_image(0))
    candidates = [(path, "mp4v"), (path.with_suffix(".avi"), "MJPG")]
    for target, codec in candidates:
        writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*codec), 5, (320, 240))
        if not writer.isOpened():
            continue
        for index in range(frames):
            writer.write(_frame_image(index))
        writer.release()
        capture = cv2.VideoCapture(str(target))
        readable = capture.isOpened() and capture.read()[0]
        capture.release()
        if readable:
            return target
    pytest.skip("OpenCV could not write a readable sample video on this machine.")


def _seed_run(video: Path, anchors: Path, *, min_selected: int = 3) -> str:
    with session_scope() as session:
        application = Application(
            id="APP-001",
            name="Local video",
            type="video",
            video_path=str(video),
            anchor_file=str(anchors),
        )
        test = TestDefinition(
            id="TEST-001",
            name="Left Earring Placement Test",
            application_id=application.id,
            jewelry_id="E123",
            jewelry_type="earring",
            ear_side="left",
            capture_fps=5,
            minimum_confidence=0.8,
            pass_threshold=0.10,
            fail_threshold=0.15,
            minimum_pass_rate=0.95,
            maximum_consecutive_failures=2,
            min_selected_frames=min_selected,
            max_selected_frames=30,
        )
        session.add(application)
        session.add(test)
        session.commit()
        run = run_repo.create_run(session, test.id, initial_steps())
        return run.id


@pytest.mark.asyncio
async def test_video_pipeline_passes_when_attachment_is_on_the_lobe(tmp_path: Path):
    video = _write_video(FIXTURES / "sample_tryon.mp4")
    anchors = tmp_path / "anchors.json"
    write_json(
        anchors,
        {
            "frames": [
                {
                    "frame_index": index,
                    "jewelry_id": "E123",
                    "jewelry_type": "earring",
                    "left": {
                        "x": 0.338,
                        "y": 0.604,
                        "visible": True,
                        "local_x": -0.8,
                        "local_y": -3.8,
                        "local_z": -0.4,
                    },
                }
                for index in range(8)
            ]
        },
    )
    run_id = _seed_run(video, anchors)
    report = None
    runner = TestRunner(get_settings(), landmark_provider=FixedLandmarks())
    await runner.execute(run_id, None, "password-should-not-be-stored")
    with session_scope() as session:
        run = run_repo.get_run(session, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.overall_status == "PASS"
        report = json.loads(run.report_json or "{}")
        assert "password-should-not-be-stored" not in (run.report_json or "")
    assert report["layers"]["frame_selection"]["status"] == "PASS"
    assert report["layers"]["anchor_detection"]["status"] == "PASS"
    assert report["layers"]["placement_validation"]["status"] == "PASS"
    assert report["statistics"]["frames_selected"] >= 3
    assert report["frames"][0]["earring"]["source"] == "debug"
    assert report["frames"][0]["placement"]["status"] == "PASS"


@pytest.mark.asyncio
async def test_pipeline_fails_when_the_attachment_is_below_the_lobe(tmp_path: Path):
    video = _write_video(tmp_path / "low-earring.mp4")
    anchors = tmp_path / "anchors.json"
    write_json(
        anchors,
        {
            "frames": [
                {
                    "frame_index": index,
                    "jewelry_id": "E123",
                    "jewelry_type": "earring",
                    "left": {
                        "x": 0.338,
                        "y": 0.92,
                        "visible": True,
                        "local_x": 2.0,
                        "local_y": 2.0,
                        "local_z": 2.0,
                    },
                }
                for index in range(8)
            ]
        },
    )
    run_id = _seed_run(video, anchors, min_selected=3)
    runner = TestRunner(get_settings(), landmark_provider=FixedLandmarks())
    await runner.execute(run_id, None, None)
    with session_scope() as session:
        run = run_repo.get_run(session, run_id)
        assert run is not None
        assert run.overall_status == "FAIL"
        reason = (run.reason or "").lower()
        assert any(
            word in reason
            for word in ("below", "placement", "zone", "distance", "tracking", "earlobe", "attached")
        )
        report = json.loads(run.report_json or "{}")
        assert report["layers"]["frame_selection"]["status"] == "PASS"
        assert report["layers"]["anchor_detection"]["status"] == "PASS"
        assert report["layers"]["placement_validation"]["status"] == "FAIL"


@pytest.mark.asyncio
async def test_pipeline_fails_with_a_reason_when_the_face_is_missing(tmp_path: Path):
    video = _write_video(tmp_path / "empty-face.mp4", frames=6)
    anchors = tmp_path / "anchors.json"
    write_json(anchors, {"frames": []})
    run_id = _seed_run(video, anchors, min_selected=5)
    runner = TestRunner(get_settings(), landmark_provider=FixedLandmarks(face_detected=False))
    await runner.execute(run_id, None, None)
    with session_scope() as session:
        run = run_repo.get_run(session, run_id)
        assert run is not None
        assert run.overall_status == "FAIL"
        assert run.reason
        assert "frame" in run.reason.lower() or "face" in run.reason.lower()
