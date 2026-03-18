"""
ex09 - Curacion de clips: ranking + agrupacion antes de editar.

Objetivo:
  - Revisar candidatos por query (vectorial si hay ChromaDB, sino texto)
  - Combinar score semantico + metadata del clip
  - Mostrar mejores matches ANTES de cortar/pegar
  - Generar agrupaciones para edicion y un cutlist simple para DaVinci/CSV

Uso:
  python src/main.py ex09 --query "villain monologue"
  python src/main.py ex09 --query "motivacion gym" --max-results 24 --group-size 4
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from exercises.ex07_search_scenes import search_chromadb, search_sqlite_simple


def _norm(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _duration_score(start_ms: int, end_ms: int, ideal_s: float = 5.0) -> float:
    dur_s = max(0.0, (end_ms - start_ms) / 1000.0)
    # Campana simple: mejor cerca de ideal_s.
    return math.exp(-((dur_s - ideal_s) ** 2) / 6.0)


def _text_relevance(text: str, query: str) -> float:
    t = set(re.findall(r"[a-zA-Z0-9]{3,}", text.lower()))
    q = set(re.findall(r"[a-zA-Z0-9]{3,}", query.lower()))
    if not q:
        return 0.0
    return len(t.intersection(q)) / len(q)


def _to_tc(ms: int) -> str:
    total = max(0, int(ms // 1000))
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:00"


def _fetch_used_count(conn, movie_id: int, text: str) -> int:
    cur = conn.execute(
        """SELECT used_count FROM quotes WHERE movie_id = ? AND text = ? LIMIT 1""",
        (movie_id, text),
    )
    row = cur.fetchone()
    if not row:
        return 0
    return int(row["used_count"] or 0)


def _score_candidates(candidates: list[dict], query: str, conn) -> list[dict]:
    if not candidates:
        return []

    confs = [float(c.get("confidence", 0) or 0) for c in candidates]
    mins, maxs = min(confs), max(confs)

    out = []
    for c in candidates:
        start_ms = int(c.get("start_ms", 0) or 0)
        end_ms = int(c.get("end_ms", 0) or 0)
        conf = float(c.get("confidence", 0) or 0)
        sem = float(c.get("semantic_score", 0) or 0)
        txt_rel = _text_relevance(c.get("text", ""), query)
        dscore = _duration_score(start_ms, end_ms)
        used = _fetch_used_count(conn, int(c.get("movie_id", 0) or 0), c.get("text", ""))
        novelty = 1.0 / (1.0 + used)

        conf_norm = _norm(conf, mins, maxs)
        # Use viral_score from LLM classification if available (ex10)
        viral = float(c.get("viral_score", 0) or 0) / 10.0  # Normalize 1-10 to 0-1

        # Weighted score: prioriza semantica + viral, luego calidad y novedad.
        if viral > 0:
            # With classification data: viral_score is a strong signal
            final_score = (
                0.25 * sem
                + 0.25 * viral
                + 0.20 * conf_norm
                + 0.15 * dscore
                + 0.05 * txt_rel
                + 0.10 * novelty
            )
        else:
            # Without classification: original weights
            final_score = (
                0.35 * sem
                + 0.25 * conf_norm
                + 0.20 * dscore
                + 0.10 * txt_rel
                + 0.10 * novelty
            )

        item = dict(c)
        item["duration_s"] = round(max(0.0, (end_ms - start_ms) / 1000.0), 2)
        item["used_count"] = used
        item["text_relevance"] = round(txt_rel, 3)
        item["duration_score"] = round(dscore, 3)
        item["novelty_score"] = round(novelty, 3)
        item["final_score"] = round(final_score, 4)
        out.append(item)

    out.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return out


def _group_candidates(candidates: list[dict], group_size: int = 3, max_groups: int = 3) -> list[dict]:
    groups: list[dict] = []
    used_idx = set()

    for _ in range(max_groups):
        group = []
        seen_movies = set()
        for idx, c in enumerate(candidates):
            if idx in used_idx:
                continue
            movie = c.get("movie_title", "")
            if movie in seen_movies:
                continue
            seen_movies.add(movie)
            group.append(c)
            used_idx.add(idx)
            if len(group) >= group_size:
                break

        if not group:
            break

        total_s = round(sum(float(g.get("duration_s", 0)) for g in group), 2)
        group_score = round(sum(float(g.get("final_score", 0)) for g in group) / len(group), 4)
        groups.append(
            {
                "group_id": len(groups) + 1,
                "avg_score": group_score,
                "total_duration_s": total_s,
                "clips": group,
            }
        )

    return groups


def _write_davinci_cutlist(path: Path, groups: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Group",
            "ClipIndex",
            "MovieTitle",
            "InTC",
            "OutTC",
            "DurationS",
            "Quote",
            "Score",
        ])
        for g in groups:
            gid = g["group_id"]
            for idx, c in enumerate(g["clips"], start=1):
                writer.writerow(
                    [
                        gid,
                        idx,
                        c.get("movie_title", ""),
                        _to_tc(int(c.get("start_ms", 0) or 0)),
                        _to_tc(int(c.get("end_ms", 0) or 0)),
                        c.get("duration_s", 0),
                        c.get("text", "")[:220],
                        c.get("final_score", 0),
                    ]
                )


def run(
    settings: Settings,
    query: str = "epic movie moment",
    max_results: int = 20,
    group_size: int = 3,
) -> Path:
    log = build_logger("ex09", settings.output_dir / "logs" / "ex09.log")
    conn = get_db(settings.data_dir)

    # 1) Recuperar candidatos de busqueda semantica o textual.
    raw = search_chromadb(query, settings.data_dir, n_results=max_results)
    engine = "chromadb"
    if not raw:
        raw = search_sqlite_simple(query, conn, n_results=max_results)
        engine = "sqlite"

    if not raw:
        out_dir = settings.output_dir / "curation"
        out_dir.mkdir(parents=True, exist_ok=True)
        no_data = out_dir / "ex09_no_candidates.txt"
        no_data.write_text(
            "No hay candidatos. Ejecuta ex04 -> ex05 -> ex06 -> ex07 primero.",
            encoding="utf-8",
        )
        conn.close()
        return no_data

    scored = _score_candidates(raw, query, conn)
    groups = _group_candidates(scored, group_size=group_size, max_groups=3)

    out_dir = settings.output_dir / "curation"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:50] or "theme"

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"ex09_curation_{safe}_{ts}.json"
    txt_path = out_dir / f"ex09_curation_{safe}_{ts}.txt"
    csv_path = out_dir / f"ex09_davinci_cutlist_{safe}_{ts}.csv"

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query": query,
        "engine": engine,
        "top_candidates": scored[: max_results],
        "groups": groups,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_davinci_cutlist(csv_path, groups)

    lines = [
        "ex09 - Curation Report",
        "=" * 50,
        f"Query: {query}",
        f"Engine: {engine}",
        f"Candidates: {len(scored)}",
        "",
        "Top 10 matches:",
    ]
    for i, c in enumerate(scored[:10], start=1):
        lines.append(
            f"{i:02d}. [{c.get('final_score', 0):.4f}] {c.get('movie_title', 'Unknown')} "
            f"{_to_tc(int(c.get('start_ms', 0)))}-{_to_tc(int(c.get('end_ms', 0)))} "
            f"({c.get('duration_s', 0)}s)"
        )
        lines.append(f"    {str(c.get('text', ''))[:150]}")

    lines.append("")
    lines.append("Suggested groups:")
    for g in groups:
        lines.append(
            f"- Group {g['group_id']}: score={g['avg_score']:.4f}, total={g['total_duration_s']}s, clips={len(g['clips'])}"
        )

    lines.append("")
    lines.append(f"JSON: {json_path}")
    lines.append(f"Cutlist CSV: {csv_path}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    log.info("Curation report created: %s", txt_path)
    conn.close()
    return txt_path
