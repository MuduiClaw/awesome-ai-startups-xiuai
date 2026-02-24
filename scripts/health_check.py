#!/usr/bin/env python3
"""Stage C: Daily health check for existing product data.

Rule-based checks that update volatile fields WITHOUT any LLM calls:
  - url:        HTTP HEAD on product_url → detect dead products
  - appstore:   Re-scrape Google Play / App Store → refresh ratings & downloads
  - crunchbase: Re-scrape Crunchbase via Firecrawl → refresh funding data
  - hiring:     HTTP HEAD on careers_url → detect dead careers pages
  - status:     Infer status changes from URL check results

Designed to run daily in GitHub Actions. Updates JSON files directly.

Usage:
    python scripts/health_check.py --check all
    python scripts/health_check.py --check url --limit 500
    python scripts/health_check.py --check crunchbase --limit 100
    python scripts/health_check.py --check appstore,hiring
    python scripts/health_check.py --check all --dry-run
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scrapers.config import PRODUCTS_DIR  # noqa: E402

logger = logging.getLogger("health_check")

# Concurrency for URL checks
URL_CHECK_CONCURRENCY = 10
URL_CHECK_TIMEOUT = 15  # seconds
URL_CHECK_DOMAIN_DELAY = 0.5  # seconds between requests to same domain

# Consecutive failures before marking as deprecated
CONSECUTIVE_FAILURES_THRESHOLD = 3

ALL_CHECKS = ["url", "appstore", "crunchbase", "hiring", "status"]


# ---------------------------------------------------------------------------
# Utility: load / save product JSON
# ---------------------------------------------------------------------------


def _load_product(slug: str) -> dict[str, Any] | None:
    """Load a single product JSON by slug."""
    path = PRODUCTS_DIR / f"{slug}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load %s: %s", slug, e)
        return None


def _save_product(slug: str, data: dict[str, Any]) -> None:
    """Save a product JSON, updating last_updated timestamp."""
    data.setdefault("meta", {})["last_updated"] = datetime.datetime.now(
        tz=datetime.UTC
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = PRODUCTS_DIR / f"{slug}.json"
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _all_product_slugs() -> list[str]:
    """List all product slugs from the data/products/ directory."""
    return sorted(p.stem for p in PRODUCTS_DIR.glob("*.json") if p.stem != "index")


# ---------------------------------------------------------------------------
# Check: URL liveness
# ---------------------------------------------------------------------------


def check_url_liveness(
    slugs: list[str],
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """HTTP HEAD check on product_url for each product."""
    import httpx

    stats = {"checked": 0, "alive": 0, "dead": 0, "error": 0, "updated": 0}
    targets: list[tuple[str, dict[str, Any]]] = []

    for slug in slugs:
        product = _load_product(slug)
        if product and product.get("product_url"):
            targets.append((slug, product))
    if limit:
        targets = targets[:limit]

    logger.info("URL check: %d products to check", len(targets))

    client = httpx.Client(
        timeout=URL_CHECK_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "AIProductData-HealthCheck/1.0"},
    )

    try:
        for i, (slug, product) in enumerate(targets):
            url = product["product_url"]
            try:
                resp = client.head(url)
                status_code = resp.status_code
            except (httpx.HTTPError, httpx.InvalidURL):
                status_code = 0  # network error

            stats["checked"] += 1
            if 200 <= status_code < 400:
                stats["alive"] += 1
            elif status_code == 0:
                stats["error"] += 1
            else:
                stats["dead"] += 1

            # Track consecutive failures in meta
            meta = product.setdefault("meta", {})
            prev_failures = meta.get("url_consecutive_failures", 0)

            if status_code == 0 or status_code >= 400:
                meta["url_consecutive_failures"] = prev_failures + 1
                meta["url_status"] = status_code
            else:
                meta["url_consecutive_failures"] = 0
                meta["url_status"] = status_code

            meta["url_last_checked"] = datetime.datetime.now(
                tz=datetime.UTC
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            changed = (
                meta.get("url_consecutive_failures", 0) != prev_failures
                or meta.get("url_status") != status_code
            )
            if changed and not dry_run:
                _save_product(slug, product)
                stats["updated"] += 1

            if (i + 1) % 100 == 0:
                logger.info(
                    "URL check progress: %d/%d (alive=%d, dead=%d)",
                    i + 1,
                    len(targets),
                    stats["alive"],
                    stats["dead"],
                )

            # Rate limiting
            time.sleep(URL_CHECK_DOMAIN_DELAY)
    finally:
        client.close()

    logger.info(
        "URL check done: %d checked, %d alive, %d dead, %d errors, %d updated",
        stats["checked"],
        stats["alive"],
        stats["dead"],
        stats["error"],
        stats["updated"],
    )
    return stats


# ---------------------------------------------------------------------------
# Check: App Store refresh
# ---------------------------------------------------------------------------


def check_appstore(
    slugs: list[str],
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Re-scrape Google Play / App Store for products that have app store data."""
    from scrapers.enrichment import Merger, Normalizer
    from scrapers.enrichment.cross_validator import CrossValidator
    from scrapers.enrichment.normalizer import PlausibilityValidator

    stats = {"checked": 0, "updated": 0, "errors": 0}

    # Run Google Play scraper
    try:
        from scrapers.sources.app_stores import AppStoreScraper, GooglePlayScraper
    except ImportError:
        logger.warning("App store dependencies not installed, skipping")
        return stats

    normalizer = Normalizer()
    plausibility = PlausibilityValidator()

    for scraper_cls, label in [
        (GooglePlayScraper, "google_play"),
        (AppStoreScraper, "app_store"),
    ]:
        scraper_limit = limit or 100
        logger.info("Running %s scraper (limit=%d)...", label, scraper_limit)
        try:
            scraper = scraper_cls()
            results = scraper.scrape(limit=scraper_limit)
            logger.info("%s: found %d products", label, len(results))
            stats["checked"] += len(results)

            if dry_run:
                logger.info(
                    "[DRY-RUN] Would process %d %s results", len(results), label
                )
                continue

            # Normalize and merge updates through the standard pipeline
            from scrapers.enrichment import Deduplicator

            deduplicator = Deduplicator()
            cross_validator = CrossValidator()
            merger = Merger(cross_validator=cross_validator)

            normalized = [normalizer.normalize(p) for p in results]
            plausible = [
                p for p, _ in ((p, plausibility.validate(p)) for p in normalized)
            ]
            dedup_result = deduplicator.deduplicate(plausible)

            for s, product in dedup_result.updates_for_existing:
                merger.merge_update(s, product)
                stats["updated"] += 1

        except Exception as e:
            logger.error("%s scraper failed: %s", label, e)
            stats["errors"] += 1

    logger.info(
        "App store check done: %d checked, %d updated, %d errors",
        stats["checked"],
        stats["updated"],
        stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# Check: Crunchbase refresh
# ---------------------------------------------------------------------------


def check_crunchbase(
    slugs: list[str],
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Re-scrape Crunchbase for funding/company data updates."""
    stats = {"checked": 0, "updated": 0, "errors": 0}

    try:
        from scrapers.sources.crunchbase import CrunchbaseScraper
    except ImportError:
        logger.warning("Crunchbase scraper not importable, skipping")
        return stats

    scraper_limit = limit or 100
    logger.info("Running Crunchbase scraper (limit=%d)...", scraper_limit)

    try:
        scraper = CrunchbaseScraper()
        results = scraper.scrape(limit=scraper_limit)
        logger.info("Crunchbase: found %d results", len(results))
        stats["checked"] = len(results)

        if dry_run:
            for r in results:
                logger.info(
                    "  [DRY-RUN] %s: raised=%s, round=%s, country=%s",
                    r.name,
                    r.company_total_raised_usd,
                    r.company_last_round,
                    r.company_headquarters_country,
                )
            return stats

        # Merge via standard pipeline
        from scrapers.enrichment import Merger, Normalizer
        from scrapers.enrichment.cross_validator import CrossValidator
        from scrapers.enrichment.normalizer import PlausibilityValidator

        normalizer = Normalizer()
        plausibility = PlausibilityValidator()
        cross_validator = CrossValidator()
        merger = Merger(cross_validator=cross_validator)

        from scrapers.enrichment import Deduplicator

        deduplicator = Deduplicator()
        normalized = [normalizer.normalize(p) for p in results]
        valid = []
        for p in normalized:
            is_valid, _ = plausibility.validate(p)
            if is_valid:
                valid.append(p)
        dedup_result = deduplicator.deduplicate(valid)

        for s, product in dedup_result.updates_for_existing:
            merger.merge_update(s, product)
            stats["updated"] += 1

    except Exception as e:
        logger.error("Crunchbase scraper failed: %s", e)
        stats["errors"] += 1

    logger.info(
        "Crunchbase check done: %d checked, %d updated, %d errors",
        stats["checked"],
        stats["updated"],
        stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# Check: Hiring URL liveness
# ---------------------------------------------------------------------------


def check_hiring(
    slugs: list[str],
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Check careers_url liveness. If 404/410, set is_hiring=false."""
    import httpx

    stats = {"checked": 0, "updated": 0, "still_hiring": 0, "careers_dead": 0}
    targets: list[tuple[str, dict[str, Any]]] = []

    for slug in slugs:
        product = _load_product(slug)
        if not product:
            continue
        hiring = product.get("hiring", {})
        careers_url = hiring.get("careers_url")
        if careers_url and hiring.get("is_hiring") is True:
            targets.append((slug, product))

    if limit:
        targets = targets[:limit]

    logger.info("Hiring check: %d products with careers_url", len(targets))

    client = httpx.Client(
        timeout=URL_CHECK_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "AIProductData-HealthCheck/1.0"},
    )

    try:
        for slug, product in targets:
            careers_url = product["hiring"]["careers_url"]
            try:
                resp = client.head(careers_url)
                status_code = resp.status_code
            except (httpx.HTTPError, httpx.InvalidURL):
                status_code = 0

            stats["checked"] += 1

            if status_code in (404, 410):
                stats["careers_dead"] += 1
                if not dry_run:
                    product["hiring"]["is_hiring"] = False
                    _save_product(slug, product)
                    stats["updated"] += 1
                logger.info(
                    "  %s: careers_url dead (%d) → is_hiring=false", slug, status_code
                )
            else:
                stats["still_hiring"] += 1

            time.sleep(URL_CHECK_DOMAIN_DELAY)
    finally:
        client.close()

    logger.info(
        "Hiring check done: %d checked, %d dead, %d updated",
        stats["checked"],
        stats["careers_dead"],
        stats["updated"],
    )
    return stats


# ---------------------------------------------------------------------------
# Check: Status inference
# ---------------------------------------------------------------------------


def check_status(
    slugs: list[str],
    *,
    dry_run: bool = False,
    **_kwargs: Any,
) -> dict[str, int]:
    """Infer status changes based on accumulated URL check data."""
    stats = {"checked": 0, "deprecated": 0, "updated": 0}

    for slug in slugs:
        product = _load_product(slug)
        if not product:
            continue
        if product.get("status") != "active":
            continue

        stats["checked"] += 1
        meta = product.get("meta", {})
        consecutive_failures = meta.get("url_consecutive_failures", 0)

        if consecutive_failures >= CONSECUTIVE_FAILURES_THRESHOLD:
            url_status = meta.get("url_status", "?")
            logger.info(
                "  %s: %d consecutive URL failures (last status=%s) → deprecated",
                slug,
                consecutive_failures,
                url_status,
            )
            stats["deprecated"] += 1
            if not dry_run:
                product["status"] = "deprecated"
                _save_product(slug, product)
                stats["updated"] += 1

    logger.info(
        "Status check done: %d active checked, %d → deprecated, %d updated",
        stats["checked"],
        stats["deprecated"],
        stats["updated"],
    )
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage C: Daily health check for product data (no LLM)",
    )
    parser.add_argument(
        "--check",
        type=str,
        required=True,
        help=f"Checks to run (comma-separated or 'all'): {', '.join(ALL_CHECKS)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max products to check (per check type)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    checks = (
        ALL_CHECKS
        if args.check == "all"
        else [c.strip() for c in args.check.split(",")]
    )
    unknown = [c for c in checks if c not in ALL_CHECKS]
    if unknown:
        parser.error(
            f"Unknown check(s): {', '.join(unknown)}. Valid: {', '.join(ALL_CHECKS)}"
        )

    slugs = _all_product_slugs()
    logger.info("Loaded %d product slugs", len(slugs))

    all_stats: dict[str, dict[str, int]] = {}

    check_funcs = {
        "url": check_url_liveness,
        "appstore": check_appstore,
        "crunchbase": check_crunchbase,
        "hiring": check_hiring,
        "status": check_status,
    }

    for check_name in checks:
        logger.info("=" * 50)
        logger.info("Running check: %s", check_name)
        logger.info("=" * 50)
        func = check_funcs[check_name]
        all_stats[check_name] = func(
            slugs,
            limit=args.limit,
            dry_run=args.dry_run,
        )

    # Summary
    logger.info("=" * 50)
    logger.info("HEALTH CHECK SUMMARY")
    logger.info("=" * 50)
    for check_name, check_stats in all_stats.items():
        logger.info("  [%s] %s", check_name, check_stats)


if __name__ == "__main__":
    main()
