"""Google Play and Apple App Store scrapers for mobile AI apps.

T2 Open Web — search app stores for AI-related applications,
extracting ratings, download counts, and store URLs. Uses
google-play-scraper library for Google Play and iTunes Search API
(via httpx) for Apple App Store.

Supports bilingual discovery: English queries against the US store and
Chinese queries against both the US and CN (App Store) stores, with
automatic ``name_zh`` / ``description_zh`` population for Chinese-language
results.
"""

from __future__ import annotations

import logging
import re
import time

from scrapers.base import BaseScraper, ScrapedProduct, SourceTier
from scrapers.config import DEFAULT_REQUEST_DELAY

logger = logging.getLogger(__name__)

# English search terms for app store discovery.
# Derived from aibot categories, ainav categories, and tag_inference use-cases.
_SEARCH_QUERIES_EN = [
    # --- Core (original) ---
    "AI chatbot",
    "AI assistant",
    "AI image generator",
    "AI writing",
    "AI code",
    "ChatGPT",
    "AI photo editor",
    "AI translator",
    "AI voice",
    "AI art",
    "AI video",
    "text to image AI",
    "AI productivity",
    "AI scanner",
    "AI music",
    # --- From aibot categories ---
    "AI design tool",            # ai-design-tools
    "AI document",               # ai-document-tools
    "AI presentation",           # ai-presentation-tools
    "AI meeting assistant",      # ai-meeting-tools
    "AI search engine",          # ai-search-engines
    "AI agent",                  # ai-agent
    "AI 3D generator",           # ai-3d-model-generation
    "AI audio tool",             # ai-audio-tools
    "AI background remover",     # ai-image-background-removers
    "AI office",                 # ai-office-tools
    # --- From tag_inference use-cases / domains ---
    "AI education",              # education-tutoring
    "AI healthcare",             # healthcare
    "AI finance",                # finance-accounting
    "AI marketing",              # marketing
    "AI customer service",       # customer-support
    "AI roleplay",               # popular mobile chat category
]

# Chinese search terms for discovering Chinese AI apps.
# Derived from ainav categories (AI对话聊天 … AI训练模型) and aibot CN coverage.
_SEARCH_QUERIES_ZH = [
    # --- Core (original) ---
    "AI聊天",
    "AI助手",
    "AI绘画",
    "AI写作",
    "AI编程",
    "智能对话",
    "AI工具",
    "AI翻译",
    "AI修图",
    "AI视频",
    # --- From ainav categories ---
    "AI音频",                    # AI音频工具
    "AI办公",                    # AI办公工具
    "AI搜索",                    # AI搜索引擎
    "AI图片",                    # AI图片处理
    # --- From aibot categories ---
    "AI设计",                    # ai-design-tools
    "AI文档",                    # ai-document-tools
    "AI PPT",                    # ai-presentation-tools
    "AI去背景",                  # ai-image-background-removers
    # --- From tag_inference domains ---
    "AI教育",                    # education-tutoring
    "AI客服",                    # customer-support
    "AI角色扮演",                # roleplay / character chat
    "AI配音",                    # voice / dubbing
    "AI营销",                    # marketing
    "AI健康",                    # healthcare
    "AI金融",                    # finance-accounting
]

# Known non-AI apps that show up in AI searches
_SKIP_BUNDLES = frozenset(
    {
        "com.google.android.googlequicksearchbox",
        "com.google.android.apps.photos",
        "com.apple.mobilesafari",
    }
)

# AI-relevance signal keywords (EN + ZH).  An app must mention at least one
# of these in its title OR description to pass the AI-relevance filter.
_AI_SIGNALS = re.compile(
    r"(?i)"
    # --- English signals ---
    r"\bai\b|artificial intelligence|machine learning|deep learning"
    r"|neural network|large language model|\bllm\b|gpt\b|\bchatbot\b"
    r"|generative|diffusion|transformer|natural language"
    r"|computer vision|text.to.(?:image|video|speech|music|3d)"
    r"|image.to.(?:text|video)|speech.to.text|voice.clon"
    r"|copilot|intelligent assistant|\bopenai\b|\bclaude\b|\bgemini\b"
    # --- CJK + AI boundary fix (Python \b treats CJK chars as \w) ---
    r"|[\u4e00-\u9fff]AI|AI[\u4e00-\u9fff]"
    # --- Chinese signals ---
    r"|人工智能|机器学习|深度学习|大模型|大语言模型"
    r"|智能助手|智能对话|智能客服|智能写作|智能翻译"
    r"|文心一言|通义千问|智谱|豆包|讯飞星火|Kimi"
)


