"""Shared domain classification constants.

Consolidates app-store, aggregator, and skip-domain sets used by
the deduplicator, merger, and cross-validator.
"""

from __future__ import annotations

# App-store / marketplace pages — never a real product homepage.
APP_STORE_DOMAINS: frozenset[str] = frozenset(
    {
        "play.google.com",
        "apps.apple.com",
        "itunes.apple.com",
    }
)

# Aggregator / directory / search engine domains.
AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "producthunt.com",
        "toolify.ai",
        "theresanaiforthat.com",
        "ai-bot.cn",
        "ainav.cn",
        "futurepedia.io",
        "alternativeto.net",
        "crunchbase.com",
        "pitchbook.com",
        "ycombinator.com",
        "bing.com",
        "google.com",
        "www.bing.com",
        "www.google.com",
    }
)

# Hosting / hub platforms — many independent products share the same domain.
PLATFORM_DOMAINS: frozenset[str] = frozenset(
    {
        "huggingface.co",
        "github.com",
        "gitlab.com",
        "replicate.com",
    }
)

# Union: domains that should be skipped during domain-based deduplication.
SKIP_DOMAINS: frozenset[str] = APP_STORE_DOMAINS | AGGREGATOR_DOMAINS | PLATFORM_DOMAINS


def is_skip_domain(domain: str) -> bool:
    """Return True if *domain* should be excluded from domain-based matching."""
    return domain in SKIP_DOMAINS
