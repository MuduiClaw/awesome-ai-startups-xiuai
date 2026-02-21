#!/usr/bin/env python3
"""Batch enrichment for AI product data using local Claude CLI.

Asks Claude for ALL fields in one prompt per batch:
  translation (name_zh, description_zh), SEO (target_audience, use_cases),
  tech metadata (modalities, platforms, api_available, open_source),
  company info (description, competitors),
  hiring & team (is_hiring, tech_stack, team_size, careers_url).

Usage (3-step workflow):
    python scripts/batch_enrich.py --generate-prompts           # Step 1: Generate
    bash data/.enrichment_prompts/phase_5/run_all.sh            # Step 2: Run CLI
    python scripts/batch_enrich.py --apply-responses            # Step 3: Apply

Other:
    python scripts/batch_enrich.py --phase 0                    # Rule-based only
    python scripts/batch_enrich.py --generate-prompts --limit 5 # Test with 5
    python scripts/batch_enrich.py --apply-responses --dry-run  # Preview changes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scrapers.base import ScrapedProduct, SourceTier  # noqa: E402
from scrapers.config import LLM_DAILY_BUDGET, PRODUCTS_DIR  # noqa: E402
from scrapers.enrichment.keyword_extractor import KeywordExtractor  # noqa: E402
from scrapers.enrichment.merger import TieredMerger  # noqa: E402

logger = logging.getLogger("batch_enrich")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKPOINT_FILE = PRODUCTS_DIR.parent / ".enrichment_checkpoint.json"
PROMPTS_DIR = PRODUCTS_DIR.parent / ".enrichment_prompts"
RESPONSES_DIR = PRODUCTS_DIR.parent / ".enrichment_responses"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_RATE_LIMIT_DELAY = 1.0  # seconds between API calls
CLI_RATE_LIMIT_DELAY = 0.5  # seconds between CLI calls (subscription-based)

# CJK Unicode ranges for detecting Chinese text
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")

# Open-source tag signals — matched as exact tags (case-insensitive)
_OPEN_SOURCE_TAGS = frozenset(
    {
        "open source",
        "open-source",
        "open source ai models",
        "opensource",
    }
)

# ccTLD → country name (for rule-based country inference from domain)
_TLD_COUNTRY_MAP: dict[str, str] = {
    "cn": "China",
    "de": "Germany",
    "fr": "France",
    "jp": "Japan",
    "kr": "South Korea",
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "ca": "Canada",
    "au": "Australia",
    "il": "Israel",
    "sg": "Singapore",
    "in": "India",
    "se": "Sweden",
    "no": "Norway",
    "nl": "Netherlands",
    "ch": "Switzerland",
    "es": "Spain",
    "it": "Italy",
    "pt": "Portugal",
    "br": "Brazil",
    "mx": "Mexico",
    "ar": "Argentina",
    "co": "Colombia",
    "cl": "Chile",
    "ru": "Russia",
    "ua": "Ukraine",
    "pl": "Poland",
    "cz": "Czech Republic",
    "at": "Austria",
    "be": "Belgium",
    "dk": "Denmark",
    "fi": "Finland",
    "ie": "Ireland",
    "nz": "New Zealand",
    "za": "South Africa",
    "ng": "Nigeria",
    "ke": "Kenya",
    "eg": "Egypt",
    "ae": "United Arab Emirates",
    "sa": "Saudi Arabia",
    "tw": "Taiwan",
    "hk": "Hong Kong",
    "th": "Thailand",
    "vn": "Vietnam",
    "id": "Indonesia",
    "my": "Malaysia",
    "ph": "Philippines",
    "pk": "Pakistan",
    "tr": "Turkey",
    "ee": "Estonia",
    "lt": "Lithuania",
    "lv": "Latvia",
}

# Country name → ISO alpha-2 code
_COUNTRY_TO_CODE: dict[str, str] = {
    "China": "CN",
    "Germany": "DE",
    "France": "FR",
    "Japan": "JP",
    "South Korea": "KR",
    "United Kingdom": "GB",
    "Canada": "CA",
    "Australia": "AU",
    "Israel": "IL",
    "Singapore": "SG",
    "India": "IN",
    "Sweden": "SE",
    "Norway": "NO",
    "United States": "US",
    "Netherlands": "NL",
    "Switzerland": "CH",
    "Spain": "ES",
    "Italy": "IT",
    "Portugal": "PT",
    "Brazil": "BR",
    "Mexico": "MX",
    "Argentina": "AR",
    "Colombia": "CO",
    "Chile": "CL",
    "Russia": "RU",
    "Ukraine": "UA",
    "Poland": "PL",
    "Czech Republic": "CZ",
    "Austria": "AT",
    "Belgium": "BE",
    "Denmark": "DK",
    "Finland": "FI",
    "Ireland": "IE",
    "New Zealand": "NZ",
    "South Africa": "ZA",
    "Nigeria": "NG",
    "Kenya": "KE",
    "Egypt": "EG",
    "United Arab Emirates": "AE",
    "Saudi Arabia": "SA",
    "Taiwan": "TW",
    "Hong Kong": "HK",
    "Thailand": "TH",
    "Vietnam": "VN",
    "Indonesia": "ID",
    "Malaysia": "MY",
    "Philippines": "PH",
    "Pakistan": "PK",
    "Turkey": "TR",
    "Estonia": "EE",
    "Lithuania": "LT",
    "Latvia": "LV",
}


# ---------------------------------------------------------------------------
# Checkpoint management (atomic read-modify-write)
# ---------------------------------------------------------------------------


def load_checkpoint() -> dict[str, list[str]]:
    """Load checkpoint file mapping phase -> list of completed slugs."""
    if CHECKPOINT_FILE.exists():
        try:
            data: dict[str, list[str]] = json.loads(
                CHECKPOINT_FILE.read_text(encoding="utf-8")
            )
            return data
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt checkpoint file, starting fresh")
    return {}


def save_checkpoint(phase_key: str, completed_slugs: set[str]) -> None:
    """Atomically update a single phase key in the checkpoint file.

    Re-reads from disk before writing to avoid clobbering progress
    from concurrent phase runs.
    """
    checkpoint = load_checkpoint()
    checkpoint[phase_key] = sorted(completed_slugs)
    tmp = CHECKPOINT_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(checkpoint, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(CHECKPOINT_FILE)


# ---------------------------------------------------------------------------
# Product loading & prompt sanitisation
# ---------------------------------------------------------------------------


def load_all_products() -> list[tuple[str, dict[str, Any]]]:
    """Load all product JSON files. Returns list of (slug, product_dict)."""
    products: list[tuple[str, dict[str, Any]]] = []
    for filepath in sorted(PRODUCTS_DIR.glob("*.json")):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            slug = data.get("slug", filepath.stem)
            products.append((slug, data))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping %s: %s", filepath.name, exc)
    return products


def _sanitize(text: str, max_len: int = 300) -> str:
    """Escape user-controlled text for safe inclusion in LLM prompts."""
    return text[:max_len].replace('"', '\\"').replace("\n", " ")


# ---------------------------------------------------------------------------
# Phase 0: Rule-based enrichment
# ---------------------------------------------------------------------------


def _cjk_ratio(text: str) -> float:
    """Return the fraction of characters that are CJK."""
    if not text:
        return 0.0
    return len(_CJK_PATTERN.findall(text)) / len(text)


def _infer_open_source(product: dict[str, Any]) -> bool | None:
    """Infer open_source from tags and other signals."""
    tags_lower = {t.lower() for t in product.get("tags", [])}
    if _OPEN_SOURCE_TAGS & tags_lower:
        return True
    if product.get("repository_url") or product.get("license"):
        return True
    if product.get("pricing", {}).get("model") == "open-source":
        return True
    return None


def _infer_api_available(product: dict[str, Any]) -> bool | None:
    """Infer api_available from tags, product_type, and other signals."""
    if product.get("product_type") == "api-service":
        return True
    if product.get("api_docs_url"):
        return True
    tags_lower = {t.lower() for t in product.get("tags", [])}
    api_signals = {"api", "api-service", "api service", "rest api"}
    if api_signals & tags_lower:
        return True
    return None


def _infer_platforms(product: dict[str, Any]) -> list[str] | None:
    """Infer platforms from app_store data, tags, and product_url."""
    platforms: set[str] = set()

    app_store = product.get("app_store", {})
    if app_store.get("apple_store_url"):
        platforms.add("ios")
    if app_store.get("google_play_url"):
        platforms.add("android")

    for p in product.get("platforms", []):
        platforms.add(p.lower())

    tags_lower = [t.lower() for t in product.get("tags", [])]
    tag_map = {
        "web app": "web",
        "web-app": "web",
        "browser extension": "web",
        "chrome extension": "web",
        "ios": "ios",
        "iphone": "ios",
        "ipad": "ios",
        "android": "android",
        "desktop": "desktop",
        "mac app": "desktop",
        "windows app": "desktop",
        "cli": "cli",
        "command-line": "cli",
        "self-hosted": "self-hosted",
        "api": "api",
    }
    for tag in tags_lower:
        for signal, platform in tag_map.items():
            if signal in tag:
                platforms.add(platform)

    if not platforms and product.get("product_url"):
        url = product["product_url"].lower()
        app_store_domains = (
            "play.google.com",
            "apps.apple.com",
            "itunes.apple.com",
        )
        if not any(d in url for d in app_store_domains):
            platforms.add("web")

    return sorted(platforms) if platforms else None


def _infer_country(product: dict[str, Any]) -> dict[str, str] | None:
    """Infer headquarters country from company name (CJK) or domain TLD.

    Returns {"country": ..., "country_code": ...} or None.
    """
    # Already has country data — skip
    if product.get("company", {}).get("headquarters", {}).get("country"):
        return None

    # Signal 1: CJK characters in company name → China
    company_name = product.get("company", {}).get("name", "")
    if company_name and _cjk_ratio(company_name) > 0.3:
        return {"country": "China", "country_code": "CN"}

    # Signal 2: ccTLD from product_url or company website
    url = product.get("product_url") or product.get("company", {}).get("website", "")
    if url:
        # Extract TLD from domain (e.g. "example.co.uk" → "uk", "example.cn" → "cn")
        match = re.search(r"https?://[^/]+\.([a-z]{2})(?:[:/]|$)", url.lower())
        if match:
            tld = match.group(1)
            country = _TLD_COUNTRY_MAP.get(tld)
            if country:
                return {
                    "country": country,
                    "country_code": _COUNTRY_TO_CODE.get(country, ""),
                }

    return None


def phase_0_enrich_product(
    product: dict[str, Any],
    keyword_extractor: KeywordExtractor,
) -> dict[str, Any]:
    """Apply rule-based enrichments. Returns dict of new field values."""
    enrichments: dict[str, Any] = {}

    if not product.get("description_zh"):
        desc = product.get("description", "")
        if desc and _cjk_ratio(desc) > 0.5:
            enrichments["description_zh"] = desc

    if not product.get("name_zh"):
        name = product.get("name", "")
        if name and _cjk_ratio(name) > 0.3:
            enrichments["name_zh"] = name

    if product.get("open_source") is None:
        val = _infer_open_source(product)
        if val is not None:
            enrichments["open_source"] = val

    if product.get("api_available") is None:
        val = _infer_api_available(product)
        if val is not None:
            enrichments["api_available"] = val

    if not product.get("platforms"):
        platforms_val = _infer_platforms(product)
        if platforms_val:
            enrichments["platforms"] = platforms_val

    if not product.get("keywords"):
        keywords = keyword_extractor.extract(product)
        if keywords:
            enrichments["keywords"] = keywords

    # --- Country inference (TLD / CJK) ---
    country_data = _infer_country(product)
    if country_data:
        enrichments["company_headquarters_country"] = country_data["country"]
        if country_data.get("country_code"):
            enrichments["company_headquarters_country_code"] = country_data[
                "country_code"
            ]

    return enrichments


def run_phase_0(
    products: list[tuple[str, dict[str, Any]]],
    *,
    dry_run: bool = False,
    limit: int | None = None,
    resume: bool = False,
) -> dict[str, int]:
    """Run Phase 0: rule-based enrichment."""
    completed_slugs = set(load_checkpoint().get("phase_0", []) if resume else [])

    merger = TieredMerger()
    kw_ext = KeywordExtractor()
    stats: dict[str, int] = {
        "processed": 0,
        "enriched": 0,
        "skipped": 0,
    }

    candidates = [(s, p) for s, p in products if s not in completed_slugs]
    if limit:
        candidates = candidates[:limit]

    logger.info(
        "Phase 0: %d to process (%d already done)",
        len(candidates),
        len(completed_slugs),
    )

    for slug, product in candidates:
        enrichments = phase_0_enrich_product(product, kw_ext)
        stats["processed"] += 1
        # Always mark processed — even if nothing to enrich
        completed_slugs.add(slug)

        if not enrichments:
            stats["skipped"] += 1
        elif dry_run:
            logger.info(
                "[DRY-RUN] %s: would set %s",
                slug,
                list(enrichments.keys()),
            )
            stats["enriched"] += 1
        else:
            kwargs: dict[str, Any] = {
                "name": product.get("name", "Unknown"),
                "source": "rule-based-enrichment",
                "source_tier": SourceTier.T3_AI_GENERATED,
                "source_url": "",
            }
            for field_name, value in enrichments.items():
                if isinstance(value, list):
                    kwargs[field_name] = tuple(value)
                else:
                    kwargs[field_name] = value
            merger.merge_update(slug, ScrapedProduct(**kwargs))
            stats["enriched"] += 1

        if stats["processed"] % 500 == 0:
            save_checkpoint("phase_0", completed_slugs)
            logger.info(
                "Progress: %d/%d processed, %d enriched",
                stats["processed"],
                len(candidates),
                stats["enriched"],
            )

    if not dry_run:
        save_checkpoint("phase_0", completed_slugs)
    return stats


# ---------------------------------------------------------------------------
# LLM batch client
# ---------------------------------------------------------------------------


class BatchLLMClient:
    """Thin wrapper around the Anthropic API for batch enrichment."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
    ) -> None:
        self.model = model
        self.rate_limit_delay = rate_limit_delay
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ImportError(
                    "anthropic package required: pip install anthropic"
                ) from exc
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is required.")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def call(self, prompt: str, max_tokens: int = 8192) -> str:
        """Call the Anthropic API and return text response."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: list[str] = []
        for block in message.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        # Join all text blocks — JSON may span multiple blocks
        return "\n".join(text_parts) if text_parts else "{}"

    def call_with_retry(
        self,
        prompt: str,
        max_tokens: int = 8192,
        max_retries: int = 3,
    ) -> str | None:
        """Call with exponential backoff on transient errors."""
        for attempt in range(max_retries):
            try:
                result = self.call(prompt, max_tokens)
                time.sleep(self.rate_limit_delay)
                return result
            except (ConnectionError, TimeoutError, OSError) as exc:
                self._handle_retry(attempt, max_retries, exc)
            except Exception as exc:
                # Anthropic SDK errors are recoverable (rate limit, etc.)
                if type(exc).__module__.startswith("anthropic"):
                    self._handle_retry(attempt, max_retries, exc)
                else:
                    raise
        return None

    @staticmethod
    def _handle_retry(
        attempt: int,
        max_retries: int,
        exc: Exception,
    ) -> None:
        err = type(exc).__name__
        if attempt < max_retries - 1:
            wait = (2**attempt) * 2
            logger.warning(
                "API error (%d/%d): %s: %s — retry in %ds",
                attempt + 1,
                max_retries,
                err,
                exc,
                wait,
            )
            time.sleep(wait)
        else:
            logger.error("API error (final): %s: %s", err, exc)


class CLILLMClient:
    """Use Claude CLI (claude -p) for enrichment instead of the API.

    Requires the ``claude`` CLI to be installed and authenticated.
    Uses the user's subscription — no ANTHROPIC_API_KEY needed.
    """

    def __init__(self, rate_limit_delay: float = CLI_RATE_LIMIT_DELAY) -> None:
        self.rate_limit_delay = rate_limit_delay
        self._verified = False

    def _verify_cli(self) -> None:
        """Check that the claude CLI is available on PATH."""
        if self._verified:
            return
        import shutil as _shutil

        if _shutil.which("claude") is None:
            raise FileNotFoundError(
                "Claude CLI not found. Install from https://claude.ai/code"
            )
        self._verified = True

    def call(self, prompt: str, max_tokens: int = 8192) -> str:
        """Call Claude via the CLI and return the text response."""
        self._verify_cli()
        import subprocess as _sp

        # Strip CLAUDECODE env var to allow running inside a Claude Code session
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = _sp.run(
            [
                "claude",
                "-p",
                "--model",
                "haiku",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Claude CLI error (exit {result.returncode}): "
                f"{result.stderr[:500]}"
            )
        return result.stdout

    def call_with_retry(
        self,
        prompt: str,
        max_tokens: int = 8192,
        max_retries: int = 3,
    ) -> str | None:
        """Call with exponential backoff on transient errors."""
        for attempt in range(max_retries):
            try:
                result = self.call(prompt, max_tokens)
                time.sleep(self.rate_limit_delay)
                return result
            except (TimeoutError, OSError, RuntimeError) as exc:
                err = type(exc).__name__
                if attempt < max_retries - 1:
                    wait = (2**attempt) * 2
                    logger.warning(
                        "CLI error (%d/%d): %s: %s — retry in %ds",
                        attempt + 1,
                        max_retries,
                        err,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error("CLI error (final): %s: %s", err, exc)
        return None


# ---------------------------------------------------------------------------
# JSON response parsing
# ---------------------------------------------------------------------------


def _parse_json_array(response: str) -> list[dict[str, Any]] | None:
    """Parse a JSON array from LLM response, stripping markdown fences.

    Returns None if parsing fails or result is not a list.
    """
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: extract the outermost JSON array from the text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse JSON array: %.200s", text)
    return None


# ---------------------------------------------------------------------------
# Generic LLM batch phase runner
# ---------------------------------------------------------------------------

# Type aliases for phase callbacks
ProductList = list[tuple[str, dict[str, Any]]]
CandidateFilter = Callable[[str, dict[str, Any]], bool]
PromptBuilder = Callable[[list[tuple[str, dict[str, Any]]]], str]
ResultApplier = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]],
    dict[str, Any] | None,
]


def _run_llm_phase(
    phase_key: str,
    phase_label: str,
    products: ProductList,
    candidate_filter: CandidateFilter,
    prompt_builder: PromptBuilder,
    result_applier: ResultApplier,
    *,
    batch_size: int,
    dry_run: bool = False,
    limit: int | None = None,
    resume: bool = False,
    model: str = DEFAULT_MODEL,
    rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
    backend: str = "api",
) -> dict[str, int]:
    """Generic batch processing loop shared by Phases 1-4.

    Args:
        phase_key: Checkpoint key (e.g. "phase_1").
        phase_label: Human-readable label for logging.
        products: Full product list.
        candidate_filter: Returns True if a product needs this phase.
        prompt_builder: Builds the LLM prompt for a batch.
        result_applier: Extracts ScrapedProduct kwargs from one LLM
            result item. Returns kwargs dict or None to skip.
        backend: "api" for Anthropic API, "cli" for Claude CLI.
    """
    completed_slugs = set(load_checkpoint().get(phase_key, []) if resume else [])
    candidates = [
        (s, p)
        for s, p in products
        if s not in completed_slugs and candidate_filter(s, p)
    ]
    if limit:
        candidates = candidates[:limit]

    num_batches = (len(candidates) + batch_size - 1) // batch_size
    stats: dict[str, int] = {
        "processed": 0,
        "enriched": 0,
        "batches": 0,
        "errors": 0,
    }
    logger.info(
        "Phase %s: %d products in %d batches (backend=%s)",
        phase_label,
        len(candidates),
        num_batches,
        backend,
    )

    if dry_run:
        logger.info("[DRY-RUN] Would process %d products", len(candidates))
        stats["processed"] = len(candidates)
        return stats

    if backend == "cli":
        llm: BatchLLMClient | CLILLMClient = CLILLMClient(
            rate_limit_delay=rate_limit_delay,
        )
    else:
        llm = BatchLLMClient(model=model, rate_limit_delay=rate_limit_delay)
    merger = TieredMerger()

    for batch_start in range(0, len(candidates), batch_size):
        # Budget enforcement (skip for CLI — it's subscription-based)
        if backend == "api" and stats["batches"] >= LLM_DAILY_BUDGET:
            logger.warning(
                "Daily budget (%d calls) reached, stopping.",
                LLM_DAILY_BUDGET,
            )
            break

        batch = candidates[batch_start : batch_start + batch_size]
        prompt = prompt_builder(batch)

        response = llm.call_with_retry(prompt)
        stats["batches"] += 1

        if response is None:
            stats["errors"] += 1
            logger.error(
                "Batch %d failed, skipping %d products",
                stats["batches"],
                len(batch),
            )
            continue

        parsed = _parse_json_array(response)
        if parsed is None:
            stats["errors"] += 1
            continue

        slug_map = {s: p for s, p in batch}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug", "")
            if slug not in slug_map:
                continue

            product = slug_map[slug]
            kwargs = result_applier(item, product, {})
            if kwargs:
                scraped = ScrapedProduct(**kwargs)
                merger.merge_update(slug, scraped)
                stats["enriched"] += 1

            # Mark as completed even if no valid fields extracted,
            # to avoid retrying products the LLM cannot enrich.
            completed_slugs.add(slug)
            stats["processed"] += 1

        save_checkpoint(phase_key, completed_slugs)
        logger.info(
            "Batch %d: %d/%d processed, %d enriched",
            stats["batches"],
            stats["processed"],
            len(candidates),
            stats["enriched"],
        )

    return stats


# ---------------------------------------------------------------------------
# Phase 1: Translation
# ---------------------------------------------------------------------------


def _build_translation_prompt(
    batch: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = []
    for i, (slug, p) in enumerate(batch, 1):
        lines.append(
            f'{i}. slug: "{slug}", '
            f'name: "{_sanitize(p.get("name", ""), 100)}", '
            f'company: "{_sanitize(p.get("company", {}).get("name", ""), 80)}", '
            f'description: "{_sanitize(p.get("description", ""))}"'
        )
    products_text = "\n".join(lines)
    return f"""Translate these AI product names and descriptions to Chinese.
