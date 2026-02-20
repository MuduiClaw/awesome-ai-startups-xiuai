#!/usr/bin/env python3
"""Migrate product categories from 11-category to 22-category taxonomy.

Three-tier routing strategy:
  Tier 1: 8 unchanged categories pass through directly.
  Tier 2: Route by sub_category field (~86% of reclassified products).
  Tier 3: Keyword fallback on name + description + tags (~14% remainder).

Also fixes the product_type='llm' bug for 3D model generators (68 products).

Usage:
    python scripts/migrate_categories.py --dry-run   # Preview changes
    python scripts/migrate_categories.py --execute    # Apply to disk
    python scripts/migrate_categories.py --stats      # Show distribution
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "products"

# ── Tier 1: Categories that pass through unchanged ─────────────────────────

PASSTHROUGH_CATEGORIES = frozenset(
    {
        "ai-foundation-model",
        "ai-dev-platform",
        "ai-infrastructure",
        "ai-data-platform",
        "ai-search-retrieval",
        "ai-hardware",
        "ai-security-governance",
        "ai-science-research",
    }
)

# ── Tier 2: Sub-category routing tables ─────────────────────────────────────

# ai-creative-media → split into 3 categories
_CREATIVE_MEDIA_ROUTES: list[tuple[tuple[str, ...], str]] = [
    # Video & animation
    (
        (
            "video",
            "animation",
            "animated",
            "movie",
            "tiktok video",
            "youtube video",
            "short video",
            "ugc",
            "lip sync",
            "face swap video",
            "avatar video",
            "cartoon video",
            "commercial",
            "subtitle",
            "dubbing",
            "video translat",
            "video editor",
            "video enhancer",
            "video search",
            "video summar",
            "video recording",
            "script to video",
            "image to video",
            "text to video",
            "video to video",
            "music video",
        ),
        "ai-video-animation",
    ),
    # Audio & music
    (
        (
            "audio",
            "music",
            "song",
            "voice",
            "speech",
            "sound",
            "vocal",
            "transcri",
            "lyrics",
            "cover generator",
            "midi",
            "beat",
            "melody",
            "singing",
            "rap generator",
            "stems",
            "splitter",
            "mastering",
            "noise cancel",
            "tts",
            "text to speech",
            "speech to text",
            "voice clon",
            "voice chang",
            "voice over",
            "voice enhanc",
            "voice translat",
            "audio to text",
            "celebrity voice",
        ),
        "ai-audio-music",
    ),
    # Image & design (default for creative-media)
    (
        (
            "image",
            "photo",
            "art",
            "design",
            "illustration",
            "avatar",
            "headshot",
            "profile picture",
            "poster",
            "infographic",
            "graphic",
            "ppt",
            "presentation",
            "interior",
            "3d",
            "game",
            "anime",
            "background",
            "watermark",
            "eraser",
            "remover",
            "upscal",
            "enhancer",
            "style transfer",
            "product photo",
            "clothing",
            "realistic",
            "inpainting",
            "outpainting",
            "expand",
            "combiner",
            "colorize",
            "pixel",
            "t shirt",
            "icon",
            "landscape",
            "ux design",
            "charting",
            "describe image",
            "image scan",
            "face recogni",
            "image detect",
            "image translat",
            "crop",
            "passport",
            "baby gen",
            "object remover",
            "floor plan",
            "drawing",
            "sketch",
            "texture",
            "pattern",
            "wallpaper",
            "mockup",
            "svg",
            "vector",
            "selfie",
            "yearbook",
            "disney",
            "sticker",
            "coloring book",
            "comic",
            "manga",
            "waifu",
            "album cover",
            "tattoo",
        ),
        "ai-image-design",
    ),
]

# ai-application → split into multiple categories
_APPLICATION_ROUTES: list[tuple[tuple[str, ...], str]] = [
    # Education
    (
        (
            "education",
            "tutoring",
            "course",
            "homework",
            "language learning",
            "flashcard",
            "lesson plan",
            "quiz",
            "teacher",
            "math",
        ),
        "ai-education",
    ),
    # Translation
    (
        ("translat", "translate"),
        "ai-translation",
    ),
    # Customer service
    (
        (
            "customer service",
            "call center",
            "helpdesk",
            "customer support",
        ),
        "ai-customer-service",
    ),
    # Marketing & commerce
    (
        (
            "marketing",
            "seo",
            "ad generator",
            "advertising",
            "ad creative",
            "digital marketing",
            "email marketing",
            "marketing plan",
            "affiliate marketing",
            "lead generation",
            "landing page",
            "shopify",
            "shopping",
            "ecommerce",
            "e-commerce",
            "commerce",
            "influencer",
            "caption generator",
            "hashtag",
            "instagram",
            "tiktok",
            "facebook",
            "social media post",
        ),
        "ai-marketing-commerce",
    ),
    # Social & entertainment
    (
        (
            "social media",
            "character",
            "roleplay",
            "girlfriend",
            "boyfriend",
            "dating",
            "games",
            "gaming",
            "nsfw",
            "anime girlfriend",
            "meme",
            "dream interpreter",
            "religion",
            "bible",
            "god",
            "joke",
            "rizz",
            "pickup lines",
            "dirty talk",
            "travel",
            "trip planner",
            "recipe",
            "cooking",
            "fitness",
            "mental health",
            "beauty",
            "hairstyle",
            "fashion",
            "outfit",
            "predictions",
            "sports",
            "poker",
            "news",
            "podcast",
        ),
        "ai-social-entertainment",
    ),
    # Productivity
    (
        (
            "productivity",
            "workflow",
            "task management",
            "scheduling",
            "project management",
            "meeting",
            "calendar",
            "note",
            "knowledge management",
            "knowledge base",
            "forms",
            "spreadsheet",
            "excel",
            "document",
            "pdf",
            "ocr",
            "scanner",
            "files",
            "whiteboard",
            "mind map",
            "email assistant",
            "copilot",
            "coaching",
            "consulting",
            "monitor",
            "erp",
            "tools directory",
        ),
        "ai-productivity",
    ),
    # Writing & content
    (
        (
            "writing",
            "copywriting",
            "blog",
            "rewriter",
            "paraphras",
            "story",
            "book",
            "essay",
            "report generator",
            "text generator",
            "script writing",
            "creative writing",
            "novel",
            "letter",
            "email generator",
            "article",
            "content",
            "seo writing",
            "humanizer",
            "bypasser",
            "grammar",
            "proofread",
            "answer",
            "reply",
            "response generator",
            "message generator",
            "bio generator",
            "name generator",
            "domain name",
            "title generator",
            "description generator",
            "review generator",
            "prompt",
            "newsletter",
            "paragraph",
            "sentence",
            "summary",
            "reader",
        ),
        "ai-writing-content",
    ),
    # Chatbot & agent (default for application)
    (
        (
            "chatbot",
            "chat",
            "assistant",
            "agent",
            "conversational",
        ),
        "ai-chatbot-agent",
    ),
]

# ai-enterprise-vertical → split into multiple categories
_ENTERPRISE_ROUTES: list[tuple[tuple[str, ...], str]] = [
    # HR & recruiting
    (
        (
            "recruit",
            "hiring",
            "job",
            "resume",
            "interview",
            "talent",
            "hr",
            "human resource",
        ),
        "ai-hr-recruiting",
    ),
    # Finance & legal
    (
        (
            "finance",
            "accounting",
            "tax",
            "investing",
            "trading",
            "crypto",
            "stock",
            "fintech",
            "legal",
            "contract",
            "law",
        ),
        "ai-finance-legal",
    ),
    # Sales & CRM
    (
        (
            "sales",
            "crm",
            "lead generation",
        ),
        "ai-sales-crm",
    ),
    # Marketing & commerce (from enterprise overlap)
    (
        (
            "seo",
            "ad generator",
            "advertising",
            "ad creative",
            "digital marketing",
            "email marketing",
            "marketing plan",
            "marketing",
        ),
        "ai-marketing-commerce",
    ),
]

# ── Tier 3: Keyword fallback on name + description + tags ───────────────────

_KEYWORD_FALLBACK: list[tuple[tuple[str, ...], str]] = [
    (
        ("education", "tutoring", "course", "learning", "teach", "school"),
        "ai-education",
    ),
    (("translat",), "ai-translation"),
    (
        ("customer service", "customer support", "helpdesk", "call center"),
        "ai-customer-service",
    ),
    (
        (
            "video",
            "animation",
            "movie",
        ),
        "ai-video-animation",
    ),
    (
        ("audio", "music", "song", "voice", "speech", "sound", "vocal", "podcast"),
        "ai-audio-music",
    ),
    (
        ("image", "photo", "art", "design", "illustration", "3d model", "avatar"),
        "ai-image-design",
    ),
    (
        ("marketing", "seo", "advertising", "ecommerce", "e-commerce", "influencer"),
        "ai-marketing-commerce",
    ),
    (
        (
            "social media",
            "character",
            "roleplay",
            "girlfriend",
            "dating",
            "game",
            "gaming",
            "entertainment",
            "nsfw",
        ),
        "ai-social-entertainment",
    ),
    (
        ("recruit", "hiring", "resume", "interview", "job search", "talent"),
        "ai-hr-recruiting",
    ),
    (
        ("finance", "accounting", "tax", "investing", "trading", "legal", "contract"),
        "ai-finance-legal",
    ),
    (("sales", "crm"), "ai-sales-crm"),
    (
        (
            "writing",
            "copywriting",
            "blog",
            "content creat",
            "story",
            "book",
            "essay",
            "report",
        ),
        "ai-writing-content",
    ),
    (
        (
            "productivity",
            "workflow",
            "task manag",
            "scheduling",
            "project manag",
            "meeting",
            "note",
            "document",
            "pdf",
        ),
        "ai-productivity",
    ),
]

# Default fallback per removed category
_CATEGORY_DEFAULTS: dict[str, str] = {
    "ai-application": "ai-chatbot-agent",
    "ai-creative-media": "ai-image-design",
    "ai-enterprise-vertical": "ai-marketing-commerce",
}


def migrate_product(data: dict) -> tuple[dict, list[str]]:
    """Migrate a single product's category. Returns (modified_data, list_of_changes)."""
    changes: list[str] = []
    category = data.get("category", "")
    sub = (data.get("sub_category") or "").lower()

    # ── Tier 1: Passthrough ──
    if category in PASSTHROUGH_CATEGORIES:
        changes.extend(_fix_product_type_bug(data))
        return data, changes

    # ── Tier 2: Sub-category routing ──
    new_cat = None

    if category == "ai-creative-media":
        new_cat = _route_by_subcategory(sub, _CREATIVE_MEDIA_ROUTES)
    elif category == "ai-application":
        new_cat = _route_by_subcategory(sub, _APPLICATION_ROUTES)
    elif category == "ai-enterprise-vertical":
        new_cat = _route_by_subcategory(sub, _ENTERPRISE_ROUTES)

    # ── Tier 3: Keyword fallback ──
    if new_cat is None:
        text = _build_search_text(data)
        new_cat = _route_by_keywords(text, _KEYWORD_FALLBACK)

    # ── Ultimate fallback ──
    if new_cat is None:
        new_cat = _CATEGORY_DEFAULTS.get(category, "ai-chatbot-agent")

    if new_cat != category:
        changes.append(f"category: {category} -> {new_cat}")
        data["category"] = new_cat

    # Fix product_type bug
    changes.extend(_fix_product_type_bug(data))

    return data, changes


