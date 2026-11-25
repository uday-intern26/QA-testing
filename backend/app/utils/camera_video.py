"""Turn an uploaded face video into the Y4M file Chromium uses as a fake camera."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

# Keep a full left/right head turn. Cap only so a multi-minute upload cannot fill the disk.
MAX_CAMERA_FRAMES = 3600
# Bump when the encoder rules change so a truncated cache is not reused.
_CACHE_VERSION = "v2"


def ensure_fake_camera(source: Path) -> Path:
    """Return a Y4M path Chromium can play as the webcam. Regenerates when the source changes."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source.name)
    if source.suffix.lower() == ".y4m" and " " not in str(source):
        return source
    digest = hashlib.sha1(f"{source}|{source.stat().st_mtime_ns}|{source.stat().st_size}".encode("utf-8")).hexdigest()[:16]
    destination = Path(tempfile.gettempdir()) / f"aijewel-face-camera-{_CACHE_VERSION}-{digest}.y4m"
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    _write_y4m(source, destination)
    os.utime(destination, None)
    return destination


def video_duration_seconds(source: Path | None) -> float | None:
    """Length of the face/body video used as the try-on camera, in seconds."""
    if source is None:
        return None
    path = Path(source)
    if not path.is_file():
        return None
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    finally:
        capture.release()
    if fps <= 0 or frames <= 0:
        return None
    return float(frames / fps)


def _write_y4m(source: Path, destination: Path, *, max_frames: int = MAX_CAMERA_FRAMES) -> None:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError(f"Face video could not be opened: {source.name}")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    width -= width % 2
    height -= height % 2
    fps = int(round(capture.get(cv2.CAP_PROP_FPS) or 25)) or 25
    if width < 2 or height < 2:
        capture.release()
        raise ValueError("Face video has no usable frames.")
    written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".partial.y4m")
    try:
        with tmp.open("wb") as handle:
            handle.write(f"YUV4MPEG2 W{width} H{height} F{fps}:1 Ip A0:0 C420\n".encode("ascii"))
            while written < max_frames:
                ok, frame = capture.read()
                if not ok:
                    break
                cropped = np.ascontiguousarray(frame[:height, :width])
                yuv = cv2.cvtColor(cropped, cv2.COLOR_BGR2YUV_I420)
                handle.write(b"FRAME\n")
                handle.write(yuv.tobytes())
                written += 1
    finally:
        capture.release()
    if written == 0:
        tmp.unlink(missing_ok=True)
        raise ValueError("Face video has no usable frames.")
    tmp.replace(destination)
