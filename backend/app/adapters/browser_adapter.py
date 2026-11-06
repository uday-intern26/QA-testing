"""Browser automation boundary. Playwright is one implementation."""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote_to_bytes


class BrowserAdapter(ABC):
    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def goto(self, url: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def screenshot(self, path: Path) -> None:
        raise NotImplementedError

    @abstractmethod
    async def fill(self, selector: str, value: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def click(self, selector: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def query(self, selector: str):
        raise NotImplementedError

    @abstractmethod
    async def evaluate(self, script: str, argument=None):
        raise NotImplementedError

    @abstractmethod
    async def wait_for_timeout(self, milliseconds: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def content_text(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class PlaywrightBrowserAdapter(BrowserAdapter):
    def __init__(
        self,
        *,
        headless: bool,
        viewport_width: int,
        viewport_height: int,
        timeout_ms: int,
        video_dir: Path | None = None,
        camera_video: Path | None = None,
    ) -> None:
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.timeout_ms = timeout_ms
        self.video_dir = video_dir
        self.camera_video = camera_video
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Install backend requirements and run 'playwright install chromium'."
            ) from exc
        self._playwright = await async_playwright().start()
        context_options = {
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
        }
        if self.video_dir is not None:
            self.video_dir.mkdir(parents=True, exist_ok=True)
            context_options["record_video_dir"] = str(self.video_dir)
            context_options["record_video_size"] = {
                "width": self.viewport_width,
                "height": self.viewport_height,
            }
        launch_args = ["--use-fake-ui-for-media-stream"]
        if self.camera_video is not None:
            from app.utils.camera_video import ensure_fake_camera

            camera = ensure_fake_camera(Path(self.camera_video))
            launch_args.append("--use-fake-device-for-media-stream")
            launch_args.append(f"--use-file-for-fake-video-capture={camera}")
        self._browser = await self._playwright.chromium.launch(
            channel="msedge",
            headless=self.headless,
            args=launch_args,
        )
        self._context = await self._browser.new_context(**context_options)
        await self._context.grant_permissions(["camera", "microphone"])
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    async def goto(self, url: str) -> None:
        await self._require_page().goto(url, wait_until="domcontentloaded")

    async def set_input_files(self, selector: str, path: Path) -> None:
        await self._require_page().locator(selector).set_input_files(str(path))

    async def fetch_bytes(self, url: str) -> bytes | None:
        """Download a catalog image. Page cookies are sent for http(s) URLs."""
        if not url:
            return None
        if url.startswith("data:"):
            return _decode_data_url(url)
        if not url.startswith(("http://", "https://")):
            return None
        try:
            response = await self._require_page().request.get(url, timeout=15000)
            if not response.ok:
                return None
            body = await response.body()
            return body or None
        except Exception:
            return None

    async def screenshot_first(self, selector: str, path: Path) -> bool:
        """Save a catalog thumbnail. A hidden thumbnail must not stop the test."""
        try:
            page = self._require_page()
            locator = page.locator(selector).first
            if await locator.count() == 0 or not await locator.is_visible():
                return False
            path.parent.mkdir(parents=True, exist_ok=True)
            await locator.screenshot(path=str(path), timeout=3000, animations="disabled")
            return True
        except Exception:
            return False

    async def screenshot_clip(self, path: Path, box: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        clip = {
            "x": max(0, float(box["x"])),
            "y": max(0, float(box["y"])),
            "width": max(1, float(box["width"])),
            "height": max(1, float(box["height"])),
        }
        await self._require_page().screenshot(path=str(path), clip=clip)

    async def tryon_box(self) -> dict | None:
        locator = await self._tryon_viewport()
        if locator is None:
            return None
        box = await locator.bounding_box()
        if not box or box.get("width", 0) < 80 or box.get("height", 0) < 80:
            return None
        return {
            "x": float(box["x"]),
            "y": float(box["y"]),
            "width": float(box["width"]),
            "height": float(box["height"]),
        }

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        page = self._require_page()
        tryon = await self._tryon_viewport()
        if tryon is not None:
            await tryon.screenshot(path=str(path))
            return
        raise RuntimeError(
            "The try-on viewport was not visible, so the advertisement video was not captured."
        )

    async def _tryon_viewport(self):
        page = self._require_page()
        frames = page.locator("iframe")
        count = await frames.count()
        best = None
        best_area = 0
        for index in range(count):
            handle = frames.nth(index)
            src = (await handle.get_attribute("src") or "").lower()
            if "advertisement" in src:
                continue
            box = await handle.bounding_box()
            if not box or box.get("width", 0) < 80 or box.get("height", 0) < 80:
                continue
            area = box["width"] * box["height"]
            if "unity" in src or "tryon" in src or "modal-frame" in (await handle.get_attribute("class") or "").lower() or area > best_area:
                best = handle
                best_area = area
        if best is not None:
            return best
        canvases = page.locator("canvas")
        count = await canvases.count()
        for index in range(count):
            handle = canvases.nth(index)
            box = await handle.bounding_box()
            if box and box.get("width", 0) > 80 and box.get("height", 0) > 80:
                return handle
        return None

    async def fill(self, selector: str, value: str) -> None:
        await self._require_page().fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._require_page().click(selector)

    async def click_text(self, text: str) -> bool:
        locator = self._require_page().get_by_text(text, exact=True)
        if await locator.count() == 0:
            return False
        await locator.first.click(force=True, timeout=2000)
        return True

    async def query(self, selector: str):
        return await self._require_page().query_selector(selector)

    async def evaluate(self, script: str, argument=None):
        page = self._require_page()
        if argument is None:
            return await page.evaluate(script)
        return await page.evaluate(script, argument)

    async def wait_for_timeout(self, milliseconds: int) -> None:
        await self._require_page().wait_for_timeout(milliseconds)

    async def content_text(self) -> str:
        return await self._require_page().inner_text("body")

    async def video_path(self) -> Path | None:
        page = self._page
        if page is None or page.video is None:
            return None
        raw = await page.video.path()
        return Path(raw) if raw else None

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    def _require_page(self):
        if self._page is None:
            raise RuntimeError("Browser is not started.")
        return self._page


def _decode_data_url(url: str) -> bytes | None:
    header, separator, payload = url.partition(",")
    if not separator or not payload:
        return None
    try:
        if ";base64" in header:
            return base64.b64decode(payload, validate=False)
        return unquote_to_bytes(payload)
    except Exception:
        return None
