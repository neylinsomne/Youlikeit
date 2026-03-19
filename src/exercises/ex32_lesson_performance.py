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

Pipeline estadístico:
  1. Shapiro-Wilk → ¿los datos son normales?
  2. Si sí → ANOVA (scipy.stats.f_oneway) + eta²
     Si no → Kruskal-Wallis (alternativa no paramétrica)
  3. Si significativo → post-hoc pairwise con corrección Bonferroni
  4. Cohen's d para tamaño del efecto en cada par significativo
  5. Intervalos de confianza al 95%

Uso:
  python src/main.py ex32
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from scipy import stats as sp_stats

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from common.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# Statistical helpers
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
    """Effect size: Cohen's d (pooled std) between two groups."""
    if len(group_a) < 2 or len(group_b) < 2:
        return 0.0
    m1, m2 = _mean(group_a), _mean(group_b)
    s1, s2 = _variance(group_a), _variance(group_b)
    n1, n2 = len(group_a), len(group_b)
    pooled_std = math.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    if pooled_std == 0:
        return 0.0
    return (m1 - m2) / pooled_std


def _effect_label(d: float) -> str:
    ad = abs(d)
    if ad >= 0.8:
        return "large"
    if ad >= 0.5:
        return "medium"
    if ad >= 0.2:
        return "small"
    return "negligible"


def _confidence_interval_95(values: list[float]) -> tuple[float, float]:
    """95% CI for the mean using t-distribution."""
    if len(values) < 2:
        return (_mean(values), _mean(values))
    n = len(values)
    m = _mean(values)
    se = _std(values) / math.sqrt(n)
    t_crit = sp_stats.t.ppf(0.975, df=n - 1)
    return (round(m - t_crit * se, 4), round(m + t_crit * se, 4))


def _test_normality(values: list[float]) -> tuple[bool, float]:
    """Shapiro-Wilk normality test. Returns (is_normal, p_value)."""
    if len(values) < 8:
        return True, 1.0  # Too few samples — assume normal (conservative)
    _, p = sp_stats.shapiro(values)
    return p > 0.05, round(p, 4)


def _omnibus_test(groups: dict[str, list[float]]) -> dict:
    """
    Proper omnibus test with assumption checking.

    1. Check normality per group (Shapiro-Wilk)
    2. If normal → one-way ANOVA (parametric) + eta²
       If not → Kruskal-Wallis (non-parametric)
    3. Report both F/H statistic, p-value, effect size
    """
    valid = {k: v for k, v in groups.items() if len(v) >= 2}
    all_values = []
    for v in valid.values():
        all_values.extend(v)

    if len(all_values) < 3 or len(valid) < 2:
        return {
            "test": "none", "statistic": 0, "p_value": 1.0,
            "significant": False, "eta_squared": 0,
            "groups_n": {k: len(v) for k, v in groups.items()},
            "grand_mean": round(_mean(all_values), 4),
        }

    # Check normality in each group
    normality_ok = True
    normality_details = {}
    for name, vals in valid.items():
        is_normal, p = _test_normality(vals)
        normality_details[name] = {"normal": is_normal, "shapiro_p": p}
        if not is_normal:
            normality_ok = False

    lists = list(valid.values())

    if normality_ok:
        # Parametric: one-way ANOVA (exact p-value via scipy)
        f_stat, p_value = sp_stats.f_oneway(*lists)
        test_name = "anova"
        statistic = float(f_stat)
    else:
        # Non-parametric: Kruskal-Wallis
        h_stat, p_value = sp_stats.kruskal(*lists)
        test_name = "kruskal_wallis"
        statistic = float(h_stat)

    p_value = float(p_value)

    # Effect size: eta² = SS_between / SS_total
    grand_mean = _mean(all_values)
    ss_between = sum(
        len(v) * (_mean(v) - grand_mean) ** 2
        for v in valid.values()
    )
    ss_total = sum((x - grand_mean) ** 2 for x in all_values)
    eta_sq = ss_between / ss_total if ss_total > 0 else 0

    return {
        "test": test_name,
        "statistic": round(statistic, 4),
        "p_value": round(p_value, 6),
        "significant": p_value < 0.05,
        "eta_squared": round(eta_sq, 4),
        "variance_explained_pct": round(eta_sq * 100, 1),
        "normality_assumed": normality_ok,
        "normality_details": normality_details,
        "groups_n": {k: len(v) for k, v in valid.items()},
        "grand_mean": round(grand_mean, 4),
        "n_total": len(all_values),
    }


