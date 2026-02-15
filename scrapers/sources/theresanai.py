"""There's An AI For That (TAAFT) scraper via BrowserClient + internal API.

T2 Open Web — one of the largest AI product directories with 14,000+
tools. Uses Playwright stealth to bypass Cloudflare, then paginates
TAAFT's internal API for structured JSON product data.

Falls back to HTML scroll-and-parse if the API endpoint is unreachable.

Requires optional dependencies: ``playwright``, ``playwright-stealth``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from scrapers.base import BaseScraper, DiscoveredProduct, ScrapedProduct, SourceTier
from scrapers.config import DEFAULT_REQUEST_DELAY

if TYPE_CHECKING:
    from scrapers.utils.browser_client import BrowserClient

logger = logging.getLogger(__name__)

_BASE_URL = "https://theresanaiforthat.com"
_SEED_URL = f"{_BASE_URL}/s/chatbots"

# ---------------------------------------------------------------------------
# Internal HTML API configuration
# ---------------------------------------------------------------------------
# Discovered via scripts/discover_taaft_api.py:
# TAAFT uses an HTMX-style API that returns HTML fragments, not JSON.
# /api/featured/ returns <li> elements with data-* attributes containing
# tool data (name, url, category, id). The category context is set by
# navigating to a category page first, then calling the API.

_FEATURED_API = "/api/featured/?sfb=1&max_featured_items={limit}"
_MAX_FEATURED_PER_CATEGORY = 1000  # Server may return fewer

# ---------------------------------------------------------------------------
# Category pages for HTML fallback
# ---------------------------------------------------------------------------

_CATEGORY_URLS = [
    "/s/text-generators",
    "/s/image-generators",
    "/s/video-generators",
    "/s/code-assistants",
    "/s/chatbots",
    "/s/writing-assistants",
    "/s/marketing",
    "/s/productivity",
    "/s/music-generators",
    "/s/search-engines",
    "/s/data-analysis",
    "/s/education",
    "/s/design",
    "/s/developer-tools",
    "/s/customer-support",
    "/s/healthcare",
    "/s/finance",
    "/s/legal",
    "/s/speech",
    "/s/audio",
    "/s/3d",
    "/s/robotics",
    "/s/autonomous-vehicles",
    "/s/cybersecurity",
    "/s/gaming",
]

# ---------------------------------------------------------------------------
# Category mapping: TAAFT slug -> project schema category
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, str] = {
    # Creative & media
    "image-generators": "ai-creative-media",
    "video-generators": "ai-creative-media",
    "music-generators": "ai-creative-media",
    "design": "ai-creative-media",
    "3d": "ai-creative-media",
    "audio": "ai-creative-media",
    "speech": "ai-creative-media",
    "gaming": "ai-creative-media",
    # Text generation — TAAFT's broadest category, mostly apps not models.
    # Actual LLMs are refined via task_slug keyword matching.
    "text-generators": "ai-application",
    # Applications
    "chatbots": "ai-application",
    "writing-assistants": "ai-application",
    "marketing": "ai-application",
    "productivity": "ai-application",
    "customer-support": "ai-application",
    "education": "ai-application",
    # Developer tools
    "code-assistants": "ai-dev-platform",
    "developer-tools": "ai-dev-platform",
    # Data & analytics
    "data-analysis": "ai-data-platform",
    # Search
    "search-engines": "ai-search-retrieval",
    # Hardware
    "robotics": "ai-hardware",
    "autonomous-vehicles": "ai-hardware",
    # Security
    "cybersecurity": "ai-security-governance",
    # Verticals
    "healthcare": "ai-science-research",
    "finance": "ai-enterprise-vertical",
    "legal": "ai-enterprise-vertical",
}

# Keyword fallback rules for unmapped categories.
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("image", "video", "photo", "design", "art", "music", "audio", "3d", "voice"),
        "ai-creative-media",
    ),
    (
        ("code", "developer", "programming", "devops", "api", "no-code"),
        "ai-dev-platform",
    ),
    (("data", "analytics", "database"), "ai-data-platform"),
    (("search", "retrieval", "summariz"), "ai-search-retrieval"),
    (("security", "safety", "detector", "moderation"), "ai-security-governance"),
    (
        ("healthcare", "medical", "science", "research", "biology", "chemistry"),
        "ai-science-research",
    ),
    (("llm", "model", "language-model", "foundation"), "ai-foundation-model"),
    (
        ("finance", "legal", "accounting", "hr", "recruiting", "real-estate"),
        "ai-enterprise-vertical",
    ),
    (("robot", "hardware", "chip"), "ai-hardware"),
]

# ---------------------------------------------------------------------------
# Product-type inference
# ---------------------------------------------------------------------------

_PRODUCT_TYPE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("code", "developer", "api", "sdk", "framework", "no-code"), "dev-tool"),
    (("llm", "model", "language-model", "foundation"), "llm"),
    (("robot", "hardware", "chip", "autonomous"), "hardware"),
]

# ---------------------------------------------------------------------------
# Sub-category mapping
# ---------------------------------------------------------------------------

_SUB_CATEGORY_MAP: dict[str, str] = {
    "text-generators": "text-generation",
    "image-generators": "image-generation",
    "video-generators": "video-generation",
    "code-assistants": "coding-assistant",
    "chatbots": "chatbot",
    "writing-assistants": "writing-copywriting",
    "marketing": "marketing",
    "music-generators": "music-generation",
    "search-engines": "ai-search",
    "data-analysis": "data-analysis",
    "education": "education-tutoring",
    "design": "design-creative",
    "developer-tools": "ai-framework",
    "customer-support": "customer-service",
    "healthcare": "healthcare-medical",
    "finance": "finance-accounting",
    "legal": "legal",
    "speech": "audio-speech",
    "audio": "audio-speech",
    "3d": "3d-generation",
    "robotics": "robot",
    "autonomous-vehicles": "autonomous-vehicle",
    "cybersecurity": "ai-security",
    "gaming": "gaming",
    "productivity": "productivity",
}

# ---------------------------------------------------------------------------
# Pricing mapping
# ---------------------------------------------------------------------------

_PRICING_MAP: dict[str, tuple[str, bool]] = {
    "free": ("free", True),
    "freemium": ("freemium", True),
    "paid": ("paid", False),
    "free-trial": ("free-trial", True),
    "free trial": ("free-trial", True),
    "contact": ("enterprise", False),
}

# Detect TAAFT referral tracking in query strings.
# The site appends ?ref=taaft_feat&utm_source=taaft_feat or ?red=taaft etc.
_TAAFT_REFERRAL_RE = re.compile(r"[?&](?:ref|red|utm_source)=[^&]*taaft", re.IGNORECASE)


class TAAScraper(BaseScraper):
    """Scrape There's An AI For That via BrowserClient + internal API.

    Primary approach: Playwright stealth bypass -> paginated internal API.
    Fallback: Playwright scroll-and-parse on category pages.

    Requires: ``pip install -e ".[browser]"`` (playwright + playwright-stealth).
    """

    @property
    def source_name(self) -> str:
        return "theresanaiforthat"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Scrape TAAFT for AI tool listings."""
        try:
            from scrapers.utils.browser_client import BrowserClient, BrowserClientError
        except ImportError:
            logger.info("BrowserClient not available, skipping TAAFT scraper.")
            return []

        products: list[ScrapedProduct] = []

        try:
            with BrowserClient(_SEED_URL) as client:
                # Phase 1: Grab the site-wide featured list (fast, up to ~955 items).
                # Category assignment uses task_slug keyword matching.
                featured = self._scrape_featured(client, limit)
                products.extend(featured)

                # Phase 2: If we need more items, scrape category pages
                # via scroll-and-collect for category-specific listings.
                if len(products) < limit:
                    remaining = limit - len(products)
                    seen = {p.name.lower() for p in products}
                    html_products = self._scrape_via_html(client, remaining, seen)
                    products.extend(html_products)

        except BrowserClientError as exc:
            logger.warning("TAAFT BrowserClient error: %s", exc)
        except Exception as exc:
            logger.warning("TAAFT scraper error: %s", exc)

        logger.info("TAAFT: scraped %d products", len(products))
        return products[:limit]

    def discover(self, limit: int = 100) -> list[DiscoveredProduct]:
        """Lightweight discovery — names and URLs only."""
        products = self.scrape(limit=limit)
        return [
            DiscoveredProduct(
                name=p.name,
                source=self.source_name,
                source_url=p.source_url,
                product_url=p.product_url or "",
            )
            for p in products
        ]

    # ------------------------------------------------------------------
    # Phase 1: Site-wide featured list via /api/featured/
    # ------------------------------------------------------------------

    def _scrape_featured(
        self,
        client: BrowserClient,
        limit: int,
    ) -> list[ScrapedProduct]:
        """Grab the site-wide featured tool list in a single API call.

        TAAFT's ``/api/featured/`` returns the same ~955 featured tools
        regardless of which page is loaded. A single call from the seed
        page is enough — no category iteration needed.

        Category assignment relies on each tool's ``data-task_slug``
        attribute and keyword-based fallback.
        """
        from scrapers.utils.browser_client import BrowserClientError

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.info("BeautifulSoup not available; skipping featured API.")
            return []

        api_path = _FEATURED_API.format(limit=_MAX_FEATURED_PER_CATEGORY)
        try:
            html = client.fetch_text(api_path)
        except BrowserClientError as exc:
            logger.warning("TAAFT featured API failed: %s", exc)
            return []

        if not html or len(html) < 100:
            logger.debug("TAAFT: empty featured response")
            return []

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li[data-id][data-name]")
        logger.info("TAAFT featured: %d items returned", len(items))

        products: list[ScrapedProduct] = []
        seen_ids: set[str] = set()

        for li in items:
            tool_id = str(li.get("data-id") or "")
            if not tool_id or tool_id in seen_ids:
                continue
            seen_ids.add(tool_id)

            # Use the tool's own task_slug for category (no page-level cat_slug
            # since this is a global featured list, not category-specific).
            task_slug = str(li.get("data-task_slug") or "")
            product = _li_to_product(li, task_slug)
            if product is not None:
                products.append(product)
                if len(products) >= limit:
                    break

        logger.info("TAAFT featured: %d unique products", len(products))
        return products

    # ------------------------------------------------------------------
    # Phase 2: Category-specific scraping via scroll-and-parse
    # ------------------------------------------------------------------

    def _scrape_via_html(
        self,
        client: BrowserClient,
        limit: int,
        seen_names: set[str] | None = None,
    ) -> list[ScrapedProduct]:
        """Scrape category pages by navigating and scrolling."""
        products: list[ScrapedProduct] = []
        if seen_names is None:
            seen_names = set()

        for cat_path in _CATEGORY_URLS:
            if len(products) >= limit:
                break

            cat_slug = cat_path.rsplit("/", 1)[-1]
            url = f"{_BASE_URL}{cat_path}"
            logger.debug("TAAFT HTML: scraping category %s", cat_slug)

            try:
                client.navigate(url)
                time.sleep(2)
                html = client.scroll_and_collect(
                    max_scrolls=10, scroll_delay_ms=2000, idle_threshold=3
                )
            except Exception as exc:
                logger.debug("TAAFT HTML: %s failed: %s", cat_slug, exc)
                continue

            parsed = _parse_html_listing(html, cat_slug, url)

            for product in parsed:
                name_lower = product.name.lower()
                if name_lower in seen_names:
                    continue
                seen_names.add(name_lower)
                products.append(product)
                if len(products) >= limit:
                    break

            time.sleep(DEFAULT_REQUEST_DELAY)

        return products


