"""Scraper source implementations.

Scrapers are organized by role:
- DiscoveryScraper: Only discovers new products (names + URLs)
- EnrichmentScraper: Enriches existing products with additional data
- UnifiedScraper (BaseScraper): Does both discovery and full scraping
"""

from scrapers.sources.aibot import AiBotScraper
from scrapers.sources.ainav import AiNavScraper
from scrapers.sources.app_stores import AppStoreScraper, GooglePlayScraper

# from scrapers.sources.artificial_analysis import ArtificialAnalysisScraper  # disabled
# from scrapers.sources.crunchbase import CrunchbaseScraper  # disabled
# from scrapers.sources.github_trending import GitHubTrendingScraper  # disabled
# from scrapers.sources.huggingface import HuggingFaceScraper  # disabled
# from scrapers.sources.lmsys import LMSYSScraper  # disabled
# from scrapers.sources.openrouter import OpenRouterScraper  # disabled
# from scrapers.sources.papers_with_code import PapersWithCodeScraper  # disabled
from scrapers.sources.producthunt import ProductHuntScraper

# from scrapers.sources.techcrunch import TechCrunchScraper  # disabled
from scrapers.sources.theresanai import TAAScraper
from scrapers.sources.toolify import ToolifyScraper

# from scrapers.sources.ycombinator import YCombinatorScraper  # disabled

ALL_SCRAPERS = {
    # T1 Authoritative (EnrichmentScraper role)
    # "crunchbase": CrunchbaseScraper,  # disabled
    # T2 Open Web — Discovery role
    "producthunt": ProductHuntScraper,
    # "github": GitHubTrendingScraper,  # disabled
    "toolify": ToolifyScraper,
    "aibot": AiBotScraper,
    "ainav": AiNavScraper,
    # "ycombinator": YCombinatorScraper,  # disabled
    # "techcrunch": TechCrunchScraper,  # disabled
    # T2 Open Web — Unified role (discover + enrich)
    # "huggingface": HuggingFaceScraper,  # disabled
    # "lmsys": LMSYSScraper,  # disabled
    # "openrouter": OpenRouterScraper,  # disabled
    "theresanaiforthat": TAAScraper,
    # "artificial_analysis": ArtificialAnalysisScraper,  # disabled
    # "papers_with_code": PapersWithCodeScraper,  # disabled
    # T2 Open Web — Enrichment role (app stores)
    "google_play": GooglePlayScraper,
    "app_store": AppStoreScraper,
}

__all__ = [
    "ALL_SCRAPERS",
    "AiBotScraper",
    "AiNavScraper",
    "AppStoreScraper",
    # "ArtificialAnalysisScraper",  # disabled
    # "CrunchbaseScraper",  # disabled
    # "GitHubTrendingScraper",  # disabled
    "GooglePlayScraper",
    # "HuggingFaceScraper",  # disabled
    # "LMSYSScraper",  # disabled
    # "OpenRouterScraper",  # disabled
    # "PapersWithCodeScraper",  # disabled
    "ProductHuntScraper",
    "TAAScraper",
    # "TechCrunchScraper",  # disabled
    "ToolifyScraper",
    # "YCombinatorScraper",  # disabled
]
