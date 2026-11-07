"""
ex33 - ETL: Planificador de currículum con diversidad pedagógica.

Extract: lesson performance (ex32 knowledge_base) + distribución actual
Transform: Detectar gaps pedagógicos, proponer siguiente contenido
Load: curriculum_plan en SQLite

Principios de planificación:
  1. Diversidad: no repetir el mismo learning_type consecutivamente
  2. Performance: priorizar tipos que retienen mejor
  3. Cobertura: cubrir todos los curriculum_areas a lo largo del tiempo
  4. Feedback: ajustar según datos reales de retención/engagement
  5. Round-robin: si no hay datos suficientes, distribuir uniformemente

Estrategia de selección:
  score = (performance_weight * normalized_retention)
        + (diversity_weight * time_since_last_used)
        + (coverage_weight * (1 - area_coverage_ratio))

Uso:
  python src/main.py ex33
  python src/main.py ex33 --plan-size 10
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger
from utils.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEARNING_TYPES = [
    "critical_thinking", "emotional_intelligence", "ethics", "creativity",
    "resilience", "self_awareness", "empathy", "decision_making",
]

CURRICULUM_AREAS = ["character", "relationships", "society", "self", "conflict"]

CATEGORIES = ["villain", "romance", "motivational", "comedy", "action", "dramatic", "horror"]

EMOTIONS = ["anger", "joy", "sadness", "fear", "surprise", "disgust", "neutral"]

# Mapping: learning_type → suggested categories and themes
THEME_SUGGESTIONS: dict[str, list[dict]] = {
    "critical_thinking": [
        {"query": "plot twist revelación", "category": "dramatic"},
        {"query": "villano tiene razón", "category": "villain"},
        {"query": "dilema moral", "category": "dramatic"},
    ],
    "emotional_intelligence": [
        {"query": "momento emotivo", "category": "dramatic"},
        {"query": "despedida conmovedora", "category": "romance"},
        {"query": "reconciliación", "category": "romance"},
    ],
    "ethics": [
        {"query": "justicia vs venganza", "category": "villain"},
        {"query": "sacrificio heroico", "category": "action"},
        {"query": "corrupción poder", "category": "villain"},
    ],
    "creativity": [
        {"query": "solución ingeniosa", "category": "comedy"},
        {"query": "plan maestro", "category": "action"},
        {"query": "improvisación genial", "category": "comedy"},
    ],
    "resilience": [
        {"query": "nunca rendirse", "category": "motivational"},
        {"query": "levantarse después de caer", "category": "motivational"},
        {"query": "superar trauma", "category": "dramatic"},
    ],
    "self_awareness": [
        {"query": "momento de verdad consigo mismo", "category": "dramatic"},
        {"query": "aceptar quien eres", "category": "motivational"},
        {"query": "confrontar miedo interior", "category": "horror"},
    ],
    "empathy": [
        {"query": "entender al enemigo", "category": "villain"},
        {"query": "ponerse en lugar del otro", "category": "dramatic"},
        {"query": "compasión inesperada", "category": "romance"},
    ],
    "decision_making": [
        {"query": "decisión imposible", "category": "action"},
        {"query": "elegir entre dos males", "category": "dramatic"},
        {"query": "momento de no retorno", "category": "villain"},
    ],
}


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

def _extract_current_state(conn) -> dict:
    """
    Extract current state of the curriculum.

    Returns:
      - performance: learning_type → avg_retention, avg_engagement (from knowledge_base)
      - distribution: how many quotes/shorts of each type exist
      - recent_plan: last N items in curriculum_plan
      - published_types: sequence of learning_types in published shorts
    """
    # Performance insights from knowledge_base (saved by ex32)
    cur = conn.execute("""
        SELECT title, content, confidence
        FROM knowledge_base
        WHERE source = 'lesson_performance'
          AND category = 'insight'
          AND is_active = 1
        ORDER BY created_at DESC
    """)
    insights = [dict(r) for r in cur.fetchall()]

    # Parse performance data from insights
    performance: dict[str, dict] = {}
    for insight in insights:
        try:
            data = json.loads(insight.get("content", "{}"))
            lt = data.get("learning_type")
            if lt and lt not in performance:
                performance[lt] = {
                    "avg_retention": data.get("avg_retention", 0),
                    "avg_engagement": data.get("avg_engagement", 0),
                    "sample_size": data.get("sample_size", 0),
                    "confidence": insight.get("confidence", 0.5),
                }
        except (json.JSONDecodeError, TypeError):
            continue

    # Current distribution of classified quotes
    cur = conn.execute("""
        SELECT learning_type, curriculum_area, COUNT(*) as n
        FROM quotes
        WHERE learning_type IS NOT NULL
        GROUP BY learning_type, curriculum_area
    """)
    distribution: dict[str, int] = {}
    area_distribution: dict[str, int] = {}
    for r in cur.fetchall():
        lt = r["learning_type"]
        ca = r["curriculum_area"]
        distribution[lt] = distribution.get(lt, 0) + r["n"]
        area_distribution[ca] = area_distribution.get(ca, 0) + r["n"]

    # Recent curriculum plan entries
    cur = conn.execute("""
        SELECT position, suggested_query, target_learning_type,
               target_category, target_emotion, status
        FROM curriculum_plan
        ORDER BY position DESC
        LIMIT 20
    """)
    recent_plan = [dict(r) for r in cur.fetchall()]

    # Recent published shorts' learning types (for diversity tracking)
    cur = conn.execute("""
        SELECT s.id, s.quote_ids, s.created_at
        FROM shorts s
        WHERE s.status IN ('rendered', 'uploaded')
        ORDER BY s.created_at DESC
        LIMIT 20
    """)
    published = [dict(r) for r in cur.fetchall()]

    # Get learning_types for each published short
    published_types: list[str] = []
    for short in published:
        qids_json = short.get("quote_ids")
        if not qids_json:
            continue
        try:
            qids = json.loads(qids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not qids:
            continue
        placeholders = ",".join("?" * len(qids))
        cur = conn.execute(
            f"SELECT DISTINCT learning_type FROM quotes WHERE id IN ({placeholders}) AND learning_type IS NOT NULL",
            qids,
        )
        for r in cur.fetchall():
            published_types.append(r["learning_type"])

    return {
        "performance": performance,
        "distribution": distribution,
        "area_distribution": area_distribution,
        "recent_plan": recent_plan,
        "published_types": published_types,
    }


# ---------------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------------

def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize to 0-1."""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [0.5] * len(values)
    return [(v - mn) / (mx - mn) for v in values]