# ---------------------------------------------------------------------------
# HTML <li> element -> ScrapedProduct
# ---------------------------------------------------------------------------
# TAAFT's /api/featured/ returns <li> elements with this structure:
#   <li data-id="276387" data-name="Tendem" data-url="https://..."
#       data-task="Task automation" data-task_slug="task-automation">
#     <img class="taaft_icon" src="..." alt="...">
#     <a class="ai_link" href="/ai/tendem/?..."><span>Tendem</span></a>
#     <div class="short_desc">AI + Human Agent to get tasks done</div>
#     <a class="task_label" href="..." title="Task automation">...</a>
#   </li>


def _li_to_product(li: Any, cat_slug: str) -> ScrapedProduct | None:
    """Convert a TAAFT ``<li>`` element to a ScrapedProduct."""
    name = (li.get("data-name") or "").strip()
    if not name or len(name) < 2 or len(name) > 200:
        return None

    tool_id = li.get("data-id", "")
    website = _clean_url(li.get("data-url") or "")
    task_name = li.get("data-task") or ""
    task_slug = li.get("data-task_slug") or cat_slug

    # Description from <div class="short_desc">
    desc_el = li.select_one(".short_desc")
    description = desc_el.get_text(strip=True) if desc_el else ""
    if len(description) > 500:
        description = description[:497] + "..."

    # Icon URL from <img class="taaft_icon">
    icon_el = li.select_one("img.taaft_icon")
    icon_url = icon_el.get("src") if icon_el else None

    # TAAFT page link from <a class="ai_link">
    link_el = li.select_one("a.ai_link")
    tool_path = ""
    if link_el:
        href = link_el.get("href", "")
        if isinstance(href, str):
            tool_path = href.split("?")[0]  # strip query params

    # Category: use the page-level cat_slug first, then try to refine
    # via the tool's own task_slug if it yields something more specific.
    category = _map_category(cat_slug)
    if task_slug:
        refined = _map_category(task_slug)
        if refined != "ai-application":
            # task_slug matched a specific category — use it
            category = refined

    sub_category = _SUB_CATEGORY_MAP.get(cat_slug)
    product_type = _infer_product_type(cat_slug)
    if task_slug:
        refined_type = _infer_product_type(task_slug)
        if refined_type != "app":
            product_type = refined_type

    # Tags: use task name + category slug
    tags: list[str] = []
    if task_name:
        tags.append(task_name)
    cat_label = cat_slug.replace("-", " ")
    if cat_label and cat_label != task_name:
        tags.append(cat_label)

    # Extra metadata
    extra: dict[str, str] = {}
    if tool_id:
        extra["taaft_id"] = str(tool_id)

    source_url = f"{_BASE_URL}{tool_path}" if tool_path else _BASE_URL

    return ScrapedProduct(
        name=name,
        source="theresanaiforthat",
        source_url=source_url,
        source_tier=SourceTier.T2_OPEN_WEB,
        product_url=website or None,
        icon_url=icon_url,
        description=description or None,
        product_type=product_type,
        category=category,
        sub_category=sub_category,
        tags=tuple(tags),
        company_website=website or None,
        status="active",
        extra=extra,
    )


