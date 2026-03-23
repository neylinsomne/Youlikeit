"""ex38 - Manga panel detection, OCR, and Ken Burns Short generation.

ETL Pattern:
  Extract:  Manga page images (CBZ/CBR/folder) + OCR text extraction
  Transform: Panel detection (OpenCV) + quote matching + narration generation
  Load:     Ken Burns animated video (FFmpeg) with pauses at key panels

Pipeline:
  1. Load manga page(s) from image/CBZ/folder
  2. Detect individual panels (OpenCV contour detection)
  3. OCR each panel's speech bubbles (EasyOCR)
  4. Match OCR text against manga_quotes DB (rapidfuzz)
  5. Generate narration/reflection for matched panels (Gemini)
  6. Create Ken Burns video: pan through panels L→R, T→B
     Pause + narrate at panels with matching quotes
  7. Output: 9:16 vertical Short ready for upload

Dependencies: easyocr, opencv-python-headless, numpy, rapidfuzz
"""

import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from common.config import Settings
from common.db import get_db, register_clip

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Panel Detection (OpenCV)
# ---------------------------------------------------------------------------

def _detect_panels(image_path: str, min_area_ratio: float = 0.02) -> list[dict]:
    """Detect manga panels from a page image using contour detection.

    Returns list of panels sorted in reading order (right-to-left for manga,
    left-to-right for manhwa/comics), each with {x, y, w, h, index}.
    """
    import cv2

    img = cv2.imread(image_path)
    if img is None:
        log.warning(f"Could not read image: {image_path}")
        return []

    h, w = img.shape[:2]
    total_area = h * w
    min_area = total_area * min_area_ratio

    # Convert to grayscale and threshold
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Invert: manga panels have dark borders on white
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 200, 255, cv2.THRESH_BINARY)
    # Invert so panel borders become white
    thresh_inv = cv2.bitwise_not(thresh)

    # Morphological operations to connect panel borders
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(thresh_inv, kernel, iterations=3)

    # Find contours
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    panels = []
    for cnt in contours:
        x, y, pw, ph = cv2.boundingRect(cnt)
        area = pw * ph
        if area < min_area:
            continue
        # Skip if it's basically the whole page
        if area > total_area * 0.9:
            continue
        panels.append({"x": x, "y": y, "w": pw, "h": ph, "area": area})

    if not panels:
        # Fallback: split page into grid (2 cols x 3 rows for manga)
        log.info("No panels detected, using grid fallback")
        cols, rows = 2, 3
        pw, ph = w // cols, h // rows
        for r in range(rows):
            for c in range(cols):
                panels.append({
                    "x": c * pw, "y": r * ph,
                    "w": pw, "h": ph,
                    "area": pw * ph,
                })

    # Sort in reading order: top-to-bottom, right-to-left (manga style)
    # Group into rows (similar y position)
    panels.sort(key=lambda p: p["y"])
    rows = []
    current_row = [panels[0]]
    for p in panels[1:]:
        if abs(p["y"] - current_row[0]["y"]) < h * 0.1:
            current_row.append(p)
        else:
            rows.append(current_row)
            current_row = [p]
    rows.append(current_row)

    # Within each row, sort right-to-left (manga) or left-to-right (comics)
    sorted_panels = []
    for row in rows:
        row.sort(key=lambda p: -p["x"])  # Right to left (manga default)
        sorted_panels.extend(row)

    for i, p in enumerate(sorted_panels):
        p["index"] = i

    return sorted_panels


def _extract_panel_image(image_path: str, panel: dict, output_path: str, padding: int = 10):
    """Extract a single panel from the page image."""
    import cv2

    img = cv2.imread(image_path)
    h, w = img.shape[:2]

    x1 = max(0, panel["x"] - padding)
    y1 = max(0, panel["y"] - padding)
    x2 = min(w, panel["x"] + panel["w"] + padding)
    y2 = min(h, panel["y"] + panel["h"] + padding)

    panel_img = img[y1:y2, x1:x2]
    cv2.imwrite(output_path, panel_img)
    return output_path


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

_ocr_reader = None


def _get_ocr_reader(languages: list[str] = None):
    """Lazy-load EasyOCR reader (heavy model download on first use)."""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        langs = languages or ["en"]
        _ocr_reader = easyocr.Reader(langs, gpu=True)
        log.info(f"EasyOCR loaded with languages: {langs}")
    return _ocr_reader


