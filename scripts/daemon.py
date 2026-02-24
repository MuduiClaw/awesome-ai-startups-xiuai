#!/usr/bin/env python3
"""Stage B: Daily incremental scrape + Phase 7 enrichment service.

Discovers new products from all enabled sources, enriches them via Phase 7
(Claude CLI), and keeps JSON files + SQLite up to date.

Designed to run once daily. Can be triggered by:
  - Windows Task Scheduler
  - Manual invocation
  - A simple loop with --loop flag

The script is safe to interrupt (Ctrl+C) and resume — Phase 7 uses
checkpoint files, and the candidate filter skips already-enriched products.

Usage:
    # Single daily run:
    python scripts/daemon.py

    # Run continuously (once per day, stays alive):
    python scripts/daemon.py --loop

    # Scrape only, skip enrichment:
    python scripts/daemon.py --skip-enrich

    # Limit enrichment (e.g. only 20 new products):
    python scripts/daemon.py --enrich-limit 20

    # Test with dry run:
    python scripts/daemon.py --dry-run
"""

from __future__ import annotations

import argparse
import datetime
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent

logger = logging.getLogger("daemon")

# Sources to scrape each cycle
DEFAULT_SOURCES = [
    "producthunt",
    "toolify",
    "theresanaiforthat",
    "aibot",
    "ainav",
    "google_play",
    "app_store",
]

# Incremental scrape limit per source (catch new products only)
DEFAULT_SCRAPE_LIMIT = 50
PAUSE_BETWEEN_SOURCES = 15  # seconds

# Shutdown flag for graceful exit
_shutdown_requested = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown_requested  # noqa: PLW0603
    logger.info("Received signal %d, requesting graceful shutdown...", signum)
    _shutdown_requested = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def _run_cmd(args: list[str], *, label: str, dry_run: bool = False) -> bool:
    """Run a subprocess command. Returns True on success."""
    if dry_run:
        logger.info("[DRY-RUN] Would run: %s", " ".join(args))
        return True
    logger.info("Running: %s", " ".join(args))
    try:
        result = subprocess.run(args, cwd=str(_PROJECT_ROOT), check=False)
        if result.returncode != 0:
            logger.error("[%s] Failed with exit code %d", label, result.returncode)
            return False
        return True
    except FileNotFoundError:
        logger.error("[%s] Command not found: %s", label, args[0])
        return False


def run_incremental_scrape(
    sources: list[str],
    limit: int,
    dry_run: bool = False,
) -> dict[str, bool]:
    """Scrape all sources with a small limit to catch new products."""
    results: dict[str, bool] = {}
    for i, source in enumerate(sources):
        if _shutdown_requested:
            logger.info("Shutdown requested, stopping scrape cycle")
            break
        logger.info(
            "--- Scraping %d/%d: %s (limit=%d) ---",
            i + 1,
            len(sources),
            source,
            limit,
        )
        cmd = [
            sys.executable,
            "-m",
            "scrapers.cli",
            "scrape",
            "--source",
            source,
            "--limit",
            str(limit),
        ]
        if dry_run:
            cmd.append("--dry-run")
        results[source] = _run_cmd(cmd, label=f"scrape-{source}", dry_run=False)

        if i < len(sources) - 1 and not _shutdown_requested:
            time.sleep(PAUSE_BETWEEN_SOURCES)

    return results


def run_phase7_enrich(
    *,
    limit: int | None = None,
    backend: str = "cli",
    rate_limit_delay: float = 0.5,
    dry_run: bool = False,
) -> bool:
    """Run Phase 7 enrichment on un-enriched products."""
    logger.info("--- Phase 7 enrichment ---")
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
    if limit is not None:
        cmd.extend(["--limit", str(limit)])
    if dry_run:
        cmd.append("--dry-run")
    return _run_cmd(cmd, label="phase-7")


