#!/usr/bin/env python3
"""Migrate all product JSON files to a single SQLite database.

Usage:
    python scripts/migrate_json_to_sqlite.py             # Run migration
    python scripts/migrate_json_to_sqlite.py --verify    # Verify round-trip fidelity
    python scripts/migrate_json_to_sqlite.py --dry-run   # Preview without writing DB

This script reads every JSON file in data/products/, converts each to a DB
row via ProductDB.dict_to_row(), bulk-inserts them, then optionally verifies
that row_to_dict() round-trips produce identical data.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.config import DB_FILE, PRODUCTS_DIR  # noqa: E402
from scrapers.db import ProductDB  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_all_products(products_dir: Path) -> list[dict]:
    """Load all product JSON files from disk."""
    products = []
    errors = 0
    for filepath in sorted(products_dir.glob("*.json")):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            products.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping %s: %s", filepath.name, e)
            errors += 1
    return products


def _normalize_for_comparison(data: dict) -> dict:
    """Normalize a product dict for comparison by removing non-essential differences.

    Handles:
    - Sorting keys for consistent comparison
    - Converting numeric types (int/float equivalence for 0/0.0)
    - Removing empty containers that may not survive round-trip
    """
    result = json.loads(json.dumps(data, sort_keys=True, default=str))
    return result


def verify_roundtrip(db: ProductDB, original_products: list[dict]) -> tuple[int, int]:
    """Verify that every product round-trips through DB correctly.

    Returns (pass_count, fail_count).
    """
    passed = 0
    failed = 0

    for original in original_products:
        slug = original.get("slug", "")
        if not slug:
            continue

        reconstructed = db.get(slug)
        if reconstructed is None:
            logger.error("MISSING in DB: %s", slug)
            failed += 1
            continue

        # Normalize both for comparison
        orig_norm = _normalize_for_comparison(original)
        recon_norm = _normalize_for_comparison(reconstructed)

        # Compare key fields that must survive round-trip
        critical_fields = [
            "slug",
            "name",
            "name_zh",
            "product_url",
            "description",
            "description_zh",
            "product_type",
            "category",
            "status",
        ]
        field_ok = True
        for field in critical_fields:
            orig_val = orig_norm.get(field)
            recon_val = recon_norm.get(field)
            if orig_val != recon_val:
                logger.error(
                    "MISMATCH %s.%s: %r -> %r",
                    slug,
                    field,
                    orig_val,
                    recon_val,
                )
                field_ok = False

        # Check nested company fields
        orig_company = orig_norm.get("company", {})
        recon_company = recon_norm.get("company", {})
        for field in ("name", "url", "website", "founded_year"):
            if orig_company.get(field) != recon_company.get(field):
                logger.error(
                    "MISMATCH %s.company.%s: %r -> %r",
                    slug,
                    field,
                    orig_company.get(field),
                    recon_company.get(field),
                )
                field_ok = False

        # Check tags array
        orig_tags = sorted(orig_norm.get("tags", []))
        recon_tags = sorted(recon_norm.get("tags", []))
        if orig_tags != recon_tags:
            logger.error(
                "MISMATCH %s.tags: %d -> %d items",
                slug,
                len(orig_tags),
                len(recon_tags),
            )
            field_ok = False

        # Check funding
        orig_funding = (
            orig_norm.get("company", {}).get("funding", {}).get("total_raised_usd", 0)
        )
        recon_funding = (
            recon_norm.get("company", {}).get("funding", {}).get("total_raised_usd", 0)
        )
        if orig_funding != recon_funding:
            logger.error(
                "MISMATCH %s.funding: %r -> %r", slug, orig_funding, recon_funding
            )
            field_ok = False

        if field_ok:
            passed += 1
        else:
            failed += 1

    return passed, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate product JSONs to SQLite")
    parser.add_argument(
        "--verify", action="store_true", help="Verify round-trip fidelity"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Load and count without writing"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Override DB path (default: data/products.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else DB_FILE

    logger.info("Loading product JSON files from %s...", PRODUCTS_DIR)
    t0 = time.time()
    products = load_all_products(PRODUCTS_DIR)
    load_time = time.time() - t0
    logger.info("Loaded %d products in %.1fs", len(products), load_time)

    if not products:
        logger.error("No products found in %s", PRODUCTS_DIR)
        sys.exit(1)

    if args.dry_run:
        logger.info("[DRY RUN] Would migrate %d products to %s", len(products), db_path)
        return

    # Remove existing DB to start fresh
    if db_path.exists():
        db_path.unlink()
        logger.info("Removed existing database: %s", db_path)

    logger.info("Creating database at %s...", db_path)
    with ProductDB(db_path) as db:
        db.init_schema()

        t0 = time.time()
        count = db.upsert_batch(products)
        insert_time = time.time() - t0
        logger.info("Inserted %d products in %.1fs", count, insert_time)

        # Rebuild FTS index for good measure
        t0 = time.time()
        db.rebuild_fts()
        fts_time = time.time() - t0
        logger.info("FTS index rebuilt in %.1fs", fts_time)

        # Summary
        db_size_mb = db_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Migration complete: %d products, %.1f MB database",
            count,
            db_size_mb,
        )

        if args.verify:
            logger.info("Verifying round-trip fidelity...")
            t0 = time.time()
            passed, failed = verify_roundtrip(db, products)
            verify_time = time.time() - t0
            logger.info(
                "Verification: %d passed, %d failed in %.1fs",
                passed,
                failed,
                verify_time,
            )
            if failed > 0:
                logger.error(
                    "VERIFICATION FAILED: %d/%d products have round-trip mismatches",
                    failed,
                    passed + failed,
                )
                sys.exit(1)
            logger.info("All %d products verified successfully!", passed)


if __name__ == "__main__":
    main()
