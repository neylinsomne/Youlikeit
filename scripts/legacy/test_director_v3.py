"""Director v3: Fixed voice consistency + subtitle timing."""
import sys
import os
import json
import sqlite3
import shutil
import subprocess
import logging
import requests
import re
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

DB_PATH = "data/shorts_pipeline.db"
OUTPUT_DIR = Path("outputs/manga/director_v3")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP = Path("C:/Users/Usuario/OneDrive/Escritorio/YouLikeIt_Tests")

# ── Step 1: Generate script with Gemini ──
log.info("=== Step 1: Script ===")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

from apps.content.personas import get_persona, build_narration_prompt
from apps.production.video_director import get_director_prompt_addon

persona = get_persona(conn, "deep_mind")
cross_refs = conn.execute("""
    SELECT description_deep_mind FROM cross_references
    WHERE source_work = 'Berserk' AND description_deep_mind IS NOT NULL
    ORDER BY strength DESC LIMIT 2
""").fetchall()

context = {
    "series_title": "Berserk",
    "arc_name": "Golden Age — The Eclipse",
    "creator": "Kentaro Miura",
    "summary": (
        "Griffith, broken after a year of torture, activates the Crimson Behelit. "
        "The God Hand offers him godhood in exchange for sacrificing the Band of the Hawk. "
        "Griffith accepts. Apostles devour his comrades. Guts loses his arm and eye fighting. "
        "Casca is violated by Femto. The Skull Knight saves Guts and Casca, both branded."
    ),
    "cross_refs": [r[0] for r in cross_refs],
}

prompt = build_narration_prompt(persona, context)
prompt += "\n\n" + get_director_prompt_addon()
prompt += "\n\nIMPORTANT: Generate exactly 4 segments (not more). Keep total narration under 45 seconds."

gemini_key = os.getenv("GEMINI_API_KEY", "")
resp = requests.post(
    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
    json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.5}},
    timeout=30,
)
text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
text = re.sub(r"```json?\s*", "", text).strip().rstrip("`")
script = json.loads(text)

log.info(f"Title: {script.get('title', '?')}")
log.info(f"Segments: {len(script.get('segments', []))}")

with open(str(OUTPUT_DIR / "script.json"), "w") as f:
    json.dump(script, f, indent=2)

# ── Step 2: Get manga pages ──
log.info("=== Step 2: Pages ===")

from integrations.mangadex import search_manga, get_chapters, download_chapter_pages

pages = []
manga_result = search_manga("Berserk")
if manga_result:
    # Get all EN chapters, filter to Eclipse arc (Ch 73-84)
    all_chapters = get_chapters(manga_result["id"], lang="en", limit=100, offset=0)
    eclipse_chs = []
    for ch in all_chapters:
        ch_num = ch.get("chapter", "")
        try:
            if ch_num and 73 <= float(ch_num) <= 84:
                eclipse_chs.append(ch)
        except (ValueError, TypeError):
            pass
    if not eclipse_chs:
        eclipse_chs = all_chapters[-5:]  # fallback
    log.info(f"Eclipse EN chapters: {len(eclipse_chs)}")
    for ch in eclipse_chs[:3]:
        ch_pages = download_chapter_pages(ch["id"], output_dir=str(OUTPUT_DIR / "pages"), max_pages=5)
        pages.extend(ch_pages)

if not pages:
    for d in ["data/manga_panels/berserk_eclipse_ch83", "data/manga_panels/berserk_ch382"]:
        if Path(d).exists():
            pages = sorted(str(p) for p in Path(d).glob("*.[jp][pn]g"))[:10]
            if pages:
                break

log.info(f"Pages: {len(pages)}")

# ── Step 2b: OCR pages for text matching ──
log.info("=== Step 2b: OCR pages ===")
page_ocr = {}
try:
    import easyocr
    reader = easyocr.Reader(["en"], gpu=True, verbose=False)
    for page in pages:
        results = reader.readtext(page)
        page_text = " ".join(r[1] for r in results)
        page_ocr[page] = page_text
        if page_text.strip():
            log.info(f"  {Path(page).name}: {page_text[:60]}...")
