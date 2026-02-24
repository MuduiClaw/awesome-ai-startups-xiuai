#!/usr/bin/env python3
"""Stage A: One-time full scrape + Phase 7 enrichment.

Orchestrates a complete data seeding pipeline:
  1. Run all enabled scrapers (no limit) to discover every product
  2. Rebuild SQLite database from JSON files
  3. Run Phase 7 deep enrichment on all products (supports --shard for parallel)

Scraping runs sequentially (one source at a time) with pauses between sources.
Phase 7 enrichment supports --shard N/M for parallel terminals.

Usage:
    # Full pipeline (scrape + enrich):
    python scripts/full_init.py

    # Scrape only (skip enrichment):
    python scripts/full_init.py --skip-enrich

    # Enrich only (skip scraping, e.g. resume after scrape completed):
    python scripts/full_init.py --skip-scrape

    # Parallel enrichment across 10 terminals:
    python scripts/full_init.py --skip-scrape --shard 1/10
    python scripts/full_init.py --skip-scrape --shard 2/10
    ...
    python scripts/full_init.py --skip-scrape --shard 10/10

    # Scrape specific sources only:
    python scripts/full_init.py --sources producthunt,toolify --skip-enrich
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

logger = logging.getLogger("full_init")

# Sources to scrape, in recommended order (discovery sources first, then enrichment)
DEFAULT_SOURCES = [
    "producthunt",
    "toolify",
    "theresanaiforthat",
    "aibot",
    "ainav",
    "google_play",
    "app_store",
]

PAUSE_BETWEEN_SOURCES = 30  # seconds


def _run_cmd(args: list[str], *, label: str) -> bool:
    """Run a subprocess command, streaming output. Returns True on success."""
    logger.info("Running: %s", " ".join(args))
    try:
        result = subprocess.run(
            args,
            cwd=str(_PROJECT_ROOT),
            check=False,
        )
        if result.returncode != 0:
            logger.error("[%s] Failed with exit code %d", label, result.returncode)
            return False
        logger.info("[%s] Completed successfully", label)
        return True
    except FileNotFoundError:
        logger.error("[%s] Command not found: %s", label, args[0])
        return False


def run_scrape(sources: list[str], limit: int | None = None) -> dict[str, bool]:
    """Run scrapers sequentially with pauses between sources."""
    results: dict[str, bool] = {}
    for i, source in enumerate(sources):
        logger.info("=== Scraping source %d/%d: %s ===", i + 1, len(sources), source)
        cmd = [sys.executable, "-m", "scrapers.cli", "scrape", "--source", source]
        if limit is not None:
            cmd.extend(["--limit", str(limit)])
        else:
            cmd.extend(["--limit", "99999"])  # effectively no limit

        results[source] = _run_cmd(cmd, label=f"scrape-{source}")

        # Pause between sources to be polite to rate limits
        if i < len(sources) - 1:
            logger.info("Pausing %ds before next source...", PAUSE_BETWEEN_SOURCES)
            time.sleep(PAUSE_BETWEEN_SOURCES)

    return results


def run_init_db() -> bool:
    """Rebuild SQLite database from JSON files."""
    logger.info("=== Rebuilding SQLite database ===")
    return _run_cmd(
        [sys.executable, "-m", "scrapers.cli", "init-db"],
        label="init-db",
    )


def run_generate_stats() -> bool:
    """Regenerate index.json and stats.json."""
    logger.info("=== Regenerating stats ===")
    return _run_cmd(
        [sys.executable, "-m", "scrapers.cli", "generate-stats"],
        label="generate-stats",
    )


def run_phase7(
    *,
    shard: str | None = None,
    limit: int | None = None,
    backend: str = "cli",
    rate_limit_delay: float = 0.5,
) -> bool:
    """Run Phase 7 deep enrichment."""
    logger.info("=== Running Phase 7 deep enrichment ===")
    cmd = [
        sys.executable,
        "scripts/batch_enrich.py",
        "--phase",
        "7",
        "--backend",
        backend,
        "--rate-limit-delay",
        str(rate_limit_delay),
        "--resume",
    ]
    if shard:
        cmd.extend(["--shard", shard])
    if limit is not None:
        cmd.extend(["--limit", str(limit)])

    return _run_cmd(cmd, label="phase-7")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage A: One-time full scrape + Phase 7 enrichment",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip scraping phase (go straight to enrichment)",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrichment phase (scrape only)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=None,
        help=f"Comma-separated sources to scrape (default: all {len(DEFAULT_SOURCES)})",
    )
    parser.add_argument(
        "--scrape-limit",
        type=int,
        default=None,
        help="Max products per source (default: no limit)",
    )
    parser.add_argument(
        "--shard",
        type=str,
        default=None,
        help="Shard partition for Phase 7 (e.g. 1/10). Implies --skip-scrape",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=None,
        help="Max products to enrich in Phase 7",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["api", "cli"],
        default="cli",
        help="LLM backend for Phase 7 (default: cli)",
    )
    parser.add_argument(
        "--rate-limit-delay",
        type=float,
        default=0.5,
        help="Seconds between LLM calls (default: 0.5)",
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

    # --shard implies --skip-scrape (scraping is separate from enrichment shards)
    if args.shard:
        args.skip_scrape = True

    sources = (
        [s.strip() for s in args.sources.split(",")]
        if args.sources
        else DEFAULT_SOURCES
    )

    logger.info("=" * 60)
    logger.info("Stage A: Full Init Pipeline")
    logger.info("  Sources: %s", ", ".join(sources))
    logger.info("  Skip scrape: %s", args.skip_scrape)
    logger.info("  Skip enrich: %s", args.skip_enrich)
    logger.info("  Shard: %s", args.shard or "none (full)")
    logger.info("  Backend: %s", args.backend)
    logger.info("=" * 60)

    # Step 1: Scrape
    if not args.skip_scrape:
        scrape_results = run_scrape(sources, limit=args.scrape_limit)
        succeeded = sum(1 for v in scrape_results.values() if v)
        failed = sum(1 for v in scrape_results.values() if not v)
        logger.info(
            "Scraping complete: %d/%d succeeded, %d failed",
            succeeded,
            len(scrape_results),
            failed,
        )
        for source, ok in scrape_results.items():
            status = "OK" if ok else "FAILED"
            logger.info("  %s: %s", source, status)

        # Step 2: Rebuild DB after scraping
        run_init_db()

    # Step 3: Phase 7 enrichment
    if not args.skip_enrich:
        run_phase7(
            shard=args.shard,
            limit=args.enrich_limit,
            backend=args.backend,
            rate_limit_delay=args.rate_limit_delay,
        )

    # Step 4: Regenerate stats (only if no shard — final step after all shards done)
    if not args.shard:
        run_init_db()
        run_generate_stats()

    logger.info("=" * 60)
    logger.info("Full init pipeline complete!")
    if args.shard:
        logger.info(
            "Note: Run 'aiscrape init-db && aiscrape generate-stats' "
            "after ALL shards finish."
        )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
