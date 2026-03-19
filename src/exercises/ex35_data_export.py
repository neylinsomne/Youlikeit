"""
ex35 - ETL: Exportar datos y generar reporte de estado del canal.

Extract: Todas las tablas de la BD
Transform: Generar CSV/JSON + reporte resumen del canal
Load: Archivos en outputs/exports/

Exporta:
  - movies.csv, quotes.csv, analytics.csv, shorts.csv
  - knowledge_base.json (insights acumulados)
  - curriculum_plan.json (plan de contenido)
  - channel_report.txt (reporte ejecutivo del canal)
  - backup completo: shorts_pipeline_backup_YYYYMMDD.db

Uso:
  python src/main.py ex35
  python src/main.py ex35 --format csv
  python src/main.py ex35 --format json
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from datetime import datetime
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from common.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------------

def _extract_table(conn, table: str, limit: int = 0) -> tuple[list[str], list[dict]]:
    """Extract all rows from a table. Returns (columns, rows)."""
    query = f"SELECT * FROM {table}"
    if limit > 0:
        query += f" LIMIT {limit}"
    cur = conn.execute(query)
    columns = [desc[0] for desc in cur.description] if cur.description else []
    rows = [dict(r) for r in cur.fetchall()]
    return columns, rows


def _extract_summary_stats(conn) -> dict:
    """Extract high-level stats about the channel pipeline."""
    stats = {}

    # Movies
    cur = conn.execute("SELECT COUNT(*) as n FROM movies")
    stats["movies_total"] = cur.fetchone()["n"]

    # Quotes
    cur = conn.execute("SELECT COUNT(*) as n FROM quotes")
    stats["quotes_total"] = cur.fetchone()["n"]

    cur = conn.execute("SELECT COUNT(*) as n FROM quotes WHERE start_ms IS NOT NULL")
    stats["quotes_with_timestamps"] = cur.fetchone()["n"]

    cur = conn.execute("SELECT COUNT(*) as n FROM quotes WHERE category IS NOT NULL")
    stats["quotes_classified"] = cur.fetchone()["n"]

    cur = conn.execute("SELECT COUNT(*) as n FROM quotes WHERE learning_type IS NOT NULL")
    stats["quotes_with_learning_type"] = cur.fetchone()["n"]

    # Shorts
    cur = conn.execute("SELECT COUNT(*) as n, status FROM shorts GROUP BY status")
    stats["shorts_by_status"] = {r["status"]: r["n"] for r in cur.fetchall()}
    stats["shorts_total"] = sum(stats["shorts_by_status"].values())

    # Analytics
    cur = conn.execute("""
        SELECT COUNT(*) as n,
               COALESCE(SUM(views), 0) as total_views,
               COALESCE(SUM(likes), 0) as total_likes,
               COALESCE(AVG(engagement_rate), 0) as avg_engagement,
               COALESCE(AVG(retention_avg), 0) as avg_retention
        FROM analytics
        WHERE platform = 'youtube'
    """)
    row = cur.fetchone()
    stats["analytics_entries"] = row["n"]
    stats["total_views"] = row["total_views"]
    stats["total_likes"] = row["total_likes"]
    stats["avg_engagement"] = round(row["avg_engagement"], 4)
    stats["avg_retention"] = round(row["avg_retention"], 2)

    # Knowledge base
    cur = conn.execute("SELECT COUNT(*) as n FROM knowledge_base WHERE is_active = 1")
    stats["active_insights"] = cur.fetchone()["n"]

    # AB Tests
    cur = conn.execute("SELECT COUNT(*) as n, status FROM ab_tests GROUP BY status")
    stats["ab_tests"] = {r["status"]: r["n"] for r in cur.fetchall()}

    # Goals
    cur = conn.execute("SELECT metric, target_value, current_value, status FROM goals WHERE status = 'active'")
    stats["active_goals"] = [dict(r) for r in cur.fetchall()]

    # Curriculum plan
    cur = conn.execute("SELECT COUNT(*) as n, status FROM curriculum_plan GROUP BY status")
    stats["curriculum"] = {r["status"]: r["n"] for r in cur.fetchall()}

    # Top categories
    cur = conn.execute("""
        SELECT category, COUNT(*) as n
        FROM quotes
        WHERE category IS NOT NULL
        GROUP BY category
        ORDER BY n DESC
    """)
    stats["top_categories"] = {r["category"]: r["n"] for r in cur.fetchall()}

    # Top emotions
    cur = conn.execute("""
        SELECT emotion, COUNT(*) as n
        FROM quotes
        WHERE emotion IS NOT NULL
        GROUP BY emotion
        ORDER BY n DESC
    """)
    stats["top_emotions"] = {r["emotion"]: r["n"] for r in cur.fetchall()}

    # Learning type distribution
    cur = conn.execute("""
        SELECT learning_type, COUNT(*) as n
        FROM quotes
        WHERE learning_type IS NOT NULL
        GROUP BY learning_type
        ORDER BY n DESC
    """)
    stats["learning_types"] = {r["learning_type"]: r["n"] for r in cur.fetchall()}

    # Retention events
    cur = conn.execute("""
        SELECT event_type, COUNT(*) as n
        FROM retention_events
        GROUP BY event_type
        ORDER BY n DESC
    """)
    stats["retention_events"] = {r["event_type"]: r["n"] for r in cur.fetchall()}

    # Audience segments
    cur = conn.execute("SELECT COUNT(*) as n FROM audience_segments")
    stats["audience_segments"] = cur.fetchone()["n"]

    return stats


# ---------------------------------------------------------------------------
# TRANSFORM: Generate exports
# ---------------------------------------------------------------------------

def _transform_to_csv(columns: list[str], rows: list[dict]) -> str:
    """Convert rows to CSV string."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def _transform_channel_report(stats: dict) -> str:
    """Generate a human-readable channel status report."""
    lines = [
        "═" * 60,
        "  CHANNEL STATUS REPORT",
        f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "═" * 60,
        "",
        "─── Pipeline Coverage ───",
        f"  Movies discovered:        {stats['movies_total']:>6d}",
        f"  Quotes extracted:         {stats['quotes_total']:>6d}",
        f"  Quotes with timestamps:   {stats['quotes_with_timestamps']:>6d}",
        f"  Quotes classified:        {stats['quotes_classified']:>6d}",
        f"  Quotes with lesson type:  {stats['quotes_with_learning_type']:>6d}",
        f"  Shorts total:             {stats['shorts_total']:>6d}",
        "",
    ]

    if stats["shorts_by_status"]:
        lines.append("  Shorts by status:")
        for status, n in stats["shorts_by_status"].items():
            lines.append(f"    {status:15s} {n:>4d}")

    lines.extend([
        "",
        "─── Performance ───",
        f"  Total views:          {stats['total_views']:>10,d}",
        f"  Total likes:          {stats['total_likes']:>10,d}",
        f"  Avg engagement rate:  {stats['avg_engagement']:>10.4f}",
        f"  Avg retention:        {stats['avg_retention']:>10.2f}%",
        f"  Analytics entries:    {stats['analytics_entries']:>10d}",
        "",
    ])

    if stats.get("top_categories"):
        lines.append("─── Content Distribution ───")
        lines.append("  Categories:")
        for cat, n in stats["top_categories"].items():
            bar = "█" * max(1, n * 30 // max(stats["top_categories"].values()))
            lines.append(f"    {cat:15s} {n:4d} {bar}")

    if stats.get("learning_types"):
        lines.append("  Learning types:")
        for lt, n in stats["learning_types"].items():
            bar = "█" * max(1, n * 30 // max(stats["learning_types"].values()))
            lines.append(f"    {lt:25s} {n:4d} {bar}")

    if stats.get("retention_events"):
        lines.append("")
        lines.append("─── Retention Events ───")
        for evt, n in stats["retention_events"].items():
            lines.append(f"    {evt:15s} {n:4d}")

    lines.append("")
    lines.append("─── Intelligence ───")
    lines.append(f"  Active insights:      {stats['active_insights']:>6d}")
    lines.append(f"  Audience segments:    {stats['audience_segments']:>6d}")

    if stats.get("ab_tests"):
        lines.append("  A/B tests:")
        for status, n in stats["ab_tests"].items():
            lines.append(f"    {status:15s} {n:>4d}")

    if stats.get("active_goals"):
        lines.append("")
        lines.append("─── Active Goals ───")
        for goal in stats["active_goals"]:
            progress = (
                round(goal["current_value"] / goal["target_value"] * 100, 1)
                if goal["target_value"] > 0 else 0
            )
            lines.append(
                f"  {goal['metric']:20s}  "
                f"{goal['current_value']:.1f} / {goal['target_value']:.1f}  "
                f"({progress:.0f}%)"
            )

    if stats.get("curriculum"):
        lines.append("")
        lines.append("─── Curriculum Plan ───")
        for status, n in stats["curriculum"].items():
            lines.append(f"    {status:15s} {n:>4d}")

    lines.append("")
    lines.append("═" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LOAD: Write files
# ---------------------------------------------------------------------------

EXPORT_TABLES = [
    "movies", "quotes", "shorts", "analytics", "subtitles",
    "competitor_videos", "retention_events", "audience_demographics",
    "audience_segments", "ab_tests", "goals", "curriculum_plan",
]


def _load_exports(
    conn,
    export_dir: Path,
    fmt: str = "csv",
    log=None,
) -> list[Path]:
    """Export tables to files."""
    files: list[Path] = []

    for table in EXPORT_TABLES:
        try:
            columns, rows = _extract_table(conn, table)
        except Exception as e:
            if log:
                log.warning("Skip table %s: %s", table, e)
            continue

        if not rows:
            continue

        if fmt == "csv":
            content = _transform_to_csv(columns, rows)
            path = export_dir / f"{table}.csv"
            path.write_text(content, encoding="utf-8")
        else:
            path = export_dir / f"{table}.json"
            path.write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

        files.append(path)
        if log:
            log.info("  Exported %s: %d rows → %s", table, len(rows), path.name)

    # Knowledge base (always JSON - has nested JSON fields)
    columns, rows = _extract_table(conn, "knowledge_base")
    if rows:
        path = export_dir / "knowledge_base.json"
        path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        files.append(path)

    return files


# ---------------------------------------------------------------------------
# Main ETL
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    fmt: str = "csv",
) -> Path:
    log = build_logger("ex35", settings.output_dir / "logs" / "ex35.log")
    conn = get_db(settings.data_dir)
    tracker = ETLTracker("ex35")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    export_dir = settings.output_dir / "exports" / ts
    export_dir.mkdir(parents=True, exist_ok=True)

    # ── EXTRACT ──
    tracker.extract_start()
    stats = _extract_summary_stats(conn)
    tracker.extract_done({"tables": len(EXPORT_TABLES), "movies": stats["movies_total"]})
    log.info("Extract: %d movies, %d quotes, %d shorts", stats["movies_total"], stats["quotes_total"], stats["shorts_total"])

    # ── TRANSFORM + LOAD: Export tables ──
    tracker.transform_start(f"Exporting tables as {fmt}")
    files = _load_exports(conn, export_dir, fmt=fmt, log=log)
    tracker.transform_done({"files_exported": len(files)})

    # ── Channel report ──
    tracker.load_start()
    report_text = _transform_channel_report(stats)
    report_path = export_dir / "channel_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    files.append(report_path)

    # ── DB backup ──
    db_path = settings.data_dir / "shorts_pipeline.db"
    if db_path.exists():
        backup_name = f"shorts_pipeline_backup_{ts}.db"
        backup_path = export_dir / backup_name
        shutil.copy2(str(db_path), str(backup_path))
        files.append(backup_path)
        log.info("  DB backup: %s", backup_path.name)

    tracker.load_done({"total_files": len(files)})

    # ── REPORT ──
    tracker.complete({
        "export_dir": str(export_dir),
        "files": len(files),
        "format": fmt,
    })

    # Print summary
    print(f"\nExport complete: {export_dir}")
    print(f"  Files: {len(files)}")
    for f in files:
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name:40s} {size_kb:8.1f} KB")

    conn.close()
    log.info("Export complete: %s (%d files)", export_dir, len(files))
    return report_path
