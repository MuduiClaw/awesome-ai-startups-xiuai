"""SQLite database layer for products.

Provides ProductDB — a single class that handles CRUD operations,
dict↔row conversion, FTS search, and aggregation queries.  Designed
as a drop-in replacement for the JSON-file-based data layer.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from scrapers.config import DB_FILE, SCHEMA_DIR

logger = logging.getLogger(__name__)

# Batch size for bulk inserts during migration.
_BATCH_SIZE = 500

# ---------------------------------------------------------------------------
# Column mapping: product JSON path -> SQL column name
# ---------------------------------------------------------------------------

# Scalar fields: JSON dotted path -> SQL column name
_SCALAR_MAP: dict[str, str] = {
    "slug": "slug",
    "name": "name",
    "name_zh": "name_zh",
    "product_url": "product_url",
    "icon_url": "icon_url",
    "description": "description",
    "description_zh": "description_zh",
    "product_type": "product_type",
    "category": "category",
    "sub_category": "sub_category",
    "status": "status",
    "company.name": "company_name",
    "company.name_zh": "company_name_zh",
    "company.url": "company_url",
    "company.website": "company_website",
    "company.wikipedia_url": "company_wikipedia_url",
    "company.logo_url": "company_logo_url",
    "company.description": "company_description",
    "company.founded_year": "company_founded_year",
    "company.headquarters.city": "company_hq_city",
    "company.headquarters.country": "company_hq_country",
    "company.headquarters.country_code": "company_hq_country_code",
    "company.employee_count_range": "company_employee_count_range",
    "company.funding.total_raised_usd": "funding_total_raised_usd",
    "company.funding.last_round": "funding_last_round",
    "company.funding.last_round_date": "funding_last_round_date",
    "company.funding.valuation_usd": "funding_valuation_usd",
    "open_source": "open_source",
    "license": "license",
    "repository_url": "repository_url",
    "github_stars": "github_stars",
    "github_contributors": "github_contributors",
    "architecture": "architecture",
    "parameter_count": "parameter_count",
    "context_window": "context_window",
    "api_available": "api_available",
    "api_docs_url": "api_docs_url",
    "pricing.model": "pricing_model",
    "pricing.has_free_tier": "has_free_tier",
    "release_date": "release_date",
    "meta.added_date": "added_date",
    "meta.last_updated": "last_updated",
    "meta.data_quality_score": "data_quality_score",
    "meta.needs_review": "needs_review",
}

# JSON array/object fields: JSON key -> SQL column name
_JSON_MAP: dict[str, str] = {
    "tags": "tags_json",
    "keywords": "keywords_json",
    "key_people": "key_people_json",
    "modalities": "modalities_json",
    "supported_languages": "supported_languages_json",
    "platforms": "platforms_json",
    "target_audience": "target_audience_json",
    "use_cases": "use_cases_json",
    "competitors": "competitors_json",
    "based_on": "based_on_json",
    "used_by": "used_by_json",
    "sources": "sources_json",
    "hiring": "hiring_json",
    "app_store": "app_store_json",
}

# Nested JSON fields stored separately
_NESTED_JSON_MAP: dict[str, str] = {
    "meta.provenance": "provenance_json",
    "company.social": "social_json",
    "company.funding.investors": "funding_investors_json",
}

# Boolean columns that need int conversion
_BOOL_COLUMNS: frozenset[str] = frozenset(
    {"open_source", "api_available", "has_free_tier", "needs_review"}
)


def _get_nested(data: dict[str, Any], path: str) -> Any:
    """Retrieve a value from *data* following a dotted *path*."""
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _set_nested(data: dict[str, Any], path: str, value: Any) -> None:
    """Set a value inside *data* at the given dotted *path*."""
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        current = current.setdefault(key, {})
    current[keys[-1]] = value


# ---------------------------------------------------------------------------
# ProductDB
# ---------------------------------------------------------------------------


class ProductDB:
    """SQLite-backed product database with dict↔row conversion and FTS5 search."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else DB_FILE
        self._conn: sqlite3.Connection | None = None

    # -- connection management ----------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-open connection with WAL mode and row factory."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> ProductDB:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # -- schema initialization ----------------------------------------------

    def init_schema(self) -> None:
        """Create tables, indexes, FTS, and triggers from the DDL file."""
        ddl_path = SCHEMA_DIR / "products.sql"
        ddl = ddl_path.read_text(encoding="utf-8")
        self.conn.executescript(ddl)
        logger.info("Schema initialized from %s", ddl_path)

    # -- dict ↔ row conversion ----------------------------------------------

    def dict_to_row(self, data: dict[str, Any]) -> dict[str, Any]:
        """Flatten a nested product dict into a flat row dict for SQL INSERT.

        Scalar fields are extracted via dotted-path traversal.
        Array/object fields are serialized to JSON strings.
        Booleans are converted to 0/1 integers.
        """
        row: dict[str, Any] = {}

        # Scalar fields
        for json_path, col in _SCALAR_MAP.items():
            value = _get_nested(data, json_path)
            if col in _BOOL_COLUMNS and value is not None:
                value = int(bool(value))
            row[col] = value

        # JSON array/object fields
        for json_key, col in _JSON_MAP.items():
            value = data.get(json_key)
            if value is not None:
                row[col] = json.dumps(value, ensure_ascii=False)
            else:
                # Use default from schema (empty array or object)
                row[col] = (
                    "[]"
                    if col.endswith("_json")
                    and col not in ("hiring_json", "app_store_json")
                    else "{}"
                )

        # Nested JSON fields
        for json_path, col in _NESTED_JSON_MAP.items():
            value = _get_nested(data, json_path)
            if value is not None:
                row[col] = json.dumps(value, ensure_ascii=False)
            else:
                row[col] = "[]" if col == "funding_investors_json" else "{}"

        return row

    def row_to_dict(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        """Reconstruct a full nested product dict from a flat SQL row.

        Reverses dict_to_row: scalar columns are placed at their dotted
        paths, JSON columns are deserialized, and booleans are restored.
        """
        if isinstance(row, sqlite3.Row):
            row = dict(row)

        data: dict[str, Any] = {}

        # Scalar fields: column -> nested path
        reverse_scalar = {col: path for path, col in _SCALAR_MAP.items()}
        for col, json_path in reverse_scalar.items():
            value = row.get(col)
            if value is None:
                continue
            # Restore booleans
            if col in _BOOL_COLUMNS:
                value = bool(value)
            _set_nested(data, json_path, value)

        # JSON array/object fields
        reverse_json = {col: key for key, col in _JSON_MAP.items()}
        for col, json_key in reverse_json.items():
            raw = row.get(col)
            if raw:
                with contextlib.suppress(json.JSONDecodeError):
                    data[json_key] = json.loads(raw)

        # Nested JSON fields
        reverse_nested = {col: path for path, col in _NESTED_JSON_MAP.items()}
        for col, json_path in reverse_nested.items():
            raw = row.get(col)
            if raw:
                try:
                    parsed = json.loads(raw)
                    if parsed:  # skip empty containers
                        _set_nested(data, json_path, parsed)
                except json.JSONDecodeError:
                    pass

        # Clean up empty containers to match original JSON style
        self._clean_empty(data)

        return data

    @staticmethod
    def _clean_empty(data: dict[str, Any]) -> None:
        """Remove empty dicts/lists and None-value top-level keys."""
        # Remove empty top-level arrays
        for key in list(data.keys()):
            if isinstance(data[key], list) and not data[key]:
                del data[key]

        # Remove empty nested dicts (e.g., company with no fields)
        for key in list(data.keys()):
            if isinstance(data[key], dict) and not data[key]:
                del data[key]

        # Recursively clean nested dicts
        for key in list(data.keys()):
            if isinstance(data[key], dict):
                ProductDB._clean_empty(data[key])
                if not data[key]:
                    del data[key]

    # -- CRUD operations ----------------------------------------------------

    def upsert(self, data: dict[str, Any]) -> None:
        """Insert or replace a product.  Expects a full product dict."""
        row = self.dict_to_row(data)
        columns = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in columns)
        col_list = ", ".join(columns)
        sql = f"INSERT OR REPLACE INTO products ({col_list}) VALUES ({placeholders})"
        self.conn.execute(sql, row)
        self.conn.commit()

    def upsert_batch(self, products: list[dict[str, Any]]) -> int:
        """Bulk upsert products in batches.  Returns count of inserted rows."""
        if not products:
            return 0

        count = 0
        for i in range(0, len(products), _BATCH_SIZE):
            batch = products[i : i + _BATCH_SIZE]
            rows = [self.dict_to_row(p) for p in batch]
            columns = list(rows[0].keys())
            placeholders = ", ".join(f":{c}" for c in columns)
            col_list = ", ".join(columns)
            sql = (
                f"INSERT OR REPLACE INTO products ({col_list}) VALUES ({placeholders})"
            )
            self.conn.executemany(sql, rows)
            self.conn.commit()
            count += len(batch)
            logger.info("Upserted batch %d-%d (%d total)", i, i + len(batch), count)

        return count

    def get(self, slug: str) -> dict[str, Any] | None:
        """Get a single product by slug.  Returns None if not found."""
        row = self.conn.execute(
            "SELECT * FROM products WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None:
            return None
        return self.row_to_dict(row)

    def delete(self, slug: str) -> bool:
        """Delete a product by slug.  Returns True if a row was deleted."""
        cursor = self.conn.execute("DELETE FROM products WHERE slug = ?", (slug,))
        self.conn.commit()
        return cursor.rowcount > 0

    def exists(self, slug: str) -> bool:
        """Check if a product exists by slug."""
        row = self.conn.execute(
            "SELECT 1 FROM products WHERE slug = ?", (slug,)
        ).fetchone()
        return row is not None

    def count(self) -> int:
        """Return the total number of products."""
        row = self.conn.execute("SELECT COUNT(*) FROM products").fetchone()
        return row[0] if row else 0

    def all_slugs(self) -> list[str]:
        """Return all product slugs, sorted alphabetically."""
        rows = self.conn.execute("SELECT slug FROM products ORDER BY slug").fetchall()
        return [r[0] for r in rows]

    # -- dedup index queries ------------------------------------------------

    def get_dedup_index(self) -> dict[str, Any]:
        """Load deduplication data: domains, names, name_zh for all products.

        Uses root-domain extraction and skips store/aggregator domains
        to avoid false-positive matches on shared mega-domains.

        Returns a dict with keys:
            domains: dict[str, str]  (root domain -> slug)
            names: dict[str, str]    (lowercase name -> slug)
            names_zh: dict[str, str] (name_zh -> slug)
        """
        rows = self.conn.execute(
            "SELECT slug, name, name_zh, product_url, company_website " "FROM products"
        ).fetchall()

        from scrapers.utils import extract_domain, extract_root_domain
        from scrapers.utils.domains import is_skip_domain

        domains: dict[str, str] = {}
        names: dict[str, str] = {}
        names_zh: dict[str, str] = {}

        for row in rows:
            slug = row["slug"]
            name = row["name"] or ""
            name_zh = row["name_zh"] or ""
            product_url = row["product_url"] or ""
            company_website = row["company_website"] or ""

            if name:
                names[name.lower()] = slug
            if name_zh:
                names_zh[name_zh] = slug
            if product_url:
                orig = extract_domain(product_url)
                if orig and not is_skip_domain(orig):
                    root = extract_root_domain(product_url)
                    if root:
                        domains[root] = slug
            if company_website:
                orig = extract_domain(company_website)
                if orig and not is_skip_domain(orig):
                    root = extract_root_domain(company_website)
                    if root:
                        domains[root] = slug

        return {"domains": domains, "names": names, "names_zh": names_zh}

    # -- cross-validator index queries --------------------------------------

    def get_cross_validation_index(self) -> dict[str, Any]:
        """Load cross-validation data for all products.

        Returns a dict with keys:
            names: dict[str, str]           (lowercase name -> slug)
            names_zh: dict[str, str]        (name_zh -> slug)
            urls: dict[str, str]            (product_url -> slug)
            descriptions: dict[str, str]    (slug -> description)
            descriptions_zh: dict[str, str] (slug -> description_zh)
            company_data: dict[str, dict]   (company_name -> first seen data)
        """
        rows = self.conn.execute(
            "SELECT slug, name, name_zh, product_url, description, description_zh, "
            "company_name, company_name_zh, company_hq_country, company_founded_year "
            "FROM products"
        ).fetchall()

        names: dict[str, str] = {}
        names_zh: dict[str, str] = {}
        urls: dict[str, str] = {}
        descriptions: dict[str, str] = {}
        descriptions_zh: dict[str, str] = {}
        company_data: dict[str, dict[str, Any]] = {}

        for row in rows:
            slug = row["slug"]
            name = row["name"] or ""
            if name:
                names[name.lower()] = slug
            name_zh_val = row["name_zh"] or ""
            if name_zh_val:
                names_zh[name_zh_val] = slug
            product_url = row["product_url"] or ""
            if product_url:
                urls[product_url] = slug
            desc = row["description"] or ""
            if desc and len(desc) >= 20:
                descriptions[slug] = desc
            desc_zh = row["description_zh"] or ""
            if desc_zh and len(desc_zh) >= 20:
                descriptions_zh[slug] = desc_zh

            company_name = (row["company_name"] or "").strip()
            if company_name and company_name not in company_data:
                company_data[company_name] = {
                    "slug": slug,
                    "headquarters": (
                        {
                            "country": row["company_hq_country"],
                        }
                        if row["company_hq_country"]
                        else None
                    ),
                    "founded_year": row["company_founded_year"],
                    "name_zh": row["company_name_zh"],
                }

        return {
            "names": names,
            "names_zh": names_zh,
            "urls": urls,
            "descriptions": descriptions,
            "descriptions_zh": descriptions_zh,
            "company_data": company_data,
        }

    # -- index generation queries -------------------------------------------

    def get_index_entries(self) -> list[dict[str, Any]]:
        """Return lightweight product entries for index.json generation.

        Matches the fields produced by IndexGenerator.
        """
        rows = self.conn.execute(
            "SELECT slug, name, name_zh, description, description_zh, "
            "product_url, icon_url, product_type, category, "
            "tags_json, keywords_json, open_source, status, "
            "company_name, company_url, "
            "company_hq_country AS country, company_hq_country_code AS country_code, "
            "company_hq_city AS city, "
            "funding_total_raised_usd AS total_raised_usd, "
            "funding_last_round AS last_round, "
            "funding_valuation_usd AS valuation_usd, "
            "company_employee_count_range AS employee_count_range "
            "FROM products "
            "ORDER BY funding_total_raised_usd DESC, name ASC"
        ).fetchall()

        entries: list[dict[str, Any]] = []
        for row in rows:
            entry = dict(row)
            # Deserialize JSON columns
            for json_col in ("tags_json", "keywords_json"):
                field = json_col.replace("_json", "")
                raw = entry.pop(json_col, "[]")
                try:
                    entry[field] = json.loads(raw) if raw else []
                except json.JSONDecodeError:
                    entry[field] = []
            # Restore booleans
            if entry.get("open_source") is not None:
                entry["open_source"] = bool(entry["open_source"])
            # Fill defaults for missing values
            entry.setdefault("total_raised_usd", 0)
            entry.setdefault("last_round", "")
            entry.setdefault("valuation_usd", 0)
            entry.setdefault("employee_count_range", "")
            entry.setdefault("country", "")
            entry.setdefault("country_code", "")
            entry.setdefault("city", "")
            entry.setdefault("company_name", "")
            entry.setdefault("company_url", "")
            entries.append(entry)

        return entries

    # -- stats generation queries -------------------------------------------

    def get_stats_data(self) -> dict[str, Any]:
        """Return aggregated statistics via SQL.

        Returns a dict with:
            total: int
            by_category: list[dict]
            by_country: list[dict]
            by_status: list[dict]
            funding_leaderboard: list[dict]
            total_funding_usd: float
            open_source_count: int
            recently_added: list[dict]
            all_products: list[dict]  (full product list for tag dimension stats)
        """
        stats: dict[str, Any] = {}

        # Total count
        stats["total"] = self.count()

        # By category
        rows = self.conn.execute(
            "SELECT category AS label, COUNT(*) AS count "
            "FROM products WHERE category IS NOT NULL "
            "GROUP BY category ORDER BY count DESC"
        ).fetchall()
        stats["by_category"] = [dict(r) for r in rows]

        # By country
        rows = self.conn.execute(
            "SELECT company_hq_country AS label, COUNT(*) AS count "
            "FROM products WHERE company_hq_country IS NOT NULL "
            "GROUP BY company_hq_country ORDER BY count DESC"
        ).fetchall()
        stats["by_country"] = [dict(r) for r in rows]

        # By status
        rows = self.conn.execute(
            "SELECT status AS label, COUNT(*) AS count "
            "FROM products WHERE status IS NOT NULL "
            "GROUP BY status ORDER BY count DESC"
        ).fetchall()
        stats["by_status"] = [dict(r) for r in rows]

        # Funding leaderboard (top 10)
        rows = self.conn.execute(
            "SELECT slug, name, funding_total_raised_usd AS total_raised_usd, "
            "funding_valuation_usd AS valuation_usd "
            "FROM products WHERE funding_total_raised_usd > 0 "
            "ORDER BY funding_total_raised_usd DESC LIMIT 10"
        ).fetchall()
        stats["funding_leaderboard"] = [dict(r) for r in rows]

        # Total funding
        row = self.conn.execute(
            "SELECT COALESCE(SUM(funding_total_raised_usd), 0) FROM products"
        ).fetchone()
        stats["total_funding_usd"] = row[0] if row else 0

        # Open source count
        row = self.conn.execute(
            "SELECT COUNT(*) FROM products WHERE open_source = 1"
        ).fetchone()
        stats["open_source_count"] = row[0] if row else 0

        # Recently added
        rows = self.conn.execute(
            "SELECT slug, name, added_date "
            "FROM products WHERE added_date IS NOT NULL "
            "ORDER BY added_date DESC LIMIT 5"
        ).fetchall()
        stats["recently_added"] = [dict(r) for r in rows]

        return stats

    # -- FTS search ---------------------------------------------------------

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Full-text search using FTS5.  Returns lightweight dicts."""
        rows = self.conn.execute(
            "SELECT p.slug, p.name, p.name_zh, p.description, p.category, "
            "p.company_name, p.icon_url, p.product_url, p.status "
            "FROM products_fts fts "
            "JOIN products p ON fts.rowid = p.rowid "
            "WHERE products_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- rebuild FTS --------------------------------------------------------

    def rebuild_fts(self) -> None:
        """Rebuild the FTS5 index from scratch.

        For external-content FTS5 tables, triggers keep the index in sync
        during normal INSERT/UPDATE/DELETE.  This method is useful after
        bulk data changes outside the trigger path.  If rebuild fails
        (e.g., older SQLite versions), it logs a warning but does not raise.
        """
        try:
            self.conn.execute(
                "INSERT INTO products_fts(products_fts) VALUES('rebuild')"
            )
            self.conn.commit()
            logger.info("FTS index rebuilt")
        except Exception as e:
            logger.warning("FTS rebuild skipped (triggers keep index in sync): %s", e)

    # -- all products as dicts (for tag dimension stats etc.) ---------------

    def get_all_dicts(self) -> list[dict[str, Any]]:
        """Return all products as full nested dicts.  Use sparingly."""
        rows = self.conn.execute("SELECT * FROM products").fetchall()
        return [self.row_to_dict(r) for r in rows]