except Exception as e:
    log.warning(f"OCR failed: {e}")

# ── Step 3: Generate ONE audio (single voice) ──
log.info("=== Step 3: Single-voice audio ===")

from gradio_client import Client
fish = Client("http://fish-speech:7860")

def enhance_for_tts(text):
    """Add punctuation cues that help Fish Speech with intonation."""
    # Ensure questions end with ?
    if any(text.lower().startswith(w) for w in ["what ", "why ", "how ", "is ", "can ", "does ", "will ", "are ", "was "]):
        if not text.rstrip().endswith("?"):
            text = text.rstrip().rstrip(".") + "?"
    # Add dramatic pauses
    text = text.replace(" — ", "... ")
    text = text.replace(" – ", "... ")
    # Emphasize ellipsis for pauses
    text = text.replace("...", "... ")
    return text

# Combine all narration into one text with pauses
all_parts = []
if script.get("intro"):
    all_parts.append(("intro", enhance_for_tts(script["intro"])))
for i, seg in enumerate(script.get("segments", [])):
    if seg.get("text"):
        all_parts.append((f"seg{i}", enhance_for_tts(seg["text"])))
if script.get("outro"):
    all_parts.append(("outro", enhance_for_tts(script["outro"])))

# Generate each segment individually but KEEP the same session
# Fish Speech maintains voice within a session if we use memory cache
audio_files = []
durations = []

for label, text in all_parts:
    dst = str(OUTPUT_DIR / f"audio_{label}.wav")
    try:
        result = fish.predict(
            text=text,
            enable_reference_audio=False,
            reference_audio=None,
            reference_text="",
            max_new_tokens=1024,
            chunk_length=200,
            top_p=0.8,
            repetition_penalty=1.15,
            temperature=0.8,
            batch_infer_num=1,
            api_name="/inference_wrapper",
        )
        audio_info = result[1]
        if isinstance(audio_info, dict) and audio_info.get("value"):
            src = audio_info["value"]
            if isinstance(src, dict):
                src = src.get("path", "")
            if src and os.path.exists(str(src)):
                shutil.copy(src, dst)
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", dst],
                    capture_output=True, text=True,
                )
                dur = float(probe.stdout.strip()) if probe.stdout.strip() else 3.0
                audio_files.append(dst)
                durations.append(dur)
                log.info(f"  {label}: {dur:.1f}s")
    except Exception as e:
        log.warning(f"  {label} failed: {e}")

# Also try: generate ALL text as one single audio for voice consistency
full_text = " ... ".join(text for _, text in all_parts)
single_audio = str(OUTPUT_DIR / "audio_single.wav")
try:
    result = fish.predict(
        text=full_text,
        enable_reference_audio=False,
        reference_audio=None,
        reference_text="",
        max_new_tokens=2048,
        chunk_length=300,
        top_p=0.8,
        repetition_penalty=1.15,
        temperature=0.8,
        batch_infer_num=1,
        api_name="/inference_wrapper",
    )
    audio_info = result[1]
    if isinstance(audio_info, dict) and audio_info.get("value"):
        src = audio_info["value"]
        if isinstance(src, dict):
            src = src.get("path", "")
        if src and os.path.exists(str(src)):
            shutil.copy(src, single_audio)
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", single_audio],
                capture_output=True, text=True,
            )
            single_dur = float(probe.stdout.strip()) if probe.stdout.strip() else 0
            log.info(f"  SINGLE voice: {single_dur:.1f}s")
except Exception as e:
    log.warning(f"  Single audio failed: {e}")
    single_audio = None

# Decide: use single audio (consistent voice) or individual segments
use_single = single_audio and Path(single_audio).exists() and Path(single_audio).stat().st_size > 1000
if use_single:
    final_audio = single_audio
    total_duration = single_dur
    log.info("Using SINGLE voice audio (consistent)")
