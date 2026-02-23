"""Tests for scrapers.db.ProductDB."""

from __future__ import annotations

import json

import pytest

from scrapers.db import ProductDB


@pytest.fixture
def db(tmp_path):
    """Create a temporary ProductDB with schema initialized."""
    db_path = tmp_path / "test.db"
    db = ProductDB(db_path)
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def sample_product():
    """A full product dict matching the JSON schema."""
    return {
        "slug": "test-product",
        "name": "Test Product",
        "name_zh": "测试产品",
        "product_url": "https://test-product.com",
        "icon_url": "https://cdn.example.com/icon.png",
        "description": "A test product for unit testing purposes with enough length.",
        "description_zh": "一个用于单元测试的测试产品，描述足够长。",
        "product_type": "app",
        "category": "ai-chatbot-agent",
        "sub_category": "ai assistant",
        "status": "active",
        "open_source": True,
        "license": "MIT",
        "repository_url": "https://github.com/test/test-product",
        "github_stars": 1234,
        "api_available": True,
        "tags": ["AI Assistant", "Chatbot"],
        "keywords": ["artificial intelligence", "chatbot"],
        "key_people": [{"name": "Jane Doe", "title": "CEO", "is_founder": True}],
        "company": {
            "name": "Test Company",
            "name_zh": "测试公司",
            "url": "https://test-company.com",
            "website": "https://test-company.com",
            "founded_year": 2023,
            "headquarters": {
                "city": "San Francisco",
                "country": "United States",
                "country_code": "US",
            },
            "funding": {
                "total_raised_usd": 50000000,
                "last_round": "Series B",
                "investors": ["VC Fund A", "VC Fund B"],
            },
            "employee_count_range": "51-200",
            "social": {
                "github": "https://github.com/test",
                "twitter": "https://twitter.com/test",
            },
        },
        "pricing": {
            "model": "freemium",
            "has_free_tier": True,
        },
        "sources": [
            {
                "url": "https://toolify.ai/tool/test-product",
                "source_name": "toolify",
                "scraped_at": "2026-01-01",
            }
        ],
        "meta": {
            "added_date": "2026-01-01",
            "last_updated": "2026-01-15",
            "data_quality_score": 0.8,
            "provenance": {
                "name": {"source": "toolify", "tier": 2, "confidence": 0.75},
            },
        },
    }


class TestProductDBSchema:
    """Test schema initialization."""

    def test_init_schema(self, db):
        """Schema should create tables and indexes."""
        # Check products table exists
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
        ).fetchone()
        assert row is not None

        # Check FTS table exists
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='products_fts'"
        ).fetchone()
        assert row is not None

    def test_init_schema_idempotent(self, db):
        """Calling init_schema twice should not error."""
        db.init_schema()
        assert db.count() == 0


class TestDictToRow:
    """Test dict_to_row conversion."""

    def test_scalar_fields(self, db, sample_product):
        row = db.dict_to_row(sample_product)
        assert row["slug"] == "test-product"
        assert row["name"] == "Test Product"
        assert row["name_zh"] == "测试产品"
        assert row["category"] == "ai-chatbot-agent"
        assert row["status"] == "active"

    def test_nested_company_fields(self, db, sample_product):
        row = db.dict_to_row(sample_product)
        assert row["company_name"] == "Test Company"
        assert row["company_hq_city"] == "San Francisco"
        assert row["company_hq_country"] == "United States"
        assert row["company_founded_year"] == 2023
        assert row["funding_total_raised_usd"] == 50000000

    def test_boolean_conversion(self, db, sample_product):
        row = db.dict_to_row(sample_product)
        assert row["open_source"] == 1
        assert row["api_available"] == 1
        assert row["has_free_tier"] == 1

    def test_json_columns(self, db, sample_product):
        row = db.dict_to_row(sample_product)
        tags = json.loads(row["tags_json"])
        assert tags == ["AI Assistant", "Chatbot"]
        sources = json.loads(row["sources_json"])
        assert len(sources) == 1
        assert sources[0]["source_name"] == "toolify"

    def test_meta_fields(self, db, sample_product):
        row = db.dict_to_row(sample_product)
        assert row["added_date"] == "2026-01-01"
        assert row["last_updated"] == "2026-01-15"
        assert row["data_quality_score"] == 0.8

    def test_provenance_json(self, db, sample_product):
        row = db.dict_to_row(sample_product)
        prov = json.loads(row["provenance_json"])
        assert prov["name"]["source"] == "toolify"


class TestRowToDict:
    """Test row_to_dict conversion (reverse of dict_to_row)."""

    def test_roundtrip_scalar(self, db, sample_product):
        """Scalar fields should survive a round-trip."""
        db.upsert(sample_product)
        result = db.get("test-product")
        assert result is not None
        assert result["slug"] == "test-product"
        assert result["name"] == "Test Product"
        assert result["name_zh"] == "测试产品"
        assert result["category"] == "ai-chatbot-agent"

    def test_roundtrip_booleans(self, db, sample_product):
        """Booleans should be restored as Python bools."""
        db.upsert(sample_product)
        result = db.get("test-product")
        assert result is not None
        assert result["open_source"] is True
        assert result["api_available"] is True

    def test_roundtrip_company(self, db, sample_product):
        """Company nested dict should be reconstructed."""
        db.upsert(sample_product)
        result = db.get("test-product")
        assert result is not None
        assert result["company"]["name"] == "Test Company"
        assert result["company"]["headquarters"]["city"] == "San Francisco"
        assert result["company"]["funding"]["total_raised_usd"] == 50000000

    def test_roundtrip_arrays(self, db, sample_product):
        """Arrays should survive round-trip."""
        db.upsert(sample_product)
        result = db.get("test-product")
        assert result is not None
        assert result["tags"] == ["AI Assistant", "Chatbot"]
        assert result["keywords"] == ["artificial intelligence", "chatbot"]

    def test_roundtrip_pricing(self, db, sample_product):
        """Pricing nested dict should be reconstructed."""
        db.upsert(sample_product)
        result = db.get("test-product")
        assert result is not None
        assert result["pricing"]["model"] == "freemium"
        assert result["pricing"]["has_free_tier"] is True


