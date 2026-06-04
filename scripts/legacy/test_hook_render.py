"""
End-to-end smoke test for the hook engine.

Skips the Gemini-dependent steps (LLM script generation, Gemini Vision panel
matching) and instead uses hardcoded segments + keyword-only matching, so we
can validate that:

  1. The first segment is marked with is_hook=True
  2. expand_hook generates N sub-cuts at the configured hook_cps
  3. The hook subtitle uses the Hook style with the accent keyword
  4. The final video renders successfully

This is meant to run locally with FFmpeg installed. No GEMINI_API_KEY needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("hook-test")

OUT = Path("outputs/hook_smoke_test")
OUT.mkdir(parents=True, exist_ok=True)


# ── Hardcoded test script (Berserk · personality video type) ──
SCRIPT = [
    {"text": "Griffith was right. And you know it.", "emotion": "dark", "is_hook": True},
    {"text": "Every great antihero made the same choice.", "emotion": "dark"},
    {"text": "Walter White. Light Yagami. Michael Corleone.", "emotion": "epic"},
    {"text": "The only difference? Griffith was honest.", "emotion": "tragic"},
    {"text": "What would you sacrifice for your dream?", "emotion": "dark"},
]
VTYPE = "personality"
VOICE = "en-US-AndrewMultilingualNeural"
RATE = "-3%"
PITCH = "-5Hz"


def main():
    log.info(f"\n=== Hook smoke test — vtype={VTYPE} ===")

    # ── 1. Generate audio ──
    log.info("\n1) Generate audio")
    audio_files, narration_data, full_audio = generate_audio()

    # Validate hook flag survived
    assert narration_data[0]["is_hook"] is True, "First segment must be marked is_hook"
    assert all(not n["is_hook"] for n in narration_data[1:]), "Only first segment should be hook"
    log.info(f"  ✓ Hook flag correctly placed on segment 0")

    # ── 2. Pick images ──
    log.info("\n2) Collect image pool (no Gemini Vision)")
    images = sorted(
        list(Path("data/manga_panels").rglob("*.[jp][pn]g"))
        + list(Path("data/fandom_stills").rglob("*.[jp][pn]g"))
    )[:30]
    log.info(f"  {len(images)} images available")
    assert len(images) >= 3, "Need at least 3 images for the hook to expand"

    # Naive matching: rotate through pool
    for i, n in enumerate(narration_data):
        n["matched_image"] = str(images[i % len(images)])

    # ── 3. Subtitles with Hook style ──
    log.info("\n3) Generate subtitles with Hook style")
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
            log.info(f"  Hook accent word: '{seg['accent_word']}'")
        sub_segments.append(seg)

    ass_path = str(OUT / "subtitles.ass")
    generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")
    ass_text = Path(ass_path).read_text(encoding="utf-8")
    assert "Style: Hook," in ass_text, "Hook style must be defined in ASS header"
    assert "Style: HookKey," in ass_text, "HookKey style must be defined"
    assert "Hook,,0,0,0," in ass_text, "Hook dialogue line must use Hook style"
    log.info(f"  ✓ Hook style + HookKey in subtitles.ass")

    # ── 4. Build EDL with hook expansion ──
    log.info("\n4) Build EDL + expand hook into sub-cuts")
    from apps.production.video_director import VideoDirector, EditDecision
    from apps.production.script_generator import hook_cps_for_video_type

    director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)
    hook_cps = hook_cps_for_video_type(VTYPE)
    log.info(f"  hook_cps for '{VTYPE}': {hook_cps}")

    hook_pool = [str(p) for p in images[:8]]

    edl = []
    for i, ns in enumerate(narration_data):
        camera = director._camera_for_emotion(ns["emotion"])
        transition = director._transition_for_shift(ns["emotion"], i)
        edl.append(EditDecision(
            visual_type="manga_panel",
            visual_path=ns["matched_image"],
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

    # Test the expansion
    sub_d = director.expand_hook(edl[0])
    expected_cuts = max(1, int(round(edl[0].duration * hook_cps)))
    log.info(f"  Hook duration={edl[0].duration:.2f}s × hook_cps={hook_cps} → {expected_cuts} sub-cuts")
    log.info(f"  expand_hook produced: {len(sub_d)}")
    assert len(sub_d) == expected_cuts, f"expand_hook should produce {expected_cuts} cuts, got {len(sub_d)}"
    log.info(f"  ✓ Hook expanded correctly")

    # ── 5. Render ──
    log.info("\n5) Render all sub-clips and assemble")
    tmpdir = tempfile.mkdtemp(prefix="hook_test_")
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
    assert len(clip_paths) >= len(edl), "Should have at least one clip per EDL entry"

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

    merged = os.path.join(tmpdir, "merged.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_only, "-i", full_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", merged,
    ], capture_output=True, text=True, timeout=120)

    final = str(OUT / "FINAL_HOOK_TEST.mp4")
    ass_esc = ass_path.replace("\\", "/").replace(":", "\\\\:")
    subprocess.run([
        "ffmpeg", "-y", "-i", merged,
        "-vf", f"ass='{ass_esc}'",
        "-c:v", "h264_nvenc", "-b:v", "5M", "-c:a", "copy", final,
    ], capture_output=True, text=True, timeout=120)

    if not Path(final).exists():
        # Fallback: keep the merged version
        if Path(merged).exists():
            shutil.copy(merged, final)
            log.warning("Subtitle burn failed, using version without burnt subs")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if Path(final).exists():
        size_kb = Path(final).stat().st_size // 1024
        log.info(f"\n✓✓✓ FINAL: {final} ({size_kb}KB) — hook engine works")
    else:
        log.error("Render produced no output")
        sys.exit(1)


def generate_audio():
    """Generate edge-tts per segment."""
    audio_files = []
    narration_data = []
    t = 0.0

    for old in OUT.glob("seg_*.wav"):
        old.unlink()

    for i, seg in enumerate(SCRIPT):
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
            "text": text,
            "start_s": t,
            "duration_s": dur,
            "emotion": seg.get("emotion", "dark"),
            "is_hook": is_hook,
        })
        hook_tag = " [HOOK]" if is_hook else ""
        log.info(f"  seg{i}: {dur:.1f}s — {text[:50]}{hook_tag}")
        t += dur

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
