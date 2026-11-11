"""Try-on application boundary. Web uses Playwright. Desktop is reserved."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from app.adapters.browser_adapter import PlaywrightBrowserAdapter
from app.cv.visualization import image_from_bytes, save_catalog_sprite
from app.adapters.earring_anchor_adapter import EarringAnchorPageAdapter
from app.adapters.screenshot_adapter import ScreenshotAdapter
from app.core.logging import log_event
from app.models.application import Application
from app.services.frame_selector import RawFrame

USERNAME_SELECTORS = [
    "input[type='email']",
    "input[name='username']",
    "input[name='email']",
    "input[id='username']",
    "input[id='email']",
    "input[autocomplete='username']",
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
        password_selector = await self._wait_present(
            _split(self.application.password_selector) or PASSWORD_SELECTORS,
            timeout_ms=12000,
        )
        if password_selector is None:
            log_event("AUTHENTICATION_SUCCESS", detail="No password field was present.")
            return
        username_selector = await self._wait_present(
            _split(self.application.username_selector) or USERNAME_SELECTORS,
            timeout_ms=3000,
        )
        if username_selector is None:
            raise TryOnError(
                "Authentication failed. A password field was found, but the username field was not.",
                "AUTH_FAILED",
                "Set a username selector in the application configuration.",
            )
        await self.browser.fill(username_selector, self.username)
        await self.browser.fill(password_selector, self.password)
        submit_selector = await self._wait_present(
            _split(self.application.submit_selector) or SUBMIT_SELECTORS,
            timeout_ms=3000,
        )
        if submit_selector is None:
            raise TryOnError(
                "Authentication failed. The login submit control was not found.",
                "AUTH_FAILED",
                "Set a submit selector in the application configuration.",
            )
        await self.browser.click(submit_selector)
        for _ in range(20):
            await self.browser.wait_for_timeout(500)
            try:
                still_login = await self.browser.query("input[type='password']")
            except Exception:
                still_login = None
            if still_login is None:
                log_event("AUTHENTICATION_SUCCESS")
                return
        raise TryOnError(
            "Authentication failed.",
            "AUTH_FAILED",
            "Check the username, password, and login selectors. The password was not logged.",
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
            await self._open_storefront_tryon()
        else:
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

    async def _open_storefront_tryon(self) -> None:
        """New Amplify dump opens try-on from a Try ON button into an embedded iframe."""
        await self._dismiss_overlays()
        opened = await self.browser.evaluate(
            """() => {
              const cards = [...document.querySelectorAll('article.card')];
              const earring = cards.find((card) => /earring/i.test(card.innerText || ''));
              const card = earring || cards[0];
              const cardButton = card && card.querySelector('button.try-on');
              if (cardButton) {
                cardButton.click();
                return 'card';
              }
              const header = document.querySelector('button.header-try-on');
              if (header) {
                header.click();
                return 'header';
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

    async def _wait_for_canvas(self, timeout_ms: int) -> bool:
        elapsed = 0
        retried_storefront = False
        while elapsed <= timeout_ms:
            await self._leave_photo_matching()
            ready = await self.browser.evaluate(
                """() => {
                  const text = document.body.innerText || '';
                  if (text.includes('Loading try-on')) return false;
                  const frames = [...document.querySelectorAll('iframe')];
                  const hasFrame = frames.some((frame) => {
                    const src = (frame.getAttribute('src') || '').toLowerCase();
                    if (src.includes('advertisement')) return false;
                    const box = frame.getBoundingClientRect();
                    return box.width > 80 && box.height > 80;
                  });
                  if (hasFrame) return true;
                  return [...document.querySelectorAll('video, canvas')].some((node) => {
                    const box = node.getBoundingClientRect();
                    return box.width > 80 && box.height > 80;
                  });
                }"""
            )
            if ready:
                # Storefront may show "Starting try-on…" briefly while the iframe boots.
                await self.browser.wait_for_timeout(1500)
                return True
            if not retried_storefront and elapsed >= 3000 and await self._is_storefront():
                retried_storefront = True
                await self._open_storefront_tryon()
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
        if await self._is_storefront():
            return await self._select_storefront_jewelry(jewelry_id, jewelry_type=jewelry_type)
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
        await self.browser.wait_for_timeout(4000)
        still_matching = await self.browser.evaluate(
            """() => {
              const text = document.body.innerText || '';
              return text.includes('No matching jewelry') || text.includes('Try All Categories');
            }"""
        )
        if still_matching:
            raise TryOnError(
                f"The try-on page stayed on photo matching after the catalog {pattern} was selected.",
                "JEWELRY_NOT_FOUND",
                "Leave AI Recommendations closed and keep Show All Category selected.",
            )
        return f"Selected catalogue {pattern} {selected}."

    async def _select_storefront_jewelry(self, jewelry_id: str | None, jewelry_type: str | None = None) -> str:
        jewelry_type = (jewelry_type or self.jewelry_type or "earring").lower()
        pattern = self._catalog_name_pattern(jewelry_type)
        await self.browser.evaluate(
            """() => {
              const close = [...document.querySelectorAll('button')].find(
                (node) => (node.innerText || '').trim().toLowerCase() === 'close'
              );
              if (close) close.click();
            }"""
        )
        await self.browser.wait_for_timeout(500)
        wanted = (jewelry_id or "").strip().lower()
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
        await self.browser.wait_for_timeout(3000)
        if not await self._wait_for_canvas(timeout_ms=30000):
            raise TryOnError(
                "The storefront try-on did not open after the jewelry was selected.",
                "APPLICATION_NOT_READY",
                "Click Try ON on the chosen jewelry and wait for the camera view.",
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

    async def capture(self) -> list[RawFrame]:
        log_event("CAPTURE_STARTED", fps=self.fps, duration_seconds=self.duration_seconds)
        await self._dismiss_overlays()
        await self._wait_for_tryon_view()
        blocked = await self.browser.evaluate(
            """() => {
              const text = document.body.innerText || '';
              if (text.includes('Loading try-on')) return 'loading';
              if (text.includes('No matching jewelry') || text.includes('Try All Categories')) return 'photo-match';
              return '';
            }"""
        )
        if blocked == "photo-match":
            raise TryOnError(
                "Capture stopped because the page was matching the face photo instead of showing a catalog earring.",
                "JEWELRY_NOT_FOUND",
                "Open Show All Category and select the catalog earring before capture.",
            )
        if blocked == "loading":
            raise TryOnError(
                "The try-on view was still loading, so the catalog earring was not measured.",
                "APPLICATION_NOT_READY",
                "Wait until the try-on face is visible, then run the test again.",
            )
        frame_dir = self.output_dir / "captured"
        frame_dir.mkdir(parents=True, exist_ok=True)
        interval_ms = max(1, int(round(1000 / self.fps)))
        total = max(1, int(self.duration_seconds * self.fps))
        frames: list[RawFrame] = []
        for index in range(total):
            path = frame_dir / f"frame_{index:04d}.png"
            await self.screenshots.capture(path)
            await self.live_overlay.update(path)
            state = await self.get_earring_anchor()
            frames.append(RawFrame(index=index, timestamp_ms=index * interval_ms, path=path, debug_state=state))
            if index < total - 1:
                await self.browser.wait_for_timeout(interval_ms)
        if self.live_overlay.shown:
            await self.browser.wait_for_timeout(1500)
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

    async def get_earring_anchor(self) -> dict | None:
        return await self.anchors.read_state()

    async def close(self) -> None:
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