def _ocr_panel(image_path: str, languages: list[str] = None) -> list[dict]:
    """Run OCR on a panel image, return detected text blocks.

    Returns list of {text, confidence, bbox} sorted top-to-bottom.
    """
    reader = _get_ocr_reader(languages)
    results = reader.readtext(image_path)

    blocks = []
    for bbox, text, conf in results:
        if conf < 0.3 or len(text.strip()) < 2:
            continue
        # bbox is [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        blocks.append({
            "text": text.strip(),
            "confidence": conf,
            "y_center": y_center,
            "bbox": bbox,
        })

    # Sort top to bottom
    blocks.sort(key=lambda b: b["y_center"])
    return blocks


# ---------------------------------------------------------------------------
# Quote Matching
# ---------------------------------------------------------------------------

def _match_ocr_to_quotes(ocr_text: str, series_title: str, conn) -> dict | None:
    """Match OCR-extracted text against manga_quotes DB using fuzzy matching."""
    from rapidfuzz import fuzz

    if len(ocr_text) < 10:
        return None

    cur = conn.execute(
        """SELECT mq.id, mq.text, mq.character_name, mq.category, mq.viral_score
           FROM manga_quotes mq
           JOIN manga_series ms ON mq.series_id = ms.id
           WHERE ms.title LIKE ?""",
        (f"%{series_title}%",),
    )
    best_match = None
    best_score = 0

    for row in cur.fetchall():
        score = fuzz.partial_ratio(ocr_text.lower(), row["text"].lower())
        if score > best_score and score >= 60:
            best_score = score
            best_match = {
                "quote_id": row["id"],
                "text": row["text"],
                "character": row["character_name"],
                "category": row["category"],
                "viral_score": row["viral_score"],
                "match_score": score,
            }

    return best_match


# ---------------------------------------------------------------------------
# Ken Burns Video Generation
# ---------------------------------------------------------------------------

# Camera movement presets for Ken Burns
CAMERA_MOVES = {
    "zoom_in":     "z='min(zoom+0.002,1.25)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "zoom_out":    "z='if(eq(on,1),1.25,max(zoom-0.002,1))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    "pan_left":    "z=1.15:x='if(eq(on,1),iw/4,max(x-2,0))':y='ih/2-(ih/zoom/2)'",
    "pan_right":   "z=1.15:x='if(eq(on,1),0,min(x+2,iw/4))':y='ih/2-(ih/zoom/2)'",
    "pan_up":      "z=1.15:x='iw/2-(iw/zoom/2)':y='if(eq(on,1),ih/4,max(y-2,0))'",
    "pan_down":    "z=1.15:x='iw/2-(iw/zoom/2)':y='if(eq(on,1),0,min(y+2,ih/4))'",
    "zoom_pan_r":  "z='min(zoom+0.001,1.20)':x='if(eq(on,1),0,min(x+1,iw/5))':y='ih/2-(ih/zoom/2)'",
    "zoom_pan_l":  "z='min(zoom+0.001,1.20)':x='if(eq(on,1),iw/5,max(x-1,0))':y='ih/2-(ih/zoom/2)'",
    "dramatic":    "z='min(zoom+0.004,1.40)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
}


def _pick_camera_move(panel_index: int, is_match: bool, total_panels: int) -> str:
    """Pick camera movement based on panel position and match status."""
    if is_match:
        return "dramatic"

    moves = list(CAMERA_MOVES.keys())
    # Cycle through movements for visual variety
    cycle = ["zoom_in", "pan_right", "zoom_out", "pan_left", "zoom_pan_r", "pan_up", "zoom_pan_l", "pan_down"]
    return cycle[panel_index % len(cycle)]


