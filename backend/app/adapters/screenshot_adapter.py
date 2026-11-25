"""Screenshot capture behind an adapter so storage can change later."""

from __future__ import annotations

from pathlib import Path

from app.adapters.browser_adapter import BrowserAdapter


class ScreenshotAdapter:
    def __init__(self, browser: BrowserAdapter) -> None:
        self.browser = browser

    async def capture(self, path: Path) -> Path:
        await self.browser.screenshot(path)
        return path

    async def capture_playing(self, path: Path) -> Path:
        """Capture while the try-on video keeps advancing."""
        playing = getattr(self.browser, "screenshot_playing", None)
        if playing is not None:
            await playing(path)
        else:
            await self.browser.screenshot(path)
        return path
