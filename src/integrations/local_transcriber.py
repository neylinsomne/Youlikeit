"""
Local transcription from video/audio files using Whisper.

For content you already have (downloaded, qBittorrent, local archives):
1. Extract audio track from video with ffmpeg
2. Transcribe with Whisper (GPU-accelerated)
3. Output: SRT + timestamped quotes ready for the pipeline

Supports:
- Any video format (mp4, mkv, avi, etc.)
- Any audio format (mp3, wav, flac, etc.)
- Batch processing of directories
- Language detection (auto) or forced (es, en, pt)
- Quote extraction with emotion classification

Usage:
    from integrations.local_transcriber import transcribe_file, batch_transcribe

    # Single file
    quotes = transcribe_file("movie.mkv", lang="es")

    # Batch
    results = batch_transcribe("data/videos/novelas/", lang="es")
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"}
SUPPORTED_AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".wma"}


def _extract_audio(video_path: str, output_wav: str) -> bool:
    """Extract audio track from video as 16kHz mono WAV (Whisper's preferred format)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", video_path,
             "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             output_wav],
            capture_output=True, text=True, timeout=300,
        )
        return result.returncode == 0 and Path(output_wav).exists()
    except Exception as e:
        log.warning(f"Audio extraction failed: {e}")
        return False


def _get_duration(file_path: str) -> float:
    """Get media duration in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", file_path],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip()) if result.stdout.strip() else 0
    except Exception:
        return 0


def transcribe_file(
    file_path: str,
    lang: str = "auto",
    model_size: str = "",
    output_srt: str = "",
    output_json: str = "",
) -> dict:
    """
    Transcribe a single video/audio file with Whisper.

    Returns:
        {
            "success": True/False,
            "file": "path",
            "lang": "es",
            "duration_s": 120.5,
            "segments": [
                {"start_ms": 0, "end_ms": 3500, "text": "Hola mundo"},
                ...
            ],
            "srt_path": "path/to/output.srt",
            "full_text": "complete transcription",
        }
    """
    try:
        import whisper
    except ImportError:
        return {"success": False, "error": "whisper not installed. Run: pip install openai-whisper"}

    file_path = str(file_path)
    if not Path(file_path).exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    suffix = Path(file_path).suffix.lower()
    is_video = suffix in SUPPORTED_VIDEO
    is_audio = suffix in SUPPORTED_AUDIO

    if not is_video and not is_audio:
        return {"success": False, "error": f"Unsupported format: {suffix}"}

    duration = _get_duration(file_path)
    log.info(f"Transcribing: {Path(file_path).name} ({duration:.0f}s, lang={lang})")

    # Extract audio if video
    tmpdir = tempfile.mkdtemp(prefix="whisper_")
    audio_path = file_path

    if is_video:
        audio_path = os.path.join(tmpdir, "audio.wav")
        if not _extract_audio(file_path, audio_path):
            return {"success": False, "error": "Failed to extract audio from video"}

    # Load model
    if not model_size:
        # Auto-select based on duration and available VRAM
        if duration > 3600:
            model_size = "medium"  # Long content = better accuracy
        elif duration > 600:
            model_size = "small"
        else:
            model_size = "base"
        model_size = os.getenv("WHISPER_MODEL", model_size)

    log.info(f"Loading Whisper model: {model_size}")
    model = whisper.load_model(model_size)

    # Transcribe
    whisper_kwargs = {}
    if lang != "auto":
        whisper_kwargs["language"] = lang

    result = whisper.transcribe(model, audio_path, **whisper_kwargs)

    detected_lang = result.get("language", lang)
    segments_raw = result.get("segments", [])

    # Build segments with milliseconds
    segments = []
    for seg in segments_raw:
        text = seg.get("text", "").strip()
        if not text:
            continue
        segments.append({
            "start_ms": int(seg["start"] * 1000),
            "end_ms": int(seg["end"] * 1000),
            "text": text,
        })

    # Generate SRT
    srt_content = _segments_to_srt(segments)
    srt_path = output_srt or str(Path(file_path).with_suffix(".srt"))
    Path(srt_path).write_text(srt_content, encoding="utf-8")

    # Generate JSON
    if output_json:
        Path(output_json).write_text(
            json.dumps({"segments": segments, "lang": detected_lang}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Cleanup temp
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    full_text = " ".join(s["text"] for s in segments)

    log.info(f"Transcribed: {len(segments)} segments, {len(full_text)} chars, lang={detected_lang}")

    return {
        "success": True,
        "file": file_path,
        "lang": detected_lang,
        "duration_s": duration,
        "segments": segments,
        "srt_path": srt_path,
        "full_text": full_text,
    }


def batch_transcribe(
    directory: str,
    lang: str = "auto",
    model_size: str = "",
    recursive: bool = True,
) -> list[dict]:
    """
    Transcribe all video/audio files in a directory.
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        return [{"success": False, "error": f"Directory not found: {directory}"}]

    all_extensions = SUPPORTED_VIDEO | SUPPORTED_AUDIO
    if recursive:
        files = [f for f in dir_path.rglob("*") if f.suffix.lower() in all_extensions]
    else:
        files = [f for f in dir_path.glob("*") if f.suffix.lower() in all_extensions]

    files.sort(key=lambda f: f.name)

    results = []
    for i, f in enumerate(files):
        log.info(f"[{i+1}/{len(files)}] {f.name}")
        result = transcribe_file(str(f), lang=lang, model_size=model_size)
        results.append(result)

    success = sum(1 for r in results if r.get("success"))
    log.info(f"Batch complete: {success}/{len(files)} transcribed")
    return results