def _is_ai_relevant(title: str, description: str) -> bool:
    """Return True if the app appears to be an AI product.

    Checks whether the title or description contains at least one
    AI-related keyword (English or Chinese).
    """
    return bool(_AI_SIGNALS.search(title) or _AI_SIGNALS.search(description))


def _has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


class GooglePlayScraper(BaseScraper):
    """Scrape Google Play for AI-related mobile applications.

    Uses the google-play-scraper library to search for apps by
    AI-related keywords (English and Chinese) and extract metadata
    (rating, installs, etc.).  Chinese-language results automatically
    populate ``name_zh`` and ``description_zh``.
    """

    @property
    def source_name(self) -> str:
        return "google_play"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    def scrape_raw(self, limit: int = 100) -> list[dict[str, object]]:
        """Return raw app dicts from google-play-scraper, filtered for AI relevance."""
        try:
            from google_play_scraper import search as gp_search
        except ImportError:
            logger.info(
                "google-play-scraper not installed. "
                "Install with: pip install google-play-scraper"
            )
            return []

        raw_items: list[dict[str, object]] = []
        seen_ids: set[str] = set()

        query_pairs: list[tuple[str, str]] = [
            (q, "en") for q in _SEARCH_QUERIES_EN
        ] + [
            (q, "zh") for q in _SEARCH_QUERIES_ZH
        ]

        for query, lang in query_pairs:
            if len(raw_items) >= limit:
                break

            logger.debug("Google Play: searching '%s' (lang=%s)", query, lang)
            try:
                results = gp_search(
                    query,
                    lang=lang,
                    country="us",
                    n_hits=20,
                )
            except Exception as e:
                logger.debug("Google Play search '%s' failed: %s", query, e)
                time.sleep(DEFAULT_REQUEST_DELAY)
                continue

            for app in results:
                app_id = app.get("appId", "")
                if not app_id or app_id in seen_ids:
                    continue
                if app_id in _SKIP_BUNDLES:
                    continue

                seen_ids.add(app_id)

                title = app.get("title", "").strip()
                description = app.get("summary") or app.get("description", "")
                if not title:
                    continue
                if not _is_ai_relevant(title, description):
                    logger.debug("Skipping non-AI app: %s", title)
                    continue

                raw_items.append(dict(app))
                if len(raw_items) >= limit:
                    break

            time.sleep(DEFAULT_REQUEST_DELAY)

        logger.info("Google Play: collected %d raw items", len(raw_items))
        return raw_items

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Search Google Play for AI apps (EN + ZH queries)."""
        raw_items = self.scrape_raw(limit=limit)
        products: list[ScrapedProduct] = []

        for app in raw_items:
            product = _gp_app_to_product(app, self.source_name)
            if product is not None:
                products.append(product)

        logger.info("Google Play: discovered %d apps", len(products))
        return products


def _gp_app_to_product(
    app: dict[str, object], source_name: str
) -> ScrapedProduct | None:
    """Convert a raw Google Play app dict to a ScrapedProduct."""
    title = str(app.get("title", "")).strip()
    if not title:
        return None

    app_id = str(app.get("appId", ""))
    developer = str(app.get("developer", ""))
    score = app.get("score")
    installs = app.get("realInstalls") or app.get("installs", "")
    icon = str(app.get("icon", ""))
    description = str(app.get("summary") or app.get("description", ""))
    url = f"https://play.google.com/store/apps/details?id={app_id}"

    if description and len(description) > 500:
        description = description[:497] + "..."

    name_zh = title if title and _has_chinese(title) else None
    description_zh = description if description and _has_chinese(description) else None
    company_name_zh = developer if developer and _has_chinese(developer) else None

    extra: dict[str, str] = {"google_play_app_id": app_id}
    if score is not None:
        extra["google_play_rating"] = f"{score:.1f}"
    if installs:
        extra["google_play_installs"] = str(installs)

    return ScrapedProduct(
        name=title,
        name_zh=name_zh,
        source=source_name,
        source_url=url,
        source_tier=SourceTier.T2_OPEN_WEB,
        product_url=url,
        icon_url=icon if icon else None,
        description=description if description else None,
        description_zh=description_zh,
        product_type="app",
        category="ai-app",
        company_name=developer if developer else None,
        company_name_zh=company_name_zh,
        platforms=("android",),
        status="active",
        extra=extra,
    )


class AppStoreScraper(BaseScraper):
    """Scrape Apple App Store for AI-related mobile applications.

    Uses the iTunes Search API (free, no auth required) to find
    AI apps and extract metadata.  Searches both the US and CN App
    Stores with English and Chinese queries, automatically populating
    ``name_zh`` and ``description_zh`` for Chinese-language results.
    """

    @property
    def source_name(self) -> str:
        return "app_store"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    def scrape_raw(self, limit: int = 100) -> list[dict[str, object]]:
        """Return raw app dicts from iTunes Search API, filtered for AI relevance."""
        from scrapers.utils import create_http_client

        client = create_http_client()
        raw_items: list[dict[str, object]] = []
        seen_ids: set[str] = set()

        query_region_pairs: list[tuple[str, str]] = [
            (q, "us") for q in _SEARCH_QUERIES_EN
        ] + [
            (q, country)
            for q in _SEARCH_QUERIES_ZH
            for country in ("us", "cn")
        ]

        try:
            for query, country in query_region_pairs:
                if len(raw_items) >= limit:
                    break

                logger.debug("App Store: searching '%s' (country=%s)", query, country)
                try:
                    response = client.get(
                        "https://itunes.apple.com/search",
                        params={
                            "term": query,
                            "entity": "software",
                            "country": country,
                            "limit": 20,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    logger.debug("App Store search '%s' failed: %s", query, e)
                    time.sleep(DEFAULT_REQUEST_DELAY)
                    continue

                for app in data.get("results", []):
                    track_id = str(app.get("trackId", ""))
                    if not track_id or track_id in seen_ids:
                        continue

                    seen_ids.add(track_id)

                    name = app.get("trackName", "").strip()
                    description = app.get("description", "")
                    if not name:
                        continue
                    if not _is_ai_relevant(name, description):
                        logger.debug("Skipping non-AI app: %s", name)
                        continue

                    raw_items.append(dict(app))
                    if len(raw_items) >= limit:
                        break

                time.sleep(DEFAULT_REQUEST_DELAY)

        finally:
            client.close()

        logger.info("App Store: collected %d raw items", len(raw_items))
        return raw_items

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Search Apple App Store for AI apps via iTunes Search API (US + CN)."""
        raw_items = self.scrape_raw(limit=limit)
        products: list[ScrapedProduct] = []

        for app in raw_items:
            product = _appstore_app_to_product(app, self.source_name)
            if product is not None:
                products.append(product)

        logger.info("App Store: discovered %d apps", len(products))
        return products


