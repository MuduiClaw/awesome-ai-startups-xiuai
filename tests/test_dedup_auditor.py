"""Tests for DedupAuditor and dict_to_scraped_product."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scrapers.base import ScrapedProduct, SourceTier
from scrapers.enrichment.dedup_auditor import DedupAuditor, dict_to_scraped_product


def _make_product(
    slug: str,
    name: str,
    product_url: str,
    company_name: str = "",
    quality_score: float = 0.5,
    added_date: str = "2025-01-01",
) -> dict[str, Any]:
    """Create a minimal product dict for testing."""
    return {
        "slug": slug,
        "name": name,
        "product_url": product_url,
        "description": f"{name} is an AI product.",
        "product_type": "other",
        "category": "ai-application",
        "status": "active",
        "company": {"name": company_name or name, "url": product_url},
        "meta": {
            "added_date": added_date,
            "last_updated": "2025-06-01",
            "data_quality_score": quality_score,
        },
    }


class TestDedupAuditor:
    def test_finds_duplicate_group(self, tmp_path: Path) -> None:
        """Two products sharing a domain should form a duplicate group."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product("polybuzz", "PolyBuzz", "https://polybuzz.ai", quality_score=0.8)
        p2 = _make_product(
            "polybuzz-chat", "PolyBuzz Chat", "https://app.polybuzz.ai/chat", quality_score=0.4
        )
        (products_dir / "polybuzz.json").write_text(
            json.dumps(p1), encoding="utf-8"
        )
        (products_dir / "polybuzz-chat.json").write_text(
            json.dumps(p2), encoding="utf-8"
        )

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 1
        assert groups[0].root_domain == "polybuzz.ai"

    def test_classifies_merge_same_company(self, tmp_path: Path) -> None:
        """Products with the same company name should be classified as 'merge'."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product(
            "acme", "Acme AI", "https://acme.ai", company_name="Acme Inc"
        )
        p2 = _make_product(
            "acme-pro", "Acme Pro", "https://pro.acme.ai", company_name="Acme Inc"
        )
        (products_dir / "acme.json").write_text(json.dumps(p1), encoding="utf-8")
        (products_dir / "acme-pro.json").write_text(json.dumps(p2), encoding="utf-8")

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 1
        assert groups[0].classification == "merge"

    def test_classifies_merge_similar_company_names(self, tmp_path: Path) -> None:
        """Products with similar company names should be classified as 'merge'."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product(
            "cutoutpro", "CutoutPro", "https://cutout.pro", company_name="Cutout.Pro"
        )
        p2 = _make_product(
            "cutoutpro-retouch",
            "CutoutPro Retouch",
            "https://cutout.pro/retouch",
            company_name="Cutout.Pro Retouch",
        )
        (products_dir / "cutoutpro.json").write_text(json.dumps(p1), encoding="utf-8")
        (products_dir / "cutoutpro-retouch.json").write_text(
            json.dumps(p2), encoding="utf-8"
        )

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 1
        assert groups[0].classification == "merge"

    def test_classifies_skip_store(self, tmp_path: Path) -> None:
        """Products on apps.apple.com should be classified as 'skip_store'."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product("app1", "App One", "https://apps.apple.com/app/id111")
        p2 = _make_product("app2", "App Two", "https://apps.apple.com/app/id222")
        (products_dir / "app1.json").write_text(json.dumps(p1), encoding="utf-8")
        (products_dir / "app2.json").write_text(json.dumps(p2), encoding="utf-8")

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 1
        assert groups[0].classification == "skip_store"

    def test_classifies_skip_legitimate(self, tmp_path: Path) -> None:
        """Products with truly different company names should be 'skip_legitimate'."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product(
            "product-a", "Product A", "https://example.com/a", company_name="Acme Corporation"
        )
        p2 = _make_product(
            "product-b", "Product B", "https://api.example.com/b", company_name="Widget Labs"
        )
        (products_dir / "product-a.json").write_text(json.dumps(p1), encoding="utf-8")
        (products_dir / "product-b.json").write_text(json.dumps(p2), encoding="utf-8")

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 1
        assert groups[0].classification == "skip_legitimate"

    def test_target_selection_by_quality(self, tmp_path: Path) -> None:
        """The product with the highest quality score should be the target."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product("low", "Low Quality", "https://example.com", quality_score=0.2)
        p2 = _make_product("high", "High Quality", "https://app.example.com", quality_score=0.9)
        (products_dir / "low.json").write_text(json.dumps(p1), encoding="utf-8")
        (products_dir / "high.json").write_text(json.dumps(p2), encoding="utf-8")

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 1
        assert groups[0].target_slug == "high"
        assert "low" in groups[0].source_slugs

    def test_min_count_filter(self, tmp_path: Path) -> None:
        """Groups smaller than min_count should be excluded."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        p1 = _make_product("only-one", "Only One", "https://unique-domain.com")
        (products_dir / "only-one.json").write_text(json.dumps(p1), encoding="utf-8")

        with patch("scrapers.enrichment.dedup_auditor.PRODUCTS_DIR", products_dir):
            auditor = DedupAuditor()
            groups = auditor.audit(min_count=2)

        assert len(groups) == 0


