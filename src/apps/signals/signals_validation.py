"""
Signals Validation — capa de Data Verification (Sculley) sin dependencias pesadas.

Hace lo mismo que pandera/great_expectations a escala pequeña: chequea
invariantes sobre `market_signals` y `persona_briefs` y devuelve un reporte
estructurado.

Filosofía:
  - Invariantes "duros" (sí/no) → falla el job si los rompemos.
  - Métricas "blandas" (tendencias) → warning sin fallar.
  - Cada chequeo tiene severity y motivo, no solo booleano.

API:
    from apps.signals.signals_validation import run_all_checks, ValidationReport

    report = run_all_checks(conn)
    if not report.passes_hard():
        sys.exit(1)
    print(report.summary())

Notas MLOps:
  - Cuando crezca, migrar a Pandera (DataFrame schemas) o GE.
  - Threshold de alertas calibrable vía env vars (ver tabla en MLOPS_FLOW.md).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

log = logging.getLogger(__name__)


# ── Modelo de resultado ─────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    severity: str            # 'hard' | 'soft'
    passed: bool
    actual: float | int | str
    expected: str            # texto descriptivo del threshold
    notes: str = ""


@dataclass
class ValidationReport:
    checks: list[CheckResult] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add(self, result: CheckResult):
        self.checks.append(result)

    def passes_hard(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "hard")

    def passes_all(self) -> bool:
        return all(c.passed for c in self.checks)

    def hard_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == "hard" and not c.passed]

    def soft_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.severity == "soft" and not c.passed]

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "passes_hard": self.passes_hard(),
            "passes_all": self.passes_all(),
            "checks": [
                {
                    "name": c.name, "severity": c.severity,
                    "passed": c.passed, "actual": c.actual,
                    "expected": c.expected, "notes": c.notes,
                } for c in self.checks
            ],
        }

    def summary(self) -> str:
        hard = self.hard_failures()
        soft = self.soft_failures()
        lines = [f"Validation @ {self.started_at}"]
        lines.append(f"  Hard:  {'PASS' if not hard else f'FAIL ({len(hard)})'}")
        lines.append(f"  Soft:  {'PASS' if not soft else f'WARN ({len(soft)})'}")
        for c in self.checks:
            mark = "✓" if c.passed else ("✗" if c.severity == "hard" else "!")
            lines.append(f"   {mark} [{c.severity:4s}] {c.name}: actual={c.actual} (expected {c.expected})")
            if c.notes:
                lines.append(f"        ↳ {c.notes}")
        return "\n".join(lines)


# ── Thresholds (env-overridable) ───────────────────────────────────


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except ValueError:
        return default


THRESHOLDS = {
    "min_signals_24h":           _env_int("MIN_SIGNALS_24H", 80),
    "min_signals_7d":            _env_int("MIN_SIGNALS_7D", 1000),
    "max_dup_pct":               _env_int("MAX_DUP_PCT", 25),       # soft
    "min_briefs_per_persona":    _env_int("MIN_BRIEFS_PER_PERSONA", 3),
    "max_scraper_fail_rate_pct": _env_int("MAX_SCRAPER_FAIL_RATE_PCT", 30),
    "max_stale_brief_days":      _env_int("MAX_STALE_BRIEF_DAYS", 14),
}


# ── Invariantes individuales ───────────────────────────────────────


def check_signals_volume_24h(conn: sqlite3.Connection) -> CheckResult:
    """HARD: deben llegar >= N señales en las últimas 24h.

    Si esto falla por más de 1 corrida consecutiva, hay un scraper caído
    o cambió un selector / endpoint upstream.
    """
    n = conn.execute(
        "SELECT COUNT(*) FROM market_signals WHERE fetched_at >= datetime('now', '-1 day')"
    ).fetchone()[0]
    expected = THRESHOLDS["min_signals_24h"]
    return CheckResult(
        name="signals_volume_24h",
        severity="hard",
        passed=n >= expected,
        actual=n,
        expected=f">= {expected}",
        notes="0 = todos los scrapers caídos" if n == 0 else "",
    )


def check_signals_volume_7d(conn: sqlite3.Connection) -> CheckResult:
    """SOFT: volumen agregado de 7d. Decae lento, alerta temprano."""
    n = conn.execute(
        "SELECT COUNT(*) FROM market_signals WHERE fetched_at >= datetime('now', '-7 day')"
    ).fetchone()[0]
    expected = THRESHOLDS["min_signals_7d"]
    return CheckResult(
        name="signals_volume_7d",
        severity="soft",
        passed=n >= expected,
        actual=n,
        expected=f">= {expected}",
    )


def check_signals_have_required_fields(conn: sqlite3.Connection) -> CheckResult:
    """HARD: las filas recientes deben tener domain, title y normalized_title.

    Las filas legacy pueden tener domain NULL; solo chequeamos las últimas 24h.
    """
    n_bad = conn.execute(
        """SELECT COUNT(*) FROM market_signals
           WHERE fetched_at >= datetime('now', '-1 day')
             AND (title IS NULL OR title = ''
                  OR normalized_title IS NULL OR normalized_title = ''
                  OR domain IS NULL OR domain = '')"""
    ).fetchone()[0]
    return CheckResult(
        name="signals_required_fields",
        severity="hard",
        passed=n_bad == 0,
        actual=n_bad,
        expected="0 filas con campos requeridos vacíos",
    )


def check_domain_enum(conn: sqlite3.Connection) -> CheckResult:
    """HARD: domain debe estar en el set conocido."""
    valid = {"gaming", "anime_manga", "movies_tv", "music", "latam"}
    rows = conn.execute(
        """SELECT DISTINCT domain FROM market_signals
           WHERE fetched_at >= datetime('now', '-1 day')"""
    ).fetchall()
    invalid = [r[0] for r in rows if r[0] not in valid]
    return CheckResult(
        name="domain_enum",
        severity="hard",
        passed=len(invalid) == 0,
        actual=str(invalid) if invalid else "ok",
        expected=f"subset of {sorted(valid)}",
    )


def check_dedup_efficiency(conn: sqlite3.Connection) -> CheckResult:
    """SOFT: ratio (unique normalized_title) / (total) en última semana.

    Si baja mucho indica una fuente que está duplicando o el normalizador
    está fallando.
    """
    row = conn.execute(
        """SELECT COUNT(*) as total,
                  COUNT(DISTINCT normalized_title) as uniq
           FROM market_signals
           WHERE fetched_at >= datetime('now', '-7 day')"""
    ).fetchone()
    total = row[0] or 0
    uniq = row[1] or 0
    if total == 0:
        return CheckResult(
            name="dedup_efficiency", severity="soft", passed=True,
            actual="n/a", expected="—", notes="0 signals in window",
        )
    dup_pct = round(100 * (1 - uniq / total), 1)
    return CheckResult(
        name="dedup_efficiency",
        severity="soft",
        passed=dup_pct <= THRESHOLDS["max_dup_pct"],
        actual=f"{dup_pct}% duplicates",
        expected=f"<= {THRESHOLDS['max_dup_pct']}%",
    )


def check_briefs_per_persona(conn: sqlite3.Connection) -> CheckResult:
    """HARD: cada persona debe tener >= N briefs unconsumed.

    Si una persona se queda en cero, el rotator caerá al CATALOG estático
    y perdemos la señal de mercado.
    """
    rows = conn.execute(
        """SELECT persona, COUNT(*) FROM persona_briefs
           WHERE consumed_at IS NULL
           GROUP BY persona"""
    ).fetchall()
    expected = THRESHOLDS["min_briefs_per_persona"]
    expected_personas = {"deep_mind", "pop_oracle", "latam"}
    counts = {r[0]: r[1] for r in rows}
    missing = [p for p in expected_personas if counts.get(p, 0) < expected]
    return CheckResult(
        name="briefs_per_persona_unconsumed",
        severity="hard",
        passed=len(missing) == 0,
        actual=counts,
        expected=f"each persona >= {expected}",
        notes=f"under threshold: {missing}" if missing else "",
    )


def check_scraper_health(conn: sqlite3.Connection) -> CheckResult:
    """SOFT: ningún scraper con fail_rate > umbral en últimas 24h."""
    threshold = THRESHOLDS["max_scraper_fail_rate_pct"] / 100.0
    rows = conn.execute(
        """SELECT scraper_name,
                  SUM(success_count) as ok,
                  SUM(failure_count) as ko
           FROM scraper_health
           WHERE checked_at >= datetime('now', '-1 day')
           GROUP BY scraper_name"""
    ).fetchall()
    bad = []
    for r in rows:
        ok = r[1] or 0
        ko = r[2] or 0
        total = ok + ko
        if total == 0:
            continue
        fail_rate = ko / total
        if fail_rate > threshold:
            bad.append(f"{r[0]} ({round(fail_rate*100)}%)")
    return CheckResult(
        name="scraper_fail_rate",
        severity="soft",
        passed=len(bad) == 0,
        actual=bad or "all ok",
        expected=f"fail_rate <= {THRESHOLDS['max_scraper_fail_rate_pct']}%",
    )


def check_stale_briefs(conn: sqlite3.Connection) -> CheckResult:
    """SOFT: briefs unconsumed más viejos que N días sugieren que el rotator
    está ignorándolos (mal resolver / score bajo / cooldown perpetuo).
    """
    max_days = THRESHOLDS["max_stale_brief_days"]
    cutoff = (datetime.now() - timedelta(days=max_days)).isoformat()
    n_stale = conn.execute(
        """SELECT COUNT(*) FROM persona_briefs
           WHERE consumed_at IS NULL AND created_at < ?""",
        (cutoff,),
    ).fetchone()[0]
    return CheckResult(
        name="stale_unconsumed_briefs",
        severity="soft",
        passed=n_stale == 0,
        actual=n_stale,
        expected=f"0 (briefs > {max_days}d sin consumir)",
        notes="revisar brief_resolver o reducir min_days_cooldown" if n_stale else "",
    )


# ── Runner ──────────────────────────────────────────────────────────


ALL_CHECKS: list[Callable[[sqlite3.Connection], CheckResult]] = [
    check_signals_volume_24h,
    check_signals_volume_7d,
    check_signals_have_required_fields,
    check_domain_enum,
    check_dedup_efficiency,
    check_briefs_per_persona,
    check_scraper_health,
    check_stale_briefs,
]


def run_all_checks(conn: sqlite3.Connection) -> ValidationReport:
    report = ValidationReport()
    for check in ALL_CHECKS:
        try:
            report.add(check(conn))
        except sqlite3.OperationalError as e:
            # Tabla no existe (DB fresca) — marcar como soft fail con nota.
            report.add(CheckResult(
                name=check.__name__,
                severity="soft",
                passed=False,
                actual="table missing",
                expected="schema present",
                notes=str(e),
            ))
        except Exception as e:
            log.exception("check %s crashed", check.__name__)
            report.add(CheckResult(
                name=check.__name__,
                severity="soft",
                passed=False,
                actual="exception",
                expected="no exception",
                notes=str(e)[:200],
            ))
    return report


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.db import get_db
    logging.basicConfig(level=logging.INFO)
    conn = get_db(Path("data"))
    rep = run_all_checks(conn)
    print(rep.summary())
    if not rep.passes_hard():
        print("\nHARD failures detected.", file=sys.stderr)
        sys.exit(1)
