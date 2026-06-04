"""
Bootstrap the A/B tests for the hook / retention strategy.

Creates three tests (idempotent — won't duplicate if already created):

  1. hook_cps_strong_vs_baseline
       Variant A (control):    hook_cps = 0.5   (legacy, no hook expansion)
       Variant B (treatment):  hook_cps = 2.5   (per-persona average target)
       Metric: retention_at_3s

  2. hook_style_centered_vs_bottom
       Variant A: subtitle Style=Main (bottom anchor, default size)
       Variant B: subtitle Style=Hook (centered, 1.4x, accent keyword)
       Metric: retention_at_3s

  3. hook_text_question_vs_declaration
       Variant A: question opening
       Variant B: contrarian declaration opening
       Metric: engagement_rate

Usage:
    python scripts/setup_hook_ab_tests.py
    python scripts/setup_hook_ab_tests.py --list
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from apps.scoring import ab_testing
from core.db import get_db


TESTS = [
    {
        "name": "hook_cps_strong_vs_baseline",
        "hypothesis": (
            "Shorts with hook_cps>=2.0 retain more than 75% of viewers at 3s "
            "vs the 0.5 baseline that yields the legacy single-cut hook."
        ),
        "variable": "hook_cps",
        "variant_a": {"hook_cps": 0.5, "label": "baseline_no_hook"},
        "variant_b": {"hook_cps": 2.5, "label": "strong_hook_avg"},
        "metric": "retention_at_3s",
        "min_samples": 3,
        "significance_level": 0.10,
    },
    {
        "name": "hook_style_centered_vs_bottom",
        "hypothesis": (
            "Centered Hook subtitle (1.4x size, accent keyword) outperforms "
            "the default bottom-anchored Main subtitle on retention_at_3s."
        ),
        "variable": "hook_style",
        "variant_a": {"hook_style": "Main", "label": "subtitle_bottom_default"},
        "variant_b": {"hook_style": "Hook", "label": "subtitle_centered_accent"},
        "metric": "retention_at_3s",
        "min_samples": 3,
        "significance_level": 0.10,
    },
    {
        "name": "hook_text_question_vs_declaration",
        "hypothesis": (
            "Contrarian declarations as opening (e.g. 'Griffith was right.') "
            "drive higher engagement_rate than open questions."
        ),
        "variable": "hook_text",
        "variant_a": {"hook_text": "question", "label": "open_question"},
        "variant_b": {"hook_text": "declaration", "label": "contrarian_declaration"},
        "metric": "engagement_rate",
        "min_samples": 4,
        "significance_level": 0.10,
    },
]


def _exists(conn: sqlite3.Connection, name: str) -> int | None:
    row = conn.execute("SELECT id FROM ab_tests WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _ensure_table(conn: sqlite3.Connection):
    """Create ab_tests + audit_log if they don't already exist (idempotent)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            hypothesis TEXT,
            status TEXT DEFAULT 'draft',
            variant_a TEXT,
            variant_b TEXT,
            variant_a_results TEXT,
            variant_b_results TEXT,
            metric TEXT,
            min_samples INTEGER DEFAULT 5,
            significance_level REAL DEFAULT 0.05,
            winner TEXT,
            p_value REAL,
            effect_size REAL,
            confidence_interval TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            ended_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT,
            action TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()


def setup():
    try:
        from core.config import Settings
        conn = get_db(Settings().data_dir)
    except Exception:
        # Fallback: open the DB directly
        conn = sqlite3.connect("data/shorts_pipeline.db")
        conn.row_factory = sqlite3.Row

    _ensure_table(conn)

    created, skipped = [], []
    for spec in TESTS:
        existing = _exists(conn, spec["name"])
        if existing is not None:
            skipped.append((existing, spec["name"]))
            continue
        test_id = ab_testing.create_ab_test(
            conn=conn,
            name=spec["name"],
            hypothesis=spec["hypothesis"],
            variable=spec["variable"],
            variant_a_config=spec["variant_a"],
            variant_b_config=spec["variant_b"],
            metric=spec["metric"],
            min_samples=spec["min_samples"],
            significance_level=spec["significance_level"],
        )
        ab_testing.start_test(conn, test_id)
        created.append((test_id, spec["name"]))

    print("\n=== HOOK A/B TESTS ===")
    if created:
        print("\nCreated and started:")
        for tid, name in created:
            print(f"  [{tid}] {name}")
    if skipped:
        print("\nAlready existed (skipped):")
        for tid, name in skipped:
            print(f"  [{tid}] {name}")

    print("\nNext steps:")
    print("  1. Render videos with the new hook pipeline (produce_for_series.py)")
    print("  2. After upload, call ab_testing.assign_short_to_test(conn, test_id, short_id, 'a' or 'b')")
    print("  3. After 28 days call ab_testing.collect_results + conclude_test")

    conn.close()


def list_tests():
    conn = sqlite3.connect("data/shorts_pipeline.db")
    conn.row_factory = sqlite3.Row
    _ensure_table(conn)
    print("\n=== A/B TESTS ===\n")
    for r in conn.execute(
        "SELECT id, name, status, metric, winner, p_value FROM ab_tests ORDER BY id"
    ):
        d = dict(r)
        print(
            f"  [{d['id']:>2}] {d['name']:<45} "
            f"status={d['status']:<10} metric={d['metric']:<20} "
            f"winner={d.get('winner') or '-':<10} p={d.get('p_value') or '-':<8}"
        )
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="List existing A/B tests instead of creating")
    args = ap.parse_args()

    if args.list:
        list_tests()
    else:
        setup()
