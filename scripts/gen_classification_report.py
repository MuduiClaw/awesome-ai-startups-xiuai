"""Generate product classification quality report as Markdown."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

PRODUCTS_DIR = Path(__file__).resolve().parent.parent / "data" / "products"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "CLASSIFICATION_REVIEW.md"

# Keyword signals for detecting misclassified ai-application products
_SHOULD_BE_CREATIVE: list[str] = [
    "image",
    "video",
    "photo",
    "art",
    "design",
    "music",
    "audio",
    "voice",
    "3d",
    "animation",
    "avatar",
    "interior",
]

_SHOULD_BE_DEV: list[str] = [
    "developer tool",
    "code assistant",
    "code generator",
    "app builder",
    "website builder",
    "no code",
    "low code",
    "devops",
    "sdk",
]

_SHOULD_BE_ENTERPRISE: list[str] = [
    "finance",
    "legal",
    "recruiting",
    "real estate",
    "sales",
    "marketing",
    "seo",
    "accounting",
    "crm",
    "email marketing",
    "ad generator",
    "advertising",
]

_SHOULD_BE_SEARCH: list[str] = [
    "search engine",
    "ai summarizer",
    "book summarizer",
    "pdf summarizer",
]

_SHOULD_BE_SECURITY: list[str] = [
    "plagiarism checker",
    "content detector",
    "ai detector",
    "ai checker",
]

_SHOULD_BE_FOUNDATION: list[str] = [
    "large language model",
    "llm",
    "foundation model",
]

RECLASSIFY_SIGNALS: dict[str, list[str]] = {
    "ai-creative-media": _SHOULD_BE_CREATIVE,
    "ai-dev-platform": _SHOULD_BE_DEV,
    "ai-enterprise-vertical": _SHOULD_BE_ENTERPRISE,
    "ai-search-retrieval": _SHOULD_BE_SEARCH,
    "ai-security-governance": _SHOULD_BE_SECURITY,
    "ai-foundation-model": _SHOULD_BE_FOUNDATION,
}


def load_products() -> dict[str, dict]:
    results: dict[str, dict] = {}
    for f in sorted(PRODUCTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results[f.stem] = data
        except Exception:
            continue
    return results


def get_sources(data: dict) -> list[str]:
    return [s.get("source_name", "?") for s in data.get("sources", [])]


def main() -> None:
    products = load_products()
    total = len(products)
    today = date.today().isoformat()

    cat_count: Counter[str] = Counter()
    type_count: Counter[str] = Counter()
    for d in products.values():
        cat_count[d.get("category", "")] += 1
        type_count[d.get("product_type", "")] += 1

    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("# Product Classification Review Report")
    w("")
    w(f"Generated: {today}  ")
    w(f"Total products: {total:,}  ")
    w("")
    w("---")
    w("")
    w("## Current Distribution")
    w("")
    w("| Category | Count | % |")
    w("|----------|-------|---|")
    for c, n in cat_count.most_common():
        w(f"| {c} | {n:,} | {n * 100 / total:.1f}% |")
    w("")
    w("| Product Type | Count | % |")
    w("|-------------|-------|---|")
    for t, n in type_count.most_common():
        w(f"| {t} | {n:,} | {n * 100 / total:.1f}% |")
    w("")
    w("---")
    w("")

    # =================================================================
    # ISSUE 1: Frankenstein Merges
    # =================================================================
    w(
        "## 1. CRITICAL: Frankenstein Merges (deduplicator over-merged unrelated products)"
    )
    w("")
    w(
        "**Root cause:** The deduplicator matched multiple unrelated products to the same"
    )
    w("slug, creating products with contaminated tags, keywords, and metadata from")
    w("completely different products.")
    w("")
    w("**Impact:** These products have incorrect data across ALL fields.")
    w("")
    w(
        "**Action:** Delete and re-scrape, or manually reconstruct from primary source only."
    )
    w("")

    franken: list[tuple[str, dict]] = []
    for slug, d in products.items():
        sources = d.get("sources", [])
        kw = d.get("keywords", [])
        if len(sources) > 10 or len(kw) > 50:
            franken.append((slug, d))
    franken.sort(key=lambda x: -len(x[1].get("sources", [])))

    for slug, d in franken:
        sources = d.get("sources", [])
        src_counts = Counter(s.get("source_name", "") for s in sources)
        src_str = ", ".join(f"{s}({c})" for s, c in src_counts.most_common())
        kw_n = len(d.get("keywords", []))
        w(
            f"- [ ] `{slug}` | {d.get('name', '')} | **{len(sources)} sources** | keywords: {kw_n} | {src_str}"
        )
    w("")

    # =================================================================
    # ISSUE 2: name_zh Contamination
    # =================================================================
    w("## 2. CRITICAL: name_zh Contamination (Chinese name from wrong product)")
    w("")
    w("**Root cause:** Over-merging caused Chinese metadata (name_zh, description_zh)")
    w("from one product to be applied to a completely different product.")
    w("")
    w(
        "**Action:** Remove incorrect name_zh/description_zh, or replace with correct values."
    )
    w("")

    for slug, d in sorted(products.items()):
        name = d.get("name", "")
        name_zh = d.get("name_zh", "")
        if not name_zh or not name:
            continue
        name_words = {w_word for w_word in name.lower().split() if len(w_word) > 2}
        if len(name_words) >= 2:
            overlap = any(nw in name_zh.lower() for nw in name_words)
            if not overlap and len(name_zh) > 3:
                w(f'- [ ] `{slug}` | name="{name}" | name_zh="{name_zh}"')
    w("")

    # =================================================================
    # ISSUE 3: 3D Model -> LLM
    # =================================================================
    w('## 3. HIGH: 3D Model Generators Misclassified as product_type="llm"')
    w("")
    w("**Root cause:** `_PRODUCT_TYPE_KEYWORDS` in `toolify.py` line 270:")
    w('`("llm", "model", "language-model", "foundation") -> "llm"`. The keyword')
    w('"model" in "3d model generator" triggers the LLM type assignment.')
    w("")
    w("**Fix:** Remove bare `model` from the keyword list. Use `language-model`")
    w("or add a negative check for `3d` before matching `model`.")
    w("")

    count_3d = 0
    for slug, d in sorted(products.items()):
        if d.get("category") == "ai-creative-media" and d.get("product_type") == "llm":
            count_3d += 1
            if count_3d <= 15:
                w(
                    f"- [ ] `{slug}` | {d.get('name', '')} | sub={d.get('sub_category', '')}"
                )
    if count_3d > 15:
        w(f"- ... and {count_3d - 15} more")
    w(f"\n**Affected:** {count_3d} products")
    w("")

    # =================================================================
    # ISSUE 4: Hardware = app
    # =================================================================
    w('## 4. HIGH: Hardware Products with product_type="app"')
    w("")
    w(
        "**Root cause:** No product_type inference for hardware. Toolify scraper defaults"
    )
    w('to "app" when no keyword match is found.')
    w("")
    w('**Fix:** Add `("robot", "hardware", "chip", "device") -> "hardware"` to')
    w("`_PRODUCT_TYPE_KEYWORDS` in `toolify.py`.")
    w("")

    for slug, d in sorted(products.items()):
        if d.get("category") == "ai-hardware" and d.get("product_type") == "app":
            url = d.get("product_url", "")
            w(f"- [ ] `{slug}` | {d.get('name', '')} | url: {url}")
    w("")

    # =================================================================
    # ISSUE 5: ai-application Default Bucket
    # =================================================================
    w("## 5. HIGH: Products Misclassified in ai-application (should be elsewhere)")
    w("")
    w("**Root cause:** Multiple sources:")
    w(
        "1. Toolify only uses `categories[0]` - if the first API category is unmapped, defaults to ai-application"
    )
    w("2. Some Toolify category handles are missing from `_CATEGORY_MAP`")
    w("3. AiBot and AiNav have limited category maps (13 entries each)")
    w("")

    misclassified: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for slug, d in products.items():
        if d.get("category") != "ai-application":
            continue
        sub = (d.get("sub_category") or "").lower()
        if not sub:
            continue
        for target_cat, kw_list in RECLASSIFY_SIGNALS.items():
            matched = False
            for kw in kw_list:
                if kw in sub:
                    matched = True
                    break
            if matched:
                misclassified[target_cat].append((slug, d.get("name", ""), sub))
                break

    total_mis = sum(len(v) for v in misclassified.values())
    w(f"**Affected:** ~{total_mis} products")
    w("")

    for cat, items in sorted(misclassified.items(), key=lambda x: -len(x[1])):
        w(f"### Should be `{cat}` ({len(items)} products)")
        w("")
        for slug_i, name_i, sub_i in items[:10]:
            w(f'- [ ] `{slug_i}` | {name_i} | sub_category="{sub_i}"')
        if len(items) > 10:
            w("")
            w("<details>")
            w(f"<summary>Show all {len(items)} products</summary>")
            w("")
            for slug_i, name_i, sub_i in items[10:]:
                w(f'- [ ] `{slug_i}` | {name_i} | sub_category="{sub_i}"')
            w("")
            w("</details>")
        w("")

    # =================================================================
    # ISSUE 6: product_type=other
    # =================================================================
    other_count = type_count.get("other", 0)
    w(f'## 6. MEDIUM: product_type="other" ({other_count:,} products)')
    w("")
    w("**Root cause:** Sources that do not infer product_type default to 'other':")
    w("")

    other_sources: Counter[str] = Counter()
    other_subs: Counter[str] = Counter()
    for d in products.values():
        if d.get("product_type") != "other":
            continue
        for s in d.get("sources", []):
            other_sources[s.get("source_name", "")] += 1
        sub = d.get("sub_category", "")
        if sub:
            other_subs[sub] += 1

    for src, n in other_sources.most_common():
        w(f"- {src}: {n}")
    w("")
    w("**Fix:** Add category-based product_type inference in the normalizer:")
    w("- ai-creative-media -> `app`")
    w("- ai-dev-platform -> `dev-tool`")
    w("- ai-foundation-model -> `llm`")
    w("- ai-hardware -> `hardware`")
    w("- others -> `app`")
    w("")

    # =================================================================
    # ISSUE 7: Sub-category contradicts category
    # =================================================================
    w("## 7. MEDIUM: Sub-category Contradicts Category")
    w("")
    w("**Root cause:** Toolify assigns category from `categories[0]` handle, but")
    w("sub_category directly from the same handle. When the first handle maps to the")
    w("wrong schema category, the sub_category reveals the mismatch.")
    w("")

    conflict_groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    creative_kw = {
        "image",
        "video",
        "photo",
        "art",
        "music",
        "audio",
        "voice",
        "3d",
        "animation",
    }
    dev_kw = {"code", "developer", "api", "sdk", "programming"}
    for slug, d in products.items():
        cat = d.get("category", "")
        sub = (d.get("sub_category") or "").lower()
        if not sub:
            continue
        if cat == "ai-application" and any(kw in sub for kw in creative_kw):
            conflict_groups[(cat, "creative")].append((slug, d.get("name", "")))
        elif cat == "ai-application" and any(kw in sub for kw in dev_kw):
            conflict_groups[(cat, "dev")].append((slug, d.get("name", "")))

    total_conflicts = sum(len(v) for v in conflict_groups.values())
    w(f"**Affected:** ~{total_conflicts} products")
    w("")

    # =================================================================
    # ISSUE 8: Toolify first-category-wins problem
    # =================================================================
    w("## 8. LOW: Toolify First-Category-Wins Problem")
    w("")
    w("**Root cause:** Each Toolify product has multiple category handles (avg 3-5).")
    w("The scraper only uses `categories[0]` for classification. If categories[0]")
    w(
        "is generic (e.g. `ai-chatbot`) but categories[1] is specific (e.g. `ai-code-assistant`),"
    )
    w("the product gets the wrong category.")
    w("")
    w(
        "**Example:** A product with categories = [`ai-chatbot`, `ai-code-assistant`, `ai-developer-tools`]"
    )
    w("gets classified as `ai-application` instead of `ai-dev-platform`.")
    w("")
    w(
        "**Fix:** Score all category handles against the mapping and use the most specific match."
    )
    w("")

    # =================================================================
    # ISSUE 9: Missing sub_category
    # =================================================================
    no_sub = sum(1 for d in products.values() if not d.get("sub_category"))
    w(f"## 9. LOW: Missing sub_category ({no_sub:,} products)")
    w("")
    w(f"**Affected:** {no_sub} products ({no_sub * 100 // total}%)")
    w("")
    w("**Root cause:** Products from app_store, google_play, and some aibot/ainav")
    w("categories lack sub_category mapping.")
    w("")

    # =================================================================
    # Summary
    # =================================================================
    w("---")
    w("")
    w("## Summary")
    w("")
    w("| # | Issue | Count | Priority | Fix Location |")
    w("|---|-------|-------|----------|-------------|")
    w(
        f"| 1 | Frankenstein merges | {len(franken)} products | CRITICAL | deduplicator + manual cleanup |"
    )
    w("| 2 | name_zh contamination | 5 products | CRITICAL | manual cleanup |")
    w(
        f"| 3 | 3D model -> LLM | {count_3d} products | HIGH | toolify.py _PRODUCT_TYPE_KEYWORDS |"
    )
    w("| 4 | Hardware = app | 10 products | HIGH | toolify.py _PRODUCT_TYPE_KEYWORDS |")
    w(
        f"| 5 | ai-application bucket | {total_mis} products | HIGH | _CATEGORY_MAP + normalizer |"
    )
    w(
        f"| 6 | product_type=other | {other_count:,} products | MEDIUM | normalizer fallback |"
    )
    w(
        f"| 7 | Sub contradicts category | {total_conflicts} products | MEDIUM | toolify.py category logic |"
    )
    w("| 8 | First-category-wins | unknown | LOW | toolify.py _tool_to_product |")
    w(f"| 9 | Missing sub_category | {no_sub:,} products | LOW | source scrapers |")
    w("")

    w("---")
    w("")
    w("## Recommended Fix Priority")
    w("")
    w("1. **Fix deduplicator** to prevent Frankenstein merges (CRITICAL)")
    w(
        "2. **Fix `_PRODUCT_TYPE_KEYWORDS`** in toolify.py: remove bare `model`, add `hardware` (HIGH)"
    )
    w("3. **Expand `_CATEGORY_MAP`** in toolify.py to cover more handles (HIGH)")
    w("4. **Add category-based product_type fallback** in normalizer (MEDIUM)")
    w("5. **Use best-match category** instead of first-category from Toolify API (LOW)")
    w("")

    report = "\n".join(lines)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"Written {len(lines)} lines to {OUTPUT}")
    print(f"File size: {len(report):,} bytes")


if __name__ == "__main__":
    main()
