"""Audit products with empty product_url and generate a grouped Markdown report."""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "products"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "AUDIT_EMPTY_URL.md"


def main() -> None:
    empty_url_products: list[dict] = []

    for fpath in sorted(DATA_DIR.glob("*.json")):
        slug = fpath.stem
        try:
            with open(fpath, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue

        url = d.get("product_url", "")
        if url and url.strip():
            continue

        name = d.get("name", "")
        desc = d.get("description", "")
        source_list = d.get("sources", [])
        source_name = source_list[0].get("source_name", "") if source_list else ""
        company = d.get("company", {})
        company_url = company.get("url", "") or company.get("website", "") or ""
        cat = d.get("category", "")

        is_stub = desc.endswith("is an AI product.") or len(desc) < 20
        has_junk = (
            desc.startswith("[") or desc.startswith("- !") or chr(92) in desc[:20]
        )

        empty_url_products.append(
            {
                "slug": slug,
                "name": name,
                "desc": desc[:120],
                "source": source_name,
                "company_url": company_url[:80],
                "cat": cat,
                "is_stub": is_stub,
                "has_junk": has_junk,
            }
        )

    junk = [p for p in empty_url_products if p["has_junk"]]
    stubs = [p for p in empty_url_products if p["is_stub"] and not p["has_junk"]]
    real = [p for p in empty_url_products if not p["is_stub"] and not p["has_junk"]]

    out: list[str] = []
    out.append("# Empty product_url - Detailed Review\n")
    out.append(f"Total: **{len(empty_url_products)}** products\n")
    out.append(f"- A. Junk (garbled/malformed): **{len(junk)}** -> RECOMMEND DELETE")
    out.append(f"- B. Stub/placeholder: **{len(stubs)}** -> RECOMMEND DELETE")
    out.append(
        f"- C. Real products missing URL: **{len(real)}** -> CAN FIX or DELETE\n"
    )

    # --- Section A ---
    out.append("---\n")
    out.append("## A. Junk Data (RECOMMEND DELETE)\n")
    out.append("| # | Slug | Name | Source | Description |")
    out.append("|---|------|------|--------|-------------|")
    for i, p in enumerate(junk, 1):
        out.append(
            f'| {i} | `{p["slug"]}` | {p["name"]} | {p["source"]} | {p["desc"][:70]} |'
        )

    # --- Section B ---
    out.append("\n---\n")
    out.append("## B. Stub / Placeholder (RECOMMEND DELETE)\n")
    out.append("| # | Slug | Name | Source | Description |")
    out.append("|---|------|------|--------|-------------|")
    for i, p in enumerate(stubs, 1):
        out.append(
            f'| {i} | `{p["slug"]}` | {p["name"]} | {p["source"]} | {p["desc"][:70]} |'
        )

    # --- Section C ---
    out.append("\n---\n")
    out.append("## C. Real Products Missing URL (need decision)\n")
    out.append("These have meaningful descriptions but no product_url.\n")
    out.append("| # | Slug | Name | Source | Category | Company URL | Description |")
    out.append("|---|------|------|--------|----------|-------------|-------------|")
    for i, p in enumerate(real, 1):
        out.append(
            f'| {i} | `{p["slug"]}` | {p["name"]} | {p["source"]} '
            f'| {p["cat"]} | {p["company_url"]} | {p["desc"][:80]} |'
        )

    report = "\n".join(out)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report written to {OUT_PATH}")
    print(f"A. Junk: {len(junk)}")
    print(f"B. Stub: {len(stubs)}")
    print(f"C. Real: {len(real)}")


if __name__ == "__main__":
    main()
