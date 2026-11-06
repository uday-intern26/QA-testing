"""Opens the public try-on application and checks that login reaches the app."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from app.adapters.tryon_application import PlaywrightTryOnAdapter, TryOnError
from app.core.config import Settings
from app.core.logging import log_event
from app.core.security import secret_registry
from app.models.application import Application
from app.schemas.application import ApplicationValidateResponse, CatalogCategory, CatalogResponse, CheckItem


def validate_url(url: str) -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TryOnError(
            "Invalid URL. Enter an http or https address such as the public Amplify URL.",
            "INVALID_URL",
        )
    if parsed.username or parsed.password:
        raise TryOnError("Do not embed credentials in the application URL.", "INVALID_URL")


class BrowserService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def validate(
        self,
        *,
        url: str,
        username: str,
        password: str,
        username_selector: str | None,
        password_selector: str | None,
        submit_selector: str | None,
        ready_selector: str | None,
        screenshot_dir: Path,
        video_path: str | None = None,
    ) -> ApplicationValidateResponse:
        checks: list[CheckItem] = []
        secret_registry.add(password)
        try:
            validate_url(url)
            checks.append(CheckItem(name="url_format", ok=True, detail="URL format is valid."))
        except TryOnError as exc:
            checks.append(CheckItem(name="url_format", ok=False, detail=str(exc)))
            return _failed(checks, str(exc))

        face_video = Path(video_path) if video_path else None
        if face_video is None or not face_video.is_file():
            checks.append(
                CheckItem(
                    name="face_video",
                    ok=False,
                    detail="Upload a video of the girl wearing no earrings before validation.",
                )
            )
            return _failed(
                checks,
                "Upload a video of the girl wearing no earrings, then validate the try-on again.",
            )
        checks.append(CheckItem(name="face_video", ok=True, detail="Face video is ready for the try-on camera."))
        application = Application(
            id="validation",
            name="validation",
            type="web",
            url=url,
            video_path=str(face_video),
            username=username or None,
            username_selector=username_selector,
            password_selector=password_selector,
            submit_selector=submit_selector,
            ready_selector=ready_selector,
        )
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        shot = screenshot_dir / f"{uuid4().hex}.png"
        adapter = PlaywrightTryOnAdapter(
            application,
            username=username,
            password=password,
            output_dir=screenshot_dir,
            fps=1,
            duration_seconds=1,
            headless=self.settings.playwright_headless,
            viewport_width=self.settings.viewport_width,
            viewport_height=self.settings.viewport_height,
            timeout_ms=self.settings.navigation_timeout_ms,
        )
        reachable = False
        login_ok = False
        loaded = False
        try:
            await adapter.connect()
            reachable = True
            checks.append(CheckItem(name="reachable", ok=True, detail="Application is reachable."))
            await adapter.authenticate()
            login_ok = True
            checks.append(CheckItem(name="login", ok=True, detail="Login successful."))
            await adapter.launch()
            loaded = True
            checks.append(
                CheckItem(
                    name="loaded",
                    ok=True,
                    detail="Try-on page opened with the face video as the camera.",
                )
            )
            # Keep Video mode active so the camera feed is ready for jewelry testing.
            await adapter.browser.wait_for_timeout(1500)
            catalog = await _read_catalog(adapter)
            jewelry = [name for group in catalog for name in group.items]
            if not jewelry:
                checks.append(
                    CheckItem(name="catalog", ok=False, detail="The try-on catalog did not list any jewelry.")
                )
                return ApplicationValidateResponse(
                    status="failed",
                    reachable=True,
                    login_successful=True,
                    application_loaded=True,
                    message="The try-on opened, but no catalog jewelry was available to choose.",
                    checks=checks,
                )
            checks.append(
                CheckItem(name="catalog", ok=True, detail=f"{len(jewelry)} catalog pieces are ready to choose.")
            )
            # Catalog reading may close a storefront modal; reopen so the camera view is ready.
            if await adapter._is_storefront():
                await adapter._open_storefront_tryon()
                await adapter._wait_for_canvas(timeout_ms=30000)
            try:
                await adapter.browser.screenshot(shot)
                screenshot = str(shot)
            except Exception:
                try:
                    page = adapter.browser._require_page()
                    await page.screenshot(path=str(shot))
                    screenshot = str(shot)
                except Exception:
                    screenshot = None
            log_event("APPLICATION_VALIDATED", url=url, jewelry=len(jewelry))
            return ApplicationValidateResponse(
                status="success",
                reachable=True,
                login_successful=True,
                application_loaded=True,
                message="Try-on is open with the camera. Choose a catalog piece from the dropdown.",
                checks=checks,
                screenshot_url=screenshot,
                jewelry=jewelry,
                catalog=catalog,
            )
        except TryOnError as exc:
            if not reachable:
                checks.append(CheckItem(name="reachable", ok=False, detail=str(exc)))
            elif not login_ok:
                checks.append(CheckItem(name="login", ok=False, detail=str(exc)))
            elif not loaded:
                checks.append(CheckItem(name="loaded", ok=False, detail=str(exc)))
            else:
                checks.append(CheckItem(name="catalog", ok=False, detail=str(exc)))
            log_event("APPLICATION_VALIDATION_FAILED", code=exc.code, detail=str(exc))
            return ApplicationValidateResponse(
                status="failed",
                reachable=reachable,
                login_successful=login_ok,
                application_loaded=loaded,
                message=str(exc),
                checks=checks,
                screenshot_url=None,
            )
        except Exception as exc:
            detail = secret_registry.redact(str(exc)).strip() or exc.__class__.__name__
            message = f"Browser automation failed: {detail}"
            checks.append(CheckItem(name="browser", ok=False, detail=message))
            log_event("APPLICATION_VALIDATION_FAILED", code="BROWSER", detail=message)
            return _failed(checks, message)
        finally:
            await adapter.close()
            secret_registry.discard(password)

    async def list_catalog(
        self,
        *,
        url: str,
        username: str,
        password: str,
        video_path: str | None,
    ) -> CatalogResponse:
        """Open a try-on URL and return the jewelry names grouped by category."""
        secret_registry.add(password)
        try:
            validate_url(url)
        except TryOnError as exc:
            return CatalogResponse(url=url, categories=[], message=str(exc))
        face_video = Path(video_path) if video_path else None
        if face_video is None or not face_video.is_file():
            return CatalogResponse(
                url=url,
                categories=[],
                message="Upload a video of the girl wearing no earrings, then load the catalog again.",
            )
        application = Application(
            id="catalog",
            name="catalog",
            type="web",
            url=url,
            video_path=str(face_video),
            username=username or None,
        )
        adapter = PlaywrightTryOnAdapter(
            application,
            username=username,
            password=password,
            output_dir=self.settings.data_dir / "applications" / "validation",
            fps=1,
            duration_seconds=1,
            headless=self.settings.playwright_headless,
            viewport_width=self.settings.viewport_width,
            viewport_height=self.settings.viewport_height,
            timeout_ms=self.settings.navigation_timeout_ms,
        )
        try:
            await adapter.connect()
            await adapter.authenticate()
            await adapter.launch()
            categories = await _read_catalog(adapter)
            if not categories:
                return CatalogResponse(url=url, categories=[], message="The try-on URL did not list any jewelry.")
            return CatalogResponse(url=url, categories=categories, message="")
        except TryOnError as exc:
            return CatalogResponse(url=url, categories=[], message=str(exc))
        except Exception as exc:
            detail = secret_registry.redact(str(exc)).strip() or exc.__class__.__name__
            return CatalogResponse(url=url, categories=[], message=f"Browser automation failed: {detail}")
        finally:
            await adapter.close()
            secret_registry.discard(password)


async def _read_catalog(adapter: PlaywrightTryOnAdapter) -> list[CatalogCategory]:
    grouped = await adapter.catalog_by_category()
    if not grouped:
        names = await adapter.catalog_earring_names()
        if names:
            grouped = [{"category": "Earrings", "items": names}]
    return [CatalogCategory.model_validate(group) for group in grouped]


def _failed(checks: list[CheckItem], message: str) -> ApplicationValidateResponse:
    return ApplicationValidateResponse(
        status="failed",
        reachable=False,
        login_successful=False,
        application_loaded=False,
        message=message,
        checks=checks,
    )
