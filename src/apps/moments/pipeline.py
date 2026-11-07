"""Orquestación del dominio moments (idempotente por asset).

detect_moments:  transcripción + planos + audio  →  candidatos con señales,
                 anclas (Wikiquote / trama) e importancia  →  tabla moments
                 (+ etiquetas débiles: léxicas y de posición).
label_moments:   top-K → LLM (local/API) → etiquetas validadas (labeling.py).
"""
from __future__ import annotations

import bisect
import logging
import sqlite3
from pathlib import Path

from apps.media import schema as media_schema
from apps.media import storage
from apps.moments import anchors, features, labeling, schema, scenes, vocab
from utils.websocket_hub import notify

log = logging.getLogger(__name__)
SOURCE = "moments.detect"
CREDITS_HEAD_MS = 90_000          # picos de audio en los créditos no son momentos
CREDITS_TAIL_FRAC = 0.03


def load_inputs(conn: sqlite3.Connection, asset_id: int):
    asset = media_schema.get_asset(conn, asset_id)
    if asset is None:
        raise KeyError(f"asset {asset_id} no existe")
    segs = [{"start_ms": r[0], "end_ms": r[1], "text": r[2], "lang": r[3]} for r in conn.execute(
        "SELECT start_ms, end_ms, text, lang FROM transcript_segments WHERE asset_id = ? ORDER BY idx",
        (asset_id,))]
    word_starts = [r[0] for r in conn.execute(
        "SELECT start_ms FROM transcript_words WHERE asset_id = ? ORDER BY start_ms", (asset_id,))]
    shots = [(r[0], r[1]) for r in conn.execute(
        "SELECT start_ms, end_ms FROM shots WHERE asset_id = ? ORDER BY idx", (asset_id,))]
    return asset, segs, word_starts, shots


def ensure_anchors(conn: sqlite3.Connection, work_id: int, title: str, year: int | None, lang: str,
                   *, fetch: bool = True, refresh: bool = False) -> tuple[list[dict], list[str]]:
    """Citas y trama desde caché (work_texts); si faltan, las baja una vez."""
    out = {}
    for kind, fn in (("wikiquote", anchors.fetch_wikiquote), ("plot", anchors.fetch_plot)):
        cached = schema.get_work_texts(conn, work_id, kind, lang)
        if cached is not None and not refresh:
            out[kind] = cached
            continue
        if not fetch:
            out[kind] = cached or []
            continue
        try:
            items, url = fn(title, year, lang=lang)
        except Exception as e:  # noqa: BLE001 — sin red / página rara: seguir sin anclas
            log.warning("No se pudo bajar %s de %r: %s", kind, title, e)
            out[kind] = cached or []
            continue
        schema.save_work_texts(conn, work_id, kind, items, lang=lang, source_url=url)
        out[kind] = items
    return out["wikiquote"], out["plot"]


def _weak_labels(text: str, sig: dict, position: float) -> tuple[list[tuple], list[str]]:
    labels = []
    hits = vocab.trope_cue_hits(text) if text else {}
    for trope, n in sorted(hits.items(), key=lambda kv: -kv[1])[:3]:
        labels.append(("trope", trope, min(0.6, 0.25 + 0.15 * n), "lexical"))
    beats = sorted(vocab.beat_prior(position).items(), key=lambda kv: -kv[1])
    if beats and beats[0][1] >= 1.0:
        labels.append(("beat", beats[0][0], 0.3, "position"))
    if sig["sudden_onset"] >= 0.6:
        labels.append(("emotion", "shock", 0.35, "audio"))
    elif sig["loudness"] >= 0.7 and sig["shot_tempo"] >= 0.5:
        labels.append(("emotion", "tension", 0.3, "audio"))
    return labels, list(hits)


