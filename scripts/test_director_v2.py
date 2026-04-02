"""Test VideoDirector v2 with Berserk Golden Age — full production pipeline."""
import sys
import os
import json
import sqlite3
import shutil
import subprocess
import logging
import requests
from pathlib import Path
import asyncio
import edge_tts

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

DB_PATH = "data/shorts_pipeline.db"
OUTPUT_DIR = Path("outputs/manga/director_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Step 1: Get narration script from Gemini via persona system ──
log.info("=== Step 1: Generate narration script ===")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

from common.personas import get_persona, build_narration_prompt

persona = get_persona(conn, "deep_mind")

# Get top cross-refs for Berserk
cross_refs = conn.execute("""
    SELECT description_deep_mind FROM cross_references
    WHERE source_work = 'Berserk' AND description_deep_mind IS NOT NULL
    ORDER BY strength DESC LIMIT 2
""").fetchall()
ref_texts = [r[0] for r in cross_refs]

# Build the full prompt
from common.video_director import get_director_prompt_addon

context = {
    "series_title": "Berserk",
    "arc_name": "Golden Age — The Eclipse",
    "creator": "Kentaro Miura",
    "summary": (
        "Griffith, broken and tortured after a year in prison, activates the Crimson Behelit. "
        "The God Hand appears and offers him a choice: sacrifice the Band of the Hawk to become "
        "the fifth God Hand member, Femto. Griffith accepts. The Eclipse begins — a nightmarish "
        "dimension where apostles devour the Band of the Hawk. Guts fights desperately but loses "
        "his arm and eye. Casca is violated by Femto. The Skull Knight intervenes to save Guts and Casca, "
        "but both are branded with the Mark of Sacrifice."
    ),
    "cross_refs": ref_texts,
}

prompt = build_narration_prompt(persona, context)
prompt += "\n\n" + get_director_prompt_addon()

# Call Gemini
gemini_key = os.getenv("GEMINI_API_KEY", "")
resp = requests.post(
    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
    json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5},
    },
    timeout=30,
)

import re
text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
text = re.sub(r"```json?\s*", "", text).strip().rstrip("`")
script = json.loads(text)

log.info(f"Script: {script.get('title', '?')}")
log.info(f"  Intro: {script.get('intro', '')[:60]}...")
log.info(f"  Segments: {len(script.get('segments', []))}")
log.info(f"  Outro: {script.get('outro', '')[:60]}...")

with open(str(OUTPUT_DIR / "script.json"), "w") as f:
    json.dump(script, f, indent=2)

# ── Step 2: Download manga pages from MangaDex ──
log.info("=== Step 2: Download manga pages ===")

from common.mangadex import search_manga, get_chapters, download_chapter_pages

manga_result = search_manga("Berserk")
if manga_result:
    manga_uuid = manga_result["id"]
    log.info(f"MangaDex: {manga_result.get('title', '?')} ({manga_uuid})")
    chapters = get_chapters(manga_uuid, limit=5, offset=80)  # Eclipse chapters (~83-88)
    pages = []
    for ch in chapters[:3]:
        ch_pages = download_chapter_pages(ch["id"], output_dir=str(OUTPUT_DIR / "pages"), max_pages=4)
        pages.extend(ch_pages)
    log.info(f"Downloaded {len(pages)} pages")

# Fallback: use existing pages if MangaDex failed or returned nothing
if not manga_result or not pages:
    for fallback_dir in ["data/manga_panels/berserk_eclipse_ch83", "data/manga_panels/berserk_ch382",
                         "data/manga_panels/berserk_golden_age", "data/manga_panels/berserk"]:
        d = Path(fallback_dir)
        if d.exists():
            pages = sorted(str(p) for p in d.glob("*.jpg"))[:12]
            if not pages:
                pages = sorted(str(p) for p in d.glob("*.png"))[:12]
            if pages:
                log.info(f"Fallback: {len(pages)} pages from {fallback_dir}")
                break
    if not pages:
        pages = sorted(str(p) for p in Path("data/manga_panels").rglob("*.[jp][pn]g"))[:12]
        log.info(f"Fallback (global): {len(pages)} pages")

if not pages:
    log.error("No pages available!")
    sys.exit(1)

# ── Step 3: Generate audio with edge-tts (consistent voice) ──
log.info("=== Step 3: Generate audio (edge-tts) ===")

# Clean old audio files to prevent stale data
for old in OUTPUT_DIR.glob("audio_*.wav"):
    old.unlink()
for old in OUTPUT_DIR.glob("audio_*.mp3"):
    old.unlink()
old_full = OUTPUT_DIR / "full_audio.wav"
if old_full.exists():
    old_full.unlink()
log.info("Cleaned old audio files")

VOICE = "en-US-AndrewMultilingualNeural"  # Warm, confident, authentic
RATE = "-5%"   # Slightly slower for gravitas
PITCH = "-8Hz"  # Deeper tone for narrator feel

all_texts = []
if script.get("intro"):
    all_texts.append(("intro", script["intro"]))
for i, seg in enumerate(script.get("segments", [])):
    if seg.get("text"):
        all_texts.append((f"seg{i}", seg["text"]))
if script.get("outro"):
    all_texts.append(("outro", script["outro"]))

audio_files = []
narration_segments = []
t = 0.0

async def generate_tts(text, output_path, rate=RATE, pitch=PITCH):
    """Generate audio with edge-tts and convert to WAV."""
    mp3_path = output_path.replace(".wav", ".mp3")
    communicate = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch)
    await communicate.save(mp3_path)
    # Convert to WAV for pipeline compatibility
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "1",
         "-c:a", "pcm_s16le", output_path],
        capture_output=True, timeout=15,
    )
    os.unlink(mp3_path)