def _pairwise_posthoc(groups: dict[str, list[float]], alpha: float = 0.05) -> list[dict]:
    """
    Pairwise comparisons with Bonferroni correction.

    For each pair of groups with n >= 2:
      - Welch's t-test (does not assume equal variances)
      - Cohen's d effect size
      - Bonferroni-adjusted p-value
    """
    valid = {k: v for k, v in groups.items() if len(v) >= 2}
    names = sorted(valid.keys())
    n_comparisons = len(names) * (len(names) - 1) // 2

    if n_comparisons == 0:
        return []

    results = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_name, b_name = names[i], names[j]
            a_vals, b_vals = valid[a_name], valid[b_name]

            t_stat, p_raw = sp_stats.ttest_ind(a_vals, b_vals, equal_var=False)
            p_adj = min(1.0, p_raw * n_comparisons)  # Bonferroni

            d = _cohens_d(a_vals, b_vals)

            results.append({
                "group_a": a_name,
                "group_b": b_name,
                "t_statistic": round(float(t_stat), 4),
                "p_raw": round(float(p_raw), 6),
                "p_adjusted": round(p_adj, 6),
                "significant": p_adj < alpha,
                "cohens_d": round(d, 3),
                "effect": _effect_label(d),
                "mean_a": round(_mean(a_vals), 2),
                "mean_b": round(_mean(b_vals), 2),
            })

    results.sort(key=lambda x: x["p_adjusted"])
    return results


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


