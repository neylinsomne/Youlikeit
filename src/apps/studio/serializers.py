"""Filas de la DB → formas JSON del contrato (Work, Asset, MediaCandidate, Moment, Vocab)."""
from __future__ import annotations

import json
import sqlite3

from apps.media.models import MediaCandidate
from apps.moments import vocab
from apps.studio.errors import NotFound
from apps.supercut.lessons import preview_url


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.row_factory = prev


def _loads(text: str | None) -> dict:
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


# ── works / assets ──────────────────────────────────────────────────


def works(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn, """SELECT w.id, w.kind, w.title, w.year, COUNT(a.id) AS assets
                          FROM works w LEFT JOIN media_assets a ON a.work_id = w.id
                          GROUP BY w.id ORDER BY w.year IS NULL, w.year, w.title""")


_ASSET_SQL = """
SELECT a.*, w.title AS work_title, w.year AS work_year,
       (SELECT COUNT(*) FROM moments m WHERE m.asset_id = a.id) AS n_moments,
       (SELECT COUNT(*) FROM moments m WHERE m.asset_id = a.id AND m.status = 'labeled') AS n_labeled,
       (SELECT GROUP_CONCAT(DISTINCT r.step) FROM media_index_runs r
         WHERE r.asset_id = a.id AND r.status = 'ok') AS ok_steps
FROM media_assets a JOIN works w ON w.id = a.work_id
"""


def _asset(r: dict) -> dict:
    ok = set((r.get("ok_steps") or "").split(","))
    return {
        "id": r["id"], "work_id": r["work_id"], "work_title": r["work_title"], "work_year": r["work_year"],
        "provider": r["provider"], "external_id": r["external_id"], "rights": r["rights"],
        "duration_ms": r["duration_ms"], "height": r["height"], "fps": r["fps"],
        "accept_ranges": None if r["accept_ranges"] is None else bool(r["accept_ranges"]),
        "steps": {"probe": bool(r["fps"]) or "probe" in ok, "proxy": bool(r["proxy_path"]) or "proxy" in ok,
                  "analyze": "analyze" in ok or bool(r["shots_at"]), "asr": bool(r["transcribed_at"]),
                  "shots": bool(r["shots_at"])},
        "moments": r["n_moments"], "moments_labeled": r["n_labeled"],
    }


def assets(conn: sqlite3.Connection, work_id: int | None = None) -> list[dict]:
    where, params = ("WHERE a.work_id = ?", (work_id,)) if work_id is not None else ("", ())
    return [_asset(r) for r in _rows(conn, f"{_ASSET_SQL} {where} ORDER BY a.id", params)]


def asset(conn: sqlite3.Connection, asset_id: int) -> dict:
    rows = _rows(conn, f"{_ASSET_SQL} WHERE a.id = ?", (asset_id,))
    if not rows:
        raise NotFound(f"asset {asset_id} no existe")
    return _asset(rows[0])


def candidate(c: MediaCandidate) -> dict:
    return {"provider": c.provider, "external_id": c.external_id, "title": c.title, "year": c.year,
            "rights": c.rights, "license_url": c.license_url or None, "height": c.height or None,
            "duration_ms": c.duration_ms or None, "partial": bool(c.extra.get("partial")),
            "master_file": c.extra.get("master_file"), "proxy_file": c.extra.get("proxy_file"),
            "usable": c.usable, "via": c.extra.get("via")}


# ── moments ─────────────────────────────────────────────────────────

_MOMENT_SQL = """
SELECT m.id, m.asset_id, a.work_id, w.title AS work_title, w.year AS work_year, m.start_ms, m.end_ms,
       m.text, m.summary_es, m.importance, m.signal_score, m.position, m.status, m.features_json, m.anchors_json
FROM moments m JOIN media_assets a ON a.id = m.asset_id JOIN works w ON w.id = a.work_id
"""


def _moment(r: dict, labels: list[dict]) -> dict:
    contrib = _loads(r.pop("features_json")).get("contrib") or {}
    anchors = _loads(r.pop("anchors_json"))
    why = {k: round(float(v), 4) for k, v in sorted(contrib.items(), key=lambda kv: -float(kv[1] or 0))
           if isinstance(v, (int, float)) and v > 0}
    return {**r, "why": why, "anchors": {k: anchors[k] for k in ("quote", "plot") if anchors.get(k)},
            "labels": labels, "preview_url": preview_url(r["id"])}


def moments_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[dict]:
    """Moments en el MISMO orden que ids (los inexistentes se omiten)."""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = {r["id"]: r for r in _rows(conn, f"{_MOMENT_SQL} WHERE m.id IN ({marks})", tuple(ids))}
    labels: dict[int, list[dict]] = {}
    for lab in _rows(conn, f"SELECT moment_id, dimension, value, confidence, source FROM moment_labels "
                           f"WHERE moment_id IN ({marks}) ORDER BY confidence DESC, dimension, value", tuple(ids)):
        mid = lab.pop("moment_id")
        labels.setdefault(mid, []).append(lab)
    return [_moment(dict(rows[i]), labels.get(i, [])) for i in ids if i in rows]


def moment(conn: sqlite3.Connection, moment_id: int) -> dict:
    found = moments_by_ids(conn, [moment_id])
    if not found:
        raise NotFound(f"momento {moment_id} no existe")
    return found[0]


def query_moments(conn: sqlite3.Connection, *, asset_id: int | None = None, work_id: int | None = None,
                  dimension: str | None = None, value: str | None = None, min_conf: float = 0.0,
                  status: str | None = None, q: str | None = None, page: int = 1,
                  per_page: int = 50) -> dict:
    where, params = ["1 = 1"], []
    if asset_id is not None:
        where.append("m.asset_id = ?")
        params.append(asset_id)
    if work_id is not None:
        where.append("a.work_id = ?")
        params.append(work_id)
    if status:
        where.append("m.status = ?")
        params.append(status)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(m.text LIKE ? ESCAPE '\\' OR m.summary_es LIKE ? ESCAPE '\\')")
        params += [like, like]
    if dimension or value or min_conf > 0:
        sub = ["l.moment_id = m.id", "l.confidence >= ?"]
        params.append(float(min_conf))
        if dimension:
            sub.append("l.dimension = ?")
            params.append(dimension)
        if value:
            sub.append("l.value = ?")
            params.append(value)
        where.append(f"EXISTS (SELECT 1 FROM moment_labels l WHERE {' AND '.join(sub)})")
    base = f"FROM moments m JOIN media_assets a ON a.id = m.asset_id WHERE {' AND '.join(where)}"
    total = conn.execute(f"SELECT COUNT(*) {base}", tuple(params)).fetchone()[0]
    ids = [r[0] for r in conn.execute(f"SELECT m.id {base} ORDER BY m.importance DESC, m.id LIMIT ? OFFSET ?",
                                      (*params, per_page, (page - 1) * per_page))]
    return {"items": moments_by_ids(conn, ids), "page": page, "per_page": per_page, "total": int(total)}


# ── vocab ───────────────────────────────────────────────────────────


def vocab_json() -> dict:
    return {dim: [{"id": e["id"], "es": e.get("es") or e["id"], "en": e.get("en") or e["id"],
                   "desc_es": e.get("desc_es"), "desc_en": e.get("desc_en")} for e in entries]
            for dim, entries in vocab.load_vocab().items()}
