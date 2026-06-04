"""
ex23 - Análisis estadístico + metas automáticas.

Estadística interpretable, sin redes neuronales:
  - Regresión lineal: tendencia de métricas y proyección
  - R² y varianza explicada: cuánto entendemos del engagement
  - Information gain: qué features importan más
  - ANOVA simplificado: qué factor domina (hashtag vs hora vs categoría)
  - Metas automáticas: basadas en tendencia real, no fantasía

Todo con stdlib + math. Sin numpy/scipy/sklearn.

Uso:
  python src/main.py ex23
  python src/main.py ex23 --set-goal views_avg 1000 --deadline 2026-06-01
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger


# ---------------------------------------------------------------------------
# Statistics from scratch (no external deps)
# ---------------------------------------------------------------------------

def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _var(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return sum((x - m) ** 2 for x in vals) / (len(vals) - 1)


def _std(vals: list[float]) -> float:
    return math.sqrt(_var(vals))


def _correlation(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    mx, my = _mean(x[:n]), _mean(y[:n])
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den_x = sum((x[i] - mx) ** 2 for i in range(n))
    den_y = sum((y[i] - my) ** 2 for i in range(n))
    den = math.sqrt(den_x * den_y)
    return num / den if den > 0 else 0.0


def _linear_regression(x: list[float], y: list[float]) -> dict:
    """
    Simple linear regression: y = slope * x + intercept
    Returns slope, intercept, r_squared.
    """
    n = min(len(x), len(y))
    if n < 2:
        return {"slope": 0, "intercept": 0, "r_squared": 0, "n": n}

    mx, my = _mean(x[:n]), _mean(y[:n])
    ss_xy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    ss_xx = sum((x[i] - mx) ** 2 for i in range(n))

    if ss_xx == 0:
        return {"slope": 0, "intercept": my, "r_squared": 0, "n": n}

    slope = ss_xy / ss_xx
    intercept = my - slope * mx

    # R²
    y_pred = [slope * x[i] + intercept for i in range(n)]
    ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))
    ss_tot = sum((y[i] - my) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    return {
        "slope": round(slope, 8),
        "intercept": round(intercept, 6),
        "r_squared": round(r_squared, 4),
        "n": n,
    }


def _information_gain(feature_groups: dict[str, list[float]], all_values: list[float]) -> float:
    """
    Information gain of splitting by a categorical feature.
    Uses variance reduction (continuous target).

    IG = Var(all) - weighted_avg(Var(groups))

    Higher = feature explains more variance = more useful.
    """
    if not all_values or not feature_groups:
        return 0.0

    total_var = _var(all_values)
    n_total = len(all_values)

    weighted_var = 0.0
    for group_vals in feature_groups.values():
        if len(group_vals) >= 2:
            weight = len(group_vals) / n_total
            weighted_var += weight * _var(group_vals)

    return round(total_var - weighted_var, 8)


def _anova_f_ratio(groups: dict[str, list[float]]) -> dict:
    """
    One-way ANOVA F-ratio (simplified).
    Measures if group means are significantly different.

    Returns F-ratio and eta-squared (% variance explained by grouping).
    """
    all_vals = []
    for vals in groups.values():
        all_vals.extend(vals)

    if len(all_vals) < 3 or len(groups) < 2:
        return {"f_ratio": 0, "eta_squared": 0, "n_groups": len(groups)}

    grand_mean = _mean(all_vals)
    n_total = len(all_vals)
    k = len(groups)

    # Between-group sum of squares
    ss_between = sum(
        len(vals) * (_mean(vals) - grand_mean) ** 2
        for vals in groups.values()
        if vals
    )

    # Within-group sum of squares
    ss_within = sum(
        sum((x - _mean(vals)) ** 2 for x in vals)
        for vals in groups.values()
        if len(vals) >= 2
    )

    df_between = k - 1
    df_within = n_total - k

    if df_within <= 0 or df_between <= 0:
        return {"f_ratio": 0, "eta_squared": 0, "n_groups": k}

    ms_between = ss_between / df_between
    ms_within = ss_within / df_within

    f_ratio = ms_between / ms_within if ms_within > 0 else 0
    ss_total = ss_between + ss_within
    eta_squared = ss_between / ss_total if ss_total > 0 else 0

    return {
        "f_ratio": round(f_ratio, 4),
        "eta_squared": round(eta_squared, 4),
        "variance_explained_pct": round(eta_squared * 100, 1),
        "n_groups": k,
        "n_total": n_total,
    }


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def _analyze_trends(conn) -> dict:
    """Analyze trends over time using linear regression."""
    cur = conn.execute("""
        SELECT views, likes, engagement_rate, scraped_at
        FROM analytics
        WHERE views > 0
        ORDER BY scraped_at ASC
    """)
    rows = [dict(r) for r in cur.fetchall()]

    if len(rows) < 3:
        return {"has_data": False, "n": len(rows)}

    # Time index (0, 1, 2, ...)
    x = list(range(len(rows)))
    views = [r["views"] for r in rows]
    engagement = [r["engagement_rate"] for r in rows]

    views_reg = _linear_regression(x, views)
    eng_reg = _linear_regression(x, engagement)

    return {
        "has_data": True,
        "n": len(rows),
        "views_trend": {
            **views_reg,
            "direction": "up" if views_reg["slope"] > 0 else "down",
            "per_video_change": round(views_reg["slope"], 1),
            "interpretation": (
                f"Each new video gets ~{abs(views_reg['slope']):.0f} "
                f"{'more' if views_reg['slope'] > 0 else 'fewer'} views than the previous. "
                f"R²={views_reg['r_squared']:.2f} ({views_reg['r_squared']*100:.0f}% of the variance is explained by this trend)."
            ),
        },
        "engagement_trend": {
            **eng_reg,
            "direction": "up" if eng_reg["slope"] > 0 else "down",
            "interpretation": (
                f"Engagement {'increases' if eng_reg['slope'] > 0 else 'decreases'} "
                f"by {abs(eng_reg['slope']):.6f} per video. "
                f"R²={eng_reg['r_squared']:.2f}."
            ),
        },
        "current_avg_views": round(_mean(views[-5:])) if len(views) >= 5 else round(_mean(views)),
        "current_avg_engagement": round(_mean(engagement[-5:]), 6) if len(engagement) >= 5 else round(_mean(engagement), 6),
    }


def _analyze_feature_importance(conn) -> dict:
    """
    Which features explain the most variance in engagement?
    Uses information gain and ANOVA.
    """
    results = {}

    # 1. Category impact
    cur = conn.execute("""
        SELECT q.category, a.engagement_rate
        FROM analytics a
        JOIN shorts s ON a.short_id = s.id
        JOIN quotes q ON q.movie_id IS NOT NULL
        WHERE a.engagement_rate > 0 AND q.category IS NOT NULL
        LIMIT 200
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if rows:
        groups = {}
        all_vals = []
        for r in rows:
            cat = r.get("category", "unknown")
            eng = r["engagement_rate"]
            groups.setdefault(cat, []).append(eng)
            all_vals.append(eng)

        ig = _information_gain(groups, all_vals)
        anova = _anova_f_ratio(groups)
        results["category"] = {
            "information_gain": ig,
            "anova": anova,
            "group_means": {k: round(_mean(v), 6) for k, v in groups.items() if v},
        }

    # 2. Platform impact
    cur = conn.execute("""
        SELECT platform, engagement_rate
        FROM analytics WHERE engagement_rate > 0
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if rows:
        groups = {}
        all_vals = []
        for r in rows:
            groups.setdefault(r["platform"], []).append(r["engagement_rate"])
            all_vals.append(r["engagement_rate"])

        results["platform"] = {
            "information_gain": _information_gain(groups, all_vals),
            "anova": _anova_f_ratio(groups),
            "group_means": {k: round(_mean(v), 6) for k, v in groups.items()},
        }

    # 3. Song usage impact
    cur = conn.execute("""
        SELECT
            CASE WHEN song_used IS NOT NULL AND song_used != '' THEN 'with_song' ELSE 'no_song' END as has_song,
            engagement_rate
        FROM analytics WHERE engagement_rate > 0
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) >= 4:
        groups = {}
        all_vals = []
        for r in rows:
            groups.setdefault(r["has_song"], []).append(r["engagement_rate"])
            all_vals.append(r["engagement_rate"])

        results["song_usage"] = {
            "information_gain": _information_gain(groups, all_vals),
            "anova": _anova_f_ratio(groups),
            "group_means": {k: round(_mean(v), 6) for k, v in groups.items()},
        }

    # Rank features by information gain
    if results:
        ranked = sorted(results.items(), key=lambda x: x[1].get("information_gain", 0), reverse=True)
        results["ranking"] = [
            {"feature": k, "information_gain": v["information_gain"], "variance_explained_pct": v.get("anova", {}).get("variance_explained_pct", 0)}
            for k, v in ranked
        ]

    return results


