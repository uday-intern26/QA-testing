from pathlib import Path

import cv2
import numpy as np

from app.utils.camera_video import ensure_fake_camera, video_duration_seconds


def _write_clip(path: Path, frames: int = 200, fps: int = 25) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (64, 48),
    )
    assert writer.isOpened()
    for index in range(frames):
        shade = 40 + (index % 180)
        frame = np.full((48, 64, 3), shade, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_fake_camera_keeps_full_girl_video(tmp_path):
    source = tmp_path / "turn.mp4"
    _write_clip(source, frames=200, fps=25)
    y4m = ensure_fake_camera(source)
    assert y4m.is_file()
    header = y4m.read_bytes().split(b"\n", 1)[0].decode("ascii")
    assert "W64" in header and "H48" in header
    frame_marker_count = y4m.read_bytes().count(b"FRAME\n")
    assert frame_marker_count == 200
    assert abs((video_duration_seconds(source) or 0) - 8.0) < 0.2
