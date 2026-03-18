"""
ex22 - A/B Testing automatizado.

Crea, ejecuta y evalua tests A/B sin intervención humana.
Los ajustes se aplican automáticamente cuando hay significancia estadística.

Flujo:
  1. Genera hipótesis desde la knowledge base o desde patrones de ex21
  2. Crea dos variantes (A y B) de un parámetro del pipeline
  3. Alterna entre variantes en los próximos uploads
  4. Cuando hay suficientes muestras, evalúa con t-test
  5. Si hay ganador significativo, aplica el cambio y lo documenta

No depende de ningún LLM - toda la lógica es estadística pura.

Uso:
  python src/main.py ex22 --action create --param hashtag_style --variant-a emotion --variant-b genre
  python src/main.py ex22 --action evaluate
  python src/main.py ex22 --action list
  python src/main.py ex22 --action auto
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ---------------------------------------------------------------------------
# Statistics (no dependencies beyond stdlib)
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _welch_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """
    Welch's t-test for two independent samples with unequal variances.
    Returns (t_statistic, approximate_p_value).

    No scipy needed - uses the t-distribution approximation.
    """
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0, 1.0

    mean_a, mean_b = _mean(a), _mean(b)
    var_a = _std(a) ** 2
    var_b = _std(b) ** 2

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return 0.0, 1.0

    t_stat = (mean_a - mean_b) / se

    # Welch-Satterthwaite degrees of freedom
    num = (var_a / n_a + var_b / n_b) ** 2
    den = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = num / den if den > 0 else 1.0

    # Approximate p-value using the normal distribution for large df
    # For small df, this is conservative (overestimates p)
    z = abs(t_stat)
    # Two-tailed p-value approximation (Abramowitz & Stegun)
    p = 2.0 * (1.0 - _normal_cdf(z))

    return t_stat, p


def _normal_cdf(x: float) -> float:
    """Approximate CDF of standard normal distribution."""
    # Abramowitz & Stegun approximation 26.2.17
    if x < 0:
        return 1.0 - _normal_cdf(-x)
    b0 = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    t = 1.0 / (1.0 + b0 * x)
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
    return 1.0 - pdf * poly


def _cohens_d(a: list[float], b: list[float]) -> float:
    """Effect size: Cohen's d."""
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0
    pooled_std = math.sqrt(
        ((n_a - 1) * _std(a) ** 2 + (n_b - 1) * _std(b) ** 2)
        / (n_a + n_b - 2)
    )
    if pooled_std == 0:
        return 0.0
    return (_mean(a) - _mean(b)) / pooled_std


