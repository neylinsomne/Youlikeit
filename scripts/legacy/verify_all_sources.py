"""
End-to-end verification of all content capture sources.

Runs each module and verifies output with clear pass/fail logs.
"""
import sys, os, logging, sqlite3
# Force UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger("verify")


OK = "[OK]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"
INFO = "[..]"

results = {}


def section(name):
    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")


def ok(key, detail=""):
    results[key] = True
    print(f"  {OK} {key}: {detail}")


def fail(key, detail=""):
    results[key] = False
    print(f"  {FAIL} {key}: {detail}")


def skip(key, detail=""):
    results[key] = None
    print(f"  {SKIP} {key}: {detail}")


# ══════════════════════════════════════════════════════════════════
# 1. ENVIRONMENT
# ══════════════════════════════════════════════════════════════════

section("1. ENVIRONMENT")

has_gemini = bool(os.getenv("GEMINI_API_KEY"))
has_tmdb = bool(os.getenv("TMDB_API_KEY"))
has_trakt = bool(os.getenv("TRAKT_CLIENT_ID"))

if has_gemini:
    ok("GEMINI_API_KEY", "set")
else:
    fail("GEMINI_API_KEY", "missing")

if has_tmdb:
    ok("TMDB_API_KEY", "set")
else:
    fail("TMDB_API_KEY", "missing")

if has_trakt:
    ok("TRAKT_CLIENT_ID", "set")
else:
    skip("TRAKT_CLIENT_ID", "not set (optional)")

db_path = Path("data/shorts_pipeline.db")
if db_path.exists():
    ok("database", f"{db_path.stat().st_size // 1024} KB")
else:
    fail("database", "not found")


# ══════════════════════════════════════════════════════════════════
# 2. TRENDING ANIME (AniList + Jikan + TMDb)
# ══════════════════════════════════════════════════════════════════

section("2. TRENDING ANIME SOURCES")

try:
    from apps.signals.trending_anime import (
        fetch_anilist_trending,
        fetch_jikan_top_airing,
        fetch_tmdb_trending_anime,
        cross_reference_sources,
    )

    al = fetch_anilist_trending(top_n=5)
    if al:
        ok("anilist", f"{len(al)} trending (top: {al[0]['title'][:40]})")
    else:
        fail("anilist", "empty response")

    jk = fetch_jikan_top_airing(top_n=5)
    if jk:
        ok("jikan", f"{len(jk)} top airing (top: {jk[0]['title'][:40]})")
    else:
        fail("jikan", "empty response")

    if has_tmdb:
        tm = fetch_tmdb_trending_anime(top_n=5)
        if tm:
            ok("tmdb_anime", f"{len(tm)} trending")
        else:
            fail("tmdb_anime", "empty")

    xref = cross_reference_sources(top_n=5)
    if xref and len(xref) >= 3:
        multi_source = sum(1 for x in xref if len(x.get("sources", [])) >= 2)
        ok("cross_reference", f"{len(xref)} series, {multi_source} confirmed by 2+ sources")
    else:
        fail("cross_reference", "not enough data")
except Exception as e:
    fail("trending_anime", str(e)[:100])


# ══════════════════════════════════════════════════════════════════
# 3. MANGA DOWNLOADER (MangaDex + TMDb fallback)
# ══════════════════════════════════════════════════════════════════

section("3. MANGA DOWNLOADER")

try:
    from integrations.trending_manga_downloader import (
        get_available_series,
        download_manga_by_title,
    )

    avail = get_available_series()
    if avail:
        ok("local_cache", f"{len(avail)} series, {sum(avail.values())} total images")
        for slug, n in list(avail.items())[:5]:
            print(f"      └─ {slug}: {n} images")
    else:
        skip("local_cache", "empty (run download_trending_manga first)")

    # Live probe — quick one
    print(f"\n  {INFO} Live probe: Vinland Saga...")
    paths = download_manga_by_title("Vinland Saga", pages=2, chapters_to_sample=1)
    if paths:
        ok("mangadex_live", f"Vinland Saga: {len(paths)} pages downloaded/cached")
    else:
        fail("mangadex_live", "no pages")

except Exception as e:
    fail("manga_downloader", str(e)[:100])


# ══════════════════════════════════════════════════════════════════
# 4. FANDOM WIKI SCRAPER
# ══════════════════════════════════════════════════════════════════

section("4. FANDOM WIKI SCRAPER")

