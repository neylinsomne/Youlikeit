"""
Signals Distiller — Data Verification + Feature Extraction sobre market_signals.

Lee `market_signals` (crudo, multi-fuente), aplica:
  1. Dedupe por normalized_title (capa 1) + fuzzy ratio > 88 (capa 2).
  2. Cluster por título normalizado.
  3. Scoring per persona:
        score = freq_norm * recency * persona_alignment * source_quality
  4. Para top-K por persona, genera `suggested_angle` con LLM (1 frase).
  5. Persiste en `persona_briefs`.

API pública:
    from apps.signals.signals_distiller import distill, fetch_briefs_for_persona

    n_briefs = distill(conn, settings)
    briefs = fetch_briefs_for_persona(conn, "deep_mind", limit=10)

Notas MLOps:
  - El LLM se usa **solo** para el campo `suggested_angle`, no para ranking.
    Mantenerlo así preserva reproducibilidad: el ranking siempre será el
    mismo dadas las mismas señales (semilla algorítmica).
  - `persona_alignment` es un dict de keywords ponderadas. Cuando tengamos
    análisis posterior (qué brief produjo videos de mejor retención),
    podemos actualizar pesos vía bandit. (Ver evolve_persona_weights.)
  - Retention window por defecto = 7 días. Si una señal sigue apareciendo
    cada día, su frecuencia compuesta destaca naturalmente.

Mejoras futuras:
  - [ ] Reemplazar fuzzy 88 por embedding cosine ≥ 0.85 (sentence-transformers).
  - [ ] Bandit Thompson sampling para `persona_alignment` weights.
  - [ ] Considerar serie temporal: novedad vs. retorno cíclico (ej. AOT
        rumores cada N meses) — flag cíclico vs. flag breakout.
  - [ ] Cuando un brief produce un video con retention > target, marcar
        en persona_briefs.consumed_at + outcome → realimentar peso.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import Settings

log = logging.getLogger(__name__)


# ── Configuración por persona ────────────────────────────────────────
# Cada persona tiene afinidad con dominios + keywords boost.
# Pesos en [0, 1.5]. Editables on-the-fly; futuras versiones via bandit.

PERSONA_ALIGNMENT: dict[str, dict] = {
    "deep_mind": {
        "domains": {
            "anime_manga": 1.0,
            "movies_tv":   1.2,
            "gaming":      0.7,   # gaming sí, pero perfil analítico
            "music":       0.5,
            "latam":       0.4,
        },
        # Keywords que disparan boost (lowercase match en title+summary).
        "keywords_boost": {
            "philosophy":   1.4, "existential": 1.3, "tragedy": 1.3,
            "antihero":     1.3, "villain":     1.2, "morality": 1.3,
            "psychology":   1.2, "analysis":    1.1, "essay":   1.1,
            "kubrick":      1.3, "tarkovsky":   1.3, "berserk": 1.3,
            "vagabond":     1.3, "monster":     1.3, "vinland": 1.2,
        },
        # Penalización de fuentes muy ligeras
        "source_weight": {
            "ann_features":      1.2,
            "animefeminist":     1.1,
            "polygon":           1.1,
            "letterboxd_weekly": 1.2,
            "reddit_r_TrueFilm": 1.3,
            "steam_charts":      0.6,
            "reddit_r_Games":    0.7,
        },
    },
    "pop_oracle": {
        "domains": {
            "anime_manga": 1.0,
            "movies_tv":   1.0,
            "gaming":      1.3,   # gaming es su zona
            "music":       0.9,
            "latam":       0.5,
        },
        "keywords_boost": {
            "viral":       1.3, "trending":   1.3, "leak":      1.3,
            "controversy": 1.2, "drama":      1.2, "tier list": 1.2,
            "meta":        1.1, "release":    1.1, "rumor":     1.2,
            "esports":     1.2, "stream":     1.1, "speedrun":  1.1,
        },
        "source_weight": {
            "steam_charts":      1.3,
            "opencritic":        1.2,
            "ign_games":         1.2,
            "reddit_r_Games":    1.2,
            "reddit_r_anime":    1.1,
            "ann_features":      0.8,  # demasiado serio para Pop Oracle
        },
    },
    "latam": {
        "domains": {
            "latam":       1.5,
            "movies_tv":   1.0,
            "music":       1.1,
            "anime_manga": 0.6,
            "gaming":      0.5,
        },
        "keywords_boost": {
            "novela":      1.4, "telenovela": 1.4, "latino":     1.3,
            "regueton":    1.2, "reggaeton":  1.2, "narco":      1.2,
            "colombiana":  1.3, "mexicana":   1.3, "spanish":    1.2,
            "españa":      1.2, "iberia":     1.1, "festival":   1.0,
        },
        "source_weight": {
            "letterboxd_weekly": 1.0,
            "variety":           0.8,
            "deadline":          0.8,
        },
    },
}


# ── Distill ──────────────────────────────────────────────────────────


@dataclass
class _Cluster:
    """Cluster intermedio antes de scorear."""
    key: str                  # normalized_title canónico
    headline: str             # mejor título crudo del cluster
    domain: str
    signal_ids: list[int]
    fuentes: set
    recency_ts: float         # max(fetched_at) del cluster
    raw_frequency: int
    sources_text: str         # concatenación de title+summary para keyword boost


def _load_recent_signals(conn: sqlite3.Connection, window_days: int = 7) -> list[sqlite3.Row]:
    """Trae señales recientes ordenadas por fetched_at desc."""
    cutoff = (datetime.now() - timedelta(days=window_days)).isoformat()
    cur = conn.execute(
        """SELECT id, source, source_type, domain, title, normalized_title,
                  summary, raw_score, fetched_at
           FROM market_signals
           WHERE fetched_at >= ?
           ORDER BY fetched_at DESC""",
        (cutoff,),
    )
    return cur.fetchall()


def _fuzzy_merge_clusters(clusters: dict[str, _Cluster]) -> dict[str, _Cluster]:
    """Capa 2: junta clusters con normalized_title muy similares.

    Usa rapidfuzz si está disponible; si no, no hace nada (fail-soft).
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        log.info("rapidfuzz no instalado — skip fuzzy merge")
        return clusters

    keys = list(clusters.keys())
    merged: dict[str, _Cluster] = {}
    used: set[str] = set()

    for i, k in enumerate(keys):
        if k in used:
            continue
        canonical = clusters[k]
        for k2 in keys[i + 1:]:
            if k2 in used:
                continue
            ratio = fuzz.token_set_ratio(k, k2)
            if ratio >= 88:
                other = clusters[k2]
                canonical.signal_ids.extend(other.signal_ids)
                canonical.fuentes.update(other.fuentes)
                canonical.recency_ts = max(canonical.recency_ts, other.recency_ts)
                canonical.raw_frequency += other.raw_frequency
                canonical.sources_text += " " + other.sources_text
                used.add(k2)
        used.add(k)
        merged[canonical.key] = canonical
    return merged