class TestDictToScrapedProduct:
    def test_basic_conversion(self) -> None:
        """A minimal product dict should convert to ScrapedProduct."""
        data = _make_product("test", "Test Product", "https://test.com")
        result = dict_to_scraped_product(data)

        assert isinstance(result, ScrapedProduct)
        assert result.name == "Test Product"
        assert result.source == "dedup-merge"
        assert result.source_tier == SourceTier.T2_OPEN_WEB
        assert result.product_url == "https://test.com"

    def test_company_fields_mapped(self) -> None:
        """Company fields should be extracted from nested dict."""
        data = {
            "slug": "test",
            "name": "Test",
            "product_url": "https://test.com",
            "company": {
                "name": "Test Corp",
                "name_zh": "测试公司",
                "website": "https://testcorp.com",
                "founded_year": 2020,
                "headquarters": {"city": "SF", "country": "US"},
            },
        }
        result = dict_to_scraped_product(data)

        assert result.company_name == "Test Corp"
        assert result.company_name_zh == "测试公司"
        assert result.company_website == "https://testcorp.com"
        assert result.company_founded_year == 2020
        assert result.company_headquarters_city == "SF"
        assert result.company_headquarters_country == "US"

    def test_lists_become_tuples(self) -> None:
        """List fields should be converted to tuples for frozen dataclass."""
        data = {
            "slug": "test",
            "name": "Test",
            "product_url": "https://test.com",
            "tags": ["ai", "ml", "nlp"],
            "platforms": ["web", "ios"],
        }
        result = dict_to_scraped_product(data)

        assert result.tags == ("ai", "ml", "nlp")
        assert result.platforms == ("web", "ios")
        assert isinstance(result.tags, tuple)

    def test_missing_fields_default(self) -> None:
        """Missing fields should use their default values."""
        data = {"slug": "minimal", "name": "Minimal", "product_url": ""}
        result = dict_to_scraped_product(data)

        assert result.description is None
        assert result.tags == ()
        assert result.company_name is None
        assert result.open_source is None

    def test_pricing_fields(self) -> None:
        """Pricing nested dict should be flattened."""
        data = {
            "slug": "test",
            "name": "Test",
            "product_url": "https://test.com",
            "pricing": {"model": "freemium", "has_free_tier": True},
        }
        result = dict_to_scraped_product(data)

        assert result.pricing_model == "freemium"
        assert result.has_free_tier is True

    def test_social_links_in_extra(self) -> None:
        """Social links should be passed through in the extra dict."""
        data = {
            "slug": "test",
            "name": "Test",
            "product_url": "https://test.com",
            "company": {
                "name": "Test",
                "social": {
                    "linkedin": "https://linkedin.com/company/test",
                    "twitter": "@test",
                },
            },
        }
        result = dict_to_scraped_product(data)

        assert result.extra.get("linkedin_url") == "https://linkedin.com/company/test"
        assert result.extra.get("twitter") == "@test"
