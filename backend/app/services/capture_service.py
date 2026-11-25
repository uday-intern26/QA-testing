"""Capture orchestration for web, video, and unsupported desktop targets."""

from __future__ import annotations

from pathlib import Path

from app.adapters.tryon_application import TryOnApplicationAdapter
from app.services.frame_selector import RawFrame


class CaptureService:
    async def capture(
        self,
        adapter: TryOnApplicationAdapter,
        jewelry_id: str | None,
        jewelry_type: str | None = None,
        *,
        already_selected: bool = False,
    ) -> tuple[list[RawFrame], str]:
        # Avoid selecting twice — a second Try ON click stacks a duplicate jewelry item.
        if already_selected or getattr(adapter, "jewelry_selected", False):
            note = "Jewellery already selected for capture."
        else:
            note = await adapter.select_jewelry(
                jewelry_id,
                jewelry_type=jewelry_type or getattr(adapter, "jewelry_type", None),
            )
        frames = await adapter.capture()
        return frames, note

    @staticmethod
    def ffmpeg_available() -> bool:
        from shutil import which

        return which("ffmpeg") is not None

    @staticmethod
    def remux_to_mp4(source: Path, destination: Path) -> bool:
        from shutil import which
        import subprocess

        if which("ffmpeg") is None or not source.is_file():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destination)],
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.returncode == 0 and destination.is_file()