def _appstore_app_to_product(
    app: dict[str, object], source_name: str
) -> ScrapedProduct | None:
    """Convert a raw iTunes Search API result dict to a ScrapedProduct."""
    name = str(app.get("trackName", "")).strip()
    if not name:
        return None

    track_id = str(app.get("trackId", ""))
    developer = str(app.get("artistName", ""))
    rating = app.get("averageUserRating")
    rating_count = app.get("userRatingCount")
    icon = str(app.get("artworkUrl512") or app.get("artworkUrl100", ""))
    description = str(app.get("description", ""))
    store_url = str(app.get("trackViewUrl", ""))

    if description and len(description) > 500:
        description = description[:497] + "..."

    name_zh = name if name and _has_chinese(name) else None
    description_zh = description if description and _has_chinese(description) else None
    company_name_zh = developer if developer and _has_chinese(developer) else None

    extra: dict[str, str] = {"app_store_track_id": track_id}
    if rating is not None:
        extra["app_store_rating"] = f"{rating:.1f}"
    if rating_count is not None:
        extra["app_store_rating_count"] = str(rating_count)

    return ScrapedProduct(
        name=name,
        name_zh=name_zh,
        source=source_name,
        source_url=store_url or f"https://apps.apple.com/app/id{track_id}",
        source_tier=SourceTier.T2_OPEN_WEB,
        product_url=store_url if store_url else None,
        icon_url=icon if icon else None,
        description=description if description else None,
        description_zh=description_zh,
        product_type="app",
        category="ai-app",
        company_name=developer if developer else None,
        company_name_zh=company_name_zh,
        platforms=("ios",),
        status="active",
        extra=extra,
    )
