"""Render de una lección a un Short vertical 1080x1920 (generaliza scripts/web/make_demo_lesson.py).

Por tramo (UNA sola recodificación de video):
    extract_segment (stream copy por rango, caché)  →  corte exacto al frame (semántica de
    fetch.cut_exact: -ss relativo al start_time del mezzanine) + en el mismo ffmpeg:
      - fondo desenfocado (la misma toma escalada) y la toma completa encima
      - rótulo del tema arriba, gancho en el primer tramo, texto en pantalla abajo
        (UNA drawtext por línea: ffmpeg 8 dibuja el '\\n' como glifo)
      - lower-third "Título (año)"
      - narración opcional (tts) con ducking del audio original (sidechaincompress)
    → seg_NN.mkv  (h264 + PCM: el audio se codifica una sola vez, al final)

Tarjeta final: "Pausa. Respira lento." (4 s), con el cierre del guion.
Final: concat (video copy) + loudnorm a −14 LUFS en dos pasadas + AAC + faststart,
sin capítulos ni metadatos del MKV de Internet Archive (-map_chapters -1).
Todo se trabaja en storage.work_dir (se borra si sale bien) y el MP4 queda en
outputs/lessons/<id>.mp4.
"""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import sqlite3
import textwrap
from collections.abc import Callable
from pathlib import Path

from apps.media import storage
from apps.media.fetch import extract_segment
from apps.media.models import USABLE_RIGHTS, Mezzanine
from apps.supercut import lessons, tts
from utils import ffmpeg as ff

log = logging.getLogger(__name__)

W, H, FPS, AR = 1080, 1920, 30, 48000
END_CARD_S = 4.0
BG_COLOR = "0x070710"
ACCENT = "0x7ad7ff"
TARGET_LUFS = -14.0
NARRATION_DELAY_MS = 250

END_CARD = {
    "es": {"pause": "Pausa.", "breathe": "Respira lento.", "brand": "YouLikeIt  ·  empatía a través del cine"},
    "en": {"pause": "Pause.", "breathe": "Breathe out slowly.", "brand": "YouLikeIt  ·  learn empathy through film"},
}

Progress = Callable[[str, int, str], None]


# ── helpers de texto (los usa también scripts/web/make_demo_lesson.py) ──


