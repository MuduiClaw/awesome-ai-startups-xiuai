"""AI工具集 (ai-bot.cn) scraper for Chinese AI product discovery.

T2 Open Web — Chinese AI tool directory with 1000+ tools.
Dynamically discovers all /favorites/ category pages from sitemap.xml,
then scrapes each page for product cards. No API key required.
"""

from __future__ import annotations

import html as html_mod
import logging
import re
import time

import httpx

from scrapers.base import BaseScraper, ScrapedProduct, SourceTier
from scrapers.config import DEFAULT_REQUEST_DELAY
from scrapers.utils import create_http_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://ai-bot.cn"
_SITEMAP_URL = f"{_BASE_URL}/sitemap.xml"

# Aggregation / "best-of" pages that duplicate content from real categories.
_SKIP_SLUGS = frozenset(
    {
        "best-ai-tools",
        "best-ai-image-tools",
        "popular-ai-office-tools",
    }
)

# Card regex — matches the url-card structure used by ai-bot.cn (OneNav theme):
#   <a ... data-url="PRODUCT_URL" ... title="DESCRIPTION" ...>
#     <img ... data-src="ICON_URL" ... alt="NAME">
#     <strong>NAME</strong>
#     <p ...>DESCRIPTION</p>
#   </a>
_CARD_PATTERN = re.compile(
    r"<a[^>]*"
    r'data-url="([^"]+)"[^>]*'  # group 1: product URL (data-url)
    r'title="([^"]*)"[^>]*>'  # group 2: description (title attr)
    r".*?"
    r'data-src="([^"]+)"'  # group 3: icon URL (lazy-loaded img)
    r".*?"
    r"<strong>([^<]+)</strong>"  # group 4: product name
    r".*?"
    r"<p[^>]*>([^<]*)</p>",  # group 5: short description (p tag)
    re.DOTALL,
)

# Domains to skip when resolving official URL from internal detail pages.
_FOOTER_DOMAINS = frozenset(
    {
        "beian.miit.gov.cn",
        "beian.gov.cn",
        "ghxi.com",
        "aisharenet.com",
        "gongke.net",
        "yjpoo.com",
    }
)

# Pattern to detect ai-bot.cn internal detail pages.
_INTERNAL_URL_RE = re.compile(r"^https?://ai-bot\.cn/sites/\d+\.html$")


