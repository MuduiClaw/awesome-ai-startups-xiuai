"""Discover TAAFT internal API endpoints via Playwright network interception.

Phase 1 of the TAAFT full-crawl migration: launch a stealth browser,
navigate to theresanaiforthat.com pages, and intercept all XHR/fetch
requests to identify internal API endpoints and their response schemas.

Uses raw Playwright (not BrowserClient) because we need ``page.on()``
hooks for request/response interception before navigation.

Usage::

    python scripts/discover_taaft_api.py
    python scripts/discover_taaft_api.py --headed   # visible browser

Requires: ``pip install playwright playwright-stealth``
Then:     ``playwright install chromium``
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

_BASE_URL = "https://theresanaiforthat.com"

# Pages to visit — homepage + two category pages to observe both global
# and category-specific API calls.
_PAGES_TO_VISIT = [
    "/",
    "/s/chatbots",
    "/s/text-generators",
]

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# How many scroll-down actions per page to trigger lazy loading.
_SCROLL_COUNT = 5
_SCROLL_DELAY_MS = 2000

# How long to wait after initial page load (Cloudflare challenge).
_CF_WAIT_MS = 8000
_CF_RETRY_WAIT_MS = 10000


@dataclass
class ApiEndpoint:
    """A discovered network request with metadata."""

    url: str
    method: str
    resource_type: str
    triggered_by: str = ""  # which page triggered this request
    status: int = 0
    content_type: str = ""
    response_preview: str = ""
    query_params: dict[str, str | list[str]] = field(default_factory=dict)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover TAAFT API endpoints")
    parser.add_argument(
        "--headed", action="store_true", help="Run browser in headed mode (visible)"
    )
    args = parser.parse_args()

    try:
        from playwright.sync_api import Request, Response, sync_playwright
        from playwright_stealth import Stealth
    except ImportError:
        print("ERROR: playwright and playwright-stealth are required.")
        print("  pip install playwright playwright-stealth")
        print("  playwright install chromium")
        sys.exit(1)

    endpoints: list[ApiEndpoint] = []
    seen_urls: set[str] = set()
    current_page_path: str = ""

    def on_request(request: Request) -> None:
        if request.resource_type not in ("xhr", "fetch"):
            return
        url = request.url
        if url in seen_urls:
            return
        seen_urls.add(url)

        parsed = urlparse(url)
        params: dict[str, str | list[str]] = {}
        for k, v in parse_qs(parsed.query).items():
            params[k] = v[0] if len(v) == 1 else v

        endpoints.append(
            ApiEndpoint(
                url=url,
                method=request.method,
                resource_type=request.resource_type,
                triggered_by=current_page_path,
                query_params=params,
            )
        )

    def on_response(response: Response) -> None:
        url = response.url
        for ep in endpoints:
            if ep.url == url and ep.status == 0:
                ep.status = response.status
                ep.content_type = response.headers.get("content-type", "")
                if "json" in ep.content_type:
                    try:
                        body = response.json()
                        preview = json.dumps(body, indent=2, ensure_ascii=False)
                        if len(preview) > 3000:
                            preview = preview[:3000] + "\n... (truncated)"
                        ep.response_preview = preview
                    except Exception:
                        ep.response_preview = "(failed to parse JSON)"
                break

    print(f"{'=' * 60}")
    print("TAAFT API Endpoint Discovery")
    print(f"{'=' * 60}\n")

    headless = not args.headed
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=_BROWSER_UA,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        Stealth().apply_stealth_sync(ctx)
        page = ctx.new_page()

        page.on("request", on_request)
        page.on("response", on_response)

        for page_path in _PAGES_TO_VISIT:
            current_page_path = page_path
            url = f"{_BASE_URL}{page_path}"
            print(f"[*] Visiting: {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(_CF_WAIT_MS)

                title = page.title()
                # Sanitize title for console output (avoid GBK encoding errors)
                safe_title = title.encode("ascii", errors="replace").decode("ascii")
                if "just a moment" in title.lower():
                    print(
                        f"    WARNING: Cloudflare challenge pending (title: {safe_title})"
                    )
                    page.wait_for_timeout(_CF_RETRY_WAIT_MS)
                    title = page.title()
                    safe_title = title.encode("ascii", errors="replace").decode("ascii")

                print(f"    Page loaded (title: {safe_title})")

                # Scroll to trigger lazy loading / infinite scroll
                for i in range(_SCROLL_COUNT):
                    page.evaluate("window.scrollBy(0, window.innerHeight)")
                    page.wait_for_timeout(_SCROLL_DELAY_MS)
                    print(f"    Scrolled {i + 1}/{_SCROLL_COUNT}")

            except Exception as exc:
                print(f"    ERROR: {exc}")

            print()

        browser.close()

    # ---- Report ----

    print(f"\n{'=' * 60}")
    print(f"DISCOVERED ENDPOINTS ({len(endpoints)} total)")
    print(f"{'=' * 60}\n")

    # Partition: same-origin vs external
    same_origin = [ep for ep in endpoints if _BASE_URL in ep.url]
    external = [ep for ep in endpoints if _BASE_URL not in ep.url]

    if same_origin:
        print(f"--- Same-origin API calls ({len(same_origin)}) ---\n")
        for ep in same_origin:
            # Strip base URL for readability
            path = ep.url.replace(_BASE_URL, "")
            print(f"  {ep.method} {path}")
            print(f"    Triggered by: {ep.triggered_by}")
            print(f"    Status: {ep.status}  Content-Type: {ep.content_type}")
            if ep.query_params:
                print(f"    Params: {json.dumps(ep.query_params)}")
            if ep.response_preview:
                lines = ep.response_preview.split("\n")[:15]
                print("    Response preview:")
                for line in lines:
                    print(f"      {line}")
            print()

    if external:
        print(f"\n--- External calls ({len(external)}) ---\n")
        for ep in external:
            # Truncate long URLs (analytics, etc.)
            display_url = ep.url[:120] + ("..." if len(ep.url) > 120 else "")
            print(f"  {ep.method} {display_url}")
            print(f"    Status: {ep.status}  Type: {ep.content_type}")
            print()

    # Summary: highlight likely API endpoints (JSON responses from same origin)
    json_apis = [ep for ep in same_origin if "json" in ep.content_type]
    if json_apis:
        print(f"\n{'=' * 60}")
        print(f"LIKELY API ENDPOINTS ({len(json_apis)} JSON responses)")
        print(f"{'=' * 60}\n")
        for ep in json_apis:
            path = ep.url.replace(_BASE_URL, "").split("?")[0]
            print(f"  {ep.method} {path}")
            if ep.query_params:
                print(f"    Params: {json.dumps(ep.query_params)}")
            # Show response keys if it's an object
            if ep.response_preview:
                try:
                    body = json.loads(
                        ep.response_preview.replace("\n... (truncated)", "")
                    )
                    if isinstance(body, dict):
                        print(f"    Top-level keys: {list(body.keys())[:10]}")
                        # Check for pagination fields
                        for key in (
                            "total",
                            "last_page",
                            "per_page",
                            "current_page",
                            "data",
                        ):
                            if key in body:
                                val = body[key]
                                if isinstance(val, list):
                                    print(f"    {key}: list[{len(val)} items]")
                                    if val:
                                        first = val[0]
                                        if isinstance(first, dict):
                                            print(
                                                f"    Item keys: {list(first.keys())[:10]}"
                                            )
                                else:
                                    print(f"    {key}: {val}")
                    elif isinstance(body, list):
                        print(f"    Array with {len(body)} items")
                        if body and isinstance(body[0], dict):
                            print(f"    Item keys: {list(body[0].keys())[:10]}")
                except (json.JSONDecodeError, KeyError):
                    pass
            print()
    else:
        print("\nNo JSON API endpoints discovered from same origin.")
        print("The site may use SSR, GraphQL, or embed data in HTML.")
        print("Consider the HTML fallback approach.")


if __name__ == "__main__":
    main()
