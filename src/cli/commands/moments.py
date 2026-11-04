"""`ylk moments …` — dominio Moments (Transform: momentos, categorías, búsqueda entre obras).

    ylk moments vocab --dimension trope
    ylk moments detect 1                 # candidatos + señales + anclas (Wikiquote/trama)
    ylk moments label 1 --provider groq  # top-K → LLM con vocabulario controlado
    ylk moments run 1                    # detect + label
    ylk moments show 1 --top 15
    ylk moments find trope:the_dead_return --min-works 3
"""
from __future__ import annotations

import json
import sqlite3

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Momentos importantes, categorías y búsqueda entre obras")


def _db() -> sqlite3.Connection:
    from core.config import load_settings
    from core.db import get_db
    return get_db(load_settings().data_dir)


def _print(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


@app.command("vocab")
def vocab_cmd(dimension: str = typer.Option("trope", help="trope|beat|emotion|role|theme")):
    """Lista el vocabulario controlado de una dimensión."""
    from apps.moments.vocab import load_vocab
    _print([{"id": e["id"], "es": e.get("es"), "desc": e.get("desc_es")} for e in load_vocab()[dimension]])


@app.command()
def detect(asset_id: int, no_fetch: bool = typer.Option(False, "--no-fetch", help="No bajar Wikiquote/trama"),
           refresh: bool = typer.Option(False, help="Volver a bajar las anclas")):
    """Candidatos de momento con señales interpretables y anclas externas."""
    from apps.moments.pipeline import detect_moments
    _print(detect_moments(_db(), asset_id, fetch_anchors=not no_fetch, refresh_anchors=refresh))


@app.command()
def label(asset_id: int, top: int = 40, batch: int = 6,
          provider: str = typer.Option(None, help="auto|ollama|groq|gemini (default: LLM_PROVIDER)")):
    """Etiqueta el top-K con el LLM (vocabulario controlado, salida validada)."""
    from apps.moments.pipeline import label_asset
    _print(label_asset(_db(), asset_id, top_k=top, batch_size=batch, provider=provider))


@app.command()
def run(asset_id: int, top: int = 40, provider: str = typer.Option(None)):
    """detect + label para un asset."""
    from apps.moments.pipeline import detect_moments, label_asset
    conn = _db()
    _print({"detect": detect_moments(conn, asset_id),
            "label": label_asset(conn, asset_id, top_k=top, provider=provider)})


@app.command()
def show(asset_id: int, top: int = 15, status: str = typer.Option(None, help="candidate|labeled")):
    """Momentos de un asset ordenados por importancia, con sus etiquetas y por qué."""
    conn = _db()
    where, params = ("AND status = ?", (asset_id, status, top)) if status else ("", (asset_id, top))
    rows = conn.execute(
        f"""SELECT id, start_ms, end_ms, importance, status, summary_es, text, features_json, anchors_json
            FROM moments WHERE asset_id = ? {where} ORDER BY importance DESC LIMIT ?""", params).fetchall()
    out = []
    for r in rows:
        feats = json.loads(r[7] or "{}")
        labels = conn.execute("SELECT dimension, value, ROUND(confidence, 2), source FROM moment_labels "
                              "WHERE moment_id = ? ORDER BY confidence DESC", (r[0],)).fetchall()
        top_why = sorted((feats.get("contrib") or {}).items(), key=lambda kv: -kv[1])[:3]
        out.append({"id": r[0], "t": f"{r[1] / 1000:.1f}-{r[2] / 1000:.1f}s", "importance": r[3],
                    "status": r[4], "summary": r[5], "text": (r[6] or "")[:120],
                    "why": {k: v for k, v in top_why if v > 0},
                    "anchors": json.loads(r[8] or "{}"),
                    "labels": [f"{d}:{v} ({c}, {s})" for d, v, c, s in labels]})
    _print(out)


@app.command()
def find(spec: str = typer.Argument(..., help="dimension:valor, p.ej. trope:the_dead_return"),
         limit: int = 6, min_works: int = 3, per_work: int = 1,
         min_confidence: float = typer.Option(0.5, help="Bajar a 0.25 para incluir etiquetas léxicas")):
    """Mejores momentos de un tropo/tema/emoción ENTRE obras distintas (MMR)."""
    from apps.moments.retrieval import find_moments
    from apps.moments.vocab import parse_spec
    dim, value = parse_spec(spec)
    _print(find_moments(_db(), dim, value, limit=limit, min_works=min_works, max_per_work=per_work,
                        min_confidence=min_confidence))
