"""Toolify.ai scraper via internal REST API + Playwright stealth.

T2 Open Web — AI tool ranking and traffic analytics platform.
Uses Playwright to bypass Cloudflare, then calls Toolify's internal
``/self-api/v1/tools`` endpoint for structured JSON product data
with traffic rankings, pricing, and category information.

Requires optional dependencies: ``playwright``, ``playwright-stealth``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from scrapers.base import BaseScraper, DiscoveredProduct, ScrapedProduct, SourceTier
from scrapers.config import DEFAULT_REQUEST_DELAY

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.toolify.ai"
_SEED_URL = f"{_BASE_URL}/new"
_API_TOOLS = "/self-api/v1/tools"
_PER_PAGE = 100  # Max supported; 200 causes server errors.

# Toolify tracking parameter appended to product URLs.
_UTM_RE = re.compile(r"[?&]utm_source=toolify.*$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Category mapping: Toolify handle → our schema category
# ---------------------------------------------------------------------------

# Direct map for the top categories (covers ~80 % of products).
# Values use normalizer aliases where convenient — the downstream
# Normalizer._CATEGORY_ALIASES automatically maps e.g. "ai-app" → "ai-application".
_CATEGORY_MAP: dict[str, str] = {
    # Applications
    "ai-chatbot": "ai-application",
    "ai-assistant": "ai-application",
    "ai-productivity-tools": "ai-application",
    "ai-writing-assistants": "ai-application",
    "ai-agent": "ai-application",
    "ai-marketing": "ai-application",
    "ai-customer-service": "ai-application",
    "ai-education": "ai-application",
    "ai-email-assistant": "ai-application",
    "ai-social-media-assistant": "ai-application",
    "ai-scheduling": "ai-application",
    "ai-translation": "ai-application",
    "ai-finance": "ai-enterprise-vertical",
    "ai-healthcare": "ai-science-research",
    "ai-legal-assistant": "ai-enterprise-vertical",
    # Creative & media
    "ai-image-generator": "ai-creative-media",
    "ai-video-generator": "ai-creative-media",
    "ai-art-generator": "ai-creative-media",
    "ai-design-generator": "ai-creative-media",
    "ai-music-generator": "ai-creative-media",
    "ai-audio": "ai-creative-media",
    "ai-3d-model-generator": "ai-creative-media",
    "ai-photo-editor": "ai-creative-media",
    "ai-voice-cloning": "ai-creative-media",
    "text-to-speech": "ai-creative-media",
    # Developer & platform
    "ai-developer-tools": "ai-dev-platform",
    "ai-api": "ai-dev-platform",
    "ai-code-assistant": "ai-dev-platform",
    "ai-code-generator": "ai-dev-platform",
    "no-code-low-code": "ai-dev-platform",
    # Models
    "large-language-models-llms": "ai-foundation-model",
    # Data & analytics
    "ai-data-analysis": "ai-data-platform",
    "ai-analytics": "ai-data-platform",
    # Search
    "ai-search-engine": "ai-search-retrieval",
    "ai-summarizer": "ai-search-retrieval",
    # Security
    "ai-security": "ai-security-governance",
    "ai-detector": "ai-security-governance",
    # Infrastructure
    "ai-infrastructure": "ai-infrastructure",
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
]

# ---------------------------------------------------------------------------
# Pricing mapping
# ---------------------------------------------------------------------------

_PRICING_MAP: dict[str, tuple[str, bool]] = {
    "free": ("free", True),
    "freemium": ("freemium", True),
    "paid": ("paid", False),
    "free-trial": ("free-trial", True),
    "contact-for-pricing": ("enterprise", False),
}


class ToolifyScraper(BaseScraper):
    """Scrape Toolify.ai for AI tool data via internal REST API.

    Uses Playwright with stealth patches to bypass Cloudflare, then
    paginates through ``/self-api/v1/tools`` for structured JSON data.

    Requires: ``pip install -e ".[browser]"`` (playwright + playwright-stealth).
    """

    @property
    def source_name(self) -> str:
        return "toolify"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    def scrape_raw(self, limit: int = 100) -> list[dict[str, object]]:
        """Return raw tool dicts from Toolify's REST API."""
        try:
            from scrapers.utils.browser_client import BrowserClient, BrowserClientError
        except ImportError:
            logger.info("BrowserClient not available, skipping Toolify scraper.")
            return []

        raw_items: list[dict[str, object]] = []
        seen_handles: set[str] = set()

        try:
            with BrowserClient(_SEED_URL) as client:
                page_num = 1
                while len(raw_items) < limit:
                    path = f"{_API_TOOLS}?page={page_num}&per_page={_PER_PAGE}"
                    try:
                        resp = client.fetch_json(path)
                    except BrowserClientError as exc:
                        logger.warning("Toolify API page %d failed: %s", page_num, exc)
                        break

                    data = resp.get("data", {})
                    if not isinstance(data, dict):
                        logger.warning(
                            "Toolify: unexpected response structure on page %d",
                            page_num,
                        )
                        break

                    items: list[dict[str, Any]] = data.get("data", [])
                    total = data.get("total", 0)
                    last_page = data.get("last_page", 1)

                    if page_num == 1:
                        logger.info(
                            "Toolify: %d total products, %d pages", total, last_page
                        )

                    if not items:
                        break

                    for tool in items:
                        handle = tool.get("handle", "")
                        if not handle or handle in seen_handles:
                            continue
                        seen_handles.add(handle)

                        name = (tool.get("name") or "").strip()
                        if name and 2 <= len(name) <= 200:
                            raw_items.append(dict(tool))
                            if len(raw_items) >= limit:
                                break

                    if page_num % 10 == 0:
                        logger.info(
                            "Toolify: page %d/%d (%d items)",
                            page_num,
                            last_page,
                            len(raw_items),
                        )

                    if page_num >= last_page:
                        break

                    page_num += 1
                    time.sleep(DEFAULT_REQUEST_DELAY)

        except Exception as exc:
            logger.warning("Toolify scraper error: %s", exc)

        logger.info("Toolify: collected %d raw items", len(raw_items))
        return raw_items[:limit]

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Full crawl: paginate all products without category filter."""
        raw_items = self.scrape_raw(limit=limit)
        products: list[ScrapedProduct] = []

        for tool in raw_items:
            product = _tool_to_product(tool)  # type: ignore[arg-type]
            if product is not None:
                products.append(product)

        logger.info("Toolify: scraped %d products", len(products))
        return products

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


# ---------------------------------------------------------------------------
# Field mapping helpers
# ---------------------------------------------------------------------------


def _tool_to_product(tool: dict[str, Any]) -> ScrapedProduct | None:
    """Convert a single Toolify API tool object to a ScrapedProduct."""
    name = (tool.get("name") or "").strip()
    if not name or len(name) < 2 or len(name) > 200:
        return None

    handle = tool.get("handle", "")
    website = _clean_url(tool.get("website") or "")
    description = (tool.get("description") or tool.get("what_is_summary") or "").strip()
    if len(description) > 500:
        description = description[:497] + "..."

    # Icon: prefer website_logo over generic image
    icon_url = tool.get("website_logo") or tool.get("image") or None

    # Categories from API
    api_categories: list[dict[str, Any]] = tool.get("categories") or []
    primary_handle = api_categories[0]["handle"] if api_categories else ""
    category = _map_category(primary_handle)
    sub_category = primary_handle.replace("-", " ") if primary_handle else None
    product_type = _infer_product_type(primary_handle)

    # Tags: use category names from the API
    tag_list: list[str] = []
    for cat in api_categories[:5]:
        cat_name = cat.get("name", "")
        if cat_name:
            tag_list.append(cat_name)

    # Keywords: Toolify's own tags
    api_tags: list[str] = tool.get("tags") or []
    keywords = tuple(t for t in api_tags[:15] if isinstance(t, str) and t.strip())

    # Pricing
    pricing_model, has_free_tier = _parse_pricing(tool)

    # Traffic & extra metadata
    extra: dict[str, str] = {}

    monthly_visits = tool.get("month_visited_count")
    if monthly_visits and monthly_visits > 0:
        extra["toolify_monthly_visits"] = str(monthly_visits)

    traffic: dict[str, Any] = tool.get("traffic") or {}
    growth_rate = traffic.get("growth_rate")
    if growth_rate and growth_rate != 0:
        extra["toolify_growth_rate"] = str(growth_rate)
    top_region = traffic.get("top_region")
    if top_region:
        extra["toolify_top_region"] = str(top_region)

    review_score = tool.get("review_score")
    if review_score is not None:
        extra["toolify_rating"] = str(review_score)

    created_at = tool.get("created_at") or ""
    if created_at:
        extra["toolify_created_at"] = created_at

    source_url = f"{_BASE_URL}/tool/{handle}" if handle else _BASE_URL

    return ScrapedProduct(
        name=name,
        source="toolify",
        source_url=source_url,
        source_tier=SourceTier.T2_OPEN_WEB,
        product_url=website or None,
        icon_url=icon_url,
        description=description or None,
        product_type=product_type,
        category=category,
        sub_category=sub_category,
        tags=tuple(tag_list),
        keywords=keywords,
        company_website=website or None,
        pricing_model=pricing_model,
        has_free_tier=has_free_tier,
        status="active",
        extra=extra,
    )


def _clean_url(url: str) -> str:
    """Strip Toolify's UTM tracking parameter from a URL."""
    if not url:
        return ""
    return _UTM_RE.sub("", url).rstrip("/")