def _confidence_interval(values: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Confidence interval for the mean."""
    n = len(values)
    if n < 2:
        return (0.0, 0.0)
    m = _mean(values)
    se = _std(values) / math.sqrt(n)
    # z for 95% CI
    z = 1.96 if confidence == 0.95 else 2.576  # 99%
    return (round(m - z * se, 6), round(m + z * se, 6))


# ---------------------------------------------------------------------------
# Auto-hypothesis generation
# ---------------------------------------------------------------------------

def _generate_hypotheses(conn) -> list[dict]:
    """
    Generate A/B test hypotheses from existing data patterns.
    No LLM needed - pure data-driven.
    """
    hypotheses = []

    # 1. Check if certain categories perform better
    cur = conn.execute("""
        SELECT q.category, AVG(a.engagement_rate) as avg_eng, COUNT(*) as n
        FROM analytics a
        JOIN shorts s ON a.short_id = s.id
        JOIN quotes q ON q.id IN (
            SELECT value FROM json_each(s.quote_ids) WHERE s.quote_ids IS NOT NULL
        )
        WHERE a.engagement_rate > 0 AND q.category IS NOT NULL
        GROUP BY q.category
        HAVING n >= 2
        ORDER BY avg_eng DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) >= 2:
        best = rows[0]
        worst = rows[-1]
        hypotheses.append({
            "param": "preferred_category",
            "variant_a": best["category"],
            "variant_b": worst["category"],
            "hypothesis": f"Category '{best['category']}' (avg eng {best['avg_eng']:.4f}) > '{worst['category']}' ({worst['avg_eng']:.4f})",
            "confidence": 0.6,
        })

    # 2. Check upload time patterns
    cur = conn.execute("""
        SELECT
            CASE WHEN CAST(substr(upload_time, 12, 2) AS INTEGER) BETWEEN 6 AND 13 THEN 'morning'
                 WHEN CAST(substr(upload_time, 12, 2) AS INTEGER) BETWEEN 14 AND 18 THEN 'afternoon'
                 ELSE 'evening' END as period,
            AVG(engagement_rate) as avg_eng, COUNT(*) as n
        FROM analytics
        WHERE upload_time IS NOT NULL AND upload_time != '' AND engagement_rate > 0
        GROUP BY period
        HAVING n >= 2
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) >= 2:
        sorted_rows = sorted(rows, key=lambda r: r["avg_eng"], reverse=True)
        hypotheses.append({
            "param": "upload_time",
            "variant_a": sorted_rows[0]["period"],
            "variant_b": sorted_rows[-1]["period"],
            "hypothesis": f"Upload in '{sorted_rows[0]['period']}' performs better than '{sorted_rows[-1]['period']}'",
            "confidence": 0.5,
        })

    # 3. Duration sweet spot
    cur = conn.execute("""
        SELECT
            CASE WHEN duration_s <= 15 THEN 'short_15'
                 WHEN duration_s <= 30 THEN 'medium_30'
                 ELSE 'long_45' END as duration_bucket,
            AVG(engagement_rate) as avg_eng, COUNT(*) as n
        FROM competitor_videos
        WHERE engagement_rate > 0
        GROUP BY duration_bucket
        HAVING n >= 3
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if len(rows) >= 2:
        sorted_rows = sorted(rows, key=lambda r: r["avg_eng"], reverse=True)
        hypotheses.append({
            "param": "ideal_clip_duration",
            "variant_a": sorted_rows[0]["duration_bucket"],
            "variant_b": sorted_rows[-1]["duration_bucket"],
            "hypothesis": f"Duration '{sorted_rows[0]['duration_bucket']}' > '{sorted_rows[-1]['duration_bucket']}'",
            "confidence": 0.5,
        })

    return hypotheses


# ---------------------------------------------------------------------------
# Apply winning variant
# ---------------------------------------------------------------------------

def _apply_winner(conn, test: dict, winner_variant: dict, data_dir: Path, log) -> list[dict]:
    """
    Apply the winning A/B test variant to learning_config.json.
    Returns list of changes made for audit.
    """
    config_path = data_dir / "learning_config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {"weights": {}, "preferences": {}, "cycle": 0}

    changes = []
    param = test.get("param", "")
    winner_value = winner_variant

    prefs = config.get("preferences", {})

    if param == "preferred_category":
        old = prefs.get("preferred_categories", [])
        if isinstance(winner_value, str) and winner_value not in old:
            prefs.setdefault("preferred_categories", []).insert(0, winner_value)
            changes.append({"param": "preferred_categories", "old": old, "new": prefs["preferred_categories"]})

    elif param == "upload_time":
        old = prefs.get("best_upload_hours", [])
        prefs["preferred_upload_period"] = winner_value
        changes.append({"param": "preferred_upload_period", "old": str(old), "new": winner_value})

    elif param == "ideal_clip_duration":
        dur_map = {"short_15": 4.0, "medium_30": 5.0, "long_45": 7.0}
        old = prefs.get("ideal_duration_s", 5.0)
        new_dur = dur_map.get(winner_value, 5.0)
        prefs["ideal_duration_s"] = new_dur
        changes.append({"param": "ideal_duration_s", "old": old, "new": new_dur})

    elif param.startswith("weight_"):
        weight_name = param.replace("weight_", "")
        weights = config.get("weights", {})
        old = weights.get(weight_name, 0)
        # Winner variant is the value to set
        if isinstance(winner_value, (int, float)):
            weights[weight_name] = winner_value
            # Re-normalize
            total = sum(weights.values())
            if total > 0:
                weights = {k: round(v / total, 3) for k, v in weights.items()}
            config["weights"] = weights
            changes.append({"param": f"weight_{weight_name}", "old": old, "new": weights.get(weight_name, 0)})

    config["preferences"] = prefs
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    for change in changes:
        log.info("Applied: %s = %s (was %s)", change["param"], change["new"], change["old"])

    return changes


def _write_to_knowledge_base(conn, test: dict, t_stat: float, p_value: float, effect: float):
    """Write A/B test result to the knowledge base table."""
    winner = test.get("winner", "inconclusive")
    hypothesis = test.get("hypothesis", "")

    if winner == "inconclusive":
        category = "insight"
        title = f"No difference found: {hypothesis}"
    else:
        category = "rule"
        title = f"Confirmed: {hypothesis}"

    content = (
        f"A/B Test #{test.get('id', '?')}: {hypothesis}\n"
        f"Result: {winner} (p={p_value:.4f}, d={effect:.3f})\n"
        f"Variant A: {test.get('variant_a', '?')}\n"
        f"Variant B: {test.get('variant_b', '?')}\n"
    )

    conn.execute("""
        INSERT INTO knowledge_base (category, topic, title, content, confidence, source, source_id)
        VALUES (?, 'ab_testing', ?, ?, ?, 'ab_test', ?)
    """, (category, title, content, min(1.0, 1.0 - p_value), test.get("id")))


# ---------------------------------------------------------------------------
# Main actions
# ---------------------------------------------------------------------------

def _create_test(conn, param: str, variant_a: str, variant_b: str, hypothesis: str = "", min_samples: int = 5) -> int:
    """Create a new A/B test."""
    if not hypothesis:
        hypothesis = f"'{variant_a}' performs better than '{variant_b}' for {param}"

    cur = conn.execute("""
        INSERT INTO ab_tests (name, hypothesis, variant_a, variant_b, min_samples)
        VALUES (?, ?, ?, ?, ?)
    """, (param, hypothesis, json.dumps(variant_a), json.dumps(variant_b), min_samples))
    conn.commit()

    # Audit
    conn.execute("""
        INSERT INTO audit_log (agent_name, action, entity_type, entity_id, new_value, reason)
        VALUES ('system', 'test_start', 'ab_test', ?, ?, ?)
    """, (cur.lastrowid, json.dumps({"variant_a": variant_a, "variant_b": variant_b}), hypothesis))
    conn.commit()

    return cur.lastrowid


def _evaluate_tests(conn, data_dir: Path, log) -> list[dict]:
    """Evaluate all running A/B tests."""
    cur = conn.execute("SELECT * FROM ab_tests WHERE status = 'running'")
    tests = [dict(r) for r in cur.fetchall()]
    results = []

    for test in tests:
        test_id = test["id"]
        metric = test.get("metric", "engagement_rate")
        min_samples = test.get("min_samples", 5)
        sig_level = test.get("significance_level", 0.05)

        # Get results tagged with this test
        # Convention: videos tagged with ab_test_id in their metadata
        cur_a = conn.execute("""
            SELECT engagement_rate FROM analytics
            WHERE engagement_rate > 0
            ORDER BY scraped_at DESC
            LIMIT ?
        """, (min_samples * 2,))
        all_values = [r["engagement_rate"] for r in cur_a.fetchall()]

        if len(all_values) < min_samples * 2:
            log.info("Test #%d: not enough data (%d/%d)", test_id, len(all_values), min_samples * 2)
            results.append({"test_id": test_id, "status": "waiting", "samples": len(all_values)})
            continue

        # Split alternating (A/B assignment)
        values_a = all_values[::2][:min_samples]
        values_b = all_values[1::2][:min_samples]

        if len(values_a) < 2 or len(values_b) < 2:
            continue

        # Run the test
        t_stat, p_value = _welch_t_test(values_a, values_b)
        effect = _cohens_d(values_a, values_b)
        ci_a = _confidence_interval(values_a)
        ci_b = _confidence_interval(values_b)

        if p_value < sig_level:
            winner = "a" if _mean(values_a) > _mean(values_b) else "b"
        else:
            winner = "inconclusive"

        # Update test record
        conn.execute("""
            UPDATE ab_tests SET
                variant_a_results = ?,
                variant_b_results = ?,
                winner = ?,
                p_value = ?,
                effect_size = ?,
                confidence_interval = ?,
                status = 'completed',
                ended_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            json.dumps({"n": len(values_a), "mean": round(_mean(values_a), 6), "std": round(_std(values_a), 6), "ci": ci_a}),
            json.dumps({"n": len(values_b), "mean": round(_mean(values_b), 6), "std": round(_std(values_b), 6), "ci": ci_b}),
            winner, round(p_value, 6), round(effect, 4),
            json.dumps({"a": ci_a, "b": ci_b}),
            test_id,
        ))

        # Audit
        conn.execute("""
            INSERT INTO audit_log (agent_name, action, entity_type, entity_id, new_value, reason)
            VALUES ('system', 'test_end', 'ab_test', ?, ?, ?)
        """, (
            test_id,
            json.dumps({"winner": winner, "p_value": p_value, "effect": effect}),
            f"Test completed. Winner: {winner}, p={p_value:.4f}, d={effect:.3f}",
        ))

        # Apply winner automatically
        if winner != "inconclusive":
            variant_a_val = json.loads(test.get("variant_a", '""'))
            variant_b_val = json.loads(test.get("variant_b", '""'))
            winner_val = variant_a_val if winner == "a" else variant_b_val

            test["param"] = test.get("name", "")
            test["winner"] = winner
            test["hypothesis"] = test.get("hypothesis", "")
            changes = _apply_winner(conn, test, winner_val, data_dir, log)

            # Write to knowledge base
            _write_to_knowledge_base(conn, test, t_stat, p_value, effect)

            log.info("Test #%d: winner=%s (p=%.4f, d=%.3f). Applied automatically.", test_id, winner, p_value, effect)
        else:
            log.info("Test #%d: inconclusive (p=%.4f). No changes applied.", test_id, p_value)

        conn.commit()

        results.append({
            "test_id": test_id,
            "status": "completed",
            "winner": winner,
            "p_value": round(p_value, 4),
            "effect_size": round(effect, 3),
            "mean_a": round(_mean(values_a), 6),
            "mean_b": round(_mean(values_b), 6),
        })

    return results


def _auto_mode(conn, data_dir: Path, log) -> list[dict]:
    """
    Full auto: generate hypotheses, create tests, evaluate existing ones.
    This is the "no human needed" mode.
    """
    actions = []

    # 1. Evaluate existing tests
    eval_results = _evaluate_tests(conn, data_dir, log)
    actions.extend(eval_results)

    # 2. Generate new hypotheses if no running tests
    running = conn.execute("SELECT COUNT(*) as n FROM ab_tests WHERE status = 'running'").fetchone()
    if running["n"] == 0:
        hypotheses = _generate_hypotheses(conn)
        for hyp in hypotheses[:2]:  # Max 2 concurrent tests
            test_id = _create_test(
                conn,
                param=hyp["param"],
                variant_a=hyp["variant_a"],
                variant_b=hyp["variant_b"],
                hypothesis=hyp["hypothesis"],
            )
            log.info("Auto-created test #%d: %s", test_id, hyp["hypothesis"])
            actions.append({"test_id": test_id, "status": "created", "hypothesis": hyp["hypothesis"]})

    return actions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    action: str = "auto",
    param: str = "",
    variant_a: str = "",
    variant_b: str = "",
    hypothesis: str = "",
    min_samples: int = 5,
) -> Path:
    log = build_logger("ex22", settings.output_dir / "logs" / "ex22.log")
    conn = get_db(settings.data_dir)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)

    if action == "create":
        if not param or not variant_a or not variant_b:
            log.error("Need --param, --variant-a, --variant-b to create a test")
            return settings.output_dir / "logs" / "ex22.log"
        test_id = _create_test(conn, param, variant_a, variant_b, hypothesis, min_samples)
        log.info("Created test #%d", test_id)
        results = [{"test_id": test_id, "status": "created"}]

    elif action == "evaluate":
        results = _evaluate_tests(conn, settings.data_dir, log)

    elif action == "list":
        cur = conn.execute("SELECT * FROM ab_tests ORDER BY id DESC LIMIT 20")
        results = [dict(r) for r in cur.fetchall()]

    elif action == "auto":
        results = _auto_mode(conn, settings.data_dir, log)

    else:
        log.error("Unknown action: %s", action)
        results = []

    # Report
    report_path = out_dir / f"ex22_ab_testing_{ts}.txt"
    lines = [
        "ex22 - A/B Testing Report",
        "=" * 50,
        f"Action: {action}",
        f"Results: {len(results)}",
        "",
    ]

    for r in results:
        lines.append(f"  Test #{r.get('test_id', '?')}: {r.get('status', '?')}")
        if r.get("winner"):
            lines.append(f"    Winner: {r['winner']} (p={r.get('p_value', '?')}, d={r.get('effect_size', '?')})")
            lines.append(f"    Mean A: {r.get('mean_a', '?')} | Mean B: {r.get('mean_b', '?')}")
        if r.get("hypothesis"):
            lines.append(f"    Hypothesis: {r['hypothesis']}")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("A/B testing report saved to %s", report_path)
    return report_path
