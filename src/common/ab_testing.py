"""
A/B Testing system for YouLikeIt.
Generates variants, tracks results, determines winners, feeds learning.

Flow:
1. Create test: define variable to test + 2 variants
2. Generate: pipeline produces 2 Shorts (same content, different treatment)
3. Publish: both uploaded (one public, one unlisted or both public different hours)
4. Measure: analytics pulled after 48h
5. Conclude: statistical test determines winner
6. Learn: winning approach fed back into persona knowledge/rules
"""
import sqlite3
import json
import math
import logging
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)


# ── Test variables that can be A/B tested ─────────────────────
TESTABLE_VARIABLES = {
    "voice": "Fish Speech vs edge-tts, or different Fish Speech params",
    "cross_ref": "Different cross-reference used in narration",
    "subtitle_style": "Different subtitle appearance (color, size, animation)",
    "intro_type": "Question hook vs statement hook vs quote hook",
    "emotion": "Dark vs epic vs tragic tone for same content",
    "narration_speed": "Slow reflective vs fast energetic pacing",
    "persona": "Same content narrated by different personas",
    "panel_count": "3 panels vs 5 panels per Short",
    "music_genre": "Orchestral vs ambient vs lo-fi suggestion",
}


def create_ab_test(
    conn: sqlite3.Connection,
    name: str,
    hypothesis: str,
    variable: str,
    variant_a_config: dict,
    variant_b_config: dict,
    metric: str = "engagement_rate",
    min_samples: int = 5,
    significance_level: float = 0.05,
) -> int:
    """Create a new A/B test."""
    if variable not in TESTABLE_VARIABLES:
        raise ValueError(f"Variable '{variable}' not testable. Options: {list(TESTABLE_VARIABLES.keys())}")

    cur = conn.execute("""
        INSERT INTO ab_tests (name, hypothesis, status, variant_a, variant_b,
            metric, min_samples, significance_level)
        VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)
    """, (name, hypothesis, json.dumps(variant_a_config),
          json.dumps(variant_b_config), metric, min_samples, significance_level))
    conn.commit()

    test_id = cur.lastrowid
    log.info(f"Created A/B test #{test_id}: {name} ({variable})")

    # Audit
    conn.execute("""INSERT INTO audit_log (agent_name, action, entity_type, entity_id, reason)
        VALUES ('ab_tester', 'create', 'ab_test', ?, ?)""", (test_id, hypothesis))
    conn.commit()

    return test_id


def start_test(conn: sqlite3.Connection, test_id: int) -> dict:
    """Start an A/B test — marks it as running."""
    conn.execute("UPDATE ab_tests SET status='running', started_at=datetime('now') WHERE id=?", (test_id,))
    conn.commit()

    test = dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())
    log.info(f"Started A/B test #{test_id}: {test['name']}")
    return test


def assign_short_to_test(
    conn: sqlite3.Connection,
    test_id: int,
    short_id: int,
    variant: str,  # 'a' or 'b'
) -> None:
    """Assign a Short to a variant of an A/B test."""
    field = f"variant_a_results" if variant == "a" else "variant_b_results"

    # Get current results
    row = conn.execute(f"SELECT {field} FROM ab_tests WHERE id=?", (test_id,)).fetchone()
    results = json.loads(row[0]) if row and row[0] else {"short_ids": [], "values": []}
    results["short_ids"].append(short_id)

    conn.execute(f"UPDATE ab_tests SET {field}=? WHERE id=?", (json.dumps(results), test_id))

    # Tag the Short with the test
    conn.execute("UPDATE shorts SET metadata = json_set(COALESCE(metadata,'{}'), '$.ab_test_id', ?, '$.ab_variant', ?) WHERE id=?",
                 (test_id, variant, short_id))
    conn.commit()
    log.info(f"Assigned Short #{short_id} to test #{test_id} variant {variant.upper()}")


def collect_results(conn: sqlite3.Connection, test_id: int) -> dict:
    """Pull analytics for both variants of a test."""
    test = dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())
    metric = test["metric"]

    results = {"a": {"values": [], "short_ids": []}, "b": {"values": [], "short_ids": []}}

    for variant in ["a", "b"]:
        field = f"variant_{variant}_results"
        data = json.loads(test[field]) if test[field] else {"short_ids": []}

        for sid in data.get("short_ids", []):
            row = conn.execute(f"SELECT {metric} FROM analytics WHERE short_id=? ORDER BY scraped_at DESC LIMIT 1", (sid,)).fetchone()
            if row and row[0] is not None:
                results[variant]["values"].append(row[0])
                results[variant]["short_ids"].append(sid)

    # Update stored results with metrics
    for variant in ["a", "b"]:
        vals = results[variant]["values"]
        stored = {
            "short_ids": results[variant]["short_ids"],
            "values": vals,
            "n": len(vals),
            "mean": sum(vals) / len(vals) if vals else 0,
            "std": _std(vals) if vals else 0,
        }
        field = f"variant_{variant}_results"
        conn.execute(f"UPDATE ab_tests SET {field}=? WHERE id=?", (json.dumps(stored), test_id))

    conn.commit()
    return results