try:
    from integrations.fandom_scraper import (
        get_episode_images,
        get_character_images,
        download_episode_iconic_scenes,
        WIKI_SUBDOMAINS,
    )

    ok("wiki_mappings", f"{len(WIKI_SUBDOMAINS)} series mapped")

    # Probe JJK Ep13
    print(f"\n  {INFO} Probing JJK Ep13 images...")
    imgs = get_episode_images("jujutsu_kaisen", 13, max_images=5)
    if imgs:
        ok("jjk_episode_images", f"{len(imgs)} iconic scenes (top: '{imgs[0]['title'][:50]}')")
    else:
        fail("jjk_episode_images", "empty — wiki or API issue")

    # Probe character
    print(f"\n  {INFO} Probing Berserk Griffith character...")
    chars = get_character_images("berserk", "Griffith", max_images=3)
    if chars:
        ok("berserk_character", f"{len(chars)} character images")
    else:
        fail("berserk_character", "no images (check wiki subdomain)")

    # Actual download test (cached if exists)
    print(f"\n  {INFO} Downloading JJK Ep13 scenes...")
    paths = download_episode_iconic_scenes("jujutsu_kaisen", 13, max_images=3)
    if paths:
        ok("fandom_download", f"{len(paths)} files cached in data/fandom_stills/")
    else:
        fail("fandom_download", "download failed")

except Exception as e:
    fail("fandom_scraper", str(e)[:200])


# ══════════════════════════════════════════════════════════════════
# 5. THEMATIC CLASSIFIER
# ══════════════════════════════════════════════════════════════════

section("5. THEMATIC CLASSIFIER")

try:
    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row

    from apps.content.thematic_classifier import (
        get_series_themes,
        get_moments_by_themes,
        DEEP_THEMES,
    )

    ok("theme_vocabulary", f"{len(DEEP_THEMES)} deep themes defined")

    # Check Berserk classification
    berserk_themes = get_series_themes(conn, "berserk")
    if berserk_themes:
        ok("berserk_classified", f"themes: {berserk_themes['primary_themes']}")
    else:
        skip("berserk_classified", "not yet classified (run classify_series_full)")

    # Check JJK classification
    jjk_themes = get_series_themes(conn, "jujutsu_kaisen")
    if jjk_themes:
        ok("jjk_classified", f"themes: {jjk_themes['primary_themes']} / {jjk_themes['dominant_emotion']}")
    else:
        skip("jjk_classified", "not yet classified")

    # Check scene moments
    jjk_moments = get_moments_by_themes(conn, "jujutsu_kaisen", ["betrayal", "sacrifice"])
    if jjk_moments:
        ok("scene_moments", f"{len(jjk_moments)} JJK moments by theme match")
        for m in jjk_moments[:3]:
            print(f"      └─ Ep{m['episode_number']}: {m['moment_description'][:60]}")
    else:
        skip("scene_moments", "no moments yet")

    conn.close()

except Exception as e:
    fail("thematic_classifier", str(e)[:200])


# ══════════════════════════════════════════════════════════════════
# 6. CROSS-REF IMAGES (character mentions)
# ══════════════════════════════════════════════════════════════════

section("6. CROSS-REFERENCE CHARACTER IMAGES")

try:
    from apps.production.cross_ref_images import (
        detect_references_in_text,
        _get_active_map,
        CHARACTER_WORK_MAP,
        EXPERIMENTAL_CHARACTER_MAP,
    )

    ok("curated_pool", f"{len(CHARACTER_WORK_MAP)} characters (permanent)")
    ok("experimental_pool", f"{len(EXPERIMENTAL_CHARACTER_MAP)} characters (A/B test)")

    active = _get_active_map(include_trending=True)
    trending_chars = len(active) - len(CHARACTER_WORK_MAP)
    ok("active_map", f"{len(active)} total ({trending_chars} from trending cache)")

    # Detection test
    test_text = "Griffith and Walter White share the same flaw"
    refs = detect_references_in_text(test_text)
    if refs:
        names = [r["character"] for r in refs]
        ok("detection", f"detected: {names}")
    else:
        fail("detection", "should have found griffith + walter white")

except Exception as e:
    fail("cross_ref_images", str(e)[:200])


# ══════════════════════════════════════════════════════════════════
# 7. THEMATIC STILLS (full integration: Fandom → TMDb)
# ══════════════════════════════════════════════════════════════════

section("7. THEMATIC STILLS INTEGRATION")

