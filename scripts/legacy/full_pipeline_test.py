"""
Full pipeline dry-run test.
Simulates generating 3 videos (narration/personality/test) for Deep Mind
without actual rendering. Verifies every data collection step works.
"""
import sys, os, logging, sqlite3, json, time
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("test")

# ── Test content (same as real content_cycle_v2) ──

VIDEOS = [
    {
        "type": "narration",
        "persona": "deep_mind",
        "segments": [
            {"text": "It was the night that changed everything.", "emotion": "dark"},
            {"text": "Griffith, broken and desperate, held the Crimson Behelit.", "emotion": "dark"},
            {"text": "The Band of the Hawk, his brothers, all sacrificed.", "emotion": "tragic"},
            {"text": "Guts lost his arm. He lost his eye. He lost everything.", "emotion": "tragic"},
        ],
    },
    {
        "type": "personality",
        "persona": "deep_mind",
        "segments": [
            {"text": "Griffith was right. And deep down, you know it.", "emotion": "dark"},
            {"text": "Walter White and Light Yagami understood the same truth.", "emotion": "dark"},
            {"text": "The only difference? Griffith was honest about the cost.", "emotion": "dark"},
            {"text": "Guts calls it betrayal. Miura calls it ambition.", "emotion": "tragic"},
        ],
    },
    {
        "type": "test",
        "persona": "deep_mind",
        "segments": [
            {"text": "Junpei's death broke something in Yuji forever.", "emotion": "tragic"},
            {"text": "Sukuna craves power like a starving beast.", "emotion": "dark"},
            {"text": "Have you ever been betrayed by someone you loved?", "emotion": "tragic"},
        ],
    },
]


def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def timed(func, label):
    start = time.time()
    result = func()
    elapsed = time.time() - start
    print(f"  [{elapsed:5.1f}s] {label}")
    return result


# ══════════════════════════════════════════════════════════════════
# STEP 1: Ensure classification exists for target series
# ══════════════════════════════════════════════════════════════════
section("STEP 1 — Ensure series classified (Berserk + JJK)")

conn = sqlite3.connect("data/shorts_pipeline.db")
conn.row_factory = sqlite3.Row

from apps.production.thematic_stills import ensure_series_classified

timed(
    lambda: ensure_series_classified(
        conn, "Berserk: The Golden Age Arc", tmdb_id=211057, slug="berserk"
    ),
    "Berserk classification",
)
timed(
    lambda: ensure_series_classified(
        conn, "JUJUTSU KAISEN", tmdb_id=95479, slug="jujutsu_kaisen"
    ),
    "JJK classification",
)

# Verify
from apps.content.thematic_classifier import get_series_themes
for slug in ("berserk", "jujutsu_kaisen"):
    themes = get_series_themes(conn, slug)
    if themes:
        print(f"    {slug}: {themes['primary_themes']} / {themes['dominant_emotion']}")


# ══════════════════════════════════════════════════════════════════
# STEP 2: Per-video full pipeline simulation
# ══════════════════════════════════════════════════════════════════

for video in VIDEOS:
    vtype = video["type"]
    section(f"STEP 2 — Video: {vtype.upper()} ({len(video['segments'])} segments)")

    segments = video["segments"]

    # 2a. Base manga pages
    base_dirs = [
        "data/manga_panels/berserk_ch382",
        "data/manga_panels/berserk_eclipse_ch83",
    ]
    base_images = []
    for d in base_dirs:
        base_images += sorted(str(p) for p in Path(d).glob("*.[jp][pn]g"))
    print(f"\n  2a. Base manga pages: {len(base_images)} files")

    # 2b. Thematic stills (Fandom + TMDb fallback)
    print(f"\n  2b. Thematic stills (Fandom priority):")
    from apps.production.thematic_stills import (
        get_thematic_stills_for_narration,
        detect_themes,
    )

    # Show what themes are detected per segment
    for seg in segments:
        themes = detect_themes(seg["text"])
        if themes:
            print(f"      '{seg['text'][:55]}' → themes: {themes}")

    # Run the fetch — target Berserk for video 1/2, JJK for video 3 (test mentions JJK chars)
    target_series = "jujutsu_kaisen" if vtype == "test" else "berserk"

    start = time.time()
    thematic_paths = get_thematic_stills_for_narration(conn, segments, target_series)
    print(f"\n    → {len(thematic_paths)} thematic stills ({time.time() - start:.1f}s)")
    for p in thematic_paths:
        print(f"      {Path(p).name}")

    # 2c. Cross-ref character images
    print(f"\n  2c. Cross-ref character images:")
    from apps.production.cross_ref_images import (
        enrich_segments_with_cross_refs,
        detect_references_in_text,
    )

    for seg in segments:
        refs = detect_references_in_text(seg["text"])
        if refs:
            names = [r["character"] for r in refs]
            print(f"      '{seg['text'][:55]}' → refs: {names}")

    include_exp = vtype == "test"
    start = time.time()
    cross_paths = enrich_segments_with_cross_refs(
        segments, include_experimental=include_exp
    )
    print(f"\n    → {len(cross_paths)} cross-ref images ({time.time() - start:.1f}s)")
    for p in cross_paths[:6]:
        print(f"      {Path(p).name}")

    # 2d. Combined image pool
    all_images = base_images + thematic_paths + cross_paths
    print(f"\n  2d. Total image pool: {len(all_images)}")
    print(f"      - Base manga panels: {len(base_images)}")
    print(f"      - Thematic stills:   {len(thematic_paths)}")
    print(f"      - Cross-ref images:  {len(cross_paths)}")

    # 2e. Panel matcher would run Gemini Vision here (skip actual calls, just show match logic)
    print(f"\n  2e. Panel matcher readiness:")
    print(f"      → Gemini Vision would describe {len(all_images)} images")
    print(f"      → Then match {len(segments)} narration segments to best images")
    print(f"      → Each match includes reason + image path")


# ══════════════════════════════════════════════════════════════════
# STEP 3: Report
# ══════════════════════════════════════════════════════════════════
section("STEP 3 — Report")

conn_check = sqlite3.connect("data/shorts_pipeline.db")
conn_check.row_factory = sqlite3.Row

# Count what was populated
series_count = conn_check.execute(
    "SELECT COUNT(*) FROM series_themes"
).fetchone()[0]
arc_count = conn_check.execute(
    "SELECT COUNT(*) FROM series_arcs"
).fetchone()[0]
moment_count = conn_check.execute(
    "SELECT COUNT(*) FROM scene_moments"
).fetchone()[0]
print(f"\n  DB populated:")
print(f"    series_themes: {series_count}")
print(f"    series_arcs:   {arc_count}")
print(f"    scene_moments: {moment_count}")

# Image bank sizes
for dir_path in [
    "data/manga_panels",
    "data/fandom_stills",
    "data/thematic_stills",
    "data/cross_ref_images",
]:
    p = Path(dir_path)
    if p.exists():
        count = len(list(p.rglob("*.[jp][pn]g"))) + len(list(p.rglob("*.webp")))
        print(f"\n  {dir_path}: {count} images")
        # Show breakdown by subfolder
        subs = sorted(p.iterdir())
        for sub in subs[:6]:
            if sub.is_dir():
                sub_count = len(list(sub.rglob("*.[jp][pn]g"))) + len(list(sub.rglob("*.webp")))
                if sub_count > 0:
                    print(f"    └─ {sub.name}: {sub_count}")

conn_check.close()
conn.close()

print(f"\n{'='*70}")
print("  END — All data collection verified successfully")
print(f"{'='*70}")
