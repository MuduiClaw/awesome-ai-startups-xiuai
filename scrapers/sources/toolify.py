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

# Direct map for the top categories.
# Values must be one of the 11 schema-valid category enum values.
# The downstream Normalizer._CATEGORY_ALIASES automatically maps
# e.g. "ai-app" → "ai-application" if needed.
_CATEGORY_MAP: dict[str, str] = {
    # -----------------------------------------------------------------
    # ai-creative-media — image/video/audio/3D/design
    # -----------------------------------------------------------------
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
    # Image generation & editing
    "image-to-video": "ai-creative-media",
    "text-to-video": "ai-creative-media",
    "text-to-image": "ai-creative-media",
    "image-to-image": "ai-creative-media",
    "video-to-video": "ai-creative-media",
    "ai-image-upscaler": "ai-creative-media",
    "ai-photo-restoration": "ai-creative-media",
    "ai-image-enhancer": "ai-creative-media",
    "ai-photo-enhancer": "ai-creative-media",
    "ai-image-sharpening": "ai-creative-media",
    "ai-unblur-image": "ai-creative-media",
    "ai-inpainting": "ai-creative-media",
    "ai-outpainting": "ai-creative-media",
    "ai-expand-image": "ai-creative-media",
    "ai-image-combiner": "ai-creative-media",
    "ai-style-transfer": "ai-creative-media",
    "ai-background-remover": "ai-creative-media",
    "ai-background-generator": "ai-creative-media",
    "ai-watermark-remover": "ai-creative-media",
    "ai-eraser": "ai-creative-media",
    "object-remover-ai": "ai-creative-media",
    "ai-illustration-generator": "ai-creative-media",
    "ai-anime-generator": "ai-creative-media",
    "ai-realistic-image-generator": "ai-creative-media",
    "ai-product-photography": "ai-creative-media",
    "ai-clothing-generator": "ai-creative-media",
    # Video generation & editing
    "ai-short-video-generator": "ai-creative-media",
    "ai-video-editor": "ai-creative-media",
    "ai-video-enhancer": "ai-creative-media",
    "ai-animation-generator": "ai-creative-media",
    "ai-animated-video": "ai-creative-media",
    "ai-cartoon-video-generator": "ai-creative-media",
    "ai-lip-sync-generator": "ai-creative-media",
    "ai-face-swap-generator": "ai-creative-media",
    "ai-face-swap-video": "ai-creative-media",
    "ai-commercial-generator": "ai-creative-media",
    "ai-tiktok-video-generator": "ai-creative-media",
    "ai-ugc-video-generator": "ai-creative-media",
    "ai-youtube-video-maker": "ai-creative-media",
    "ai-music-video-generator": "ai-creative-media",
    "ai-movie-generator": "ai-creative-media",
    "ai-video-translator": "ai-creative-media",
    "ai-subtitle-generator": "ai-creative-media",
    "ai-dubbing": "ai-creative-media",
    "script-to-video-ai-generator": "ai-creative-media",
    "ai-avatar-video-generator": "ai-creative-media",
    # Audio & speech
    "ai-song-generator": "ai-creative-media",
    "ai-voice-generator": "ai-creative-media",
    "ai-voice-over": "ai-creative-media",
    "ai-text-to-speech": "ai-creative-media",
    "ai-text-to-music": "ai-creative-media",
    "ai-speech-to-text": "ai-creative-media",
    "ai-lyrics-generator": "ai-creative-media",
    "ai-vocal-remover": "ai-creative-media",
    "ai-transcriber": "ai-creative-media",
    "ai-transcription": "ai-creative-media",
    "ai-cover-generator": "ai-creative-media",
    # Avatar & profile
    "ai-avatar-generator": "ai-creative-media",
    "ai-headshot-generator": "ai-creative-media",
    "ai-profile-picture-generator": "ai-creative-media",
    # Design & presentation
    "ai-graphic-design": "ai-creative-media",
    "ai-design-assistant": "ai-creative-media",
    "ai-poster-generator": "ai-creative-media",
    "ai-infographic-generator": "ai-creative-media",
    "ai-ppt-maker": "ai-creative-media",
    "ai-presentation-generator": "ai-creative-media",
    "ai-interior-design": "ai-creative-media",
    # 3D & gaming
    "text-to-3d": "ai-creative-media",
    "image-to-3d-model": "ai-creative-media",
    "ai-game-generator": "ai-creative-media",
    # YouTube
    "ai-youtube": "ai-creative-media",
    # -----------------------------------------------------------------
    # ai-application — writing/productivity/social/character/chatbot
    # -----------------------------------------------------------------
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
    # Writing & content
    "ai-writing": "ai-application",
    "ai-rewriter": "ai-application",
    "ai-copywriting": "ai-application",
    "ai-blog-generator": "ai-application",
    "ai-documents-generator": "ai-application",
    "ai-paraphraser": "ai-application",
    "ai-report-generator": "ai-application",
    "seo-writing-ai": "ai-application",
    "ai-pdf": "ai-application",
    "humanizer-ai": "ai-application",
    # Productivity & workflow
    "ai-knowledge-management": "ai-application",
    "ai-copilot": "ai-application",
    "ai-workflow": "ai-application",
    "ai-task-management": "ai-application",
    "ai-meeting-assistant": "ai-application",
    "ai-coaching": "ai-application",
    "ai-interview-assistant": "ai-application",
    # Social & character
    "ai-character": "ai-application",
    "ai-roleplay": "ai-application",
    "ai-social-media": "ai-application",
    "ai-social-media-post-generator": "ai-application",
    # Prompts
    "ai-prompt-generator": "ai-application",
    "prompt-engineering": "ai-application",
    # -----------------------------------------------------------------
    # ai-dev-platform — developer tools, coding, no-code, web
    # -----------------------------------------------------------------
    "ai-developer-tools": "ai-dev-platform",
    "ai-api": "ai-dev-platform",
    "ai-code-assistant": "ai-dev-platform",
    "ai-code-generator": "ai-dev-platform",
    "no-code-low-code": "ai-dev-platform",
    "ai-web-scraping": "ai-dev-platform",
    "ai-website-builder": "ai-dev-platform",
    "ai-app-builder": "ai-dev-platform",
    # -----------------------------------------------------------------
    # ai-enterprise-vertical — marketing/sales/finance/legal/HR
    # -----------------------------------------------------------------
    "ai-finance": "ai-enterprise-vertical",
    "ai-legal-assistant": "ai-enterprise-vertical",
    "ai-seo-tools": "ai-enterprise-vertical",
    "ai-ad-generator": "ai-enterprise-vertical",
    "ai-advertising": "ai-enterprise-vertical",
    "ai-digital-marketing": "ai-enterprise-vertical",
    "ai-ad-creative": "ai-enterprise-vertical",
    "ai-lead-generation": "ai-enterprise-vertical",
    "ai-sales-assistant": "ai-enterprise-vertical",
    "ai-sales": "ai-enterprise-vertical",
    "ai-marketing-plan-generator": "ai-enterprise-vertical",
    "ai-email-marketing": "ai-enterprise-vertical",
    "ai-for-finance": "ai-enterprise-vertical",
    # -----------------------------------------------------------------
    # ai-data-platform — analytics & data
    # -----------------------------------------------------------------
    "ai-data-analysis": "ai-data-platform",
    "ai-analytics": "ai-data-platform",
    "ai-for-data-analytics": "ai-data-platform",
    "ai-data-mining": "ai-data-platform",
    "ai-diagram-generator": "ai-data-platform",
    # -----------------------------------------------------------------
    # ai-search-retrieval
    # -----------------------------------------------------------------
    "ai-search-engine": "ai-search-retrieval",
    "ai-summarizer": "ai-search-retrieval",
    "ai-research-tool": "ai-search-retrieval",
    # -----------------------------------------------------------------
    # ai-security-governance
    # -----------------------------------------------------------------
    "ai-security": "ai-security-governance",
    "ai-detector": "ai-security-governance",
    "ai-content-detector": "ai-security-governance",
    "ai-checker": "ai-security-governance",
    # -----------------------------------------------------------------
    # ai-foundation-model
    # -----------------------------------------------------------------
    "large-language-models-llms": "ai-foundation-model",
    "open-source-ai-models": "ai-foundation-model",
    "ai-models": "ai-foundation-model",
    # -----------------------------------------------------------------
    # ai-science-research
    # -----------------------------------------------------------------
    "ai-healthcare": "ai-science-research",
    "ai-teachers": "ai-science-research",
    "ai-math": "ai-science-research",
    # -----------------------------------------------------------------
    # ai-infrastructure
    # -----------------------------------------------------------------
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
        max_consecutive_failures = 3

        try:
            with BrowserClient(_SEED_URL) as client:
                page_num = 1
                consecutive_failures = 0
                last_page = 1  # updated from first successful response
                while len(raw_items) < limit:
                    path = f"{_API_TOOLS}?page={page_num}&per_page={_PER_PAGE}"
                    try:
                        resp = client.fetch_json(path)
                    except BrowserClientError as exc:
                        consecutive_failures += 1
                        logger.warning(
                            "Toolify API page %d failed (%d/%d): %s",
                            page_num,
                            consecutive_failures,
                            max_consecutive_failures,
                            exc,
                        )
                        if consecutive_failures >= max_consecutive_failures:
                            logger.warning(
                                "Toolify: %d consecutive failures, stopping",
                                consecutive_failures,
                            )
                            break
                        # Skip this page and try the next one
                        page_num += 1
                        time.sleep(DEFAULT_REQUEST_DELAY * 2)
                        continue

                    data = resp.get("data", {})
                    if not isinstance(data, dict):
                        consecutive_failures += 1
                        logger.warning(
                            "Toolify: unexpected response on page %d (%d/%d)",
                            page_num,
                            consecutive_failures,
                            max_consecutive_failures,
                        )
                        if consecutive_failures >= max_consecutive_failures:
                            break
                        page_num += 1
                        time.sleep(DEFAULT_REQUEST_DELAY * 2)
                        continue

                    # Reset on success
                    consecutive_failures = 0

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