def _build_clusters(rows: list[sqlite3.Row]) -> dict[str, _Cluster]:
    """Agrupa filas por normalized_title (capa 1)."""
    clusters: dict[str, _Cluster] = {}
    for r in rows:
        key = r["normalized_title"]
        if not key:
            continue
        fetched_ts = _parse_ts(r["fetched_at"])
        if key in clusters:
            c = clusters[key]
            c.signal_ids.append(r["id"])
            c.fuentes.add(r["source"])
            c.recency_ts = max(c.recency_ts, fetched_ts)
            c.raw_frequency += 1
            c.sources_text += f" {r['title']} {r['summary'] or ''}"
        else:
            clusters[key] = _Cluster(
                key=key,
                headline=r["title"],
                domain=r["domain"] or "movies_tv",
                signal_ids=[r["id"]],
                fuentes={r["source"]},
                recency_ts=fetched_ts,
                raw_frequency=1,
                sources_text=f"{r['title']} {r['summary'] or ''}",
            )
    return clusters


def _parse_ts(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _score_cluster(c: _Cluster, persona: str, now_ts: float) -> float:
    """Score determinista por persona.

    Componentes (todos en [0, ~2]):
      - freq_norm: log(1 + raw_frequency)
      - recency: decay exponencial con vida media de 36h
      - cross_source_bonus: log(1 + n_fuentes) * 0.5
      - domain_weight: PERSONA_ALIGNMENT[persona][domains][c.domain]
      - keyword_boost: producto de boosts (cap a 2.0)
      - source_weight: promedio de pesos por fuente (default 1.0)
    """
    import math

    align = PERSONA_ALIGNMENT.get(persona, {})
    domain_w = align.get("domains", {}).get(c.domain, 0.7)
    kw_boosts = align.get("keywords_boost", {})
    src_weights = align.get("source_weight", {})

    freq_norm = math.log(1 + c.raw_frequency)

    age_hours = max(0.0, (now_ts - c.recency_ts) / 3600.0)
    recency = math.exp(-age_hours / 36.0)  # vida media 36h

    cross = math.log(1 + len(c.fuentes)) * 0.5

    text_lower = c.sources_text.lower()
    kw = 1.0
    for w, boost in kw_boosts.items():
        if w in text_lower:
            kw *= boost
    kw = min(kw, 2.0)

    src_w_vals = [src_weights.get(s, 1.0) for s in c.fuentes]
    src_w = sum(src_w_vals) / len(src_w_vals) if src_w_vals else 1.0

    score = freq_norm * recency * domain_w * kw * src_w + cross
    return float(score)


# ── LLM para el suggested_angle (opcional, controlable) ──────────────


_ANGLE_PROMPT = """Tarea: en UNA frase (máximo 22 palabras, en español),
proponer el ángulo narrativo más interesante para hacer un short sobre
este tema, alineado con la voz de la persona indicada.

Persona: {persona} ({persona_desc})
Tema: {headline}
Dominio: {domain}
Contexto (titulares cruzados): {context}

Devuelve solo la frase, sin comillas ni preámbulos."""


_PERSONA_DESC = {
    "deep_mind":  "voz analítica, filosófica, cine educativo profundo",
    "pop_oracle": "voz ágil, pop, irónica, ritmo alto",
    "latam":     "voz cálida, conversacional, español latino, novela y cine LatAm",
}


def _llm_angle(llm, brief_headline: str, persona: str, domain: str,
                context: str) -> str | None:
    """Genera la frase angle. Devuelve None si el LLM no está disponible."""
    if llm is None:
        return None
    try:
        prompt = _ANGLE_PROMPT.format(
            persona=persona,
            persona_desc=_PERSONA_DESC.get(persona, ""),
            headline=brief_headline[:160],
            domain=domain,
            context=context[:600],
        )
        out = llm.generate(prompt, task_type="analysis", max_tokens=60, temperature=0.6)
        if out:
            return out.strip().replace("\n", " ")[:240]
    except Exception as e:
        log.warning("[distiller] LLM angle failed: %s", e)
    return None


# ── Distill principal ───────────────────────────────────────────────


def distill(
    conn: sqlite3.Connection,
    settings=None,
    window_days: int = 7,
    top_per_persona: int = 12,
    use_llm: bool = True,
) -> int:
    """Pipeline completa: produce briefs y los persiste.

    Args:
        window_days: ventana de señales a considerar.
        top_per_persona: cuántos briefs por persona persistir.
        use_llm: si True, llama al LLM para suggested_angle de cada brief.

    Returns:
        Total de briefs insertados.
    """
    rows = _load_recent_signals(conn, window_days)
    log.info("[distill] %d señales en ventana de %dd", len(rows), window_days)
    if not rows:
        return 0

    clusters = _build_clusters(rows)
    log.info("[distill] %d clusters (capa 1)", len(clusters))
    clusters = _fuzzy_merge_clusters(clusters)
    log.info("[distill] %d clusters (post-fuzzy)", len(clusters))

    now_ts = datetime.now().timestamp()
    llm = None
    if use_llm:
        try:
            from integrations.llm_provider import LLMProvider
            llm = LLMProvider(settings, conn=conn) if settings else None
        except Exception as e:
            log.warning("[distill] LLM no disponible: %s", e)

    total_inserted = 0
    for persona in PERSONA_ALIGNMENT:
        scored: list[tuple[float, _Cluster]] = []
        for c in clusters.values():
            s = _score_cluster(c, persona, now_ts)
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_per_persona]

        for score, c in top:
            angle = None
            if llm is not None:
                # Construir contexto desde varios títulos del cluster
                ctx = " | ".join(c.sources_text.split()[:80])
                angle = _llm_angle(llm, c.headline, persona, c.domain, ctx)

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO persona_briefs
                         (persona, cluster_key, headline, domain, score,
                          frequency, sources_json, suggested_angle)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        persona,
                        c.key,
                        c.headline[:300],
                        c.domain,
                        round(score, 4),
                        c.raw_frequency,
                        json.dumps(c.signal_ids),
                        angle,
                    ),
                )
                if conn.total_changes:
                    total_inserted += 1
            except sqlite3.Error as e:
                log.warning("[distill] insert brief failed: %s", e)
        conn.commit()
        log.info("[distill][%s] top=%d briefs", persona, len(top))

    return total_inserted