Guidelines:
- For well-known products, use their accepted Chinese names.
- Keep translations concise and natural-sounding.
- description_zh should be 10-200 characters, factual.

Return ONLY a JSON array with keys:
slug, name_zh, description_zh, company_name_zh

Products:
{products_text}

Output ONLY the JSON array, no markdown, no explanation."""


def _apply_translation(
    item: dict[str, Any],
    product: dict[str, Any],
    _ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract translation fields from one LLM result item."""
    kwargs: dict[str, Any] = {
        "name": product.get("name", "Unknown"),
        "source": "llm-batch-translation",
        "source_tier": SourceTier.T3_AI_GENERATED,
        "source_url": "",
    }
    has_new = False

    for field, min_len in [
        ("name_zh", 1),
        ("company_name_zh", 1),
        ("description_zh", 10),
    ]:
        val = item.get(field)
        if isinstance(val, str) and len(val.strip()) >= min_len:
            kwargs[field] = val.strip()
            has_new = True

    return kwargs if has_new else None


def run_phase_1(products: ProductList, **kw: Any) -> dict[str, int]:
    """Phase 1: LLM translation enrichment."""
    return _run_llm_phase(
        "phase_1",
        "1 (translation)",
        products,
        candidate_filter=lambda _s, p: (
            not p.get("name_zh") or not p.get("description_zh")
        ),
        prompt_builder=_build_translation_prompt,
        result_applier=_apply_translation,
        **kw,
    )


