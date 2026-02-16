#!/usr/bin/env python3
"""Download product icons from CDN URLs to website/public/icons/.

Usage:
    python scripts/download_icons.py                    # Download all icons
    python scripts/download_icons.py --limit 100        # Download first 100
    python scripts/download_icons.py --concurrency 20   # Use 20 threads
    python scripts/download_icons.py --dry-run          # Preview without downloading
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "products"
ICONS_DIR = PROJECT_ROOT / "website" / "public" / "icons"

# Common image extensions to preserve; default to .png
VALID_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".ico"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_extension(url: str) -> str:
    """Extract file extension from URL, defaulting to .png."""
    path = urlparse(url).path
    ext = Path(path).suffix.lower()
    return ext if ext in VALID_EXTS else ".png"


def download_icon(slug: str, icon_url: str, dest_dir: Path) -> tuple[str, bool, str]:
    """Download a single icon. Returns (slug, success, message)."""
    ext = get_extension(icon_url)
    dest = dest_dir / f"{slug}{ext}"

    if dest.exists():
        return (slug, True, "already exists")

    try:
        req = Request(icon_url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=15) as resp:
            data = resp.read()
        dest.write_bytes(data)
        return (slug, True, f"downloaded ({len(data)} bytes)")
    except (HTTPError, URLError, OSError, TimeoutError) as e:
        return (slug, False, str(e))


def collect_icons() -> list[tuple[str, str]]:
    """Collect (slug, icon_url) pairs from all product JSON files."""
    items: list[tuple[str, str]] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            icon_url = data.get("icon_url", "")
            if icon_url:
                items.append((path.stem, icon_url))
        except (json.JSONDecodeError, OSError):
            continue
    return items


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download product icons to website/public/icons/"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="Max icons to download (0=all)"
    )
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Number of parallel downloads"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without downloading"
    )
    args = parser.parse_args()

    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Scanning {DATA_DIR} for product icons...")
    items = collect_icons()
    print(f"Found {len(items)} products with icon_url")

    if args.limit > 0:
        items = items[: args.limit]
        print(f"Limited to {len(items)} icons")

    if args.dry_run:
        for slug, url in items[:20]:
            ext = get_extension(url)
            print(f"  {slug}{ext} <- {url[:80]}...")
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")
        return

    success_count = 0
    fail_count = 0
    skip_count = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(download_icon, slug, url, ICONS_DIR): slug
            for slug, url in items
        }

        for i, future in enumerate(as_completed(futures), 1):
            slug, ok, msg = future.result()
            if ok:
                if "already exists" in msg:
                    skip_count += 1
                else:
                    success_count += 1
            else:
                fail_count += 1
                print(f"  FAIL: {slug} - {msg}")

            if i % 100 == 0:
                elapsed = time.time() - start
                print(f"  Progress: {i}/{len(items)} ({elapsed:.1f}s)")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Downloaded: {success_count}")
    print(f"  Skipped (exists): {skip_count}")
    print(f"  Failed: {fail_count}")


if __name__ == "__main__":
    main()