# ---------------------------------------------------------------------------
# HTML fallback parsing
# ---------------------------------------------------------------------------

# Matches tool cards in TAAFT's rendered HTML.
# The site uses <a> elements with tool info inside structured card divs.
_HTML_TOOL_RE = re.compile(
    r'<a[^>]+href="(/ai/[^"]+)"[^>]*>[^<]{0,5000}'
    r'<(?:h[2-4]|div|span)[^>]*class="[^"]*(?:tool-name|title)[^"]*"[^>]*>'
    r"([^<]{2,100})</",
)

_HTML_DESC_RE = re.compile(
    r'<(?:p|div|span)[^>]*class="[^"]*(?:description|desc|summary)[^"]*"[^>]*>'
    r"([^<]{10,500})</",
)


def _parse_html_listing(
    html: str,
    cat_slug: str,
    page_url: str,
) -> list[ScrapedProduct]:
    """Parse rendered HTML from a TAAFT category page."""
    if not html or len(html) < 500:
        return []

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.debug("BeautifulSoup not available; trying regex fallback.")
        return _parse_html_regex(html, cat_slug, page_url)

    soup = BeautifulSoup(html, "html.parser")
    products: list[ScrapedProduct] = []
    category = _map_category(cat_slug)
    sub_category = _SUB_CATEGORY_MAP.get(cat_slug)
    product_type = _infer_product_type(cat_slug)

    # Look for tool cards — TAAFT uses various class patterns.
    # Try common selectors for AI directory sites.
    cards = (
        soup.select("[class*='tool-card']")
        or soup.select("[class*='card']")
        or soup.select("article")
        or soup.select("[data-tool]")
    )

    for card in cards:
        # Extract name from heading or link text
        name_el = (
            card.select_one("[class*='tool-name']")
            or card.select_one("[class*='title']")
            or card.select_one("h2, h3, h4")
        )
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2 or len(name) > 200:
            continue

        # Extract link
        link_el = card.select_one("a[href*='/ai/']") or card.find("a", href=True)
        tool_path = ""
        if link_el:
            href = link_el.get("href", "")
            if isinstance(href, str):
                tool_path = href

        # Extract description
        desc_el = (
            card.select_one("[class*='description']")
            or card.select_one("[class*='desc']")
            or card.select_one("p")
        )
        description = desc_el.get_text(strip=True) if desc_el else ""
        if len(description) > 500:
            description = description[:497] + "..."

        source_url = (
            f"{_BASE_URL}{tool_path}" if tool_path.startswith("/") else page_url
        )

        products.append(
            ScrapedProduct(
                name=name,
                source="theresanaiforthat",
                source_url=source_url,
                source_tier=SourceTier.T2_OPEN_WEB,
                description=description or None,
                product_type=product_type,
                category=category,
                sub_category=sub_category,
                tags=(cat_slug.replace("-", " "),),
                status="active",
            )
        )

    if not products:
        # BeautifulSoup found nothing — try regex as last resort
        products = _parse_html_regex(html, cat_slug, page_url)

    return products


