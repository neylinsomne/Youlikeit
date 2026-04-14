"""Test content cycle v2: with Gemini Vision panel matching."""
import sys, os, json, shutil, subprocess, asyncio, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
import edge_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

OUTPUT_BASE = Path("outputs/content_cycle_v2")
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

VOICE = "en-US-AndrewMultilingualNeural"

IMAGE_DIRS = [
    "data/manga_panels/berserk_ch382",
    "data/manga_panels/berserk_eclipse_ch83",
]

VIDEOS = [
    {
        "type": "narration",
        "rate": "-5%", "pitch": "-8Hz",
        "segments": [
            {"text": "It was the night that changed everything.", "emotion": "dark"},
            {"text": "Griffith, broken and desperate, held the Crimson Behelit.", "emotion": "dark"},
            {"text": "And in that moment, he made a choice that would echo through eternity.", "emotion": "epic"},
            {"text": "The Band of the Hawk, his brothers, his family. All sacrificed.", "emotion": "tragic"},
            {"text": "Guts lost his arm. He lost his eye. He lost everything.", "emotion": "tragic"},
            {"text": "Maybe that is what makes him human. The refusal to stop.", "emotion": "hopeful"},
        ],
    },
    {
        "type": "personality",
        "rate": "-3%", "pitch": "-5Hz",
        "segments": [
            {"text": "Griffith was right. And deep down, you know it.", "emotion": "dark"},
            {"text": "Every great antihero has made the same choice for their vision.", "emotion": "dark"},
            {"text": "Walter White. Light Yagami. Michael Corleone. The same path.", "emotion": "epic"},
            {"text": "The only difference? Griffith was honest about the cost.", "emotion": "dark"},
            {"text": "Guts calls it betrayal. Miura calls it ambition.", "emotion": "tragic"},
            {"text": "What would you sacrifice for your dream?", "emotion": "dark"},
        ],
    },
    {
        "type": "test",
        "rate": "-8%", "pitch": "-10Hz",
        "segments": [
            {"text": "I have watched this scene a hundred times.", "emotion": "tragic"},
            {"text": "And every single time, it breaks me.", "emotion": "tragic"},
            {"text": "Casca. Guts. The Band of the Hawk.", "emotion": "dark"},
            {"text": "They were a family. They trusted each other.", "emotion": "hopeful"},
            {"text": "And one man destroyed all of it.", "emotion": "dark"},
            {"text": "If you have ever been betrayed by someone you loved, you understand.", "emotion": "tragic"},
        ],
    },
]


def generate_audio(segments, out_dir, rate, pitch):
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
            c = edge_tts.Communicate(t, VOICE, rate=rate, pitch=pitch)
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
            "text": text, "start_s": t, "duration_s": dur, "emotion": seg["emotion"],
        })
        t += dur
        log.info(f"  seg{i}: {dur:.1f}s")

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
    log.info(f"  Total: {t:.1f}s")
    return audio_files, narration_data, full_audio


def render_video(narration_data, audio_files, full_audio, out_dir, vtype):
    import sqlite3
    from common.animated_subs import generate_ass_subtitles
    from common.video_director import VideoDirector, EditDecision
    from common.panel_matcher import select_panels_for_narration
    from common.cross_ref_images import enrich_segments_with_cross_refs
    from common.thematic_stills import (
        ensure_series_classified,
        get_thematic_stills_for_narration,
    )

    sub_segments = [{
        "text": ns["text"], "start_s": ns["start_s"],
        "end_s": ns["start_s"] + ns["duration_s"], "emotion": ns["emotion"],
    } for ns in narration_data]
    ass_path = str(out_dir / "subtitles.ass")
    generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")

    image_paths = []
    for d in IMAGE_DIRS:
        image_paths += sorted(str(p) for p in Path(d).glob("*.[jp][pn]g"))

    # THEMATIC: detect themes in narration → query iconic moments → download stills
    # of specific episodes that match the themes. Most precise visual matching.
    log.info("  Fetching thematic stills by episode themes...")
    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row
    ensure_series_classified(
        conn, "Berserk: The Golden Age Arc", tmdb_id=211057, slug="berserk",
    )
    thematic_paths = get_thematic_stills_for_narration(conn, narration_data, "berserk")
    if thematic_paths:
        log.info(f"  Added {len(thematic_paths)} thematic stills (episode-specific)")
        image_paths += thematic_paths
    conn.close()

    # CROSS-REF: detect character mentions and fetch their images
    # Only TEST videos include the experimental pool (Marvel, DBZ, etc.)
    include_experimental = (vtype == "test")
    log.info(f"  Detecting cross-references (experimental={include_experimental})...")
    extra_images = enrich_segments_with_cross_refs(
        narration_data,
        include_experimental=include_experimental,
    )
    if extra_images:
        log.info(f"  Added {len(extra_images)} cross-ref images: {[Path(p).name for p in extra_images]}")
        image_paths += extra_images

    log.info(f"  Matching {len(narration_data)} segments to {len(image_paths)} panels (Gemini Vision)...")
    matched = select_panels_for_narration(image_paths, narration_data, use_gemini=True)

    report = []
    for seg in matched:
        report.append({
            "text": seg["text"][:60],
            "image": Path(seg.get("matched_image", "?")).name,
            "reason": seg.get("match_reason", ""),
        })
    (out_dir / "panel_matches.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix=f"v2_{vtype}_")

    edl = []
    for i, ns in enumerate(matched):
        image = ns.get("matched_image", image_paths[i % len(image_paths)])
        camera = director._camera_for_emotion(ns["emotion"])
        transition = director._transition_for_shift(ns["emotion"], i)
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
        ))

    clip_paths = []
    for i, decision in enumerate(edl):
        clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        director._render_panel_segment(decision, clip_path)
        if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
            clip_paths.append(clip_path)

    video_only = os.path.join(tmpdir, "assembled.mp4")
    cf = os.path.join(tmpdir, "vconcat.txt")
    with open(cf, "w") as f:
        for c in clip_paths:
            f.write(f"file '{c}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cf, "-c", "copy", video_only],
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


for video in VIDEOS:
    vtype = video["type"]
    log.info(f"\n{'='*50}")
    log.info(f"  {vtype.upper()}")
    log.info(f"{'='*50}")

    out_dir = OUTPUT_BASE / vtype
    out_dir.mkdir(exist_ok=True)

    audio_files, narration_data, full_audio = generate_audio(
        video["segments"], out_dir, video["rate"], video["pitch"],
    )
    final = render_video(narration_data, audio_files, full_audio, out_dir, vtype)
    size = Path(final).stat().st_size // 1024 if Path(final).exists() else 0
    log.info(f"  OUTPUT: {final} ({size}KB)")

log.info("\n=== DONE ===")
for vtype in ["narration", "personality", "test"]:
    f = OUTPUT_BASE / vtype / f"FINAL_{vtype.upper()}.mp4"
    if f.exists():
        log.info(f"  {vtype:12s}: {f.stat().st_size // 1024}KB")
