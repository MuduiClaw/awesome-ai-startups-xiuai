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


# ---------------------------------------------------------------------------
# Category mapping: AiBot category_slug → (schema category, sub_category)
# ---------------------------------------------------------------------------
_AIBOT_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "ai-agent": ("ai-chatbot-agent", "ai-agent"),
    "ai-search-engines": ("ai-search-retrieval", "ai-search"),
    "ai-productivity-tools": ("ai-productivity", "productivity"),
    "ai-content-detection-and-optimization-tools": (
        "ai-security-governance",
        "ai-content-detection",
    ),
    "ai-product-photo-generators": ("ai-image-design", "image-generation"),
    "ai-recruitment-and-job-search-tools": ("ai-hr-recruiting", "recruitment"),
    "ai-translation-tools": ("ai-translation", "translation"),
    "ai-mindmap-tools": ("ai-productivity", "mind-mapping"),
    "ai-meeting-tools": ("ai-productivity", "meeting-assistant"),
    "ai-3d-model-generation": ("ai-image-design", "3d-generation"),
    "ai-legal-assistants": ("ai-finance-legal", "legal"),
    "ai-finance-tools": ("ai-finance-legal", "finance-accounting"),
    "ai-document-tools": ("ai-productivity", "document-processing"),
}


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

    def scrape_raw(self, limit: int = 100) -> list[dict[str, object]]:
        """Return raw card dicts from ai-bot.cn category pages."""
        client = create_http_client()
        raw_items: list[dict[str, object]] = []
        seen_names: set[str] = set()

        try:
            category_urls = self._discover_categories(client)
            if not category_urls:
                logger.warning("aibot: no category URLs found in sitemap")
                return raw_items

            logger.info("aibot: found %d categories in sitemap", len(category_urls))

            for page_url, cat_slug in category_urls:
                if len(raw_items) >= limit:
                    break

                logger.debug("aibot: scraping %s", cat_slug)

                try:
                    response = client.get(page_url)
                    response.raise_for_status()
                except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
                    logger.debug("aibot %s failed: %s", cat_slug, exc)
                    time.sleep(DEFAULT_REQUEST_DELAY)
                    continue

                html_text = response.content.decode("utf-8", errors="replace")
                entries = _extract_cards(html_text)

                for name, product_url, description, icon_url in entries:
                    name = name.strip()
                    if not name or len(name) < 2 or len(name) > 80:
                        continue

                    name_lower = name.lower()
                    if name_lower in seen_names:
                        continue
                    seen_names.add(name_lower)

                    # Resolve internal URLs
                    if product_url and _INTERNAL_URL_RE.match(product_url):
                        resolved = _resolve_internal_url(client, product_url)
                        if resolved:
                            product_url = resolved

                    raw_items.append(
                        {
                            "name": name,
                            "product_url": product_url,
                            "description": description,
                            "icon_url": icon_url,
                            "category_slug": cat_slug,
                            "source_page": page_url,
                        }
                    )

                    if len(raw_items) >= limit:
                        break

                time.sleep(DEFAULT_REQUEST_DELAY)

        finally:
            client.close()

        logger.info("aibot: collected %d raw items", len(raw_items))
        return raw_items

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Scrape ai-bot.cn category pages for AI tool listings."""
        raw_items = self.scrape_raw(limit=limit)
        products: list[ScrapedProduct] = []

        for item in raw_items:
            name = str(item.get("name", ""))
            product_url = item.get("product_url")
            description = item.get("description")
            icon_url = item.get("icon_url")
            cat_slug = str(item.get("category_slug", ""))
            page_url = str(item.get("source_page", ""))

            name_zh = name if _has_chinese(name) else None
            desc_str = str(description) if description else None
            desc_zh = desc_str if desc_str and _has_chinese(desc_str) else None

            cat, sub = _AIBOT_CATEGORY_MAP.get(cat_slug, ("ai-chatbot-agent", None))

            products.append(
                ScrapedProduct(
                    name=name,
                    source=self.source_name,
                    source_url=page_url,
                    source_tier=SourceTier.T2_OPEN_WEB,
                    name_zh=name_zh,
                    product_url=str(product_url) if product_url else None,
                    description=desc_str,
                    description_zh=desc_zh,
                    icon_url=str(icon_url) if icon_url else None,
                    category=cat,
                    sub_category=sub,
                    tags=(cat_slug,),
                    status="active",
                )
            )

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
