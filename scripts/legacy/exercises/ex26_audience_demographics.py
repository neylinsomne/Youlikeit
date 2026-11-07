"""
ex26 - ETL: Demographics de audiencia + segmentación DBSCAN.

Extract: YouTube Analytics API → demographics (edad, país, género)
Transform: DBSCAN clustering desde cero (sin sklearn)
Load: audience_demographics + audience_segments en SQLite

DBSCAN vs K-Means (estado del arte 2025):
  - DBSCAN detecta outliers (bots, viewers accidentales) como ruido
  - No necesita definir # clusters de antemano
  - Maneja clusters de forma no-esférica
  - Auto-tuning de eps con k-distance knee method

Uso:
  python src/main.py ex26
  python src/main.py ex26 --days-back 90
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger
from utils.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# EXTRACT: YouTube Analytics API demographics
# ---------------------------------------------------------------------------

def _extract_demographics(log, days_back: int = 90) -> dict:
    """
    Extract audience demographics from YouTube Analytics API.

    Returns dict with keys: age_groups, genders, countries
    Each is a list of {dimension_value, viewer_percentage, views, watch_time_minutes}
    """
    try:
        from exercises.ex34_oauth_manager import get_analytics_service
    except ImportError:
        log.warning("ex34_oauth_manager not available")
        return {}

    analytics = get_analytics_service(log=log)
    if not analytics:
        log.warning("YouTube Analytics API not authenticated.")
        return {}

    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    result = {}

    for dimension in ["ageGroup", "gender", "country"]:
        try:
            response = analytics.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="viewerPercentage,views,estimatedMinutesWatched",
                dimensions=dimension,
                sort="-viewerPercentage",
            ).execute()

            rows = response.get("rows", [])
            data = []
            for row in rows:
                data.append({
                    "dimension_value": str(row[0]),
                    "viewer_percentage": float(row[1]),
                    "views": int(row[2]) if len(row) > 2 else 0,
                    "watch_time_minutes": float(row[3]) if len(row) > 3 else 0,
                })

            dim_key = {
                "ageGroup": "age_groups",
                "gender": "genders",
                "country": "countries",
            }.get(dimension, dimension)

            result[dim_key] = data
            log.info("Extracted %d %s entries", len(data), dimension)

        except Exception as e:
            log.warning("Failed to extract %s: %s", dimension, str(e)[:100])

    return result


def _extract_demographics_fallback(conn, log) -> dict:
    """
    Fallback: estimate demographics from analytics data when API is unavailable.
    Uses engagement patterns as proxy for demographic grouping.
    """
    result = {}

    # Group by country if we have geographic data
    cur = conn.execute("""
        SELECT
            CASE
                WHEN hashtags_used LIKE '%colombia%' OR hashtags_used LIKE '%parati%' THEN 'CO'
                WHEN hashtags_used LIKE '%mexico%' OR hashtags_used LIKE '%mexic%' THEN 'MX'
                WHEN hashtags_used LIKE '%españa%' OR hashtags_used LIKE '%spain%' THEN 'ES'
                WHEN hashtags_used LIKE '%fyp%' OR hashtags_used LIKE '%foryou%' THEN 'US'
                ELSE 'OTHER'
            END as country,
            COUNT(*) as n,
            AVG(engagement_rate) as avg_eng
        FROM analytics
        WHERE engagement_rate > 0
        GROUP BY country
        HAVING n >= 2
    """)
    countries = [dict(r) for r in cur.fetchall()]
    total = sum(c["n"] for c in countries)
    result["countries"] = [
        {
            "dimension_value": c["country"],
            "viewer_percentage": round(c["n"] / max(1, total) * 100, 1),
            "views": c["n"],
            "watch_time_minutes": 0,
            "avg_engagement": round(c["avg_eng"], 6),
        }
        for c in countries
    ]

    log.info("Fallback demographics: %d country groups from analytics", len(countries))
    return result


# ---------------------------------------------------------------------------
# TRANSFORM: DBSCAN from scratch
# ---------------------------------------------------------------------------

def _euclidean_distance(a: list[float], b: list[float]) -> float:
    """Euclidean distance between two points."""
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def _normalize_features(data: list[list[float]]) -> list[list[float]]:
    """Min-max normalize each feature to [0, 1]."""
    if not data or not data[0]:
        return data

    n_features = len(data[0])
    mins = [min(row[f] for row in data) for f in range(n_features)]
    maxs = [max(row[f] for row in data) for f in range(n_features)]

    normalized = []
    for row in data:
        norm_row = []
        for f in range(n_features):
            rng = maxs[f] - mins[f]
            norm_row.append((row[f] - mins[f]) / rng if rng > 0 else 0.0)
        normalized.append(norm_row)

    return normalized


def _k_distance(data: list[list[float]], k: int = 4) -> list[float]:
    """
    Compute k-distance for each point (distance to k-th nearest neighbor).
    Used for auto-tuning eps in DBSCAN.
    """
    distances = []
    for i, point in enumerate(data):
        dists = []
        for j, other in enumerate(data):
            if i != j:
                dists.append(_euclidean_distance(point, other))
        dists.sort()
        distances.append(dists[min(k - 1, len(dists) - 1)] if dists else 0.0)
    return distances


def _find_knee_eps(k_distances: list[float]) -> float:
    """
    Find the 'knee' point in the sorted k-distance curve.
    This gives us a good eps value for DBSCAN.

    Uses the maximum curvature method (simplified):
    the point with the largest second derivative.
    """
    sorted_dists = sorted(k_distances)
    n = len(sorted_dists)

    if n < 4:
        return sorted_dists[n // 2] if sorted_dists else 0.5

    # Second derivative approximation
    max_curvature = 0
    knee_idx = n // 2  # default to median

    for i in range(1, n - 1):
        curvature = abs(
            sorted_dists[i + 1] - 2 * sorted_dists[i] + sorted_dists[i - 1]
        )
        if curvature > max_curvature:
            max_curvature = curvature
            knee_idx = i

    return sorted_dists[knee_idx]


def dbscan(
    data: list[list[float]],
    eps: float | None = None,
    min_samples: int = 3,
) -> tuple[list[int], float]:
    """
    DBSCAN clustering from scratch.

    No sklearn, no numpy. Pure Python + math.

    Args:
        data: list of feature vectors
        eps: neighborhood radius (auto-tuned if None)
        min_samples: minimum points to form a cluster

    Returns:
        (labels, eps_used)
        labels[i] = cluster ID (0, 1, 2, ...) or -1 for noise
    """
    n = len(data)
    if n == 0:
        return [], 0.0

    # Normalize features
    normalized = _normalize_features(data)

    # Auto-tune eps using k-distance knee method
    if eps is None:
        k_dists = _k_distance(normalized, k=min_samples)
        eps = _find_knee_eps(k_dists)

    # DBSCAN algorithm
    labels = [-2] * n  # -2 = unvisited, -1 = noise, 0+ = cluster
    cluster_id = 0

    def region_query(point_idx: int) -> list[int]:
        """Find all points within eps distance."""
        neighbors = []
        for j in range(n):
            if _euclidean_distance(normalized[point_idx], normalized[j]) <= eps:
                neighbors.append(j)
        return neighbors

    def expand_cluster(point_idx: int, neighbors: list[int], cid: int):
        """Expand a cluster from a core point."""
        labels[point_idx] = cid
        i = 0
        while i < len(neighbors):
            nb = neighbors[i]
            if labels[nb] == -2:  # Unvisited
                labels[nb] = cid
                nb_neighbors = region_query(nb)
                if len(nb_neighbors) >= min_samples:
                    # This is also a core point - expand
                    for nn in nb_neighbors:
                        if nn not in neighbors:
                            neighbors.append(nn)
            elif labels[nb] == -1:  # Was noise, now border point
                labels[nb] = cid
            i += 1

    for i in range(n):
        if labels[i] != -2:
            continue

        neighbors = region_query(i)

        if len(neighbors) < min_samples:
            labels[i] = -1  # Noise
        else:
            expand_cluster(i, neighbors, cluster_id)
            cluster_id += 1

    return labels, eps


def _transform_build_segments(
    demographics: dict,
    engagement_by_group: dict,
    min_samples: int = 3,
) -> tuple[list[dict], dict]:
    """
    Build audience segments using DBSCAN on demographic + engagement features.

    Feature vector per demographic group:
      [viewer_percentage, avg_engagement, avg_watch_time]
    """
    # Build feature matrix
    groups = []
    feature_vectors = []

    for dim_key in ["countries", "age_groups", "genders"]:
        for entry in demographics.get(dim_key, []):
            val = entry["dimension_value"]
            eng = engagement_by_group.get(val, {}).get("avg_engagement", 0)
            wt = entry.get("watch_time_minutes", 0)
            vp = entry.get("viewer_percentage", 0)

            groups.append({
                "dimension": dim_key.rstrip("s"),
                "value": val,
                "viewer_percentage": vp,
                "avg_engagement": eng,
                "watch_time": wt,
            })
            feature_vectors.append([vp, eng * 1000, wt])  # Scale engagement

    if len(feature_vectors) < 4:
        # Not enough data for DBSCAN
        return [{
            "segment_name": "all_viewers",
            "core_points": json.dumps(list(range(len(groups)))),
            "size": len(groups),
            "noise_count": 0,
            "characteristics": json.dumps(groups),
            "eps_used": 0,
            "min_samples_used": min_samples,
        }], {"method": "fallback_single_segment", "reason": "n < 4"}

    # Run DBSCAN
    labels, eps_used = dbscan(feature_vectors, min_samples=min_samples)

    # Build segments from labels
    segments = []
    unique_labels = set(labels)

    for label in sorted(unique_labels):
        if label == -1:
            continue  # Skip noise

        members = [i for i, l in enumerate(labels) if l == label]
        member_groups = [groups[i] for i in members]

        # Determine dominant characteristics
        countries = [g["value"] for g in member_groups if g["dimension"] == "country"]
        ages = [g["value"] for g in member_groups if g["dimension"] == "age_group"]

        avg_eng = sum(g["avg_engagement"] for g in member_groups) / len(member_groups) if member_groups else 0
        avg_vp = sum(g["viewer_percentage"] for g in member_groups) / len(member_groups) if member_groups else 0

        # Auto-name segment
        if avg_eng > 0.05:
            name = f"high_engagement_segment_{label}"
        elif avg_vp > 15:
            name = f"large_audience_segment_{label}"
        else:
            name = f"niche_segment_{label}"

        segments.append({
            "segment_name": name,
            "core_points": json.dumps(members),
            "size": len(members),
            "noise_count": 0,
            "characteristics": json.dumps({
                "countries": countries,
                "age_groups": ages,
                "avg_engagement": round(avg_eng, 6),
                "avg_viewer_percentage": round(avg_vp, 2),
                "members": member_groups,
            }),
            "eps_used": round(eps_used, 4),
            "min_samples_used": min_samples,
        })

    # Count noise
    noise_count = sum(1 for l in labels if l == -1)
    noise_members = [groups[i] for i, l in enumerate(labels) if l == -1]

    meta = {
        "method": "dbscan",
        "eps": round(eps_used, 4),
        "min_samples": min_samples,
        "n_clusters": len(segments),
        "noise_count": noise_count,
        "noise_members": noise_members[:10],  # Cap for report
        "total_points": len(feature_vectors),
    }

    return segments, meta


# ---------------------------------------------------------------------------
# LOAD: Store in SQLite
# ---------------------------------------------------------------------------

def _load_demographics(conn, demographics: dict, snapshot_date: str):
    """Load demographic data into the database."""
    for dim_key in ["countries", "age_groups", "genders"]:
        dimension = dim_key.rstrip("s").replace("_", " ")
        for entry in demographics.get(dim_key, []):
            conn.execute("""
                INSERT INTO audience_demographics
                    (snapshot_date, dimension, dimension_value, viewer_percentage,
                     watch_time_minutes, views, avg_engagement)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot_date,
                dimension,
                entry["dimension_value"],
                entry.get("viewer_percentage", 0),
                entry.get("watch_time_minutes", 0),
                entry.get("views", 0),
                entry.get("avg_engagement"),
            ))


