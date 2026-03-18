"""
ex14 - Edicion automatizada con DaVinci Resolve via Scripting API.

Flujo:
  1. Lee manifest (ex07) o curation (ex09) con clips seleccionados
  2. Genera un proyecto de DaVinci Resolve con el tema como nombre
  3. Crea timeline 1080x1920 30fps (Short vertical)
  4. Importa los clips al media pool
  5. Aplica template de edicion segun la categoria del tema
  6. Agrega subtitulos via Fusion (texto quemado)
  7. Aplica color grading segun emocion/categoria
  8. Renderiza a MP4 listo para subir

Templates de edicion por tipo de video:
  - villain:      cortes rapidos, tono oscuro, zoom in en rostro
  - romance:      transiciones suaves (dissolve), tonos calidos
  - motivational: cortes al ritmo, texto grande, alto contraste
  - comedy:       jump cuts, zooms exagerados, colores saturados
  - action:       cortes ultra rapidos (<1s), speed ramp
  - dramatic:     slow motion, vignette, tonos desaturados
  - horror:       flashes, glitch, tonos frios

Requisitos:
  - DaVinci Resolve Studio (la version gratis NO soporta scripting)
  - DaVinci Resolve abierto y corriendo
  - MCP server de DaVinci configurado en Claude Code
  - O Python con acceso al modulo DaVinciResolveScript

Uso:
  python src/main.py ex14 --query "villain monologue"
  python src/main.py ex14 --query "villain" --template villain
  python src/main.py ex14 --query "romance" --template romance --render
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ── Edit templates by category ───────────────────────────────────────


EDIT_TEMPLATES = {
    "villain": {
        "name": "Villain / Dark",
        "transition_type": "CUT",
        "transition_duration_frames": 0,
        "color_grade": {
            "contrast": 1.3,
            "saturation": 0.7,
            "temperature": -15,    # Cooler (blue tint)
            "tint": -5,
            "lift": {"r": 0.0, "g": 0.0, "b": 0.05},
            "gamma": {"r": 1.0, "g": 0.95, "b": 1.0},
            "gain": {"r": 0.9, "g": 0.9, "b": 1.0},
        },
        "effects": ["vignette_heavy", "film_grain_light"],
        "text_style": {
            "font": "Arial Black",
            "size": 0.06,          # Relative to frame height
            "color": "white",
            "outline_color": "red",
            "outline_width": 3,
            "position": "bottom_quarter",
            "animation": "fade_in",
        },
        "pacing": "fast",          # Cut rhythm
        "zoom": "slow_push_in",    # Ken Burns style
    },
    "romance": {
        "name": "Romance / Warm",
        "transition_type": "DISSOLVE",
        "transition_duration_frames": 15,
        "color_grade": {
            "contrast": 1.1,
            "saturation": 1.1,
            "temperature": 20,     # Warmer (orange tint)
            "tint": 5,
            "lift": {"r": 0.02, "g": 0.0, "b": 0.0},
            "gamma": {"r": 1.05, "g": 1.0, "b": 0.95},
            "gain": {"r": 1.1, "g": 1.0, "b": 0.9},
        },
        "effects": ["soft_glow", "vignette_light"],
        "text_style": {
            "font": "Georgia",
            "size": 0.05,
            "color": "white",
            "outline_color": "black",
            "outline_width": 2,
            "position": "bottom_third",
            "animation": "typewriter",
        },
        "pacing": "slow",
        "zoom": "none",
    },
    "motivational": {
        "name": "Motivational / Bold",
        "transition_type": "CUT",
        "transition_duration_frames": 0,
        "color_grade": {
            "contrast": 1.4,
            "saturation": 1.2,
            "temperature": 5,
            "tint": 0,
            "lift": {"r": 0.0, "g": 0.0, "b": 0.0},
            "gamma": {"r": 1.0, "g": 1.0, "b": 1.0},
            "gain": {"r": 1.0, "g": 1.0, "b": 1.0},
        },
        "effects": ["sharpening"],
        "text_style": {
            "font": "Impact",
            "size": 0.08,
            "color": "white",
            "outline_color": "black",
            "outline_width": 4,
            "position": "center",
            "animation": "scale_pop",
        },
        "pacing": "rhythmic",
        "zoom": "punch_in",
    },
    "comedy": {
        "name": "Comedy / Fun",
        "transition_type": "CUT",
        "transition_duration_frames": 0,
        "color_grade": {
            "contrast": 1.2,
            "saturation": 1.3,
            "temperature": 10,
            "tint": 0,
            "lift": {"r": 0.0, "g": 0.0, "b": 0.0},
            "gamma": {"r": 1.0, "g": 1.0, "b": 1.0},
            "gain": {"r": 1.0, "g": 1.0, "b": 1.0},
        },
        "effects": [],
        "text_style": {
            "font": "Comic Sans MS",
            "size": 0.06,
            "color": "yellow",
            "outline_color": "black",
            "outline_width": 3,
            "position": "bottom_quarter",
            "animation": "bounce",
        },
        "pacing": "jump_cut",
        "zoom": "snap_zoom",
    },
    "action": {
        "name": "Action / Intense",
        "transition_type": "CUT",
        "transition_duration_frames": 0,
        "color_grade": {
            "contrast": 1.5,
            "saturation": 0.9,
            "temperature": -5,
            "tint": 0,
            "lift": {"r": 0.0, "g": 0.0, "b": 0.02},
            "gamma": {"r": 1.0, "g": 0.98, "b": 1.0},
            "gain": {"r": 0.95, "g": 0.95, "b": 1.0},
        },
        "effects": ["sharpening", "film_grain_heavy"],
        "text_style": {
            "font": "Arial Black",
            "size": 0.07,
            "color": "white",
            "outline_color": "red",
            "outline_width": 4,
            "position": "bottom_quarter",
            "animation": "slam",
        },
        "pacing": "ultra_fast",
        "zoom": "speed_ramp",
    },
    "dramatic": {
        "name": "Dramatic / Cinematic",
        "transition_type": "DISSOLVE",
        "transition_duration_frames": 20,
        "color_grade": {
            "contrast": 1.3,
            "saturation": 0.8,
            "temperature": -5,
            "tint": 0,
            "lift": {"r": 0.0, "g": 0.0, "b": 0.02},
            "gamma": {"r": 0.98, "g": 0.98, "b": 1.0},
            "gain": {"r": 0.95, "g": 0.95, "b": 1.0},
        },
        "effects": ["vignette_heavy", "letterbox"],
        "text_style": {
            "font": "Times New Roman",
            "size": 0.05,
            "color": "white",
            "outline_color": "black",
            "outline_width": 2,
            "position": "bottom_third",
            "animation": "fade_in",
        },
        "pacing": "slow",
        "zoom": "slow_push_in",
    },
    "horror": {
        "name": "Horror / Dark",
        "transition_type": "CUT",
        "transition_duration_frames": 0,
        "color_grade": {
            "contrast": 1.4,
            "saturation": 0.5,
            "temperature": -25,
            "tint": -10,
            "lift": {"r": 0.0, "g": 0.02, "b": 0.05},
            "gamma": {"r": 0.9, "g": 0.95, "b": 1.0},
            "gain": {"r": 0.8, "g": 0.85, "b": 1.0},
        },
        "effects": ["vignette_heavy", "film_grain_heavy", "glitch_subtle"],
        "text_style": {
            "font": "Courier New",
            "size": 0.05,
            "color": "red",
            "outline_color": "black",
            "outline_width": 3,
            "position": "bottom_quarter",
            "animation": "glitch",
        },
        "pacing": "suspense",
        "zoom": "slow_creep",
    },
}


# ── Detect dominant category from manifest/curation ──────────────────


def _detect_template(clips: list[dict], conn) -> str:
    """Auto-detect the best template based on classified quotes."""
    from collections import Counter

    categories = Counter()
    for clip in clips:
        # Try to get category from clip metadata
        cat = clip.get("category", "")
        if not cat:
            # Fallback: look it up in DB
            movie_id = clip.get("movie_id", 0)
            text = clip.get("quote", clip.get("text", ""))
            if movie_id and text:
                cur = conn.execute(
                    "SELECT category FROM quotes WHERE movie_id = ? AND text LIKE ? AND category IS NOT NULL LIMIT 1",
                    (movie_id, f"%{text[:50]}%"),
                )
                row = cur.fetchone()
                if row:
                    cat = row["category"]

        if cat and cat in EDIT_TEMPLATES:
            categories[cat] += 1

    if categories:
        return categories.most_common(1)[0][0]
    return "dramatic"  # Default


# ── Generate DaVinci project spec ────────────────────────────────────


def _generate_davinci_spec(
    clips: list[dict],
    theme: str,
    template_name: str,
    output_dir: Path,
) -> Path:
    """
    Generate a JSON spec that the DaVinci MCP server or manual script can consume.

    This is the bridge between our pipeline and DaVinci Resolve.
    """
    template = EDIT_TEMPLATES.get(template_name, EDIT_TEMPLATES["dramatic"])

    spec = {
        "project": {
            "name": f"Short_{theme}",
            "timeline_name": f"TL_{theme}",
            "resolution": {"width": 1080, "height": 1920},
            "fps": 30,
            "color_science": "DaVinci YRGB Color Managed",
        },
        "template": {
            "name": template["name"],
            "category": template_name,
            **template,
        },
        "clips": [],
        "render": {
            "format": "MP4",
            "codec": "H.264",
            "quality": "Best",
            "resolution": "1080x1920",
            "fps": 30,
            "audio_codec": "AAC",
            "audio_bitrate": "192",
            "filename": f"short_{theme}.mp4",
        },
        "davinci_instructions": _generate_davinci_prompt(clips, theme, template_name, template),
    }

    for i, clip in enumerate(clips):
        spec["clips"].append({
            "index": i,
            "movie_title": clip.get("movie_title", ""),
            "quote": clip.get("quote", clip.get("text", "")),
            "character": clip.get("character", ""),
            "start_ms": clip.get("start_ms", 0),
            "end_ms": clip.get("end_ms", 0),
            "duration_s": round((clip.get("end_ms", 0) - clip.get("start_ms", 0)) / 1000, 2),
            "source_note": f"Search YouTube: {clip.get('movie_title', '')} scene {clip.get('quote', '')[:30]}",
            "edit_style": clip.get("edit_style", template.get("zoom", "")),
            "subtitle_text": clip.get("quote", clip.get("text", "")),
        })

    safe_theme = re.sub(r"[^a-zA-Z0-9_-]+", "_", theme)[:40]
    spec_path = output_dir / f"ex14_davinci_spec_{safe_theme}.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    return spec_path


def _generate_davinci_prompt(clips: list[dict], theme: str, template_name: str, template: dict) -> str:
    """
    Generate the natural language prompt for the DaVinci MCP server.

    This is what Claude sends to DaVinci Resolve via MCP to automate the edit.
    """
    clip_descriptions = []
    for i, clip in enumerate(clips):
        clip_descriptions.append(
            f"  Clip {i+1}: \"{clip.get('quote', clip.get('text', ''))[:80]}\" "
            f"from {clip.get('movie_title', 'Unknown')} "
            f"({clip.get('start_ms', 0)/1000:.1f}s - {clip.get('end_ms', 0)/1000:.1f}s)"
        )

    clips_text = "\n".join(clip_descriptions)

    color = template.get("color_grade", {})
    text_style = template.get("text_style", {})

    prompt = f"""Create a YouTube Short / TikTok video project in DaVinci Resolve:

