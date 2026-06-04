"""
End-to-end smoke test of the FULL pipeline with NO LLM dependency.

  - Algorithmic script generator (templates + DB context)
  - edge-tts for audio (no LLM)
  - Panel matcher with use_gemini=False (keyword fallback)
  - VideoDirector with hook expansion

Goal: a real .mp4 produced without any external LLM call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import edge_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("no-llm-pipeline")

OUT = Path("outputs/pipeline_no_llm_test")
OUT.mkdir(parents=True, exist_ok=True)

VOICE = "en-US-AndrewMultilingualNeural"
RATE = "-3%"
PITCH = "-5Hz"
VTYPE = "personality"      # which video type to render
SERIES_SLUG = "berserk"
SERIES_TITLE = "Berserk: The Golden Age Arc"
PERSONA = "deep_mind"


def main():
    log.info(f"\n=== NO-LLM PIPELINE TEST — {SERIES_TITLE} / {VTYPE} ===")

    # ── 1. Algorithmic script generation ──
    log.info("\n1) Algorithmic script generation (no LLM)")
    from apps.production.script_generator import generate_scripts_for_series

    conn = sqlite3.connect("data/shorts_pipeline.db")
    scripts = generate_scripts_for_series(
        conn=conn, series_slug=SERIES_SLUG, series_title=SERIES_TITLE,
        persona=PERSONA, use_llm=False,
    )
    conn.close()

    if VTYPE not in scripts:
        log.error(f"No script generated for {VTYPE}")
        sys.exit(1)

    segments = scripts[VTYPE]
    log.info(f"  Got {len(segments)} segments for {VTYPE}:")
    for i, s in enumerate(segments):
        flag = " [HOOK]" if s.get("is_hook") else ""
        log.info(f"    {i}. ({s['emotion']}){flag} {s['text']}")

    assert segments[0].get("is_hook") is True, "First segment must be the hook"

    # ── 2. Generate audio (edge-tts) ──
    log.info("\n2) Generate audio (edge-tts, no LLM)")
    audio_files, narration_data, full_audio = generate_audio(segments)

    # ── 3. Collect images (manga + fandom — no Gemini fetching) ──
    log.info("\n3) Collect image pool")
    images = sorted(
        list(Path("data/manga_panels").rglob("*.[jp][pn]g"))
        + list(Path("data/fandom_stills").rglob("*.[jp][pn]g"))
    )[:25]
    images = [str(p) for p in images]
    log.info(f"  {len(images)} images available")
    assert len(images) >= 3, "Need at least 3 images"

    # ── 4. Panel matching with use_gemini=False (keyword fallback) ──
    log.info("\n4) Panel matching (use_gemini=False — keyword fallback)")
    from apps.production.panel_matcher import select_panels_for_narration
    matched = select_panels_for_narration(images, narration_data, use_gemini=False)
    for i, ns in enumerate(matched):
        img = Path(ns.get("matched_image", "?")).name
        reason = ns.get("match_reason", "")
        log.info(f"  seg{i}: {img} ({reason})")

    # ── 5. Subtitles with Hook style ──
    log.info("\n5) Subtitles with Hook style")
    from apps.production.animated_subs import generate_ass_subtitles
    from apps.production.script_generator import detect_hook_accent_word

    sub_segments = []
    for ns in narration_data:
        seg = {
            "text": ns["text"],
            "start_s": ns["start_s"],
            "end_s": ns["start_s"] + ns["duration_s"],
            "emotion": ns["emotion"],
            "is_hook": ns["is_hook"],
        }
        if ns["is_hook"]:
            seg["accent_word"] = detect_hook_accent_word(ns["text"], VTYPE) or ""
        sub_segments.append(seg)
    ass_path = str(OUT / "subtitles.ass")
    generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")

    # ── 6. Render with hook expansion ──
    log.info("\n6) Render videos with hook expansion")
    from apps.production.video_director import VideoDirector, EditDecision
    from apps.production.script_generator import hook_cps_for_video_type

    director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)
    hook_cps = hook_cps_for_video_type(VTYPE)
    log.info(f"  hook_cps for '{VTYPE}': {hook_cps}")

    hook_pool = images[:8]
    edl = []
    for i, ns in enumerate(matched):
        image = ns.get("matched_image", images[i % len(images)])
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
            is_hook=ns["is_hook"],
            hook_cps=hook_cps if ns["is_hook"] else 0.5,
            hook_image_pool=hook_pool if ns["is_hook"] else [],
        ))

    tmpdir = tempfile.mkdtemp(prefix="no_llm_")
    clip_paths = []
    for i, d in enumerate(edl):
        sub_decisions = director.expand_hook(d) if d.is_hook else [d]
        if d.is_hook and len(sub_decisions) > 1:
            log.info(f"  HOOK seg{i}: rendering {len(sub_decisions)} sub-cuts")
        for j, sd in enumerate(sub_decisions):
            clip = os.path.join(tmpdir, f"seg_{i:03d}_{j:02d}.mp4")
            director._render_panel_segment(sd, clip)
            if Path(clip).exists() and Path(clip).stat().st_size > 0:
                clip_paths.append(clip)

    log.info(f"  Rendered {len(clip_paths)} clips")

    # Concat
    video_only = os.path.join(tmpdir, "assembled.mp4")
    cf = os.path.join(tmpdir, "concat.txt")
    with open(cf, "w") as f:
        for c in clip_paths:
            f.write(f"file '{c}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cf, "-c", "copy", video_only],
        capture_output=True, timeout=60,
    )

    # Merge audio
    merged = os.path.join(tmpdir, "merged.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_only, "-i", full_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", merged,
    ], capture_output=True, text=True, timeout=120)

    # Burn subtitles
    final = str(OUT / f"FINAL_NO_LLM_{VTYPE.upper()}.mp4")
    ass_esc = ass_path.replace("\\", "/").replace(":", "\\\\:")
    subprocess.run([
        "ffmpeg", "-y", "-i", merged,
        "-vf", f"ass='{ass_esc}'",
        "-c:v", "h264_nvenc", "-b:v", "5M", "-c:a", "copy", final,
    ], capture_output=True, text=True, timeout=120)

    if not Path(final).exists():
        if Path(merged).exists():
            shutil.copy(merged, final)
            log.warning("Subtitle burn failed, using version without burnt subs")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if Path(final).exists():
        size_kb = Path(final).stat().st_size // 1024
        log.info(f"\n✓✓✓ FINAL: {final} ({size_kb}KB)")
        log.info("    No LLM was called during this entire pipeline.")
    else:
        log.error("Render produced no output")
        sys.exit(1)


def generate_audio(segments):
    """edge-tts per segment, then concat."""
    audio_files = []
    narration_data = []
    t = 0.0

    for old in OUT.glob("seg_*.wav"):
        old.unlink()

    for i, seg in enumerate(segments):
        text = seg["text"]
        wav = str(OUT / f"seg_{i:02d}.wav")
        mp3 = str(OUT / f"seg_{i:02d}.mp3")

        async def gen(t=text, mp3=mp3):
            c = edge_tts.Communicate(t, VOICE, rate=RATE, pitch=PITCH)
            await c.save(mp3)
        asyncio.run(gen())

        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "1",
             "-c:a", "pcm_s16le", wav],
            capture_output=True, timeout=15,
        )
        Path(mp3).unlink(missing_ok=True)

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", wav],
            capture_output=True, text=True,
        )
        dur = float(probe.stdout.strip()) if probe.stdout.strip() else 3.0

        is_hook = bool(seg.get("is_hook", False))
        audio_files.append(wav)
        narration_data.append({
            "text": text, "start_s": t, "duration_s": dur,
            "emotion": seg.get("emotion", "dark"),
            "is_hook": is_hook,
        })
        t += dur
        flag = " [HOOK]" if is_hook else ""
        log.info(f"  seg{i}: {dur:.1f}s {flag} {text[:50]}")

    full = str(OUT / "full_audio.wav")
    cf = str(OUT / "concat.txt")
    with open(cf, "w") as f:
        for af in audio_files:
            f.write(f"file '{os.path.abspath(af)}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cf,
         "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", full],
        capture_output=True, text=True, timeout=30,
    )
    return audio_files, narration_data, full


if __name__ == "__main__":
    main()
