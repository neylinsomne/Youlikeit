"""
Produce 3 videos for ANY series (not just Berserk).

Examples:
    python scripts/produce_for_series.py --series "Vinland Saga" --tmdb-id 64196
    python scripts/produce_for_series.py --series "Attack on Titan" --tmdb-id 1429
    python scripts/produce_for_series.py --series "Jujutsu Kaisen" --tmdb-id 95479
    python scripts/produce_for_series.py --series "Chainsaw Man" --tmdb-id 114410
    python scripts/produce_for_series.py --series "Frieren" --tmdb-id 209867

Flow:
1. Ensure the series is classified (themes + arcs + moments)
2. LLM generates 3 scripts (narration, personality, test) for this series
3. edge-tts synthesizes audio per segment
4. Collect visuals: base manga pages + thematic stills + cross-ref images
5. Panel matcher picks the best image per segment with Gemini Vision
6. Render 3 videos

Run with --dry-run to only generate scripts without rendering.
"""
import sys, os, json, shutil, subprocess, asyncio, logging, argparse, sqlite3, re
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug[:50] or "series"


def generate_audio(segments, out_dir, voice, rate, pitch):
    """Synthesize edge-tts per segment, concatenate to full_audio.wav."""
    import edge_tts
    audio_files = []
    narration_data = []
    t = 0.0

    for old in out_dir.glob("seg_*.wav"):
        old.unlink()

    for i, seg in enumerate(segments):
        text = seg["text"]
        wav_path = str(out_dir / f"seg_{i:02d}.wav")
        mp3_path = str(out_dir / f"seg_{i:02d}.mp3")

        async def gen(t=text, mp3=mp3_path):
            c = edge_tts.Communicate(t, voice, rate=rate, pitch=pitch)
            await c.save(mp3)
        asyncio.run(gen())

        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "1",
             "-c:a", "pcm_s16le", wav_path],
            capture_output=True, timeout=15,
        )
        Path(mp3_path).unlink(missing_ok=True)

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", wav_path],
            capture_output=True, text=True,
        )
        dur = float(probe.stdout.strip()) if probe.stdout.strip() else 3.0
        audio_files.append(wav_path)
        narration_data.append({
            "text": text,
            "start_s": t,
            "duration_s": dur,
            "emotion": seg.get("emotion", "dark"),
            "is_hook": bool(seg.get("is_hook", False)),
        })
        t += dur
        hook_tag = " [HOOK]" if seg.get("is_hook") else ""
        log.info(f"    seg{i}: {dur:.1f}s — {text[:50]}{hook_tag}")

    full_audio = str(out_dir / "full_audio.wav")
    concat_list = str(out_dir / "concat.txt")
    with open(concat_list, "w") as f:
        for af in audio_files:
            f.write(f"file '{os.path.abspath(af)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", full_audio],
        capture_output=True, text=True, timeout=30,
    )
    return audio_files, narration_data, full_audio


def collect_image_pool(
    narration_data,
    series_slug,
    manga_dirs,
    include_experimental=False,
):
    """Combine: manga pages + thematic stills + cross-ref images + fandom."""
    from common.thematic_stills import get_thematic_stills_for_narration
    from common.cross_ref_images import enrich_segments_with_cross_refs

    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row

    images = []

    # 1. Base manga pages
    for d in manga_dirs:
        if Path(d).exists():
            images += sorted(str(p) for p in Path(d).glob("*.[jp][pn]g"))

    # 2. Thematic stills (Fandom-first, TMDb fallback)
    thematic = get_thematic_stills_for_narration(conn, narration_data, series_slug)
    images += thematic

    # 3. Cross-ref character images
    cross = enrich_segments_with_cross_refs(
        narration_data, include_experimental=include_experimental,
    )
    images += cross

    conn.close()
    return images, thematic, cross


