"""Tests for the Normalizer and PlausibilityValidator."""

from __future__ import annotations

import pytest

from scrapers.base import ScrapedProduct
from scrapers.enrichment.normalizer import Normalizer, PlausibilityValidator


@pytest.fixture
def normalizer() -> Normalizer:
    return Normalizer()


@pytest.fixture
def validator() -> PlausibilityValidator:
    return PlausibilityValidator()


class TestNormalizeName:
    def test_strips_inc(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(name="Acme Inc.", source="test")
        result = normalizer.normalize(product)
        assert result.name == "Acme"

    def test_strips_llc(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(name="Acme LLC", source="test")
        result = normalizer.normalize(product)
        assert result.name == "Acme"

    def test_strips_ltd(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(name="Acme Ltd", source="test")
        result = normalizer.normalize(product)
        assert result.name == "Acme"

    def test_preserves_normal_name(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(name="OpenAI", source="test")
        result = normalizer.normalize(product)
        assert result.name == "OpenAI"


class TestNormalizeCountry:
    def test_normalizes_us(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(
            name="Test", source="test", company_headquarters_country="us"
        )
        result = normalizer.normalize(product)
        assert result.company_headquarters_country == "United States"
        assert result.company_headquarters_country_code == "US"

    def test_normalizes_uk(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(
            name="Test", source="test", company_headquarters_country="UK"
        )
        result = normalizer.normalize(product)
        assert result.company_headquarters_country == "United Kingdom"
        assert result.company_headquarters_country_code == "GB"

    def test_preserves_unknown_country(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(
            name="Test", source="test", company_headquarters_country="Atlantis"
        )
        result = normalizer.normalize(product)
        assert result.company_headquarters_country == "Atlantis"


class TestNormalizeUrl:
    def test_strips_trailing_slash(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(
            name="Test", source="test", company_website="https://example.com/"
        )
        result = normalizer.normalize(product)
        assert result.company_website == "https://example.com"

    def test_strips_fragment(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(
            name="Test", source="test", company_website="https://example.com#about"
        )
        result = normalizer.normalize(product)
        assert result.company_website == "https://example.com"


class TestQualityScore:
    def test_full_data(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(
            name="Test",
            source="test",
            company_website="https://test.com",
            description="desc",
            category="ai-other",
            company_founded_year=2023,
            company_headquarters_country="US",
            company_total_raised_usd=100000,
            company_employee_count_range="11-50",
        )
        score = normalizer.compute_quality_score(product)
        assert score == 1.0

    def test_minimal_data(self, normalizer: Normalizer) -> None:
        product = ScrapedProduct(name="Test", source="test")
        score = normalizer.compute_quality_score(product)
        assert score < 0.5


class TestPlausibilityValidator:
    """Tests for garbage data filters in PlausibilityValidator."""

    @staticmethod
    def _make_product(**kwargs: object) -> ScrapedProduct:
        defaults: dict[str, object] = {"name": "ValidProduct", "source": "test"}
        defaults.update(kwargs)
        return ScrapedProduct(**defaults)  # type: ignore[arg-type]

    def test_valid_product_passes(self, validator: PlausibilityValidator) -> None:
        product = self._make_product(
            description="A legitimate AI-powered code review tool.",
            product_url="https://example.com",
        )
        is_valid, issues = validator.validate(product)
        assert is_valid
        assert issues == []

    # 1. Garbled name (escape artifacts)
    def test_rejects_garbled_name_backslash_n(
        self, validator: PlausibilityValidator
    ) -> None:
        product = self._make_product(name="10,426\\n5\\n5.0")
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("escape artifacts" in i for i in issues)

    def test_rejects_garbled_name_double_backslash(
        self, validator: PlausibilityValidator
    ) -> None:
        product = self._make_product(name="foo\\\\bar")
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("escape artifacts" in i for i in issues)

    # 2. Numeric-only name
    def test_rejects_numeric_only_name(self, validator: PlausibilityValidator) -> None:
        product = self._make_product(name="10,426 5 5.0")
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("numeric-only" in i for i in issues)

    def test_allows_name_with_digits_and_letters(
        self, validator: PlausibilityValidator
    ) -> None:
        product = self._make_product(name="GPT-4o")
        is_valid, issues = validator.validate(product)
        assert is_valid

    # 3. Price-text name
    def test_rejects_price_dollar_sign(self, validator: PlausibilityValidator) -> None:
        product = self._make_product(name="Free + from $12/mo")
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("price text" in i for i in issues)

    def test_rejects_price_per_month(self, validator: PlausibilityValidator) -> None:
        product = self._make_product(name="From 500/mo")
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("price text" in i for i in issues)

    # 4. Blacklisted navigation names
    @pytest.mark.parametrize(
        "name",
        ["Deals", "New", "Launch / Advertise", "No pricing", "deals", "NEW"],
    )
    def test_rejects_blacklisted_names(
        self, validator: PlausibilityValidator, name: str
    ) -> None:
        product = self._make_product(name=name)
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("blacklisted" in i for i in issues)

    # 5. Template description
    def test_rejects_template_description(
        self, validator: PlausibilityValidator
    ) -> None:
        product = self._make_product(description="FooBar is an AI product.")
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("template" in i.lower() for i in issues)

    def test_allows_normal_description(self, validator: PlausibilityValidator) -> None:
        product = self._make_product(
            description="FooBar is an AI-powered code review tool."
        )
        is_valid, issues = validator.validate(product)
        assert is_valid

    # 6. Search engine URL
    def test_rejects_google_search_product_url(
        self, validator: PlausibilityValidator
    ) -> None:
        product = self._make_product(
            product_url="https://www.google.com/search?q=foobar"
        )
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("search engine" in i.lower() for i in issues)

    def test_rejects_bing_search_company_website(
        self, validator: PlausibilityValidator
    ) -> None:
        product = self._make_product(
            company_website="https://www.bing.com/search?q=foobar"
        )
        is_valid, issues = validator.validate(product)
        assert not is_valid
        assert any("search engine" in i.lower() for i in issues)

    def test_allows_normal_url(self, validator: PlausibilityValidator) -> None:
        product = self._make_product(
            product_url="https://example.com",
            company_website="https://company.com",
        )
        is_valid, issues = validator.validate(product)
        assert is_valid
