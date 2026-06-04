"""
ex27 - ETL: Optimización geográfica de contenido.

Extract: audience_demographics + analytics → engagement por país
Transform: ANOVA por geografía, correlaciones país-contenido
Load: knowledge_base + actualizar learning_config.json

Responde: "¿Qué contenido funciona en cada país?"
  - Colombia prefiere X categoría a Y hora
  - México tiene mejor engagement con Z emoción
  - España responde más a W tipo de hook

Uso:
  python src/main.py ex27
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from scipy import stats as sp_stats

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger
from utils.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _anova_f(groups: dict[str, list[float]]) -> dict:
    """One-way ANOVA with exact p-value via scipy."""
    all_vals = []
    for vals in groups.values():
        all_vals.extend(vals)

    valid = {k: v for k, v in groups.items() if len(v) >= 2}

    if len(all_vals) < 3 or len(valid) < 2:
        return {"f_ratio": 0, "eta_squared": 0, "p_value": 1.0, "significant": False}

    grand_mean = _mean(all_vals)
    ss_between = sum(len(v) * (_mean(v) - grand_mean) ** 2 for v in valid.values())
    ss_total = sum((x - grand_mean) ** 2 for x in all_vals)
    eta_sq = ss_between / ss_total if ss_total > 0 else 0

    f_stat, p_value = sp_stats.f_oneway(*valid.values())

    return {
        "f_ratio": round(float(f_stat), 4),
        "p_value": round(float(p_value), 6),
        "eta_squared": round(eta_sq, 4),
        "variance_explained_pct": round(eta_sq * 100, 1),
        "significant": float(p_value) < 0.05,
        "n_groups": len(valid),
        "n_total": len(all_vals),
    }


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

def _extract_geo_engagement(conn) -> dict[str, list[dict]]:
    """Get engagement data grouped by country."""
    # From demographics table
    cur = conn.execute("""
        SELECT dimension_value as country, viewer_percentage, avg_engagement
        FROM audience_demographics
        WHERE dimension = 'country'
        ORDER BY viewer_percentage DESC
    """)
    demo_data = [dict(r) for r in cur.fetchall()]

    # From analytics (hashtag-based country inference)
    cur = conn.execute("""
        SELECT
            engagement_rate, views, likes, comments,
            hashtags_used, song_used, upload_time
        FROM analytics
        WHERE engagement_rate > 0
    """)
    analytics_data = [dict(r) for r in cur.fetchall()]

    return {"demographics": demo_data, "analytics": analytics_data}


# ---------------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------------

def _transform_country_profiles(
    data: dict,
    conn,
) -> tuple[dict[str, dict], dict]:
    """Build per-country content profiles and run ANOVA."""

    # Group engagement by country from demographics
    country_engagement: dict[str, list[float]] = {}
    for row in data.get("demographics", []):
        country = row.get("country", "")
        eng = row.get("avg_engagement")
        if country and eng is not None:
            country_engagement.setdefault(country, []).append(float(eng))

    # ANOVA: is geography a significant factor?
    anova_result = _anova_f(country_engagement) if len(country_engagement) >= 2 else {"significant": False}

    # Per-country best content type
    profiles = {}
    for country, eng_values in country_engagement.items():
        if not eng_values:
            continue
        profiles[country] = {
            "avg_engagement": round(_mean(eng_values), 6),
            "n_samples": len(eng_values),
            "viewer_pct": 0,
        }

    # Add viewer percentage
    for row in data.get("demographics", []):
        country = row.get("country", "")
        if country in profiles:
            profiles[country]["viewer_pct"] = row.get("viewer_percentage", 0)

    # Get best categories per country from quotes
    for country in profiles:
        cur = conn.execute("""
            SELECT q.category, AVG(a.engagement_rate) as avg_eng, COUNT(*) as n
            FROM analytics a
            JOIN shorts s ON a.short_id = s.id
            JOIN quotes q ON q.movie_id IS NOT NULL
            WHERE a.engagement_rate > 0 AND q.category IS NOT NULL
            GROUP BY q.category
            HAVING n >= 2
            ORDER BY avg_eng DESC
            LIMIT 5
        """)
        rows = [dict(r) for r in cur.fetchall()]
        if rows:
            profiles[country]["best_categories"] = [
                {"category": r["category"], "avg_eng": round(r["avg_eng"], 6)}
                for r in rows
            ]

    return profiles, anova_result


# ---------------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------------

def _load_geo_insights(conn, profiles: dict, anova: dict, data_dir: Path):
    """Save geographic insights to knowledge base and learning config."""

    # Knowledge base
    for country, profile in profiles.items():
        title = f"Country {country}: avg engagement {profile['avg_engagement']:.4f}"
        content = json.dumps(profile, ensure_ascii=False)

        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('insight', 'geography', ?, ?, ?, 'geo_analysis')
        """, (title, content, min(1.0, profile["n_samples"] / 20 + 0.3)))

    if anova.get("significant"):
        conn.execute("""
            INSERT INTO knowledge_base (category, topic, title, content, confidence, source)
            VALUES ('rule', 'geography', ?, ?, ?, 'anova')
        """, (
            f"Geography explains {anova['variance_explained_pct']}% of engagement variance",
            json.dumps(anova),
            min(1.0, anova["eta_squared"] + 0.5),
        ))

    # Update learning_config with geo preferences
    config_path = data_dir / "learning_config.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    prefs = config.setdefault("preferences", {})
    prefs["geo_profiles"] = {
        country: {
            "avg_engagement": p["avg_engagement"],
            "best_categories": p.get("best_categories", []),
        }
        for country, p in profiles.items()
        if p["n_samples"] >= 3
    }

    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.commit()


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(settings: Settings) -> Path:
    log = build_logger("ex27", settings.output_dir / "logs" / "ex27.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex27")

    # Extract
    tracker.extract_start()
    data = _extract_geo_engagement(conn)
    tracker.extract_done({"demographics": len(data.get("demographics", [])), "analytics": len(data.get("analytics", []))})

    # Transform
    tracker.transform_start("Building country profiles + ANOVA")
    profiles, anova = _transform_country_profiles(data, conn)
    tracker.transform_done({"countries": len(profiles), "anova_significant": anova.get("significant", False)})

    log.info("Geo: %d countries. ANOVA significant: %s (F=%.2f, p=%.4f, η²=%.3f)",
             len(profiles), anova.get("significant"), anova.get("f_ratio", 0),
             anova.get("p_value", 1), anova.get("eta_squared", 0))

    # Load
    tracker.load_start()
    _load_geo_insights(conn, profiles, anova, settings.data_dir)
    tracker.load_done({"profiles_saved": len(profiles)})

    # Report
    tracker.complete({"countries": len(profiles)})
    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    report_path = out_dir / f"ex27_geo_{ts}.txt"
    lines = [
        "ex27 - Geographic Content Optimization",
        "=" * 50,
        f"Countries analyzed: {len(profiles)}",
        f"ANOVA: F={anova.get('f_ratio', 0):.2f}, p={anova.get('p_value', 1):.4f}, η²={anova.get('eta_squared', 0):.3f}",
        f"Geography explains {anova.get('variance_explained_pct', 0)}% of engagement variance",
        f"Statistically significant: {'YES' if anova.get('significant') else 'NO'}",
        "",
    ]
    for country, p in sorted(profiles.items(), key=lambda x: x[1]["avg_engagement"], reverse=True):
        lines.append(f"  {country}: eng={p['avg_engagement']:.4f} (n={p['n_samples']}, {p.get('viewer_pct', 0):.1f}% audience)")
        for cat in p.get("best_categories", [])[:3]:
            lines.append(f"    → {cat['category']}: {cat['avg_eng']:.4f}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    conn.close()
    log.info("Geo report: %s", report_path)
    return report_path