# ---------------------------------------------------------------------------
# Phase 2: SEO fields
# ---------------------------------------------------------------------------


def _build_seo_prompt(
    batch: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = []
    for i, (slug, p) in enumerate(batch, 1):
        tags = ", ".join(p.get("tags", [])[:5])
        lines.append(
            f'{i}. slug: "{slug}", '
            f'name: "{_sanitize(p.get("name", ""), 100)}", '
            f'category: "{p.get("category", "")}", '
            f"tags: [{tags}], "
            f'description: "{_sanitize(p.get("description", ""), 200)}"'
        )
    products_text = "\n".join(lines)
    return f"""Classify these AI products for SEO and discovery.
For each product, provide:
- target_audience: 2-4 audience types
  (e.g. "developers", "marketers", "enterprises", "students",
  "designers", "researchers", "content-creators")
- use_cases: 2-5 specific use cases in kebab-case
  (e.g. "code-generation", "image-editing", "customer-support")
- sub_category: a specific sub-category slug
  (e.g. "chatbot", "image-generator", "code-assistant",
  "video-editor", "text-to-speech", "writing-assistant")

Rules:
- Use kebab-case for use_cases and sub_category
- target_audience should be lowercase descriptive terms
- Use null for any field you cannot determine confidently

Return ONLY a JSON array with keys:
slug, target_audience, use_cases, sub_category

Products:
{products_text}

Output ONLY the JSON array, no markdown, no explanation."""


def _apply_seo(
    item: dict[str, Any],
    product: dict[str, Any],
    _ctx: dict[str, Any],
) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {
        "name": product.get("name", "Unknown"),
        "source": "llm-batch-seo",
        "source_tier": SourceTier.T3_AI_GENERATED,
        "source_url": "",
    }
    has_new = False

    for field in ("target_audience", "use_cases"):
        val = item.get(field)
        if isinstance(val, list):
            clean = [str(v).strip() for v in val if isinstance(v, str) and v.strip()]
            if clean:
                kwargs[field] = tuple(clean)
                has_new = True

    sub = item.get("sub_category")
    if isinstance(sub, str) and len(sub.strip()) >= 2:
        kwargs["sub_category"] = sub.strip()
        has_new = True

    return kwargs if has_new else None


def run_phase_2(products: ProductList, **kw: Any) -> dict[str, int]:
    """Phase 2: LLM SEO field enrichment."""
    return _run_llm_phase(
        "phase_2",
        "2 (SEO)",
        products,
        candidate_filter=lambda _s, p: (
            not p.get("target_audience")
            or not p.get("use_cases")
            or not p.get("sub_category")
        ),
        prompt_builder=_build_seo_prompt,
        result_applier=_apply_seo,
        **kw,
    )


# ---------------------------------------------------------------------------
# Phase 3: Tech metadata
# ---------------------------------------------------------------------------

_VALID_MODALITIES = frozenset(
    {
        "text",
        "image",
        "audio",
        "video",
        "code",
        "multimodal",
        "3d",
    }
)
_VALID_PLATFORMS = frozenset(
    {
        "web",
        "ios",
        "android",
        "desktop",
        "api",
        "cli",
        "self-hosted",
    }
)


def _build_tech_prompt(
    batch: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = []
    for i, (slug, p) in enumerate(batch, 1):
        tags = ", ".join(p.get("tags", [])[:5])
        lines.append(
            f'{i}. slug: "{slug}", '
            f'name: "{_sanitize(p.get("name", ""), 100)}", '
            f'product_type: "{p.get("product_type", "")}", '
            f'category: "{p.get("category", "")}", '
            f"tags: [{tags}], "
            f'description: "{_sanitize(p.get("description", ""), 200)}"'
        )
    products_text = "\n".join(lines)
    return f"""Determine technical metadata for these AI products.
For each product, provide:
- modalities: array from ["text", "image", "audio",
  "video", "code", "multimodal", "3d"]
- platforms: array from ["web", "ios", "android",
  "desktop", "api", "cli", "self-hosted"]
- api_available: boolean — does it offer a developer API?
- open_source: boolean — is this product open-source?

Rules:
- Most web-based SaaS products have platforms: ["web"]
- "app" products typically include "web" and may add "ios"/"android"
- If a product mentions API access, set api_available: true
- Only set open_source: true if there's clear evidence
- Use null for fields you cannot determine with confidence

Return ONLY a JSON array with keys:
slug, modalities, platforms, api_available, open_source

Products:
{products_text}

Output ONLY the JSON array, no markdown, no explanation."""


def _apply_tech(
    item: dict[str, Any],
    product: dict[str, Any],
    _ctx: dict[str, Any],
) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {
        "name": product.get("name", "Unknown"),
        "source": "llm-batch-tech",
        "source_tier": SourceTier.T3_AI_GENERATED,
        "source_url": "",
    }
    has_new = False

    for field, valid_set in [
        ("modalities", _VALID_MODALITIES),
        ("platforms", _VALID_PLATFORMS),
    ]:
        val = item.get(field)
        if isinstance(val, list):
            clean = [
                v for v in val if isinstance(v, str) and v.strip().lower() in valid_set
            ]
            if clean:
                kwargs[field] = tuple(clean)
                has_new = True

    for bool_field in ("api_available", "open_source"):
        val = item.get(bool_field)
        if isinstance(val, bool):
            kwargs[bool_field] = val
            has_new = True

    return kwargs if has_new else None


def run_phase_3(products: ProductList, **kw: Any) -> dict[str, int]:
    """Phase 3: LLM tech metadata enrichment."""
    return _run_llm_phase(
        "phase_3",
        "3 (tech)",
        products,
        candidate_filter=lambda _s, p: (
            not p.get("modalities")
            or not p.get("platforms")
            or p.get("api_available") is None
            or p.get("open_source") is None
        ),
        prompt_builder=_build_tech_prompt,
        result_applier=_apply_tech,
        **kw,
    )


# ---------------------------------------------------------------------------
# Phase 4: Descriptions & relationships
# ---------------------------------------------------------------------------


def _build_desc_prompt(
    batch: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = []
    for i, (slug, p) in enumerate(batch, 1):
        tags = ", ".join(p.get("tags", [])[:5])
        company = p.get("company", {}).get("name", "")
        lines.append(
            f'{i}. slug: "{slug}", '
            f'name: "{_sanitize(p.get("name", ""), 100)}", '
            f'company: "{_sanitize(company, 80)}", '
            f'category: "{p.get("category", "")}", '
            f"tags: [{tags}], "
            f'description: "{_sanitize(p.get("description", ""))}"'
        )
    products_text = "\n".join(lines)
    return f"""Provide company descriptions and competitor info
for these AI products.
For each product, provide:
- company_description: 1-2 sentence factual description of
  the company (50-200 chars). Focus on what the company does
  and when it was founded if known.
- competitors: 2-5 competitor product slugs in kebab-case
  (e.g. ["chatgpt", "claude", "gemini"]).
  Only include well-known, real competitor products.

Rules:
- company_description describes the COMPANY, not the product
- For solo/indie products, describe the creator or team
- competitors must be real product names in kebab-case format
- Only include direct competitors in the same category
- Use null for fields you cannot determine with confidence
- Do NOT hallucinate competitors

Return ONLY a JSON array with keys:
slug, company_description, competitors

Products:
{products_text}

Output ONLY the JSON array, no markdown, no explanation."""


def _make_desc_applier(
    known_slugs: frozenset[str],
) -> ResultApplier:
    """Create a Phase 4 result applier with competitor slug validation."""

    def _apply(
        item: dict[str, Any],
        product: dict[str, Any],
        _ctx: dict[str, Any],
    ) -> dict[str, Any] | None:
        kwargs: dict[str, Any] = {
            "name": product.get("name", "Unknown"),
            "source": "llm-batch-descriptions",
            "source_tier": SourceTier.T3_AI_GENERATED,
            "source_url": "",
        }
        has_new = False

        desc = item.get("company_description")
        if isinstance(desc, str) and len(desc.strip()) >= 10:
            kwargs["company_description"] = desc.strip()
            has_new = True

        comps = item.get("competitors")
        if isinstance(comps, list):
            validated = [
                str(v).strip().lower()
                for v in comps
                if isinstance(v, str)
                and v.strip()
                and re.match(r"^[a-z0-9-]+$", v.strip().lower())
                and v.strip().lower() in known_slugs
            ]
            if validated:
                kwargs["competitors"] = tuple(validated)
                has_new = True

        return kwargs if has_new else None

    return _apply


def run_phase_4(products: ProductList, **kw: Any) -> dict[str, int]:
    """Phase 4: LLM description & relationship enrichment."""
    known_slugs = frozenset(s for s, _ in products)
    return _run_llm_phase(
        "phase_4",
        "4 (desc+relations)",
        products,
        candidate_filter=lambda _s, p: (
            not p.get("company", {}).get("description") or not p.get("competitors")
        ),
        prompt_builder=_build_desc_prompt,
        result_applier=_make_desc_applier(known_slugs),
        **kw,
    )


# ---------------------------------------------------------------------------
# Combined: all enrichment fields in one prompt
# ---------------------------------------------------------------------------


def _build_combined_prompt(
    batch: list[tuple[str, dict[str, Any]]],
) -> str:
    """Build a single prompt that requests ALL enrichment fields at once."""
    lines = []
    for i, (slug, p) in enumerate(batch, 1):
        tags = ", ".join(p.get("tags", [])[:5])
        company_obj = p.get("company", {})
        company = company_obj.get("name", "")
        country = company_obj.get("headquarters", {}).get("country", "")
        lines.append(
            f'{i}. slug: "{slug}", '
            f'name: "{_sanitize(p.get("name", ""), 100)}", '
            f'company: "{_sanitize(company, 80)}", '
            f'country: "{country}", '
            f'product_type: "{p.get("product_type", "")}", '
            f'category: "{p.get("category", "")}", '
            f"tags: [{tags}], "
            f'description: "{_sanitize(p.get("description", ""))}"'
        )
    products_text = "\n".join(lines)
    return f"""Enrich these AI products with ALL of the following fields.
For each product, provide:

1. TRANSLATION (Chinese):
   - name_zh: Chinese name (use accepted Chinese name for well-known products)
   - description_zh: Chinese description (10-200 chars, factual, concise)
   - company_name_zh: Chinese company name

2. SEO & DISCOVERY:
   - target_audience: 2-4 audience types (lowercase, e.g. "developers", "marketers", "enterprises")
   - use_cases: 2-5 specific use cases in kebab-case (e.g. "code-generation", "image-editing")
   - sub_category: specific sub-category slug in kebab-case (e.g. "chatbot", "code-assistant")

3. TECH METADATA:
   - modalities: array from ["text", "image", "audio", "video", "code", "multimodal", "3d"]
   - platforms: array from ["web", "ios", "android", "desktop", "api", "cli", "self-hosted"]
   - api_available: boolean (does it offer a developer API?)
   - open_source: boolean (is it open-source?)

4. COMPANY & RELATIONSHIPS:
   - company_description: 1-2 sentence factual description of the COMPANY (50-200 chars)
   - competitors: 2-5 competitor product slugs in kebab-case (real, well-known products only)

5. HIRING & TEAM:
   - is_hiring: boolean — is the company likely actively hiring?
     * Well-funded startups and growing companies → true
     * Solo projects, small indie tools, discontinued products → false
   - tech_stack: array of 3-8 specific technologies the product is built with
     (programming languages, frameworks, cloud providers, databases, AI/ML frameworks)
     e.g. ["Python", "React", "AWS", "PostgreSQL", "PyTorch"]
   - team_size: one of ["solo", "small", "medium", "large", "enterprise"]
     (solo=1, small=2-10, medium=11-50, large=51-500, enterprise=500+)
   - careers_url: the company's careers/jobs page URL (e.g. "https://company.com/careers")
     * Infer from the product_url domain: try /careers, /jobs, /join-us, or known job board pages
     * Use null if you cannot confidently determine the URL

6. HEADQUARTERS:
   - headquarters_country: full English country name
     (e.g. "United States", "China", "Germany")
   - headquarters_city: city name
     (e.g. "San Francisco", "Beijing", "Berlin")
   - headquarters_country_code: ISO alpha-2 code
     (e.g. "US", "CN", "DE")

Rules:
- Use null for any field you cannot determine with confidence
- Do NOT hallucinate competitors — only include real, known products
- description_zh should be natural-sounding Chinese, not word-for-word translation
- Most web SaaS products have platforms: ["web"]
- Only set open_source: true if there is clear evidence
- For Chinese products, consider Chinese tech ecosystem (Alibaba Cloud, Tencent Cloud, etc.)
- For tech_stack, only include technologies you are reasonably confident about

Return ONLY a JSON array. Each object must include ALL keys:
slug, name_zh, description_zh, company_name_zh,
target_audience, use_cases, sub_category,
modalities, platforms, api_available, open_source,
company_description, competitors,
is_hiring, tech_stack, team_size, careers_url,
headquarters_country, headquarters_city, headquarters_country_code

Products:
{products_text}

Output ONLY the JSON array, no markdown, no explanation."""


def _make_combined_applier(
    known_slugs: frozenset[str],
) -> ResultApplier:
    """Create a result applier that extracts ALL enrichment fields at once."""

    def _apply(
        item: dict[str, Any],
        product: dict[str, Any],
        _ctx: dict[str, Any],
    ) -> dict[str, Any] | None:
        kwargs: dict[str, Any] = {
            "name": product.get("name", "Unknown"),
            "source": "llm-batch-combined",
            "source_tier": SourceTier.T3_AI_GENERATED,
            "source_url": "",
        }
        has_new = False

        # --- Translation fields ---
        for field, min_len in [
            ("name_zh", 1),
            ("company_name_zh", 1),
            ("description_zh", 10),
        ]:
            val = item.get(field)
            if isinstance(val, str) and len(val.strip()) >= min_len:
                kwargs[field] = val.strip()
                has_new = True

        # --- SEO fields ---
        for field in ("target_audience", "use_cases"):
            val = item.get(field)
            if isinstance(val, list):
                clean = [
                    str(v).strip() for v in val if isinstance(v, str) and v.strip()
                ]
                if clean:
                    kwargs[field] = tuple(clean)
                    has_new = True

        sub = item.get("sub_category")
        if isinstance(sub, str) and len(sub.strip()) >= 2:
            kwargs["sub_category"] = sub.strip()
            has_new = True

        # --- Tech metadata ---
        for field, valid_set in [
            ("modalities", _VALID_MODALITIES),
            ("platforms", _VALID_PLATFORMS),
        ]:
            val = item.get(field)
            if isinstance(val, list):
                clean = [
                    v.strip().lower()
                    for v in val
                    if isinstance(v, str) and v.strip().lower() in valid_set
                ]
                if clean:
                    kwargs[field] = tuple(clean)
                    has_new = True

        for bool_field in ("api_available", "open_source"):
            val = item.get(bool_field)
            if isinstance(val, bool):
                kwargs[bool_field] = val
                has_new = True

        # --- Company description ---
        desc = item.get("company_description")
        if isinstance(desc, str) and len(desc.strip()) >= 10:
            kwargs["company_description"] = desc.strip()
            has_new = True

        # --- Competitors (validated against known slugs) ---
        comps = item.get("competitors")
        if isinstance(comps, list):
            validated = [
                str(v).strip().lower()
                for v in comps
                if isinstance(v, str)
                and v.strip()
                and re.match(r"^[a-z0-9-]+$", v.strip().lower())
                and v.strip().lower() in known_slugs
            ]
            if validated:
                kwargs["competitors"] = tuple(validated)
                has_new = True

        # --- Hiring: is_hiring ---
        is_hiring = item.get("is_hiring")
        if isinstance(is_hiring, bool):
            kwargs["hiring_is_hiring"] = is_hiring
            has_new = True

        # --- Hiring: tech_stack ---
        tech_stack = item.get("tech_stack")
        if isinstance(tech_stack, list):
            clean_ts = [
                str(v).strip()
                for v in tech_stack
                if isinstance(v, str) and len(v.strip()) >= 1
            ]
            if clean_ts:
                kwargs["hiring_tech_stack"] = tuple(clean_ts)
                has_new = True

        # --- Hiring: team_size → company_employee_count_range ---
        _SIZE_TO_RANGE = {
            "solo": "1-10",
            "small": "1-10",
            "medium": "11-50",
            "large": "51-200",
            "enterprise": "1001-5000",
        }
        team_size = item.get("team_size")
        if isinstance(team_size, str) and team_size.strip().lower() in _SIZE_TO_RANGE:
            existing = product.get("company", {}).get("employee_count_range")
            if not existing:
                kwargs["company_employee_count_range"] = _SIZE_TO_RANGE[
                    team_size.strip().lower()
                ]
                has_new = True

        # --- Hiring: careers_url ---
        careers_url = item.get("careers_url")
        if isinstance(careers_url, str) and careers_url.strip().startswith("http"):
            kwargs["hiring_careers_url"] = careers_url.strip()
            has_new = True

        # --- Headquarters ---
        skip_country = {"unknown", "n/a", "na", "none", ""}
        existing_country = (
            product.get("company", {})
            .get(
                "headquarters",
                {},
            )
            .get("country", "")
        )

        hq_country = item.get("headquarters_country")
        if (
            not existing_country
            and isinstance(hq_country, str)
            and len(hq_country.strip()) >= 2
            and hq_country.strip().lower() not in skip_country
        ):
            country_val = hq_country.strip()
            kwargs["company_headquarters_country"] = country_val
            has_new = True

            # Auto-resolve country_code from our map if LLM didn't provide
            hq_code = item.get("headquarters_country_code")
            if isinstance(hq_code, str) and len(hq_code.strip()) == 2:
                kwargs["company_headquarters_country_code"] = hq_code.strip().upper()
            elif country_val in _COUNTRY_TO_CODE:
                kwargs["company_headquarters_country_code"] = _COUNTRY_TO_CODE[
                    country_val
                ]

        hq_city = item.get("headquarters_city")
        existing_city = (
            product.get("company", {})
            .get(
                "headquarters",
                {},
            )
            .get("city", "")
        )
        if (
            not existing_city
            and isinstance(hq_city, str)
            and len(hq_city.strip()) >= 2
            and hq_city.strip().lower() not in skip_country
        ):
            kwargs["company_headquarters_city"] = hq_city.strip()
            has_new = True

        return kwargs if has_new else None

    return _apply


# ---------------------------------------------------------------------------
# Phase 6: Hiring & tech stack inference
# ---------------------------------------------------------------------------


def _build_hiring_prompt(
    batch: list[tuple[str, dict[str, Any]]],
) -> str:
    """Build a prompt that requests hiring status and tech stack for each product."""
    lines = []
    for i, (slug, p) in enumerate(batch, 1):
        company = p.get("company", {})
        company_name = company.get("name", "")
        hq_country = company.get("headquarters", {}).get("country", "")
        category = p.get("category", "")
        tags = ", ".join(p.get("tags", [])[:5])
        desc = _sanitize(p.get("description", ""), 150)
        lines.append(
            f'{i}. slug: "{slug}", '
            f'name: "{_sanitize(p.get("name", ""), 100)}", '
            f'company: "{_sanitize(company_name, 80)}", '
            f'country: "{hq_country}", '
            f'category: "{category}", '
            f"tags: [{tags}], "
            f'description: "{desc}"'
        )
    products_text = "\n".join(lines)
    return f"""For each AI product/company below, provide hiring and technology information.

For each product, provide:

1. HIRING STATUS:
   - is_hiring: boolean — is the company likely actively hiring? Consider:
     * Well-funded startups and growing companies are usually hiring
     * Solo projects, small indie tools, and discontinued products are usually NOT hiring
     * Companies with 50+ employees are almost always hiring

2. TECH STACK (what the product is built with):
   - tech_stack: array of 3-8 specific technologies (programming languages, frameworks, cloud providers, databases, AI/ML frameworks)
   - Examples: ["Python", "React", "AWS", "PostgreSQL", "PyTorch", "FastAPI", "Docker", "Kubernetes"]
   - For AI products, include the AI/ML stack (PyTorch, TensorFlow, LangChain, etc.)
   - Only include technologies you are reasonably confident about based on the product type and category

3. TEAM SIZE ESTIMATE:
   - team_size: one of ["solo", "small", "medium", "large", "enterprise"] where:
     * solo = 1 person
     * small = 2-10 people
     * medium = 11-50 people
     * large = 51-500 people
     * enterprise = 500+ people

4. CAREERS URL:
   - careers_url: the company's careers/jobs page URL
     * Infer from the product domain: try /careers, /jobs, /join-us, or known job board pages
     * Use null if you cannot confidently determine the URL

Rules:
- Use null for any field you cannot determine with confidence
- Do NOT guess specific technologies without reasonable basis
- For Chinese products (country: China), consider Chinese tech ecosystem (Alibaba Cloud, Tencent Cloud, Baidu, etc.)
- Web-based AI SaaS typically uses: Python backend, React/Vue frontend, cloud hosting
- is_hiring: lean toward true for established companies, false for solo/indie projects

Return ONLY a JSON array. Each object must include ALL keys:
slug, is_hiring, tech_stack, team_size, careers_url

Products:
{products_text}

Output ONLY the JSON array, no markdown, no explanation."""


_VALID_TEAM_SIZES = frozenset(["solo", "small", "medium", "large", "enterprise"])


def _apply_hiring(
    item: dict[str, Any],
    product: dict[str, Any],
    _ctx: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply hiring enrichment result to a product."""
    kwargs: dict[str, Any] = {
        "name": product.get("name", "Unknown"),
        "source": "llm-batch-hiring",
        "source_tier": SourceTier.T3_AI_GENERATED,
        "source_url": "",
    }
    has_new = False

    # --- is_hiring (boolean) → ScrapedProduct.hiring_is_hiring ---
    is_hiring = item.get("is_hiring")
    if isinstance(is_hiring, bool):
        kwargs["hiring_is_hiring"] = is_hiring
        has_new = True

    # --- tech_stack → ScrapedProduct.hiring_tech_stack ---
    tech_stack = item.get("tech_stack")
    if isinstance(tech_stack, list):
        clean = [
            str(v).strip()
            for v in tech_stack
            if isinstance(v, str) and len(v.strip()) >= 1
        ]
        if clean:
            kwargs["hiring_tech_stack"] = tuple(clean)
            has_new = True

    # --- team_size → ScrapedProduct.company_employee_count_range ---
    # Map to schema-valid enum: 1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5001+
    _SIZE_MAP = {
        "solo": "1-10",
        "small": "1-10",
        "medium": "11-50",
        "large": "51-200",
        "enterprise": "1001-5000",
    }
    team_size = item.get("team_size")
    if isinstance(team_size, str) and team_size.strip().lower() in _SIZE_MAP:
        # Only set if company doesn't already have this data (from a higher-tier source)
        existing = product.get("company", {}).get("employee_count_range")
        if not existing:
            kwargs["company_employee_count_range"] = _SIZE_MAP[
                team_size.strip().lower()
            ]
            has_new = True

    # --- careers_url → ScrapedProduct.hiring_careers_url ---
    careers_url = item.get("careers_url")
    if isinstance(careers_url, str) and careers_url.strip().startswith("http"):
        kwargs["hiring_careers_url"] = careers_url.strip()
        has_new = True

    return kwargs if has_new else None


# ---------------------------------------------------------------------------
# Phase callbacks registry (for reuse across generate/apply/run modes)
# ---------------------------------------------------------------------------

# Tuple: (candidate_filter, prompt_builder, result_applier, default_batch_size)
PhaseCallbacks = tuple[CandidateFilter, PromptBuilder, ResultApplier, int]


def _get_phase_callbacks(
    phase: int,
    products: ProductList,
) -> PhaseCallbacks:
    """Return (candidate_filter, prompt_builder, result_applier, default_batch_size)
    for the given LLM phase.
    """
    if phase == 1:
        return (
            lambda _s, p: not p.get("name_zh") or not p.get("description_zh"),
            _build_translation_prompt,
            _apply_translation,
            20,
        )
    if phase == 2:
        return (
            lambda _s, p: (
                not p.get("target_audience")
                or not p.get("use_cases")
                or not p.get("sub_category")
            ),
            _build_seo_prompt,
            _apply_seo,
            20,
        )
    if phase == 3:
        return (
            lambda _s, p: (
                not p.get("modalities")
                or not p.get("platforms")
                or p.get("api_available") is None
                or p.get("open_source") is None
            ),
            _build_tech_prompt,
            _apply_tech,
            30,
        )
    if phase == 4:
        known_slugs = frozenset(s for s, _ in products)
        return (
            lambda _s, p: (
                not p.get("company", {}).get("description") or not p.get("competitors")
            ),
            _build_desc_prompt,
            _make_desc_applier(known_slugs),
            10,
        )
    if phase == 5:
        # Combined: any product missing ANY enrichable field (incl. hiring)
        known_slugs = frozenset(s for s, _ in products)
        return (
            lambda _s, p: (
                not p.get("name_zh")
                or not p.get("description_zh")
                or not p.get("target_audience")
                or not p.get("use_cases")
                or not p.get("sub_category")
                or not p.get("modalities")
                or not p.get("platforms")
                or p.get("api_available") is None
                or p.get("open_source") is None
                or not p.get("company", {}).get("description")
                or not p.get("competitors")
                or p.get("hiring", {}).get("is_hiring") is None
                or not p.get("hiring", {}).get("tech_stack")
                or not p.get("company", {}).get("headquarters", {}).get("country")
            ),
            _build_combined_prompt,
            _make_combined_applier(known_slugs),
            50,
        )
    if phase == 6:
        # Hiring & tech stack: any product missing hiring data
        return (
            lambda _s, p: (
                p.get("hiring", {}).get("is_hiring") is None
                or not p.get("hiring", {}).get("tech_stack")
            ),
            _build_hiring_prompt,
            _apply_hiring,
            60,
        )
    raise ValueError(f"No LLM callbacks for phase {phase}")


# ---------------------------------------------------------------------------
# CLI batch mode: generate prompt files
# ---------------------------------------------------------------------------


def generate_phase_prompts(
    phase: int,
    products: ProductList,
    *,
    batch_size: int | None = None,
    limit: int | None = None,
    resume: bool = False,
) -> dict[str, int]:
    """Generate prompt files + runner script for a phase.

    Creates:
      data/.enrichment_prompts/phase_N/batch_NNN.prompt.txt
      data/.enrichment_prompts/phase_N/batch_NNN.slugs.json
      data/.enrichment_prompts/phase_N/run_all.sh
    """
    phase_key = f"phase_{phase}"
    candidate_filter, prompt_builder, _applier, default_bs = _get_phase_callbacks(
        phase,
        products,
    )
    bs = batch_size or default_bs

    completed_slugs = set(load_checkpoint().get(phase_key, []) if resume else [])
    candidates = [
        (s, p)
        for s, p in products
        if s not in completed_slugs and candidate_filter(s, p)
    ]
    if limit:
        candidates = candidates[:limit]

    phase_prompts_dir = PROMPTS_DIR / phase_key
    phase_prompts_dir.mkdir(parents=True, exist_ok=True)

    num_batches = (len(candidates) + bs - 1) // bs if candidates else 0
    stats: dict[str, int] = {"candidates": len(candidates), "batches": 0}

    logger.info(
        "Generating %d prompt files for %d candidates (batch_size=%d)",
        num_batches,
        len(candidates),
        bs,
    )

    for batch_idx, batch_start in enumerate(
        range(0, len(candidates), bs),
        start=1,
    ):
        batch = candidates[batch_start : batch_start + bs]
        batch_name = f"batch_{batch_idx:03d}"

        # Write prompt file
        prompt = prompt_builder(batch)
        prompt_file = phase_prompts_dir / f"{batch_name}.prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Write slug manifest
        slugs_file = phase_prompts_dir / f"{batch_name}.slugs.json"
        slugs_file.write_text(
            json.dumps(
                {"slugs": [s for s, _ in batch]},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        stats["batches"] += 1

    # Generate runner script
    run_script = phase_prompts_dir / "run_all.sh"
    # Use POSIX paths in the script for cross-platform compatibility
    prompts_posix = phase_prompts_dir.as_posix()
    responses_posix = (RESPONSES_DIR / phase_key).as_posix()
    run_script.write_text(
        f"""#!/bin/bash
# Auto-generated runner for phase {phase} enrichment prompts.
# Review prompts in {prompts_posix}/ before running.

PROMPTS_DIR="{prompts_posix}"
RESPONSES_DIR="{responses_posix}"
mkdir -p "$RESPONSES_DIR"

# Allow running inside a Claude Code session (unset nesting guard)
unset CLAUDECODE 2>/dev/null

for f in "$PROMPTS_DIR"/batch_*.prompt.txt; do
    batch=$(basename "$f" .prompt.txt)
    resp="$RESPONSES_DIR/${{batch}}.response.txt"
    if [ -f "$resp" ]; then
        echo "Skip $batch (response exists)"
        continue
    fi
    echo "Processing $batch..."
    claude -p --model haiku < "$f" > "$resp"
    if [ $? -ne 0 ]; then
        echo "ERROR: $batch failed, removing partial response"
        rm -f "$resp"
    fi
    sleep 1
done

echo ""
echo "Done! Apply responses with:"
echo "  python scripts/batch_enrich.py --phase {phase} --apply-responses"
""",
        encoding="utf-8",
    )

    logger.info(
        "Generated %d prompt files in %s",
        stats["batches"],
        phase_prompts_dir,
    )
    logger.info("Run:  bash %s", run_script)
    return stats


# ---------------------------------------------------------------------------
# CLI batch mode: apply saved responses
# ---------------------------------------------------------------------------


def apply_phase_responses(
    phase: int,
    products: ProductList,
    *,
    dry_run: bool = False,
    resume: bool = False,
) -> dict[str, int]:
    """Apply saved response files back to product JSONs.

    Reads:
      data/.enrichment_prompts/phase_N/batch_NNN.slugs.json
      data/.enrichment_responses/phase_N/batch_NNN.response.txt

    Applies via phase-specific result_applier + TieredMerger.
    """
    phase_key = f"phase_{phase}"
    _filter, _builder, result_applier, _bs = _get_phase_callbacks(phase, products)

    phase_prompts_dir = PROMPTS_DIR / phase_key
    phase_responses_dir = RESPONSES_DIR / phase_key

    if not phase_prompts_dir.exists():
        logger.error("No prompt files found at %s", phase_prompts_dir)
        logger.error("Run --generate-prompts first.")
        return {"processed": 0, "enriched": 0, "errors": 1}

    completed_slugs = set(load_checkpoint().get(phase_key, []) if resume else [])
    merger = TieredMerger()

    # Build product lookup from full list
    product_map = {s: p for s, p in products}

    stats: dict[str, int] = {
        "processed": 0,
        "enriched": 0,
        "batches": 0,
        "errors": 0,
        "skipped_missing": 0,
    }

    # Process each batch that has both slugs.json and response.txt
    slug_files = sorted(phase_prompts_dir.glob("batch_*.slugs.json"))
    logger.info("Found %d batch slug files in %s", len(slug_files), phase_prompts_dir)

    for slugs_file in slug_files:
        batch_name = slugs_file.stem.replace(".slugs", "")
        response_file = phase_responses_dir / f"{batch_name}.response.txt"

        if not response_file.exists():
            stats["skipped_missing"] += 1
            logger.debug("No response for %s, skipping", batch_name)
            continue

        # Load slug manifest
        manifest = json.loads(slugs_file.read_text(encoding="utf-8"))
        slugs = manifest.get("slugs", [])

        # Load and parse response
        response_text = response_file.read_text(encoding="utf-8")
        parsed = _parse_json_array(response_text)
        stats["batches"] += 1

        if parsed is None:
            stats["errors"] += 1
            logger.warning("Failed to parse response for %s", batch_name)
            continue

        # Build slug->product map for this batch
        batch_slugs = set(slugs)
        for item in parsed:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug", "")
            if slug not in batch_slugs or slug not in product_map:
                continue
            if slug in completed_slugs:
                continue

            product = product_map[slug]
            kwargs = result_applier(item, product, {})

            if kwargs and not dry_run:
                scraped = ScrapedProduct(**kwargs)
                merger.merge_update(slug, scraped)
                stats["enriched"] += 1
            elif kwargs and dry_run:
                logger.info(
                    "[DRY-RUN] %s: would set %s",
                    slug,
                    [
                        k
                        for k in kwargs
                        if k not in ("name", "source", "source_tier", "source_url")
                    ],
                )
                stats["enriched"] += 1

            completed_slugs.add(slug)
            stats["processed"] += 1

        logger.info(
            "Batch %s: %d processed, %d enriched total",
            batch_name,
            stats["processed"],
            stats["enriched"],
        )

    if not dry_run:
        save_checkpoint(phase_key, completed_slugs)

    if stats["skipped_missing"]:
        logger.info(
            "%d batches skipped (no response file yet)",
            stats["skipped_missing"],
        )
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch enrichment for AI product data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Default mode (no --phase): Ask local Claude for ALL fields in one prompt.
  Fields: translation, SEO, tech metadata, company info, hiring & tech stack.

  python scripts/batch_enrich.py --generate-prompts           # Generate prompts
  bash data/.enrichment_prompts/phase_5/run_all.sh            # Run via Claude CLI
  python scripts/batch_enrich.py --apply-responses            # Apply results

Optional --phase for specific use cases:
  0  Rule-based enrichment only (free, no LLM)
  1-4  Individual field groups (for API backend)
        """,
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=None,
        choices=[0, 1, 2, 3, 4, 5, 6],
        help="Override: run a specific phase (default: combined all-in-one)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Products per LLM batch (default: phase-dependent)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview enrichments without writing to disk",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of products to process",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"LLM model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--rate-limit-delay",
        type=float,
        default=DEFAULT_RATE_LIMIT_DELAY,
        help="Seconds between API calls (default: 1.0)",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["api", "cli"],
        default="api",
        help="LLM backend: 'api' (Anthropic API) or 'cli' (Claude CLI)",
    )
    parser.add_argument(
        "--generate-prompts",
        action="store_true",
        help="Generate prompt files only (phases 1-4)",
    )
    parser.add_argument(
        "--apply-responses",
        action="store_true",
        help="Apply saved response files (phases 1-4)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Resolve phase: default to 5 (combined all-in-one) for LLM modes
    phase = args.phase
    if phase is None:
        if args.generate_prompts or args.apply_responses or args.backend == "cli":
            phase = 5  # Combined: all fields in one prompt
        else:
            parser.error(
                "Specify --phase (0 for rule-based) or use"
                " --generate-prompts / --apply-responses (defaults to combined)"
            )

    if args.generate_prompts and args.apply_responses:
        parser.error("Cannot use --generate-prompts and --apply-responses together")
    if phase == 0 and (args.generate_prompts or args.apply_responses):
        parser.error("--phase 0 is rule-based only, no prompts to generate/apply")
    if phase == 0 and args.backend == "cli":
        parser.error("--phase 0 is rule-based only, no LLM backend needed")

    logger.info("Loading products from %s ...", PRODUCTS_DIR)
    products = load_all_products()
    logger.info("Loaded %d products", len(products))

    # Route to the appropriate mode
    if args.generate_prompts:
        stats = generate_phase_prompts(
            phase,
            products,
            batch_size=args.batch_size,
            limit=args.limit,
            resume=args.resume,
        )
    elif args.apply_responses:
        stats = apply_phase_responses(
            phase,
            products,
            dry_run=args.dry_run,
            resume=args.resume,
        )
    elif phase == 0:
        stats = run_phase_0(
            products,
            dry_run=args.dry_run,
            limit=args.limit,
            resume=args.resume,
        )
    else:
        # LLM execution mode (API or CLI backend)
        cb = _get_phase_callbacks(phase, products)
        stats = _run_llm_phase(
            f"phase_{phase}",
            f"{phase} (combined)" if phase == 5 else str(phase),
            products,
            *cb[:3],
            batch_size=args.batch_size or cb[3],
            dry_run=args.dry_run,
            limit=args.limit,
            resume=args.resume,
            model=args.model,
            rate_limit_delay=args.rate_limit_delay,
            backend=args.backend,
        )

    logger.info("=" * 60)
    logger.info("Done! %s", f"(phase {phase})" if phase != 5 else "(all fields)")
    for key, value in stats.items():
        logger.info("  %s: %d", key, value)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