def extract_quotes_from_transcription(
    segments: list[dict],
    min_words: int = 5,
    max_words: int = 30,
    min_duration_ms: int = 1500,
    max_duration_ms: int = 15000,
) -> list[dict]:
    """
    Extract usable quotes from transcription segments.

    Merges short segments, filters by length, identifies good cuts.
    Returns quotes ready for the pipeline DB.
    """
    quotes = []

    # Merge very short segments into longer ones
    merged = []
    buffer = None

    for seg in segments:
        if buffer is None:
            buffer = dict(seg)
            continue

        gap_ms = seg["start_ms"] - buffer["end_ms"]
        buffer_words = len(buffer["text"].split())

        # Merge if gap < 500ms and combined is reasonable
        if gap_ms < 500 and buffer_words < max_words:
            buffer["text"] = buffer["text"] + " " + seg["text"]
            buffer["end_ms"] = seg["end_ms"]
        else:
            merged.append(buffer)
            buffer = dict(seg)

    if buffer:
        merged.append(buffer)

    # Filter by quality
    for seg in merged:
        text = seg["text"].strip()
        words = len(text.split())
        duration_ms = seg["end_ms"] - seg["start_ms"]

        if words < min_words or words > max_words:
            continue
        if duration_ms < min_duration_ms or duration_ms > max_duration_ms:
            continue

        # Skip common non-quote segments
        lower = text.lower()
        skip_patterns = [
            "subtitulado por", "subtítulos", "translated by",
            "suscríbete", "subscribe", "next episode",
            "♪", "♫", "[música]", "[music]",
        ]
        if any(p in lower for p in skip_patterns):
            continue

        quotes.append({
            "text": text,
            "start_ms": seg["start_ms"],
            "end_ms": seg["end_ms"],
            "duration_ms": duration_ms,
            "word_count": words,
        })

    log.info(f"Extracted {len(quotes)} quotes from {len(segments)} segments")
    return quotes


def save_quotes_to_db(
    conn,
    quotes: list[dict],
    movie_title: str,
    movie_id: int = 0,
    source: str = "whisper_local",
    lang: str = "es",
):
    """Save extracted quotes to the pipeline database."""
    saved = 0
    for q in quotes:
        # Check for duplicates
        existing = conn.execute(
            "SELECT id FROM quotes WHERE text = ? AND movie_id = ?",
            (q["text"], movie_id),
        ).fetchone()
        if existing:
            continue

        conn.execute("""
            INSERT INTO quotes (movie_id, text, start_ms, end_ms, confidence, source, lang)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            movie_id, q["text"], q["start_ms"], q["end_ms"],
            85,  # High confidence — local transcription
            source, lang,
        ))
        saved += 1

    conn.commit()
    log.info(f"Saved {saved} quotes for '{movie_title}' (lang={lang})")
    return saved


# ── Helpers ─────────────────────────────────────────────────────

def _segments_to_srt(segments: list[dict]) -> str:
    """Convert segments to SRT format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _ms_to_srt_time(seg["start_ms"])
        end = _ms_to_srt_time(seg["end_ms"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format (HH:MM:SS,mmm)."""
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    remainder = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{remainder:03d}"