def _map_category(toolify_handle: str) -> str:
    """Map a Toolify category handle to our schema category."""
    if not toolify_handle:
        return "ai-application"

    # Direct map first
    if toolify_handle in _CATEGORY_MAP:
        return _CATEGORY_MAP[toolify_handle]

    # Keyword fallback
    handle_lower = toolify_handle.lower()
    for keywords, our_category in _KEYWORD_RULES:
        if any(kw in handle_lower for kw in keywords):
            return our_category

    return "ai-application"


def _infer_product_type(toolify_handle: str) -> str:
    """Infer product_type from the primary Toolify category."""
    if not toolify_handle:
        return "app"

    handle_lower = toolify_handle.lower()
    for keywords, ptype in _PRODUCT_TYPE_KEYWORDS:
        if any(kw in handle_lower for kw in keywords):
            return ptype

    return "app"


def _parse_pricing(tool: dict[str, Any]) -> tuple[str | None, bool | None]:
    """Extract pricing model and free-tier info from tool attributes."""
    attributes: list[dict[str, Any]] = tool.get("attributes") or []
    for attr in attributes:
        if attr.get("handle") == "pricing":
            options: list[dict[str, str]] = attr.get("options") or []
            if options:
                pricing_handle = options[0].get("handle", "").lower()
                if pricing_handle in _PRICING_MAP:
                    return _PRICING_MAP[pricing_handle]

    # Fallback to is_free field
    if tool.get("is_free") is True:
        return "free", True

    return None, None