def detect_moments(conn: sqlite3.Connection, asset_id: int, *, fetch_anchors: bool = True,
                   refresh_anchors: bool = False, cleanup: bool | None = None) -> dict:
    asset, segs, word_starts, shots = load_inputs(conn, asset_id)
    if not segs and not shots:
        raise ValueError(f"asset {asset_id} sin transcripción ni planos: corre `ylk media index {asset_id}`")
    duration = asset["duration_ms"] or max([s["end_ms"] for s in segs] + [e for _, e in shots])
    notify(SOURCE, "extract", {"asset_id": asset_id, "segments": len(segs), "shots": len(shots)})

    audio = None
    peaks: list[int] = []
    env_npy = storage.envelope_path(asset_id)
    if asset["audio_path"] and Path(asset["audio_path"]).exists():
        audio = features.AudioProfile.from_wav(asset["audio_path"])
        audio.save(env_npy)
    elif env_npy.exists():                   # el wav ya se limpió: basta la envolvente
        audio = features.AudioProfile.from_npy(env_npy)
    if audio is not None:
        # Créditos: música fuerte al inicio/final que no es un "momento" de la obra.
        lo, hi = CREDITS_HEAD_MS, duration * (1 - CREDITS_TAIL_FRAC)
        peaks = [p for p in features.energy_peaks(audio) if lo <= p <= hi]

    lang = next((s["lang"] for s in segs if s.get("lang")), None) or "en"
    quotes, plot = ensure_anchors(conn, asset["work_id"], asset["work_title"], asset["work_year"], lang,
                                  fetch=fetch_anchors, refresh=refresh_anchors)
    q_matches = anchors.match_quotes(quotes, segs) if quotes else []
    plot_al = anchors.align_plot(plot, segs, duration) if plot else []

    cands = scenes.candidate_windows(segs, shots, duration, energy_peaks_ms=peaks)
    for q in q_matches:                      # cada cita encontrada tiene su propio candidato
        if not any(c["start_ms"] <= q["start_ms"] and c["end_ms"] >= q["end_ms"] for c in cands):
            s, e, si, so = scenes.snap_window(q["start_ms"], q["end_ms"], shots, duration)
            text = " ".join(x["text"] for x in segs if x["start_ms"] < e and x["end_ms"] > s)
            cands.append({"start_ms": s, "end_ms": e, "shot_in": si, "shot_out": so, "text": text,
                          "kind": "quote", "position": round(((s + e) / 2) / max(1, duration), 4)})

    shot_starts = [a for a, _ in shots]
    for c in cands:
        mid = (c["start_ms"] + c["end_ms"]) // 2
        q = max((q for q in q_matches if q["start_ms"] < c["end_ms"] and q["end_ms"] > c["start_ms"]),
                key=lambda q: q["score"], default=None)
        p = max((p for p in plot_al if p["start_ms"] <= mid < p["end_ms"]),
                key=lambda p: p["score"], default=None)
        words = bisect.bisect_left(word_starts, c["end_ms"]) - bisect.bisect_left(word_starts, c["start_ms"])
        hits = vocab.trope_cue_hits(c["text"]) if c["text"] else {}
        sig = features.window_signals(
            c["start_ms"], c["end_ms"], audio=audio, shot_starts=shot_starts,
            text=c["text"], words=words, position=c["position"],
            quote_score=q["score"] if q else 0.0,
            plot_score=min(1.0, p["score"] * 2) if p else 0.0,    # coseno 0.5 ya es alineación fuerte
            cue_hits=sum(hits.values()))
        score, contrib = features.importance(sig)
        labels, cue_tropes = _weak_labels(c["text"], sig, c["position"])
        c.update(signal_score=score, labels=labels,
                 features={**sig, "contrib": contrib, "kind": c["kind"], "cue_tropes": cue_tropes},
                 anchors={k: v for k, v in {
                     "quote": q["text"] if q else None, "quote_score": q["score"] if q else None,
                     "plot": p["sentence"] if p else None, "plot_score": p["score"] if p else None,
                 }.items() if v is not None})

    # Dos candidatos pueden caer en el MISMO rango (p.ej. una cita y su bloque de
    # diálogo ajustados al mismo plano): se queda el de mayor puntaje.
    by_range: dict[tuple[int, int], dict] = {}
    for c in cands:
        key = (c["start_ms"], c["end_ms"])
        if key not in by_range or c["signal_score"] > by_range[key]["signal_score"]:
            by_range[key] = c
    cands = sorted(by_range.values(), key=lambda c: c["start_ms"])

    vocab.sync_vocab_table(conn)
    n = schema.save_candidates(conn, asset_id, cands)
    top = sorted(cands, key=lambda c: -c["signal_score"])[:5]
    report = {
        "asset_id": asset_id, "title": asset["work_title"], "candidates": n,
        "quotes": {"found": len(quotes), "matched": len(q_matches)},
        "plot_sentences": len(plot), "energy_peaks": len(peaks),
        "top": [{"t": labeling._fmt_time(c["start_ms"]), "score": c["signal_score"],
                 "text": (c["text"] or "(sin diálogo)")[:80], "quote": bool(c["anchors"].get("quote"))}
                for c in top],
    }
    # Proxy + wav ya no hacen falta (transcripción en DB, envolvente en .npy).
    if cleanup if cleanup is not None else not storage.keep_analysis_files():
        report["cleanup"] = storage.cleanup_analysis(conn, asset_id)
    notify(SOURCE, "load", report)
    return report


def label_asset(conn: sqlite3.Connection, asset_id: int, *, top_k: int = 40, batch_size: int = 6,
                provider: str | None = None) -> dict:
    asset = media_schema.get_asset(conn, asset_id)
    return labeling.label_moments(conn, asset_id, work_title=asset["work_title"], year=asset["work_year"],
                                  top_k=top_k, batch_size=batch_size, provider=provider)
