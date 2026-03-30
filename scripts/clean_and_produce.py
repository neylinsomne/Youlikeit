"""Clean DB and produce first Short for upload."""
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
OUTPUT_DIR = Path("outputs/manga/production")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# ── Clean DB ──
log.info("=== Cleaning old shorts ===")
old = conn.execute("SELECT COUNT(*) FROM shorts").fetchone()[0]
conn.execute("DELETE FROM shorts")
conn.execute("DELETE FROM reviews")
conn.commit()
log.info(f"Deleted {old} old shorts")

# ── Step 1: Script ──
log.info("=== Step 1: Generate script (Deep Mind) ===")

from common.personas import get_persona, build_narration_prompt
from common.video_director import get_director_prompt_addon

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
prompt += "\n\nIMPORTANT: Generate exactly 4 segments. Keep total narration under 50 seconds. Make it compelling for YouTube Shorts."

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
with open(str(OUTPUT_DIR / "script.json"), "w") as f:
    json.dump(script, f, indent=2)

# ── Step 2: Pages (English Eclipse chapters) ──
log.info("=== Step 2: Download English Eclipse pages ===")

from common.mangadex import search_manga, get_chapters, download_chapter_pages

pages = []
manga_result = search_manga("Berserk")
if manga_result:
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
        eclipse_chs = all_chapters[-5:]
    log.info(f"Eclipse EN chapters: {len(eclipse_chs)}")
    for ch in eclipse_chs[:3]:
        ch_pages = download_chapter_pages(ch["id"], output_dir=str(OUTPUT_DIR / "pages"), max_pages=5)
        pages.extend(ch_pages)

if not pages:
    for d in ["data/manga_panels/berserk_eclipse_ch83", "data/manga_panels/berserk_ch382"]:
        if Path(d).exists():
            pages = sorted(str(p) for p in Path(d).glob("*.[jp][pn]g"))[:12]
            if pages:
                break

log.info(f"Pages: {len(pages)}")

# ── Step 2b: OCR ──
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
            log.info(f"  {Path(page).name}: {page_text[:50]}...")
except Exception as e:
    log.warning(f"OCR failed: {e}")

# ── Step 3: Audio (single voice) ──
log.info("=== Step 3: Generate audio ===")

def enhance_for_tts(text):
    if any(text.lower().startswith(w) for w in ["what ", "why ", "how ", "is ", "can ", "does "]):
        if not text.rstrip().endswith("?"):
            text = text.rstrip().rstrip(".") + "?"
    text = text.replace(" — ", "... ")
    text = text.replace(" – ", "... ")
    return text

all_parts = []
if script.get("intro"):
    all_parts.append(("intro", enhance_for_tts(script["intro"])))
for i, seg in enumerate(script.get("segments", [])):
    if seg.get("text"):
        all_parts.append((f"seg{i}", enhance_for_tts(seg["text"])))
if script.get("outro"):
    all_parts.append(("outro", enhance_for_tts(script["outro"])))

from gradio_client import Client
fish = Client("http://fish-speech:7860")

# Generate ALL as single audio
full_text = " ... ".join(text for _, text in all_parts)
single_audio = str(OUTPUT_DIR / "audio_single.wav")

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
total_duration = float(probe.stdout.strip()) if probe.stdout.strip() else 40.0
log.info(f"Single voice audio: {total_duration:.1f}s")

# ── Step 4: Render video ──
log.info("=== Step 4: Render video clips ===")

from common.video_director import VideoDirector, EditDecision
director = VideoDirector(target_size=(1080, 1920), fps=30, use_gpu=True)

import tempfile
tmpdir = tempfile.mkdtemp(prefix="prod_")
clip_paths = []

n_segments = len(all_parts)
seg_dur = total_duration / n_segments
emotions = []
for label, _ in all_parts:
    if label == "intro":
        emotions.append("epic")
    elif label == "outro":
        emotions.append("hopeful")
    else:
        idx = int(label.replace("seg", ""))
        segs = script.get("segments", [])
        emotions.append(segs[idx].get("emotion", "default") if idx < len(segs) else "default")

# Match pages to narration via OCR
def match_page(narr_text, pages_list, ocr_dict, used_set):
    query_words = set(re.findall(r'\b[a-z]{4,}\b', narr_text.lower()))
    stopwords = {"this", "that", "with", "from", "have", "been", "their", "would", "about", "which"}
    query_words -= stopwords
    best_page, best_score = None, -1
    for page in pages_list:
        if page in used_set and len(pages_list) > len(used_set) + 1:
            continue
        page_words = set(re.findall(r'\b[a-z]{4,}\b', (ocr_dict.get(page, "") or "").lower()))
        score = len(query_words & page_words)
        if score > best_score:
            best_score = score
            best_page = page
    return best_page

