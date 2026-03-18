"""
ex16 - Edicion automatizada con Shotcut (gratis, open source) via MLT XML.

Shotcut usa el formato MLT XML para sus proyectos. Este ejercicio genera
un archivo .mlt que Shotcut puede abrir directamente con:
  - Timeline multitrack 1080x1920 30fps (vertical)
  - Clips importados y posicionados
  - Transiciones (dissolve, cut)
  - Filtros de color (brightness, contrast, saturation)
  - Subtitulos quemados (filtro text:simple)
  - Listo para renderizar desde Shotcut (Export > MP4)

Tambien se puede renderizar por CLI sin abrir Shotcut:
  melt proyecto.mlt -consumer avformat:output.mp4 vcodec=libx264 acodec=aac

Flujo:
  ex07/ex09 genera manifest → ex16 genera .mlt → abrir en Shotcut o render por CLI

Uso:
  python src/main.py ex16 --query "villain monologue"
  python src/main.py ex16 --query "villain" --template villain
  python src/main.py ex16 --query "romance" --template romance --render-cli
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ── Color/style templates ────────────────────────────────────────────

SHOTCUT_TEMPLATES = {
    "villain": {
        "brightness": -0.05,
        "contrast": 1.3,
        "saturation": 70,        # 0-200, 100=normal
        "transition": "luma",
        "transition_duration_frames": 5,
        "text_color": "#FFFFFF",
        "text_outline_color": "#FF0000",
        "text_size": 72,
    },
    "romance": {
        "brightness": 0.05,
        "contrast": 1.1,
        "saturation": 120,
        "transition": "dissolve",
        "transition_duration_frames": 15,
        "text_color": "#FFFFFF",
        "text_outline_color": "#000000",
        "text_size": 60,
    },
    "motivational": {
        "brightness": 0.0,
        "contrast": 1.4,
        "saturation": 130,
        "transition": "luma",
        "transition_duration_frames": 3,
        "text_color": "#FFFFFF",
        "text_outline_color": "#000000",
        "text_size": 80,
    },
    "comedy": {
        "brightness": 0.05,
        "contrast": 1.2,
        "saturation": 140,
        "transition": "luma",
        "transition_duration_frames": 2,
        "text_color": "#FFFF00",
        "text_outline_color": "#000000",
        "text_size": 70,
    },
    "action": {
        "brightness": -0.03,
        "contrast": 1.5,
        "saturation": 90,
        "transition": "luma",
        "transition_duration_frames": 2,
        "text_color": "#FFFFFF",
        "text_outline_color": "#FF0000",
        "text_size": 74,
    },
    "dramatic": {
        "brightness": -0.02,
        "contrast": 1.3,
        "saturation": 80,
        "transition": "dissolve",
        "transition_duration_frames": 20,
        "text_color": "#FFFFFF",
        "text_outline_color": "#000000",
        "text_size": 60,
    },
    "horror": {
        "brightness": -0.1,
        "contrast": 1.4,
        "saturation": 50,
        "transition": "luma",
        "transition_duration_frames": 3,
        "text_color": "#FF3333",
        "text_outline_color": "#000000",
        "text_size": 64,
    },
}


# ── MLT XML Generation ──────────────────────────────────────────────


def _ms_to_mlt_time(ms: int, fps: int = 30) -> str:
    """Convert milliseconds to MLT timecode HH:MM:SS.mmm"""
    total_s = ms / 1000.0
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _frames_to_mlt_time(frames: int, fps: int = 30) -> str:
    """Convert frame count to MLT timecode."""
    total_s = frames / fps
    return _ms_to_mlt_time(int(total_s * 1000), fps)


def generate_mlt_project(
    clips: list[dict],
    theme: str,
    template_name: str,
    video_dir: Path,
    output_path: Path,
    fps: int = 30,
) -> Path:
    """
    Generate a Shotcut-compatible MLT XML project file.

    Structure:
      <mlt>
        <profile />                    -- 1080x1920 30fps
        <producer id="clip_0" />       -- Each video clip
        <producer id="clip_1" />
        <playlist id="main">           -- Main timeline
          <entry producer="clip_0" />   -- With in/out points
          <entry producer="clip_1" />
        </playlist>
        <tractor id="tractor0">        -- Master output
          <multitrack>
            <track producer="main" />
          </multitrack>
        </tractor>
      </mlt>
    """
    tpl = SHOTCUT_TEMPLATES.get(template_name, SHOTCUT_TEMPLATES["dramatic"])

    mlt = ET.Element("mlt", {
        "LC_NUMERIC": "C",
        "version": "7.21.0",
        "title": f"Short: {theme}",
        "producer": "main_bin",
    })

    # Profile: vertical 1080x1920
    ET.SubElement(mlt, "profile", {
        "description": "vertical_1080x1920_30",
        "width": "1080",
        "height": "1920",
        "progressive": "1",
        "sample_aspect_num": "1",
        "sample_aspect_den": "1",
        "display_aspect_num": "9",
        "display_aspect_den": "16",
        "frame_rate_num": str(fps),
        "frame_rate_den": "1",
        "colorspace": "709",
    })

    # Producers (one per clip)
    producer_ids = []
    for i, clip in enumerate(clips):
        movie_title = clip.get("movie_title", f"clip_{i}")
        safe_movie = re.sub(r"[^a-zA-Z0-9_-]+", "_", movie_title)[:30]

        # Look for actual video files in work directory
        video_file = None
        for pattern in [f"clip_{i:02d}_{safe_movie}_norm.mp4",
                        f"clip_{i:02d}_{safe_movie}_cut.mp4",
                        f"clip_{i:02d}_{safe_movie}_raw.mp4"]:
            candidate = video_dir / pattern
            if candidate.exists():
                video_file = candidate
                break

        # Use placeholder if no video found yet
        resource = str(video_file).replace("\\", "/") if video_file else f"PLACEHOLDER_{movie_title}.mp4"

        start_ms = clip.get("start_ms", 0)
        end_ms = clip.get("end_ms", 0)
        duration_ms = end_ms - start_ms
        duration_frames = max(1, int((duration_ms / 1000.0) * fps))

        prod_id = f"producer_{i}"
        producer_ids.append(prod_id)

        producer = ET.SubElement(mlt, "producer", {
            "id": prod_id,
            "in": "00:00:00.000",
            "out": _ms_to_mlt_time(duration_ms),
        })
        _add_property(producer, "resource", resource)
        _add_property(producer, "mlt_service", "avformat-novalidate")
        _add_property(producer, "shotcut:caption", f"{movie_title}: {clip.get('quote', '')[:50]}")
        _add_property(producer, "shotcut:detail", clip.get("quote", clip.get("text", "")))
        _add_property(producer, "video_delay", "0")
        _add_property(producer, "length", str(duration_frames))

        # Color grading filter
        filt_color = ET.SubElement(producer, "filter", {
            "id": f"filter_color_{i}",
            "mlt_service": "brightness",
        })
        _add_property(filt_color, "mlt_service", "brightness")
        _add_property(filt_color, "level", str(1.0 + tpl["brightness"]))

        filt_contrast = ET.SubElement(producer, "filter", {
            "id": f"filter_contrast_{i}",
        })
        _add_property(filt_contrast, "mlt_service", "avfilter.eq")
        _add_property(filt_contrast, "av.contrast", str(tpl["contrast"]))
        _add_property(filt_contrast, "av.saturation", str(tpl["saturation"] / 100.0))

        # Subtitle filter (text overlay)
        quote_text = clip.get("quote", clip.get("text", ""))
        if quote_text:
            filt_text = ET.SubElement(producer, "filter", {
                "id": f"filter_text_{i}",
            })
            _add_property(filt_text, "mlt_service", "dynamictext")
            _add_property(filt_text, "argument", quote_text[:120])
            _add_property(filt_text, "geometry", f"50 1440 980 300 1")  # x y w h opacity
            _add_property(filt_text, "family", "Arial")
            _add_property(filt_text, "size", str(tpl["text_size"]))
            _add_property(filt_text, "fgcolour", tpl["text_color"])
            _add_property(filt_text, "olcolour", tpl["text_outline_color"])
            _add_property(filt_text, "outline", "3")
            _add_property(filt_text, "halign", "center")
            _add_property(filt_text, "valign", "bottom")

    # Main playlist (timeline)
    playlist = ET.SubElement(mlt, "playlist", {"id": "main"})
    _add_property(playlist, "shotcut:video", "1")
    _add_property(playlist, "shotcut:name", f"Timeline: {theme}")

    for i, prod_id in enumerate(producer_ids):
        clip = clips[i]
        duration_ms = clip.get("end_ms", 0) - clip.get("start_ms", 0)

        entry_attrs = {
            "producer": prod_id,
            "in": "00:00:00.000",
            "out": _ms_to_mlt_time(duration_ms),
        }
        ET.SubElement(playlist, "entry", entry_attrs)

    # Background track (black)
    bg_producer = ET.SubElement(mlt, "producer", {"id": "black"})
    _add_property(bg_producer, "mlt_service", "color")
    _add_property(bg_producer, "resource", "black")
    _add_property(bg_producer, "length", "2147483647")

    bg_playlist = ET.SubElement(mlt, "playlist", {"id": "background"})
    ET.SubElement(bg_playlist, "entry", {
        "producer": "black",
        "in": "00:00:00.000",
        "out": "01:00:00.000",
    })

    # Tractor (master output)
    tractor = ET.SubElement(mlt, "tractor", {
        "id": "tractor0",
        "title": f"Short: {theme}",
    })
    _add_property(tractor, "shotcut", "1")
    _add_property(tractor, "shotcut:projectAudioChannels", "2")
    _add_property(tractor, "shotcut:projectFolder", str(video_dir).replace("\\", "/"))

    multitrack = ET.SubElement(tractor, "multitrack")
    ET.SubElement(multitrack, "track", {"producer": "background"})
    ET.SubElement(multitrack, "track", {"producer": "main"})

    # Transition between background and main
    transition = ET.SubElement(tractor, "transition", {"id": "transition0"})
    _add_property(transition, "mlt_service", "mix")
    _add_property(transition, "a_track", "0")
    _add_property(transition, "b_track", "1")
    _add_property(transition, "always_active", "1")
    _add_property(transition, "sum", "1")

    transition_v = ET.SubElement(tractor, "transition", {"id": "transition1"})
    _add_property(transition_v, "mlt_service", "frei0r.cairoblend")
    _add_property(transition_v, "a_track", "0")
    _add_property(transition_v, "b_track", "1")
    _add_property(transition_v, "disable", "0")

    # Write XML
    rough = ET.tostring(mlt, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")

    output_path.write_bytes(pretty)
    return output_path


def _add_property(parent: ET.Element, name: str, value: str) -> ET.Element:
    prop = ET.SubElement(parent, "property", {"name": name})
    prop.text = value
    return prop


# ── CLI Render ───────────────────────────────────────────────────────


def _render_with_melt(mlt_path: Path, output_path: Path, log) -> bool:
    """
    Render MLT project using melt CLI (comes with Shotcut or MLT framework).

    melt is the command-line renderer for MLT projects.
    On Windows with Shotcut installed: C:\\Program Files\\Shotcut\\melt.exe
    """
    melt_cmd = shutil.which("melt")
    if not melt_cmd:
        # Try common Shotcut install locations
        for candidate in [
            "C:/Program Files/Shotcut/melt.exe",
            "C:/Program Files (x86)/Shotcut/melt.exe",
        ]:
            if Path(candidate).exists():
                melt_cmd = candidate
                break

    if not melt_cmd:
        log.warning("melt not found. Install Shotcut or add melt to PATH.")
        log.warning("Download Shotcut from: https://shotcut.org")
        return False

    cmd = [
        melt_cmd,
        str(mlt_path),
        "-consumer", f"avformat:{output_path}",
        "vcodec=libx264",
        "acodec=aac",
        "width=1080",
        "height=1920",
        "frame_rate_num=30",
        "progressive=1",
        "b=8000000",      # 8Mbps video bitrate
        "ab=192000",      # 192kbps audio
        "movflags=+faststart",
    ]

    try:
        log.info(f"Rendering with melt: {output_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and output_path.exists():
            log.info(f"Render complete: {output_path}")
            return True
        log.warning(f"melt render failed: {result.stderr[:300]}")
    except subprocess.TimeoutExpired:
        log.warning("melt render timed out (5 min)")
    except Exception as e:
        log.warning(f"melt error: {e}")
    return False


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    query: str = "epic movie moment",
    template: str = "auto",
    render_cli: bool = False,
) -> Path:
    log = build_logger("ex16", settings.output_dir / "logs" / "ex16.log")
    conn = get_db(settings.data_dir)

    # Load manifest
    manifests_dir = settings.output_dir / "manifests"
    manifest = None
    if manifests_dir.exists():
        candidates = sorted(manifests_dir.glob("short_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if query:
            safe_q = query.replace(" ", "_").lower()
            for c in candidates:
                if safe_q in c.stem.lower():
                    manifest = json.loads(c.read_text(encoding="utf-8"))
                    break
        if not manifest and candidates:
            manifest = json.loads(candidates[0].read_text(encoding="utf-8"))

    if not manifest or not manifest.get("clips"):
        msg = "No manifest found. Run ex07 first."
        log.error(msg)
        rp = settings.output_dir / "logs" / "ex16_shotcut_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(f"ex16 - ERROR: {msg}\n", encoding="utf-8")
        conn.close()
        return rp

    clips = manifest["clips"]
    theme = manifest.get("theme", query)
    safe_theme = re.sub(r"[^a-zA-Z0-9_-]+", "_", theme)[:40]

    # Auto-detect template
    if template == "auto":
        from exercises.ex14_davinci_edit import _detect_template
        template_name = _detect_template(clips, conn)
        log.info(f"Auto-detected template: {template_name}")
    else:
        template_name = template if template in SHOTCUT_TEMPLATES else "dramatic"

    # Video directory (where ex11 puts clips)
    video_dir = settings.output_dir / "video" / f"work_{safe_theme}"
    video_dir.mkdir(parents=True, exist_ok=True)

    # Generate MLT project
    shotcut_dir = settings.output_dir / "shotcut"
    shotcut_dir.mkdir(parents=True, exist_ok=True)
    mlt_path = shotcut_dir / f"short_{safe_theme}.mlt"

    generate_mlt_project(clips, theme, template_name, video_dir, mlt_path)
    log.info(f"Shotcut project: {mlt_path}")

    # Optionally render via CLI
    rendered = False
    final_path = None
    if render_cli:
        final_dir = settings.output_dir / "video" / "finals"
        final_dir.mkdir(parents=True, exist_ok=True)
        final_path = final_dir / f"short_{safe_theme}_shotcut.mp4"
        rendered = _render_with_melt(mlt_path, final_path, log)

    # Report
    tpl = SHOTCUT_TEMPLATES[template_name]
    report_lines = [
        "ex16 - Shotcut Edit Report",
        "=" * 50,
        f"Theme: {theme}",
        f"Template: {template_name}",
        f"Clips: {len(clips)}",
        f"Contrast: {tpl['contrast']} | Saturation: {tpl['saturation']}%",
        f"Transition: {tpl['transition']} ({tpl['transition_duration_frames']} frames)",
        "",
        f"Shotcut project: {mlt_path}",
        "",
    ]

    if rendered and final_path:
        report_lines.append(f"Rendered: {final_path}")
    else:
        report_lines.append("HOW TO USE:")
        report_lines.append("-" * 40)
        report_lines.append("")
        report_lines.append("Option A: Open in Shotcut (GUI)")
        report_lines.append(f"  1. Open Shotcut")
        report_lines.append(f"  2. File > Open > {mlt_path}")
        report_lines.append(f"  3. Review/adjust the timeline")
        report_lines.append(f"  4. Export > MP4 H.264 (1080x1920)")
        report_lines.append("")
        report_lines.append("Option B: Render via CLI (no GUI needed)")
        report_lines.append(f"  melt \"{mlt_path}\" -consumer avformat:output.mp4 vcodec=libx264 acodec=aac width=1080 height=1920")
        report_lines.append("")
        report_lines.append("Option C: Re-run with --render-cli flag")
        report_lines.append(f"  python src/main.py ex16 --query \"{query}\" --render-cli")

    report_lines.append("")
    report_lines.append("CLIPS:")
    for i, clip in enumerate(clips):
        dur = (clip.get("end_ms", 0) - clip.get("start_ms", 0)) / 1000
        report_lines.append(f"  {i+1}. {clip.get('movie_title', '')} ({dur:.1f}s)")
        report_lines.append(f"     \"{clip.get('quote', clip.get('text', ''))[:80]}\"")

    report_path = settings.output_dir / "logs" / "ex16_shotcut_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report: {report_path}")

    conn.close()
    return report_path
