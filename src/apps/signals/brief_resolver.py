"""
Brief Resolver — puente entre persona_briefs (texto libre) y CATALOG (slugs producibles).

Razón de existir:
  El distiller no sabe nada de qué series podemos producir. Genera briefs como
  "Frieren ratings break MAL records" o "Spy x Family movie sequel announced".
  El content_rotator necesita decidir QUÉ SLUG del CATALOG renderizar.

Estrategia:
  1. Capa 1 — alias map manual (override exacto, máxima precisión)
  2. Capa 2 — token_set_ratio entre brief headline y CATALOG title (≥ 75)
  3. Capa 3 — match contra `series_themes`/aliases en DB (cuando exista)
  4. Si nada matchea → registrar en `unresolved_briefs_queue` para curación humana

API pública:
    from apps.signals.brief_resolver import resolve_brief, suggest_boost_for_slug

    slug = resolve_brief(brief, catalog_dict)           # → "frieren" | None
    boost = suggest_boost_for_slug(conn, slug, persona) # 0.0 .. 1.0

Notas MLOps:
  - El alias map es la única estructura tocable a mano. Cuando un brief queda
    sin matchear pero el equipo decide "sí, agréguenlo", se añade el alias
    aquí y se añade la entrada al CATALOG en content_rotator. Reducir esa
    fricción es el objetivo de `unresolved_briefs_queue`.
  - Boost saturado en [0, 1] para no dominar el score base del rotator.
  - Score combinado: rotator_score + brief_boost; ver content_rotator.score_candidate.

Mejoras futuras:
  - [ ] Capa 4: embeddings cosine ≥ 0.82 (sentence-transformers).
  - [ ] Bandit sobre alias_map: tracker de "qué alias produjo briefs útiles".
  - [ ] Auto-expandir CATALOG cuando un slug aparece N+ veces en
        unresolved_briefs_queue con score > 5.0 (con review humano).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from typing import Iterable

log = logging.getLogger(__name__)


# ── Alias map manual (override de máxima precisión) ─────────────────
# Clave: substring lowercased que aparece en el headline o cluster_key.
# Valor: slug EXACTO del CATALOG en content_rotator.py.
#
# Reglas de mantenimiento:
#   1. Solo añadir un alias si el slug existe en CATALOG (validar con
#      tests en docs/PENDING_TESTS.md → smoke_alias_map_consistency).
#   2. El matching es por substring → ordenado por longitud DESC, así que
#      'jujutsu kaisen' gana sobre 'kaisen' aunque ambos estén.
#   3. Preferir aliases cortos y distintivos (nombre del protagonista o
#      sigla canónica) sobre frases largas que también funcionarían.
#   4. Si una franquicia comparte personajes (e.g., Walter White ↔ Saul),
#      apuntar al slug más probable según el contexto editorial.
#
# Estructura: agrupado por dominio para revisión humana rápida.
# Si crece >120 entradas, mover a JSON/DB con UI de curación.

ALIAS_MAP: dict[str, str] = {
    # ──────────── ANIME / MANGA ────────────
    # Deep Mind canon
    "berserk":                  "berserk",
    "guts":                     "berserk",
    "griffith":                 "berserk",
    "golden age arc":           "berserk",

    "vinland saga":             "vinland_saga",
    "thorfinn":                 "vinland_saga",
    "askeladd":                 "vinland_saga",

    "monster":                  "monster",
    "kenzo tenma":              "monster",
    "johan liebert":            "monster",

    "death note":               "death_note",
    "light yagami":             "death_note",
    "kira":                     "death_note",
    "ryuk":                     "death_note",

    "neon genesis evangelion":  "neon_genesis_evangelion",
    "evangelion":               "neon_genesis_evangelion",
    "shinji ikari":             "neon_genesis_evangelion",
    "rebuild of evangelion":    "neon_genesis_evangelion",
    "nge":                      "neon_genesis_evangelion",

    "cowboy bebop":             "cowboy_bebop",
    "spike spiegel":            "cowboy_bebop",

    "attack on titan":          "attack_on_titan",
    "shingeki no kyojin":       "attack_on_titan",
    "aot":                      "attack_on_titan",
    "eren yeager":              "attack_on_titan",
    "eren jaeger":              "attack_on_titan",
    "levi ackerman":            "attack_on_titan",

    # Trending / Pop Oracle
    "jujutsu kaisen":           "jujutsu_kaisen",
    "jjk":                      "jujutsu_kaisen",
    "gojo":                     "jujutsu_kaisen",
    "sukuna":                   "jujutsu_kaisen",
    "yuji itadori":             "jujutsu_kaisen",

    "chainsaw man":             "chainsaw_man",
    "denji":                    "chainsaw_man",
    "makima":                   "chainsaw_man",
    "power":                    "chainsaw_man",   # ambiguo, pero contexto chainsaw es probable

    "solo leveling":            "solo_leveling",
    "sung jin-woo":             "solo_leveling",
    "sung jin woo":             "solo_leveling",

    "frieren":                  "frieren",
    "sousou no frieren":        "frieren",
    "beyond journey":           "frieren",
    "fern":                     "frieren",
    "stark":                    "frieren",        # contexto frieren

    "oshi no ko":               "oshi_no_ko",
    "aqua hoshino":             "oshi_no_ko",
    "ruby hoshino":             "oshi_no_ko",
    "ai hoshino":               "oshi_no_ko",

    "one piece":                "one_piece",
    "monkey d luffy":           "one_piece",
    "luffy":                    "one_piece",
    "zoro":                     "one_piece",
    "sanji":                    "one_piece",
    "egghead arc":              "one_piece",
    "wano":                     "one_piece",

    # ──────────── CINE / TV — ANTIHÉROES (Deep Mind) ────────────
    "breaking bad":             "breaking_bad",
    "walter white":             "breaking_bad",
    "heisenberg":               "breaking_bad",
    "jesse pinkman":            "breaking_bad",
    "los pollos hermanos":      "breaking_bad",

    "better call saul":         "better_call_saul",
    "saul goodman":             "better_call_saul",
    "jimmy mcgill":             "better_call_saul",
    "kim wexler":               "better_call_saul",

    "fight club":               "fight_club",
    "tyler durden":             "fight_club",
    "first rule of fight club": "fight_club",

    "hannibal":                 "hannibal",
    "hannibal lecter":          "hannibal",
    "will graham":              "hannibal",
    "mads mikkelsen":           "hannibal",
    "silence of the lambs":     "hannibal",

    "american psycho":          "american_psycho",
    "patrick bateman":          "american_psycho",
    "christian bale":           "american_psycho",  # contexto bateman

    "no country for old men":   "no_country_for_old_men",
    "anton chigurh":             "no_country_for_old_men",
    "javier bardem":            "no_country_for_old_men",
    "coen brothers":            "no_country_for_old_men",

    "there will be blood":      "there_will_be_blood",
    "daniel plainview":         "there_will_be_blood",
    "paul thomas anderson":     "there_will_be_blood",
    "i drink your milkshake":   "there_will_be_blood",

    "joker":                    "joker",
    "arthur fleck":             "joker",
    "joaquin phoenix":          "joker",

    "the dark knight":          "the_dark_knight",
    "heath ledger joker":       "the_dark_knight",
    "why so serious":           "the_dark_knight",
    "harvey dent":              "the_dark_knight",

    "taxi driver":              "taxi_driver",
    "travis bickle":            "taxi_driver",
    "you talkin to me":         "taxi_driver",

    # ──────────── LATAM · TELENOVELAS (Voz Latina) ────────────
    "yo soy betty la fea":      "yo_soy_betty_la_fea",
    "betty la fea":             "yo_soy_betty_la_fea",
    "ugly betty":               "yo_soy_betty_la_fea",
    "beatriz pinzon":           "yo_soy_betty_la_fea",
    "armando mendoza":          "yo_soy_betty_la_fea",

    "la casa de las flores":    "la_casa_de_las_flores",
    "house of flowers":         "la_casa_de_las_flores",
    "manolo caro":              "la_casa_de_las_flores",
    "paulina de la mora":       "la_casa_de_las_flores",

    "pasion de gavilanes":      "pasion_de_gavilanes",
    "pasión de gavilanes":      "pasion_de_gavilanes",
    "hermanos reyes":           "pasion_de_gavilanes",
    "norma elizondo":           "pasion_de_gavilanes",

    "el senor de los cielos":   "el_senor_de_los_cielos",
    "el señor de los cielos":   "el_senor_de_los_cielos",
    "aurelio casillas":         "el_senor_de_los_cielos",
    "rafael amaya":             "el_senor_de_los_cielos",

    "rubi":                     "rubi",
    "rubí":                     "rubi",
    "barbara mori":             "rubi",

    "la reina del sur":         "la_reina_del_sur",
    "teresa mendoza":           "la_reina_del_sur",
    "kate del castillo":        "la_reina_del_sur",

    "sin senos si hay paraiso": "sin_senos_si_hay_paraiso",
    "sin senos sí hay paraíso": "sin_senos_si_hay_paraiso",
    "catalina santana":         "sin_senos_si_hay_paraiso",

    "la rosa de guadalupe":     "la_rosa_de_guadalupe",
    "rosa de guadalupe":        "la_rosa_de_guadalupe",

    # ──────────── GAMING (Pop Oracle + Deep Mind) ────────────
    # Trending / Pop Oracle
    "elden ring":               "elden_ring",
    "shadow of the erdtree":    "elden_ring",
    "tarnished":                "elden_ring",
    "miquella":                 "elden_ring",
    "malenia":                  "elden_ring",
    "radahn":                   "elden_ring",

    "baldurs gate 3":           "baldurs_gate_3",
    "baldur's gate 3":          "baldurs_gate_3",
    "bg3":                      "baldurs_gate_3",
    "astarion":                 "baldurs_gate_3",
    "shadowheart":              "baldurs_gate_3",
    "larian":                   "baldurs_gate_3",

    "helldivers 2":             "helldivers_2",
    "helldivers":               "helldivers_2",
    "arrowhead studios":        "helldivers_2",
    "for democracy":            "helldivers_2",

    "black myth wukong":        "black_myth_wukong",
    "black myth: wukong":       "black_myth_wukong",
    "wukong":                   "black_myth_wukong",
    "game science":             "black_myth_wukong",

    "stalker 2":                "stalker_2",
    "s.t.a.l.k.e.r. 2":         "stalker_2",
    "heart of chornobyl":       "stalker_2",
    "gsc game world":           "stalker_2",
    "the zone":                 "stalker_2",

    "path of exile 2":          "path_of_exile_2",
    "poe2":                     "path_of_exile_2",
    "grinding gear games":      "path_of_exile_2",

    "marvel rivals":            "marvel_rivals",
    "netease":                  "marvel_rivals",   # contexto marvel rivals probable

    "hollow knight silksong":   "hollow_knight_silksong",
    "silksong":                 "hollow_knight_silksong",
    "team cherry":              "hollow_knight_silksong",
    "hornet":                   "hollow_knight_silksong",

    "persona 5":                "persona_5",
    "joker persona":            "persona_5",
    "phantom thieves":          "persona_5",
    "atlus":                    "persona_5",      # contexto persona probable

    "stardew valley":           "stardew_valley",
    "concernedape":              "stardew_valley",
    "pelican town":             "stardew_valley",

    "hades 2":                  "hades_2",
    "hades ii":                 "hades_2",
    "supergiant games":         "hades_2",
    "melinoë":                  "hades_2",
    "melinoe":                  "hades_2",

    # Critical / Deep Mind canon
    "bloodborne":               "bloodborne",
    "yharnam":                  "bloodborne",
    "hunter's dream":           "bloodborne",
    "bloodborne pc port":       "bloodborne",

    "disco elysium":            "disco_elysium",
    "harry du bois":            "disco_elysium",
    "kim kitsuragi":            "disco_elysium",
    "za/um":                    "disco_elysium",

    "outer wilds":              "outer_wilds",
    "mobius digital":           "outer_wilds",
    "echoes of the eye":        "outer_wilds",

    "silent hill 2":            "silent_hill_2",
    "silent hill 2 remake":     "silent_hill_2",
    "james sunderland":         "silent_hill_2",
    "pyramid head":             "silent_hill_2",
    "bloober team":             "silent_hill_2",
}


# ── Consistencia interna del ALIAS_MAP ──────────────────────────────


def validate_alias_map(catalog: dict) -> list[str]:
    """Devuelve lista de errores: aliases que apuntan a slugs fuera del CATALOG.

    Diseñado para correrse en CI / smoke test al cargar el módulo.
    Si ALIAS_MAP queda inconsistente (renombran un slug, eliminan una entrada),
    los aliases huérfanos quedarían silenciosamente ignorados — esta función
    los hace ruidosos.

    Uso:
        from apps.signals.brief_resolver import ALIAS_MAP, validate_alias_map
        from apps.production.content_rotator import CATALOG
        errors = validate_alias_map(CATALOG)
        assert not errors, errors
    """
    errors = []
    for alias, slug in ALIAS_MAP.items():
        if slug not in catalog:
            errors.append(
                f"alias '{alias}' → '{slug}' (no existe en CATALOG)"
            )
    return errors


def alias_map_stats(catalog: dict) -> dict:
    """Estadística de cobertura del ALIAS_MAP por slug.

    Útil para detectar slugs sin aliases (probablemente no van a matchear
    nunca y solo se elegirán por catalog-only score).
    """
    from collections import Counter
    slug_counts = Counter(ALIAS_MAP.values())
    uncovered = [s for s in catalog if s not in slug_counts]
    return {
        "total_aliases":         len(ALIAS_MAP),
        "slugs_with_aliases":    len(slug_counts),
        "slugs_total_in_catalog": len(catalog),
        "coverage_pct":          round(100 * len(slug_counts) / max(1, len(catalog)), 1),
        "uncovered_slugs":       uncovered,
        "top_aliased":           slug_counts.most_common(10),
    }


# ── Resolver ────────────────────────────────────────────────────────


_PUNCT_RE = re.compile(r"[^\w\s]")


def _norm(s: str) -> str:
    """Lowercase + strip puntuación + colapso espacios. Igual que market_signals."""
    s = (s or "").lower()
    s = _PUNCT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _match_alias_map(headline_norm: str) -> str | None:
    """Capa 1: alias map. Devuelve slug o None."""
    # Ordenar por longitud descendente para que 'jujutsu kaisen' gane sobre 'kaisen'
    for alias in sorted(ALIAS_MAP.keys(), key=len, reverse=True):
        if alias in headline_norm:
            return ALIAS_MAP[alias]
    return None


def _match_catalog_fuzzy(headline_norm: str, catalog: dict, threshold: int = 75) -> str | None:
    """Capa 2: rapidfuzz token_set_ratio contra CATALOG titles."""
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return None
    best_slug = None
    best_score = 0
    for slug, entry in catalog.items():
        title_norm = _norm(entry.get("title", ""))
        if not title_norm:
            continue
        score = fuzz.token_set_ratio(headline_norm, title_norm)
        if score > best_score:
            best_score = score
            best_slug = slug
    return best_slug if best_score >= threshold else None


def _match_series_themes(conn: sqlite3.Connection, headline_norm: str) -> str | None:
    """Capa 3: tabla series_themes en DB (slugs ya clasificados)."""
    try:
        cur = conn.execute("SELECT DISTINCT series_slug FROM series_themes")
        rows = cur.fetchall()
    except sqlite3.Error:
        return None
    for r in rows:
        slug = r[0] if isinstance(r, tuple) else r["series_slug"]
        slug_words = slug.replace("_", " ").lower()
        if slug_words and slug_words in headline_norm:
            return slug
    return None


def resolve_brief(
    brief: dict,
    catalog: dict,
    conn: sqlite3.Connection | None = None,
    fuzzy_threshold: int = 75,
) -> tuple[str | None, str]:
    """Resuelve un brief a un slug del CATALOG.

    Args:
        brief: dict con al menos 'headline' o 'cluster_key'.
        catalog: dict slug → entry (de content_rotator.CATALOG).
        conn: opcional, para capa 3.

    Returns:
        (slug | None, layer): layer indica qué capa matcheó
                              ('alias' | 'fuzzy' | 'series_themes' | 'unresolved').
    """
    headline_norm = _norm(brief.get("headline", "") or brief.get("cluster_key", ""))
    if not headline_norm:
        return None, "empty"

    slug = _match_alias_map(headline_norm)
    if slug and slug in catalog:
        return slug, "alias"

    slug = _match_catalog_fuzzy(headline_norm, catalog, threshold=fuzzy_threshold)
    if slug and slug in catalog:
        return slug, "fuzzy"

    if conn is not None:
        slug = _match_series_themes(conn, headline_norm)
        if slug:
            return slug, "series_themes"

    return None, "unresolved"


# ── Boost para el rotator ───────────────────────────────────────────


def suggest_boost_for_slug(
    conn: sqlite3.Connection,
    slug: str,
    persona: str,
    catalog: dict,
    max_briefs: int = 5,
    decay_per_brief: float = 0.7,
) -> tuple[float, list[int]]:
    """Calcula boost [0, 1] para un slug basado en briefs vivos.

    El boost suma `score / 5.0` por cada brief de esa persona que resuelve
    al slug, con decay para evitar dominar.

    Returns:
        (boost, brief_ids_consumed): lista de IDs de briefs que contribuyeron
                                     (el rotator los marca consumed_at al usarlos).
    """
    try:
        from apps.signals.signals_distiller import fetch_briefs_for_persona
    except ImportError:
        return 0.0, []

    briefs = fetch_briefs_for_persona(
        conn, persona, limit=20, only_unconsumed=True,
    )
    matched_ids: list[int] = []
    boost = 0.0
    multiplier = 1.0
    for b in briefs:
        if len(matched_ids) >= max_briefs:
            break
        candidate_slug, _layer = resolve_brief(b, catalog, conn)
        if candidate_slug == slug:
            # Normalizar score del brief al rango [0, 1] aprox.
            # Distiller scores típicos: 0.5 .. 8.0 → / 5.0
            sub = min(1.0, max(0.0, (b.get("score", 0.0) or 0.0) / 5.0))
            boost += sub * multiplier
            matched_ids.append(b["id"])
            multiplier *= decay_per_brief

    return min(1.0, boost), matched_ids


# ── Queue de no-resueltos para curación humana ──────────────────────


SCHEMA_UNRESOLVED = """
CREATE TABLE IF NOT EXISTS unresolved_briefs_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id INTEGER NOT NULL,
    persona TEXT,
    headline TEXT,
    domain TEXT,
    score REAL,
    suggested_angle TEXT,
    queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed INTEGER DEFAULT 0,    -- 1 cuando humano decide (agregar/descartar)
    decision TEXT,                  -- 'added_to_catalog' | 'discarded' | NULL
    decision_notes TEXT,
    UNIQUE(brief_id)
);
CREATE INDEX IF NOT EXISTS idx_unresolved_reviewed ON unresolved_briefs_queue(reviewed, score DESC);
"""


def ensure_unresolved_schema(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_UNRESOLVED)
    conn.commit()


def enqueue_unresolved(conn: sqlite3.Connection, brief: dict, persona: str) -> bool:
    """Persiste un brief sin match para curación humana. Idempotente."""
    ensure_unresolved_schema(conn)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO unresolved_briefs_queue
                 (brief_id, persona, headline, domain, score, suggested_angle)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                brief["id"], persona,
                brief.get("headline", "")[:300],
                brief.get("domain"),
                float(brief.get("score", 0.0) or 0.0),
                brief.get("suggested_angle"),
            ),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        log.warning("enqueue_unresolved failed: %s", e)
        return False


def list_unresolved(
    conn: sqlite3.Connection,
    only_unreviewed: bool = True,
    min_score: float = 1.0,
    limit: int = 50,
) -> list[dict]:
    """Lista briefs sin match pendientes de decisión."""
    ensure_unresolved_schema(conn)
    sql = "SELECT * FROM unresolved_briefs_queue WHERE score >= ?"
    params: list = [min_score]
    if only_unreviewed:
        sql += " AND reviewed = 0"
    sql += " ORDER BY score DESC LIMIT ?"
    params.append(limit)
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def mark_unresolved_decision(
    conn: sqlite3.Connection, queue_id: int,
    decision: str, notes: str | None = None,
):
    """Marca un unresolved como revisado por humano."""
    assert decision in ("added_to_catalog", "discarded")
    conn.execute(
        """UPDATE unresolved_briefs_queue
           SET reviewed = 1, decision = ?, decision_notes = ?
           WHERE id = ?""",
        (decision, notes, queue_id),
    )
    conn.commit()


# ── Sweep helper: corre por todos los briefs vivos y encola los no-resueltos ──


def sweep_unresolved(conn: sqlite3.Connection, catalog: dict) -> dict:
    """Para cada persona, busca briefs unconsumed sin match y los encola.

    Útil correr después de cada `distill()` para mantener fresco el queue.

    Returns:
        dict con counts por persona.
    """
    from apps.signals.signals_distiller import fetch_briefs_for_persona, PERSONA_ALIGNMENT
    ensure_unresolved_schema(conn)
    report: dict = {}
    for persona in PERSONA_ALIGNMENT:
        briefs = fetch_briefs_for_persona(conn, persona, limit=30, only_unconsumed=True)
        n_unresolved = 0
        for b in briefs:
            slug, layer = resolve_brief(b, catalog, conn)
            if slug is None:
                if enqueue_unresolved(conn, b, persona):
                    n_unresolved += 1
        report[persona] = n_unresolved
    return report
