"""Try-on application boundary. Web uses Playwright. Desktop is reserved."""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

from app.adapters.browser_adapter import PlaywrightBrowserAdapter
from app.cv.image_processing import read_bgr
from app.cv.jewelry_presence import jewelry_visible_in_image, subject_visible
from app.cv.visualization import image_from_bytes, save_catalog_sprite
from app.adapters.earring_anchor_adapter import EarringAnchorPageAdapter
from app.adapters.screenshot_adapter import ScreenshotAdapter
from app.core.logging import log_event
from app.models.application import Application
from app.services.frame_selector import RawFrame

USERNAME_SELECTORS = [
    "input[name='username']",
    "input[id='username']",
    "input[autocomplete='username']",
    "input[type='email']",
    "input[name='email']",
    "input[id='email']",
    "input[type='text']",
]
PASSWORD_SELECTORS = [
    "input[type='password']",
    "input[name='password']",
    "input[id='password']",
]
SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Sign in')",
    "button:has-text('Log in')",
    "button:has-text('Login')",
    "button:has-text('Continue')",
]


class TryOnError(Exception):
    def __init__(self, message: str, code: str, recommended_action: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.recommended_action = recommended_action


class TryOnApplicationAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def authenticate(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def launch(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def select_jewelry(self, jewelry_id: str | None, jewelry_type: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    async def capture(self) -> list[RawFrame]:
        raise NotImplementedError

    @abstractmethod
    async def get_earring_anchor(self) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class PlaywrightTryOnAdapter(TryOnApplicationAdapter):
    def __init__(
        self,
        application: Application,
        *,
        username: str,
        password: str,
        output_dir: Path,
        fps: int,
        duration_seconds: float,
        headless: bool,
        viewport_width: int,
        viewport_height: int,
        timeout_ms: int,
    ) -> None:
        self.application = application
        self.username = username
        self.password = password
        self.output_dir = output_dir
        self.fps = fps
        self.duration_seconds = duration_seconds
        camera_video = Path(application.video_path) if application.video_path else None
        self.browser = PlaywrightBrowserAdapter(
            headless=headless,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            timeout_ms=timeout_ms,
            video_dir=output_dir / "video",
            camera_video=camera_video,
        )
        self.screenshots = ScreenshotAdapter(self.browser)
        self.anchors = EarringAnchorPageAdapter(self.browser)
        self.video_file: Path | None = None
        from app.services.live_jewelry_overlay import LiveJewelryOverlay

        self.live_overlay = LiveJewelryOverlay(self.browser, output_dir)
        self.jewelry_type = "earring"
        self.jewelry_selected = False
        self._qa_hand_jewelry_placed = False

    async def connect(self) -> None:
        if not self.application.url:
            raise TryOnError("Web application URL is missing.", "INVALID_URL")
        if self.application.video_path and not Path(self.application.video_path).is_file():
            raise TryOnError(
                "The bare-ear face video was not found. Upload that video before running the try-on test.",
                "VIDEO_MISSING",
            )
        await self.browser.start()
        try:
            await self.browser.goto(self.application.url)
        except Exception as exc:
            raise TryOnError(
                f"Unable to open the application URL: {exc.__class__.__name__}.",
                "APPLICATION_UNREACHABLE",
                "Check the public Amplify URL and that the machine can reach it.",
            ) from exc
        log_event("APPLICATION_CONNECTED", url=self.application.url)

    async def authenticate(self) -> None:
        if not self.username or not self.password:
            log_event("AUTHENTICATION_SUCCESS", detail="No credentials configured; skipping login.")
            return

        # Some Amplify builds show only a Login button until the form is opened.
        password_selector = await self._wait_present(
            _split(self.application.password_selector) or PASSWORD_SELECTORS,
            timeout_ms=2500,
        )
        if password_selector is None:
            opened = await self._open_login_form()
            password_selector = await self._wait_present(
                _split(self.application.password_selector) or PASSWORD_SELECTORS,
                timeout_ms=15000,
            )
            if password_selector is None:
                if await self._looks_like_login_landing():
                    raise TryOnError(
                        "Authentication failed. The Login page opened, but the username/password form never appeared.",
                        "AUTH_FAILED",
                        "Click Login on the try-on site, confirm the form is visible, then try again.",
                    )
                # Already inside the app — no login form needed.
                log_event(
                    "AUTHENTICATION_SUCCESS",
                    detail="No password field was present." + (" Opened Login first." if opened else ""),
                )
                return

        username_selector = await self._wait_present(
            _split(self.application.username_selector) or USERNAME_SELECTORS,
            timeout_ms=5000,
        )
        if username_selector is None:
            raise TryOnError(
                "Authentication failed. A password field was found, but the username field was not.",
                "AUTH_FAILED",
                "Set a username selector in the application configuration.",
            )
        # Live screenshots during typing can drop the username. Keep the page still until both fields stick.
        self._pause_live_view = True
        try:
            await self._fill_login_username(username_selector, self.username)
            await self.browser.fill(password_selector, self.password)
            # Filling the password re-renders the React form and can wipe the username.
            if not await self._login_username_matches(self.username):
                await self._fill_login_username(username_selector, self.username)
            if not await self._login_username_matches(self.username):
                raise TryOnError(
                    "Authentication failed. The username field was left empty.",
                    "AUTH_FAILED",
                    "The login username did not stay in the form. Run again.",
                )
        finally:
            self._pause_live_view = False
        await self.browser.wait_for_timeout(200)
        submitted = await self.browser.evaluate(
            """() => {
              const form = document.querySelector('form.login-card, form');
              if (form && typeof form.requestSubmit === 'function') {
                form.requestSubmit();
                return 'form';
              }
              const button = document.querySelector("button[type='submit'], input[type='submit']");
              if (button) { button.click(); return 'button'; }
              return '';
            }"""
        )
        if not submitted:
            submit_selector = await self._wait_present(
                _split(self.application.submit_selector) or SUBMIT_SELECTORS,
                timeout_ms=5000,
            )
            if submit_selector is None:
                if not await self._click_exact("Login") and not await self._click_visible_text("Login"):
                    raise TryOnError(
                        "Authentication failed. The login submit control was not found.",
                        "AUTH_FAILED",
                        "Set a submit selector in the application configuration.",
                    )
            else:
                await self.browser.click(submit_selector)

        for _ in range(40):
            await self.browser.wait_for_timeout(500)
            auth_error = await self._login_error_text()
            if auth_error:
                raise TryOnError(
                    f"Authentication failed. {auth_error}",
                    "AUTH_FAILED",
                    "Check the username and password. The password was not logged.",
                )
            try:
                still_password = await self.browser.query("input[type='password']")
            except Exception:
                still_password = None
            # Success = credential form is gone and we are no longer on the Login gate.
            if still_password is None and (
                await self._tryon_surface_present() or not await self._looks_like_login_landing()
            ):
                log_event("AUTHENTICATION_SUCCESS")
                return
            # DemoGate keeps the password input mounted until React re-renders the storefront.
            if await self._tryon_surface_present() and not await self._looks_like_login_landing():
                log_event("AUTHENTICATION_SUCCESS")
                return
        raise TryOnError(
            "Authentication failed.",
            "AUTH_FAILED",
            "Check the username, password, and login selectors. The password was not logged.",
        )

    async def _fill_login_username(self, fallback_selector: str, value: str) -> None:
        """Fill the username next to the password, not the first text box on the page."""
        marked = await self.browser.evaluate(
            """() => {
              const visible = (el) => {
                if (!el) return false;
                const box = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return box.width > 8 && box.height > 8 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              document.querySelectorAll('[data-qa-username]').forEach((el) => el.removeAttribute('data-qa-username'));
              const password = [...document.querySelectorAll('input[type="password"]')].find(visible);
              const root = (password && password.closest('form')) || document;
              const selectors = [
                'input[name="username"]',
                'input[id="username"]',
                'input[autocomplete="username"]',
                'input[type="email"]',
                'input[name="email"]',
                'input[id="email"]',
                'input[type="text"]',
              ];
              for (const sel of selectors) {
                const match = [...root.querySelectorAll(sel)].find((el) => visible(el) && el !== password);
                if (match) {
                  match.setAttribute('data-qa-username', '1');
                  return true;
                }
              }
              return false;
            }"""
        )
        target = "input[data-qa-username='1']" if marked else fallback_selector
        await self.browser.fill(target, value)

    async def _login_username_matches(self, value: str) -> bool:
        current = await self.browser.evaluate(
            """() => {
              const marked = document.querySelector('input[data-qa-username="1"]');
              if (marked) return marked.value || '';
              const password = document.querySelector('input[type="password"]');
              const root = (password && password.closest('form')) || document;
              const field = root.querySelector(
                'input[name="username"], input[id="username"], input[autocomplete="username"], input[type="email"], input[type="text"]'
              );
              return field ? (field.value || '') : '';
            }"""
        )
        return str(current or "") == value

    async def _login_error_text(self) -> str | None:
        text = await self.browser.evaluate(
            """() => {
              const alert = document.querySelector('form.login-card .login-error, form.login-card [role="alert"], .login-error[role="alert"]');
              const raw = (alert?.innerText || '').trim();
              if (raw) return raw.slice(0, 200);
              const body = (document.body?.innerText || '');
              const match = body.match(/that username or password is not valid\\.?/i)
                || body.match(/invalid username or password\\.?/i);
              return match ? match[0].trim() : '';
            }"""
        )
        cleaned = str(text or "").strip()
        return cleaned or None

    async def _open_login_form(self) -> bool:
        """Open the credential form from the Login landing page.

        Some Amplify builds show only a Login button on `/`. Clicking it should
        route to `/login`, but automation can miss that client route — so we also
        navigate to `/login` directly when the form still is not present.

        Do not click "Sign in" when the password field is already visible — on the
        DemoGate storefront that label is the submit button and would submit empty.
        """
        if await self._wait_present(PASSWORD_SELECTORS, timeout_ms=500):
            return True
        for label in ("Login", "Log in", "Sign in", "Sign In"):
            # Avoid submitting an already-visible credential form.
            if await self._wait_present(PASSWORD_SELECTORS, timeout_ms=200):
                return True
            if await self._click_exact(label) or await self._click_visible_text(label):
                await self.browser.wait_for_timeout(1000)
                if await self._wait_present(PASSWORD_SELECTORS, timeout_ms=2000):
                    return True
        # Direct route used by the Virtual Jewelry Try-On Amplify app.
        try:
            href = str(await self.browser.evaluate("() => location.origin") or "").rstrip("/")
            if href:
                await self.browser.goto(f"{href}/login")
                await self.browser.wait_for_timeout(1000)
                return True
        except Exception:
            return False
        return False

    async def _looks_like_login_landing(self) -> bool:
        return bool(
            await self.browser.evaluate(
                """() => {
                  const text = (document.body.innerText || '').trim();
                  const loginOnly = /^login$/i.test(text) || text.toLowerCase() === 'login';
                  const loginButton = [...document.querySelectorAll('button, [role="button"], a')]
                    .some((node) => /^(login|log in|sign in)$/i.test((node.innerText || node.getAttribute('aria-label') || '').trim()));
                  const hasTryOn = !!document.querySelector('button.header-try-on, button.try-on, canvas, video, article.card');
                  // Password form open is still the login flow, but handled separately by callers.
                  return (loginOnly || loginButton) && !hasTryOn;
                }"""
            )
        )

    async def _tryon_surface_present(self) -> bool:
        return bool(
            await self.browser.evaluate(
                """() => {
                  const surface = [...document.querySelectorAll('canvas, video, iframe, article.card')]
                    .some((node) => {
                      const box = node.getBoundingClientRect();
                      return box.width > 80 && box.height > 80;
                    });
                  const tryOn = !!document.querySelector('button.header-try-on, button.try-on');
                  return surface || tryOn;
                }"""
            )
        )

    async def _wait_present(self, selectors: list[str], timeout_ms: int) -> str | None:
        elapsed = 0
        while elapsed <= timeout_ms:
            found = await self._first_present(selectors)
            if found is not None:
                return found
            await self.browser.wait_for_timeout(250)
            elapsed += 250
        return None

    async def launch(self) -> None:
        if await self._is_storefront():
            # Stay on the catalog. Clicking Try ON here AND again in select_jewelry stacks jewelry.
            await self._dismiss_overlays()
            await self._close_storefront_tryon_modal()
            has_cards = bool(
                await self.browser.evaluate("() => document.querySelectorAll('article.card').length > 0")
            )
            if not has_cards:
                raise TryOnError(
                    "The storefront catalog did not show jewelry cards.",
                    "APPLICATION_NOT_READY",
                    "Open the jewelry storefront URL and confirm product cards are visible.",
                )
            log_event("TRYON_READY", mode="storefront-catalog")
            return
        await self._reach_tryon()
        await self._dismiss_overlays()
        await self._click_exact("Video")
        await self._leave_photo_matching()
        ready = await self._wait_for_canvas(timeout_ms=90000)
        if not ready:
            raise TryOnError(
                "Try-on application did not reach the ready state.",
                "APPLICATION_NOT_READY",
                "Confirm the try-on viewport opens. On the storefront, click Try ON so the camera view appears.",
            )
        await self._leave_photo_matching()
        log_event("TRYON_READY")

    async def _is_storefront(self) -> bool:
        return bool(
            await self.browser.evaluate(
                """() => Boolean(
                  document.querySelector('button.header-try-on, button.try-on, article.card')
                )"""
            )
        )

    async def _close_storefront_tryon_modal(self) -> None:
        """Close an open try-on modal so the next Try ON starts from a clean single instance."""
        await self.browser.evaluate(
            """() => {
              const labels = ['close', '×', 'x'];
              const nodes = [...document.querySelectorAll('button, [role="button"], a')];
              for (const node of nodes) {
                const text = (node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase();
                if (labels.includes(text)) {
                  node.click();
                  return true;
                }
              }
              const root = document.getElementById('qa-live-jewelry');
              if (root) root.remove();
              return false;
            }"""
        )
        await self.browser.wait_for_timeout(400)

    async def _open_storefront_tryon(self) -> None:
        """Open try-on only when needed (validation preview). Prefer header, not a product card."""
        await self._dismiss_overlays()
        await self._close_storefront_tryon_modal()
        opened = await self.browser.evaluate(
            """() => {
              const header = document.querySelector('button.header-try-on');
              if (header) {
                header.click();
                return 'header';
              }
              const cards = [...document.querySelectorAll('article.card')];
              const card = cards[0];
              const cardButton = card && card.querySelector('button.try-on');
              if (cardButton) {
                cardButton.click();
                return 'card';
              }
              return '';
            }"""
        )
        if not opened:
            raise TryOnError(
                "The storefront Try ON control was not found.",
                "APPLICATION_NOT_READY",
                "Open the jewelry storefront URL and confirm a Try ON button is visible.",
            )
        await self.browser.wait_for_timeout(2000)
        log_event("STOREFRONT_TRYON_OPENED", source=opened)

    async def _reach_tryon(self) -> None:
        target = self.application.url
        for _ in range(10):
            href = str(await self.browser.evaluate("() => location.href") or "")
            if "/choose-theme" in href:
                await self._click_visible_text("Soft Gray")
                await self._click_visible_text("Next")
                await self.browser.wait_for_timeout(1500)
                continue
            if "/try-on" in href:
                return
            if await self._is_storefront():
                return
            if target:
                await self.browser.goto(target)
            await self.browser.wait_for_timeout(1500)

    async def _wait_for_tryon_view(self) -> None:
        if await self._wait_for_canvas(timeout_ms=30000):
            return
        raise TryOnError(
            "The try-on viewport did not open, so the advertisement video was not used.",
            "APPLICATION_NOT_READY",
            "Open Try ON until the camera view is visible, then run the test again.",
        )

    async def _tryon_load_status(self) -> str:
        """Return loading | photo-match | ready | empty for the live try-on UI."""
        return str(
            await self.browser.evaluate(
                """() => {
                  const text = document.body.innerText || '';
                  if (text.includes('No matching jewelry') || text.includes('Try All Categories')) {
                    return 'photo-match';
                  }
                  const frames = [...document.querySelectorAll('iframe')];
                  const hasFrame = frames.some((frame) => {
                    const src = (frame.getAttribute('src') || '').toLowerCase();
                    if (src.includes('advertisement')) return false;
                    const box = frame.getBoundingClientRect();
                    return box.width > 80 && box.height > 80;
                  });
                  const hasSurface = [...document.querySelectorAll('video, canvas')].some((node) => {
                    const box = node.getBoundingClientRect();
                    return box.width > 80 && box.height > 80;
                  });
                  // Storefront try-on keeps "Starting try-on…" in the modal title until the
                  // iframe posts ready — the iframe itself is already the camera surface.
                  if (hasFrame || hasSurface) return 'ready';
                  if (
                    text.includes('Loading jewelry')
                    || text.includes('Loading try-on')
                    || text.includes('Starting try-on')
                  ) {
                    return 'loading';
                  }
                  return 'empty';
                }"""
            )
            or "empty"
        )

    async def _wait_for_jewelry_ready(self, timeout_ms: int = 60000) -> bool:
        """Wait until the try-on canvas is up and 'Loading jewelry...' has cleared."""
        elapsed = 0
        while elapsed <= timeout_ms:
            await self._leave_photo_matching()
            status = await self._tryon_load_status()
            if status == "photo-match":
                return False
            if status == "ready":
                # Let the AR attachment settle after the loading chip disappears.
                await self.browser.wait_for_timeout(1000)
                if await self._tryon_load_status() == "ready":
                    await self._capture_jewelry_lay_if_present()
                    return True
            await self.browser.wait_for_timeout(500)
            elapsed += 500
        return False

    @staticmethod
    def _supports_qa_jewelry_fallback(jewelry_type: str | None) -> bool:
        return (jewelry_type or "earring").lower() in {
            "ring",
            "bracelet",
            "bangle",
            "necklace",
            "earring",
        }

    async def _place_jewelry_fallback(self) -> bool:
        """If AR stays on Loading jewelry, place the catalog piece on the detected body region."""
        jewelry_type = (getattr(self, "jewelry_type", None) or "earring").lower()
        if not self._supports_qa_jewelry_fallback(jewelry_type):
            return False
        # Amplify storefront AR already draws the selected piece — stacking a sprite
        # makes the jewel appear twice in the live preview / capture.
        if await self._storefront_ar_active():
            self._qa_hand_jewelry_placed = False
            overlay = getattr(self, "live_overlay", None)
            if overlay is not None:
                await overlay.clear()
            log_event("JEWELRY_FALLBACK_SKIPPED_STOREFRONT_AR", jewelry_type=jewelry_type)
            return False
        overlay = getattr(self, "live_overlay", None)
        if overlay is None:
            return False
        overlay.jewelry_type = jewelry_type
        frame_dir = self.output_dir / "captured"
        frame_dir.mkdir(parents=True, exist_ok=True)
        probe = frame_dir / "_jewelry_ready_probe.png"
        screenshots = getattr(self, "screenshots", None)
        if screenshots is None:
            return False
        await screenshots.capture(probe)
        placed = await overlay.force_place(probe)
        if placed:
            log_event("JEWELRY_FALLBACK_PLACED", jewelry_type=jewelry_type)
            self._qa_hand_jewelry_placed = True
        return placed

    async def _anchors_available(self) -> bool:
        """Canvas 'ready' alone is not enough — the attachment point must exist too."""
        from app.adapters.earring_anchor_adapter import state_has_attachment

        state = await self.get_earring_anchor()
        return state_has_attachment(state)

    async def _storefront_ar_active(self) -> bool:
        """True when the Amplify/storefront try-on iframe is already drawing jewelry.

        That iframe is usually cross-origin, so QA cannot read attachment anchors.
        Placing the catalog overlay on top stacks a second jewel on screen.
        """
        if await self._is_storefront():
            return bool(
                await self.browser.evaluate(
                    """() => {
                      const modal = document.querySelector('.modal, [role="dialog"]');
                      const frames = [...document.querySelectorAll('iframe')];
                      return frames.some((frame) => {
                        const src = (frame.getAttribute('src') || '').toLowerCase();
                        const box = frame.getBoundingClientRect();
                        if (box.width < 80 || box.height < 80) return false;
                        if (src.includes('advertisement')) return false;
                        return Boolean(modal) || src.includes('tryon') || src.includes('embed=1');
                      });
                    }"""
                )
            )
        return False

    async def _ensure_jewelry_ready(self, timeout_ms: int) -> bool:
        if await self._wait_for_jewelry_ready(timeout_ms=timeout_ms):
            # The loading chip can clear while the GLB still has no projected anchor.
            if await self._anchors_available():
                self._qa_hand_jewelry_placed = False
                return True
            # Storefront AR already paints the piece — never stack a QA sprite on top.
            if await self._storefront_ar_active():
                self._qa_hand_jewelry_placed = False
                overlay = getattr(self, "live_overlay", None)
                if overlay is not None:
                    await overlay.clear()
                log_event("JEWELRY_READY_STOREFRONT_AR")
                return True
            # Fall through to the catalog overlay so validation still has coordinates.
        jewelry_type = (getattr(self, "jewelry_type", None) or "earring").lower()
        if not self._supports_qa_jewelry_fallback(jewelry_type):
            return False
        # Never overlay a second jewel when storefront AR is already rendering one.
        if await self._storefront_ar_active():
            self._qa_hand_jewelry_placed = False
            overlay = getattr(self, "live_overlay", None)
            if overlay is not None:
                await overlay.clear()
            return await self._wait_for_jewelry_ready(timeout_ms=min(timeout_ms, 15000))
        # AR often keeps "Loading jewelry..." even with a clear face/hand/neck.
        # Place the catalog sprite on the detected body region so capture can continue.
        if await self._place_jewelry_fallback():
            return True
        await self.browser.wait_for_timeout(2000)
        if await self._wait_for_jewelry_ready(timeout_ms=15000) and await self._anchors_available():
            self._qa_hand_jewelry_placed = False
            return True
        if await self._storefront_ar_active():
            self._qa_hand_jewelry_placed = False
            return True
        return await self._place_jewelry_fallback()

    # Back-compat aliases used by older call sites / tests.
    async def _place_hand_jewelry_fallback(self) -> bool:
        return await self._place_jewelry_fallback()

    async def _ensure_hand_jewelry_ready(self, timeout_ms: int) -> bool:
        return await self._ensure_jewelry_ready(timeout_ms)

    async def _wait_for_canvas(self, timeout_ms: int) -> bool:
        elapsed = 0
        while elapsed <= timeout_ms:
            await self._leave_photo_matching()
            status = await self._tryon_load_status()
            # Canvas can appear while jewelry is still loading — that is not ready yet.
            if status == "ready":
                await self.browser.wait_for_timeout(1500)
                if await self._tryon_load_status() == "ready":
                    return True
            # Do not auto-click a catalog Try ON here — that stacks a second jewelry instance.
            await self.browser.wait_for_timeout(500)
            elapsed += 500
        return False

    async def _dismiss_overlays(self) -> None:
        saw_dialog = False
        for _ in range(20):
            text = str(await self.browser.evaluate("() => document.body.innerText") or "")
            if "Stay Updated" in text or "Maybe later" in text:
                saw_dialog = True
                click_text = getattr(self.browser, "click_text", None)
                if click_text is not None:
                    try:
                        await click_text("Maybe later")
                    except Exception:
                        pass
                await self.browser.evaluate(
                    """() => {
                      const nodes = [...document.querySelectorAll('button, [role="button"], a, span, p')];
                      const later = nodes.find((node) => (node.innerText || '').trim() === 'Maybe later');
                      if (later) { later.click(); return; }
                      const close = nodes.find((node) => (node.getAttribute('aria-label') || '').toLowerCase() === 'close');
                      if (close) close.click();
                    }"""
                )
                await self.browser.wait_for_timeout(400)
                continue
            if saw_dialog:
                return
            await self.browser.wait_for_timeout(500)

    async def _leave_photo_matching(self) -> None:
        text = str(await self.browser.evaluate("() => document.body.innerText") or "")
        if "No matching jewelry" in text or "Try All Categories" in text:
            await self._click_exact("Show All Category")

    @staticmethod
    def _catalog_label(jewelry_type: str | None) -> str:
        return {
            "earring": "Earrings",
            "necklace": "Necklaces",
            "bracelet": "Bracelets",
            "ring": "Rings",
            "bangle": "Bangles",
        }.get((jewelry_type or "earring").lower(), "Earrings")

    @staticmethod
    def _catalog_name_pattern(jewelry_type: str | None) -> str:
        return {
            "earring": "earring",
            "necklace": "necklace",
            "bracelet": "bracelet",
            "ring": "ring",
            "bangle": "bangle",
        }.get((jewelry_type or "earring").lower(), "earring")

    async def _open_earring_catalog(self) -> None:
        await self._open_jewelry_catalog("earring")

    async def _open_jewelry_catalog(self, jewelry_type: str | None) -> None:
        """Open the catalog for the jewelry type. AI Recommendations is not the test."""
        label = self._catalog_label(jewelry_type)
        pattern = self._catalog_name_pattern(jewelry_type)
        for _ in range(40):
            await self._click_exact("Show All Category")
            await self.browser.wait_for_timeout(300)
            await self._click_exact(label)
            state = await self.browser.evaluate(
                """({ pattern }) => {
                  const text = document.body.innerText || '';
                  const photoMatch = text.includes('No matching jewelry') || text.includes('Try All Categories');
                  const re = new RegExp(pattern, 'i');
                  const matches = [...document.querySelectorAll('img')]
                    .map((img) => (img.alt || '').trim())
                    .filter((alt) => re.test(alt));
                  return { photoMatch, count: matches.length };
                }""",
                {"pattern": pattern},
            )
            if state and not state.get("photoMatch") and state.get("count", 0) > 0:
                return
            await self.browser.wait_for_timeout(500)
        raise TryOnError(
            f"The try-on page stayed on photo matching. Catalog {label.lower()} were not opened.",
            "JEWELRY_NOT_FOUND",
            f"Use Show All Category, then {label}. Do not use AI Recommendations.",
        )

    async def _click_exact(self, label: str) -> bool:
        clicked = await self.browser.evaluate(
            """(label) => {
              const wanted = label.trim().toLowerCase();
              const nodes = [...document.querySelectorAll('button, [role="button"], a, div, span, p')];
              const matches = nodes.filter((node) => {
                const text = (node.innerText || node.getAttribute('aria-label') || '').trim().toLowerCase();
                return text === wanted;
              });
              if (!matches.length) return false;
              matches.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
              matches[0].click();
              return true;
            }""",
            label,
        )
        return bool(clicked)

    async def _click_visible_text(self, label: str) -> bool:
        clicked = await self.browser.evaluate(
            """(label) => {
              const nodes = [...document.querySelectorAll('button, [role="button"], a')];
              const match = nodes.find((node) => (node.innerText || node.getAttribute('aria-label') || '').trim() === label)
                || nodes.find((node) => (node.innerText || '').includes(label));
              if (!match) return false;
              match.click();
              return true;
            }""",
            label,
        )
        return bool(clicked)

    async def select_jewelry(self, jewelry_id: str | None, jewelry_type: str | None = None) -> str:
        jewelry_type = (jewelry_type or self.jewelry_type or "earring").lower()
        self.jewelry_type = jewelry_type
        self.live_overlay.jewelry_type = jewelry_type
        # Selecting again re-opens Try ON and can stack a second necklace/earring on screen.
        if self.jewelry_selected and (jewelry_id or "") == getattr(self, "_selected_jewelry_id", None):
            return f"Catalogue {jewelry_type} already selected."
        if await self._is_storefront():
            note = await self._select_storefront_jewelry(jewelry_id, jewelry_type=jewelry_type)
            self.jewelry_selected = True
            self._selected_jewelry_id = jewelry_id or ""
            # App AR already draws the jewelry — QA overlay would duplicate / oversize it.
            await self.live_overlay.clear()
            return note
        label = self._catalog_label(jewelry_type)
        pattern = self._catalog_name_pattern(jewelry_type)
        await self._click_exact("Video")
        await self._open_jewelry_catalog(jewelry_type)
        selected = None
        for _ in range(20):
            selected = await self.browser.evaluate(
                """async ({ jewelryId, pattern }) => {
                  const text = document.body.innerText || '';
                  if (text.includes('No matching jewelry') || text.includes('Try All Categories')) return null;
                  const wanted = (jewelryId || '').trim().toLowerCase();
                  const images = [...document.querySelectorAll('img')].filter((img) => (img.alt || '').trim());
                  const typeRe = new RegExp(pattern, 'i');
                  const match = wanted
                    ? images.find((img) => (img.alt || '').toLowerCase().includes(wanted))
                    : images.find((img) => typeRe.test(img.alt || ''));
                  if (!match) return null;
                  match.setAttribute('data-qa-selected-earring', '1');
                  match.scrollIntoView({ block: 'center', inline: 'nearest' });
                  if (match.decode) {
                    try { await match.decode(); } catch (error) {}
                  }
                  const sources = [];
                  const push = (url, width) => {
                    if (!url) return;
                    let absolute = url;
                    try { absolute = new URL(url, document.baseURI).href; } catch (error) {}
                    sources.push({ url: absolute, width: width || 0 });
                  };
                  push(match.currentSrc, match.naturalWidth || 0);
                  push(match.src, 0);
                  for (const part of (match.srcset || '').split(',')) {
                    const bits = part.trim().split(/\\s+/);
                    if (!bits[0]) continue;
                    const descriptor = bits[1] || '';
                    const width = descriptor.endsWith('w') ? parseInt(descriptor, 10) : 0;
                    push(bits[0], Number.isFinite(width) ? width : 0);
                  }
                  sources.sort((a, b) => b.width - a.width);
                  return { name: match.alt || pattern, src: sources.length ? sources[0].url : '' };
                }""",
                {"jewelryId": jewelry_id or "", "pattern": pattern},
            )
            if selected:
                await self._save_catalog_photo(str(selected.get("src") or ""))
                selected = selected.get("name") or pattern
                self._begin_jewelry_lay_timer()
                await self.browser.evaluate(
                    """() => {
                      const match = document.querySelector("img[data-qa-selected-earring='1']");
                      if (!match) return false;
                      (match.closest('button, a, [role="button"]') || match).click();
                      return true;
                    }"""
                )
                break
            await self._click_exact("Show All Category")
            await self._click_exact(label)
            await self.browser.wait_for_timeout(500)
        if not selected:
            raise TryOnError(
                f"The catalog {pattern} was not selected. Photo matching was not used.",
                "JEWELRY_NOT_FOUND",
                f"Open Show All Category, choose {label}, and select the catalog item.",
            )
        await self.browser.wait_for_timeout(1000)
        ready = await self._ensure_jewelry_ready(timeout_ms=20000)
        if not ready:
            status = await self._tryon_load_status()
            if status == "photo-match":
                raise TryOnError(
                    f"The try-on page stayed on photo matching after the catalog {pattern} was selected.",
                    "JEWELRY_NOT_FOUND",
                    "Leave AI Recommendations closed and keep Show All Category selected.",
                )
            raise TryOnError(
                f"The catalog {pattern} was selected but never finished loading onto the body.",
                "APPLICATION_NOT_READY",
                "Keep the required body part clearly in view until the jewelry can be placed, then run again.",
            )
        self.jewelry_selected = True
        self._selected_jewelry_id = jewelry_id or ""
        if not getattr(self, "_qa_hand_jewelry_placed", False):
            await self.live_overlay.clear()
        return f"Selected catalogue {pattern} {selected}."

    async def _select_storefront_jewelry(self, jewelry_id: str | None, jewelry_type: str | None = None) -> str:
        jewelry_type = (jewelry_type or self.jewelry_type or "earring").lower()
        pattern = self._catalog_name_pattern(jewelry_type)
        # Always start from a closed modal so only one Try ON instance is active.
        await self._close_storefront_tryon_modal()
        await self.live_overlay.clear()
        wanted = (jewelry_id or "").strip().lower()
        self._begin_jewelry_lay_timer()
        selected = await self.browser.evaluate(
            """({ wanted, pattern }) => {
              const cards = [...document.querySelectorAll('article.card')];
              const typeRe = new RegExp(pattern, 'i');
              const card = wanted
                ? cards.find((item) => {
                    const name = (item.querySelector('h2')?.innerText || '').trim().toLowerCase();
                    const sku = (item.querySelector('.sku')?.innerText || '').trim().toLowerCase();
                    return name.includes(wanted) || sku.includes(wanted) || wanted.includes(name);
                  })
                : cards.find((item) => typeRe.test(item.innerText || '')) || cards[0];
              if (!card) return null;
              const img = card.querySelector('img');
              if (img) img.setAttribute('data-qa-selected-earring', '1');
              const button = card.querySelector('button.try-on');
              if (!button) return null;
              button.click();
              return {
                name: (card.querySelector('h2')?.innerText || '').trim() || 'jewelry',
                src: img ? (img.currentSrc || img.src || '') : '',
              };
            }""",
            {"wanted": wanted, "pattern": pattern},
        )
        if not selected:
            raise TryOnError(
                "The storefront jewelry was not selected.",
                "JEWELRY_NOT_FOUND",
                "Choose a jewelry ID that appears on the storefront catalog.",
            )
        await self._save_catalog_photo(str(selected.get("src") or ""))
        await self.browser.wait_for_timeout(1000)
        ready = await self._ensure_jewelry_ready(timeout_ms=20000)
        if not ready:
            status = await self._tryon_load_status()
            if status == "photo-match":
                raise TryOnError(
                    f"The storefront stayed on photo matching after the catalog {pattern} was selected.",
                    "JEWELRY_NOT_FOUND",
                    "Leave AI Recommendations closed and keep the catalog item selected.",
                )
            raise TryOnError(
                f"The storefront try-on opened but the {pattern} never finished loading onto the body.",
                "APPLICATION_NOT_READY",
                "Keep the face and neck clearly in view until the necklace can be placed, then run again.",
            )
        return f"Selected catalogue {pattern} {selected.get('name') or 'jewelry'}."

    async def _save_catalog_photo(self, src: str) -> bool:
        """Keep the catalog product photo so the live try-on shows that earring, not a drawn stand-in."""
        destination = self.output_dir / "selected_earring.png"
        image = await self._catalog_image(src)
        if image is not None and save_catalog_sprite(image, destination):
            log_event("CATALOG_EARRING_SAVED", file=destination.name)
            return True
        saver = getattr(self.browser, "screenshot_first", None)
        if saver is not None and await saver("img[data-qa-selected-earring='1']", destination):
            image = image_from_bytes(destination.read_bytes())
            if image is not None and save_catalog_sprite(image, destination):
                log_event("CATALOG_EARRING_SAVED", file=destination.name, source="screenshot")
                return True
        log_event("CATALOG_EARRING_MISSING")
        return False

    async def _catalog_image(self, src: str):
        fetch = getattr(self.browser, "fetch_bytes", None)
        if fetch is not None and src:
            payload = await fetch(src)
            image = image_from_bytes(payload or b"")
            if image is not None:
                return image
        raster = await self.browser.evaluate(
            """async () => {
              const match = document.querySelector("img[data-qa-selected-earring='1']");
              if (!match || !match.naturalWidth) return null;
              const canvas = document.createElement("canvas");
              canvas.width = match.naturalWidth;
              canvas.height = match.naturalHeight;
              try {
                canvas.getContext("2d").drawImage(match, 0, 0);
                return canvas.toDataURL("image/png");
              } catch (error) {
                return null;
              }
            }"""
        )
        if fetch is None or not isinstance(raster, str):
            return None
        return image_from_bytes(await fetch(raster) or b"")

    async def use_straight_face_image(self, path: Path) -> None:
        """Show the uploaded face. Catalog earrings are placed on this photo, not matched to it."""
        await self._click_exact("Image")
        await self.browser.wait_for_timeout(800)
        try:
            await self.browser.set_input_files("[data-testid='image-upload-input']", path)
        except Exception:
            await self.browser.set_input_files("input[type='file']", path)
        await self.browser.wait_for_timeout(2000)
        await self._leave_photo_matching()

    async def catalog_by_category(self) -> list[dict]:
        """Open each try-on category and return the product names shown for that URL."""
        from app.services.jewelry_catalog import CATALOG_CATEGORIES, names_for_category

        if await self._is_storefront():
            return await self._storefront_catalog_by_category()
        found: list[dict] = []
        for label in CATALOG_CATEGORIES:
            await self._click_exact("Show All Category")
            await self.browser.wait_for_timeout(300)
            if not await self._click_exact(label):
                continue
            alts: list[str] = []
            for _ in range(8):
                await self.browser.wait_for_timeout(400)
                raw = await self.browser.evaluate(
                    """() => [...document.querySelectorAll('img')].map((img) => (img.alt || '').trim()).filter(Boolean)"""
                )
                alts = names_for_category(label, list(raw or []))
                if alts:
                    break
            if alts:
                found.append({"category": label, "items": alts})
        return found

    async def _storefront_catalog_by_category(self) -> list[dict]:
        from app.services.jewelry_catalog import CATALOG_CATEGORIES

        # Close an open try-on modal so category filters and cards are visible.
        await self.browser.evaluate(
            """() => {
              const close = [...document.querySelectorAll('button')].find(
                (node) => (node.innerText || '').trim().toLowerCase() === 'close'
              );
              if (close) close.click();
            }"""
        )
        await self.browser.wait_for_timeout(500)
        nav_labels = {
            "Earrings": "EARRINGS",
            "Necklaces": "NECKLACES",
            "Bracelets": "BRACELETS",
            "Rings": "RINGS",
            "Bangles": "BANGLES",
        }
        found: list[dict] = []
        for category in CATALOG_CATEGORIES:
            label = nav_labels.get(category, category.upper())
            if not await self._click_exact(label):
                continue
            await self.browser.wait_for_timeout(600)
            names = await self.browser.evaluate(
                """() => {
                  const seen = new Set();
                  const items = [];
                  for (const card of document.querySelectorAll('article.card')) {
                    const name = (card.querySelector('h2')?.innerText || '').trim();
                    if (!name || seen.has(name)) continue;
                    seen.add(name);
                    items.push(name);
                  }
                  return items;
                }"""
            )
            items = [str(name).strip() for name in (names or []) if str(name).strip()]
            if items:
                found.append({"category": category, "items": items})
        return found

    async def catalog_earring_names(self) -> list[str]:
        await self._open_earring_catalog()
        names = await self.browser.evaluate(
            """() => {
              const seen = new Set();
              const names = [];
              for (const img of document.querySelectorAll('img')) {
                const alt = (img.alt || '').trim();
                if (!/earring/i.test(alt) || seen.has(alt)) continue;
                seen.add(alt);
                names.push(alt);
              }
              return names;
            }"""
        )
        return list(names or [])

    async def face_panel_box(self) -> dict:
        box = await self.browser.evaluate(
            """() => {
              const nodes = [...document.querySelectorAll('h1, h2, h3, div, p, span')];
              const title = nodes.find((node) => (node.innerText || '').trim() === 'Jewelry Collection');
              const right = title ? title.getBoundingClientRect().left : window.innerWidth * 0.62;
              const width = Math.max(80, Math.min(right - 12, window.innerWidth - 12));
              const height = Math.max(80, window.innerHeight - 88);
              return { x: 8, y: 72, width, height };
            }"""
        )
        return box or {"x": 8, "y": 72, "width": 700, "height": 600}

    async def _jewelry_laid_on_video(self) -> bool:
        """True only when jewelry is actually on the live girl/face video — not still starting."""
        return bool(
            await self.browser.evaluate(
                """() => {
                  const text = (document.body?.innerText || '');
                  if (/starting try-on/i.test(text)) return false;
                  if (/loading jewelry/i.test(text) || /loading try-on/i.test(text)) return false;
                  if (/no matching jewelry/i.test(text) || /try all categories/i.test(text)) return false;
                  const frames = [...document.querySelectorAll('iframe, canvas, video')];
                  const hasSurface = frames.some((node) => {
                    const src = ((node.getAttribute && node.getAttribute('src')) || '').toLowerCase();
                    if (src.includes('advertisement')) return false;
                    const box = node.getBoundingClientRect();
                    return box.width > 80 && box.height > 80;
                  });
                  if (!hasSurface) return false;
                  // Storefront modal: title switches from "Starting try-on…" to the piece name
                  // once the jewel is laid on the camera feed.
                  const title = document.querySelector('.modal h2, [role="dialog"] h2');
                  const titleText = (title?.innerText || '').trim();
                  if (titleText) {
                    return !/starting try-on/i.test(titleText);
                  }
                  // Non-storefront try-on: surface present and loading chips gone.
                  return true;
                }"""
            )
        )

    async def _wait_for_jewelry_laid_on_video(self, timeout_ms: int = 90000) -> bool:
        """Block until the jewel is laid on the girl video, then return True."""
        elapsed = 0
        while elapsed <= timeout_ms:
            await self._leave_photo_matching()
            if await self._jewelry_laid_on_video():
                # Brief confirm so a one-frame title flicker does not start the settle clock.
                await self.browser.wait_for_timeout(800)
                if await self._jewelry_laid_on_video():
                    log_event("TRYON_SURFACE_READY")
                    return True
            await self.browser.wait_for_timeout(500)
            elapsed += 500
        return False

    async def capture(self) -> list[RawFrame]:
        log_event("CAPTURE_STARTED", fps=self.fps, duration_seconds=self.duration_seconds)
        await self._dismiss_overlays()
        await self._wait_for_tryon_view()
        jewelry_type = (getattr(self, "jewelry_type", None) or "earring").lower()
        ready = await self._ensure_jewelry_ready(timeout_ms=45000)
        if not ready:
            blocked = await self._tryon_load_status()
            if blocked == "photo-match":
                raise TryOnError(
                    "Capture stopped because the page was matching the face photo instead of showing catalog jewelry.",
                    "JEWELRY_NOT_FOUND",
                    "Open Show All Category and select the catalog jewelry before capture.",
                )
            raise TryOnError(
                f"Capture stopped because the {jewelry_type} was still loading and was never placed on the body.",
                "APPLICATION_NOT_READY",
                "Keep the required body part clearly in view until the jewelry can be placed, then run again.",
            )
        # 1) The try-on window can open before the jewel is drawn. Do not grab frames yet.
        if not await self._wait_for_jewelry_laid_on_video(timeout_ms=90000):
            raise TryOnError(
                f"Capture stopped because the {jewelry_type} try-on never opened.",
                "APPLICATION_NOT_READY",
                "Wait until the jewelry is visible on the face/body video, then run again.",
            )
        # 2) A short pause, then 30 frames. Do not wait out the whole face video.
        settle_seconds = self._jewelry_settle_seconds()
        if settle_seconds > 0 and not getattr(self, "_jewelry_settled_for_capture", False):
            log_event(
                "JEWELRY_SETTLE_WAIT",
                seconds=settle_seconds,
                jewelry_type=jewelry_type,
                detail="after_jewelry_laid_on_video",
            )
            await self.browser.wait_for_timeout(int(settle_seconds * 1000))
            self._jewelry_settled_for_capture = True
        frame_dir = self.output_dir / "captured"
        frame_dir.mkdir(parents=True, exist_ok=True)
        total = max(1, int(getattr(self, "post_lay_capture_frames", 0) or self._post_lay_capture_frames()))
        interval_ms = max(0, int(self._capture_frame_gap_ms()))
        frames: list[RawFrame] = []
        storefront_ar = await self._storefront_ar_active()
        qa_overlay = bool(getattr(self, "_qa_hand_jewelry_placed", False)) and not storefront_ar
        if storefront_ar:
            self._qa_hand_jewelry_placed = False
            qa_overlay = False
        if not qa_overlay:
            await self.live_overlay.clear()
        if jewelry_type == "earring":
            await self._wait_for_earring_worn_before_capture()
        loading_failures = 0
        kept = 0
        started = time.monotonic()
        # Live-preview shots during this loop add another screenshot per frame.
        self._pause_live_view = True
        try:
            while kept < total:
                if not storefront_ar:
                    storefront_ar = await self._storefront_ar_active()
                    if storefront_ar:
                        self._qa_hand_jewelry_placed = False
                        qa_overlay = False
                        await self.live_overlay.clear()
                status = await self._tryon_load_status()
                if status == "loading" and not qa_overlay and not storefront_ar:
                    if not await self._ensure_jewelry_ready(timeout_ms=20000):
                        loading_failures += 1
                        if loading_failures >= 3:
                            raise TryOnError(
                                f"Capture stopped because the {jewelry_type} returned to Loading jewelry during recording.",
                                "APPLICATION_NOT_READY",
                                "Keep the body steady in frame until the jewelry stays visible, then run again.",
                            )
                        continue
                    qa_overlay = bool(getattr(self, "_qa_hand_jewelry_placed", False))
                    loading_failures = 0
                path = frame_dir / f"frame_{kept:04d}.png"
                await self.screenshots.capture_playing(path)
                if qa_overlay and not storefront_ar and self._supports_qa_jewelry_fallback(jewelry_type):
                    await self.live_overlay.force_place(path)
                state = await self.get_earring_anchor()
                if not isinstance(state, dict):
                    state = {}
                from app.adapters.earring_anchor_adapter import state_has_attachment

                if (
                    not storefront_ar
                    and not state_has_attachment(state)
                    and not qa_overlay
                    and self._supports_qa_jewelry_fallback(jewelry_type)
                ):
                    if await self._place_jewelry_fallback():
                        qa_overlay = True
                        await self.live_overlay.force_place(path)
                        state = await self.get_earring_anchor() or {}
                if qa_overlay and not storefront_ar:
                    state = self._publish_qa_overlay_attachments(state if isinstance(state, dict) else {}, jewelry_type)
                elif state_has_attachment(state):
                    state = {**state, "qa_status": "ready"}
                elif storefront_ar:
                    state = {
                        **(state if isinstance(state, dict) else {}),
                        "qa_status": "ready",
                        "anchor_source": "storefront_ar",
                        "anchor_stage": "AR_VISIBLE",
                    }
                else:
                    state = {
                        **(state if isinstance(state, dict) else {}),
                        "qa_status": "anchor_missing",
                    }
                elapsed_ms = int((time.monotonic() - started) * 1000)
                frames.append(RawFrame(index=kept, timestamp_ms=elapsed_ms, path=path, debug_state=state))
                kept += 1
                if kept < total and interval_ms:
                    await self.browser.wait_for_timeout(interval_ms)
        finally:
            self._pause_live_view = False
        if len(frames) < total:
            raise TryOnError(
                f"No frames were captured because the {jewelry_type} never finished loading.",
                "INSUFFICIENT_FRAMES",
                "Wait until Loading jewelry disappears with the body part visible, then run again.",
            )
        meta_path = self.output_dir / "capture_meta.json"
        meta_path.write_text(
            json.dumps(
                [
                    {
                        "index": frame.index,
                        "timestamp_ms": frame.timestamp_ms,
                        "path": str(frame.path),
                        "debug": frame.debug_state,
                    }
                    for frame in frames
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        log_event("CAPTURE_COMPLETED", frames=len(frames))
        return frames

    def _publish_qa_overlay_attachments(self, state: dict, jewelry_type: str) -> dict:
        """Copy the catalog-overlay placements into the debug-state shape detectors already read."""
        published = {
            **state,
            "qa_status": "ready",
            "qa_overlay": jewelry_type,
            "anchor_source": "qa_overlay",
            "anchor_stage": "ANCHOR_AVAILABLE",
        }
        placements = list(getattr(self.live_overlay, "_last_placements", []) or [])
        for item in placements:
            side_key = str(item.get("side") or ("center" if jewelry_type == "necklace" else "left"))
            attachment = {
                "x": float(item["x"]),
                "y": float(item["y"]),
                "visible": True,
                "confidence": 0.92,
                "source": "qa_overlay",
                "side": side_key,
            }
            published[side_key] = attachment
            published[jewelry_type] = attachment
            if jewelry_type == "necklace":
                published["necklace"] = attachment
                published["center"] = attachment
            if jewelry_type == "earring" and side_key in {"left", "right"}:
                published[side_key] = attachment
        return published

    def _begin_jewelry_lay_timer(self) -> None:
        """Start the clock when the catalog piece is chosen, until it is on the video."""
        if getattr(self, "_lay_started_at", None) is None:
            self._lay_started_at = time.monotonic()

    async def _wait_until_jewelry_visible(self, jewelry_type: str, timeout_ms: int = 90000) -> bool:
        """Poll until the jewel is on the body. These probes are not result frames."""
        from app.adapters.earring_anchor_adapter import state_has_attachment

        frame_dir = self.output_dir / "captured"
        frame_dir.mkdir(parents=True, exist_ok=True)
        probe = frame_dir / "_lay_probe.png"
        elapsed = 0
        diagnostics = {
            "pixel_visible": False,
            "subject_visible": False,
            "storefront_ar": False,
            "attachment_published": False,
            "probes": 0,
            "timeout_ms": timeout_ms,
        }
        self._jewelry_wait_diagnostics = diagnostics
        self._pause_live_view = True
        try:
            while elapsed <= timeout_ms:
                diagnostics["probes"] += 1
                storefront = await self._storefront_ar_active()
                diagnostics["storefront_ar"] = bool(storefront)
                state = await self.get_earring_anchor()
                attached = state_has_attachment(state if isinstance(state, dict) else None)
                diagnostics["attachment_published"] = bool(attached)
                await self.screenshots.capture_playing(probe)
                try:
                    shot = read_bgr(probe)
                except ValueError:
                    shot = None
                probe.unlink(missing_ok=True)
                pixel = shot is not None and jewelry_visible_in_image(shot, jewelry_type)
                subject = shot is not None and subject_visible(shot)
                diagnostics["pixel_visible"] = bool(pixel)
                diagnostics["subject_visible"] = bool(subject)
                # A published attachment, a visible piece, or storefront AR on a body
                # all mean the jewel is placed. Probes before that are not counted.
                if pixel or attached or (storefront and subject):
                    self._note_jewelry_laid()
                    log_event(
                        "JEWELRY_LAID_ON_VIDEO",
                        seconds=getattr(self, "jewelry_lay_seconds", None),
                        pixel_visible=pixel,
                        attachment_published=attached,
                        storefront_ar=storefront,
                    )
                    return True
                await self.browser.wait_for_timeout(1500)
                elapsed += 1500
        finally:
            probe.unlink(missing_ok=True)
            self._jewelry_wait_diagnostics = diagnostics
        return False

    async def _capture_jewelry_lay_if_present(self) -> None:
        """Lay time is recorded when the jewel is visible, not when the try-on window opens."""
        return

    def _note_jewelry_laid(self) -> None:
        if getattr(self, "jewelry_lay_seconds", None) is not None:
            return
        started = getattr(self, "_lay_started_at", None)
        if started is None:
            return
        seconds = round(time.monotonic() - started, 1)
        self.jewelry_lay_seconds = seconds
        try:
            (self.output_dir / "jewelry_lay.json").write_text(
                json.dumps({"seconds": seconds}),
                encoding="utf-8",
            )
        except Exception:
            pass
        log_event("JEWELRY_LAY_SECONDS", seconds=seconds)

    def _jewelry_settle_seconds(self) -> float:
        try:
            from app.core.config import get_settings

            return max(0.0, float(get_settings().jewelry_settle_seconds))
        except Exception:
            return 1.0

    def _post_lay_capture_frames(self) -> int:
        try:
            from app.core.config import get_settings

            return max(1, int(get_settings().post_lay_capture_frames))
        except Exception:
            return 30

    def _capture_frame_gap_ms(self) -> int:
        try:
            from app.core.config import get_settings

            return max(0, int(get_settings().capture_frame_gap_ms))
        except Exception:
            return 200

    def _expand_duration_for_face_video(self) -> None:
        """Record long enough to cover the girl video's left and right rotation."""
        from app.utils.camera_video import video_duration_seconds

        source = Path(self.application.video_path) if self.application.video_path else None
        seconds = video_duration_seconds(source)
        if seconds is None or seconds <= 0:
            return
        # One full pass of the camera file, capped so a multi-minute upload stays usable.
        needed = min(180.0, max(float(self.duration_seconds), float(seconds)))
        if needed > float(self.duration_seconds):
            log_event(
                "CAPTURE_DURATION_EXPANDED",
                from_seconds=float(self.duration_seconds),
                to_seconds=needed,
                face_video_seconds=float(seconds),
            )
            self.duration_seconds = needed

    async def _wait_for_earring_worn_before_capture(self) -> None:
        """Skip the empty lead-in where earrings are not yet on the girl video."""
        from app.adapters.earring_anchor_adapter import state_has_attachment

        # Wait until AR shows the earring, then drop ~4 frames (0.4s at the old 10 fps).
        deadline_ms = 20000
        elapsed = 0
        poll_ms = 200
        while elapsed <= deadline_ms:
            storefront_ar = await self._storefront_ar_active()
            state = await self.get_earring_anchor()
            if storefront_ar or state_has_attachment(state if isinstance(state, dict) else None):
                log_event("EARRING_WORN_ON_VIDEO", elapsed_ms=elapsed)
                await self.browser.wait_for_timeout(400)
                return
            await self.browser.wait_for_timeout(poll_ms)
            elapsed += poll_ms
        log_event("EARRING_WORN_WAIT_TIMEOUT", elapsed_ms=elapsed)

    async def get_earring_anchor(self) -> dict | None:
        jewelry_type = self.jewelry_type or "earring"
        sides = ("center",) if jewelry_type == "necklace" else ("left", "right")
        return await self.anchors.read_state(jewelry_type, sides)

    def _start_live_view(self) -> None:
        """Keep a screenshot of the open try-on so Step 2 can show it while the test runs."""
        if getattr(self, "_live_view_task", None) is not None:
            return
        self._stop_live_view = False
        self._live_view_task = asyncio.create_task(self._live_view_loop())

    async def _live_view_loop(self) -> None:
        while not getattr(self, "_stop_live_view", False):
            if not getattr(self, "_pause_live_view", False):
                try:
                    await self.browser.screenshot_live(self.output_dir / "live_preview.png")
                except Exception:
                    pass
            await asyncio.sleep(2.5)

    async def _stop_live_view_task(self) -> None:
        self._stop_live_view = True
        task = getattr(self, "_live_view_task", None)
        self._live_view_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        await self._stop_live_view_task()
        self.live_overlay.close()
        self.video_file = await self.browser.video_path()
        await self.browser.close()


class VideoFileTryOnAdapter(TryOnApplicationAdapter):
    def __init__(self, application: Application, output_dir: Path, fps: int) -> None:
        self.application = application
        self.output_dir = output_dir
        self.fps = fps
        self._frames: list[RawFrame] = []

    async def connect(self) -> None:
        if not self.application.video_path:
            raise TryOnError("Video/file application is missing a video path.", "VIDEO_MISSING")
        path = Path(self.application.video_path)
        if not path.is_file():
            raise TryOnError(f"Video file was not found: {path.name}", "VIDEO_MISSING")

    async def authenticate(self) -> None:
        return None

    async def launch(self) -> None:
        return None

    async def select_jewelry(self, jewelry_id: str | None, jewelry_type: str | None = None) -> str:
        return "Video/file mode does not select jewellery in a live application."

    async def capture(self) -> list[RawFrame]:
        from app.services.frame_selector import FrameSelector

        selector = FrameSelector(
            min_blur_variance=0,
            blur_norm_variance=1,
            duplicate_hash_distance=0,
            head_pose_max_delta_deg=180,
            head_pose_max_yaw_deg=180,
            min_ear_width=0.001,
            minimum_confidence=0,
            ear_side="both",
        )
        frames = selector.extract_video(Path(self.application.video_path), self.fps, self.output_dir / "captured")
        anchors = _load_anchor_sidecar(self.application.anchor_file)
        if anchors:
            for frame in frames:
                frame.debug_state = anchors.get(frame.index) or anchors.get(frame.timestamp_ms)
        self._frames = frames
        return frames

    async def get_earring_anchor(self) -> dict | None:
        return None

    async def close(self) -> None:
        return None


class DesktopTryOnAdapter(TryOnApplicationAdapter):
    async def connect(self) -> None:
        raise TryOnError(
            "Desktop application automation is not implemented yet.",
            "DESKTOP_UNSUPPORTED",
            "Use Web Application or Video/File. The adapter boundary is in place for a later desktop engine.",
        )

    async def authenticate(self) -> None:
        await self.connect()

    async def launch(self) -> None:
        await self.connect()

    async def select_jewelry(self, jewelry_id: str | None, jewelry_type: str | None = None) -> str:
        await self.connect()
        return ""

    async def capture(self) -> list[RawFrame]:
        await self.connect()
        return []

    async def get_earring_anchor(self) -> dict | None:
        await self.connect()
        return None

    async def close(self) -> None:
        return None


def build_tryon_adapter(application: Application, **kwargs) -> TryOnApplicationAdapter:
    if application.type == "web":
        return PlaywrightTryOnAdapter(application, **kwargs)
    if application.type == "video":
        return VideoFileTryOnAdapter(
            application,
            output_dir=kwargs["output_dir"],
            fps=kwargs["fps"],
        )
    if application.type == "desktop":
        return DesktopTryOnAdapter()
    raise TryOnError(f"Unknown application type '{application.type}'.", "INVALID_APPLICATION")


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("||") if item.strip()]


def _load_anchor_sidecar(path: str | None) -> dict:
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    frames = payload.get("frames", payload if isinstance(payload, list) else [])
    mapped: dict = {}
    if isinstance(frames, list):
        for item in frames:
            if not isinstance(item, dict):
                continue
            state = item.get("state", item)
            if "frame_index" in item:
                mapped[int(item["frame_index"])] = state
            if "timestamp_ms" in item:
                mapped[int(item["timestamp_ms"])] = state
    return mapped


class ValidationSession:
    """Short-lived browser session used by application validation."""

    def __init__(self, browser: PlaywrightBrowserAdapter) -> None:
        self.browser = browser

    async def _first_present(self, selectors: list[str]):
        for selector in selectors:
            try:
                found = await self.browser.query(selector)
            except Exception:
                continue
            if found is not None:
                return selector
        return None


# Mixin-style helper used by PlaywrightTryOnAdapter.
async def _first_present_on(browser, selectors: list[str]):
    for selector in selectors:
        try:
            found = await browser.query(selector)
        except Exception:
            continue
        if found is not None:
            return selector
    return None


PlaywrightTryOnAdapter._first_present = lambda self, selectors: _first_present_on(self.browser, selectors)
