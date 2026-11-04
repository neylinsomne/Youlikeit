"""CRUD de lecciones con las formas JSON del contrato (docs/architecture/STUDIO_API.md).

Todas las funciones de lectura devuelven dicts listos para serializar:
Lesson, Issue y Publication. Las de escritura validan y levantan:

    LessonNotFound  → 404
    InvalidState    → 409 (transición no permitida por la máquina de estados)
    ValueError      → 422 (datos inválidos)
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from apps.media.models import USABLE_RIGHTS
from apps.supercut.schema import ISSUE_TYPES, PLATFORMS, PUBLICATION_STATUSES, STATUSES, now_iso
from integrations.ai.llm_json import validate

EDITABLE_TO_DRAFT = frozenset({"rendered", "approved", "rejected"})
LOCKED = frozenset({"rendering", "published"})          # no se editan ni se re-renderizan
RENDERABLE = frozenset({"draft", "rendered", "approved", "rejected"})
PUBLISHABLE = frozenset({"approved", "published"})      # published: segunda plataforma
MAX_ITEM_MS = 60_000

SCRIPT_SCHEMA: dict = {
    "type": "object",
    "required": ["hook", "outro", "segments"],
    "properties": {
        "hook": {"type": "string"},
        "outro": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["idx", "narration", "caption"],
                "properties": {"idx": {"type": "integer"}, "narration": {"type": "string"},
                               "caption": {"type": "string"}},
            },
        },
    },
}


class LessonNotFound(LookupError):
    """La lección (o el issue / la publicación) no existe."""


class InvalidState(RuntimeError):
    """La transición pedida no es válida para el estado actual de la lección."""


# ── rutas ───────────────────────────────────────────────────────────


def output_dir() -> Path:
    """outputs/lessons (respeta OUTPUT_DIR, como core.config.load_settings)."""
    return Path(os.getenv("OUTPUT_DIR", "outputs")) / "lessons"


def video_path(lesson_id: int) -> Path:
    return output_dir() / f"{int(lesson_id)}.mp4"


def preview_url(moment_id: int | None) -> str | None:
    return f"/api/moments/{moment_id}/preview" if moment_id is not None else None


# ── lectura ─────────────────────────────────────────────────────────


def _row(conn: sqlite3.Connection, lesson_id: int) -> sqlite3.Row:
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    finally:
        conn.row_factory = prev
    if row is None:
        raise LessonNotFound(f"lección {lesson_id} no existe")
    return row


def get_items(conn: sqlite3.Connection, lesson_id: int) -> list[dict]:
    """Ítems de la lección con obra, año y texto del momento (join a moments/works)."""
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT li.idx, li.moment_id, li.in_ms, li.out_ms, li.caption,
                      m.text, m.asset_id, m.start_ms, m.end_ms, m.summary_es,
                      w.id AS work_id, w.title AS work_title, w.year AS work_year,
                      a.rights, a.master_uri
               FROM lesson_items li
               LEFT JOIN moments m ON m.id = li.moment_id
               LEFT JOIN media_assets a ON a.id = m.asset_id
               LEFT JOIN works w ON w.id = a.work_id
               WHERE li.lesson_id = ? ORDER BY li.idx""", (lesson_id,)).fetchall()
    finally:
        conn.row_factory = prev
    return [dict(r) for r in rows]


def _public_item(it: dict) -> dict:
    return {"idx": it["idx"], "moment_id": it["moment_id"], "work_title": it["work_title"],
            "work_year": it["work_year"], "in_ms": it["in_ms"], "out_ms": it["out_ms"],
            "caption": it["caption"], "text": it["text"], "preview_url": preview_url(it["moment_id"])}