def _route_by_subcategory(
    sub: str, routes: list[tuple[tuple[str, ...], str]]
) -> str | None:
    """Match sub_category against routing table keywords."""
    if not sub or sub == "none" or sub == "other":
        return None
    for keywords, target in routes:
        if any(kw in sub for kw in keywords):
            return target
    return None


def _route_by_keywords(
    text: str, rules: list[tuple[tuple[str, ...], str]]
) -> str | None:
    """Match combined text against keyword rules."""
    if not text:
        return None
    text_lower = text.lower()
    for keywords, target in rules:
        if any(kw in text_lower for kw in keywords):
            return target
    return None


def _build_search_text(data: dict) -> str:
    """Combine name + description + tags for keyword matching."""
    parts = [
        data.get("name", ""),
        data.get("description", ""),
    ]
    tags = data.get("tags", [])
    if isinstance(tags, list):
        parts.extend(tags)
    keywords = data.get("keywords", [])
    if isinstance(keywords, list):
        parts.extend(keywords)
    return " ".join(str(p) for p in parts if p)


def _fix_product_type_bug(data: dict) -> list[str]:
    """Fix 3D model products incorrectly marked as product_type='llm'."""
    changes: list[str] = []
    if data.get("product_type") == "llm":
        sub = (data.get("sub_category") or "").lower()
        name = (data.get("name") or "").lower()
        cat = data.get("category", "")
        # If it's a 3D model generator or in creative/image/video category, fix it
        if (
            "3d" in sub
            or "3d" in name
            or "model generator" in sub
            or cat in ("ai-image-design", "ai-video-animation", "ai-audio-music")
        ):
            data["product_type"] = "app"
            changes.append("product_type: llm -> app (3D model bug fix)")
    return changes