else:
    # Concat individual segments
    final_audio = str(OUTPUT_DIR / "full_audio.wav")
    concat_list = str(OUTPUT_DIR / "audio_concat.txt")
    with open(concat_list, "w") as f:
        for af in audio_files:
            f.write(f"file '{af}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", final_audio],
        capture_output=True, timeout=30,
    )
    total_duration = sum(durations)
    log.info(f"Using concatenated audio ({total_duration:.1f}s)")

# ── Step 4: Render video clips (one per segment, matched to audio duration) ──
log.info("=== Step 4: Render video ===")

from apps.production.video_director import VideoDirector, EditDecision
director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)

import tempfile
tmpdir = tempfile.mkdtemp(prefix="dirv3_")
clip_paths = []

def match_page_to_text(narr_text, pages_list, ocr_dict, used_set):
    """Find the best page for a narration segment using OCR text matching."""
    import re as _re
    query_words = set(_re.findall(r'\b[a-z]{4,}\b', narr_text.lower()))
    stopwords = {"this", "that", "with", "from", "have", "been", "their", "would", "could", "about", "which"}
    query_words -= stopwords

    best_page = None
    best_score = -1
    for page in pages_list:
        if page in used_set and len(pages_list) > len(used_set) + 1:
            continue
        page_text = (ocr_dict.get(page, "") or "").lower()
        page_words = set(_re.findall(r'\b[a-z]{4,}\b', page_text))
        score = len(query_words & page_words)
        if score > best_score:
            best_score = score
            best_page = page
    return best_page

if use_single:
    # Single audio: match pages to narration via OCR
    n_pages = min(len(pages), len(all_parts))
    seg_dur = total_duration / n_pages
    emotions = ["default"]
    for seg in script.get("segments", []):
        emotions.append(seg.get("emotion", "default"))
    emotions.append("hopeful")  # outro

    used_pages = set()
    for i in range(n_pages):
        # Try OCR match first
        narr_text = all_parts[i][1] if i < len(all_parts) else ""
        matched = match_page_to_text(narr_text, pages, page_ocr, used_pages) if page_ocr else None
        page = matched or pages[i % len(pages)]
        used_pages.add(page)

        emotion = emotions[i] if i < len(emotions) else "default"
        clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")

        d = EditDecision(
            visual_type="manga_panel",
            visual_path=page,
            duration=seg_dur,
            emotion=emotion,
            camera=director._camera_for_emotion(emotion),
            transition_in=director._transition_for_shift(emotion, i),
        )
        director._render_panel_segment(d, clip_path)

        if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
            clip_paths.append(clip_path)
            log.info(f"  Clip {i}: {Path(clip_path).stat().st_size // 1024}KB | {emotion}")
else:
    # Individual segments: each clip matches its audio duration
    for i, (dur, (label, text)) in enumerate(zip(durations, all_parts)):
        page_idx = min(i, len(pages) - 1)
        page = pages[page_idx]

        emotion = "default"
        for seg in script.get("segments", []):
            if seg.get("text") == text:
                emotion = seg.get("emotion", "default")
                break

        clip_path = os.path.join(tmpdir, f"seg_{i:03d}.mp4")
        d = EditDecision(
            visual_type="manga_panel",
            visual_path=page,
            duration=dur,
            emotion=emotion,
            camera=director._camera_for_emotion(emotion),
            transition_in=director._transition_for_shift(emotion, i),
        )
        director._render_panel_segment(d, clip_path)

        if Path(clip_path).exists() and Path(clip_path).stat().st_size > 0:
            clip_paths.append(clip_path)
            log.info(f"  Clip {i}: {Path(clip_path).stat().st_size // 1024}KB | {emotion} | {dur:.1f}s")

# ── Step 5: Assemble video ──
log.info("=== Step 5: Assemble ===")

video_only = os.path.join(tmpdir, "video.mp4")
concat_file = os.path.join(tmpdir, "concat.txt")
with open(concat_file, "w") as f:
    for c in clip_paths:
        f.write(f"file '{c}'\n")
subprocess.run(
    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", video_only],
    capture_output=True, timeout=60,
)

# ── Step 6: Merge video + audio ──
log.info("=== Step 6: Merge audio ===")

