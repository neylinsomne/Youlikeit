"""Genera la lección de ejemplo del sitio (demo de la revisión de TikTok).

"Fear · Miedo" con la escena del cementerio de Night of the Living Dead (1968,
dominio público, Internet Archive): Johnny se burla de Barbra ("they're coming
for you") y al fondo aparece el primer muerto. Usa la extracción por rango de
apps.media.fetch (no baja la película) y arma un vertical 9:16 con fondo
desenfocado, rótulos educativos y una pausa final de respiración, con los
mismos helpers que el render de lecciones (apps.supercut.render: blur_fit,
drawtext por línea, TextFiles, -14 LUFS). Las lecciones del estudio usan
render.render_lesson; este script queda para el demo fijo del sitio.

    python scripts/web/make_demo_lesson.py
Salida: web/app/lessons/fear-notld-cemetery.mp4 (+ entrada en lessons.json).
El MP4 no va a git (*.mp4 ignorado); se despliega con `railway up --no-gitignore`.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from apps.media.fetch import extract_segment
from apps.supercut.render import ACCENT, BG_COLOR, FPS, TARGET_LUFS, TextFiles, blur_fit, drawtext, ff_escape, find_font
from utils import ffmpeg as ff

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "web" / "app" / "lessons"
MASTER = "https://archive.org/download/Night.Of.The.Living.Dead_1080p/NightOfTheLivingDead_1080p.mkv"
START_MS, END_MS = 366_000, 388_000          # 6:06 → 6:28 (verificado con fotogramas del proxy)
END_CARD_S = 4
LESSON = {
    "id": "fear-notld-cemetery",
    "title": "Fear: the threat is still far away",
    "emotion": "fear",
    "film": "Night of the Living Dead",
    "year": 1968,
    "rights": "Public domain",
    "source_url": "https://archive.org/details/Night.Of.The.Living.Dead_1080p",
    "file": "fear-notld-cemetery.mp4",
    "summary": "Johnny teases Barbra in the cemetery while the first ghoul appears far behind them. "
               "A lesson on how fear reacts before the threat is close.",
}
CAPTIONS = [  # (desde_s, hasta_s, texto)
    (0.0, 7.5, "Fear is an alarm,\nreal or imagined."),
    (7.5, 15.0, "The threat is still far away.\nThe body reacts anyway."),
    (15.0, 22.0, "Where do you feel fear\nin your body?"),
]


def build(out: Path) -> Path:
    """Un solo ffmpeg: corte exacto + 9:16 (apps.supercut.render.blur_fit) + rótulos + pausa final."""
    mezz = extract_segment(MASTER, START_MS, END_MS)
    clip_s = (END_MS - START_MS) / 1000
    total_s = clip_s + END_CARD_S
    font = ff_escape(find_font())
    during, after = f"lt(t,{clip_s})", f"gte(t,{clip_s})"
    with tempfile.TemporaryDirectory(prefix="ylk_lesson_") as tmp:
        tf = TextFiles(Path(tmp))                   # textos como archivo (write_bytes: sin CR en Windows)
        draws = [
            drawtext(font, tf.path("FEAR  ·  MIEDO"), size=54, y=220, color=ACCENT, enable=during),
            drawtext(font, tf.path("Night of the Living Dead (1968)  ·  Public domain"), size=30, y="h-170",
                     color="white@0.75", enable=during),
        ]
        # Una drawtext por línea: con text shaping (ffmpeg 8) el salto de línea se
        # dibuja como un glifo vacío al final de la primera línea.
        for a, b, body in CAPTIONS:
            for j, line in enumerate(body.splitlines()):
                draws.append(drawtext(font, tf.path(line), size=58, y=1370 + j * 96, box=True,
                                      enable=f"between(t,{a},{b})"))
        draws += [
            drawtext(font, tf.path("Pause."), size=110, y=780, color=ACCENT, enable=after),
            drawtext(font, tf.path("Breathe out slowly."), size=62, y=940, enable=after),
            drawtext(font, tf.path("YouLikeIt  ·  learn empathy through film"), size=34, y=1700,
                     color="white@0.6", enable=after),
        ]
        pad = f"tpad=stop_mode=add:stop_duration={END_CARD_S}:color={BG_COLOR}"
        graph = (blur_fit("0:v", "v", [pad, *draws]) + ";"
                 f"[0:a]loudnorm=I={TARGET_LUFS:g}:TP=-1.5:LRA=11,apad[a2]")
        out.parent.mkdir(parents=True, exist_ok=True)
        ff.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-ss", ff.ms_to_ts(START_MS - mezz.start_ms), "-i", mezz.path, "-t", f"{clip_s:.3f}",
                "-filter_complex", graph, "-map", "[v]", "-map", "[a2]", "-t", f"{total_s:.3f}",
                "-map_chapters", "-1", "-map_metadata", "-1",   # capítulos del MKV de IA → pista bin_data
                *ff.video_encoder_args(bitrate="5M", cq=23), "-r", str(FPS),
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)],
               timeout=900)
    return out


def main() -> None:
    out = build(OUT_DIR / LESSON["file"])
    info = ff.summarize_probe(ff.probe(out))
    entry = {**LESSON, "duration_s": round(info["duration_ms"] / 1000, 1),
             "size_bytes": out.stat().st_size, "width": info["width"], "height": info["height"]}
    reg_path = OUT_DIR / "lessons.json"
    lessons = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.exists() else []
    lessons = [x for x in lessons if x["id"] != entry["id"]] + [entry]
    reg_path.write_text(json.dumps(lessons, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(entry, indent=1))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