log.info(f"Voice: {VOICE} | Rate: {RATE} | Pitch: {PITCH}")

for label, text in all_texts:
    dst = str(OUTPUT_DIR / f"audio_{label}.wav")
    try:
        asyncio.run(generate_tts(text, dst))

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", dst],
            capture_output=True, text=True,
        )
        dur = float(probe.stdout.strip()) if probe.stdout.strip() else 3.0
        audio_files.append(dst)

        # Find matching segment emotion
        emotion = "default"
        for seg in script.get("segments", []):
            if seg.get("text") == text:
                emotion = seg.get("emotion", "default")
                break

        narration_segments.append({
            "text": text,
            "start_s": t,
            "duration_s": dur,
            "emotion": emotion,
            "audio_file": dst,
        })
        t += dur
        log.info(f"  {label}: {dur:.1f}s")
    except Exception as e:
        log.warning(f"  {label} failed: {e}")

# Concat all audio
full_audio = str(OUTPUT_DIR / "full_audio.wav")
concat_list = str(OUTPUT_DIR / "audio_concat.txt")
with open(concat_list, "w") as f:
    for af in audio_files:
        # Use absolute paths to avoid ffmpeg path resolution issues
        abs_path = os.path.abspath(af)
        f.write(f"file '{abs_path}'\n")

concat_result = subprocess.run(
    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
     "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", full_audio],
    capture_output=True, text=True, timeout=30,
)
if concat_result.returncode != 0:
    log.error(f"Audio concat FAILED: {concat_result.stderr[:300]}")
    sys.exit(1)
if not Path(full_audio).exists():
    log.error("full_audio.wav not created!")
    sys.exit(1)
log.info(f"Total audio: {t:.1f}s (full_audio.wav: {Path(full_audio).stat().st_size // 1024}KB)")

# ── Step 4: Generate subtitles ──
log.info("=== Step 4: Generate subtitles ===")

from common.animated_subs import generate_ass_subtitles

sub_segments = [{
    "text": ns["text"],
    "start_s": ns["start_s"],
    "end_s": ns["start_s"] + ns["duration_s"],
    "emotion": ns.get("emotion", "default"),
} for ns in narration_segments]

ass_path = str(OUTPUT_DIR / "subtitles.ass")
generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")
log.info(f"Subtitles: {ass_path}")

# ── Step 5: Render with Director v2 ──
log.info("=== Step 5: Render with Director v2 ===")

from common.video_director import VideoDirector

director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)

# Build EDL manually from our data
from common.video_director import EditDecision

edl = []
pages_per_seg = max(1, len(pages) // max(len(narration_segments), 1))

for i, ns in enumerate(narration_segments):
    page_idx = min(i * pages_per_seg, len(pages) - 1)
    page = pages[page_idx]
    emotion = ns.get("emotion", "default")

    camera = director._camera_for_emotion(emotion)
    transition = director._transition_for_shift(emotion, i)

    edl.append(EditDecision(
        visual_type="manga_panel",
        visual_path=page,
        duration=ns["duration_s"],
        narration_text=ns["text"],
        narration_audio=ns.get("audio_file", ""),
        emotion=emotion,
        camera=camera,
        transition_in=transition,
        j_cut_s=0.3 if i > 0 else 0,
    ))

# Render each segment
import tempfile
tmpdir = tempfile.mkdtemp(prefix="director_test_")
clip_paths = []

for i, decision in enumerate(edl):
    clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
    director._render_panel_segment(decision, clip_path)
    if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
        clip_paths.append(clip_path)
        log.info(f"  Clip {i}: {Path(clip_path).stat().st_size // 1024}KB | {decision.emotion} | {decision.transition_in}")

# Concatenate
video_only = os.path.join(tmpdir, "assembled.mp4")
concat_file = os.path.join(tmpdir, "concat.txt")
with open(concat_file, "w") as f:
    for c in clip_paths:
        f.write(f"file '{c}'\n")
subprocess.run(
    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", video_only],
    capture_output=True, timeout=60,
)

# Merge video + audio (without subtitles first, then burn subs)
merged_no_subs = os.path.join(tmpdir, "merged.mp4")
r1 = subprocess.run([
    "ffmpeg", "-y",
    "-i", video_only, "-i", full_audio,
    "-map", "0:v", "-map", "1:a",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
    "-shortest",
    merged_no_subs,
], capture_output=True, text=True, timeout=120)

if not Path(merged_no_subs).exists():
    log.error(f"Audio merge failed: {r1.stderr[:300]}")
    # Fallback: use video only
    merged_no_subs = video_only

# Burn subtitles
final_output = str(OUTPUT_DIR / "DIRECTOR_TEST.mp4")
ass_escaped = ass_path.replace("\\", "/").replace(":", "\\\\:")
r2 = subprocess.run([
    "ffmpeg", "-y",
    "-i", merged_no_subs,
    "-vf", f"ass='{ass_escaped}'",
    "-c:v", "h264_nvenc", "-b:v", "5M",
    "-c:a", "copy",
    final_output,
], capture_output=True, text=True, timeout=120)

if not Path(final_output).exists():
    log.warning(f"Subtitle burn failed: {r2.stderr[:200]}")
    # Fallback: use merged without subs
    shutil.copy(merged_no_subs, final_output)
    log.info("Using version without subtitles")

# Cleanup
shutil.rmtree(tmpdir, ignore_errors=True)

if Path(final_output).exists():
    size = Path(final_output).stat().st_size // 1024
    log.info(f"\n=== DONE: {final_output} ({size}KB) ===")
    log.info(f"Script: {script.get('title', '?')}")
    log.info(f"Segments: {len(narration_segments)}")
    log.info(f"Duration: {t:.1f}s")
    log.info(f"Pages used: {len(pages)}")
else:
    log.error("Final render failed!")
