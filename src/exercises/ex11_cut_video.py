"""
ex11 - Edicion completa de Shorts: corte + musica + subtitulos + formato final.

Pipeline de edicion:
  1. Lee manifest JSON (de ex07) o CSV de curation (de ex09)
  2. Descarga fragmentos de escenas de YouTube con yt-dlp
  3. Corta segmentos exactos con FFmpeg
  4. Escala a 9:16 vertical (1080x1920)
  5. Quema subtitulos sobre el video
  6. Descarga cancion viral de TikTok/YouTube (del growth pack ex08)
  7. Mezcla audio: voz original + musica de fondo a volumen bajo
  8. Concatena clips con transiciones
  9. Exporta en formato compatible con YouTube Shorts Y TikTok

Formato de salida (compatible con ambas plataformas):
  - Codec: H.264 (video) + AAC (audio)
  - Resolucion: 1080x1920 (9:16)
  - FPS: 30
  - Bitrate: 8Mbps video, 192kbps audio
  - Max duracion: 59s
  - Contenedor: .mp4 con faststart

Requisitos:
  - FFmpeg instalado y en PATH
  - yt-dlp instalado (ya esta en requirements.txt)

Uso:
  python src/main.py ex11 --query "villain monologue"
  python src/main.py ex11 --query "villain" --burn-subs --music-vol 0.15
  python src/main.py ex11 --manifest outputs/manifests/short_manifest_villain.json
  python src/main.py ex11 --music-url "https://www.youtube.com/watch?v=xxx" --music-vol 0.2
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ── Output specs (YouTube Shorts + TikTok compatible) ────────────────

FINAL_WIDTH = 1080
FINAL_HEIGHT = 1920
FINAL_FPS = 30
VIDEO_BITRATE = "8M"
AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 44100
MAX_DURATION_S = 59  # YouTube Shorts max 60s, leave 1s margin


# ── Tool checks ──────────────────────────────────────────────────────


def _check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _check_ytdlp() -> bool:
    return shutil.which("yt-dlp") is not None


def _has_nvenc() -> bool:
    """Check if NVIDIA NVENC encoder is available (GPU accelerated)."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        return "h264_nvenc" in result.stdout
    except Exception:
        return False


def _get_video_encoder() -> tuple[str, list[str]]:
    """
    Return (encoder_name, extra_args) for video encoding.
    Uses GPU (NVENC) if available, otherwise CPU (libx264).

    RTX 5060 NVENC: ~3s/clip vs CPU libx264: ~20s/clip
    """
    if _has_nvenc():
        return "h264_nvenc", [
            "-c:v", "h264_nvenc",
            "-preset", "p4",      # balanced speed/quality
            "-rc", "vbr",         # variable bitrate
            "-cq", "23",          # quality level (lower = better)
            "-b:v", VIDEO_BITRATE,
        ]
    return "libx264", [
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-b:v", VIDEO_BITRATE,
    ]