def get_lesson(conn: sqlite3.Connection, lesson_id: int) -> dict:
    """Lesson del contrato (items, issues, publications incluidos)."""
    r = _row(conn, lesson_id)
    path = Path(r["output_path"]) if r["output_path"] else None
    issues = conn.execute("SELECT COUNT(*) FROM lesson_issues WHERE lesson_id = ?", (lesson_id,)).fetchone()[0]
    return {
        "id": r["id"], "title": r["title"], "spec": r["spec"], "format": r["format"], "lang": r["lang"],
        "status": r["status"], "duration_s": r["duration_s"],
        "video_url": f"/api/lessons/{r['id']}/video" if path and path.exists() else None,
        "script": json.loads(r["script_json"]) if r["script_json"] else None,
        "script_source": r["script_source"],
        "items": [_public_item(it) for it in get_items(conn, lesson_id)],
        "issues": int(issues), "publications": list_publications(conn, lesson_id),
        "reject_reason": r["reject_reason"], "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def list_lessons(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status inválido: {status!r} (usa {', '.join(STATUSES)})")
    where, params = ("WHERE status = ?", (status,)) if status else ("", ())
    ids = [r[0] for r in conn.execute(f"SELECT id FROM lessons {where} ORDER BY updated_at DESC, id DESC",
                                      params)]
    return [get_lesson(conn, i) for i in ids]


def get_status(conn: sqlite3.Connection, lesson_id: int) -> str:
    return _row(conn, lesson_id)["status"]


# ── validación ──────────────────────────────────────────────────────