def _load_segments(conn, segments: list[dict]):
    """Load audience segments into the database."""
    # Clear old segments
    conn.execute("DELETE FROM audience_segments")

    for seg in segments:
        conn.execute("""
            INSERT INTO audience_segments
                (segment_name, core_points, size, noise_count, characteristics,
                 eps_used, min_samples_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            seg["segment_name"],
            seg["core_points"],
            seg["size"],
            seg.get("noise_count", 0),
            seg.get("characteristics", "{}"),
            seg.get("eps_used", 0),
            seg.get("min_samples_used", 3),
        ))


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    days_back: int = 90,
    min_samples: int = 3,
) -> Path:
    log = build_logger("ex26", settings.output_dir / "logs" / "ex26.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex26")

    # ── EXTRACT ──
    tracker.extract_start()
    log.info("Extract: fetching demographics (last %d days)...", days_back)

    demographics = _extract_demographics(log, days_back)
    if not demographics:
        log.info("Analytics API not available. Using fallback.")
        demographics = _extract_demographics_fallback(conn, log)

    tracker.extract_done({
        "countries": len(demographics.get("countries", [])),
        "age_groups": len(demographics.get("age_groups", [])),
        "genders": len(demographics.get("genders", [])),
    })

    # Get engagement data per group for DBSCAN features
    engagement_by_group = {}
    cur = conn.execute("""
        SELECT
            COALESCE(hashtags_used, '') as group_key,
            AVG(engagement_rate) as avg_engagement
        FROM analytics
        WHERE engagement_rate > 0
        GROUP BY group_key
    """)
    for row in cur.fetchall():
        engagement_by_group[row["group_key"]] = {"avg_engagement": row["avg_engagement"]}

    # ── TRANSFORM ──
    tracker.transform_start("DBSCAN clustering")
    log.info("Transform: running DBSCAN segmentation...")

    segments, dbscan_meta = _transform_build_segments(
        demographics, engagement_by_group, min_samples=min_samples
    )

    tracker.transform_done({
        "method": dbscan_meta.get("method", "unknown"),
        "n_clusters": dbscan_meta.get("n_clusters", len(segments)),
        "noise_count": dbscan_meta.get("noise_count", 0),
        "eps": dbscan_meta.get("eps", 0),
    })

    log.info(
        "DBSCAN result: %d clusters, %d noise points (eps=%.4f)",
        dbscan_meta.get("n_clusters", len(segments)),
        dbscan_meta.get("noise_count", 0),
        dbscan_meta.get("eps", 0),
    )

    # ── LOAD ──
    tracker.load_start()

    snapshot_date = datetime.utcnow().strftime("%Y-%m-%d")
    _load_demographics(conn, demographics, snapshot_date)
    _load_segments(conn, segments)
    conn.commit()

    tracker.load_done({
        "demographics_rows": sum(len(v) for v in demographics.values()),
        "segments": len(segments),
    })

    # ── REPORT ──
    tracker.complete({
        "segments": len(segments),
        "noise": dbscan_meta.get("noise_count", 0),
    })

    out_dir = settings.output_dir / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # JSON report
    json_path = out_dir / f"ex26_demographics_{ts}.json"
    json_path.write_text(json.dumps({
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "demographics": demographics,
        "segments": segments,
        "dbscan_meta": dbscan_meta,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Text report
    report_path = out_dir / f"ex26_demographics_{ts}.txt"
    lines = [
        "ex26 - Audience Demographics & Segmentation ETL",
        "=" * 55,
        f"Period: last {days_back} days",
        f"Data source: {'YouTube Analytics API' if demographics.get('age_groups') else 'Fallback estimates'}",
        "",
        "Demographics:",
    ]

    for dim_key in ["countries", "age_groups", "genders"]:
        entries = demographics.get(dim_key, [])
        if entries:
            lines.append(f"  {dim_key}:")
            for e in entries[:10]:
                lines.append(f"    {e['dimension_value']}: {e.get('viewer_percentage', 0):.1f}%")

    lines.append("")
    lines.append(f"DBSCAN Segmentation (eps={dbscan_meta.get('eps', 0):.4f}):")
    lines.append(f"  Clusters found: {dbscan_meta.get('n_clusters', len(segments))}")
    lines.append(f"  Noise points (outliers/bots): {dbscan_meta.get('noise_count', 0)}")
    lines.append(f"  Total data points: {dbscan_meta.get('total_points', 0)}")

    for seg in segments:
        chars = json.loads(seg.get("characteristics", "{}"))
        lines.append(f"  [{seg['segment_name']}] size={seg['size']}")
        if chars.get("countries"):
            lines.append(f"    Countries: {', '.join(chars['countries'][:5])}")
        if chars.get("avg_engagement"):
            lines.append(f"    Avg engagement: {chars['avg_engagement']:.4f}")

    noise_members = dbscan_meta.get("noise_members", [])
    if noise_members:
        lines.append(f"  Noise (outliers, not assigned to any cluster):")
        for nm in noise_members[:5]:
            lines.append(f"    {nm.get('dimension', '?')}: {nm.get('value', '?')} (eng: {nm.get('avg_engagement', 0):.4f})")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    conn.close()
    log.info("Demographics ETL complete. Report: %s", report_path)
    return report_path
