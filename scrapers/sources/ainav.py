"""AI导航网 (ainav.cn) scraper for Chinese AI product discovery.

T2 Open Web — Chinese AI tool directory with 1000+ tools.
Fetches the single-page homepage which contains ~490 product cards
grouped by 23 category sections (#term-XXX). Each card carries
the product URL directly in a data-url attribute.
No API key required.
"""

from __future__ import annotations

import base64
import html as html_mod
import logging
import re
from urllib.parse import unquote

from scrapers.base import BaseScraper, ScrapedProduct, SourceTier
from scrapers.utils import create_http_client

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.ainav.cn"

# Aggregation / "hot picks" section that duplicates products from real categories.
_SKIP_TERMS = frozenset({"699"})  # term-699 = AI热门工具

# Ad tracking / redirect domains whose URLs are not real product websites.
_AD_DOMAINS = frozenset({"dis.csqixiang.cn"})

# Section header: <i ... id="term-XXX"></i>\n  CategoryName  </h4>
_SECTION_HEADER_RE = re.compile(r'id="term-(\d+)"></i>\s*\n\s*(.+?)\s*</h4>')

# Product card: <a ... data-url="PRODUCT_URL" ... title="DESCRIPTION" ...>
#   <img ... data-src="ICON_URL" ... alt="NAME">
#   <strong>NAME</strong>
#   <p ...>DESCRIPTION</p>
# </a>
_CARD_PATTERN = re.compile(
    r"<a[^>]*"
    r'data-url="([^"]+)"[^>]*'  # group 1: product URL (data-url)
    r'title="([^"]*)"[^>]*>'  # group 2: description (title attr)
    r".*?"
    r'data-src="([^"]*)"'  # group 3: icon URL (lazy-loaded img)
    r".*?"
    r"<strong>([^<]+)</strong>"  # group 4: product name
    r".*?"
    r"<p[^>]*>([^<]*)</p>",  # group 5: short description (p tag)
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Category mapping: AiNav Chinese category_name → (schema category, sub_category)
# ---------------------------------------------------------------------------
_AINAV_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "AI绘画工具": ("ai-image-design", "image-generation"),
    "AI图片处理": ("ai-image-design", "image-editing"),
    "AI文本工具": ("ai-writing-content", "text-generation"),
    "AI对话聊天": ("ai-chatbot-agent", "chatbot"),
    "AI开发者社区": ("ai-dev-platform", "developer-community"),
    "AI编程工具": ("ai-dev-platform", "coding-assistant"),
    "AI视频工具": ("ai-video-animation", "video-generation"),
    "AI智能体平台": ("ai-chatbot-agent", "ai-agent"),
    "AI搜索引擎": ("ai-search-retrieval", "ai-search"),
    "AI音频工具": ("ai-audio-music", "audio-speech"),
    "AI办公工具": ("ai-productivity", "productivity"),
    "AI提示词": ("ai-writing-content", "prompt-engineering"),
    "AI内容检测": ("ai-security-governance", "ai-content-detection"),
}


