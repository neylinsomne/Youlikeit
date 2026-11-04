"""
WebSocket hub for real-time ETL progress and dashboard updates.

Usage in ETL exercises:
    from utils.websocket_hub import notify

    notify("ex24", "extract", {"step": "fetching retention", "progress": 30})
    notify("ex24", "transform", {"step": "detecting cliffs", "video": "abc123"})
    notify("ex24", "load", {"step": "saved 45 retention points"})
    notify("ex24", "complete", {"videos_processed": 12, "events_found": 8})

Usage in dashboard (FastAPI):
    from utils.websocket_hub import create_ws_endpoint

    app = FastAPI()
    create_ws_endpoint(app)
    # Frontend connects to ws://localhost:8000/ws and receives all events

The hub is fire-and-forget: if no dashboard is listening, events are silently
dropped. ETL exercises never block on WebSocket delivery.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import UTC, datetime

# A nivel de módulo a propósito: con `from __future__ import annotations` FastAPI resuelve
# la anotación `websocket: WebSocket` con los globals del módulo; importada dentro de la
# función no la encuentra, la trata como query param y cierra todo con 1008.
try:
    from fastapi import WebSocket, WebSocketDisconnect
except ImportError:  # runtime mínimo (crons) sin fastapi: notify() sigue funcionando
    WebSocket = WebSocketDisconnect = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# In-memory event bus (no external deps)
# ---------------------------------------------------------------------------

# Recent events buffer (last 100 events, for late-connecting clients)
_event_buffer: deque = deque(maxlen=100)

# Connected WebSocket clients
_ws_clients: set = set()

# Event loop del servidor (se captura cuando conecta el primer cliente). notify()
# se llama desde hilos de trabajo (jobs del estudio, indexer): sin este loop,
# asyncio.ensure_future fallaba y se desconectaba a TODOS los clientes.
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _build_event(source: str, stage: str, data: dict | None = None) -> dict:
    """Build a structured event."""
    return {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": source,
        "stage": stage,  # extract, transform, load, complete, error
        "data": data or {},
    }


def notify(source: str, stage: str, data: dict | None = None):
    """
    Fire-and-forget notification from ETL to any listening dashboards.
    Safe to call from sync code - never blocks.
    """
    event = _build_event(source, stage, data)
    _event_buffer.append(event)

    # Try to push to connected WebSocket clients (seguro desde cualquier hilo)
    global _ws_clients
    if not _ws_clients:
        return
    msg = json.dumps(event, ensure_ascii=False, default=str)
    try:
        running = asyncio.get_running_loop()           # estamos en el hilo del servidor
    except RuntimeError:
        running = None
    loop = _loop
    disconnected = set()
    for ws in list(_ws_clients):
        try:
            if running is not None:
                running.create_task(ws.send_text(msg))
            elif loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(ws.send_text(msg), loop)
            # sin loop disponible: el evento queda en el buffer; NO se desconecta al cliente
        except Exception:
            disconnected.add(ws)
    _ws_clients -= disconnected


def get_recent_events(n: int = 50) -> list[dict]:
    """Get last N events from the buffer."""
    return list(_event_buffer)[-n:]


# ---------------------------------------------------------------------------
# ETL progress tracker
# ---------------------------------------------------------------------------

class ETLTracker:
    """
    Track ETL progress for a single exercise run.

    Usage:
        tracker = ETLTracker("ex24")
        tracker.extract_start(total=12)
        for video in videos:
            tracker.extract_progress(current=i, detail=f"video {video.id}")
        tracker.extract_done(result={"videos": 12})

        tracker.transform_start()
        ...
        tracker.transform_done(result={"events": 45})

        tracker.load_start()
        ...
        tracker.load_done(result={"rows_inserted": 120})

        tracker.complete(summary={...})
    """

    def __init__(self, source: str):
        self.source = source
        self.start_time = time.time()
        self._stage_start = 0.0

    def extract_start(self, total: int = 0):
        self._stage_start = time.time()
        notify(self.source, "extract", {"status": "started", "total": total})

    def extract_progress(self, current: int, total: int = 0, detail: str = ""):
        pct = round(current / total * 100) if total > 0 else 0
        notify(self.source, "extract", {
            "status": "progress", "current": current, "total": total,
            "pct": pct, "detail": detail,
        })

    def extract_done(self, result: dict | None = None):
        elapsed = round(time.time() - self._stage_start, 2)
        notify(self.source, "extract", {
            "status": "done", "elapsed_s": elapsed, **(result or {}),
        })

    def transform_start(self, detail: str = ""):
        self._stage_start = time.time()
        notify(self.source, "transform", {"status": "started", "detail": detail})

    def transform_progress(self, current: int, total: int = 0, detail: str = ""):
        pct = round(current / total * 100) if total > 0 else 0
        notify(self.source, "transform", {
            "status": "progress", "current": current, "total": total,
            "pct": pct, "detail": detail,
        })

    def transform_done(self, result: dict | None = None):
        elapsed = round(time.time() - self._stage_start, 2)
        notify(self.source, "transform", {
            "status": "done", "elapsed_s": elapsed, **(result or {}),
        })

    def load_start(self):
        self._stage_start = time.time()
        notify(self.source, "load", {"status": "started"})

    def load_done(self, result: dict | None = None):
        elapsed = round(time.time() - self._stage_start, 2)
        notify(self.source, "load", {
            "status": "done", "elapsed_s": elapsed, **(result or {}),
        })

    def complete(self, summary: dict | None = None):
        total_elapsed = round(time.time() - self.start_time, 2)
        notify(self.source, "complete", {
            "total_elapsed_s": total_elapsed, **(summary or {}),
        })

    def error(self, message: str, detail: dict | None = None):
        notify(self.source, "error", {"message": message, **(detail or {})})


# ---------------------------------------------------------------------------
# FastAPI WebSocket endpoint
# ---------------------------------------------------------------------------

def create_ws_endpoint(app):
    """
    Add a WebSocket endpoint to a FastAPI app.

    Clients connect to ws://host:port/ws and receive all ETL events in real time.
    On connect, they receive the last 20 events as a catch-up buffer.
    """
    if WebSocket is None:
        return

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        bind_loop(asyncio.get_running_loop())
        _ws_clients.add(websocket)

        # Send recent events as catch-up
        try:
            recent = get_recent_events(20)
            if recent:
                await websocket.send_text(json.dumps({
                    "type": "catchup",
                    "events": recent,
                }, ensure_ascii=False))
        except Exception:
            pass

        # Keep alive until disconnect
        try:
            while True:
                # Wait for ping/pong or client messages
                await websocket.receive_text()
        except WebSocketDisconnect:
            _ws_clients.discard(websocket)
        except Exception:
            _ws_clients.discard(websocket)