def render_video(narration_data, audio_files, full_audio, image_paths, out_dir, vtype):
    """Render the final Short."""
    from common.animated_subs import generate_ass_subtitles
    from common.video_director import VideoDirector, EditDecision
    from common.panel_matcher import select_panels_for_narration
    from common.script_generator import (
        hook_cps_for_video_type, detect_hook_accent_word,
    )

    hook_cps = hook_cps_for_video_type(vtype)

    # Subtitles — propagate is_hook + accent_word for the Hook style
    sub_segments = []
    for ns in narration_data:
        is_hook = bool(ns.get("is_hook", False))
        seg = {
            "text": ns["text"],
            "start_s": ns["start_s"],
            "end_s": ns["start_s"] + ns["duration_s"],
            "emotion": ns["emotion"],
            "is_hook": is_hook,
        }
        if is_hook:
            seg["accent_word"] = detect_hook_accent_word(ns["text"], vtype) or ""
        sub_segments.append(seg)
    ass_path = str(out_dir / "subtitles.ass")
    generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")

    # Match images to segments via Gemini Vision
    log.info(f"    Matching {len(narration_data)} segments to {len(image_paths)} images...")
    matched = select_panels_for_narration(image_paths, narration_data, use_gemini=True)

    # Save matching report
    report = [{
        "text": seg["text"][:60],
        "image": Path(seg.get("matched_image", "?")).name,
        "reason": seg.get("match_reason", ""),
        "is_hook": bool(seg.get("is_hook", False)),
    } for seg in matched]
    (out_dir / "panel_matches.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Render
    director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix=f"produce_{vtype}_")

    # Build a hook image pool — distinct images that share theme/emotion
    # so the hook can rotate between them without semantic drift
    hook_pool = [p for p in image_paths if p][:8]

    edl = []
    for i, ns in enumerate(matched):
        image = ns.get("matched_image", image_paths[i % len(image_paths)])
        camera = director._camera_for_emotion(ns["emotion"])
        transition = director._transition_for_shift(ns["emotion"], i)
        is_hook = bool(ns.get("is_hook", False))
        edl.append(EditDecision(
            visual_type="manga_panel",
            visual_path=image,
            duration=ns["duration_s"],
            narration_text=ns["text"],
            narration_audio=audio_files[i],
            emotion=ns["emotion"],
            camera=camera,
            transition_in=transition,
            j_cut_s=0.3 if i > 0 else 0,
            is_hook=is_hook,
            hook_cps=hook_cps if is_hook else 0.5,
            hook_image_pool=hook_pool if is_hook else [],
        ))

    clip_paths = []
    for i, d in enumerate(edl):
        # Expand the hook into N visual sub-cuts (no-op if not a hook
        # or if hook_cps is too low to benefit)
        sub_decisions = director.expand_hook(d) if d.is_hook else [d]
        if d.is_hook and len(sub_decisions) > 1:
            log.info(
                f"    HOOK seg{i}: expanded into {len(sub_decisions)} sub-cuts "
                f"(hook_cps={d.hook_cps}, duration={d.duration:.1f}s)"
            )

        for j, sd in enumerate(sub_decisions):
            clip = os.path.join(tmpdir, f"seg_{i:03d}_{j:02d}.mp4")
            director._render_panel_segment(sd, clip)
            if Path(clip).exists() and Path(clip).stat().st_size > 0:
                clip_paths.append(clip)

    video_only = os.path.join(tmpdir, "assembled.mp4")
    cf = os.path.join(tmpdir, "concat.txt")
    with open(cf, "w") as f:
        for c in clip_paths:
            f.write(f"file '{c}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cf,
         "-c", "copy", video_only],
        capture_output=True, timeout=60,
    )

    merged = os.path.join(tmpdir, "merged.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_only, "-i", full_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", merged,
    ], capture_output=True, text=True, timeout=120)

    final = str(out_dir / f"FINAL_{vtype.upper()}.mp4")
    ass_esc = ass_path.replace("\\", "/").replace(":", "\\\\:")
    subprocess.run([
        "ffmpeg", "-y", "-i", merged,
        "-vf", f"ass='{ass_esc}'",
        "-c:v", "h264_nvenc", "-b:v", "5M", "-c:a", "copy", final,
    ], capture_output=True, text=True, timeout=120)

    if not Path(final).exists():
        fallback = merged if Path(merged).exists() else video_only
        if Path(fallback).exists():
            shutil.copy(fallback, final)

    shutil.rmtree(tmpdir, ignore_errors=True)
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", required=True, help='Series title (e.g., "Vinland Saga")')
    ap.add_argument("--tmdb-id", type=int, default=0, help="TMDb TV ID (auto-search if 0)")
    ap.add_argument("--slug", default="", help="Custom slug (default: slugified title)")
    ap.add_argument("--persona", default="deep_mind", choices=["deep_mind", "pop_oracle", "latam"])
    ap.add_argument("--voice", default="en-US-AndrewMultilingualNeural")
    ap.add_argument("--types", nargs="+", default=["narration", "personality", "test"],
                    choices=["narration", "personality", "test"])
    ap.add_argument("--manga-dirs", nargs="+", default=[])
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate scripts only, no audio/video")
    args = ap.parse_args()

    slug = args.slug or _slugify(args.series)

    # Step 1: Ensure classified
    log.info(f"\n=== Series: {args.series} (slug={slug}) ===")

    from common.thematic_stills import ensure_series_classified
    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row
    ensure_series_classified(conn, args.series, tmdb_id=args.tmdb_id, slug=slug)

    # Step 2: Generate scripts
    log.info("\n=== Generating scripts via LLM ===")
    from common.script_generator import generate_scripts_for_series, voice_params_for_video_type

    scripts = generate_scripts_for_series(
        conn, slug, args.series, persona=args.persona,
    )
    conn.close()

    if not scripts:
        log.error("No scripts generated. Check GEMINI_API_KEY and series classification.")
        return

    # Save scripts
    out_base = Path(f"outputs/produce/{slug}")
    out_base.mkdir(parents=True, exist_ok=True)
    (out_base / "scripts.json").write_text(
        json.dumps(scripts, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n=== GENERATED SCRIPTS ===")
    for vtype, segs in scripts.items():
        print(f"\n── {vtype.upper()} ({len(segs)} segments) ──")
        for i, s in enumerate(segs):
            print(f"  {i+1}. [{s.get('emotion', ''):8s}] {s.get('text', '')}")

    if args.dry_run:
        log.info("\n=== DRY RUN — stopping here. Scripts saved to outputs/produce/ ===")
        return

    # Step 3: Render each video
    log.info("\n=== Rendering videos ===")

    # Auto-detect manga dirs for this series
    manga_dirs = args.manga_dirs or []
    if not manga_dirs:
        # Try common patterns
        candidates = [
            f"data/manga_panels/{slug}",
            f"data/manga_panels/{slug.replace('_', '')}",
            f"data/fandom_stills/{slug}",
            f"data/thematic_stills/{slug}",
        ]
        manga_dirs = [c for c in candidates if Path(c).exists()]
        log.info(f"Auto-detected manga dirs: {manga_dirs}")

    for vtype in args.types:
        if vtype not in scripts:
            log.warning(f"Skipping {vtype} — no script generated")
            continue

        log.info(f"\n── Rendering {vtype.upper()} ──")
        out_dir = out_base / vtype
        out_dir.mkdir(exist_ok=True)

        # Audio
        voice_params = voice_params_for_video_type(vtype)
        audio_files, narration_data, full_audio = generate_audio(
            scripts[vtype], out_dir, args.voice,
            voice_params["rate"], voice_params["pitch"],
        )

        # Images
        include_exp = vtype == "test"
        images, thematic, cross = collect_image_pool(
            narration_data, slug, manga_dirs, include_experimental=include_exp,
        )
        log.info(
            f"  Image pool: {len(images)} total "
            f"(manga: {len(images) - len(thematic) - len(cross)}, "
            f"thematic: {len(thematic)}, cross-ref: {len(cross)})"
        )

        # Render
        final = render_video(narration_data, audio_files, full_audio, images, out_dir, vtype)
        size_kb = Path(final).stat().st_size // 1024 if Path(final).exists() else 0
        log.info(f"  ✓ {final} ({size_kb}KB)")

    print("\n=== DONE ===")
    for vtype in args.types:
        f = out_base / vtype / f"FINAL_{vtype.upper()}.mp4"
        if f.exists():
            print(f"  {vtype:12s}: {f} ({f.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