def _transform_plan(
    state: dict,
    plan_size: int = 10,
    perf_weight: float = 0.4,
    div_weight: float = 0.35,
    cov_weight: float = 0.25,
) -> list[dict]:
    """
    Generate a curriculum plan based on performance, diversity, and coverage.

    Score for each learning_type:
      score = perf_weight * norm_retention
            + div_weight * norm_recency_gap
            + cov_weight * norm_coverage_gap
    """
    performance = state["performance"]
    distribution = state["distribution"]
    area_dist = state["area_distribution"]
    published_types = state["published_types"]

    # Calculate scores for each learning type
    type_scores: dict[str, dict] = {}

    for lt in LEARNING_TYPES:
        perf = performance.get(lt, {})
        count_in_corpus = distribution.get(lt, 0)

        # Performance score (retention)
        ret = perf.get("avg_retention", 0)

        # Diversity: how many positions since this type was last used
        if lt in published_types:
            last_idx = published_types.index(lt)
            recency_gap = last_idx  # 0 = most recent, higher = longer ago
        else:
            recency_gap = len(published_types) + 5  # Never used = high gap

        # Coverage: how underrepresented is this type
        total_quotes = max(1, sum(distribution.values()))
        ideal_ratio = 1.0 / len(LEARNING_TYPES)
        actual_ratio = count_in_corpus / total_quotes
        coverage_gap = max(0, ideal_ratio - actual_ratio)

        type_scores[lt] = {
            "retention": ret,
            "recency_gap": recency_gap,
            "coverage_gap": coverage_gap,
            "corpus_count": count_in_corpus,
            "has_performance_data": bool(perf),
        }

    # Normalize each dimension
    retentions = [ts["retention"] for ts in type_scores.values()]
    gaps = [ts["recency_gap"] for ts in type_scores.values()]
    coverages = [ts["coverage_gap"] for ts in type_scores.values()]

    norm_ret = _normalize(retentions)
    norm_gap = _normalize(gaps)
    norm_cov = _normalize(coverages)

    for i, lt in enumerate(type_scores):
        ts = type_scores[lt]
        ts["norm_retention"] = norm_ret[i]
        ts["norm_recency"] = norm_gap[i]
        ts["norm_coverage"] = norm_cov[i]
        ts["score"] = (
            perf_weight * norm_ret[i]
            + div_weight * norm_gap[i]
            + cov_weight * norm_cov[i]
        )

    # Sort by score (highest first)
    ranked = sorted(type_scores.items(), key=lambda x: x[1]["score"], reverse=True)

    # Generate plan entries: cycle through ranked types
    plan: list[dict] = []
    used_in_plan: list[str] = []
    position = 1

    # Determine next position from existing plan
    existing_max = 0
    for entry in state.get("recent_plan", []):
        existing_max = max(existing_max, entry.get("position", 0))

    while len(plan) < plan_size:
        # Pick the best type not recently used in this plan
        chosen_lt = None
        for lt, scores in ranked:
            if lt not in used_in_plan[-3:]:  # Don't repeat in last 3
                chosen_lt = lt
                break
        if not chosen_lt:
            chosen_lt = ranked[0][0]  # Fallback

        used_in_plan.append(chosen_lt)

        # Pick a theme suggestion
        suggestions = THEME_SUGGESTIONS.get(chosen_lt, [])
        suggestion_idx = (len(plan)) % max(1, len(suggestions))
        suggestion = suggestions[suggestion_idx] if suggestions else {
            "query": chosen_lt.replace("_", " "),
            "category": "dramatic",
        }

        # Determine curriculum area
        lt_to_area = {
            "critical_thinking": "society",
            "emotional_intelligence": "character",
            "ethics": "conflict",
            "creativity": "character",
            "resilience": "self",
            "self_awareness": "self",
            "empathy": "relationships",
            "decision_making": "conflict",
        }

        # Pick emotion that complements the learning type
        emotion_map = {
            "critical_thinking": "surprise",
            "emotional_intelligence": "sadness",
            "ethics": "anger",
            "creativity": "joy",
            "resilience": "fear",
            "self_awareness": "neutral",
            "empathy": "sadness",
            "decision_making": "fear",
        }

        scores = type_scores[chosen_lt]
        rationale_parts = []
        if scores["has_performance_data"]:
            rationale_parts.append(f"retention={scores['retention']:.1f}%")
        rationale_parts.append(f"diversity_score={scores['norm_recency']:.2f}")
        rationale_parts.append(f"coverage_gap={scores['norm_coverage']:.2f}")
        rationale_parts.append(f"total_score={scores['score']:.3f}")

        plan.append({
            "position": existing_max + position,
            "suggested_query": suggestion["query"],
            "target_learning_type": chosen_lt,
            "target_category": suggestion.get("category", "dramatic"),
            "target_emotion": emotion_map.get(chosen_lt, "neutral"),
            "rationale": " | ".join(rationale_parts),
            "curriculum_area": lt_to_area.get(chosen_lt, "character"),
        })
        position += 1

    return plan


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def _load_plan(conn, plan: list[dict]):
    """Insert plan entries into curriculum_plan table."""
    for entry in plan:
        conn.execute("""
            INSERT INTO curriculum_plan
                (position, suggested_query, target_learning_type,
                 target_category, target_emotion, rationale, status)
            VALUES (?, ?, ?, ?, ?, ?, 'planned')
        """, (
            entry["position"],
            entry["suggested_query"],
            entry["target_learning_type"],
            entry["target_category"],
            entry["target_emotion"],
            entry["rationale"],
        ))


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    plan_size: int = 10,
) -> Path:
    log = build_logger("ex33", settings.output_dir / "logs" / "ex33.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex33")

    # ── EXTRACT ──
    tracker.extract_start()
    state = _extract_current_state(conn)

    # Enrich with Google Trends (what cinema topics are hot right now)
    # Also saves daily snapshot to DB for the frontend carrusel
    try:
        from apps.signals.trends import suggest_trending_queries, save_trends_to_db
        saved = save_trends_to_db(conn, geo="")
        if saved:
            log.info("Google Trends: %d topics saved to DB", saved)
        trending = suggest_trending_queries()
        if trending:
            state["trending_topics"] = trending
            log.info("Google Trends: %d trending cinema topics found", len(trending))
    except Exception:
        pass
    tracker.extract_done({
        "performance_types": len(state["performance"]),
        "classified_quotes": sum(state["distribution"].values()),
        "published_types": len(state["published_types"]),
        "existing_plan_entries": len(state["recent_plan"]),
    })
    log.info(
        "Extract: %d types with performance data, %d classified quotes, %d published types",
        len(state["performance"]),
        sum(state["distribution"].values()),
        len(state["published_types"]),
    )

    # ── TRANSFORM ──
    tracker.transform_start(f"Planning next {plan_size} shorts")
    plan = _transform_plan(state, plan_size=plan_size)
    tracker.transform_done({"plan_entries": len(plan)})

    # Diversity check: count unique types in plan
    plan_types = set(e["target_learning_type"] for e in plan)
    log.info("Plan diversity: %d unique types in %d entries", len(plan_types), len(plan))

    # ── LOAD ──
    tracker.load_start()
    _load_plan(conn, plan)
    conn.commit()
    tracker.load_done({"entries_saved": len(plan)})

    # Save insight about curriculum diversity
    conn.execute("""
        INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
        VALUES ('pattern', 'curriculum', ?, ?, 0.7, 'curriculum_planner')
    """, (
        f"Curriculum plan: {len(plan)} entries, {len(plan_types)} types",
        json.dumps({
            "plan_size": len(plan),
            "unique_types": len(plan_types),
            "type_coverage": round(len(plan_types) / len(LEARNING_TYPES) * 100, 1),
            "has_performance_data": len(state["performance"]) > 0,
        }, ensure_ascii=False),
    ))
    conn.commit()

    # ── REPORT ──
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"ex33_curriculum_{ts}.txt"

    lines = [
        "ex33 - Curriculum Plan",
        "=" * 60,
        f"Plan size: {len(plan)} shorts",
        f"Type diversity: {len(plan_types)}/{len(LEARNING_TYPES)} learning types",
        f"Performance data available: {'Yes' if state['performance'] else 'No (round-robin mode)'}",
        "",
        "─── Planned Content ───",
        "",
    ]

    for entry in plan:
        perf_data = state["performance"].get(entry["target_learning_type"], {})
        perf_str = f"ret={perf_data.get('avg_retention', '?')}%" if perf_data else "no data yet"

        lines.append(
            f"  #{entry['position']:2d}  [{entry['target_learning_type']:25s}]"
        )
        lines.append(
            f"       query: \"{entry['suggested_query']}\""
        )
        lines.append(
            f"       {entry['target_category']} | {entry['target_emotion']} | {perf_str}"
        )
        lines.append(
            f"       reason: {entry['rationale']}"
        )
        lines.append("")

    # Distribution summary
    lines.append("─── Current Distribution (quotes by learning_type) ───")
    total_q = max(1, sum(state["distribution"].values()))
    for lt in LEARNING_TYPES:
        count = state["distribution"].get(lt, 0)
        ideal = total_q / len(LEARNING_TYPES)
        bar = "█" * max(1, count * 40 // max(1, max(state["distribution"].values()) if state["distribution"] else 1))
        gap = "  ← UNDER" if count < ideal * 0.5 else ""
        lines.append(f"  {lt:25s} {count:4d} ({count/total_q*100:4.1f}%) {bar}{gap}")

    lines.append("")
    lines.append("─── Coverage by Curriculum Area ───")
    total_a = max(1, sum(state["area_distribution"].values()))
    for ca in CURRICULUM_AREAS:
        count = state["area_distribution"].get(ca, 0)
        lines.append(f"  {ca:15s} {count:4d} ({count/total_a*100:4.1f}%)")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    tracker.complete({
        "plan_entries": len(plan),
        "type_diversity": len(plan_types),
    })

    conn.close()
    log.info("Curriculum plan: %s", report_path)
    return report_path
