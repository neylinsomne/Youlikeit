"""Genera la lección de ejemplo del sitio (demo de la revisión de TikTok).

"Fear · Miedo" con la escena del cementerio de Night of the Living Dead (1968,
dominio público, Internet Archive): Johnny se burla de Barbra ("they're coming
for you") y al fondo aparece el primer muerto. Usa la extracción por rango de
apps.media.fetch (no baja la película) y arma un vertical 9:16 con fondo
desenfocado, rótulos educativos y una pausa final de respiración.

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


def _font() -> str:
    for cand in ("C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("No se encontró una fuente TTF para drawtext")


def _esc(path: str | Path) -> str:
    """Ruta para opciones de filtro ffmpeg (escapa ':' de Windows y comillas)."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build(out: Path) -> Path:
    mezz = extract_segment(MASTER, START_MS, END_MS)
    clip_s = (END_MS - START_MS) / 1000
    total_s = clip_s + END_CARD_S
    font = _esc(_font())
    with tempfile.TemporaryDirectory(prefix="ylk_lesson_") as tmp:
        tmp = Path(tmp)

        def text(name: str, body: str) -> str:
            p = tmp / f"{name}.txt"
            # write_bytes y no write_text: en Windows write_text convierte LF en CRLF
            # y drawtext dibuja el CR como un recuadro.
            p.write_bytes(body.encode("utf-8"))
            return _esc(p)

        draws = [
            f"drawtext=fontfile='{font}':textfile='{text('label', 'FEAR  ·  MIEDO')}':fontcolor=0x7ad7ff:"
            f"fontsize=54:x=(w-text_w)/2:y=220:enable='lt(t,{clip_s})'",
            f"drawtext=fontfile='{font}':textfile='{text('credit', 'Night of the Living Dead (1968)  ·  Public domain')}':"
            f"fontcolor=white@0.75:fontsize=30:x=(w-text_w)/2:y=h-170:enable='lt(t,{clip_s})'",
        ]
        # Una drawtext por linea: con text shaping (ffmpeg 8) el salto de linea se
        # dibuja como un glifo vacio al final de la primera linea.
        for i, (a, b, body) in enumerate(CAPTIONS):
            for j, line in enumerate(body.splitlines()):
                draws.append(
                    f"drawtext=fontfile='{font}':textfile='{text(f'cap{i}_{j}', line)}':fontcolor=white:"
                    f"fontsize=58:box=1:boxcolor=black@0.55:boxborderw=22:x=(w-text_w)/2:y={1370 + j * 96}:"
                    f"enable='between(t,{a},{b})'")
        draws += [
            f"drawtext=fontfile='{font}':textfile='{text('pause', 'Pause.')}':fontcolor=0x7ad7ff:fontsize=110:"
            f"x=(w-text_w)/2:y=780:enable='gte(t,{clip_s})'",
            f"drawtext=fontfile='{font}':textfile='{text('breathe', 'Breathe out slowly.')}':fontcolor=white:"
            f"fontsize=62:x=(w-text_w)/2:y=940:enable='gte(t,{clip_s})'",
            f"drawtext=fontfile='{font}':textfile='{text('brand', 'YouLikeIt  ·  learn empathy through film')}':"
            f"fontcolor=white@0.6:fontsize=34:x=(w-text_w)/2:y=1700:enable='gte(t,{clip_s})'",
        ]
        graph = (
            "[0:v]split=2[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:3,"
            "eq=brightness=-0.18[bg];"
            "[b]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2-60,"
            f"tpad=stop_mode=add:stop_duration={END_CARD_S}:color=0x070710,"
            + ",".join(draws) + "[v];"
            f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,apad[a2]"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        ff.run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-ss", ff.ms_to_ts(START_MS - mezz.start_ms), "-i", mezz.path, "-t", f"{clip_s:.3f}",
                "-filter_complex", graph, "-map", "[v]", "-map", "[a2]", "-t", f"{total_s:.3f}",
                "-map_chapters", "-1", "-map_metadata", "-1",   # capítulos del MKV de IA → pista bin_data
                *ff.video_encoder_args(bitrate="5M", cq=23), "-r", "30",
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
