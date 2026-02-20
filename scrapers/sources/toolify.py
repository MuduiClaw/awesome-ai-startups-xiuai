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
    # ai-image-design — image/photo/design/3D/avatar
    # -----------------------------------------------------------------
    "ai-image-generator": "ai-image-design",
    "ai-art-generator": "ai-image-design",
    "ai-design-generator": "ai-image-design",
    "ai-photo-editor": "ai-image-design",
    "text-to-image": "ai-image-design",
    "image-to-image": "ai-image-design",
    "ai-image-upscaler": "ai-image-design",
    "ai-photo-restoration": "ai-image-design",
    "ai-image-enhancer": "ai-image-design",
    "ai-photo-enhancer": "ai-image-design",
    "ai-image-sharpening": "ai-image-design",
    "ai-unblur-image": "ai-image-design",
    "ai-inpainting": "ai-image-design",
    "ai-outpainting": "ai-image-design",
    "ai-expand-image": "ai-image-design",
    "ai-image-combiner": "ai-image-design",
    "ai-style-transfer": "ai-image-design",
    "ai-background-remover": "ai-image-design",
    "ai-background-generator": "ai-image-design",
    "ai-watermark-remover": "ai-image-design",
    "ai-eraser": "ai-image-design",
    "object-remover-ai": "ai-image-design",
    "ai-illustration-generator": "ai-image-design",
    "ai-anime-generator": "ai-image-design",
    "ai-realistic-image-generator": "ai-image-design",
    "ai-product-photography": "ai-image-design",
    "ai-clothing-generator": "ai-image-design",
    "ai-avatar-generator": "ai-image-design",
    "ai-headshot-generator": "ai-image-design",
    "ai-profile-picture-generator": "ai-image-design",
    "ai-graphic-design": "ai-image-design",
    "ai-design-assistant": "ai-image-design",
    "ai-poster-generator": "ai-image-design",
    "ai-infographic-generator": "ai-image-design",
    "ai-ppt-maker": "ai-image-design",
    "ai-presentation-generator": "ai-image-design",
    "ai-interior-design": "ai-image-design",
    "text-to-3d": "ai-image-design",
    "image-to-3d-model": "ai-image-design",
    "ai-3d-model-generator": "ai-image-design",
    "ai-game-generator": "ai-image-design",
    # -----------------------------------------------------------------
    # ai-video-animation — video generation/editing/animation
    # -----------------------------------------------------------------
    "ai-video-generator": "ai-video-animation",
    "image-to-video": "ai-video-animation",
    "text-to-video": "ai-video-animation",
    "video-to-video": "ai-video-animation",
    "ai-short-video-generator": "ai-video-animation",
    "ai-video-editor": "ai-video-animation",
    "ai-video-enhancer": "ai-video-animation",
    "ai-animation-generator": "ai-video-animation",
    "ai-animated-video": "ai-video-animation",
    "ai-cartoon-video-generator": "ai-video-animation",
    "ai-lip-sync-generator": "ai-video-animation",
    "ai-face-swap-generator": "ai-video-animation",
    "ai-face-swap-video": "ai-video-animation",
    "ai-commercial-generator": "ai-video-animation",
    "ai-tiktok-video-generator": "ai-video-animation",
    "ai-ugc-video-generator": "ai-video-animation",
    "ai-youtube-video-maker": "ai-video-animation",
    "ai-music-video-generator": "ai-video-animation",
    "ai-movie-generator": "ai-video-animation",
    "ai-video-translator": "ai-video-animation",
    "ai-subtitle-generator": "ai-video-animation",
    "ai-dubbing": "ai-video-animation",
    "script-to-video-ai-generator": "ai-video-animation",
    "ai-avatar-video-generator": "ai-video-animation",
    "ai-youtube": "ai-video-animation",
    # -----------------------------------------------------------------
    # ai-audio-music — audio/voice/music/speech
    # -----------------------------------------------------------------
    "ai-music-generator": "ai-audio-music",
    "ai-audio": "ai-audio-music",
    "ai-voice-cloning": "ai-audio-music",
    "text-to-speech": "ai-audio-music",
    "ai-song-generator": "ai-audio-music",
    "ai-voice-generator": "ai-audio-music",
    "ai-voice-over": "ai-audio-music",
    "ai-text-to-speech": "ai-audio-music",
    "ai-text-to-music": "ai-audio-music",
    "ai-speech-to-text": "ai-audio-music",
    "ai-lyrics-generator": "ai-audio-music",
    "ai-vocal-remover": "ai-audio-music",
    "ai-transcriber": "ai-audio-music",
    "ai-transcription": "ai-audio-music",
    "ai-cover-generator": "ai-audio-music",
    # -----------------------------------------------------------------
    # ai-chatbot-agent — chatbot/assistant/agent
    # -----------------------------------------------------------------
    "ai-chatbot": "ai-chatbot-agent",
    "ai-assistant": "ai-chatbot-agent",
    "ai-agent": "ai-chatbot-agent",
    # -----------------------------------------------------------------
    # ai-writing-content — writing/copywriting/content
    # -----------------------------------------------------------------
    "ai-writing-assistants": "ai-writing-content",
    "ai-writing": "ai-writing-content",
    "ai-rewriter": "ai-writing-content",
    "ai-copywriting": "ai-writing-content",
    "ai-blog-generator": "ai-writing-content",
    "ai-documents-generator": "ai-writing-content",
    "ai-paraphraser": "ai-writing-content",
    "ai-report-generator": "ai-writing-content",
    "seo-writing-ai": "ai-writing-content",
    "ai-pdf": "ai-writing-content",
    "humanizer-ai": "ai-writing-content",
    "ai-prompt-generator": "ai-writing-content",
    "prompt-engineering": "ai-writing-content",
    # -----------------------------------------------------------------
    # ai-productivity — workflow/scheduling/knowledge/copilot
    # -----------------------------------------------------------------
    "ai-productivity-tools": "ai-productivity",
    "ai-knowledge-management": "ai-productivity",
    "ai-copilot": "ai-productivity",
    "ai-workflow": "ai-productivity",
    "ai-task-management": "ai-productivity",
    "ai-meeting-assistant": "ai-productivity",
    "ai-coaching": "ai-productivity",
    "ai-email-assistant": "ai-productivity",
    "ai-scheduling": "ai-productivity",
    # -----------------------------------------------------------------
    # ai-education
    # -----------------------------------------------------------------
    "ai-education": "ai-education",
    # -----------------------------------------------------------------
    # ai-marketing-commerce — marketing/SEO/ads/social media posts
    # -----------------------------------------------------------------
    "ai-marketing": "ai-marketing-commerce",
    "ai-seo-tools": "ai-marketing-commerce",
    "ai-ad-generator": "ai-marketing-commerce",
    "ai-advertising": "ai-marketing-commerce",
    "ai-digital-marketing": "ai-marketing-commerce",
    "ai-ad-creative": "ai-marketing-commerce",
    "ai-marketing-plan-generator": "ai-marketing-commerce",
    "ai-email-marketing": "ai-marketing-commerce",
    "ai-social-media-post-generator": "ai-marketing-commerce",
    # -----------------------------------------------------------------
    # ai-social-entertainment — social/character/roleplay
    # -----------------------------------------------------------------
    "ai-character": "ai-social-entertainment",
    "ai-roleplay": "ai-social-entertainment",
    "ai-social-media": "ai-social-entertainment",
    "ai-social-media-assistant": "ai-social-entertainment",
    # -----------------------------------------------------------------
    # ai-customer-service
    # -----------------------------------------------------------------
    "ai-customer-service": "ai-customer-service",
    # -----------------------------------------------------------------
    # ai-translation
    # -----------------------------------------------------------------
    "ai-translation": "ai-translation",
    # -----------------------------------------------------------------
    # ai-hr-recruiting
    # -----------------------------------------------------------------
    "ai-interview-assistant": "ai-hr-recruiting",
    # -----------------------------------------------------------------
    # ai-finance-legal
    # -----------------------------------------------------------------
    "ai-finance": "ai-finance-legal",
    "ai-legal-assistant": "ai-finance-legal",
    "ai-for-finance": "ai-finance-legal",
    # -----------------------------------------------------------------
    # ai-sales-crm
    # -----------------------------------------------------------------
    "ai-lead-generation": "ai-sales-crm",
    "ai-sales-assistant": "ai-sales-crm",
    "ai-sales": "ai-sales-crm",
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
    (("image", "photo", "design", "art", "3d", "avatar"), "ai-image-design"),
    (("video", "animation", "movie"), "ai-video-animation"),
    (("music", "audio", "voice", "speech", "sound"), "ai-audio-music"),
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
    (("llm", "language-model", "foundation"), "ai-foundation-model"),
    (("marketing", "seo", "advertising", "ecommerce"), "ai-marketing-commerce"),
    (("finance", "legal", "accounting"), "ai-finance-legal"),
    (("hr", "recruiting", "resume", "interview"), "ai-hr-recruiting"),
    (("sales", "crm"), "ai-sales-crm"),
    (("education", "tutoring", "course"), "ai-education"),
    (("translat",), "ai-translation"),
    (("customer-service", "helpdesk"), "ai-customer-service"),
    (("writing", "copywriting", "blog", "content"), "ai-writing-content"),
    (("robot", "hardware", "chip"), "ai-hardware"),
]

# ---------------------------------------------------------------------------
# Product-type inference
# ---------------------------------------------------------------------------

_PRODUCT_TYPE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("code", "developer", "api", "sdk", "framework", "no-code"), "dev-tool"),
    (("llm", "language-model", "foundation"), "llm"),
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
        return "ai-chatbot-agent"

    # Direct map first
    if toolify_handle in _CATEGORY_MAP:
        return _CATEGORY_MAP[toolify_handle]

    # Keyword fallback
    handle_lower = toolify_handle.lower()
    for keywords, our_category in _KEYWORD_RULES:
        if any(kw in handle_lower for kw in keywords):
            return our_category

    return "ai-chatbot-agent"


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