merged = str(OUTPUT_DIR / "merged.mp4")
r = subprocess.run([
    "ffmpeg", "-y",
    "-i", video_only, "-i", final_audio,
    "-map", "0:v", "-map", "1:a",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
    "-shortest",
    merged,
], capture_output=True, text=True, timeout=60)

if not Path(merged).exists():
    log.error(f"Merge failed: {r.stderr[:200]}")
    shutil.copy(video_only, merged)

# ── Step 7: Burn subtitles AFTER merge ──
log.info("=== Step 7: Subtitles ===")

from apps.production.animated_subs import generate_ass_subtitles

# Use Whisper to get EXACT word timestamps from the audio
log.info("Transcribing audio with Whisper for exact subtitle timing...")
sub_segments = []

try:
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(final_audio, language="en", word_timestamps=True)

    for segment in result.get("segments", []):
        seg_text = segment.get("text", "").strip()
        seg_start = segment.get("start", 0)
        seg_end = segment.get("end", 0)

        if not seg_text:
            continue

        # Find matching emotion from script
        emotion = "default"
        seg_lower = seg_text.lower()
        for s in script.get("segments", []):
            s_text = s.get("text", "").lower()
            # Check if any words overlap
            seg_words = set(seg_lower.split())
            s_words = set(s_text.split())
            if len(seg_words & s_words) >= 3:
                emotion = s.get("emotion", "default")
                break

        sub_segments.append({
            "text": seg_text,
            "start_s": seg_start,
            "end_s": seg_end,
            "emotion": emotion,
        })

    log.info(f"Whisper: {len(sub_segments)} subtitle segments with exact timing")

except Exception as e:
    log.warning(f"Whisper failed: {e}, using estimated timing")
    # Fallback: estimated timing
    if use_single:
        seg_dur_sub = total_duration / max(len(all_parts), 1)
        for i, (label, text) in enumerate(all_parts):
            emotion = "default"
            for seg in script.get("segments", []):
                if seg.get("text") == text:
                    emotion = seg.get("emotion", "default")
                    break
            sub_segments.append({
                "text": text,
                "start_s": i * seg_dur_sub,
                "end_s": (i + 1) * seg_dur_sub,
                "emotion": emotion,
            })
    else:
        t = 0.0
        for i, (dur, (label, text)) in enumerate(zip(durations, all_parts)):
            emotion = "default"
            for seg in script.get("segments", []):
                if seg.get("text") == text:
                    emotion = seg.get("emotion", "default")
                    break
            sub_segments.append({
                "text": text,
                "start_s": t,
                "end_s": t + dur,
                "emotion": emotion,
            })
            t += dur

ass_path = str(OUTPUT_DIR / "subtitles.ass")
generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")

# Burn
final_output = str(OUTPUT_DIR / "FINAL.mp4")
ass_escaped = ass_path.replace("\\", "/").replace(":", "\\\\:")
r = subprocess.run([
    "ffmpeg", "-y",
    "-i", merged,
    "-vf", f"ass='{ass_escaped}'",
    "-c:v", "h264_nvenc", "-b:v", "5M",
    "-c:a", "copy",
    final_output,
], capture_output=True, text=True, timeout=120)

if not Path(final_output).exists():
    log.warning(f"Subtitle burn failed: {r.stderr[:200]}")
    shutil.copy(merged, final_output)
    log.info("Using version without subtitles")

# Cleanup
shutil.rmtree(tmpdir, ignore_errors=True)

# ── Done ──
if Path(final_output).exists():
    size = Path(final_output).stat().st_size // 1024
    log.info(f"\n=== DONE ===")
    log.info(f"File: {final_output} ({size}KB)")
    log.info(f"Title: {script.get('title', '?')}")
    log.info(f"Duration: {total_duration:.1f}s")
    log.info(f"Clips: {len(clip_paths)}")
    log.info(f"Voice: {'single (consistent)' if use_single else 'per-segment'}")
    log.info(f"Subtitles: {'Whisper-synced' if sub_segments else 'estimated'}")
else:
    log.error("Final render failed!")
