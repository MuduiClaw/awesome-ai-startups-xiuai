"""Product Hunt GraphQL API scraper for AI products.

Scans ALL Product Hunt posts (no topic restriction) using ``order: NEWEST``
with cursor-based pagination, then filters for AI relevance via keyword
matching.  This captures AI products regardless of how they are tagged.

Usage:
    aiscrape scrape --source producthunt --limit 200    # daily incremental
    aiscrape scrape --source producthunt --limit 5000   # deeper backfill
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time
from typing import Any

import httpx

from scrapers.base import BaseScraper, ScrapedProduct, SourceTier
from scrapers.config import DEFAULT_REQUEST_DELAY
from scrapers.utils import create_http_client

logger = logging.getLogger(__name__)

# AI-relevance keywords — product must mention at least one in name/tagline/description.
_AI_SIGNALS = re.compile(
    r"(?i)"
    r"\bai\b|artificial intelligence|machine learning|deep learning"
    r"|neural network|large language model|\bllm\b|gpt\b|\bchatbot\b"
    r"|generative|diffusion|transformer|natural language"
    r"|computer vision|text.to.(?:image|video|speech|music|3d)"
    r"|image.to.(?:text|video)|speech.to.text|voice.clon"
    r"|copilot|intelligent assistant|\bopenai\b|\bclaude\b|\bgemini\b"
    r"|coding.agent|code.agent|vibe.cod"
    r"|人工智能|机器学习|深度学习|大模型|大语言模型"
    r"|智能助手|智能对话|智能客服|智能写作|智能翻译"
)

# Page size per GraphQL request (PH allows up to 50)
_PAGE_SIZE = 50

# Minimum remaining rate-limit points before pausing
_RATE_LIMIT_FLOOR = 100

# Absolute cap on rate-limit wait to prevent hangs from malformed headers
_MAX_RATE_LIMIT_WAIT = 900  # 15 minutes

# Safety cap on total pages to prevent runaway loops.
# 10 000 pages × 50 items = 500k posts — enough for a full-site backfill.
_MAX_PAGES = 10_000

# PH was founded in 2013; this ensures the query covers the full archive.
_EPOCH = "2013-01-01T00:00:00Z"


class ProductHuntScraper(BaseScraper):
    """Scrape Product Hunt for AI products via full-site scan + keyword filter.

    Strategy: query ``posts(order: NEWEST, postedAfter: 2013-01-01)`` without
    any topic restriction to scan ALL products, then apply ``_AI_SIGNALS``
    regex to keep only AI-relevant ones.

    Requires: ``PRODUCTHUNT_TOKEN`` env var.

    Pagination: cursor-based (Relay-style) via ``pageInfo.endCursor``.
    Rate limiting: respects ``X-Rate-Limit-Remaining`` / ``X-Rate-Limit-Reset``.
    """

    API_URL = "https://api.producthunt.com/v2/api/graphql"

    QUERY = """
    query($first: Int!, $after: String, $postedAfter: DateTime) {
      posts(first: $first, after: $after, order: NEWEST, postedAfter: $postedAfter) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            id name tagline description url website votesCount
            makers { name }
          }
        }
      }
    }
    """

    @property
    def source_name(self) -> str:
        return "producthunt"

    @property
    def source_tier(self) -> SourceTier:
        return SourceTier.T2_OPEN_WEB

    # -- Public API ----------------------------------------------------------

    def scrape_raw(self, limit: int = 100) -> list[dict[str, object]]:
        """Return raw GraphQL node dicts, filtered for AI relevance."""
        token = os.environ.get("PRODUCTHUNT_TOKEN", "")
        if not token:
            logger.warning("PRODUCTHUNT_TOKEN not set, skipping.")
            return []

        client = create_http_client()
        client.headers["Authorization"] = f"Bearer {token}"

        raw_nodes: list[dict[str, object]] = []
        seen_names: set[str] = set()

        try:
            self._paginate_raw(client, raw_nodes, seen_names, limit)
        finally:
            client.close()

        return raw_nodes[:limit]

    def scrape(self, limit: int = 100) -> list[ScrapedProduct]:
        raw_nodes = self.scrape_raw(limit=limit)
        products: list[ScrapedProduct] = []

        for node in raw_nodes:
            product = _node_to_product(node)
            if product is not None:
                products.append(product)

        return products[:limit]

    # -- Pagination core -----------------------------------------------------

    def _paginate_raw(
        self,
        client: httpx.Client,
        raw_nodes: list[dict[str, object]],
        seen_names: set[str],
        limit: int,
    ) -> None:
        """Paginate through all PH posts, collecting AI-relevant node dicts."""
        after_cursor: str | None = None
        page = 0
        skipped = 0

        while len(raw_nodes) < limit and page < _MAX_PAGES:
            page += 1

            variables: dict[str, Any] = {
                "first": _PAGE_SIZE,
                "postedAfter": _EPOCH,
            }
            if after_cursor:
                variables["after"] = after_cursor

            logger.info(
                "Fetching page %d (%d AI products so far, %d skipped)",
                page,
                len(raw_nodes),
                skipped,
            )

            try:
                response = client.post(
                    self.API_URL,
                    json={"query": self.QUERY, "variables": variables},
                )
            except httpx.TransportError as exc:
                logger.warning("Network error on page %d: %s", page, exc)
                break

            if not response.is_success:
                logger.warning("HTTP %d on page %d", response.status_code, page)
                break

            self._check_rate_limit(response)

            data = response.json()

            if data.get("errors"):
                msgs = [e.get("message", "") for e in data["errors"]]
                logger.warning("GraphQL errors on page %d: %s", page, "; ".join(msgs))
                if not data.get("data"):
                    break

            posts = data.get("data", {}).get("posts") or {}
            edges = posts.get("edges", [])
            page_info = posts.get("pageInfo", {})

            if not edges:
                break

            for edge in edges:
                if len(raw_nodes) >= limit:
                    break
                node = edge.get("node", {})
                name = node.get("name", "")

                if not name or name.lower() in seen_names:
                    skipped += 1
                    continue

                # AI-relevance gate
                tagline = node.get("tagline") or ""
                description = node.get("description") or ""
                text = f"{name} {tagline} {description}"
                if not _AI_SIGNALS.search(text):
                    skipped += 1
                    continue

                seen_names.add(name.lower())
                raw_nodes.append(dict(node))

            if not page_info.get("hasNextPage"):
                logger.info("Reached end of posts archive at page %d", page)
                break
            after_cursor = page_info.get("endCursor")
            if not after_cursor:
                break

            time.sleep(DEFAULT_REQUEST_DELAY)

        logger.info(
            "Done: %d AI products collected, %d non-AI skipped across %d pages",
            len(raw_nodes),
            skipped,
            page,
        )

    # -- Rate-limit protection -----------------------------------------------

    @staticmethod
    def _check_rate_limit(response: httpx.Response) -> None:
        """Pause if the PH API rate-limit budget is running low."""
        remaining_str = response.headers.get("X-Rate-Limit-Remaining", "")
        if not remaining_str:
            return
        try:
            remaining = int(remaining_str)
        except ValueError:
            return

        if remaining < _RATE_LIMIT_FLOOR:
            wait_secs = 60  # default fallback
            reset_str = response.headers.get("X-Rate-Limit-Reset", "")
            if reset_str:
                with contextlib.suppress(ValueError):
                    reset_epoch = int(reset_str)
                    wait_secs = max(1, reset_epoch - int(time.time()))
            wait_secs = min(wait_secs, _MAX_RATE_LIMIT_WAIT)
            logger.warning(
                "PH rate limit approaching (%d remaining), waiting %ds",
                remaining,
                wait_secs,
            )
            time.sleep(wait_secs)


def _node_to_product(node: dict[str, object]) -> ScrapedProduct | None:
    """Convert a raw GraphQL node dict to a ScrapedProduct."""
    name = str(node.get("name", "")).strip()
    if not name:
        return None

    raw_makers = node.get("makers")
    maker_list: list[object] = list(raw_makers) if isinstance(raw_makers, list) else []
    makers = tuple(
        {"name": m["name"], "title": "Maker", "is_founder": False}
        for m in maker_list
        if isinstance(m, dict) and m.get("name")
    )

    website = node.get("website")
    votes = node.get("votesCount", 0)
    tagline = str(node.get("tagline") or "")
    description = str(node.get("description") or "")

    return ScrapedProduct(
        name=name,
        source="producthunt",
        source_url=str(node.get("url", "")),
        source_tier=SourceTier.T2_OPEN_WEB,
        product_url=str(website) if website else None,
        company_website=str(website) if website else None,
        description=tagline or description,
        key_people=makers,
        tags=("generative-ai",),
        status="active",
        extra={"producthunt_votes": str(votes)},
    )