def _ms_to_ffmpeg_time(ms: int) -> str:
    total_s = ms / 1000.0
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _get_duration_s(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


# ── Manifest loading ────────────────────────────────────────────────


def _find_latest_manifest(manifests_dir: Path, query: str = "") -> Path | None:
    if not manifests_dir.exists():
        return None
    candidates = sorted(
        manifests_dir.glob("short_manifest_*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if query:
        safe_q = query.replace(" ", "_").lower()
        for c in candidates:
            if safe_q in c.stem.lower():
                return c
    return candidates[0] if candidates else None


# ── YouTube search + download ────────────────────────────────────────


def _search_youtube_url(movie_title: str, quote_text: str, conn=None) -> str | None:
    """Search YouTube for a scene, with DB cache to avoid repeated searches."""
    snippet = quote_text[:40]

    # Check cache first
    if conn:
        try:
            cur = conn.execute(
                "SELECT youtube_url FROM url_cache WHERE movie_title = ? AND quote_snippet = ? LIMIT 1",
                (movie_title, snippet),
            )
            row = cur.fetchone()
            if row:
                return row["youtube_url"]
        except Exception:
            pass

    search_query = f"{movie_title} movie scene {snippet}"
    try:
        result = subprocess.run(
            ["yt-dlp", f"ytsearch3:{search_query}", "--get-id", "--no-download", "--no-warnings"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            video_id = result.stdout.strip().split("\n")[0]
            url = f"https://www.youtube.com/watch?v={video_id}"

            # Cache the URL
            if conn:
                try:
                    conn.execute(
                        "INSERT OR REPLACE INTO url_cache (movie_title, quote_snippet, youtube_url) VALUES (?, ?, ?)",
                        (movie_title, snippet, url),
                    )
                    conn.commit()
                except Exception:
                    pass

            return url
    except Exception:
        pass
    return None


def _download_clip_segment(url: str, start_ms: int, end_ms: int, output_path: Path, log) -> bool:
    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0
    safe_start = max(0, start_s - 2)
    safe_end = end_s + 2
    section = f"*{safe_start:.1f}-{safe_end:.1f}"

    cmd = [
        "yt-dlp", url,
        "--download-sections", section,
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-playlist", "--quiet", "--no-warnings",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            log.info(f"  Downloaded: {output_path.name}")
            return True
        log.warning(f"  yt-dlp failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.warning(f"  yt-dlp timeout: {url}")
    except Exception as e:
        log.warning(f"  yt-dlp error: {e}")
    return False



# ── FFmpeg operations ────────────────────────────────────────────────


def _cut_segment(input_path: Path, output_path: Path, start_ms: int, end_ms: int, log) -> bool:
    """Cut exact segment with standardized output format."""
    start_time = _ms_to_ffmpeg_time(start_ms)
    duration_s = (end_ms - start_ms) / 1000.0
    _, v_args = _get_video_encoder()

    cmd = [
        "ffmpeg", "-y",
        "-ss", start_time,
        "-i", str(input_path),
        "-t", f"{duration_s:.3f}",
        *v_args, "-c:a", "aac",
        "-ar", str(AUDIO_SAMPLE_RATE),
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and output_path.exists():
            return True
        log.warning(f"  Cut failed: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"  Cut error: {e}")
    return False


def _scale_to_vertical(input_path: Path, output_path: Path, log) -> bool:
    """Scale + crop to 1080x1920 (9:16) with padding if needed."""
    _, v_args = _get_video_encoder()
    vf = (
        f"scale={FINAL_WIDTH}:{FINAL_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={FINAL_WIDTH}:{FINAL_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={FINAL_FPS}"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        *v_args, "-c:a", "aac",
        "-ar", str(AUDIO_SAMPLE_RATE),
        "-b:a", AUDIO_BITRATE,
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            return True
        log.warning(f"  Scale failed: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"  Scale error: {e}")
    return False


def _burn_subtitle_text(input_path: Path, output_path: Path, text: str, log) -> bool:
    """Burn subtitle text centered at bottom quarter of video."""
    # Escape FFmpeg drawtext special characters
    safe_text = text.replace("\\", "\\\\\\\\").replace("'", "'\\''").replace(":", "\\:")
    # Word wrap: insert newline every ~30 chars at word boundary
    words = safe_text.split()
    lines = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > 30:
            lines.append(current_line)
            current_line = word
        else:
            current_line = f"{current_line} {word}".strip()
    if current_line:
        lines.append(current_line)
    wrapped = "\\n".join(lines)

    drawtext = (
        f"drawtext=text='{wrapped}':"
        f"fontsize=48:fontcolor=white:"
        f"borderw=4:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*3/4:"
        f"font=Arial:line_spacing=8"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", drawtext,
        "-c:v", "libx264", "-c:a", "copy",
        "-preset", "fast",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and output_path.exists():
            return True
        log.warning(f"  Subtitle burn failed: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"  Subtitle error: {e}")
    return False


def _normalize_clip_for_concat(input_path: Path, output_path: Path, log) -> bool:
    """
    Normalize a clip so all clips are concat-compatible:
    same resolution, fps, codec, pixel format, audio sample rate.
    """
    _, v_args = _get_video_encoder()
    vf = (
        f"scale={FINAL_WIDTH}:{FINAL_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={FINAL_WIDTH}:{FINAL_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={FINAL_FPS},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        *v_args, "-c:a", "aac",
        "-ar", str(AUDIO_SAMPLE_RATE), "-ac", "2",
        "-b:a", AUDIO_BITRATE,
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists():
            return True
        log.warning(f"  Normalize failed: {result.stderr[:200]}")
    except Exception as e:
        log.warning(f"  Normalize error: {e}")
    return False


def _concat_clips(clip_paths: list[Path], output_path: Path, log) -> bool:
    """Concatenate clips using FFmpeg concat demuxer."""
    if not clip_paths:
        return False

    list_file = output_path.parent / "concat_list.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for p in clip_paths:
            safe_path = str(p).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        list_file.unlink(missing_ok=True)
        if result.returncode == 0 and output_path.exists():
            return True
        log.warning(f"  Concat failed: {result.stderr[:300]}")
    except Exception as e:
        log.warning(f"  Concat error: {e}")
        list_file.unlink(missing_ok=True)
    return False



def _finalize_for_upload(input_path: Path, output_path: Path, log) -> bool:
    """
    Final pass: ensure the video meets platform specs exactly.

    Output: H.264 + AAC, 1080x1920, 30fps, yuv420p, faststart, max 59s.
    Compatible with both YouTube Shorts and TikTok.
    """
    encoder_name, v_args = _get_video_encoder()
    log.info(f"  Final encode with: {encoder_name}")

    vf = (
        f"scale={FINAL_WIDTH}:{FINAL_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={FINAL_WIDTH}:{FINAL_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={FINAL_FPS},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-t", str(MAX_DURATION_S),
        "-vf", vf,
        *v_args,
        "-profile:v", "high",
        "-maxrate", "10M",
        "-bufsize", "16M",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-ar", str(AUDIO_SAMPLE_RATE),
        "-ac", "2",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0 and output_path.exists():
            return True
        log.warning(f"  Finalize failed: {result.stderr[:300]}")
    except Exception as e:
        log.warning(f"  Finalize error: {e}")
    return False


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    query: str = "",
    manifest_path: str = "",
    burn_subs: bool = False,
    vertical: bool = True,
) -> Path:
    log = build_logger("ex11", settings.output_dir / "logs" / "ex11.log")

    # Validate tools
    for tool_name, check_fn, install_hint in [
        ("FFmpeg", _check_ffmpeg, "Install from https://ffmpeg.org and add to PATH"),
        ("yt-dlp", _check_ytdlp, "pip install yt-dlp"),
    ]:
        if not check_fn():
            msg = f"{tool_name} not found. {install_hint}"
            log.error(msg)
            rp = settings.output_dir / "logs" / "ex11_cut_report.txt"
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(f"ex11 - ERROR: {msg}\n", encoding="utf-8")
            return rp

    # Load manifest
    manifest = None
    if manifest_path and Path(manifest_path).exists():
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        log.info(f"Loaded manifest: {manifest_path}")
    else:
        found = _find_latest_manifest(settings.output_dir / "manifests", query)
        if found:
            manifest = json.loads(found.read_text(encoding="utf-8"))
            log.info(f"Found manifest: {found}")

    if not manifest or not manifest.get("clips"):
        msg = "No manifest or clips found. Run ex07 first."
        log.error(msg)
        rp = settings.output_dir / "logs" / "ex11_cut_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(f"ex11 - ERROR: {msg}\n", encoding="utf-8")
        return rp

    clips = manifest["clips"]
    theme = manifest.get("theme", query or "short")
    safe_theme = re.sub(r"[^a-zA-Z0-9_-]+", "_", theme)[:40]

    # Directories
    work_dir = settings.output_dir / "video" / f"work_{safe_theme}"
    work_dir.mkdir(parents=True, exist_ok=True)
    final_dir = settings.output_dir / "video" / "finals"
    final_dir.mkdir(parents=True, exist_ok=True)

    encoder_name, _ = _get_video_encoder()
    log.info(f"Video encoder: {encoder_name} ({'GPU NVENC' if 'nvenc' in encoder_name else 'CPU'})")
    log.info(f"Processing {len(clips)} clips | theme: {theme}")

    report_lines = [
        "ex11 - Video Editing Report",
        "=" * 50,
        f"Theme: {theme}",
        f"Clips: {len(clips)}",
        f"Subtitles: {'ON' if burn_subs else 'OFF'}",
        f"Encoder: {encoder_name} ({'GPU' if 'nvenc' in encoder_name else 'CPU'})",
        f"Music: select on platform (see ex08 growth pack for recommended song)",
        f"Output format: {FINAL_WIDTH}x{FINAL_HEIGHT} @ {FINAL_FPS}fps H.264+AAC",
        "",
    ]

    conn = get_db(settings.data_dir)

    # Migrate: add url_cache table if not exists
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS url_cache ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "movie_title TEXT NOT NULL,"
            "quote_snippet TEXT,"
            "youtube_url TEXT,"
            "cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
            "CREATE INDEX IF NOT EXISTS idx_url_cache_movie ON url_cache(movie_title);"
        )
    except Exception:
        pass

    # Step 1: Search + download ALL clips in parallel (biggest bottleneck)
    log.info("Phase 1: Searching & downloading clips in parallel...")

    def _search_and_download(i, clip):
        movie_title = clip.get("movie_title", f"clip_{i}")
        quote_text = clip.get("quote", "")
        start_ms = clip.get("start_ms", 0)
        end_ms = clip.get("end_ms", 0)
        safe_movie = re.sub(r"[^a-zA-Z0-9_-]+", "_", movie_title)[:30]
        clip_name = f"clip_{i:02d}_{safe_movie}"
        raw_path = work_dir / f"{clip_name}_raw.mp4"

        if raw_path.exists():
            return i, clip_name, raw_path, "cached"

        url = _search_youtube_url(movie_title, quote_text, conn)
        if not url:
            return i, clip_name, None, "no source"

        ok = _download_clip_segment(url, start_ms, end_ms, raw_path, log)
        if ok:
            return i, clip_name, raw_path, "downloaded"
        return i, clip_name, None, "download failed"

    download_results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_search_and_download, i, clip): i for i, clip in enumerate(clips)}
        for future in as_completed(futures):
            idx, clip_name, raw_path, status = future.result()
            download_results[idx] = (clip_name, raw_path, status)
            log.info(f"  [{idx+1}/{len(clips)}] {clips[idx].get('movie_title', '')}: {status}")

    # Step 2: Process clips sequentially (FFmpeg encode, subtitles, normalize)
    log.info("Phase 2: Processing clips (encode + subtitles + normalize)...")
    ready_clips: list[Path] = []

    for i, clip in enumerate(clips):
        movie_title = clip.get("movie_title", f"clip_{i}")
        quote_text = clip.get("quote", "")
        start_ms = clip.get("start_ms", 0)
        end_ms = clip.get("end_ms", 0)

        clip_name, raw_path, dl_status = download_results.get(i, ("", None, "missing"))

        report_lines.append(f"Clip {i + 1}: {movie_title}")
        report_lines.append(f"  Quote: \"{quote_text[:80]}\"")

        if not raw_path or not raw_path.exists():
            report_lines.append(f"  Status: SKIPPED ({dl_status})")
            report_lines.append("")
            continue

        # Precise cut
        current_path = raw_path
        cut_path = work_dir / f"{clip_name}_cut.mp4"
        if not cut_path.exists():
            if _cut_segment(raw_path, cut_path, start_ms, end_ms, log):
                current_path = cut_path

        # Burn subtitles
        if burn_subs and quote_text:
            sub_path = work_dir / f"{clip_name}_sub.mp4"
            if not sub_path.exists():
                if _burn_subtitle_text(current_path, sub_path, quote_text, log):
                    current_path = sub_path

        # Normalize to final format
        norm_path = work_dir / f"{clip_name}_norm.mp4"
        if not norm_path.exists():
            if _normalize_clip_for_concat(current_path, norm_path, log):
                current_path = norm_path

        ready_clips.append(current_path)
        duration_s = (end_ms - start_ms) / 1000.0
        report_lines.append(f"  Status: OK ({duration_s:.1f}s)")
        report_lines.append("")

    if not ready_clips:
        report_lines.append("NO CLIPS PRODUCED - check logs")
        rp = settings.output_dir / "logs" / "ex11_cut_report.txt"
        rp.write_text("\n".join(report_lines), encoding="utf-8")
        conn.close()
        return rp

    # Step 5: Concatenate
    if len(ready_clips) > 1:
        concat_path = work_dir / f"concat_{safe_theme}.mp4"
        log.info(f"Concatenating {len(ready_clips)} clips...")
        ok = _concat_clips(ready_clips, concat_path, log)
        if not ok:
            # Fallback: use first clip
            concat_path = ready_clips[0]
    else:
        concat_path = ready_clips[0]

    current_final = concat_path

    # NOTE: Background music is NOT mixed into the video.
    # The song is selected ON THE PLATFORM (TikTok/YouTube) when uploading,
    # so users can discover this content by searching for that song.
    # See ex08 growth pack for the recommended song to select.

    # Step 6: Final encode for platform compatibility
    final_path = final_dir / f"short_{safe_theme}.mp4"
    log.info("Final encoding for YouTube Shorts + TikTok...")
    if _finalize_for_upload(current_final, final_path, log):
        file_size_mb = final_path.stat().st_size / (1024 * 1024)
        duration = _get_duration_s(final_path)
        log.info(f"DONE: {final_path} ({file_size_mb:.1f} MB, {duration:.1f}s)")

        report_lines.append("")
        report_lines.append("=" * 50)
        report_lines.append(f"FINAL SHORT: {final_path}")
        report_lines.append(f"Duration: {duration:.1f}s")
        report_lines.append(f"Size: {file_size_mb:.1f} MB")
        report_lines.append(f"Format: {FINAL_WIDTH}x{FINAL_HEIGHT} @ {FINAL_FPS}fps")
        report_lines.append(f"Clips: {len(ready_clips)}/{len(clips)}")
        report_lines.append(f"Compatible: YouTube Shorts + TikTok")

        # Register in DB
        clip_ids = json.dumps([c.get("index", i) for i, c in enumerate(clips) if i < len(ready_clips)])
        conn.execute(
            """INSERT INTO shorts (title, theme_query, quote_ids, output_file, status)
               VALUES (?, ?, ?, ?, 'rendered')""",
            (f"Short: {theme}", theme, clip_ids, str(final_path)),
        )
        conn.commit()
    else:
        report_lines.append("FINAL ENCODE FAILED - raw concat available in work dir")
        # Copy unfinalized version as fallback
        shutil.copy2(current_final, final_path)

    report_path = settings.output_dir / "logs" / "ex11_cut_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report: {report_path}")

    conn.close()
    return report_path