def find_font() -> str:
    for cand in ("C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("No se encontró una fuente TTF para drawtext")


def ff_escape(path: str | Path) -> str:
    """Ruta para opciones de filtro ffmpeg (escapa ':' de Windows y comillas)."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


class TextFiles:
    """Textos para drawtext como archivos (sin problemas de escape con ':' o comillas).

    write_bytes y no write_text: en Windows write_text convierte LF en CRLF y
    drawtext dibuja el CR como un recuadro.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._n = 0

    def path(self, body: str, name: str | None = None) -> str:
        self._n += 1
        p = self.root / f"{name or 't'}_{self._n:03d}.txt"
        p.write_bytes(body.replace("\r", "").encode("utf-8"))
        return ff_escape(p)


def drawtext(font: str, textfile: str, *, size: int, y: str | int, color: str = "white",
             x: str = "(w-text_w)/2", enable: str | None = None, box: bool = False,
             boxcolor: str = "black@0.55", boxborderw: int = 22) -> str:
    """Una drawtext (font y textfile ya escapados con ff_escape)."""
    parts = [f"fontfile='{font}'", f"textfile='{textfile}'", "expansion=none", f"fontcolor={color}",
             f"fontsize={size}", f"x={x}", f"y={y}"]
    if box:
        parts += ["box=1", f"boxcolor={boxcolor}", f"boxborderw={boxborderw}"]
    if enable:
        parts.append(f"enable='{enable}'")
    return "drawtext=" + ":".join(parts)


def wrap_lines(text: str | None, width: int = 26, max_lines: int = 3) -> list[str]:
    """Respeta los saltos explícitos y parte las líneas largas; recorta con '…'."""
    lines: list[str] = []
    for para in (text or "").replace("\r", "").split("\n"):
        para = " ".join(para.split())
        if para:
            lines += textwrap.wrap(para, width=width, break_long_words=True) or [para]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:") + "…"
    return lines


def text_block(tf: TextFiles, font: str, text: str | None, *, y0: int, size: int, line_h: int,
               width: int = 26, max_lines: int = 3, name: str = "t", **kw) -> list[str]:
    """Bloque de varias líneas: UNA drawtext por línea."""
    return [drawtext(font, tf.path(line, name), size=size, y=y0 + j * line_h, **kw)
            for j, line in enumerate(wrap_lines(text, width, max_lines))]


def blur_fit(src: str = "0:v", out: str = "v", draws: list[str] | None = None, *, fg_offset_y: int = -60) -> str:
    """Toma horizontal → vertical W×H: fondo desenfocado + la toma entera encima."""
    tail = ",".join(["setsar=1", f"fps={FPS}", "format=yuv420p", *(draws or [])])
    return (f"[{src}]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,"
            "eq=brightness=-0.18[bg];"
            f"[fgsrc]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{fg_offset_y:+d},{tail}[{out}]")


# ── comandos ────────────────────────────────────────────────────────

_FF = ("ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y")
_SEG_OUT = ("-c:a", "pcm_s16le", "-ar", str(AR), "-ac", "2", "-map_chapters", "-1", "-map_metadata", "-1",
            "-f", "matroska")


def _audio_prep(src: str, out: str, dur: float, extra: str = "") -> str:
    chain = f"aresample={AR},aformat=sample_fmts=fltp:channel_layouts=stereo"
    if extra:
        chain += f",{extra}"
    return f"[{src}]{chain},apad,atrim=0:{dur:.3f},asetpts=N/SR/TB[{out}]"


def _mix(narration_input: int | None, dur: float, *, end_fade: bool = False) -> str:
    """[o] = audio original preparado. Con narración: ducking + mezcla. Sale [a]."""
    fade = f",afade=t=out:st={max(0.0, dur - 0.6):.3f}:d=0.6" if end_fade else ""
    if narration_input is None:
        return f"[o]anull{fade}[a]"
    delay = f"adelay=delays={NARRATION_DELAY_MS}:all=1,volume=1.4"
    return (_audio_prep(f"{narration_input}:a", "nr", dur, delay) + ";"
            "[nr]asplit=2[nar][sc];"
            "[o][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck];"
            f"[duck][nar]amix=inputs=2:duration=first:normalize=0{fade}[a]")


def build_segment_cmd(mezz: Mezzanine, in_ms: int, out_ms: int, out_path: str | Path, *, draws: list[str],
                      narration: str | Path | None = None, has_audio: bool = True) -> list[str]:
    """Corte exacto (como fetch.build_cut_cmd) + 9:16 + rótulos + ducking, en una pasada."""
    if in_ms < mezz.start_ms or out_ms > mezz.end_ms:
        raise ValueError(f"{in_ms}..{out_ms} fuera del mezzanine {mezz.start_ms}..{mezz.end_ms}")
    dur = (out_ms - in_ms) / 1000
    cmd = [*_FF, "-ss", ff.ms_to_ts(in_ms - mezz.start_ms), "-t", f"{dur:.3f}", "-i", mezz.path]
    nxt = 1
    if has_audio:
        src_audio = "0:a:0"
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
        src_audio, nxt = f"{nxt}:a", nxt + 1
    nar_idx = None
    if narration:
        cmd += ["-i", str(narration)]
        nar_idx = nxt
    graph = ";".join([blur_fit("0:v", "v", draws), _audio_prep(src_audio, "o", dur), _mix(nar_idx, dur)])
    return [*cmd, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", "-r", str(FPS),
            *ff.video_encoder_args(bitrate="6M", cq=21), *_SEG_OUT, str(out_path)]


def build_end_card_cmd(out_path: str | Path, *, draws: list[str], narration: str | Path | None = None,
                       duration_s: float = END_CARD_S) -> list[str]:
    d = f"{duration_s:.3f}"
    cmd = [*_FF, "-f", "lavfi", "-i", f"color=c={BG_COLOR}:s={W}x{H}:r={FPS}:d={d}",
           "-f", "lavfi", "-t", d, "-i", f"anullsrc=r={AR}:cl=stereo"]
    nar_idx = None
    if narration:
        cmd += ["-i", str(narration)]
        nar_idx = 2
    video = f"[0:v]setsar=1,format=yuv420p{''.join(',' + x for x in draws)}[v]"
    graph = ";".join([video, _audio_prep("1:a", "o", duration_s), _mix(nar_idx, duration_s, end_fade=True)])
    return [*cmd, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", d, "-r", str(FPS),
            *ff.video_encoder_args(bitrate="6M", cq=21), *_SEG_OUT, str(out_path)]


def write_concat_list(paths: list[Path], list_path: Path) -> Path:
    lines = ["file '" + str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''") + "'" for p in paths]
    list_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return list_path


_LOUDNORM = f"loudnorm=I={TARGET_LUFS:g}:TP=-1.5:LRA=11"


def measure_loudness(list_path: Path) -> dict | None:
    """Primera pasada de loudnorm (solo audio). None si no se pudo medir (p. ej. silencio)."""
    proc = ff.run(["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-f", "concat", "-safe", "0",
                   "-i", str(list_path), "-vn", "-af", f"{_LOUDNORM}:print_format=json", "-f", "null", "-"],
                  timeout=600)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr or "", flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m[-1])
        vals = {k: float(data[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, ValueError):
        return None
    return vals if all(math.isfinite(v) for v in vals.values()) else None


def build_final_cmd(list_path: Path, out_path: Path, measured: dict | None) -> list[str]:
    if measured:
        af = (f"{_LOUDNORM}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
              f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
              f":offset={measured['target_offset']}:linear=true")
    else:
        af = _LOUDNORM
    return [*_FF, "-f", "concat", "-safe", "0", "-i", str(list_path), "-map", "0:v:0", "-map", "0:a:0",
            "-c:v", "copy", "-af", f"{af},aresample={AR}", "-c:a", "aac", "-b:a", "192k", "-ar", str(AR),
            "-map_chapters", "-1", "-map_metadata", "-1", "-movflags", "+faststart", str(out_path)]


# ── lección ─────────────────────────────────────────────────────────


def _label(spec: str, lang: str) -> str:
    from apps.supercut.planner import label_for
    dimension, _, value = spec.partition(":")
    try:
        return label_for(dimension, value, lang)
    except KeyError:
        return value.replace("_", " ")


def segment_draws(tf: TextFiles, font: str, *, label: str, caption: str | None, credit: str,
                  hook: str | None = None) -> list[str]:
    draws = text_block(tf, font, label.upper(), y0=220, size=54, line_h=64, width=30, max_lines=1,
                       name="label", color=ACCENT)
    if hook:
        draws += text_block(tf, font, hook, y0=310, size=46, line_h=60, width=34, max_lines=2, name="hook")
    draws += text_block(tf, font, caption, y0=1370, size=58, line_h=96, width=26, max_lines=3, name="cap",
                        box=True)
    draws += text_block(tf, font, credit, y0=1715, size=34, line_h=44, width=44, max_lines=2, name="credit",
                        color="white@0.8")
    return draws


def end_card_draws(tf: TextFiles, font: str, *, lang: str, outro: str | None) -> list[str]:
    t = END_CARD["es" if lang.startswith("es") else "en"]
    draws = [drawtext(font, tf.path(t["pause"], "pause"), size=110, y=760, color=ACCENT),
             drawtext(font, tf.path(t["breathe"], "breathe"), size=62, y=920)]
    draws += text_block(tf, font, outro, y0=1080, size=44, line_h=58, width=36, max_lines=3, name="outro",
                        color="white@0.85")
    draws.append(drawtext(font, tf.path(t["brand"], "brand"), size=34, y=1700, color="white@0.6"))
    return draws


def _credit(title: str | None, year: int | None) -> str:
    return f"{title} ({year})" if year else (title or "")


def render_lesson(conn: sqlite3.Connection, lesson_id: int, progress: Progress | None = None, *,
                  narrate: bool | None = None) -> dict:
    """Renderiza la lección (rendering → rendered; si falla vuelve a draft).

    narrate=None: narra si la lección tiene guion. La narración usa tts (red);
    si la voz falla, el render falla (no se entrega un Short mudo sin avisar).
    """
    def report(stage: str, pct: int, detail: str = "") -> None:
        if progress:
            progress(stage, pct, detail)

    lesson = lessons.get_lesson(conn, lesson_id)
    items = lessons.get_items(conn, lesson_id)
    script = lesson["script"]
    if narrate is None:
        narrate = bool(script)
    if narrate and not script:
        raise ValueError("No hay guion para narrar (genera uno o renderiza sin narración)")
    lessons.begin_render(conn, lesson_id)
    try:
        out = _render(lesson, items, narrate=narrate, report=report)
    except BaseException:
        lessons.fail_render(conn, lesson_id)
        raise
    info = ff.summarize_probe(ff.probe(out))
    duration_s = info["duration_ms"] / 1000
    lessons.finish_render(conn, lesson_id, out, duration_s)
    report("done", 100, f"{duration_s:.1f} s")
    return {"lesson_id": lesson_id, "output_path": str(out), "duration_s": round(duration_s, 2),
            "width": info["width"], "height": info["height"], "segments": len(items), "narration": narrate,
            "video_url": f"/api/lessons/{lesson_id}/video"}


def _render(lesson: dict, items: list[dict], *, narrate: bool, report: Callable[[str, int, str], None]) -> Path:
    lang = lesson["lang"] or "es"
    script = lesson["script"] or {}
    seg_script = {s["idx"]: s for s in script.get("segments", [])}
    font = ff_escape(find_font())
    label = _label(lesson["spec"], lang)
    n = len(items)
    with storage.work_dir(f"lesson_{lesson['id']}") as wd:
        tf = TextFiles(wd / "txt")
        parts: list[Path] = []
        for k, it in enumerate(items):
            title = it["work_title"] or "?"
            report("extract", int(5 + 75 * k / n), f"tramo {k + 1}/{n}: {title}")
            if not it["master_uri"]:
                raise ValueError(f"El momento {it['moment_id']} ya no existe o no tiene asset")
            if it["rights"] not in USABLE_RIGHTS:
                raise ValueError(f"'{title}' tiene derechos '{it['rights']}': no se puede usar")
            mezz = extract_segment(it["master_uri"], it["in_ms"], it["out_ms"])
            has_audio = ff.summarize_probe(ff.probe(mezz.path))["has_audio"]
            seg = seg_script.get(it["idx"], {})
            hook = script.get("hook") if k == 0 else None
            narration = None
            if narrate:
                text = " ".join(x for x in (hook, seg.get("narration")) if x)
                if text.strip():
                    report("voice", int(5 + 75 * (k + 0.4) / n), f"voz {k + 1}/{n}")
                    narration, _ = tts.synthesize(text, lang=lang, out_path=wd / f"nar_{k:02d}.mp3")
            report("render", int(5 + 75 * (k + 0.6) / n), f"tramo {k + 1}/{n}")
            draws = segment_draws(tf, font, label=label, caption=it["caption"] or seg.get("caption"),
                                  credit=_credit(title, it["work_year"]), hook=hook)
            part = wd / f"seg_{k:02d}.mkv"
            ff.run(build_segment_cmd(mezz, it["in_ms"], it["out_ms"], part, draws=draws,
                                     narration=narration, has_audio=has_audio), timeout=900)
            parts.append(part)

        report("end_card", 82, "tarjeta final")
        outro = script.get("outro")
        narration = None
        if narrate and outro:
            narration, _ = tts.synthesize(outro, lang=lang, out_path=wd / "nar_end.mp3")
        end = wd / "end.mkv"
        ff.run(build_end_card_cmd(end, draws=end_card_draws(tf, font, lang=lang, outro=outro),
                                  narration=narration), timeout=300)
        parts.append(end)

        report("mix", 88, f"loudnorm {TARGET_LUFS:g} LUFS")
        list_path = write_concat_list(parts, wd / "concat.txt")
        measured = measure_loudness(list_path)
        tmp_out = wd / "final.mp4"
        report("mux", 94, "concat + faststart")
        ff.run(build_final_cmd(list_path, tmp_out, measured), timeout=900)
        dest = lessons.video_path(lesson["id"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        shutil.move(str(tmp_out), str(dest))
    return dest