def _set_auto_goals(conn, trends: dict) -> list[dict]:
    """Set realistic goals based on current trend."""
    goals = []

    if not trends.get("has_data"):
        return goals

    # Views goal: 50% increase in next 30 videos
    current_views = trends.get("current_avg_views", 0)
    if current_views > 0:
        slope = trends.get("views_trend", {}).get("slope", 0)
        # Project 30 videos ahead
        projected = current_views + slope * 30
        # Goal: max of 50% increase or projection, whichever is more ambitious
        target = max(current_views * 1.5, projected)

        # When will we hit it? (if slope > 0)
        if slope > 0:
            videos_needed = (target - current_views) / slope
            projected_date = f"~{int(videos_needed)} videos from now"
        else:
            projected_date = "need to improve trend first"

        goals.append({
            "metric": "views_avg",
            "target_value": round(target),
            "current_value": current_views,
            "baseline_value": current_views,
            "trend_slope": slope,
            "projected_date": projected_date,
            "status": "active",
            "notes": f"Based on trend slope {slope:.1f} views/video. R²={trends['views_trend']['r_squared']:.2f}",
        })

    # Engagement goal
    current_eng = trends.get("current_avg_engagement", 0)
    if current_eng > 0:
        target_eng = min(current_eng * 1.3, 0.15)  # 30% increase, capped at 15%
        goals.append({
            "metric": "engagement_rate",
            "target_value": round(target_eng, 6),
            "current_value": current_eng,
            "baseline_value": current_eng,
            "trend_slope": trends.get("engagement_trend", {}).get("slope", 0),
            "status": "active",
            "notes": "Target: 30% improvement or 15% engagement rate (whichever is lower)",
        })

    # Save to DB
    for goal in goals:
        existing = conn.execute(
            "SELECT id FROM goals WHERE metric = ? AND status = 'active'",
            (goal["metric"],),
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE goals SET
                    current_value = ?, trend_slope = ?,
                    projected_date = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (goal["current_value"], goal["trend_slope"], goal.get("projected_date"), goal["notes"], existing["id"]))
        else:
            conn.execute("""
                INSERT INTO goals (metric, target_value, current_value, baseline_value, trend_slope, projected_date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                goal["metric"], goal["target_value"], goal["current_value"],
                goal["baseline_value"], goal["trend_slope"],
                goal.get("projected_date"), goal["notes"],
            ))

    conn.commit()
    return goals


def _check_goal_progress(conn) -> list[dict]:
    """Check progress on all active goals."""
    cur = conn.execute("SELECT * FROM goals WHERE status = 'active'")
    goals = [dict(r) for r in cur.fetchall()]

    for goal in goals:
        target = goal.get("target_value", 0)
        current = goal.get("current_value", 0)
        baseline = goal.get("baseline_value", 0)

        if target > baseline:
            progress = (current - baseline) / (target - baseline) * 100
        else:
            progress = 100 if current >= target else 0

        goal["progress_pct"] = round(min(100, max(0, progress)), 1)

        if current >= target:
            conn.execute("UPDATE goals SET status = 'achieved', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (goal["id"],))
            goal["status"] = "achieved"

    conn.commit()
    return goals


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    set_goal_metric: str = "",
    set_goal_target: float = 0,
    deadline: str = "",
) -> Path:
    log = build_logger("ex23", settings.output_dir / "logs" / "ex23.log")
    conn = get_db(settings.data_dir)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Manual goal setting
    if set_goal_metric and set_goal_target > 0:
        conn.execute("""
            INSERT INTO goals (metric, target_value, deadline, notes)
            VALUES (?, ?, ?, 'Manually set')
        """, (set_goal_metric, set_goal_target, deadline or None))
        conn.commit()
        log.info("Goal set: %s = %s by %s", set_goal_metric, set_goal_target, deadline or "no deadline")

    # 1. Trend analysis
    log.info("Analyzing trends...")
    trends = _analyze_trends(conn)

    # 2. Feature importance
    log.info("Analyzing feature importance...")
    features = _analyze_feature_importance(conn)

    # 3. Auto-set goals from trends
    auto_goals = _set_auto_goals(conn, trends)

    # 4. Check goal progress
    goals = _check_goal_progress(conn)

    # 5. Write knowledge base entries from insights
    if features.get("ranking"):
        top_feature = features["ranking"][0]
        conn.execute("""
            INSERT OR REPLACE INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', ?, ?, ?, ?, 'stats')
        """, (
            top_feature["feature"],
            f"Top feature: {top_feature['feature']} explains {top_feature['variance_explained_pct']}% of engagement variance",
            f"Feature '{top_feature['feature']}' has the highest information gain ({top_feature['information_gain']:.6f}) "
            f"and explains {top_feature['variance_explained_pct']}% of the variance in engagement rate.",
            min(1.0, top_feature["variance_explained_pct"] / 100 + 0.3),
        ))
        conn.commit()

    # 6. Report
    report_path = out_dir / f"ex23_stats_{ts}.txt"
    lines = [
        "ex23 - Statistical Analysis & Goals",
        "=" * 55,
        "",
    ]

    if trends.get("has_data"):
        lines.append(f"Data points: {trends['n']}")
        lines.append("")
        lines.append("TRENDS:")
        lines.append(f"  Views: {trends['views_trend']['interpretation']}")
        lines.append(f"  Engagement: {trends['engagement_trend']['interpretation']}")
        lines.append(f"  Current avg views (last 5): {trends['current_avg_views']:,}")
        lines.append(f"  Current avg engagement: {trends['current_avg_engagement']:.4f}")
    else:
        lines.append(f"Not enough data for trends (need 3+, have {trends.get('n', 0)})")

    if features.get("ranking"):
        lines.append("")
        lines.append("FEATURE IMPORTANCE (by information gain):")
        for f in features["ranking"]:
            lines.append(f"  {f['feature']}: IG={f['information_gain']:.6f}, "
                        f"variance explained={f['variance_explained_pct']}%")

    if features:
        for name, data in features.items():
            if name == "ranking":
                continue
            means = data.get("group_means", {})
            if means:
                lines.append(f"  {name} means: {means}")

    if goals:
        lines.append("")
        lines.append("GOALS:")
        for g in goals:
            status_icon = {"active": "~", "achieved": "+", "missed": "X"}.get(g.get("status", ""), "?")
            lines.append(
                f"  [{status_icon}] {g.get('metric', '?')}: "
                f"{g.get('current_value', 0)} / {g.get('target_value', 0)} "
                f"({g.get('progress_pct', 0)}%)"
            )
            if g.get("notes"):
                lines.append(f"      {g['notes']}")

    lines.append("")
    lines.append("INTERPRETATION GUIDE:")
    lines.append("  R²: 0-0.3 = weak trend, 0.3-0.7 = moderate, 0.7-1.0 = strong")
    lines.append("  Information Gain: higher = feature matters more for engagement")
    lines.append("  Variance Explained: % of engagement variation due to this factor")
    lines.append("  The rest is noise, luck, or factors we don't track yet.")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Stats report saved to %s", report_path)
    return report_path
