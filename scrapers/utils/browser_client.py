"""Playwright browser client with stealth mode for Cloudflare bypass.

Provides a reusable context-manager class that:
  1. Launches headless Chromium with anti-fingerprinting patches.
  2. Navigates to a seed URL to clear Cloudflare challenges.
  3. Exposes ``fetch_json()`` to call same-origin APIs via
     ``page.evaluate(fetch(...))``, inheriting session cookies.
  4. Provides ``navigate()`` and ``scroll_and_collect()`` for HTML-based
     scraping of infinite-scroll pages.

Requires optional dependencies: ``playwright`` and ``playwright-stealth``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from scrapers.config import DEFAULT_REQUEST_DELAY, MAX_RETRIES

logger = logging.getLogger(__name__)

# Chrome-like UA — project USER_AGENT triggers Cloudflare blocks.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class BrowserClientError(Exception):
    """A browser operation failed after all retries."""


class BrowserClient:
    """Playwright stealth browser session for Cloudflare-protected sites.

    Usage::

        with BrowserClient("https://www.example.com/any-page") as client:
            data = client.fetch_json("/api/v1/items?page=1")
            print(data)

    The seed URL is loaded once to establish a valid Cloudflare session.
    Subsequent ``fetch_json`` calls use the browser's cookies automatically.
    """

    def __init__(self, seed_url: str, *, headless: bool = True) -> None:
        self._seed_url = seed_url
        self._headless = headless
        self._pw: Any = None
        self._browser: Any = None
        self._page: Any = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> BrowserClient:
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
        except ImportError as exc:
            raise BrowserClientError(
                "playwright and playwright-stealth are required. "
                "Install with: pip install -e '.[browser]'"
            ) from exc

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        ctx = self._browser.new_context(
            user_agent=_BROWSER_UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        Stealth().apply_stealth_sync(ctx)
        self._page = ctx.new_page()

        # Navigate to seed URL to clear Cloudflare challenge.
        logger.debug("BrowserClient: loading seed URL %s", self._seed_url)
        self._page.goto(self._seed_url, wait_until="domcontentloaded", timeout=45_000)
        self._page.wait_for_timeout(8_000)

        title = self._page.title()
        if "just a moment" in title.lower():
            raise BrowserClientError(
                f"Cloudflare challenge not cleared (page title: {title!r})"
            )

        logger.debug("BrowserClient: session established (title: %s)", title)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()
        self._page = None
        self._browser = None
        self._pw = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_json(self, path: str) -> dict[str, Any]:
        """Fetch a same-origin JSON endpoint via the browser session.

        Args:
            path: Relative path (e.g. ``/self-api/v1/tools?page=1``).

        Returns:
            Parsed JSON response body.

        Raises:
            BrowserClientError: On network failure or non-200 status.
        """
        if self._page is None:
            raise BrowserClientError("BrowserClient is not open")

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                result: dict[str, Any] = self._page.evaluate(
                    """async (path) => {
                        const r = await fetch(path);
                        if (!r.ok) return {__error: true, status: r.status, text: await r.text()};
                        return await r.json();
                    }""",
                    path,
                )

                if isinstance(result, dict) and result.get("__error"):
                    status = result.get("status", 0)
                    if status == 429:
                        wait = min(60 * (2**attempt), 300)
                        logger.warning("Rate limited on %s, waiting %ds", path, wait)
                        time.sleep(wait)
                        continue
                    raise BrowserClientError(
                        f"API error {status} for {path}: {str(result.get('text', ''))[:200]}"
                    )

                return result

            except BrowserClientError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    delay = DEFAULT_REQUEST_DELAY * (2**attempt)
                    logger.debug(
                        "fetch_json retry %d for %s: %s", attempt + 1, path, exc
                    )
                    time.sleep(delay)

        raise BrowserClientError(
            f"Failed after {MAX_RETRIES} attempts for {path}"
        ) from last_error

    def fetch_text(self, path: str) -> str:
        """Fetch a same-origin endpoint and return the response as text.

        Useful for APIs that return HTML fragments (HTMX-style) rather
        than JSON.

        Args:
            path: Relative path (e.g. ``/api/featured/?max_featured_items=100``).

        Returns:
            Response body as a string.

        Raises:
            BrowserClientError: On network failure or non-200 status.
        """
        if self._page is None:
            raise BrowserClientError("BrowserClient is not open")

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                result: dict[str, Any] = self._page.evaluate(
                    """async (path) => {
                        const r = await fetch(path);
                        if (!r.ok) return {__error: true, status: r.status};
                        return {__text: await r.text()};
                    }""",
                    path,
                )

                if isinstance(result, dict) and result.get("__error"):
                    status = result.get("status", 0)
                    if status == 429:
                        wait = min(60 * (2**attempt), 300)
                        logger.warning("Rate limited on %s, waiting %ds", path, wait)
                        time.sleep(wait)
                        continue
                    raise BrowserClientError(f"API error {status} for {path}")

                text: str = result.get("__text", "")
                return text

            except BrowserClientError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    delay = DEFAULT_REQUEST_DELAY * (2**attempt)
                    logger.debug(
                        "fetch_text retry %d for %s: %s", attempt + 1, path, exc
                    )
                    time.sleep(delay)

        raise BrowserClientError(
            f"Failed after {MAX_RETRIES} attempts for {path}"
        ) from last_error

    def navigate(self, url: str, *, wait_until: str = "domcontentloaded") -> None:
        """Navigate the browser to a new URL within the existing session.

        Unlike the constructor's seed URL, this does not re-check for
        Cloudflare challenges — the session cookies are already set.

        Args:
            url: Full URL or same-origin path to navigate to.
            wait_until: Playwright load state (default ``domcontentloaded``).

        Raises:
            BrowserClientError: If the page is not open or navigation fails.
        """
        if self._page is None:
            raise BrowserClientError("BrowserClient is not open")

        try:
            self._page.goto(url, wait_until=wait_until, timeout=45_000)
        except Exception as exc:
            raise BrowserClientError(f"Navigation to {url} failed: {exc}") from exc

    def scroll_and_collect(
        self,
        *,
        max_scrolls: int = 20,
        scroll_delay_ms: int = 2000,
        idle_threshold: int = 3,
    ) -> str:
        """Scroll the current page to trigger infinite loading, return HTML.

        Scrolls to the bottom of the page repeatedly, waiting for new
        content to load. Stops when the page height stops changing for
        ``idle_threshold`` consecutive scrolls or ``max_scrolls`` is reached.

        Args:
            max_scrolls: Maximum number of scroll-to-bottom actions.
            scroll_delay_ms: Milliseconds to wait between scrolls.
            idle_threshold: Stop after this many scrolls with no height change.

        Returns:
            Full page HTML after scrolling completes.

        Raises:
            BrowserClientError: If the page is not open.
        """
        if self._page is None:
            raise BrowserClientError("BrowserClient is not open")

        max_allowed = 100
        if max_scrolls > max_allowed:
            logger.warning(
                "scroll_and_collect: capping max_scrolls from %d to %d",
                max_scrolls,
                max_allowed,
            )
            max_scrolls = max_allowed

        idle_count = 0
        prev_height: int = 0

        for i in range(max_scrolls):
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(scroll_delay_ms)

            current_height: int = self._page.evaluate("document.body.scrollHeight")
            if current_height == prev_height:
                idle_count += 1
                if idle_count >= idle_threshold:
                    logger.debug(
                        "scroll_and_collect: no new content after %d idle scrolls "
                        "(total scrolls: %d)",
                        idle_threshold,
                        i + 1,
                    )
                    break
            else:
                idle_count = 0
            prev_height = current_height

        return self.get_page_html()

    def get_page_html(self) -> str:
        """Return the current page's full HTML content.

        Raises:
            BrowserClientError: If the page is not open.
        """
        if self._page is None:
            raise BrowserClientError("BrowserClient is not open")

        html: str = self._page.content()
        return html