class AiBotScraper(BaseScraper):
    """Scrape ai-bot.cn for Chinese AI product discovery.

    Workflow:
    1. Fetch sitemap.xml to discover all /favorites/ category URLs.
    2. Iterate each category page, extract product cards via regex.
    3. For cards with internal URLs, follow the detail page to resolve
       the real official product URL.
    4. Emit ScrapedProduct for each unique product found.
    """

    @property
    def source_name(self) -> str:
        return "aibot"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Scrape ai-bot.cn category pages for AI tool listings."""
        client = create_http_client()
        products: list[ScrapedProduct] = []
        seen_names: set[str] = set()

        try:
            category_urls = self._discover_categories(client)
            if not category_urls:
                logger.warning("aibot: no category URLs found in sitemap")
                return products

            logger.info("aibot: found %d categories in sitemap", len(category_urls))

            for page_url, cat_slug in category_urls:
                if len(products) >= limit:
                    break

                logger.debug("aibot: scraping %s", cat_slug)

                try:
                    response = client.get(page_url)
                    response.raise_for_status()
                except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
                    logger.debug("aibot %s failed: %s", cat_slug, exc)
                    time.sleep(DEFAULT_REQUEST_DELAY)
                    continue

                html = response.content.decode("utf-8", errors="replace")
                parsed = self._parse_listing(client, html, cat_slug, page_url)

                for product in parsed:
                    name_lower = product.name.lower()
                    if name_lower in seen_names:
                        continue
                    seen_names.add(name_lower)
                    products.append(product)

                    if len(products) >= limit:
                        break

                time.sleep(DEFAULT_REQUEST_DELAY)

        finally:
            client.close()

        logger.info("aibot: discovered %d products", len(products))
        return products

    def _discover_categories(self, client: httpx.Client) -> list[tuple[str, str]]:
        """Fetch sitemap.xml and extract all /favorites/ category URLs.

        Returns list of (full_url, slug) tuples, excluding aggregation pages.
        """
        try:
            response = client.get(_SITEMAP_URL)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
            logger.warning("aibot: sitemap fetch failed: %s", exc)
            return []

        text = response.text
        urls: list[tuple[str, str]] = []
        seen: set[str] = set()

        for match in re.finditer(
            r"<loc>\s*(https?://ai-bot\.cn/favorites/([a-z0-9\-]+)/?)\s*</loc>",
            text,
        ):
            full_url = match.group(1)
            slug = match.group(2)

            if slug in seen or slug in _SKIP_SLUGS:
                continue
            seen.add(slug)

            # Ensure URL has trailing slash for consistency
            if not full_url.endswith("/"):
                full_url += "/"

            urls.append((full_url, slug))

        return urls

    def _parse_listing(
        self, client: httpx.Client, html: str, cat_slug: str, page_url: str
    ) -> list[ScrapedProduct]:
        """Parse an ai-bot.cn category listing page into ScrapedProduct list."""
        if not html or len(html) < 200:
            return []

        entries = _extract_cards(html)
        products: list[ScrapedProduct] = []

        for name, product_url, description, icon_url in entries:
            name = name.strip()
            if not name or len(name) < 2 or len(name) > 80:
                continue

            # Resolve internal URLs by following the detail page
            if product_url and _INTERNAL_URL_RE.match(product_url):
                resolved = _resolve_internal_url(client, product_url)
                if resolved:
                    product_url = resolved

            name_zh = name if _has_chinese(name) else None
            desc_zh = description if description and _has_chinese(description) else None

            products.append(
                ScrapedProduct(
                    name=name,
                    source=self.source_name,
                    source_url=page_url,
                    source_tier=SourceTier.T2_OPEN_WEB,
                    name_zh=name_zh,
                    product_url=product_url or None,
                    description=description or None,
                    description_zh=desc_zh,
                    icon_url=icon_url or None,
                    tags=(cat_slug,),
                    status="active",
                )
            )

        return products


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_cards(html: str) -> list[tuple[str, str, str, str]]:
    """Extract (name, product_url, description, icon_url) from card HTML."""
    entries: list[tuple[str, str, str, str]] = []
    seen_urls: set[str] = set()

    for match in _CARD_PATTERN.finditer(html):
        raw_url = html_mod.unescape(match.group(1)).strip()
        title_desc = html_mod.unescape(match.group(2)).strip()
        icon_url = match.group(3).strip()
        name = html_mod.unescape(match.group(4)).strip()
        p_desc = html_mod.unescape(match.group(5)).strip()

        if not name or raw_url in seen_urls:
            continue
        seen_urls.add(raw_url)

        # Prefer the <p> description; fall back to title attribute
        description = p_desc if p_desc else title_desc

        # Strip tracking params from URLs
        product_url = _clean_url(raw_url)

        entries.append((name, product_url, description, icon_url))

    return entries


def _resolve_internal_url(client: httpx.Client, internal_url: str) -> str | None:
    """Follow an ai-bot.cn /sites/ detail page to find the official product URL.

    The detail page contains outbound links; the first non-footer external
    href is typically the product's official website.
    """
    try:
        response = client.get(internal_url)
        response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
        logger.debug("aibot: failed to resolve %s: %s", internal_url, exc)
        return None

    html = response.content.decode("utf-8", errors="replace")

    # Find all external hrefs (non ai-bot.cn)
    externals = re.findall(r'href="(https?://(?!ai-bot\.cn)[^"]+)"', html)

    for url in externals:
        url = html_mod.unescape(url).strip()
        # Skip footer/utility domains
        if any(domain in url for domain in _FOOTER_DOMAINS):
            continue
        return _clean_url(url)

    return None


def _clean_url(url: str) -> str:
    """Remove common tracking query params (channel, source, utm_*, etc.).

    Also handles malformed URLs with multiple ``?`` characters.
    """
    # Fix double-? URLs: keep only the first ?, turn subsequent ? into &
    parts = url.split("?")
    if len(parts) > 2:
        url = parts[0] + "?" + "&".join(parts[1:])

    if "?" not in url:
        return url

    base, _, query = url.partition("?")
    params = query.split("&")
    clean = [
        p
        for p in params
        if not re.match(
            r"(channel|source|source_id|utm_\w+|type|theme|ref|from)=",
            p,
            re.IGNORECASE,
        )
    ]
    return f"{base}?{'&'.join(clean)}" if clean else base


def _has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))