class AiNavScraper(BaseScraper):
    """Scrape ainav.cn homepage for Chinese AI product discovery.

    Workflow:
    1. Fetch the homepage (single request, ~950KB).
    2. Split HTML into category sections by #term-XXX markers.
    3. For each section, extract product cards via regex.
    4. Emit ScrapedProduct for each unique product found.
    """

    @property
    def source_name(self) -> str:
        return "ainav"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    def scrape_raw(self, limit: int = 100) -> list[dict[str, object]]:
        """Return raw card dicts from ainav.cn homepage."""
        client = create_http_client()
        raw_items: list[dict[str, object]] = []
        seen_names: set[str] = set()

        try:
            try:
                response = client.get(_BASE_URL)
                response.raise_for_status()
            except Exception as exc:
                logger.warning("ainav: homepage fetch failed: %s", exc)
                return raw_items

            html = response.content.decode("utf-8", errors="replace")
            sections = _split_sections(html)

            if not sections:
                logger.warning("ainav: no category sections found on homepage")
                return raw_items

            logger.info("ainav: found %d categories on homepage", len(sections))

            for term_id, cat_name, section_html in sections:
                if term_id in _SKIP_TERMS:
                    continue

                if len(raw_items) >= limit:
                    break

                parsed = _extract_cards(section_html)
                logger.debug("ainav: %s (%d products)", cat_name, len(parsed))

                for name, product_url, description, icon_url in parsed:
                    name = name.strip()
                    if not name or len(name) < 2 or len(name) > 80:
                        continue

                    name_lower = name.lower()
                    if name_lower in seen_names:
                        continue
                    seen_names.add(name_lower)

                    # Resolve redirect/tracking URLs to real product URLs
                    resolved_url = _resolve_url(product_url) if product_url else None

                    # Skip placeholder icons
                    clean_icon = icon_url
                    if clean_icon and (
                        "favicon.png" in clean_icon or "default" in clean_icon
                    ):
                        clean_icon = None

                    raw_items.append(
                        {
                            "name": name,
                            "product_url": resolved_url,
                            "description": description,
                            "icon_url": clean_icon,
                            "term_id": term_id,
                            "category_name": cat_name,
                        }
                    )

                    if len(raw_items) >= limit:
                        break

        finally:
            client.close()

        logger.info("ainav: collected %d raw items", len(raw_items))
        return raw_items

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        """Scrape ainav.cn homepage for AI tool listings."""
        raw_items = self.scrape_raw(limit=limit)
        products: list[ScrapedProduct] = []

        for item in raw_items:
            name = str(item.get("name", ""))
            product_url = item.get("product_url")
            description = item.get("description")
            icon_url = item.get("icon_url")
            cat_name = str(item.get("category_name", ""))

            name_zh = name if _has_chinese(name) else None
            desc_str = str(description) if description else None
            desc_zh = desc_str if desc_str and _has_chinese(desc_str) else None

            cat, sub = _AINAV_CATEGORY_MAP.get(
                cat_name, ("ai-chatbot-agent", None)
            )

            products.append(
                ScrapedProduct(
                    name=name,
                    source=self.source_name,
                    source_url=_BASE_URL,
                    source_tier=SourceTier.T2_OPEN_WEB,
                    name_zh=name_zh,
                    product_url=str(product_url) if product_url else None,
                    description=desc_str,
                    description_zh=desc_zh,
                    icon_url=str(icon_url) if icon_url else None,
                    category=cat,
                    sub_category=sub,
                    tags=(cat_name,),
                    status="active",
                )
            )

        logger.info("ainav: discovered %d products", len(products))
        return products


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_sections(html: str) -> list[tuple[str, str, str]]:
    """Split homepage HTML into (term_id, category_name, section_html) tuples.

    Each section runs from one <h4> header (with id="term-XXX") to the next.
    """
    headers = list(_SECTION_HEADER_RE.finditer(html))
    if not headers:
        return []

    sections: list[tuple[str, str, str]] = []
    for i, match in enumerate(headers):
        term_id = match.group(1)
        cat_name = match.group(2).strip()
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(html)
        sections.append((term_id, cat_name, html[start:end]))

    return sections


def _extract_cards(
    section_html: str,
) -> list[tuple[str, str, str, str | None]]:
    """Extract (name, product_url, description, icon_url) from section HTML."""
    entries: list[tuple[str, str, str, str | None]] = []
    seen_urls: set[str] = set()

    for match in _CARD_PATTERN.finditer(section_html):
        raw_url = html_mod.unescape(match.group(1)).strip()
        title_desc = html_mod.unescape(match.group(2)).strip()
        icon_url = match.group(3).strip() or None
        name = html_mod.unescape(match.group(4)).strip()
        p_desc = html_mod.unescape(match.group(5)).strip()

        if not name or raw_url in seen_urls:
            continue
        seen_urls.add(raw_url)

        # Prefer the <p> description; fall back to title attribute
        description = p_desc if p_desc else title_desc

        entries.append((name, raw_url, description, icon_url))

    return entries


def _resolve_url(url: str) -> str | None:
    """Resolve ainav redirect/tracking URLs to real product URLs.

    Handles three patterns:
    - /go/?url=BASE64 — decode base64 to get the real URL
    - /go2/NAME.html — JS redirect page, drop (unreliable without JS)
    - Ad tracking domains (csqixiang.cn) — drop
    - Normal URLs — clean tracking params and return
    """
    # Decode /go/?url=BASE64 pattern
    b64_match = re.search(r"/go/\?url=([A-Za-z0-9+/=%]+)", url)
    if b64_match:
        try:
            decoded = base64.b64decode(unquote(b64_match.group(1))).decode("utf-8")
            return _clean_params(decoded)
        except Exception:
            return None

    # Drop /go2/ JS redirect pages (can't resolve without browser)
    if "ainav.cn/go2/" in url:
        return None

    # Drop ainav.cn internal pages (sites/ detail pages, homepage itself)
    if re.match(r"https?://(www\.)?ainav\.cn(/|$)", url):
        return None

    # Drop ad tracking domains
    domain_match = re.match(r"https?://([^/]+)", url)
    if domain_match and domain_match.group(1) in _AD_DOMAINS:
        return None

    return _clean_params(url)


def _clean_params(url: str) -> str:
    """Remove common tracking query params (utm_*, ref, from, etc.)."""
    if "?" not in url:
        return url

    base, _, query = url.partition("?")
    params = query.split("&")
    clean = [
        p
        for p in params
        if not re.match(
            r"(utm_\w+|ref|from|source|channel|theme)=",
            p,
            re.IGNORECASE,
        )
    ]
    return f"{base}?{'&'.join(clean)}" if clean else base


def _has_chinese(text: str) -> bool:
    """Check if text contains Chinese characters."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))
