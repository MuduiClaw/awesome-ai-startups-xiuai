"""Validate cross-product referential integrity."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from scrapers.config import PRODUCTS_DIR


@dataclass
class IntegrityError:
    """A single referential integrity violation."""

    product_slug: str
    field: str
    referenced_slug: str
    message: str


# Fields that contain references to other product slugs
_REFERENCE_FIELDS: tuple[str, ...] = ("competitors", "based_on", "used_by")


class IntegrityValidator:
    """Validate cross-product references (competitors, based_on, used_by)."""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    def validate_all(self) -> list[IntegrityError]:
        """Check all products for broken references."""
        if self._db is not None:
            return self._validate_all_from_db()
        return self._validate_all_from_files()

    def _validate_all_from_db(self) -> list[IntegrityError]:
        """Check all products from SQLite for broken references."""
        all_slugs = set(self._db.all_slugs())
        all_products = self._db.get_all_dicts()

        errors: list[IntegrityError] = []
        for data in all_products:
            errors.extend(self.validate_product(data, all_slugs))
        return errors

    def _validate_all_from_files(self) -> list[IntegrityError]:
        """Check all products from JSON files for broken references."""
        if not PRODUCTS_DIR.exists():
            return []

        # 1. Collect all known slugs and their parsed data
        all_slugs: set[str] = set()
        products: list[tuple[str, dict[str, Any]]] = []

        for filepath in sorted(PRODUCTS_DIR.glob("*.json")):
            slug = filepath.stem
            all_slugs.add(slug)
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                products.append((slug, data))
            except (json.JSONDecodeError, OSError):
                continue

        # 2. Validate each product's references
        errors: list[IntegrityError] = []
        for _slug, data in products:
            errors.extend(self.validate_product(data, all_slugs))

        return errors

    def validate_product(self, data: dict, all_slugs: set[str]) -> list[IntegrityError]:
        """Check a single product's references against known slugs."""
        errors: list[IntegrityError] = []
        product_slug: str = data.get("slug", "<unknown>")

        for field in _REFERENCE_FIELDS:
            references = data.get(field)
            if references is None:
                continue
            if not isinstance(references, list):
                continue

            for ref_slug in references:
                if not isinstance(ref_slug, str):
                    continue
                if ref_slug not in all_slugs:
                    errors.append(
                        IntegrityError(
                            product_slug=product_slug,
                            field=field,
                            referenced_slug=ref_slug,
                            message=(
                                f"Product '{product_slug}' references "
                                f"'{ref_slug}' in '{field}', but no file "
                                f"'{ref_slug}.json' exists in products directory"
                            ),
                        )
                    )

        return errors
