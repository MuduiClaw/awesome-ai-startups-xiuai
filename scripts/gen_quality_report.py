"""Generate data quality review report as Markdown."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

PRODUCTS_DIR = Path(__file__).resolve().parent.parent / "data" / "products"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "DATA_QUALITY_REVIEW.md"

SOCIAL_DOMAINS = {
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "www.twitter.com",
    "www.x.com",
    "www.facebook.com",
    "www.instagram.com",
    "www.linkedin.com",
    "www.youtube.com",
    "www.tiktok.com",
    "ads.tiktok.com",
}

# Domains that are valid as product URLs even though they look social
ALLOWED_SOCIAL = {"copilot.github.com"}


def load_products() -> list[tuple[str, dict]]:
    results = []
    for f in sorted(PRODUCTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append((f.stem, data))
        except Exception:
            continue
    return results


def get_sources(data: dict) -> list[str]:
    return [s.get("source_name", "?") for s in data.get("sources", [])]


def main() -> None:
    products = load_products()
    total = len(products)
    today = date.today().isoformat()

    # --- Collect issues ---
    url_map: dict[str, list[str]] = {}
    desc_map: dict[str, list[str]] = {}
    parking: list[dict] = []
    social_urls: list[dict] = []
    store_urls: list[dict] = []
    no_url: list[dict] = []
    generic_tags: list[dict] = []
    name_eq_desc: list[dict] = []
    desc_just_name: list[dict] = []

    for slug, data in products:
        name = data.get("name", "")
        desc = data.get("description", "")
        purl = data.get("product_url", "")
        sources = get_sources(data)
        tags = data.get("tags", [])

        # URL tracking
        if purl:
            url_map.setdefault(purl, []).append(slug)
        else:
            no_url.append({"slug": slug, "name": name, "sources": sources})

        # Description tracking
        if desc.strip():
            desc_map.setdefault(desc.strip(), []).append(slug)

        # Parking pages
        if "domain parking" in desc.lower():
            parking.append(
                {
                    "slug": slug,
                    "name": name,
                    "url": purl,
                    "desc": desc,
                    "sources": sources,
                }
            )

        # Social media URLs
        if purl:
            try:
                domain = urlparse(purl).netloc.lower()
                if domain in SOCIAL_DOMAINS and domain not in ALLOWED_SOCIAL:
                    social_urls.append(
                        {"slug": slug, "name": name, "url": purl, "sources": sources}
                    )
                if "play.google.com" in domain or "apps.apple.com" in domain:
                    store_urls.append(
                        {"slug": slug, "name": name, "url": purl, "sources": sources}
                    )
            except Exception:
                pass

        # Generic tags
        if tags and all(
            t.lower() in ("other", "ai", "tool", "app", "other ai tools") for t in tags
        ):
            generic_tags.append(
                {"slug": slug, "name": name, "tags": tags, "sources": sources}
            )

        # Name == description
        if name and desc and name.lower().strip() == desc.lower().strip():
            name_eq_desc.append({"slug": slug, "name": name, "sources": sources})

        # Description is just padded name
        if (
            desc
            and name
            and len(desc) < len(name) * 2
            and name.lower() in desc.lower()
            and len(desc) < 30
        ):
            desc_just_name.append(
                {"slug": slug, "name": name, "desc": desc, "sources": sources}
            )

    # Post-process
    dup_url_groups = {u: slugs for u, slugs in url_map.items() if len(slugs) > 1}

    # Template descriptions: same desc, different product URLs
    template_descs: dict[str, list[str]] = {}
    for desc_text, slugs in desc_map.items():
        if len(slugs) < 2:
            continue
        urls = set()
        for s in slugs:
            f = PRODUCTS_DIR / f"{s}.json"
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                urls.add(d.get("product_url", ""))
            except Exception:
                pass
        if len(urls) > 1:
            template_descs[desc_text] = slugs

    # --- Generate report ---
    lines: list[str] = []

    def w(s: str = "") -> None:
        lines.append(s)

    w("# Data Quality Review Report")
    w("")
    w(f"Generated: {today}  ")
    w(f"Total products: {total}  ")
    w("")
    w("---")
    w("")
    w("## How to use this report")
    w("")
    w("Each section lists problematic products with their slug, name, URL, and source.")
    w("After reviewing, you can:")
    w("- **Delete** the JSON file from `data/products/` if the product is invalid")
    w("- **Edit** the JSON file to fix incorrect fields")
    w("- **Mark as reviewed** by checking the checkbox `[x]`")
    w("")
    w("---")
    w("")

    # === Section 1: Template/Fake Descriptions ===
    w("## 1. Fake/Template Descriptions (different products, same generic description)")
    w("")
    w(
        "**Root cause:** Toolify API returns auto-generated template text instead of real product descriptions."
    )
    w(
        "**Action:** Replace description via LLM enrichment or manual edit, or delete if product is invalid."
    )
    w("")
    for desc_text, slugs in sorted(template_descs.items(), key=lambda x: -len(x[1])):
        short = desc_text[:80] + "..." if len(desc_text) > 80 else desc_text
        w(f'### "{short}"')
        w("")
        for s in slugs:
            f = PRODUCTS_DIR / f"{s}.json"
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            nm = d.get("name", "")
            pu = d.get("product_url", "")
            src = get_sources(d)
            w(f'- [ ] `{s}` | {nm} | {pu} | source: {", ".join(src)}')
        w("")

    # === Section 2: Domain Parking ===
    w("## 2. Domain Parking Pages")
    w("")
    w("**Root cause:** Product website is a parked domain, not a real product.")
    w("**Action:** Delete these products.")
    w("")
    for p in parking:
        w(
            f'- [ ] `{p["slug"]}` | {p["name"]} | {p["url"]} | source: {", ".join(p["sources"])}'
        )
    w("")

    # === Section 3: Social Media URLs ===
    w("## 3. Product URL Points to Social Media")
    w("")
    w("**Root cause:** Source data has social media profile as product URL.")
    w("**Action:** Find real product URL or delete.")
    w("")
    for p in social_urls:
        w(
            f'- [ ] `{p["slug"]}` | {p["name"]} | {p["url"]} | source: {", ".join(p["sources"])}'
        )
    w("")

    # === Section 4: Store URLs ===
    w("## 4. Product URL Points to App Store / Google Play")
    w("")
    w(
        "**Root cause:** App store scraper used store listing URL as product_url instead of product website."
    )
    w("**Action:** Replace with real product website URL.")
    w("")
    for p in store_urls:
        w(
            f'- [ ] `{p["slug"]}` | {p["name"]} | {p["url"]} | source: {", ".join(p["sources"])}'
        )
    w("")

    # === Section 5: Duplicate product_url ===
    w("## 5. Duplicate Product URLs (different slugs, same URL)")
    w("")
    w("**Root cause:** Deduplicator failed to merge products from different sources.")
    w("**Action:** Merge into one product or delete the duplicate.")
    w("")
    for url, slugs in sorted(dup_url_groups.items()):
        w(f"### {url}")
        w("")
        for s in slugs:
            f = PRODUCTS_DIR / f"{s}.json"
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            nm = d.get("name", "")
            src = get_sources(d)
            w(f'- [ ] `{s}` | {nm} | source: {", ".join(src)}')
        w("")

    # === Section 6: Missing product_url ===
    w("## 6. Missing Product URL")
    w("")
    w("**Root cause:** App store scraper could not extract external website URL.")
    w(
        "**Action:** Find and add the real product URL, or delete if not a standalone product."
    )
    w("")
    for p in no_url:
        w(f'- [ ] `{p["slug"]}` | {p["name"]} | source: {", ".join(p["sources"])}')
    w("")

    # === Section 7: Name == Description ===
    w("## 7. Name Equals Description")
    w("")
    w("**Root cause:** Source only provided a name with no real description.")
    w("**Action:** Write a real description or mark for LLM enrichment.")
    w("")
    for p in name_eq_desc:
        w(f'- [ ] `{p["slug"]}` | {p["name"]} | source: {", ".join(p["sources"])}')
    w("")

    # === Section 8: Description is just padded name ===
    w("## 8. Description is Essentially Just the Product Name")
    w("")
    w(
        "**Root cause:** Source provided minimal description that is just a restatement of the name."
    )
    w("**Action:** Write a real description or mark for LLM enrichment.")
    w("")
    for p in desc_just_name:
        w(
            f'- [ ] `{p["slug"]}` | {p["name"]} | desc: "{p["desc"]}" | source: {", ".join(p["sources"])}'
        )
    w("")

    # === Section 9: Generic Tags ===
    w("## 9. Tags Are All Generic (no information value)")
    w("")
    w('**Root cause:** Source only provided generic tags like ["Other"].')
    w("**Action:** Low priority. Can be enriched later via LLM.")
    w(f"**Count:** {len(generic_tags)} products")
    w("")
    w("<details>")
    w(f"<summary>Click to expand full list ({len(generic_tags)} products)</summary>")
    w("")
    for p in generic_tags:
        w(
            f'- [ ] `{p["slug"]}` | {p["name"]} | tags: {p["tags"]} | source: {", ".join(p["sources"])}'
        )
    w("")
    w("</details>")
    w("")

    # === Summary ===
    w("---")
    w("")
    w("## Summary")
    w("")
    w("| # | Issue | Count | Priority |")
    w("|---|-------|-------|----------|")
    template_count = sum(len(s) for s in template_descs.values())
    dup_url_count = sum(len(s) for s in dup_url_groups.values())
    w(
        f"| 1 | Fake/template descriptions | {template_count} products in {len(template_descs)} groups | High |"
    )
    w(f"| 2 | Domain parking pages | {len(parking)} | High |")
    w(f"| 3 | Social media as product URL | {len(social_urls)} | High |")
    w(f"| 4 | App Store as product URL | {len(store_urls)} | Medium |")
    w(
        f"| 5 | Duplicate product URLs | {dup_url_count} products ({len(dup_url_groups)} URLs) | Medium |"
    )
    w(f"| 6 | Missing product URL | {len(no_url)} | Medium |")
    w(f"| 7 | Name equals description | {len(name_eq_desc)} | Low |")
    w(f"| 8 | Description is just name | {len(desc_just_name)} | Low |")
    w(f"| 9 | Generic tags only | {len(generic_tags)} | Low |")
    w("")

    report = "\n".join(lines)
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"Written {len(lines)} lines to {OUTPUT}")
    print(f"File size: {len(report):,} bytes")


if __name__ == "__main__":
    main()