def _parse_html_regex(
    html: str,
    cat_slug: str,
    page_url: str,
) -> list[ScrapedProduct]:
    """Regex-based HTML extraction when BeautifulSoup is unavailable."""
    products: list[ScrapedProduct] = []
    category = _map_category(cat_slug)
    sub_category = _SUB_CATEGORY_MAP.get(cat_slug)
    product_type = _infer_product_type(cat_slug)

    for match in _HTML_TOOL_RE.finditer(html):
        tool_path = match.group(1).strip()
        name = match.group(2).strip()

        if not name or len(name) < 2 or len(name) > 200:
            continue

        source_url = f"{_BASE_URL}{tool_path}"

        products.append(
            ScrapedProduct(
                name=name,
                source="theresanaiforthat",
                source_url=source_url,
                source_tier=SourceTier.T2_OPEN_WEB,
                product_type=product_type,
                category=category,
                sub_category=sub_category,
                tags=(cat_slug.replace("-", " "),),
                status="active",
            )
        )

    return products


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _clean_url(url: str) -> str:
    """Strip TAAFT referral/tracking parameters from a URL."""
    if not url:
        return ""
    # If the query string contains TAAFT referral markers, strip it entirely.
    if _TAAFT_REFERRAL_RE.search(url):
        url = url.split("?")[0]
    return url.rstrip("/")