PROJECT SETUP:
- Project name: "Short_{theme}"
- Timeline: 1080x1920 (vertical 9:16), 30fps
- Color science: DaVinci YRGB Color Managed

CLIPS TO IMPORT (search and download these, then import to Media Pool):
{clips_text}

EDITING TEMPLATE: {template['name']}
- Transitions: {template['transition_type']} ({template['transition_duration_frames']} frames)
- Pacing: {template['pacing']}
- Zoom style: {template.get('zoom', 'none')}

COLOR GRADING (apply to all clips on Color page):
- Contrast: {color.get('contrast', 1.0)}
- Saturation: {color.get('saturation', 1.0)}
- Temperature: {color.get('temperature', 0)}
- Lift RGB: {color.get('lift', {})}
- Gamma RGB: {color.get('gamma', {})}
- Gain RGB: {color.get('gain', {})}

SUBTITLES (add via Fusion page - Text+ node):
- Font: {text_style.get('font', 'Arial')}
- Size: {text_style.get('size', 0.05)} (relative to frame height)
- Color: {text_style.get('color', 'white')} with {text_style.get('outline_color', 'black')} outline ({text_style.get('outline_width', 2)}px)
- Position: {text_style.get('position', 'bottom_third')}
- Animation: {text_style.get('animation', 'fade_in')}
- Each clip gets its own subtitle with the quote text