class TestCRUD:
    """Test CRUD operations."""

    def test_upsert_and_get(self, db, sample_product):
        db.upsert(sample_product)
        result = db.get("test-product")
        assert result is not None
        assert result["name"] == "Test Product"

    def test_get_missing(self, db):
        result = db.get("nonexistent")
        assert result is None

    def test_exists(self, db, sample_product):
        assert not db.exists("test-product")
        db.upsert(sample_product)
        assert db.exists("test-product")

    def test_delete(self, db, sample_product):
        db.upsert(sample_product)
        assert db.delete("test-product")
        assert not db.exists("test-product")

    def test_delete_nonexistent(self, db):
        assert not db.delete("nonexistent")

    def test_count(self, db, sample_product):
        assert db.count() == 0
        db.upsert(sample_product)
        assert db.count() == 1

    def test_all_slugs(self, db, sample_product):
        db.upsert(sample_product)
        second = dict(sample_product)
        second["slug"] = "another-product"
        second["name"] = "Another Product"
        db.upsert(second)
        slugs = db.all_slugs()
        assert slugs == ["another-product", "test-product"]

    def test_upsert_replaces(self, db, sample_product):
        """Upserting with same slug should replace."""
        db.upsert(sample_product)
        updated = dict(sample_product)
        updated["name"] = "Updated Name"
        db.upsert(updated)
        assert db.count() == 1
        result = db.get("test-product")
        assert result is not None
        assert result["name"] == "Updated Name"


class TestBatchUpsert:
    """Test bulk upsert."""

    def test_batch_upsert(self, db, sample_product):
        products = []
        for i in range(10):
            p = dict(sample_product)
            p["slug"] = f"product-{i}"
            p["name"] = f"Product {i}"
            products.append(p)
        count = db.upsert_batch(products)
        assert count == 10
        assert db.count() == 10

    def test_batch_empty(self, db):
        count = db.upsert_batch([])
        assert count == 0


class TestDedupIndex:
    """Test dedup index queries."""

    def test_dedup_index(self, db, sample_product):
        db.upsert(sample_product)
        index = db.get_dedup_index()
        assert "test product" in index["names"]
        assert index["names"]["test product"] == "test-product"
        assert "测试产品" in index["names_zh"]
        assert "test-product.com" in index["domains"]


class TestIndexEntries:
    """Test index generation query."""

    def test_index_entries(self, db, sample_product):
        db.upsert(sample_product)
        entries = db.get_index_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["slug"] == "test-product"
        assert entry["company_name"] == "Test Company"
        assert entry["total_raised_usd"] == 50000000
        assert entry["country"] == "United States"
        assert entry["tags"] == ["AI Assistant", "Chatbot"]


class TestStatsData:
    """Test stats aggregation query."""

    def test_stats(self, db, sample_product):
        db.upsert(sample_product)
        stats = db.get_stats_data()
        assert stats["total"] == 1
        assert stats["total_funding_usd"] == 50000000
        assert stats["open_source_count"] == 1
        assert len(stats["by_category"]) == 1
        assert stats["by_category"][0]["label"] == "ai-chatbot-agent"


class TestFTS:
    """Test full-text search."""

    def test_search_by_name(self, db, sample_product):
        db.upsert(sample_product)
        results = db.search("Test Product")
        assert len(results) >= 1
        assert results[0]["slug"] == "test-product"

    def test_search_by_description(self, db, sample_product):
        db.upsert(sample_product)
        results = db.search("unit testing")
        assert len(results) >= 1

    def test_search_no_results(self, db, sample_product):
        db.upsert(sample_product)
        results = db.search("xyznonexistent")
        assert len(results) == 0


class TestMinimalProduct:
    """Test handling of minimal products (few optional fields)."""

    def test_minimal_product(self, db):
        minimal = {
            "slug": "minimal",
            "name": "Minimal Product",
            "description": "A minimal product.",
            "product_type": "app",
            "category": "ai-chatbot-agent",
            "status": "active",
            "company": {
                "name": "Minimal Co",
                "url": "https://minimal.com",
            },
        }
        db.upsert(minimal)
        result = db.get("minimal")
        assert result is not None
        assert result["slug"] == "minimal"
        assert result["name"] == "Minimal Product"
        assert result["company"]["name"] == "Minimal Co"

    def test_product_without_funding(self, db):
        product = {
            "slug": "no-funding",
            "name": "No Funding Product",
            "description": "Product without funding info.",
            "product_type": "app",
            "category": "ai-chatbot-agent",
            "status": "active",
            "company": {"name": "Co", "url": "https://co.com"},
        }
        db.upsert(product)
        result = db.get("no-funding")
        assert result is not None
        # funding should not appear in reconstructed dict
        company = result.get("company", {})
        assert "funding" not in company or not company.get("funding")
