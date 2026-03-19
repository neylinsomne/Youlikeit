"""
ex32 - ETL: Rendimiento de lecciones por tipo pedagógico.

Extract: quotes con learning_type (de ex31) + retention/engagement (de ex24/analytics)
Transform: Cruzar tipo de lección con métricas. Rankear qué tipo retiene mejor.
Load: Insights en knowledge_base + reporte

Cruza dos dimensiones:
  - Pedagógica (ex31): critical_thinking, emotional_intelligence, ethics, etc.
  - Rendimiento (ex24/analytics): retention_avg, engagement_rate, views, cliffs

Preguntas que responde:
  1. ¿Qué tipo de lección retiene mejor a la audiencia?
  2. ¿Qué área curricular genera más engagement?
  3. ¿Hay tipos de lección que causan más "cliffs" (caídas de retención)?
  4. ¿La emoción + tipo de lección interactúan? (e.g., ethics+anger vs ethics+sadness)

Usa ANOVA de una vía (desde cero) para significancia estadística.
Cohen's d para tamaño del efecto.

Uso:
  python src/main.py ex32
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from common.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# Statistical helpers (sin sklearn/scipy)
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return sum((x - m) ** 2 for x in values) / (len(values) - 1)


def _std(values: list[float]) -> float:
    return math.sqrt(_variance(values))


def _cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """Effect size: Cohen's d between two groups."""
    if len(group_a) < 2 or len(group_b) < 2:
        return 0.0
    m1, m2 = _mean(group_a), _mean(group_b)
    s1, s2 = _variance(group_a), _variance(group_b)
    n1, n2 = len(group_a), len(group_b)
    pooled_std = math.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    if pooled_std == 0:
        return 0.0
    return (m1 - m2) / pooled_std


def _one_way_anova(groups: dict[str, list[float]]) -> dict:
    """
    One-way ANOVA from scratch.

    Returns: {f_statistic, p_approx, significant, groups_n, grand_mean}

    p_approx uses the F-distribution approximation via the incomplete beta
    function. For small samples this is approximate but sufficient for
    our use case (deciding if lesson type matters for retention).
    """
    all_values = []
    for vals in groups.values():
        all_values.extend(vals)

    if len(all_values) < 3 or len(groups) < 2:
        return {"f_statistic": 0, "p_approx": 1.0, "significant": False,
                "groups_n": {k: len(v) for k, v in groups.items()},
                "grand_mean": _mean(all_values)}

    grand_mean = _mean(all_values)
    k = len(groups)  # number of groups
    n_total = len(all_values)

    # Between-group sum of squares (SSB)
    ssb = sum(
        len(vals) * (_mean(vals) - grand_mean) ** 2
        for vals in groups.values()
        if vals
    )

    # Within-group sum of squares (SSW)
    ssw = sum(
        sum((x - _mean(vals)) ** 2 for x in vals)
        for vals in groups.values()
        if vals
    )

    df_between = k - 1
    df_within = n_total - k

    if df_within <= 0 or ssw == 0:
        return {"f_statistic": 0, "p_approx": 1.0, "significant": False,
                "groups_n": {k_: len(v) for k_, v in groups.items()},
                "grand_mean": grand_mean}

    msb = ssb / df_between
    msw = ssw / df_within
    f_stat = msb / msw

    # Approximate p-value using the relationship between F and Beta distributions
    # P(F > f) ≈ 1 - I_x(a, b) where x = a*f/(a*f+b), a = df1/2, b = df2/2
    # For simplicity, use a threshold-based approach
    # F critical values (approx) for common df combinations at alpha=0.05
    p_approx = _f_to_p_approx(f_stat, df_between, df_within)

    return {
        "f_statistic": round(f_stat, 4),
        "p_approx": round(p_approx, 4),
        "significant": p_approx < 0.05,
        "df_between": df_between,
        "df_within": df_within,
        "ssb": round(ssb, 4),
        "ssw": round(ssw, 4),
        "groups_n": {k_: len(v) for k_, v in groups.items()},
        "grand_mean": round(grand_mean, 4),
    }


