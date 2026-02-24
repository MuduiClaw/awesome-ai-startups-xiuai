"""Utility functions: slugify, HTTP client, retry logic."""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

import httpx

from scrapers.config import (
    HTTP_TIMEOUT,
    MAX_RETRIES,
    PRODUCTS_DIR,
    RETRY_DELAY,
    USER_AGENT,
)

# Slug validation pattern — must match product.schema.json and website slug check
_VALID_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug.

    Handles Chinese/CJK characters via transliteration (unidecode).

    >>> slugify("OpenAI")
    'openai'
    >>> slugify("Hugging Face")
    'hugging-face'
    >>> slugify("1X Technologies")
    '1x-technologies'
    """
    from unidecode import unidecode

    text = unicodedata.normalize("NFKD", text)
    # Transliterate non-ASCII (Chinese, etc.) to ASCII before stripping
    text = unidecode(text)
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    text = text.strip("-")
    return text


def validate_slug(slug: str) -> str:
    """Validate that a slug is safe for use in file paths.

    Prevents path traversal attacks by ensuring the slug contains only
    lowercase alphanumeric characters and hyphens, and that the resolved
    file path stays within PRODUCTS_DIR.

    Args:
        slug: The slug to validate.

    Returns:
        The validated slug (unchanged).

    Raises:
        ValueError: If the slug is invalid or would escape PRODUCTS_DIR.
    """
    if not slug or not _VALID_SLUG_RE.match(slug):
        raise ValueError(f"Invalid slug: {slug!r}")
    # Defense-in-depth: verify resolved path stays within PRODUCTS_DIR
    filepath = (PRODUCTS_DIR / f"{slug}.json").resolve()
    if not str(filepath).startswith(str(PRODUCTS_DIR.resolve())):
        raise ValueError(f"Slug would escape products directory: {slug!r}")
    return slug


def create_http_client(**kwargs: Any) -> httpx.Client:
    """Create a configured httpx client with default headers."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=kwargs.pop("timeout", HTTP_TIMEOUT),
        follow_redirects=True,
        **kwargs,
    )


def fetch_with_retry(
    url: str,
    *,
    client: httpx.Client | None = None,
    max_retries: int = MAX_RETRIES,
    retry_delay: float = RETRY_DELAY,
) -> httpx.Response:
    """Fetch a URL with retry logic for transient failures.

    When no *client* is provided, a temporary client is created and
    closed automatically after the request completes (success or failure).
    """
    own_client = client is None
    if own_client:
        client = create_http_client()
    assert client is not None  # narrowing for mypy

    last_error: Exception | None = None
    try:
        for attempt in range(max_retries):
            try:
                response = client.get(url)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2**attempt))
    finally:
        if own_client:
            client.close()

    raise last_error  # type: ignore[misc]


def get_nested(data: dict[str, Any], path: str) -> Any:
    """Retrieve a value from *data* following a dotted *path*.

    Returns ``None`` when any intermediate key is missing.

    >>> get_nested({"a": {"b": 2}}, "a.b")
    2
    >>> get_nested({"a": 1}, "a.b.c") is None
    True
    """
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_url(url: str) -> str:
    """Normalize a URL by stripping trailing slashes and fragments."""
    url = url.strip()
    url = url.split("#")[0]
    url = url.rstrip("/")
    return url


def extract_domain(url: str) -> str:
    """Extract the domain from a URL.

    >>> extract_domain("https://www.openai.com/research")
    'openai.com'
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    domain = parsed.netloc or parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.lower()


# Two-part TLDs where the "registrable domain" is three labels deep.
_TWO_PART_TLDS: frozenset[str] = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "or.jp",
        "ne.jp",
        "co.kr",
        "or.kr",
        "com.cn",
        "net.cn",
        "org.cn",
        "com.tw",
        "org.tw",
        "com.hk",
        "com.sg",
        "com.br",
        "com.mx",
        "co.in",
        "com.ar",
        "co.za",
        "co.il",
        "com.tr",
        "co.id",
        "com.my",
        "co.th",
        "com.vn",
        "com.ph",
    }
)


def extract_root_domain(url: str) -> str:
    """Extract the registrable (root) domain from a URL.

    Strips subdomains beyond the registrable part, handling two-part
    TLDs like ``.co.uk`` and ``.com.cn`` without requiring ``tldextract``.

    >>> extract_root_domain("https://app.polybuzz.ai/chat")
    'polybuzz.ai'
    >>> extract_root_domain("https://www.bbc.co.uk/news")
    'bbc.co.uk'
    >>> extract_root_domain("https://openai.com")
    'openai.com'
    """
    domain = extract_domain(url)
    if not domain:
        return ""

    # Strip port if present
    domain = domain.split(":")[0]

    parts = domain.split(".")
    if len(parts) <= 2:
        return domain

    # Check if the last two parts form a known two-part TLD
    two_part = f"{parts[-2]}.{parts[-1]}"
    if two_part in _TWO_PART_TLDS:
        # Registrable domain is three labels: e.g. bbc.co.uk
        if len(parts) >= 3:
            return f"{parts[-3]}.{two_part}"
        return domain

    # Standard TLD: registrable domain is the last two labels
    return f"{parts[-2]}.{parts[-1]}"