# ── Lectura para downstream (content_rotator, script_generator) ────


def fetch_briefs_for_persona(
    conn: sqlite3.Connection,
    persona: str,
    limit: int = 10,
    only_unconsumed: bool = True,
    min_score: float = 0.0,
) -> list[dict]:
    """Lista los mejores briefs disponibles para una persona.

    `only_unconsumed=True` filtra los que aún no produjeron un video
    (consumed_at IS NULL). El content_rotator marca consumed_at cuando
    selecciona un brief, evitando reprocessar.
    """
    sql = (
        "SELECT id, persona, cluster_key, headline, domain, score, frequency, "
        "       sources_json, suggested_angle, created_at "
        "FROM persona_briefs WHERE persona = ? AND score >= ? "
    )
    params: list = [persona, min_score]
    if only_unconsumed:
        sql += "AND consumed_at IS NULL "
    sql += "ORDER BY score DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def mark_brief_consumed(conn: sqlite3.Connection, brief_id: int):
    """El content_rotator/produce_for_series llama esto tras producir el video."""
    conn.execute(
        "UPDATE persona_briefs SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (brief_id,),
    )
    conn.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from pathlib import Path
    from core.db import get_db
    conn = get_db(Path("data"))
    n = distill(conn, settings=None, use_llm=False)
    print(f"Inserted {n} briefs (LLM off)")
    for p in PERSONA_ALIGNMENT:
        for b in fetch_briefs_for_persona(conn, p, limit=5):
            print(f"  [{p}] {b['score']:.2f}  {b['headline']}")