def validate_items(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    """Normaliza [{moment_id, in_ms, out_ms, caption}] y valida contra la DB."""
    if not isinstance(items, list):
        raise ValueError("items debe ser una lista")
    out = []
    for i, it in enumerate(items):
        try:
            mid, a, b = int(it["moment_id"]), int(it["in_ms"]), int(it["out_ms"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"items[{i}]: faltan moment_id/in_ms/out_ms enteros") from e
        if a < 0 or b <= a:
            raise ValueError(f"items[{i}]: rango inválido {a}..{b} ms")
        if b - a > MAX_ITEM_MS:
            raise ValueError(f"items[{i}]: un tramo no puede pasar de {MAX_ITEM_MS // 1000} s")
        row = conn.execute("SELECT a.rights FROM moments m JOIN media_assets a ON a.id = m.asset_id "
                           "WHERE m.id = ?", (mid,)).fetchone()
        if row is None:
            raise ValueError(f"items[{i}]: el momento {mid} no existe")
        if row[0] not in USABLE_RIGHTS:
            raise ValueError(f"items[{i}]: el momento {mid} viene de un asset con derechos '{row[0]}' (no usable)")
        caption = it.get("caption")
        if caption is not None and not isinstance(caption, str):
            raise ValueError(f"items[{i}]: caption debe ser texto")
        out.append({"moment_id": mid, "in_ms": a, "out_ms": b,
                    "caption": caption.strip() if isinstance(caption, str) else None})
    return out


def validate_script(script: dict) -> dict:
    errs = validate(script, SCRIPT_SCHEMA)
    if errs:
        raise ValueError(f"script inválido: {'; '.join(errs[:3])}")
    return {"hook": script["hook"].strip(), "outro": script["outro"].strip(),
            "segments": [{"idx": int(s["idx"]), "narration": s["narration"].strip(),
                          "caption": s["caption"].strip()} for s in script["segments"]]}


# ── escritura ───────────────────────────────────────────────────────


def _set_items(conn: sqlite3.Connection, lesson_id: int, items: list[dict]) -> None:
    conn.execute("DELETE FROM lesson_items WHERE lesson_id = ?", (lesson_id,))
    conn.executemany(
        "INSERT INTO lesson_items (lesson_id, idx, moment_id, in_ms, out_ms, caption) VALUES (?, ?, ?, ?, ?, ?)",
        [(lesson_id, i, it["moment_id"], it["in_ms"], it["out_ms"], it.get("caption")) for i, it in enumerate(items)])


def create_lesson(conn: sqlite3.Connection, *, title: str, spec: str, items: list[dict], lang: str = "es",
                  fmt: str = "essay", script: dict | None = None, script_source: str | None = None) -> int:
    items = validate_items(conn, items)
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO lessons (title, spec, format, lang, status, script_json, script_source, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
        (title.strip(), spec, fmt, lang, json.dumps(script, ensure_ascii=False) if script else None,
         script_source if script else None, ts, ts))
    lesson_id = int(cur.lastrowid)
    _set_items(conn, lesson_id, items)
    conn.commit()
    return lesson_id


def update_lesson(conn: sqlite3.Connection, lesson_id: int, *, title: str | None = None,
                  items: list[dict] | None = None, script: dict | None = None,
                  script_source: str = "manual") -> dict:
    """Edita título / ítems / guion. Una lección rendered|approved|rejected vuelve a draft."""
    status = get_status(conn, lesson_id)
    if status in LOCKED:
        raise InvalidState(f"La lección está '{status}': no se puede editar")
    fields: dict = {}
    if title is not None:
        if not title.strip():
            raise ValueError("title vacío")
        fields["title"] = title.strip()
    if script is not None:
        fields["script_json"] = json.dumps(validate_script(script), ensure_ascii=False)
        fields["script_source"] = script_source
    clean_items = validate_items(conn, items) if items is not None else None
    if not fields and clean_items is None:
        return get_lesson(conn, lesson_id)
    if status in EDITABLE_TO_DRAFT:
        fields["status"] = "draft"
    fields["updated_at"] = now_iso()
    conn.execute(f"UPDATE lessons SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                 (*fields.values(), lesson_id))
    if clean_items is not None:
        _set_items(conn, lesson_id, clean_items)
    conn.commit()
    return get_lesson(conn, lesson_id)


def set_item_captions(conn: sqlite3.Connection, lesson_id: int, captions: dict[int, str],
                      *, only_empty: bool = False) -> None:
    for idx, caption in captions.items():
        sql = "UPDATE lesson_items SET caption = ? WHERE lesson_id = ? AND idx = ?"
        if only_empty:
            sql += " AND (caption IS NULL OR caption = '')"
        conn.execute(sql, (caption, lesson_id, idx))
    conn.commit()


def _transition(conn: sqlite3.Connection, lesson_id: int, allowed: frozenset[str] | set[str], new: str,
                msg: str, **fields) -> dict:
    status = get_status(conn, lesson_id)
    if status not in allowed:
        raise InvalidState(msg.format(status=status))
    fields = {"status": new, "updated_at": now_iso(), **fields}
    conn.execute(f"UPDATE lessons SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                 (*fields.values(), lesson_id))
    conn.commit()
    return get_lesson(conn, lesson_id)


def assert_renderable(conn: sqlite3.Connection, lesson_id: int) -> None:
    status = get_status(conn, lesson_id)
    if status not in RENDERABLE:
        raise InvalidState(f"La lección está '{status}': no se puede renderizar")
    if not conn.execute("SELECT 1 FROM lesson_items WHERE lesson_id = ? LIMIT 1", (lesson_id,)).fetchone():
        raise InvalidState("La lección no tiene tramos")


def begin_render(conn: sqlite3.Connection, lesson_id: int) -> dict:
    assert_renderable(conn, lesson_id)
    return _transition(conn, lesson_id, RENDERABLE, "rendering", "No se puede renderizar desde '{status}'")


def finish_render(conn: sqlite3.Connection, lesson_id: int, output_path: Path, duration_s: float) -> dict:
    return _transition(conn, lesson_id, {"rendering"}, "rendered", "Render terminado pero la lección está '{status}'",
                       output_path=str(output_path), duration_s=round(float(duration_s), 2))


def fail_render(conn: sqlite3.Connection, lesson_id: int) -> None:
    if get_status(conn, lesson_id) == "rendering":
        _transition(conn, lesson_id, {"rendering"}, "draft", "")


def approve(conn: sqlite3.Connection, lesson_id: int) -> dict:
    return _transition(conn, lesson_id, {"rendered"}, "approved",
                       "Solo se aprueba una lección 'rendered' (está '{status}')", reject_reason=None)


def reject(conn: sqlite3.Connection, lesson_id: int, reason: str) -> dict:
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("reason vacío")
    return _transition(conn, lesson_id, {"rendered", "approved"}, "rejected",
                       "Solo se rechaza una lección 'rendered' o 'approved' (está '{status}')",
                       reject_reason=reason[:2000])


def assert_publishable(conn: sqlite3.Connection, lesson_id: int) -> None:
    status = get_status(conn, lesson_id)
    if status not in PUBLISHABLE:
        raise InvalidState(f"Para publicar la lección debe estar aprobada (está '{status}')")


def mark_published(conn: sqlite3.Connection, lesson_id: int) -> None:
    if get_status(conn, lesson_id) == "approved":
        _transition(conn, lesson_id, {"approved"}, "published", "")


# ── issues ──────────────────────────────────────────────────────────


def _issue(r) -> dict:
    return {"id": r[0], "issue_type": r[1], "start_s": r[2], "end_s": r[3], "note": r[4], "created_at": r[5]}


def list_issues(conn: sqlite3.Connection, lesson_id: int) -> list[dict]:
    _row(conn, lesson_id)
    return [_issue(r) for r in conn.execute(
        "SELECT id, issue_type, start_s, end_s, note, created_at FROM lesson_issues WHERE lesson_id = ? "
        "ORDER BY start_s, id", (lesson_id,))]


def add_issue(conn: sqlite3.Connection, lesson_id: int, *, issue_type: str, start_s: float, end_s: float,
              note: str | None = None) -> dict:
    _row(conn, lesson_id)
    if issue_type not in ISSUE_TYPES:
        raise ValueError(f"issue_type inválido: {issue_type!r} (usa {', '.join(ISSUE_TYPES)})")
    start_s, end_s = float(start_s), float(end_s)
    if start_s < 0 or end_s < start_s:
        raise ValueError(f"rango inválido {start_s}..{end_s} s")
    cur = conn.execute(
        "INSERT INTO lesson_issues (lesson_id, issue_type, start_s, end_s, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (lesson_id, issue_type, round(start_s, 3), round(end_s, 3), (note or "").strip() or None, now_iso()))
    conn.commit()
    row = conn.execute("SELECT id, issue_type, start_s, end_s, note, created_at FROM lesson_issues WHERE id = ?",
                       (cur.lastrowid,)).fetchone()
    return _issue(row)


def delete_issue(conn: sqlite3.Connection, lesson_id: int, issue_id: int) -> None:
    cur = conn.execute("DELETE FROM lesson_issues WHERE id = ? AND lesson_id = ?", (issue_id, lesson_id))
    conn.commit()
    if cur.rowcount == 0:
        raise LessonNotFound(f"issue {issue_id} no existe en la lección {lesson_id}")


# ── publicaciones ───────────────────────────────────────────────────

_PUB_COLS = "id, lesson_id, platform, status, external_id, url, detail, created_at"


def _publication(r) -> dict:
    return dict(zip(("id", "lesson_id", "platform", "status", "external_id", "url", "detail", "created_at"),
                    tuple(r), strict=True))


def list_publications(conn: sqlite3.Connection, lesson_id: int) -> list[dict]:
    return [_publication(r) for r in conn.execute(
        f"SELECT {_PUB_COLS} FROM publications WHERE lesson_id = ? ORDER BY id", (lesson_id,))]


def get_publication(conn: sqlite3.Connection, pub_id: int) -> dict:
    row = conn.execute(f"SELECT {_PUB_COLS} FROM publications WHERE id = ?", (pub_id,)).fetchone()
    if row is None:
        raise LessonNotFound(f"publicación {pub_id} no existe")
    return _publication(row)


def create_publication(conn: sqlite3.Connection, lesson_id: int, platform: str) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"plataforma inválida: {platform!r}")
    ts = now_iso()
    cur = conn.execute("INSERT INTO publications (lesson_id, platform, status, created_at, updated_at) "
                       "VALUES (?, ?, 'pending', ?, ?)", (lesson_id, platform, ts, ts))
    conn.commit()
    return get_publication(conn, int(cur.lastrowid))


def update_publication(conn: sqlite3.Connection, pub_id: int, *, status: str, external_id: str | None = None,
                       url: str | None = None, detail: str | None = None) -> dict:
    if status not in PUBLICATION_STATUSES:
        raise ValueError(f"estado de publicación inválido: {status!r}")
    conn.execute(
        """UPDATE publications SET status = ?, external_id = COALESCE(?, external_id), url = COALESCE(?, url),
                                   detail = COALESCE(?, detail), updated_at = ? WHERE id = ?""",
        (status, external_id, url, (detail or None) and detail[:1000], now_iso(), pub_id))
    conn.commit()
    return get_publication(conn, pub_id)