try:
    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row

    from apps.production.thematic_stills import (
        detect_themes,
        get_thematic_stills_for_narration,
    )

    # Theme detection
    themes = detect_themes("Griffith's ambition led to betrayal and sacrifice")
    if set(themes) & {"ambition", "betrayal", "sacrifice"}:
        ok("theme_detection", f"{themes}")
    else:
        fail("theme_detection", f"got {themes}, expected [ambition, betrayal, sacrifice]")

    # Full pipeline: segments → stills (Fandom first, TMDb fallback)
    segments = [
        {"text": "Griffith betrayed the Band of the Hawk for power"},
        {"text": "The Eclipse was the ultimate sacrifice"},
    ]
    stills = get_thematic_stills_for_narration(conn, segments, "berserk")
    if stills:
        ok("full_pipeline", f"{len(stills)} thematic stills fetched")
        for p in stills[:3]:
            print(f"      └─ {Path(p).name}")
    else:
        skip("full_pipeline", "no stills (verify Berserk is classified)")

    conn.close()

except Exception as e:
    fail("thematic_stills", str(e)[:200])


# ══════════════════════════════════════════════════════════════════
# 8. LOCAL TRANSCRIBER (Whisper)
# ══════════════════════════════════════════════════════════════════

section("8. LOCAL TRANSCRIBER")

try:
    from integrations.local_transcriber import extract_quotes_from_transcription

    # Module loads
    ok("module_loaded", "local_transcriber importable")

    # Test quote extraction — realistic gaps (>500ms = not merged)
    fake_segments = [
        {"start_ms": 0, "end_ms": 2500, "text": "Lo que mas temo en el mundo no es fallar."},
        {"start_ms": 4000, "end_ms": 6500, "text": "Es no haber intentado con todas mis fuerzas."},
        {"start_ms": 8000, "end_ms": 10000, "text": "Subscribe for more content please."},  # skip_pattern
    ]
    quotes = extract_quotes_from_transcription(fake_segments)
    if len(quotes) >= 2:
        ok("quote_extraction", f"{len(quotes)}/3 quotes passed filter (noise removed)")
    else:
        fail("quote_extraction", f"only {len(quotes)}/3 passed — {[q['text'] for q in quotes]}")

except Exception as e:
    fail("local_transcriber", str(e)[:200])


# ══════════════════════════════════════════════════════════════════
# 9. PANEL MATCHER (Gemini Vision)
# ══════════════════════════════════════════════════════════════════

section("9. PANEL MATCHER")

try:
    from apps.production.panel_matcher import (
        describe_image_gemini,
        match_panels_to_segments,
    )

    # Find an image to describe
    sample_imgs = list(Path("data/manga_panels/berserk_eclipse_ch83").glob("*.[jp][pn]g"))
    if not sample_imgs:
        sample_imgs = list(Path("data/fandom_stills").rglob("*.[jp][pn]g"))

    if sample_imgs and has_gemini:
        print(f"\n  {INFO} Describing {sample_imgs[0].name} with Gemini Vision...")
        desc = describe_image_gemini(str(sample_imgs[0]))
        if desc and len(desc) > 20:
            ok("gemini_vision", f"{desc[:80]}...")
        else:
            fail("gemini_vision", f"got: {desc[:50]}")
    elif not has_gemini:
        skip("gemini_vision", "no API key")
    else:
        skip("gemini_vision", "no sample images")

    # Matching (no API calls)
    images = [
        {"path": "fake/betrayal.png", "description": "Griffith stands before the God Hand", "index": 0},
        {"path": "fake/friends.png", "description": "Band of the Hawk laughs together", "index": 1},
    ]
    segs = [
        {"text": "They were a family once"},
        {"text": "Griffith chose power over friendship"},
    ]
    matched = match_panels_to_segments(images, segs, use_llm=False)
    if all(s.get("matched_image") for s in matched):
        ok("matching_logic", "keyword fallback matches all segments")
    else:
        fail("matching_logic", "some segments unmatched")

except Exception as e:
    fail("panel_matcher", str(e)[:200])


# ══════════════════════════════════════════════════════════════════
# 10. SUMMARY
# ══════════════════════════════════════════════════════════════════

section("SUMMARY")

total = len(results)
passed = sum(1 for v in results.values() if v is True)
failed = sum(1 for v in results.values() if v is False)
skipped = sum(1 for v in results.values() if v is None)

print(f"\n  {OK} Passed:  {passed}/{total}")
print(f"  {FAIL} Failed:  {failed}/{total}")
print(f"  {SKIP} Skipped: {skipped}/{total}")

if failed:
    print("\n  Failed sections:")
    for k, v in results.items():
        if v is False:
            print(f"    - {k}")

sys.exit(0 if failed == 0 else 1)