def _f_to_p_approx(f: float, df1: int, df2: int) -> float:
    """
    Approximate p-value for F-statistic using the regularized incomplete
    beta function via continued fraction expansion.
    """
    if f <= 0:
        return 1.0
    x = df2 / (df2 + df1 * f)
    a = df2 / 2.0
    b = df1 / 2.0
    # I_x(a, b) = regularized incomplete beta function
    return _regularized_beta(x, a, b)


def _regularized_beta(x: float, a: float, b: float, max_iter: int = 200) -> float:
    """Regularized incomplete beta function via Lentz's continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    # Use the log-beta for the prefactor
    ln_prefix = (
        a * math.log(x) + b * math.log(1 - x)
        - math.log(a)
        - _log_beta(a, b)
    )
    prefix = math.exp(ln_prefix)

    # Continued fraction (Lentz's method)
    tiny = 1e-30
    f_cf = 1.0 + tiny
    c = f_cf
    d = 0.0

    for m in range(1, max_iter + 1):
        # Even step
        numerator = _beta_cf_coeff(m, a, b, x, even=True)
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        f_cf *= c * d

        # Odd step
        numerator = _beta_cf_coeff(m, a, b, x, even=False)
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        delta = c * d
        f_cf *= delta

        if abs(delta - 1.0) < 1e-10:
            break

    return prefix * (f_cf - 1.0)


def _beta_cf_coeff(m: int, a: float, b: float, x: float, even: bool) -> float:
    """Coefficients for the continued fraction expansion of I_x(a,b)."""
    if even:
        k = m
        return (k * (b - k) * x) / ((a + 2 * k - 1) * (a + 2 * k))
    else:
        k = m - 1
        return -((a + k) * (a + b + k) * x) / ((a + 2 * k) * (a + 2 * k + 1))


def _log_beta(a: float, b: float) -> float:
    """Log of Beta function: ln(B(a,b)) = ln(Γ(a)) + ln(Γ(b)) - ln(Γ(a+b))."""
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

def _extract_lesson_metrics(conn) -> list[dict]:
    """
    Get quotes with learning_type joined with their video performance metrics.

    Joins: quotes (learning_type from ex31) → shorts (quote_ids) → analytics
    """
    # Get all classified quotes
    cur = conn.execute("""
        SELECT q.id, q.text, q.category, q.emotion, q.learning_type,
               q.curriculum_area, q.life_lesson, q.viral_score,
               m.title as movie_title
        FROM quotes q
        JOIN movies m ON q.movie_id = m.id
        WHERE q.learning_type IS NOT NULL
    """)
    quotes = [dict(r) for r in cur.fetchall()]

    if not quotes:
        return []

    # Get all analytics data
    cur = conn.execute("""
        SELECT a.id as analytics_id, a.short_id, a.views, a.likes, a.comments,
               a.shares, a.retention_avg, a.retention_3s, a.engagement_rate,
               a.impressions, a.ctr, s.quote_ids
        FROM analytics a
        JOIN shorts s ON a.short_id = s.id
        WHERE a.platform = 'youtube'
          AND a.views > 0
    """)
    analytics_rows = [dict(r) for r in cur.fetchall()]

    # Build quote_id → analytics mapping
    quote_analytics: dict[int, list[dict]] = {}
    for row in analytics_rows:
        qids_json = row.get("quote_ids")
        if not qids_json:
            continue
        try:
            qids = json.loads(qids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for qid in qids:
            if qid not in quote_analytics:
                quote_analytics[qid] = []
            quote_analytics[qid].append(row)

    # Get retention events per analytics_id
    cur = conn.execute("""
        SELECT analytics_id, event_type, COUNT(*) as count,
               AVG(magnitude) as avg_magnitude
        FROM retention_events
        GROUP BY analytics_id, event_type
    """)
    events_by_analytics: dict[int, dict[str, dict]] = {}
    for r in cur.fetchall():
        aid = r["analytics_id"]
        if aid not in events_by_analytics:
            events_by_analytics[aid] = {}
        events_by_analytics[aid][r["event_type"]] = {
            "count": r["count"],
            "avg_magnitude": r["avg_magnitude"],
        }

    # Merge quotes with their performance
    enriched = []
    for q in quotes:
        analytics_list = quote_analytics.get(q["id"], [])
        if not analytics_list:
            # Quote not yet in a published short - include with null metrics
            enriched.append({**q, "has_metrics": False,
                             "views": 0, "retention_avg": 0, "engagement_rate": 0,
                             "retention_3s": 0, "impressions": 0, "ctr": 0,
                             "cliff_count": 0, "hook_pass": False})
            continue

        # Aggregate across all shorts that used this quote
        total_views = sum(a.get("views", 0) for a in analytics_list)
        avg_retention = _mean([a["retention_avg"] for a in analytics_list if a.get("retention_avg")])
        avg_engagement = _mean([a["engagement_rate"] for a in analytics_list if a.get("engagement_rate")])
        avg_ret_3s = _mean([a["retention_3s"] for a in analytics_list if a.get("retention_3s")])
        avg_ctr = _mean([a["ctr"] for a in analytics_list if a.get("ctr")])
        total_impressions = sum(a.get("impressions", 0) for a in analytics_list)

        # Retention events
        cliff_count = 0
        hook_pass = False
        for a in analytics_list:
            events = events_by_analytics.get(a["analytics_id"], {})
            cliff_count += events.get("cliff", {}).get("count", 0)
            if "hook_pass" in events:
                hook_pass = True

        enriched.append({
            **q,
            "has_metrics": True,
            "views": total_views,
            "retention_avg": avg_retention,
            "engagement_rate": avg_engagement,
            "retention_3s": avg_ret_3s,
            "impressions": total_impressions,
            "ctr": avg_ctr,
            "cliff_count": cliff_count,
            "hook_pass": hook_pass,
        })

    return enriched


# ---------------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------------

def _transform_by_learning_type(enriched: list[dict]) -> dict:
    """
    Group metrics by learning_type and compute statistics.

    Returns a dict of learning_type → {
        count, with_metrics, avg_retention, avg_engagement,
        avg_views, avg_cliff_count, hook_pass_rate,
        retention_values (for ANOVA), engagement_values
    }
    """
    groups: dict[str, dict] = {}

    for item in enriched:
        lt = item["learning_type"]
        if lt not in groups:
            groups[lt] = {
                "count": 0,
                "with_metrics": 0,
                "retention_values": [],
                "engagement_values": [],
                "views_values": [],
                "ret_3s_values": [],
                "cliff_counts": [],
                "hook_passes": 0,
                "categories": {},
                "emotions": {},
            }

        g = groups[lt]
        g["count"] += 1

        # Track category/emotion distribution within this learning type
        cat = item.get("category", "unknown")
        g["categories"][cat] = g["categories"].get(cat, 0) + 1
        emo = item.get("emotion", "unknown")
        g["emotions"][emo] = g["emotions"].get(emo, 0) + 1

        if not item.get("has_metrics"):
            continue

        g["with_metrics"] += 1
        if item["retention_avg"] > 0:
            g["retention_values"].append(item["retention_avg"])
        if item["engagement_rate"] > 0:
            g["engagement_values"].append(item["engagement_rate"])
        if item["views"] > 0:
            g["views_values"].append(float(item["views"]))
        if item["retention_3s"] > 0:
            g["ret_3s_values"].append(item["retention_3s"])
        g["cliff_counts"].append(item["cliff_count"])
        if item["hook_pass"]:
            g["hook_passes"] += 1

    # Compute summary stats per group
    for lt, g in groups.items():
        g["avg_retention"] = round(_mean(g["retention_values"]), 2)
        g["avg_engagement"] = round(_mean(g["engagement_values"]), 4)
        g["avg_views"] = round(_mean(g["views_values"]), 1)
        g["avg_ret_3s"] = round(_mean(g["ret_3s_values"]), 2)
        g["avg_cliffs"] = round(_mean(g["cliff_counts"]), 2)
        g["hook_pass_rate"] = (
            round(g["hook_passes"] / g["with_metrics"] * 100, 1)
            if g["with_metrics"] > 0 else 0
        )
        g["std_retention"] = round(_std(g["retention_values"]), 2)
        g["std_engagement"] = round(_std(g["engagement_values"]), 4)

    return groups


def _transform_by_curriculum_area(enriched: list[dict]) -> dict:
    """Same grouping but by curriculum_area."""
    groups: dict[str, dict] = {}

    for item in enriched:
        ca = item.get("curriculum_area", "unknown")
        if ca not in groups:
            groups[ca] = {
                "count": 0, "with_metrics": 0,
                "retention_values": [], "engagement_values": [],
                "views_values": [],
            }

        g = groups[ca]
        g["count"] += 1
        if not item.get("has_metrics"):
            continue
        g["with_metrics"] += 1
        if item["retention_avg"] > 0:
            g["retention_values"].append(item["retention_avg"])
        if item["engagement_rate"] > 0:
            g["engagement_values"].append(item["engagement_rate"])
        if item["views"] > 0:
            g["views_values"].append(float(item["views"]))

    for ca, g in groups.items():
        g["avg_retention"] = round(_mean(g["retention_values"]), 2)
        g["avg_engagement"] = round(_mean(g["engagement_values"]), 4)
        g["avg_views"] = round(_mean(g["views_values"]), 1)

    return groups


def _transform_interactions(enriched: list[dict]) -> list[dict]:
    """
    Analyze interactions between learning_type + emotion.
    Returns top combinations sorted by retention.
    """
    combos: dict[str, list[float]] = {}

    for item in enriched:
        if not item.get("has_metrics") or item["retention_avg"] <= 0:
            continue
        key = f"{item['learning_type']}+{item.get('emotion', 'neutral')}"
        if key not in combos:
            combos[key] = []
        combos[key].append(item["retention_avg"])

    results = []
    for key, values in combos.items():
        if len(values) < 2:
            continue
        lt, emo = key.split("+", 1)
        results.append({
            "learning_type": lt,
            "emotion": emo,
            "n": len(values),
            "avg_retention": round(_mean(values), 2),
            "std_retention": round(_std(values), 2),
        })

    results.sort(key=lambda x: x["avg_retention"], reverse=True)
    return results


def _transform_anova_tests(groups_by_lt: dict) -> dict:
    """Run ANOVA tests on retention and engagement by learning_type."""
    # ANOVA on retention
    retention_groups = {
        lt: g["retention_values"]
        for lt, g in groups_by_lt.items()
        if len(g["retention_values"]) >= 2
    }
    anova_retention = _one_way_anova(retention_groups)

    # ANOVA on engagement
    engagement_groups = {
        lt: g["engagement_values"]
        for lt, g in groups_by_lt.items()
        if len(g["engagement_values"]) >= 2
    }
    anova_engagement = _one_way_anova(engagement_groups)

    # Pairwise Cohen's d for top vs bottom learning types (by retention)
    sorted_types = sorted(
        groups_by_lt.items(),
        key=lambda x: x[1]["avg_retention"],
        reverse=True,
    )
    pairwise = []
    if len(sorted_types) >= 2:
        top_lt, top_g = sorted_types[0]
        bot_lt, bot_g = sorted_types[-1]
        if top_g["retention_values"] and bot_g["retention_values"]:
            d = _cohens_d(top_g["retention_values"], bot_g["retention_values"])
            pairwise.append({
                "comparison": f"{top_lt} vs {bot_lt}",
                "cohens_d": round(d, 3),
                "effect": (
                    "large" if abs(d) >= 0.8 else
                    "medium" if abs(d) >= 0.5 else
                    "small" if abs(d) >= 0.2 else
                    "negligible"
                ),
            })

    return {
        "anova_retention": anova_retention,
        "anova_engagement": anova_engagement,
        "pairwise_effects": pairwise,
    }


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def _load_insights(conn, groups_by_lt: dict, anova: dict, interactions: list[dict]):
    """Save insights to knowledge_base."""
    # Best and worst learning types
    sorted_types = sorted(
        groups_by_lt.items(),
        key=lambda x: x[1]["avg_retention"],
        reverse=True,
    )
    with_data = [(lt, g) for lt, g in sorted_types if g["with_metrics"] > 0]

    if with_data:
        best_lt, best_g = with_data[0]
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'pedagogy', ?, ?, ?, 'lesson_performance')
        """, (
            f"Best performing lesson type: {best_lt}",
            json.dumps({
                "learning_type": best_lt,
                "avg_retention": best_g["avg_retention"],
                "avg_engagement": best_g["avg_engagement"],
                "sample_size": best_g["with_metrics"],
                "hook_pass_rate": best_g["hook_pass_rate"],
            }, ensure_ascii=False),
            min(0.9, 0.5 + best_g["with_metrics"] * 0.05),
        ))

    if len(with_data) >= 2:
        worst_lt, worst_g = with_data[-1]
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'pedagogy', ?, ?, ?, 'lesson_performance')
        """, (
            f"Lowest performing lesson type: {worst_lt}",
            json.dumps({
                "learning_type": worst_lt,
                "avg_retention": worst_g["avg_retention"],
                "avg_engagement": worst_g["avg_engagement"],
                "sample_size": worst_g["with_metrics"],
            }, ensure_ascii=False),
            min(0.9, 0.5 + worst_g["with_metrics"] * 0.05),
        ))

    # ANOVA result
    if anova.get("anova_retention", {}).get("significant"):
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'pedagogy', ?, ?, 0.8, 'lesson_performance')
        """, (
            "Lesson type significantly affects retention (ANOVA p < 0.05)",
            json.dumps(anova["anova_retention"], ensure_ascii=False),
        ))

    # Best interaction
    if interactions:
        best = interactions[0]
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'pedagogy', ?, ?, 0.6, 'lesson_performance')
        """, (
            f"Best combo: {best['learning_type']}+{best['emotion']}",
            json.dumps(best, ensure_ascii=False),
        ))


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(settings: Settings) -> Path:
    log = build_logger("ex32", settings.output_dir / "logs" / "ex32.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex32")

    # ── EXTRACT ──
    tracker.extract_start()
    enriched = _extract_lesson_metrics(conn)
    with_metrics = [e for e in enriched if e.get("has_metrics")]
    tracker.extract_done({
        "total_quotes": len(enriched),
        "with_metrics": len(with_metrics),
    })
    log.info("Extract: %d quotes classified, %d with metrics", len(enriched), len(with_metrics))

    if not enriched:
        out = settings.output_dir / "logs" / "ex32_no_data.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "ex32: No quotes with learning_type found.\n"
            "Run ex31 first to classify quotes, then ex19/ex24 for metrics.",
            encoding="utf-8",
        )
        conn.close()
        return out

    # ── TRANSFORM ──
    tracker.transform_start("Grouping by learning type")

    groups_by_lt = _transform_by_learning_type(enriched)
    tracker.transform_progress(1, 4, "by learning_type")

    groups_by_ca = _transform_by_curriculum_area(enriched)
    tracker.transform_progress(2, 4, "by curriculum_area")

    interactions = _transform_interactions(enriched)
    tracker.transform_progress(3, 4, "interactions")

    anova = _transform_anova_tests(groups_by_lt)
    tracker.transform_progress(4, 4, "ANOVA tests")

    tracker.transform_done({
        "learning_types": len(groups_by_lt),
        "curriculum_areas": len(groups_by_ca),
        "interactions": len(interactions),
    })

    # ── LOAD ──
    tracker.load_start()
    _load_insights(conn, groups_by_lt, anova, interactions)
    conn.commit()
    tracker.load_done({"insights_saved": True})

    # ── REPORT ──
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"ex32_lesson_performance_{ts}.txt"

    lines = [
        "ex32 - Lesson Performance Report",
        "=" * 60,
        f"Total quotes classified: {len(enriched)}",
        f"Quotes with metrics: {len(with_metrics)}",
        "",
        "─── By Learning Type ───",
    ]

    sorted_lt = sorted(
        groups_by_lt.items(),
        key=lambda x: x[1]["avg_retention"],
        reverse=True,
    )
    for lt, g in sorted_lt:
        bar = "█" * max(1, int(g["avg_retention"] / 5))
        lines.append(
            f"  {lt:25s}  n={g['count']:3d}  "
            f"ret={g['avg_retention']:5.1f}%  "
            f"eng={g['avg_engagement']:.4f}  "
            f"views={g['avg_views']:7.0f}  "
            f"cliffs={g['avg_cliffs']:.1f}  "
            f"hook={g['hook_pass_rate']:4.0f}%  {bar}"
        )

    lines.append("")
    lines.append("─── By Curriculum Area ───")
    sorted_ca = sorted(
        groups_by_ca.items(),
        key=lambda x: x[1]["avg_retention"],
        reverse=True,
    )
    for ca, g in sorted_ca:
        lines.append(
            f"  {ca:20s}  n={g['count']:3d}  "
            f"ret={g['avg_retention']:5.1f}%  "
            f"eng={g['avg_engagement']:.4f}  "
            f"views={g['avg_views']:7.0f}"
        )

    lines.append("")
    lines.append("─── Top Interactions (learning_type + emotion) ───")
    for ix in interactions[:8]:
        lines.append(
            f"  {ix['learning_type']:20s} + {ix['emotion']:10s}  "
            f"n={ix['n']:3d}  ret={ix['avg_retention']:5.1f}% ± {ix['std_retention']:.1f}"
        )

    lines.append("")
    lines.append("─── Statistical Tests ───")
    ar = anova.get("anova_retention", {})
    lines.append(f"  ANOVA (retention by learning_type):")
    lines.append(f"    F = {ar.get('f_statistic', 0):.4f},  p ≈ {ar.get('p_approx', 1):.4f}")
    lines.append(f"    Significant: {'YES' if ar.get('significant') else 'NO'} (α = 0.05)")

    ae = anova.get("anova_engagement", {})
    lines.append(f"  ANOVA (engagement by learning_type):")
    lines.append(f"    F = {ae.get('f_statistic', 0):.4f},  p ≈ {ae.get('p_approx', 1):.4f}")
    lines.append(f"    Significant: {'YES' if ae.get('significant') else 'NO'} (α = 0.05)")

    for pw in anova.get("pairwise_effects", []):
        lines.append(f"  Cohen's d ({pw['comparison']}): {pw['cohens_d']:.3f} ({pw['effect']})")

    lines.append("")
    lines.append("─── What We Don't Know ───")
    no_metrics = len(enriched) - len(with_metrics)
    lines.append(f"  Quotes without metrics: {no_metrics} ({no_metrics/len(enriched)*100:.0f}%)")
    if not ar.get("significant"):
        lines.append("  ANOVA not significant: lesson type may NOT affect retention with current data")
        lines.append("  → Need more published shorts with diverse learning types")
    small_groups = [lt for lt, g in groups_by_lt.items() if g["with_metrics"] < 3]
    if small_groups:
        lines.append(f"  Small sample groups (<3): {', '.join(small_groups)}")
        lines.append("  → Publish more shorts in these categories for reliable stats")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    tracker.complete({
        "learning_types": len(groups_by_lt),
        "anova_significant": ar.get("significant", False),
    })

    conn.close()
    log.info("Lesson performance report: %s", report_path)
    return report_path