def run_migration(mode: str) -> None:
    """Run the migration in the specified mode."""
    if not DATA_DIR.exists():
        print(f"Error: {DATA_DIR} not found")
        sys.exit(1)

    files = sorted(DATA_DIR.glob("*.json"))
    print(f"Found {len(files)} product files in {DATA_DIR}")

    stats_before: Counter[str] = Counter()
    stats_after: Counter[str] = Counter()
    changed_count = 0
    ptype_fixes = 0
    all_changes: list[tuple[str, list[str]]] = []

    for filepath in files:
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  SKIP {filepath.name}: {exc}")
            continue

        stats_before[data.get("category", "UNKNOWN")] += 1

        migrated, changes = migrate_product(data)

        stats_after[migrated.get("category", "UNKNOWN")] += 1

        if changes:
            changed_count += 1
            all_changes.append((filepath.name, changes))
            ptype_fix = any("product_type" in c for c in changes)
            if ptype_fix:
                ptype_fixes += 1

            if mode == "execute":
                filepath.write_text(
                    json.dumps(migrated, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

    # ── Report ──
    print(f"\n{'=' * 60}")
    print(f"Migration {'EXECUTED' if mode == 'execute' else 'DRY RUN'}")
    print(f"{'=' * 60}")
    print(f"Total files:        {len(files)}")
    print(f"Changed:            {changed_count}")
    print(f"product_type fixes: {ptype_fixes}")

    if mode == "dry-run" and all_changes:
        print("\n--- Sample changes (first 30) ---")
        for fname, changes in all_changes[:30]:
            for c in changes:
                print(f"  {fname}: {c}")
        if len(all_changes) > 30:
            print(f"  ... and {len(all_changes) - 30} more")

    print("\n--- Category distribution BEFORE ---")
    for cat, cnt in stats_before.most_common():
        pct = 100.0 * cnt / len(files) if files else 0
        print(f"  {cat:30s} {cnt:>6d}  ({pct:5.1f}%)")

    print("\n--- Category distribution AFTER ---")
    for cat, cnt in stats_after.most_common():
        pct = 100.0 * cnt / len(files) if files else 0
        print(f"  {cat:30s} {cnt:>6d}  ({pct:5.1f}%)")

    # Verify no removed categories remain
    removed = {"ai-application", "ai-creative-media", "ai-enterprise-vertical"}
    remaining_removed = removed & set(stats_after.keys())
    if remaining_removed:
        print(f"\n  WARNING: Removed categories still present: {remaining_removed}")
    else:
        print("\n  OK: All removed categories eliminated")

    # Check no category exceeds 20%
    if stats_after:
        max_cat = stats_after.most_common(1)[0]
        max_pct = 100.0 * max_cat[1] / len(files) if files else 0
        if max_pct > 20:
            print(f"  WARNING: {max_cat[0]} has {max_pct:.1f}% of products")
        else:
            print(
                f"  OK: No category exceeds 20% (max: {max_cat[0]} at {max_pct:.1f}%)"
            )


def show_stats() -> None:
    """Show current category distribution."""
    files = sorted(DATA_DIR.glob("*.json"))
    stats: Counter[str] = Counter()
    for filepath in files:
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            stats[data.get("category", "UNKNOWN")] += 1
        except Exception:
            pass
    print(f"Total: {len(files)}")
    for cat, cnt in stats.most_common():
        pct = 100.0 * cnt / len(files) if files else 0
        print(f"  {cat:30s} {cnt:>6d}  ({pct:5.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate product categories (11 -> 22)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes")
    group.add_argument("--execute", action="store_true", help="Apply changes to disk")
    group.add_argument("--stats", action="store_true", help="Show current distribution")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.dry_run:
        run_migration("dry-run")
    elif args.execute:
        run_migration("execute")


if __name__ == "__main__":
    main()
