"""Helpers compartidos por tests/supercut, tests/publish y tests/studio."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

STUDIO_ENV = ("STUDIO_TOKEN", "STUDIO_PORT", "WEB_BASE_URL", "STUDIO_API_KEY", "TOKEN_ENC_KEY",
              "GOOGLE_CLIENT_SECRETS", "TTS_BACKEND", "TTS_VOICE", "TTS_VOICE_ES", "TTS_VOICE_EN",
              "LLM_PROVIDER", "ASR_BACKEND", "STUDIO_ALLOWED_ORIGINS", "STUDIO_FRONT_URL",
              "KEEP_ANALYSIS_FILES", "MEDIA_CACHE_MAX_GB")

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg/ffprobe no están en el PATH")


def isolate_env(tmp_path: Path, monkeypatch) -> Path:
    """DATA_DIR, OUTPUT_DIR y TOKENS_DIR en tmp; variables del estudio limpias."""
    for key in STUDIO_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("TOKENS_DIR", str(tmp_path / "tokens"))
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS", str(tmp_path / "no_client_secrets.json"))
    monkeypatch.setenv("LLM_PROVIDER", "groq")              # sin GROQ_API_KEY → LLMUnavailable, sin red
    return tmp_path


def schema_conn() -> sqlite3.Connection:
    """SQLite en memoria con media + moments + supercut + studio."""
    from apps.media.schema import ensure_schema as media
    from apps.moments.schema import ensure_schema as moments
    from apps.studio.schema import ensure_schema as studio
    from apps.supercut.schema import ensure_schema as supercut
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for fn in (media, moments, supercut, studio):
        fn(c)
    return c


def add_asset(conn: sqlite3.Connection, *, title: str, year: int | None, master: str | None = None,
              rights: str = "public_domain") -> int:
    from apps.media.indexer import register_candidate
    from apps.media.models import MediaCandidate
    uri = master or f"https://ia.example/{title.replace(' ', '_')}.mkv"
    return register_candidate(conn, MediaCandidate(provider="local" if master else "archive_org",
                                                   external_id=title, title=title, year=year, master_uri=uri,
                                                   proxy_uri=uri, rights=rights))


def add_moment(conn: sqlite3.Connection, asset_id: int, *, start_ms: int, end_ms: int, text: str = "",
               importance: float = 0.8, labels: tuple = (("emotion", "fear", 0.9),),
               features: dict | None = None, anchors: dict | None = None) -> int:
    import json

    from apps.moments.schema import add_label
    cur = conn.execute(
        "INSERT INTO moments (asset_id, start_ms, end_ms, text, importance, signal_score, position, status, "
        "features_json, anchors_json) VALUES (?, ?, ?, ?, ?, ?, 0.3, 'labeled', ?, ?)",
        (asset_id, start_ms, end_ms, text, importance, importance * 0.8,
         json.dumps(features or {"contrib": {"loudness": 0.2, "quote_anchor": 0.4, "silence": 0.0}}),
         json.dumps(anchors or {"quote": "They're coming for you", "quote_score": 0.9})))
    for dim, value, conf in labels:
        add_label(conn, cur.lastrowid, dim, value, conf, "llm:test", commit=False)
    conn.commit()
    return int(cur.lastrowid)


def seed_fear_world(conn: sqlite3.Connection, masters: dict[str, Path] | None = None) -> dict:
    """3 obras con un momento 'emotion:fear' cada una (+1 asset restringido que no debe aparecer)."""
    masters = masters or {}
    out = {"assets": {}, "moments": {}}
    for title, year, start, end, imp in (("Horror Express", 1972, 5_000, 25_000, 0.7),
                                         ("Carnival of Souls", 1962, 4_000, 9_000, 0.6),
                                         ("Night of the Living Dead", 1968, 6_000, 30_000, 0.9)):
        m = masters.get(title)
        aid = add_asset(conn, title=title, year=year, master=str(m) if m else None)
        out["assets"][title] = aid
        out["moments"][title] = add_moment(conn, aid, start_ms=start, end_ms=end, importance=imp,
                                           text=f"A frightening scene from {title}.")
    bad = add_asset(conn, title="Restricted Film", year=1980, rights="restricted")
    out["moments"]["Restricted Film"] = add_moment(conn, bad, start_ms=0, end_ms=5_000, importance=1.0)
    return out


def make_master(path: Path, *, seconds: int = 12, size: str = "640x360", audio: bool = True) -> Path:
    """Master sintético (testsrc2 + seno) con keyframe cada 1 s, como una película local."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", f"testsrc2=size={size}:rate=24:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=48000"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-g", "24", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if audio else []
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def fake_tts(text: str, *, lang: str, out_path, voice=None, backend=None):
    """Reemplazo de tts.synthesize: un tono de 1.5 s en mp3 (sin red)."""
    out_path = Path(out_path)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=1.5:sample_rate=24000", "-c:a", "libmp3lame", str(out_path)],
                   check=True, capture_output=True)
    return out_path, [{"word": w, "start_ms": i * 300, "end_ms": i * 300 + 250} for i, w in enumerate(text.split())]


def probe(path) -> dict:
    from utils import ffmpeg as ff
    return ff.probe(path)


def integrated_lufs(path) -> float:
    import re
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null",
                           "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    vals = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    return float(vals[-1])
