"""Headless-browser renderer for block-based slides: HTML -> PNG.

Launches Chromium through Playwright, renders each slide document and refuses
to save a slide whose content still overflows the canvas after the built-in
auto-fit has shrunk it. Words are never cropped: an overflowing slide raises
instead of producing a broken image.
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_LAUNCH_ARGS = ("--no-sandbox", "--disable-dev-shm-usage", "--force-color-profile=srgb")


def find_chromium_executable() -> Optional[str]:
    """Locate a usable Chromium: explicit env first, then known locations."""
    candidates = [
        (os.getenv("SLIDE_RENDERER_EXECUTABLE") or "").strip(),
        (os.getenv("CHROME_BIN") or "").strip(),
        "/usr/bin/chromium-headless-shell",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("chromium-headless-shell") or shutil.which("chromium") or shutil.which("google-chrome")
    return found


class HtmlSlideRenderer:
    """Context manager: one browser instance renders any number of slides."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "HtmlSlideRenderer":
        from playwright.sync_api import sync_playwright

        executable = find_chromium_executable()
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                args=list(_LAUNCH_ARGS),
            )
        except Exception:
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        for closable in (self._browser, self._playwright):
            try:
                if closable:
                    closable.close() if closable is self._browser else closable.stop()
            except Exception:
                logger.warning("Failed to close slide renderer cleanly", exc_info=True)
        self._page = None
        self._browser = None
        self._playwright = None

    def _ensure_page(self, width: int, height: int):
        if self._page is None:
            if self._browser is None:
                raise RuntimeError("HtmlSlideRenderer не запущен: используй оператор with")
            self._page = self._browser.new_page(
                viewport={"width": int(width), "height": int(height)},
                device_scale_factor=1,
            )
        return self._page

    def render_html(self, html: str, output_path: str, width: int, height: int) -> None:
        """Render one slide document and save it as PNG; raises on overflow."""
        page = self._ensure_page(width, height)
        page.set_viewport_size({"width": int(width), "height": int(height)})
        try:
            page.set_content(html, wait_until="load")
        except Exception as exc:
            raise RuntimeError(f"Рендер слайда не удался: {exc}") from exc
        try:
            page.evaluate("() => document.fonts.ready")
            status = page.evaluate("() => document.documentElement.dataset.fitStatus || 'ok'")
        except Exception as exc:
            raise RuntimeError(f"Не удалось проверить слайд на переполнение: {exc}") from exc
        if status == "overflow":
            index = page.evaluate(
                "() => { const bad = document.querySelector('.slide[data-fit=\\'overflow\\']');"
                " return bad ? bad.dataset.index : ''; }"
            )
            raise RuntimeError(
                f"Слайд {index}: текст не помещается даже после авто-подгонки — сократи текст"
            )
        screenshot = page.screenshot(type="png", clip={"x": 0, "y": 0, "width": int(width), "height": int(height)})
        self._save_png(screenshot, output_path)

    @staticmethod
    def _save_png(content: bytes, output_path: str) -> str:
        if not content.startswith(_PNG_MAGIC):
            raise RuntimeError("Рендер вернул не PNG")
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
        return str(destination)
