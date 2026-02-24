"""Retroactive duplicate auditor — scan existing products for domain-based duplicates.

Provides ``DedupAuditor`` for finding duplicate groups and ``dict_to_scraped_product``
for converting product dicts into ``ScrapedProduct`` instances suitable for
``TieredMerger.merge_update()``.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from scrapers.base import ScrapedProduct, SourceTier
from scrapers.config import PRODUCTS_DIR
from scrapers.utils import extract_root_domain
from scrapers.utils.domains import APP_STORE_DOMAINS, SKIP_DOMAINS

try:
    from Levenshtein import ratio as lev_ratio
except ImportError:

    def lev_ratio(a: str, b: str) -> float:
        """Fallback: positional character match ratio."""
        if not a or not b:
            return 0.0
        common = sum(1 for ca, cb in zip(a, b, strict=False) if ca == cb)
        return (2.0 * common) / (len(a) + len(b))


# Similarity threshold for company name fuzzy matching within a domain group.
_COMPANY_NAME_SIMILARITY = 0.60

# Minimum common prefix length to consider two names as related.
_MIN_COMMON_PREFIX = 4

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DuplicateGroup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateGroup:
    """A group of products sharing the same root domain."""

    root_domain: str
    classification: str  # "merge", "skip_store", "skip_legitimate", "review"
    target_slug: str
    source_slugs: tuple[str, ...]
    reason: str
    products: tuple[dict[str, Any], ...] = field(repr=False)


# ---------------------------------------------------------------------------
# DedupAuditor
# ---------------------------------------------------------------------------


class DedupAuditor:
    """Scan all products for domain-based duplicates and classify them."""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    def audit(self, min_count: int = 2) -> list[DuplicateGroup]:
        """Find all root-domain groups with *min_count* or more products.

        Returns a list of ``DuplicateGroup`` objects sorted by group size
        (largest first).
        """
        from scrapers.utils import extract_domain

        products = self._load_all_products()

        # Group products by root domain, tracking original domains per group
        domain_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        original_domains: dict[str, set[str]] = defaultdict(set)
        for product in products:
            product_url = product.get("product_url", "")
            if not product_url:
                continue
            root = extract_root_domain(product_url)
            if root:
                domain_groups[root].append(product)
                orig = extract_domain(product_url)
                if orig:
                    original_domains[root].add(orig)

        # Filter to groups with enough members
        groups: list[DuplicateGroup] = []
        for domain, members in sorted(
            domain_groups.items(), key=lambda x: len(x[1]), reverse=True
        ):
            if len(members) < min_count:
                continue
            orig_set = original_domains.get(domain, set())
            group = self._classify_group(domain, members, orig_set)
            groups.append(group)

        return groups

    # -- classification logic -----------------------------------------------

    def _classify_group(
        self,
        root_domain: str,
        products: list[dict[str, Any]],
        original_domains: set[str] | None = None,
    ) -> DuplicateGroup:
        """Classify a group of products sharing *root_domain*."""
        # Collect company names for each product in the group
        company_names: set[str] = set()
        for p in products:
            company = p.get("company") or {}
            cn = (company.get("name") or "").strip().lower()
            if cn:
                company_names.add(cn)

        # Pick the best target (highest quality score > most fields > earliest added)
        target = self._select_target(products)
        target_slug = target.get("slug", "")
        source_slugs = tuple(
            p.get("slug", "") for p in products if p.get("slug") != target_slug
        )
        product_tuple = tuple(products)

        # Check if any original domain is a skip domain (app store or aggregator)
        orig_set = original_domains or set()
        has_skip_domain = any(d in SKIP_DOMAINS for d in orig_set)
        has_app_store = any(d in APP_STORE_DOMAINS for d in orig_set)

        # Classification rules
        if has_app_store:
            return DuplicateGroup(
                root_domain=root_domain,
                classification="skip_store",
                target_slug=target_slug,
                source_slugs=source_slugs,
                reason=f"App store domain: {root_domain}",
                products=product_tuple,
            )

        if has_skip_domain:
            return DuplicateGroup(
                root_domain=root_domain,
                classification="skip_store",
                target_slug=target_slug,
                source_slugs=source_slugs,
                reason=f"Aggregator domain: {root_domain}",
                products=product_tuple,
            )

        if len(company_names) <= 1:
            # Same company name (or all missing) — likely true duplicates
            return DuplicateGroup(
                root_domain=root_domain,
                classification="merge",
                target_slug=target_slug,
                source_slugs=source_slugs,
                reason=f"Same company, {len(products)} files for {root_domain}",
                products=product_tuple,
            )

        # Check if company names are similar enough to be the same company
        # (e.g. "Cutout.Pro" vs "Cutout.Pro扣图" vs "Cutout.Pro老照片上色")
        if self._names_are_related(company_names):
            return DuplicateGroup(
                root_domain=root_domain,
                classification="merge",
                target_slug=target_slug,
                source_slugs=source_slugs,
                reason=(
                    f"Similar company names on {root_domain}: "
                    f"{', '.join(sorted(company_names))}"
                ),
                products=product_tuple,
            )

        if len(company_names) == len(products):
            # Every product has a truly different company name
            return DuplicateGroup(
                root_domain=root_domain,
                classification="skip_legitimate",
                target_slug=target_slug,
                source_slugs=source_slugs,
                reason=(
                    f"Different companies sharing {root_domain}: "
                    f"{', '.join(sorted(company_names))}"
                ),
                products=product_tuple,
            )

        # Ambiguous: some names match, some don't
        return DuplicateGroup(
            root_domain=root_domain,
            classification="review",
            target_slug=target_slug,
            source_slugs=source_slugs,
            reason=(
                f"Mixed company names on {root_domain}: "
                f"{', '.join(sorted(company_names))}"
            ),
            products=product_tuple,
        )

    @staticmethod
    def _names_are_related(names: set[str]) -> bool:
        """Return True if the company names are similar enough to be the same company.

        Uses both Levenshtein similarity and common-prefix detection.
        A group is related if ANY pair of names is similar, or if all names
        share a common prefix of at least ``_MIN_COMMON_PREFIX`` chars.
        """
        from itertools import combinations

        name_list = list(names)
        if len(name_list) <= 1:
            return True

        # Check pairwise similarity
        for a, b in combinations(name_list, 2):
            # Levenshtein ratio
            if lev_ratio(a, b) >= _COMPANY_NAME_SIMILARITY:
                continue  # Similar — keep checking
            # Common prefix
            prefix_len = 0
            for ca, cb in zip(a, b):
                if ca == cb:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= _MIN_COMMON_PREFIX:
                continue  # Shares prefix — keep checking
            # This pair is not related
            return False

        return True

    @staticmethod
    def _select_target(products: list[dict[str, Any]]) -> dict[str, Any]:
        """Select the best product to keep as the merge target.

        Priority: highest data_quality_score > most populated fields > earliest added_date.
        """

        def _sort_key(p: dict[str, Any]) -> tuple[float, int, str]:
            meta = p.get("meta") or {}
            quality = meta.get("data_quality_score", 0.0)
            if not isinstance(quality, (int, float)):
                quality = 0.0
            # Count non-empty top-level fields as a tiebreaker
            field_count = sum(
                1
                for v in p.values()
                if v is not None and v != "" and v != [] and v != {}
            )
            # Earlier added_date wins (sort ascending, so negate or invert)
            added = meta.get("added_date", "9999-99-99")
            if not isinstance(added, str):
                added = "9999-99-99"
            return (quality, field_count, added)

        # Sort descending by quality/fields, ascending by date (use negation trick)
        return max(
            products,
            key=lambda p: (
                _sort_key(p)[0],
                _sort_key(p)[1],
                # Invert date: earlier is better, so use reversed string comparison
                "".join(
                    chr(255 - ord(c)) if c.isdigit() else c for c in _sort_key(p)[2]
                ),
            ),
        )

    # -- data loading -------------------------------------------------------

    def _load_all_products(self) -> list[dict[str, Any]]:
        """Load all product dicts from DB or JSON files."""
        if self._db is not None:
            return self._db.get_all_dicts()

        products: list[dict[str, Any]] = []
        if not PRODUCTS_DIR.exists():
            return products
        for filepath in sorted(PRODUCTS_DIR.glob("*.json")):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                products.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return products


# ---------------------------------------------------------------------------
# dict -> ScrapedProduct converter
# ---------------------------------------------------------------------------


def dict_to_scraped_product(data: dict[str, Any]) -> ScrapedProduct:
    """Convert a product dict to a ``ScrapedProduct`` for use with TieredMerger.

    The resulting ScrapedProduct uses T2 tier and ``"dedup-merge"`` source.
    Lists in the dict are converted to tuples for frozen dataclass compatibility.
    """
    company = data.get("company") or {}
    meta = data.get("meta") or {}
    pricing = data.get("pricing") or {}
    hiring = data.get("hiring") or {}

    def _to_tuple(val: Any) -> tuple[Any, ...]:
        if isinstance(val, (list, tuple)):
            return tuple(val)
        return ()

    def _to_dict_tuple(val: Any) -> tuple[dict[str, Any], ...]:
        if isinstance(val, (list, tuple)):
            return tuple(dict(item) if isinstance(item, dict) else item for item in val)
        return ()

    return ScrapedProduct(
        name=data.get("name", ""),
        source="dedup-merge",
        source_url=data.get("product_url", ""),
        source_tier=SourceTier.T2_OPEN_WEB,
        # Product identity
        name_zh=data.get("name_zh"),
        product_url=data.get("product_url"),
        icon_url=data.get("icon_url"),
        description=data.get("description"),
        description_zh=data.get("description_zh"),
        product_type=data.get("product_type"),
        category=data.get("category"),
        sub_category=data.get("sub_category"),
        tags=_to_tuple(data.get("tags")),
        keywords=_to_tuple(data.get("keywords")),
        # Company
        company_name=company.get("name"),
        company_name_zh=company.get("name_zh"),
        company_website=company.get("website"),
        company_wikipedia_url=company.get("wikipedia_url"),
        company_logo_url=company.get("logo_url"),
        company_description=company.get("description"),
        company_founded_year=company.get("founded_year"),
        company_headquarters_city=(company.get("headquarters") or {}).get("city"),
        company_headquarters_country=(company.get("headquarters") or {}).get("country"),
        company_headquarters_country_code=(company.get("headquarters") or {}).get(
            "country_code"
        ),
        company_total_raised_usd=(company.get("funding") or {}).get("total_raised_usd"),
        company_last_round=(company.get("funding") or {}).get("last_round"),
        company_employee_count_range=company.get("employee_count_range"),
        # Key people
        key_people=_to_dict_tuple(data.get("key_people")),
        # Tech specs
        architecture=data.get("architecture"),
        parameter_count=data.get("parameter_count"),
        context_window=data.get("context_window"),
        modalities=_to_tuple(data.get("modalities")),
        supported_languages=_to_tuple(data.get("supported_languages")),
        platforms=_to_tuple(data.get("platforms")),
        api_available=data.get("api_available"),
        api_docs_url=data.get("api_docs_url"),
        # Open source
        open_source=data.get("open_source"),
        license=data.get("license"),
        repository_url=data.get("repository_url"),
        github_stars=data.get("github_stars"),
        github_contributors=data.get("github_contributors"),
        # Pricing
        pricing_model=pricing.get("model"),
        has_free_tier=pricing.get("has_free_tier"),
        # Market
        target_audience=_to_tuple(data.get("target_audience")),
        use_cases=_to_tuple(data.get("use_cases")),
        # Relations
        competitors=_to_tuple(data.get("competitors")),
        based_on=_to_tuple(data.get("based_on")),
        # Status
        status=data.get("status"),
        release_date=data.get("release_date"),
        # Hiring
        hiring_is_hiring=hiring.get("is_hiring"),
        hiring_careers_url=hiring.get("careers_url", ""),
        hiring_positions=_to_dict_tuple(hiring.get("positions")),
        hiring_tech_stack=_to_tuple(hiring.get("tech_stack")),
        # Extra: pass through social links
        extra=_build_extra(data, company, meta),
    )


def _build_extra(
    data: dict[str, Any],
    company: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, str]:
    """Build the extra dict from auxiliary fields in the product data."""
    extra: dict[str, str] = {}
    social = company.get("social") or {}
    if social.get("linkedin"):
        extra["linkedin_url"] = social["linkedin"]
    if social.get("twitter"):
        extra["twitter"] = social["twitter"]
    if social.get("github"):
        extra["github_url"] = social["github"]
    if social.get("crunchbase"):
        extra["crunchbase_url"] = social["crunchbase"]
    # App store IDs
    app_store = data.get("app_store") or {}
    if app_store.get("google_play_url"):
        # Extract app ID from URL
        gp_url = app_store["google_play_url"]
        if "id=" in gp_url:
            extra["google_play_app_id"] = gp_url.split("id=")[-1].split("&")[0]
    if app_store.get("apple_store_url"):
        as_url = app_store["apple_store_url"]
        if "/id" in as_url:
            extra["app_store_track_id"] = as_url.split("/id")[-1].split("?")[0]
    if app_store.get("rating"):
        extra["app_store_rating"] = str(app_store["rating"])
    if app_store.get("downloads"):
        extra["google_play_installs"] = str(app_store["downloads"])
    return extra