def run_post_tasks(dry_run: bool = False) -> None:
    """Rebuild DB and regenerate stats after data changes."""
    _run_cmd(
        [sys.executable, "-m", "scrapers.cli", "init-db"],
        label="init-db",
        dry_run=dry_run,
    )
    _run_cmd(
        [sys.executable, "-m", "scrapers.cli", "generate-stats"],
        label="generate-stats",
        dry_run=dry_run,
    )


def run_one_cycle(
    *,
    sources: list[str],
    scrape_limit: int,
    enrich_limit: int | None,
    skip_scrape: bool,
    skip_enrich: bool,
    backend: str,
    rate_limit_delay: float,
    dry_run: bool,
) -> None:
    """Execute one full daily cycle: scrape -> enrich -> rebuild."""
    start = time.monotonic()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("=" * 60)
    logger.info("Daily cycle started at %s", now)
    logger.info("=" * 60)

    # Step 1: Incremental scrape
    if not skip_scrape and not _shutdown_requested:
        scrape_results = run_incremental_scrape(
            sources,
            limit=scrape_limit,
            dry_run=dry_run,
        )
        succeeded = sum(1 for v in scrape_results.values() if v)
        logger.info("Scrape: %d/%d sources OK", succeeded, len(scrape_results))

    # Step 2: Phase 7 enrichment on new/un-enriched products
    if not skip_enrich and not _shutdown_requested:
        run_phase7_enrich(
            limit=enrich_limit,
            backend=backend,
            rate_limit_delay=rate_limit_delay,
            dry_run=dry_run,
        )

    # Step 3: Rebuild DB + stats
    if not _shutdown_requested:
        run_post_tasks(dry_run=dry_run)

    elapsed = time.monotonic() - start
    logger.info("=" * 60)
    logger.info("Daily cycle complete in %.1f minutes", elapsed / 60)
    logger.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage B: Daily incremental scrape + Phase 7 enrichment",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously (sleep between cycles, default: run once and exit)",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=24.0,
        help="Hours between cycles when --loop is set (default: 24)",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip scraping (only run enrichment)",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip enrichment (only scrape)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default=None,
        help=f"Comma-separated sources (default: all {len(DEFAULT_SOURCES)})",
    )
    parser.add_argument(
        "--scrape-limit",
        type=int,
        default=DEFAULT_SCRAPE_LIMIT,
        help=f"Max products per source per cycle (default: {DEFAULT_SCRAPE_LIMIT})",
    )
    parser.add_argument(
        "--enrich-limit",
        type=int,
        default=None,
        help="Max products to enrich per cycle (default: no limit)",
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
        "--dry-run",
        action="store_true",
        help="Preview actions without writing data",
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
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sources = (
        [s.strip() for s in args.sources.split(",")]
        if args.sources
        else DEFAULT_SOURCES
    )

    cycle_kwargs = {
        "sources": sources,
        "scrape_limit": args.scrape_limit,
        "enrich_limit": args.enrich_limit,
        "skip_scrape": args.skip_scrape,
        "skip_enrich": args.skip_enrich,
        "backend": args.backend,
        "rate_limit_delay": args.rate_limit_delay,
        "dry_run": args.dry_run,
    }

    if not args.loop:
        # Single run mode
        run_one_cycle(**cycle_kwargs)
        return

    # Loop mode: run cycle, sleep, repeat
    logger.info("Daemon starting in loop mode (interval: %.1fh)", args.interval_hours)
    interval_secs = args.interval_hours * 3600

    while not _shutdown_requested:
        run_one_cycle(**cycle_kwargs)

        if _shutdown_requested:
            break

        logger.info(
            "Next cycle in %.1f hours. Ctrl+C to stop.",
            args.interval_hours,
        )
        # Sleep in short intervals to check shutdown flag
        sleep_until = time.monotonic() + interval_secs
        while time.monotonic() < sleep_until and not _shutdown_requested:
            time.sleep(10)

    logger.info("Daemon stopped gracefully.")


if __name__ == "__main__":
    main()
