"""Cola de trabajos del estudio: tabla studio_jobs + UN hilo worker.

Un solo worker a propósito: los trabajos usan la red (Internet Archive, Groq,
TikTok, YouTube) o la GPU (ASR local), y de a uno no compiten entre sí. La cola
vive en la DB, así que sobrevive a reinicios; al arrancar, lo que quedó
`running` se marca `error` (interrumpido) y las lecciones `rendering` vuelven a
`draft`.

Progreso: cada handler llama progress(stage, pct, detail) → se guarda en
studio_jobs.progress_json y se emite por WebSocket:
    notify("studio.job", stage, {job_id, type, status, stage, pct, detail})
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable

from apps.studio.errors import NotFound
from apps.studio.schema import JOB_STATUSES, JOB_TYPES
from apps.supercut.schema import now_iso
from utils.websocket_hub import notify

log = logging.getLogger(__name__)

SOURCE = "studio.job"
Progress = Callable[[str, int, str], None]
Handler = Callable[[sqlite3.Connection, dict, Progress], dict]


# ── lectura ─────────────────────────────────────────────────────────

_COLS = "id, type, status, params_json, progress_json, result_json, error, created_at, started_at, finished_at"


def _job(r) -> dict:
    (jid, typ, status, params, progress, result, error, created, started, finished) = tuple(r)
    return {"id": jid, "type": typ, "status": status, "params": json.loads(params or "{}"),
            "progress": json.loads(progress) if progress else {"stage": status, "pct": 0, "detail": ""},
            "result": json.loads(result) if result else None, "error": error,
            "created_at": created, "started_at": started, "finished_at": finished}


def get_job(conn: sqlite3.Connection, job_id: int) -> dict:
    row = conn.execute(f"SELECT {_COLS} FROM studio_jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise NotFound(f"job {job_id} no existe")
    return _job(row)


def list_jobs(conn: sqlite3.Connection, *, status: str | None = None, limit: int = 50) -> list[dict]:
    if status is not None and status not in JOB_STATUSES:
        raise ValueError(f"status inválido: {status!r} (usa {', '.join(JOB_STATUSES)})")
    where, params = ("WHERE status = ?", (status,)) if status else ("", ())
    return [_job(r) for r in conn.execute(
        f"SELECT {_COLS} FROM studio_jobs {where} ORDER BY id DESC LIMIT ?", (*params, int(limit)))]


# ── validación de parámetros por tipo (antes de encolar) ────────────


def _asset_exists(conn: sqlite3.Connection, asset_id) -> int:
    try:
        aid = int(asset_id)
    except (TypeError, ValueError) as e:
        raise ValueError("asset_id debe ser un entero") from e
    if not conn.execute("SELECT 1 FROM media_assets WHERE id = ?", (aid,)).fetchone():
        raise NotFound(f"asset {aid} no existe")
    return aid


def _lesson_id(params: dict) -> int:
    try:
        return int(params["lesson_id"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("lesson_id entero requerido") from e


def validate_params(conn: sqlite3.Connection, job_type: str, params: dict | None) -> dict:
    """Normaliza los params y verifica existencia/estado. ValueError→422, NotFound→404, InvalidState→409."""
    from apps.media.indexer import STEPS
    from apps.publish import service, youtube
    from apps.supercut import lessons

    params = dict(params or {})
    if job_type not in JOB_TYPES:
        raise ValueError(f"type inválido: {job_type!r} (usa {', '.join(JOB_TYPES)})")
    if job_type == "index":
        ids = params.get("asset_ids")
        if not isinstance(ids, list) or not ids:
            raise ValueError("asset_ids: lista no vacía de enteros")
        steps = params.get("steps")
        if steps is not None:
            if not isinstance(steps, list) or not steps or set(steps) - set(STEPS):
                raise ValueError(f"steps debe ser un subconjunto de {list(STEPS)}")
        return {"asset_ids": list(dict.fromkeys(_asset_exists(conn, a) for a in ids)), "steps": steps,
                "force": bool(params.get("force", False))}
    if job_type == "detect":
        return {"asset_id": _asset_exists(conn, params.get("asset_id")),
                "fetch_anchors": bool(params.get("fetch_anchors", True))}
    if job_type == "label":
        top_k = params.get("top_k")
        top_k = 40 if top_k is None else int(top_k)
        if not 1 <= top_k <= 500:
            raise ValueError("top_k entre 1 y 500")
        provider = params.get("provider")
        if provider is not None and not isinstance(provider, str):
            raise ValueError("provider debe ser texto o null")
        return {"asset_id": _asset_exists(conn, params.get("asset_id")), "top_k": top_k, "provider": provider}
    lesson_id = _lesson_id(params)
    if job_type == "render":
        lessons.assert_renderable(conn, lesson_id)
        narrate = params.get("narrate")
        if narrate is not None and not isinstance(narrate, bool):
            raise ValueError("narrate debe ser true, false o null")
        return {"lesson_id": lesson_id, "narrate": narrate}
    service.require_publishable(conn, lesson_id)
    if job_type == "publish_tiktok":
        open_id = params.get("open_id")
        if not isinstance(open_id, str) or not open_id.strip():
            raise ValueError("open_id requerido")
        return {"lesson_id": lesson_id, "open_id": open_id.strip()}
    # publish_youtube
    privacy = params.get("privacy") or "private"
    lesson = lessons.get_lesson(conn, lesson_id)
    youtube.build_body(title=lesson["title"], description="", tags=None, privacy=privacy,
                       publish_at=params.get("publish_at"), duration_s=lesson.get("duration_s"))
    if not youtube.status()["connected"]:
        raise youtube.YouTubeNotConnected("YouTube no está conectado: usa Conectar YouTube primero")
    return {"lesson_id": lesson_id, "privacy": privacy, "publish_at": params.get("publish_at") or None}


def create_job(conn: sqlite3.Connection, job_type: str, params: dict | None) -> dict:
    clean = validate_params(conn, job_type, params)
    cur = conn.execute("INSERT INTO studio_jobs (type, status, params_json, created_at) VALUES (?, 'queued', ?, ?)",
                       (job_type, json.dumps(clean, ensure_ascii=False), now_iso()))
    conn.commit()
    job = get_job(conn, int(cur.lastrowid))
    notify(SOURCE, "queued", {"job_id": job["id"], "type": job_type, "status": "queued", "stage": "queued",
                              "pct": 0, "detail": ""})
    return job


# ── handlers ────────────────────────────────────────────────────────


def _h_index(conn: sqlite3.Connection, p: dict, progress: Progress) -> dict:
    from apps.media.indexer import index_asset, index_many
    from apps.studio.settings import connect
    ids = p["asset_ids"]
    progress("index", 5, f"{len(ids)} asset(s)")
    if p.get("steps"):
        reports = []
        for k, aid in enumerate(ids):
            progress("index", int(5 + 90 * k / len(ids)), f"asset {aid} ({k + 1}/{len(ids)})")
            try:
                reports.append(index_asset(conn, aid, steps=tuple(p["steps"]), force=p["force"]))
            except Exception as e:  # noqa: BLE001 — un asset roto no frena el lote
                reports.append({"asset_id": aid, "error": f"{type(e).__name__}: {e}"})
    else:
        reports = index_many(connect, ids, force=p["force"])
    errors = [r for r in reports if r.get("error")]
    if errors and len(errors) == len(reports):
        raise RuntimeError("; ".join(f"asset {r['asset_id']}: {r['error']}" for r in errors)[:1000])
    return {"assets": reports, "errors": len(errors)}


def _h_detect(conn: sqlite3.Connection, p: dict, progress: Progress) -> dict:
    from apps.moments.pipeline import detect_moments
    progress("detect", 10, f"asset {p['asset_id']}")
    return detect_moments(conn, p["asset_id"], fetch_anchors=p["fetch_anchors"])


def _h_label(conn: sqlite3.Connection, p: dict, progress: Progress) -> dict:
    from apps.moments.pipeline import label_asset
    progress("label", 10, f"asset {p['asset_id']}, top {p['top_k']}")
    report = label_asset(conn, p["asset_id"], top_k=p["top_k"], provider=p["provider"])
    if report.get("errors") and not report.get("labeled"):
        raise RuntimeError(f"Sin LLM disponible: {report['errors'][0]}"[:1000])
    return report


def _h_render(conn: sqlite3.Connection, p: dict, progress: Progress) -> dict:
    from apps.supercut.render import render_lesson
    return render_lesson(conn, p["lesson_id"], progress, narrate=p.get("narrate"))


def _h_publish_tiktok(conn: sqlite3.Connection, p: dict, progress: Progress) -> dict:
    from apps.publish.service import publish_lesson
    return publish_lesson(conn, p["lesson_id"], "tiktok", progress=progress, open_id=p["open_id"])


def _h_publish_youtube(conn: sqlite3.Connection, p: dict, progress: Progress) -> dict:
    from apps.publish.service import publish_lesson
    return publish_lesson(conn, p["lesson_id"], "youtube", progress=progress, privacy=p["privacy"],
                          publish_at=p.get("publish_at"))


HANDLERS: dict[str, Handler] = {
    "index": _h_index, "detect": _h_detect, "label": _h_label, "render": _h_render,
    "publish_tiktok": _h_publish_tiktok, "publish_youtube": _h_publish_youtube,
}


# ── worker ──────────────────────────────────────────────────────────


class JobQueue:
    """Un hilo que toma el job `queued` más viejo y lo corre con su propia conexión."""

    def __init__(self, conn_factory: Callable[[], sqlite3.Connection],
                 handlers: dict[str, Handler] | None = None, *, idle_wait: float = 2.0):
        self.conn_factory = conn_factory
        self.handlers = handlers if handlers is not None else HANDLERS
        self.idle_wait = idle_wait
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ciclo de vida
    def start(self) -> None:
        self.recover()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="studio-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    def recover(self) -> dict:
        conn = self.conn_factory()
        try:
            jobs = conn.execute("UPDATE studio_jobs SET status = 'error', error = 'interrumpido: el estudio se "
                                "reinició', finished_at = ? WHERE status = 'running'", (now_iso(),)).rowcount
            lessons_ = conn.execute("UPDATE lessons SET status = 'draft', updated_at = ? WHERE status = 'rendering'",
                                    (now_iso(),)).rowcount
            conn.commit()
        finally:
            conn.close()
        if jobs or lessons_:
            log.warning("Recuperación: %d job(s) interrumpidos, %d lección(es) rendering → draft", jobs, lessons_)
        return {"jobs": jobs, "lessons": lessons_}

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                ran = self.run_next()
            except Exception:  # noqa: BLE001 — el worker no muere por un error de la DB
                log.exception("Worker del estudio: error inesperado")
                ran = None
            if ran is None:
                self._wake.wait(self.idle_wait)
                self._wake.clear()

    # un job
    def run_next(self) -> int | None:
        """Corre el job queued más viejo. Devuelve su id, o None si no había."""
        conn = self.conn_factory()
        try:
            row = conn.execute("SELECT id FROM studio_jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return None
            job_id = int(row[0])
            claimed = conn.execute("UPDATE studio_jobs SET status = 'running', started_at = ? "
                                   "WHERE id = ? AND status = 'queued'", (now_iso(), job_id)).rowcount
            conn.commit()
            if not claimed:
                return job_id
            self._run(conn, get_job(conn, job_id))
            return job_id
        finally:
            conn.close()

    def _run(self, conn: sqlite3.Connection, job: dict) -> None:
        job_id, job_type = job["id"], job["type"]

        def progress(stage: str, pct: int, detail: str = "") -> None:
            prog = {"stage": stage, "pct": max(0, min(100, int(pct))), "detail": str(detail)[:300]}
            conn.execute("UPDATE studio_jobs SET progress_json = ? WHERE id = ?", (json.dumps(prog), job_id))
            conn.commit()
            notify(SOURCE, stage, {"job_id": job_id, "type": job_type, "status": "running", **prog})

        progress("start", 0, "")
        handler = self.handlers.get(job_type)
        try:
            if handler is None:
                raise ValueError(f"sin handler para {job_type!r}")
            result = handler(conn, job["params"], progress)
        except Exception as e:  # noqa: BLE001 — el error queda en el job, no tumba el worker
            log.warning("Job %s (%s) falló: %s", job_id, job_type, e)
            error = f"{type(e).__name__}: {e}"[:1000]
            conn.rollback()
            conn.execute("UPDATE studio_jobs SET status = 'error', error = ?, finished_at = ? WHERE id = ?",
                         (error, now_iso(), job_id))
            conn.commit()
            notify(SOURCE, "error", {"job_id": job_id, "type": job_type, "status": "error", "stage": "error",
                                     "pct": 100, "detail": error[:300]})
            return
        prog = {"stage": "done", "pct": 100, "detail": ""}
        conn.execute("UPDATE studio_jobs SET status = 'done', result_json = ?, progress_json = ?, finished_at = ? "
                     "WHERE id = ?", (json.dumps(result, ensure_ascii=False, default=str), json.dumps(prog),
                                      now_iso(), job_id))
        conn.commit()
        notify(SOURCE, "done", {"job_id": job_id, "type": job_type, "status": "done", **prog})
