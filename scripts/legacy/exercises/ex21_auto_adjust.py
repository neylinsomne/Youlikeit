"""
ex21 - Auto-ajuste del pipeline basado en métricas reales.

Cierra el ciclo de aprendizaje:
  1. Lee métricas de ex19 (tus videos)
  2. Lee patrones de ex20 (competencia)
  3. Lee feedback de ex15 (reviews manuales)
  4. Ajusta automáticamente:
     - Pesos de scoring en ex09 (qué tipo de clips funcionan mejor)
     - Hashtags recomendados en ex08 (cuáles dan más engagement)
     - Estilos de edición preferidos (qué hook_type funciona)
     - Duración ideal de clips
     - Horarios de publicación

Los ajustes se guardan en data/learning_config.json y son leídos
por ex09, ex08, ex17 en las siguientes ejecuciones.

Uso:
  python src/main.py ex21
  python src/main.py ex21 --min-samples 5
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger


# ---------------------------------------------------------------------------
# Default scoring weights (same as ex09)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "semantic": 0.25,
    "viral": 0.25,
    "confidence": 0.20,
    "duration": 0.15,
    "text_relevance": 0.05,
    "novelty": 0.10,
}

DEFAULT_PREFS = {
    "ideal_duration_s": 5.0,
    "min_confidence": 70,
    "preferred_categories": [],       # populated from analytics
    "preferred_emotions": [],
    "preferred_edit_styles": [],
    "preferred_hook_types": [],
    "best_hashtags": [],              # populated from analytics
    "worst_hashtags": [],
    "best_upload_hours": [],          # populated from analytics
    "ideal_clip_count": 4,
}


# ---------------------------------------------------------------------------
# Learning logic
# ---------------------------------------------------------------------------

def _load_current_config(data_dir: Path) -> dict:
    """Load current learning config or create defaults."""
    config_path = data_dir / "learning_config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "weights": dict(DEFAULT_WEIGHTS),
        "preferences": dict(DEFAULT_PREFS),
        "cycle": 0,
        "last_updated": None,
    }


def _analyze_own_performance(conn) -> dict:
    """Analyze your own video metrics to find what works."""
    cur = conn.execute("""
        SELECT a.*, s.theme_query, s.quote_ids
        FROM analytics a
        LEFT JOIN shorts s ON a.short_id = s.id
        WHERE a.views > 0
        ORDER BY a.engagement_rate DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return {"has_data": False}

    # Split into top and bottom performers
    mid = max(1, len(rows) // 2)
    top = rows[:mid]
    bottom = rows[mid:]

    analysis = {"has_data": True, "total_videos": len(rows)}

    # Best hashtags
    hashtag_engagement: dict[str, list[float]] = {}
    for v in rows:
        try:
            tags = json.loads(v.get("hashtags_used", "[]") or "[]")
        except Exception:
            tags = []
        for tag in tags:
            if tag not in hashtag_engagement:
                hashtag_engagement[tag] = []
            hashtag_engagement[tag].append(v.get("engagement_rate", 0) or 0)

    if hashtag_engagement:
        sorted_tags = sorted(
            hashtag_engagement.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
            reverse=True,
        )
        analysis["best_hashtags"] = [t for t, _ in sorted_tags[:10]]
        analysis["worst_hashtags"] = [t for t, _ in sorted_tags[-5:] if len(_) >= 2]

    # Best songs
    song_engagement: dict[str, list[float]] = {}
    for v in rows:
        song = v.get("song_used", "") or ""
        if song:
            if song not in song_engagement:
                song_engagement[song] = []
            song_engagement[song].append(v.get("engagement_rate", 0) or 0)

    if song_engagement:
        sorted_songs = sorted(
            song_engagement.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
            reverse=True,
        )
        analysis["best_songs"] = [s for s, _ in sorted_songs[:5]]

    # Best upload times
    hour_engagement: dict[int, list[float]] = {}
    for v in rows:
        upload_time = v.get("upload_time", "")
        if upload_time and "T" in upload_time:
            try:
                hour = int(upload_time.split("T")[1][:2])
                if hour not in hour_engagement:
                    hour_engagement[hour] = []
                hour_engagement[hour].append(v.get("engagement_rate", 0) or 0)
            except Exception:
                pass

    if hour_engagement:
        sorted_hours = sorted(
            hour_engagement.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
            reverse=True,
        )
        analysis["best_hours"] = [h for h, _ in sorted_hours[:3]]

    # Average metrics
    analysis["avg_engagement"] = round(sum(v.get("engagement_rate", 0) or 0 for v in rows) / len(rows), 6)
    analysis["avg_views"] = round(sum(v.get("views", 0) or 0 for v in rows) / len(rows))
    analysis["top_avg_engagement"] = round(sum(v.get("engagement_rate", 0) or 0 for v in top) / len(top), 6) if top else 0

    return analysis


def _analyze_competitor_patterns(conn) -> dict:
    """Analyze competitor data to find successful patterns."""
    cur = conn.execute("""
        SELECT * FROM competitor_videos
        WHERE views > 100
        ORDER BY engagement_rate DESC
        LIMIT 100
    """)
    rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return {"has_data": False}

    analysis = {"has_data": True, "total_competitors": len(rows)}

    # Best hook types
    hook_engagement: dict[str, list[float]] = {}
    for v in rows:
        hook = v.get("detected_hook_type", "") or ""
        if hook:
            if hook not in hook_engagement:
                hook_engagement[hook] = []
            hook_engagement[hook].append(v.get("engagement_rate", 0) or 0)

    if hook_engagement:
        sorted_hooks = sorted(
            hook_engagement.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
            reverse=True,
        )
        analysis["best_hook_types"] = [h for h, _ in sorted_hooks[:3]]

    # Ideal duration
    top_vids = rows[:max(1, len(rows) // 5)]
    if top_vids:
        durations = [v.get("duration_s", 0) or 0 for v in top_vids if v.get("duration_s")]
        if durations:
            analysis["ideal_duration_s"] = round(sum(durations) / len(durations), 1)

    # Text on screen pattern
    text_count = sum(1 for v in top_vids if v.get("text_on_screen"))
    analysis["text_on_screen_pct"] = round(text_count / max(1, len(top_vids)) * 100)

    return analysis


def _analyze_review_feedback(conn) -> dict:
    """Analyze manual review feedback for patterns."""
    cur = conn.execute("""
        SELECT r.*, s.theme_query
        FROM reviews r
        JOIN shorts s ON r.short_id = s.id
        ORDER BY r.created_at DESC
        LIMIT 50
    """)
    rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        return {"has_data": False}

    approved = [r for r in rows if r.get("status") == "approved"]
    rejected = [r for r in rows if r.get("status") == "rejected"]

    analysis = {
        "has_data": True,
        "total_reviews": len(rows),
        "approved": len(approved),
        "rejected": len(rejected),
        "approval_rate": round(len(approved) / max(1, len(rows)) * 100, 1),
    }

    # Common rejection reasons
    if rejected:
        reasons = [r.get("reviewer_notes", "") for r in rejected if r.get("reviewer_notes")]
        analysis["rejection_notes"] = reasons[:10]

        # Preferred styles from approvals
        if approved:
            styles = [r.get("suggested_edit_style", "") for r in approved if r.get("suggested_edit_style")]
            analysis["preferred_styles"] = list(set(styles))[:5]

    return analysis


def _compute_adjustments(
    own_perf: dict,
    competitor: dict,
    reviews: dict,
    current_config: dict,
) -> tuple[dict, dict, list[dict]]:
    """
    Compute new weights and preferences based on all data sources.

    Returns: (new_weights, new_preferences, adjustment_log)
    """
    weights = dict(current_config.get("weights", DEFAULT_WEIGHTS))
    prefs = dict(current_config.get("preferences", DEFAULT_PREFS))
    log_entries = []

    # --- Adjust from own performance ---
    if own_perf.get("has_data"):
        # If our engagement is above average, boost the weights that correlate
        if own_perf.get("best_hashtags"):
            old = prefs.get("best_hashtags", [])
            prefs["best_hashtags"] = own_perf["best_hashtags"]
            log_entries.append({
                "metric": "best_hashtags",
                "old_value": len(old),
                "new_value": len(prefs["best_hashtags"]),
                "adjustment": "Updated from own analytics",
                "reason": f"Top hashtags by engagement from {own_perf.get('total_videos', 0)} videos",
            })

        if own_perf.get("worst_hashtags"):
            prefs["worst_hashtags"] = own_perf["worst_hashtags"]

        if own_perf.get("best_hours"):
            old = prefs.get("best_upload_hours", [])
            prefs["best_upload_hours"] = own_perf["best_hours"]
            log_entries.append({
                "metric": "best_upload_hours",
                "old_value": str(old),
                "new_value": str(prefs["best_upload_hours"]),
                "adjustment": "Updated from own analytics",
                "reason": "Hours with highest engagement rate",
            })

    # --- Adjust from competitor analysis ---
    if competitor.get("has_data"):
        if competitor.get("ideal_duration_s"):
            old = prefs["ideal_duration_s"]
            # Move toward competitor ideal by 30% (don't jump fully)
            new_dur = old * 0.7 + competitor["ideal_duration_s"] * 0.3
            prefs["ideal_duration_s"] = round(new_dur, 1)
            log_entries.append({
                "metric": "ideal_duration_s",
                "old_value": old,
                "new_value": prefs["ideal_duration_s"],
                "adjustment": "Blended with competitor data (30%)",
                "reason": f"Competitor top performers average {competitor['ideal_duration_s']}s",
            })

        if competitor.get("best_hook_types"):
            prefs["preferred_hook_types"] = competitor["best_hook_types"]
            log_entries.append({
                "metric": "preferred_hook_types",
                "old_value": 0,
                "new_value": len(prefs["preferred_hook_types"]),
                "adjustment": "Updated from competitor VLM analysis",
                "reason": f"Top hook types: {', '.join(prefs['preferred_hook_types'])}",
            })

    # --- Adjust from review feedback ---
    if reviews.get("has_data"):
        approval_rate = reviews.get("approval_rate", 50)

        if approval_rate < 40:
            # Too many rejections - boost confidence weight to prefer safer picks
            old = weights["confidence"]
            weights["confidence"] = min(0.35, old + 0.05)
            weights["viral"] = max(0.10, weights["viral"] - 0.05)
            log_entries.append({
                "metric": "scoring_weights",
                "old_value": old,
                "new_value": weights["confidence"],
                "adjustment": "Boosted confidence, reduced viral weight",
                "reason": f"Low approval rate ({approval_rate}%) - prefer safer, higher-confidence clips",
            })
        elif approval_rate > 80:
            # High approval - can be more adventurous
            old = weights["viral"]
            weights["viral"] = min(0.35, old + 0.03)
            weights["novelty"] = min(0.15, weights.get("novelty", 0.10) + 0.02)
            log_entries.append({
                "metric": "scoring_weights",
                "old_value": old,
                "new_value": weights["viral"],
                "adjustment": "Boosted viral and novelty weights",
                "reason": f"High approval rate ({approval_rate}%) - can take more risks",
            })

        if reviews.get("preferred_styles"):
            prefs["preferred_edit_styles"] = reviews["preferred_styles"]

    # Normalize weights to sum to 1
    total = sum(weights.values())
    if total > 0:
        weights = {k: round(v / total, 3) for k, v in weights.items()}

    return weights, prefs, log_entries


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    min_samples: int = 3,
) -> Path:
    log = build_logger("ex21", settings.output_dir / "logs" / "ex21.log")
    conn = get_db(settings.data_dir)

    current_config = _load_current_config(settings.data_dir)
    cycle = current_config.get("cycle", 0) + 1

    log.info("Learning cycle #%d starting...", cycle)

    # 1) Analyze all data sources
    own_perf = _analyze_own_performance(conn)
    competitor = _analyze_competitor_patterns(conn)
    reviews = _analyze_review_feedback(conn)

    has_enough_data = (
        (own_perf.get("total_videos", 0) >= min_samples) or
        (competitor.get("total_competitors", 0) >= min_samples) or
        (reviews.get("total_reviews", 0) >= min_samples)
    )

    if not has_enough_data:
        log.warning(
            "Not enough data for learning (need %d samples). "
            "Own: %d, Competitors: %d, Reviews: %d",
            min_samples,
            own_perf.get("total_videos", 0),
            competitor.get("total_competitors", 0),
            reviews.get("total_reviews", 0),
        )

    # 2) Compute adjustments (even with little data, make conservative changes)
    new_weights, new_prefs, adjustments = _compute_adjustments(
        own_perf, competitor, reviews, current_config,
    )

    # 3) Save updated config
    new_config = {
        "weights": new_weights,
        "preferences": new_prefs,
        "cycle": cycle,
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "data_sources": {
            "own_videos": own_perf.get("total_videos", 0),
            "competitors": competitor.get("total_competitors", 0),
            "reviews": reviews.get("total_reviews", 0),
        },
    }

    config_path = settings.data_dir / "learning_config.json"
    config_path.write_text(json.dumps(new_config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4) Log adjustments to DB
    for adj in adjustments:
        conn.execute("""
            INSERT INTO learning_log (cycle, metric, old_value, new_value, adjustment, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            cycle,
            adj["metric"],
            adj.get("old_value"),
            adj.get("new_value"),
            adj["adjustment"],
            adj["reason"],
        ))
    conn.commit()

    # 5) Report
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    txt_path = out_dir / f"ex21_learning_{ts}.txt"
    lines = [
        f"ex21 - Learning Cycle #{cycle}",
        "=" * 50,
        f"Data sources: {own_perf.get('total_videos', 0)} own, "
        f"{competitor.get('total_competitors', 0)} competitors, "
        f"{reviews.get('total_reviews', 0)} reviews",
        "",
        "Scoring weights:",
    ]

    for k, v in new_weights.items():
        old = current_config.get("weights", {}).get(k, v)
        delta = v - old
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "="
        lines.append(f"  {k}: {v:.3f} ({arrow} {delta:+.3f})")

    lines.append("")
    lines.append("Preferences:")
    lines.append(f"  Ideal duration: {new_prefs.get('ideal_duration_s', '?')}s")
    lines.append(f"  Best hashtags: {', '.join(new_prefs.get('best_hashtags', [])[:5]) or 'N/A'}")
    lines.append(f"  Best hours: {new_prefs.get('best_upload_hours', 'N/A')}")
    lines.append(f"  Hook types: {', '.join(new_prefs.get('preferred_hook_types', [])[:3]) or 'N/A'}")

    if adjustments:
        lines.append("")
        lines.append("Adjustments made:")
        for adj in adjustments:
            lines.append(f"  - {adj['metric']}: {adj['adjustment']}")
            lines.append(f"    Reason: {adj['reason']}")

    if reviews.get("has_data"):
        lines.append("")
        lines.append(f"Review feedback: {reviews['approval_rate']}% approval rate")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Learning cycle #%d complete. Config saved to %s", cycle, config_path)
    return txt_path