def _transform_statistical_tests(groups_by_lt: dict) -> dict:
    """
    Full statistical pipeline on retention and engagement by learning_type.

    1. Omnibus test (ANOVA or Kruskal-Wallis depending on normality)
    2. Post-hoc pairwise comparisons with Bonferroni correction
    3. 95% confidence intervals per group
    """
    # Omnibus on retention
    retention_groups = {
        lt: g["retention_values"]
        for lt, g in groups_by_lt.items()
        if len(g["retention_values"]) >= 2
    }
    omnibus_retention = _omnibus_test(retention_groups)

    # Omnibus on engagement
    engagement_groups = {
        lt: g["engagement_values"]
        for lt, g in groups_by_lt.items()
        if len(g["engagement_values"]) >= 2
    }
    omnibus_engagement = _omnibus_test(engagement_groups)

    # Post-hoc pairwise (only if omnibus is significant)
    posthoc_retention = []
    if omnibus_retention.get("significant"):
        posthoc_retention = _pairwise_posthoc(retention_groups)

    posthoc_engagement = []
    if omnibus_engagement.get("significant"):
        posthoc_engagement = _pairwise_posthoc(engagement_groups)

    # 95% CIs per group
    cis = {}
    for lt, g in groups_by_lt.items():
        cis[lt] = {}
        if len(g["retention_values"]) >= 2:
            cis[lt]["retention_ci"] = _confidence_interval_95(g["retention_values"])
        if len(g["engagement_values"]) >= 2:
            cis[lt]["engagement_ci"] = _confidence_interval_95(g["engagement_values"])

    return {
        "omnibus_retention": omnibus_retention,
        "omnibus_engagement": omnibus_engagement,
        "posthoc_retention": posthoc_retention,
        "posthoc_engagement": posthoc_engagement,
        "confidence_intervals": cis,
    }


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def _load_insights(conn, groups_by_lt: dict, test_results: dict, interactions: list[dict]):
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
        ci = test_results.get("confidence_intervals", {}).get(best_lt, {})
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
                "retention_95ci": ci.get("retention_ci"),
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

    # Omnibus test result
    omnibus = test_results.get("omnibus_retention", {})
    if omnibus.get("significant"):
        test_name = omnibus["test"].upper()
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'pedagogy', ?, ?, 0.8, 'lesson_performance')
        """, (
            f"Lesson type significantly affects retention ({test_name} p={omnibus['p_value']:.4f})",
            json.dumps(omnibus, ensure_ascii=False, default=str),
        ))

    # Significant pairwise differences
    for ph in test_results.get("posthoc_retention", []):
        if ph["significant"] and abs(ph["cohens_d"]) >= 0.2:
            conn.execute("""
                INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
                VALUES ('insight', 'pedagogy', ?, ?, ?, 'lesson_performance')
            """, (
                f"{ph['group_a']} vs {ph['group_b']}: d={ph['cohens_d']:.2f} ({ph['effect']})",
                json.dumps(ph, ensure_ascii=False),
                min(0.9, 0.5 + (1.0 - ph["p_adjusted"]) * 0.4),
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

    test_results = _transform_statistical_tests(groups_by_lt)
    tracker.transform_progress(4, 4, "statistical tests")

    tracker.transform_done({
        "learning_types": len(groups_by_lt),
        "curriculum_areas": len(groups_by_ca),
        "interactions": len(interactions),
    })

    # ── LOAD ──
    tracker.load_start()
    _load_insights(conn, groups_by_lt, test_results, interactions)
    conn.commit()
    tracker.load_done({"insights_saved": True})

    # ── REPORT ──
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"ex32_lesson_performance_{ts}.txt"

    cis = test_results.get("confidence_intervals", {})

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
        ci_str = ""
        ci_data = cis.get(lt, {}).get("retention_ci")
        if ci_data:
            ci_str = f"  CI=[{ci_data[0]:.1f},{ci_data[1]:.1f}]"
        lines.append(
            f"  {lt:25s}  n={g['count']:3d}  "
            f"ret={g['avg_retention']:5.1f}% ±{g['std_retention']:.1f}{ci_str}  "
            f"eng={g['avg_engagement']:.4f}  "
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

    # --- Statistical Tests (proper) ---
    lines.append("")
    lines.append("─── Statistical Tests ───")

    or_ = test_results.get("omnibus_retention", {})
    test_label = or_.get("test", "none").replace("_", " ").upper()
    lines.append(f"  Omnibus test (retention ~ learning_type): {test_label}")
    lines.append(f"    Statistic = {or_.get('statistic', 0):.4f},  p = {or_.get('p_value', 1):.6f}")
    lines.append(f"    Significant: {'YES' if or_.get('significant') else 'NO'} (α = 0.05)")
    lines.append(f"    η² = {or_.get('eta_squared', 0):.4f} ({or_.get('variance_explained_pct', 0):.1f}% variance explained)")
    lines.append(f"    Normality assumed: {'YES' if or_.get('normality_assumed') else 'NO → used Kruskal-Wallis'}")

    oe = test_results.get("omnibus_engagement", {})
    test_label_e = oe.get("test", "none").replace("_", " ").upper()
    lines.append(f"  Omnibus test (engagement ~ learning_type): {test_label_e}")
    lines.append(f"    Statistic = {oe.get('statistic', 0):.4f},  p = {oe.get('p_value', 1):.6f}")
    lines.append(f"    Significant: {'YES' if oe.get('significant') else 'NO'} (α = 0.05)")

    # Post-hoc
    ph_ret = test_results.get("posthoc_retention", [])
    if ph_ret:
        sig_pairs = [p for p in ph_ret if p["significant"]]
        lines.append("")
        lines.append(f"  Post-hoc pairwise (Bonferroni, {len(ph_ret)} comparisons):")
        if sig_pairs:
            for p in sig_pairs:
                lines.append(
                    f"    {p['group_a']:20s} vs {p['group_b']:20s}  "
                    f"p_adj={p['p_adjusted']:.4f}  d={p['cohens_d']:+.2f} ({p['effect']})  "
                    f"({p['mean_a']:.1f}% vs {p['mean_b']:.1f}%)"
                )
        else:
            lines.append("    No pairwise differences survive Bonferroni correction")

    lines.append("")
    lines.append("─── What We Don't Know ───")
    no_metrics = len(enriched) - len(with_metrics)
    lines.append(f"  Quotes without metrics: {no_metrics} ({no_metrics/len(enriched)*100:.0f}%)")
    if not or_.get("significant"):
        lines.append("  Omnibus test not significant: lesson type may NOT affect retention with current data")
        lines.append("  → Need more published shorts with diverse learning types")
    if or_.get("eta_squared", 0) < 0.06 and or_.get("significant"):
        lines.append(f"  η² = {or_['eta_squared']:.3f} (small effect) → statistically significant but practically weak")
        lines.append("  → The difference exists but may not justify changing content strategy")
    small_groups = [lt for lt, g in groups_by_lt.items() if g["with_metrics"] < 3]
    if small_groups:
        lines.append(f"  Small sample groups (<3): {', '.join(small_groups)}")
        lines.append("  → Publish more shorts in these categories for reliable stats")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    tracker.complete({
        "learning_types": len(groups_by_lt),
        "omnibus_significant": or_.get("significant", False),
        "test_used": or_.get("test", "none"),
    })

    conn.close()
    log.info("Lesson performance report: %s", report_path)
    return report_path