def conclude_test(conn: sqlite3.Connection, test_id: int) -> dict:
    """Run statistical test and determine winner."""
    test = dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())

    a_data = json.loads(test["variant_a_results"]) if test["variant_a_results"] else {}
    b_data = json.loads(test["variant_b_results"]) if test["variant_b_results"] else {}

    a_vals = a_data.get("values", [])
    b_vals = b_data.get("values", [])

    n_a, n_b = len(a_vals), len(b_vals)
    min_samples = test["min_samples"] or 5
    sig_level = test["significance_level"] or 0.05

    result = {
        "test_id": test_id,
        "name": test["name"],
        "n_a": n_a,
        "n_b": n_b,
        "ready": n_a >= min_samples and n_b >= min_samples,
    }

    if not result["ready"]:
        result["status"] = "insufficient_data"
        result["message"] = f"Need {min_samples} samples per variant. Have A={n_a}, B={n_b}"
        return result

    mean_a = sum(a_vals) / n_a
    mean_b = sum(b_vals) / n_b
    std_a = _std(a_vals)
    std_b = _std(b_vals)

    # Welch's t-test (unequal variances)
    t_stat, p_value = _welch_t_test(a_vals, b_vals)

    # Cohen's d (effect size)
    pooled_std = math.sqrt((std_a**2 + std_b**2) / 2) if (std_a + std_b) > 0 else 1
    cohens_d = (mean_b - mean_a) / pooled_std if pooled_std > 0 else 0

    # Determine winner
    if p_value < sig_level:
        winner = "b" if mean_b > mean_a else "a"
        confidence = "significant"
    else:
        winner = "inconclusive"
        confidence = "not_significant"

    # Effect size interpretation
    if abs(cohens_d) < 0.2:
        effect = "negligible"
    elif abs(cohens_d) < 0.5:
        effect = "small"
    elif abs(cohens_d) < 0.8:
        effect = "medium"
    else:
        effect = "large"

    # Update test
    conn.execute("""UPDATE ab_tests SET
        status='completed', winner=?, p_value=?, effect_size=?,
        confidence_interval=?, ended_at=datetime('now')
        WHERE id=?""",
        (winner, p_value, cohens_d,
         json.dumps({"mean_a": mean_a, "mean_b": mean_b, "std_a": std_a, "std_b": std_b}),
         test_id))
    conn.commit()

    result.update({
        "status": "completed",
        "mean_a": round(mean_a, 4),
        "mean_b": round(mean_b, 4),
        "std_a": round(std_a, 4),
        "std_b": round(std_b, 4),
        "t_statistic": round(t_stat, 4),
        "p_value": round(p_value, 4),
        "cohens_d": round(cohens_d, 4),
        "effect_size": effect,
        "confidence": confidence,
        "winner": winner,
        "improvement": f"{abs(mean_b - mean_a) / mean_a * 100:.1f}%" if mean_a > 0 else "N/A",
    })

    log.info(f"A/B test #{test_id} concluded: winner={winner}, p={p_value:.4f}, d={cohens_d:.2f} ({effect})")

    # Feed learning back to persona
    if winner != "inconclusive":
        _apply_learnings(conn, test_id, winner, result)

    return result


def _apply_learnings(conn: sqlite3.Connection, test_id: int, winner: str, result: dict):
    """Feed winning variant back into persona system."""
    test = dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())
    winning_config = json.loads(test[f"variant_{winner}"])
    losing_config = json.loads(test[f"variant_{'b' if winner == 'a' else 'a'}"])

    # Update cross-reference strengths if testing cross-refs
    if "cross_ref" in str(winning_config):
        winning_ref = winning_config.get("cross_ref_target", "")
        losing_ref = losing_config.get("cross_ref_target", "")

        if winning_ref:
            conn.execute("""UPDATE cross_references SET strength = MIN(1.0, strength + 0.1)
                WHERE target_work = ?""", (winning_ref,))
        if losing_ref:
            conn.execute("""UPDATE cross_references SET strength = MAX(0.1, strength - 0.05)
                WHERE target_work = ?""", (losing_ref,))

    # Add knowledge to persona
    persona_id = winning_config.get("persona_id")
    if persona_id:
        learning = f"A/B test '{test['name']}': variant {winner.upper()} won. {winning_config}. Improvement: {result.get('improvement', 'N/A')}. Effect: {result.get('effect_size', 'unknown')}."
        conn.execute("""INSERT INTO persona_knowledge
            (persona_id, knowledge_type, content, source, relevance_score)
            VALUES (?, 'insight', ?, 'a_b_test', 0.9)""",
            (persona_id, learning))

    # Audit
    conn.execute("""INSERT INTO audit_log (agent_name, action, entity_type, entity_id, reason)
        VALUES ('ab_tester', 'test_concluded', 'ab_test', ?, ?)""",
        (test_id, f"Winner: {winner}, p={result.get('p_value', 'N/A')}"))

    conn.commit()
    log.info(f"Applied learnings from test #{test_id} to persona system")