def _generate_ken_burns(
    page_image: str,
    panels: list[dict],
    matched_panels: dict,
    output_path: str,
    duration_per_panel: float = 2.0,
    pause_duration: float = 4.0,
    resolution: tuple = (1080, 1920),
) -> str:
    """Generate Ken Burns effect video panning through manga panels.

    Each panel gets a different camera movement for visual variety.
    Matched panels (with quotes) get dramatic zoom + text overlay.
    """
    import cv2

    img = cv2.imread(page_image)
    img_h, img_w = img.shape[:2]
    out_w, out_h = resolution

    filter_parts = []
    segment_durations = []
    panel_moves = []

    for i, panel in enumerate(panels):
        is_match = i in matched_panels
        dur = pause_duration if is_match else duration_per_panel
        move = _pick_camera_move(i, is_match, len(panels))
        panel_moves.append(move)

        crop_w = min(panel["w"] + 40, img_w)
        crop_h = min(panel["h"] + 40, img_h)
        crop_x = max(0, panel["x"] - 20)
        crop_y = max(0, panel["y"] - 20)

        move_expr = CAMERA_MOVES.get(move, CAMERA_MOVES["zoom_in"])

        # Build filter: crop panel → scale → Ken Burns movement
        vf = (
            f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"zoompan={move_expr}:d={int(dur * 25)}:s={out_w}x{out_h}:fps=25"
        )

        # Add text overlay for matched panels
        if is_match and matched_panels[i].get("text"):
            quote_text = matched_panels[i]["text"][:80].replace("'", "\\'").replace('"', '\\"')
            char_name = (matched_panels[i].get("character") or "").replace("'", "\\'")
            # White text with black border at bottom
            vf += (
                f",drawtext=text='{quote_text}'"
                f":fontsize=28:fontcolor=white:borderw=2:bordercolor=black"
                f":x=(w-text_w)/2:y=h-120"
                f":enable='between(t,0.5,{dur-0.5})'"
            )
            if char_name:
                vf += (
                    f",drawtext=text='— {char_name}'"
                    f":fontsize=22:fontcolor=0x00d4ff:borderw=1:bordercolor=black"
                    f":x=(w-text_w)/2:y=h-80"
                    f":enable='between(t,1,{dur-0.5})'"
                )

        filter_parts.append(vf)
        segment_durations.append(dur)

    log.info(f"  Camera moves: {', '.join(panel_moves)}")

    if not filter_parts:
        log.warning("No panels to animate")
        return ""

    # Create individual panel clips, then concat
    with tempfile.TemporaryDirectory() as tmpdir:
        clip_paths = []

        for i, (filt, dur) in enumerate(zip(filter_parts, segment_durations)):
            clip_path = f"{tmpdir}/panel_{i:03d}.mp4"
            cmd = [
                "ffmpeg", "-y", "-loop", "1",
                "-i", page_image,
                "-vf", filt,
                "-t", str(dur),
                "-c:v", "libx264", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-r", "25",
                clip_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                clip_paths.append(clip_path)
            except subprocess.CalledProcessError as e:
                log.warning(f"FFmpeg error on panel {i}: {e.stderr[:200] if e.stderr else ''}")
                # Fallback: simple static frame
                cmd_simple = [
                    "ffmpeg", "-y", "-loop", "1",
                    "-i", page_image,
                    "-vf", f"crop={panels[i]['w']}:{panels[i]['h']}:{panels[i]['x']}:{panels[i]['y']},"
                           f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                           f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black",
                    "-t", str(dur),
                    "-c:v", "libx264", "-preset", "fast",
                    "-pix_fmt", "yuv420p", "-r", "25",
                    clip_path,
                ]
                try:
                    subprocess.run(cmd_simple, capture_output=True, timeout=30, check=True)
                    clip_paths.append(clip_path)
                except Exception:
                    log.warning(f"Panel {i} skipped entirely")

        if not clip_paths:
            return ""

        # Concat all panel clips
        concat_list = f"{tmpdir}/concat.txt"
        with open(concat_list, "w") as f:
            for cp in clip_paths:
                f.write(f"file '{cp}'\n")

        concat_cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        try:
            subprocess.run(concat_cmd, capture_output=True, timeout=60, check=True)
        except subprocess.CalledProcessError as e:
            log.error(f"Concat failed: {e.stderr[:300] if e.stderr else ''}")
            return ""

    return output_path


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def _process_manga_page(
    image_path: str,
    series_title: str,
    conn,
    output_dir: Path,
    languages: list[str] = None,
    reading_order: str = "rtl",
) -> dict:
    """Process a single manga page: detect panels, OCR, match quotes, generate video.

    Args:
        reading_order: 'rtl' for manga (Japanese), 'ltr' for manhwa/comics
    """
    import cv2

    page_name = Path(image_path).stem
    log.info(f"Processing page: {page_name}")

    # 1. Detect panels
    panels = _detect_panels(image_path)
    log.info(f"  Detected {len(panels)} panels")

    if reading_order == "ltr":
        # Re-sort left-to-right for manhwa/western comics
        rows = {}
        img = cv2.imread(image_path)
        h = img.shape[0]
        for p in panels:
            row_key = p["y"] // (h // 4)
            rows.setdefault(row_key, []).append(p)
        sorted_panels = []
        for key in sorted(rows.keys()):
            rows[key].sort(key=lambda p: p["x"])
            sorted_panels.extend(rows[key])
        panels = sorted_panels
        for i, p in enumerate(panels):
            p["index"] = i

    # 2. OCR each panel
    panel_texts = {}
    matched_panels = {}
    panel_dir = output_dir / "panels"
    panel_dir.mkdir(parents=True, exist_ok=True)

    for i, panel in enumerate(panels):
        panel_img_path = str(panel_dir / f"{page_name}_panel_{i:02d}.png")
        _extract_panel_image(image_path, panel, panel_img_path)

        ocr_blocks = _ocr_panel(panel_img_path, languages)
        panel_text = " ".join(b["text"] for b in ocr_blocks)
        panel_texts[i] = {
            "text": panel_text,
            "blocks": ocr_blocks,
            "panel": panel,
        }

        if panel_text and len(panel_text) >= 10:
            log.info(f"  Panel {i}: \"{panel_text[:60]}...\"")
            match = _match_ocr_to_quotes(panel_text, series_title, conn)
            if match:
                matched_panels[i] = match
                log.info(f"    MATCH [{match['match_score']}%]: {match['text'][:50]}")

    # 3. Generate Ken Burns video
    video_path = str(output_dir / f"{page_name}_short.mp4")
    result = _generate_ken_burns(
        image_path, panels, matched_panels, video_path,
    )

    # 4. Register each panel as a reusable clip in clip_library
    # Get series_id from manga_series
    series_id = None
    try:
        cur = conn.execute(
            "SELECT id FROM manga_series WHERE title LIKE ?",
            (f"%{series_title}%",),
        )
        row = cur.fetchone()
        if row:
            series_id = row["id"]
    except Exception:
        pass

    # Extract page number from filename (e.g., page_03 -> 3)
    import re
    page_num_match = re.search(r'(\d+)', page_name)
    page_num = int(page_num_match.group(1)) if page_num_match else None

    for i, panel in enumerate(panels):
        panel_img = str(panel_dir / f"{page_name}_panel_{i:02d}.png")
        ocr_text = panel_texts.get(i, {}).get("text", "")
        match = matched_panels.get(i)

        # Determine camera move for this panel
        is_match = i in matched_panels
        camera_move = _pick_camera_move(i, is_match, len(panels))

        clip_data = {
            "source_type": "manga_panel",
            "source_id": series_id,
            "quote_id": match["quote_id"] if match else None,
            "file_path": panel_img,
            "thumbnail_path": panel_img,
            "duration_s": 4.0 if match else 2.0,
            "quote_text": match["text"] if match else None,
            "character_name": match["character"] if match else None,
            "ocr_text": ocr_text if ocr_text else None,
            "title": f"{series_title} - {page_name} panel {i}",
            "description": json.dumps({
                "camera_move": camera_move,
                "has_quote_match": is_match,
                "match_score": match["match_score"] if match else 0,
                "ocr_preview": (ocr_text or "")[:100],
            }),
            "tags": json.dumps([series_title.lower(), "manga", match["category"] if match else "unknown", camera_move]),
            "category": match["category"] if match else None,
            "emotion": match.get("emotion") if match else None,
            "themes": json.dumps([series_title.lower()]),
            "page_number": page_num,
            "panel_index": i,
        }
        register_clip(conn, **clip_data)

    clip_count = len(panels)
    log.info(f"  Registered {clip_count} clips in clip_library")

    return {
        "page": page_name,
        "panels_detected": len(panels),
        "panels_with_text": sum(1 for t in panel_texts.values() if t["text"]),
        "matched_quotes": len(matched_panels),
        "matches": matched_panels,
        "video": result if result else None,
        "panel_texts": {k: v["text"] for k, v in panel_texts.items()},
        "clips_registered": clip_count,
    }


def _load_pages_from_source(source: str) -> list[str]:
    """Load manga page images from file, folder, or CBZ/CBR.

    Supports:
    - Single image: .jpg/.png/.webp
    - Folder of images
    - CBZ (ZIP of images)
    - CBR (RAR of images, requires unrar)
    """
    source_path = Path(source)

    if source_path.is_file():
        suffix = source_path.suffix.lower()

        if suffix in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            return [str(source_path)]

        elif suffix == ".cbz":
            import zipfile
            extract_dir = source_path.parent / source_path.stem
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(source_path) as zf:
                zf.extractall(extract_dir)
            return sorted(
                str(f) for f in extract_dir.rglob("*")
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            )

        elif suffix == ".cbr":
            try:
                import rarfile
                extract_dir = source_path.parent / source_path.stem
                extract_dir.mkdir(exist_ok=True)
                with rarfile.RarFile(source_path) as rf:
                    rf.extractall(extract_dir)
                return sorted(
                    str(f) for f in extract_dir.rglob("*")
                    if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                )
            except ImportError:
                log.error("CBR requires 'rarfile' package: pip install rarfile")
                return []

    elif source_path.is_dir():
        return sorted(
            str(f) for f in source_path.rglob("*")
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        )

    log.error(f"Source not found: {source}")
    return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    source: str = "",
    series_title: str = "",
    max_pages: int = 5,
    languages: str = "en",
    reading_order: str = "rtl",
) -> str:
    """Process manga pages: detect panels, OCR, match quotes, generate Short.

    Args:
        source: Path to image, folder, or CBZ/CBR file
        series_title: Manga/anime title for quote matching
        max_pages: Max pages to process
        languages: OCR languages comma-separated (en, ja, ko, zh)
        reading_order: rtl (manga) or ltr (manhwa/comics)
    """
    if not source:
        log.error("No source provided. Use --source path/to/manga/page.jpg")
        return ""

    data_dir = Path(settings.data_dir)
    conn = get_db(data_dir)

    # Verify manga tables exist
    try:
        conn.execute("SELECT 1 FROM manga_quotes LIMIT 1")
    except Exception:
        log.warning("manga_quotes table not found. Run ex36 first for quote matching.")

    lang_list = [l.strip() for l in languages.split(",")]
    pages = _load_pages_from_source(source)
    if not pages:
        log.error(f"No images found in: {source}")
        return ""

    pages = pages[:max_pages]
    log.info(f"Processing {len(pages)} pages from: {source}")
    log.info(f"  Series: {series_title or 'unknown'}")
    log.info(f"  Languages: {lang_list} | Reading order: {reading_order}")

    output_dir = Path(settings.output_dir) / "manga" / f"{series_title or 'unknown'}_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for page_path in pages:
        result = _process_manga_page(
            page_path, series_title, conn, output_dir, lang_list, reading_order,
        )
        results.append(result)

    # Report
    report_path = output_dir / "ex38_report.txt"
    lines = [
        "ex38 - Manga Panel Detection + OCR Report",
        "=" * 50,
        f"Source: {source}",
        f"Series: {series_title}",
        f"Pages processed: {len(results)}",
        f"Reading order: {reading_order}",
        f"OCR languages: {lang_list}",
        "",
    ]
    total_panels = 0
    total_text = 0
    total_matches = 0
    videos = []

    for r in results:
        total_panels += r["panels_detected"]
        total_text += r["panels_with_text"]
        total_matches += r["matched_quotes"]
        if r.get("video"):
            videos.append(r["video"])

        lines.append(f"Page: {r['page']}")
        lines.append(f"  Panels: {r['panels_detected']} | With text: {r['panels_with_text']} | Matches: {r['matched_quotes']}")
        for idx, match in r.get("matches", {}).items():
            lines.append(f"  Panel {idx}: [{match['match_score']}%] {match['character']}: {match['text'][:50]}")
        lines.append("")

    lines.extend([
        "Summary:",
        f"  Total panels: {total_panels}",
        f"  Panels with text: {total_text}",
        f"  Quote matches: {total_matches}",
        f"  Videos generated: {len(videos)}",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Report: {report_path}")
    log.info(f"Total: {total_panels} panels, {total_text} with text, {total_matches} matches, {len(videos)} videos")

    return str(report_path)