used = set()
for i in range(n_segments):
    narr_text = all_parts[i][1]
    matched = match_page(narr_text, pages, page_ocr, used) if page_ocr else None
    page = matched or pages[i % len(pages)]
    used.add(page)
    emotion = emotions[i]

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
        log.info(f"  Clip {i}: {emotion} | {Path(page).name}")

# ── Step 5: Assemble + merge audio ──
log.info("=== Step 5: Assemble + merge ===")

video_only = os.path.join(tmpdir, "video.mp4")
concat_file = os.path.join(tmpdir, "concat.txt")
with open(concat_file, "w") as f:
    for c in clip_paths:
        f.write(f"file '{c}'\n")
subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", video_only],
               capture_output=True, timeout=60)

merged = str(OUTPUT_DIR / "merged.mp4")
subprocess.run(["ffmpeg", "-y", "-i", video_only, "-i", single_audio,
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", merged], capture_output=True, timeout=60)

# ── Step 6: Whisper sync subtitles ──
log.info("=== Step 6: Whisper sync subtitles ===")

from common.animated_subs import generate_ass_subtitles

sub_segments = []
try:
    import whisper
    model = whisper.load_model("base")
    result = model.transcribe(single_audio, language="en", word_timestamps=True)
    for segment in result.get("segments", []):
        seg_text = segment.get("text", "").strip()
        if not seg_text:
            continue
        emotion = "default"
        seg_lower = seg_text.lower()
        for s in script.get("segments", []):
            s_words = set(s.get("text", "").lower().split())
            if len(set(seg_lower.split()) & s_words) >= 3:
                emotion = s.get("emotion", "default")
                break
        sub_segments.append({
            "text": seg_text,
            "start_s": segment["start"],
            "end_s": segment["end"],
            "emotion": emotion,
        })
    log.info(f"Whisper: {len(sub_segments)} segments")
except Exception as e:
    log.warning(f"Whisper failed: {e}")

ass_path = str(OUTPUT_DIR / "subtitles.ass")
generate_ass_subtitles(sub_segments, ass_path, style="shorts", emotion="dark")

# ── Step 7: Burn subtitles ──
log.info("=== Step 7: Final render ===")

final = str(OUTPUT_DIR / "PRODUCTION_READY.mp4")
ass_escaped = ass_path.replace("\\", "/").replace(":", "\\\\:")
r = subprocess.run(["ffmpeg", "-y", "-i", merged, "-vf", f"ass='{ass_escaped}'",
                     "-c:v", "h264_nvenc", "-b:v", "5M", "-c:a", "copy", final],
                    capture_output=True, text=True, timeout=120)
if not Path(final).exists():
    shutil.copy(merged, final)
    log.warning("Subtitle burn failed, using version without subs")

shutil.rmtree(tmpdir, ignore_errors=True)

# ── Step 8: Register in DB ──
log.info("=== Step 8: Register in DB ===")

title = script.get("title", "Berserk: The Eclipse")
hashtags = ",".join(script.get("hashtags", ["#Berserk", "#Manga", "#Shorts", "#YouLikeIt", "#Anime"]))

conn.execute("""INSERT INTO shorts
    (title, theme_query, output_file, status, category, emotion, hashtags,
     narration_intro, narration_outro, narration_segments, voice,
     series_name, arc_name, part_number, description)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (title, "berserk eclipse", f"outputs/manga/production/PRODUCTION_READY.mp4",
     "pending_review", "dramatic", "dark", hashtags,
     script.get("intro", ""), script.get("outro", ""),
     json.dumps(script.get("segments", [])), "fish-speech-1.4",
     "Berserk", "Golden Age", 1,
     f"{title} | #Shorts #Manga #Berserk #Anime #YouLikeIt"))
conn.commit()

short_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

if Path(final).exists():
    size = Path(final).stat().st_size // 1024
    log.info(f"\n=== PRODUCTION READY ===")
    log.info(f"Short ID: {short_id}")
    log.info(f"Title: {title}")
    log.info(f"File: {final} ({size}KB)")
    log.info(f"Duration: {total_duration:.1f}s")
    log.info(f"Hashtags: {hashtags}")
    log.info(f"Status: pending_review")
    log.info(f"View in frontend: http://localhost:5180/review")