def _map_category(slug: str) -> str:
    """Map a TAAFT category slug to our schema category."""
    if not slug:
        return "ai-application"

    if slug in _CATEGORY_MAP:
        return _CATEGORY_MAP[slug]

    # Keyword fallback
    slug_lower = slug.lower()
    for keywords, our_category in _KEYWORD_RULES:
        if any(kw in slug_lower for kw in keywords):
            return our_category

    return "ai-application"


def _infer_product_type(slug: str) -> str:
    """Infer product_type from the primary TAAFT category slug."""
    if not slug:
        return "app"

    slug_lower = slug.lower()
    for keywords, ptype in _PRODUCT_TYPE_KEYWORDS:
        if any(kw in slug_lower for kw in keywords):
            return ptype

    return "app"


def _parse_pricing(tool: dict[str, Any]) -> tuple[str | None, bool | None]:
    """Extract pricing model and free-tier flag from a tool record."""
    # Try explicit pricing field
    pricing = (tool.get("pricing") or tool.get("price") or "").lower().strip()
    if pricing in _PRICING_MAP:
        return _PRICING_MAP[pricing]

    # Try nested pricing info
    pricing_info: dict[str, Any] = tool.get("pricing_info") or {}
    if isinstance(pricing_info, dict):
        model = (pricing_info.get("model") or pricing_info.get("type") or "").lower()
        if model in _PRICING_MAP:
            return _PRICING_MAP[model]

    # Check boolean flags
    if tool.get("is_free") is True:
        return "free", True

    return None, None