def generate_test_variants(
    conn: sqlite3.Connection,
    test_id: int,
    base_context: dict,
) -> dict:
    """Generate the two variant narration prompts for an A/B test.

    Returns {"a": {prompt, config}, "b": {prompt, config}} ready for production.
    """
    from common.personas import get_persona, build_narration_prompt

    test = dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())
    config_a = json.loads(test["variant_a"])
    config_b = json.loads(test["variant_b"])

    variants = {}
    for label, config in [("a", config_a), ("b", config_b)]:
        persona_name = config.get("persona", "deep_mind")
        persona = get_persona(conn, persona_name)

        # Override persona params with variant config
        context = {**base_context}

        # If testing cross-refs, inject the specific one
        if config.get("cross_ref_target"):
            target = config["cross_ref_target"]
            ref = conn.execute("""SELECT * FROM cross_references
                WHERE target_work = ? AND source_work = ?""",
                (target, base_context.get("series_title", ""))).fetchone()
            if ref:
                desc_field = f"description_{persona_name}"
                context["cross_refs"] = [dict(ref).get(desc_field, "")]

        # If testing intro type
        if config.get("intro_type"):
            # Modify the narration prompt to request specific intro style
            intro_instruction = {
                "question": "Start with a thought-provoking question.",
                "statement": "Start with a bold, declarative statement.",
                "quote": "Start with a famous quote that connects to the content.",
                "statistic": "Start with a surprising statistic or fact.",
            }.get(config["intro_type"], "")
            context["summary"] = f"[INTRO STYLE: {intro_instruction}]\n{context.get('summary', '')}"

        prompt = build_narration_prompt(persona, context)
        variants[label] = {"prompt": prompt, "config": config, "persona": persona_name}

    return variants


def list_tests(conn: sqlite3.Connection, status: str = "") -> list:
    """List all A/B tests."""
    if status:
        rows = conn.execute("SELECT * FROM ab_tests WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM ab_tests ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_test_summary(conn: sqlite3.Connection, test_id: int) -> dict:
    """Get a human-readable summary of a test."""
    test = dict(conn.execute("SELECT * FROM ab_tests WHERE id=?", (test_id,)).fetchone())

    config_a = json.loads(test["variant_a"]) if test["variant_a"] else {}
    config_b = json.loads(test["variant_b"]) if test["variant_b"] else {}
    results_a = json.loads(test["variant_a_results"]) if test["variant_a_results"] else {}
    results_b = json.loads(test["variant_b_results"]) if test["variant_b_results"] else {}

    return {
        "id": test["id"],
        "name": test["name"],
        "hypothesis": test["hypothesis"],
        "status": test["status"],
        "metric": test["metric"],
        "variant_a": {
            "config": config_a,
            "samples": results_a.get("n", 0),
            "mean": round(results_a.get("mean", 0), 4),
        },
        "variant_b": {
            "config": config_b,
            "samples": results_b.get("n", 0),
            "mean": round(results_b.get("mean", 0), 4),
        },
        "winner": test.get("winner"),
        "p_value": test.get("p_value"),
        "effect_size": test.get("effect_size"),
        "started_at": test.get("started_at"),
        "ended_at": test.get("ended_at"),
    }


# ── Statistics helpers ────────────────────────────────────────

def _std(values: list) -> float:
    """Standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))


def _welch_t_test(a: list, b: list) -> tuple:
    """Welch's t-test for two independent samples with unequal variance.
    Returns (t_statistic, p_value_approx).
    """
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0, 1.0

    mean_a = sum(a) / n_a
    mean_b = sum(b) / n_b
    var_a = sum((x - mean_a) ** 2 for x in a) / (n_a - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (n_b - 1)

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return 0.0, 1.0

    t = (mean_a - mean_b) / se

    # Welch-Satterthwaite degrees of freedom
    num = (var_a / n_a + var_b / n_b) ** 2
    den = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = num / den if den > 0 else 1

    # Approximate p-value using t-distribution CDF
    p = _t_to_p(abs(t), df) * 2  # two-tailed
    return t, min(p, 1.0)


def _t_to_p(t: float, df: float) -> float:
    """Approximate one-tailed p-value from t-statistic and degrees of freedom.
    Uses the approximation from Abramowitz and Stegun.
    """
    if df <= 0:
        return 0.5
    x = df / (df + t * t)
    if x >= 1:
        return 0.5

    # Beta function approximation
    a = df / 2
    b = 0.5
    # Use series approximation for regularized incomplete beta
    p = 0.5 * _regularized_beta(x, a, b)
    return max(0, min(1, p))


def _regularized_beta(x: float, a: float, b: float, max_iter: int = 200) -> float:
    """Regularized incomplete beta function via continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    # Use log-gamma for numerical stability
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1 - x) - lbeta) / a

    # Lentz's algorithm for continued fraction
    f = 1.0
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    f = d

    for m in range(1, max_iter):
        # Even step
        numerator = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1.0 + numerator * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + numerator / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        f *= c * d

        # Odd step
        numerator = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + numerator / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = c * d
        f *= delta

        if abs(delta - 1.0) < 1e-8:
            break

    return front * f
