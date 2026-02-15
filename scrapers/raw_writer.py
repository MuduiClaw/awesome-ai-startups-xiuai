"""Raw data writer — saves source-native dicts to data/raw/<source>/."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from scrapers.config import RAW_DIR


def _make_filename(item: dict[str, object], index: int) -> str:
    """Derive a filename from a raw item dict.

    Priority:
    1. Source-specific ID fields (id, appId, trackId, handle, tool_id).
    2. Product name slugified and truncated to 50 chars.
    3. Fallback: zero-padded index.
    """
    for key in ("id", "appId", "trackId", "handle", "tool_id"):
        value = item.get(key)
        if value is not None:
            return _safe_filename(str(value))

    name = item.get("name")
    if isinstance(name, str) and name.strip():
        return _safe_filename(name.strip()[:50])

    return f"{index:04d}"


def _safe_filename(text: str) -> str:
    """Convert arbitrary text to a filesystem-safe filename component."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s.\-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-.")
    return slug or "unknown"


class RawDataWriter:
    """Write raw scraped data to data/raw/<source>/<filename>.json."""

    def write(
        self,
        source_name: str,
        items: list[dict[str, object]],
    ) -> int:
        """Write items to disk. Returns number of files written."""
        out_dir = RAW_DIR / source_name
        out_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC).isoformat(timespec="seconds")
        written = 0
        used_paths: set[str] = set()

        for i, item in enumerate(items):
            filename = _make_filename(item, i)
            filepath = out_dir / f"{filename}.json"

            # Dedup: append -001, -002, ... on collision
            if str(filepath) in used_paths:
                suffix = 1
                while True:
                    candidate = out_dir / f"{filename}-{suffix:03d}.json"
                    if str(candidate) not in used_paths:
                        filepath = candidate
                        break
                    suffix += 1
            used_paths.add(str(filepath))

            doc = {
                "_meta": {
                    "source": source_name,
                    "scraped_at": now,
                },
                "_raw": item,
            }

            filepath.write_text(
                json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )
            written += 1

        return written

    @staticmethod
    def preview(items: list[dict[str, object]], max_items: int = 1) -> str:
        """Return a formatted preview string for dry-run output."""
        if not items:
            return "(no items)"
        lines: list[str] = []
        for item in items[:max_items]:
            lines.append(json.dumps(item, indent=2, ensure_ascii=False, default=str))
        return "\n".join(lines)
