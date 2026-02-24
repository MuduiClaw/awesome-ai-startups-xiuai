"""Tests for the Deduplicator and root domain extraction."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scrapers.base import ScrapedProduct
from scrapers.enrichment.deduplicator import Deduplicator

_FIXTURE_DATA: dict[str, dict] = {
    "openai": {
        "slug": "openai",
        "name": "ChatGPT",
        "product_url": "https://chat.openai.com",
        "company": {
            "name": "OpenAI",
            "url": "https://openai.com",
            "website": "https://openai.com",
        },
    },
    "anthropic": {
        "slug": "anthropic",
        "name": "Claude",
        "product_url": "https://claude.ai",
        "company": {
            "name": "Anthropic",
            "url": "https://www.anthropic.com",
            "website": "https://www.anthropic.com",
        },
    },
}


def _create_mock_products_dir(tmp_path: Path) -> Path:
    """Create a temporary products dir with known entries."""
    products_dir = tmp_path / "products"
    products_dir.mkdir()

    for slug, data in _FIXTURE_DATA.items():
        (products_dir / f"{slug}.json").write_text(json.dumps(data), encoding="utf-8")

    return products_dir


class TestDeduplicator:
    def test_detects_existing_by_domain(self, tmp_path: Path) -> None:
        products_dir = _create_mock_products_dir(tmp_path)
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(
                    name="OpenAI Inc",
                    source="test",
                    company_website="https://openai.com/about",
                ),
            ]
            result = dedup.deduplicate(products)
            assert len(result.new_products) == 0
            assert len(result.updates_for_existing) == 1
            assert result.updates_for_existing[0][0] == "openai"

    def test_detects_existing_by_name(self, tmp_path: Path) -> None:
        products_dir = _create_mock_products_dir(tmp_path)
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(name="Claude", source="test"),
            ]
            result = dedup.deduplicate(products)
            assert len(result.new_products) == 0
            assert len(result.updates_for_existing) == 1

    def test_identifies_new_product(self, tmp_path: Path) -> None:
        products_dir = _create_mock_products_dir(tmp_path)
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(
                    name="Brand New Startup",
                    source="test",
                    product_url="https://newstartup.ai",
                ),
            ]
            result = dedup.deduplicate(products)
            assert len(result.new_products) == 1
            assert len(result.updates_for_existing) == 0

    def test_mixed_new_and_existing(self, tmp_path: Path) -> None:
        products_dir = _create_mock_products_dir(tmp_path)
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(
                    name="ChatGPT",
                    source="test",
                    product_url="https://chat.openai.com",
                ),
                ScrapedProduct(
                    name="New AI Corp",
                    source="test",
                    product_url="https://newai.com",
                ),
            ]
            result = dedup.deduplicate(products)
            assert len(result.new_products) == 1
            assert len(result.updates_for_existing) == 1


class TestExtractRootDomain:
    """Test extract_root_domain() subdomain stripping and two-part TLD handling."""

    def test_simple_domain(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://openai.com") == "openai.com"

    def test_strips_www(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://www.openai.com") == "openai.com"

    def test_strips_subdomain(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://app.polybuzz.ai/chat") == "polybuzz.ai"

    def test_strips_deep_subdomain(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://api.v2.example.com/foo") == "example.com"

    def test_two_part_tld_co_uk(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://www.bbc.co.uk/news") == "bbc.co.uk"

    def test_two_part_tld_com_cn(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://sub.example.com.cn") == "example.com.cn"

    def test_two_part_tld_co_jp(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://app.company.co.jp") == "company.co.jp"

    def test_empty_url(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("") == ""

    def test_url_with_port(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://app.example.com:8080/path") == "example.com"

    def test_bare_two_labels(self) -> None:
        from scrapers.utils import extract_root_domain

        assert extract_root_domain("https://example.ai") == "example.ai"


class TestDeduplicatorSkipsDomains:
    """Test that store/aggregator domains are skipped during deduplication."""

    def test_app_store_url_not_indexed(self, tmp_path: Path) -> None:
        """Products with apps.apple.com URLs should not match by domain."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        (products_dir / "app-a.json").write_text(
            json.dumps(
                {
                    "slug": "app-a",
                    "name": "App A",
                    "product_url": "https://apps.apple.com/app/id123",
                }
            ),
            encoding="utf-8",
        )
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(
                    name="App B",
                    source="test",
                    product_url="https://apps.apple.com/app/id456",
                ),
            ]
            result = dedup.deduplicate(products)
            # App B should be treated as new — not matched to App A by domain
            assert len(result.new_products) == 1
            assert len(result.updates_for_existing) == 0

    def test_aggregator_url_not_indexed(self, tmp_path: Path) -> None:
        """Products with producthunt.com URLs should not match by domain."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        (products_dir / "tool-a.json").write_text(
            json.dumps(
                {
                    "slug": "tool-a",
                    "name": "Tool A",
                    "product_url": "https://producthunt.com/posts/tool-a",
                }
            ),
            encoding="utf-8",
        )
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(
                    name="Tool B",
                    source="test",
                    product_url="https://producthunt.com/posts/tool-b",
                ),
            ]
            result = dedup.deduplicate(products)
            assert len(result.new_products) == 1
            assert len(result.updates_for_existing) == 0

    def test_root_domain_matches_subdomain(self, tmp_path: Path) -> None:
        """app.polybuzz.ai should match an existing polybuzz.ai product."""
        products_dir = tmp_path / "products"
        products_dir.mkdir()
        (products_dir / "polybuzz.json").write_text(
            json.dumps(
                {
                    "slug": "polybuzz",
                    "name": "PolyBuzz",
                    "product_url": "https://polybuzz.ai",
                }
            ),
            encoding="utf-8",
        )
        with patch("scrapers.enrichment.deduplicator.PRODUCTS_DIR", products_dir):
            dedup = Deduplicator()
            products = [
                ScrapedProduct(
                    name="PolyBuzz Chat",
                    source="test",
                    product_url="https://app.polybuzz.ai/chat",
                ),
            ]
            result = dedup.deduplicate(products)
            assert len(result.new_products) == 0
            assert len(result.updates_for_existing) == 1
            assert result.updates_for_existing[0][0] == "polybuzz"