EFFECTS: {', '.join(template.get('effects', ['none']))}

RENDER:
- Format: MP4 (H.264 + AAC)
- Resolution: 1080x1920
- Frame rate: 30fps
- Quality: Best
- Audio: AAC 192kbps
- Output: short_{theme}.mp4

IMPORTANT:
- Total duration must be under 60 seconds
- First clip should have a strong hook (first 2 seconds visible)
- Audio from original clips should be preserved
- Do NOT add background music (that is selected on the platform when uploading)
"""
    return prompt


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    query: str = "epic movie moment",
    template: str = "auto",
    do_render: bool = False,
) -> Path:
    log = build_logger("ex14", settings.output_dir / "logs" / "ex14.log")
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
        rp = settings.output_dir / "logs" / "ex14_davinci_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(f"ex14 - ERROR: {msg}\n", encoding="utf-8")
        conn.close()
        return rp

    clips = manifest["clips"]
    theme = manifest.get("theme", query)

    # Detect or use specified template
    if template == "auto":
        template_name = _detect_template(clips, conn)
        log.info(f"Auto-detected template: {template_name}")
    else:
        template_name = template if template in EDIT_TEMPLATES else "dramatic"
        log.info(f"Using template: {template_name}")

    # Generate DaVinci spec
    davinci_dir = settings.output_dir / "davinci"
    davinci_dir.mkdir(parents=True, exist_ok=True)

    spec_path = _generate_davinci_spec(clips, theme, template_name, davinci_dir)
    log.info(f"DaVinci spec: {spec_path}")

    # Generate report
    tpl = EDIT_TEMPLATES[template_name]
    report_lines = [
        "ex14 - DaVinci Resolve Edit Spec",
        "=" * 50,
        f"Theme: {theme}",
        f"Template: {tpl['name']} ({template_name})",
        f"Clips: {len(clips)}",
        f"Transition: {tpl['transition_type']} ({tpl['transition_duration_frames']} frames)",
        f"Pacing: {tpl['pacing']}",
        f"Effects: {', '.join(tpl.get('effects', ['none']))}",
        "",
        "Clips:",
    ]

    for i, clip in enumerate(clips):
        dur = (clip.get("end_ms", 0) - clip.get("start_ms", 0)) / 1000
        report_lines.append(
            f"  {i+1}. {clip.get('movie_title', '')} ({dur:.1f}s)"
        )
        report_lines.append(f"     \"{clip.get('quote', clip.get('text', ''))[:80]}\"")

    report_lines.append("")
    report_lines.append(f"Spec JSON: {spec_path}")
    report_lines.append("")

    report_lines.append("HOW TO USE:")
    report_lines.append("-" * 40)
    report_lines.append("")
    report_lines.append("Option A: DaVinci MCP Server (automated)")
    report_lines.append("  1. Open DaVinci Resolve Studio")
    report_lines.append("  2. In Claude Code, the MCP server connects automatically")
    report_lines.append("  3. The davinci_instructions field in the spec JSON")
    report_lines.append("     contains the full prompt for Claude to execute")
    report_lines.append("")
    report_lines.append("Option B: Manual in DaVinci Resolve (free version)")
    report_lines.append("  1. Open DaVinci Resolve > New Project")
    report_lines.append("  2. Project Settings > 1080x1920, 30fps")
    report_lines.append("  3. Import clips listed above")
    report_lines.append("  4. Apply color grade values from spec")
    report_lines.append("  5. Add subtitles via Fusion > Text+")
    report_lines.append("  6. Deliver > MP4 H.264, 1080x1920")
    report_lines.append("")
    report_lines.append("Option C: FFmpeg automated (ex11)")
    report_lines.append("  Run: python src/main.py ex11 --query \"" + query + "\" --burn-subs")

    report_path = settings.output_dir / "logs" / "ex14_davinci_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report: {report_path}")

    conn.close()
    return report_path
