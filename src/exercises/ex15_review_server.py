"""
ex15 - Servidor de revision de Shorts antes de publicar.

Dashboard web donde puedes:
  - Ver todos los Shorts generados con preview de video
  - Aprobar / Rechazar / Pedir edicion
  - Escribir notas de feedback (que hizo mal, que mejorar)
  - Marcar frames especificos con problemas
  - Dar rating (1-5 estrellas)
  - Ver historial de reviews
  - Los feedbacks alimentan la BD para mejorar futuras curaciones

Flujo:
  ex11/ex14 genera video → ex15 lo muestra para review → aprobado → ex12 sube

Uso:
  python src/main.py ex15
  python src/main.py ex15 --port 8080
  python src/main.py ex15 --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ── HTML Template ────────────────────────────────────────────────────

REVIEW_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Short Review Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e0e0e0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { text-align: center; margin-bottom: 30px; color: #fff; font-size: 1.8em; }
        .stats { display: flex; gap: 15px; margin-bottom: 30px; justify-content: center; }
        .stat { background: #1a1a2e; padding: 15px 25px; border-radius: 12px; text-align: center; }
        .stat-num { font-size: 2em; font-weight: bold; }
        .stat-label { font-size: 0.85em; color: #888; margin-top: 4px; }
        .stat.pending .stat-num { color: #f0ad4e; }
        .stat.approved .stat-num { color: #5cb85c; }
        .stat.rejected .stat-num { color: #d9534f; }

        .shorts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; }
        .short-card { background: #16213e; border-radius: 16px; overflow: hidden; transition: transform 0.2s; }
        .short-card:hover { transform: translateY(-3px); }
        .short-card video { width: 100%; max-height: 400px; object-fit: contain; background: #000; }
        .short-info { padding: 16px; }
        .short-title { font-size: 1.1em; font-weight: 600; margin-bottom: 8px; }
        .short-meta { font-size: 0.85em; color: #888; margin-bottom: 12px; }
        .short-meta span { margin-right: 12px; }

        .status-badge { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: 600; }
        .status-pending { background: #f0ad4e33; color: #f0ad4e; }
        .status-approved { background: #5cb85c33; color: #5cb85c; }
        .status-rejected { background: #d9534f33; color: #d9534f; }
        .status-needs_edit { background: #5bc0de33; color: #5bc0de; }

        .review-form { margin-top: 12px; padding-top: 12px; border-top: 1px solid #ffffff15; }
        .stars { display: flex; gap: 4px; margin-bottom: 10px; }
        .stars label { cursor: pointer; font-size: 1.5em; color: #444; transition: color 0.15s; }
        .stars input { display: none; }
        .stars label:hover, .stars label:hover ~ label, .stars input:checked ~ label { color: #f0ad4e; }
        .stars { direction: rtl; }

        textarea { width: 100%; background: #0d1b2a; border: 1px solid #ffffff20; border-radius: 8px;
                   color: #e0e0e0; padding: 10px; font-size: 0.9em; resize: vertical; min-height: 60px; }
        textarea:focus { outline: none; border-color: #5bc0de; }

        .btn-group { display: flex; gap: 8px; margin-top: 10px; }
        .btn { padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;
               font-size: 0.85em; transition: opacity 0.2s; }
        .btn:hover { opacity: 0.85; }
        .btn-approve { background: #5cb85c; color: #fff; }
        .btn-reject { background: #d9534f; color: #fff; }
        .btn-edit { background: #5bc0de; color: #fff; }

        .frame-issues { margin-top: 10px; }
        .frame-issue { display: flex; gap: 8px; margin-bottom: 6px; align-items: center; }
        .frame-issue input[type=number] { width: 80px; background: #0d1b2a; border: 1px solid #ffffff20;
                                           border-radius: 6px; color: #e0e0e0; padding: 5px 8px; }
        .frame-issue select { background: #0d1b2a; border: 1px solid #ffffff20; border-radius: 6px;
                               color: #e0e0e0; padding: 5px 8px; }
        .frame-issue input[type=text] { flex: 1; background: #0d1b2a; border: 1px solid #ffffff20;
                                         border-radius: 6px; color: #e0e0e0; padding: 5px 8px; }
        .add-frame-btn { background: none; border: 1px dashed #ffffff30; color: #888; padding: 6px 12px;
                          border-radius: 6px; cursor: pointer; font-size: 0.8em; margin-top: 4px; }
        .add-frame-btn:hover { border-color: #5bc0de; color: #5bc0de; }

        .history { margin-top: 30px; }
        .history h2 { margin-bottom: 15px; color: #888; font-size: 1.1em; }
        .log-entry { padding: 8px 12px; background: #1a1a2e; border-radius: 8px; margin-bottom: 6px;
                      font-size: 0.85em; display: flex; justify-content: space-between; }
        .log-action { font-weight: 600; }
        .log-time { color: #666; }

        .empty-state { text-align: center; padding: 60px 20px; color: #666; }
        .empty-state p { margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Short Review Dashboard</h1>
        <div class="stats" id="stats"></div>
        <div class="shorts-grid" id="shorts-grid"></div>
        <div class="history" id="history"></div>
    </div>

    <script>
        async function loadDashboard() {
            const resp = await fetch('/api/shorts');
            const data = await resp.json();
            renderStats(data.stats);
            renderShorts(data.shorts);
            renderHistory(data.logs);
        }

        function renderStats(stats) {
            document.getElementById('stats').innerHTML = `
                <div class="stat pending"><div class="stat-num">${stats.pending}</div><div class="stat-label">Pendientes</div></div>
                <div class="stat approved"><div class="stat-num">${stats.approved}</div><div class="stat-label">Aprobados</div></div>
                <div class="stat rejected"><div class="stat-num">${stats.rejected}</div><div class="stat-label">Rechazados</div></div>
                <div class="stat"><div class="stat-num">${stats.total}</div><div class="stat-label">Total</div></div>
            `;
        }

        function renderShorts(shorts) {
            const grid = document.getElementById('shorts-grid');
            if (!shorts.length) {
                grid.innerHTML = '<div class="empty-state"><h2>No hay Shorts para revisar</h2><p>Ejecuta el pipeline (ex04-ex11) para generar videos</p></div>';
                return;
            }
            grid.innerHTML = shorts.map(s => `
                <div class="short-card" data-id="${s.id}">
                    ${s.output_file ? `<video controls preload="metadata" src="/video/${encodeURIComponent(s.output_file)}"></video>` : '<div style="height:200px;background:#000;display:flex;align-items:center;justify-content:center;color:#666">Sin video</div>'}
                    <div class="short-info">
                        <div class="short-title">${s.title || 'Sin título'}</div>
                        <div class="short-meta">
                            <span>Tema: ${s.theme_query || '-'}</span>
                            <span class="status-badge status-${s.review_status || 'pending'}">${s.review_status || 'pending'}</span>
                            ${s.rating ? '<span>★'.repeat(s.rating) + '</span>' : ''}
                        </div>
                        <div class="review-form">
                            <div class="stars">
                                ${[5,4,3,2,1].map(n => `<input type="radio" name="rating-${s.id}" id="star-${s.id}-${n}" value="${n}"><label for="star-${s.id}-${n}">★</label>`).join('')}
                            </div>
                            <textarea id="notes-${s.id}" placeholder="Notas: qué hizo bien, qué mejorar, qué está mal...">${s.reviewer_notes || ''}</textarea>
                            <div class="frame-issues" id="frames-${s.id}">
                                <div class="add-frame-btn" onclick="addFrameIssue(${s.id})">+ Marcar frame con problema</div>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-approve" onclick="submitReview(${s.id}, 'approved')">Aprobar</button>
                                <button class="btn btn-edit" onclick="submitReview(${s.id}, 'needs_edit')">Pedir edición</button>
                                <button class="btn btn-reject" onclick="submitReview(${s.id}, 'rejected')">Rechazar</button>
                            </div>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function addFrameIssue(shortId) {
            const container = document.getElementById(`frames-${shortId}`);
            const div = document.createElement('div');
            div.className = 'frame-issue';
            div.innerHTML = `
                <input type="number" placeholder="Seg" min="0" step="0.5" class="frame-sec">
                <select class="frame-type">
                    <option value="bad_cut">Mal corte</option>
                    <option value="bad_text">Texto ilegible</option>
                    <option value="bad_color">Color malo</option>
                    <option value="wrong_scene">Escena equivocada</option>
                    <option value="audio_issue">Problema de audio</option>
                    <option value="timing">Timing incorrecto</option>
                    <option value="other">Otro</option>
                </select>
                <input type="text" placeholder="Descripción..." class="frame-desc">
            `;
            container.insertBefore(div, container.lastElementChild);
        }

        async function submitReview(shortId, status) {
            const notes = document.getElementById(`notes-${shortId}`).value;
            const ratingEl = document.querySelector(`input[name="rating-${shortId}"]:checked`);
            const rating = ratingEl ? parseInt(ratingEl.value) : null;

            // Collect frame issues
            const frameEls = document.querySelectorAll(`#frames-${shortId} .frame-issue`);
            const frameIssues = [];
            frameEls.forEach(el => {
                const sec = el.querySelector('.frame-sec')?.value;
                const type = el.querySelector('.frame-type')?.value;
                const desc = el.querySelector('.frame-desc')?.value;
                if (sec) frameIssues.push({ frame_s: parseFloat(sec), issue_type: type, description: desc || '' });
            });

            const resp = await fetch(`/api/review/${shortId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status, notes, rating, frame_issues: frameIssues })
            });

            if (resp.ok) {
                loadDashboard();
            } else {
                alert('Error al guardar review');
            }
        }

        function renderHistory(logs) {
            const container = document.getElementById('history');
            if (!logs.length) return;
            container.innerHTML = '<h2>Historial de actividad</h2>' +
                logs.slice(0, 20).map(l => `
                    <div class="log-entry">
                        <span><span class="log-action">${l.action}</span> — ${l.details || ''}</span>
                        <span class="log-time">${l.created_at}</span>
                    </div>
                `).join('');
        }

        loadDashboard();
        setInterval(loadDashboard, 30000);
    </script>
</body>
</html>"""


# ── Server ───────────────────────────────────────────────────────────


def _create_app(settings: Settings):
    """Create the FastAPI app for the review dashboard."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    except ImportError:
        return None

    app = FastAPI(title="Short Review Dashboard")
    data_dir = settings.data_dir
    output_dir = settings.output_dir

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return REVIEW_HTML

    @app.get("/api/shorts")
    async def get_shorts():
        conn = get_db(data_dir)
        _migrate_reviews(conn)

        # Get shorts with their latest review
        cur = conn.execute("""
            SELECT s.*,
                   r.status as review_status,
                   r.reviewer_notes,
                   r.rating,
                   r.frame_issues
            FROM shorts s
            LEFT JOIN reviews r ON r.short_id = s.id
                AND r.id = (SELECT MAX(id) FROM reviews WHERE short_id = s.id)
            ORDER BY s.created_at DESC
        """)
        shorts = [dict(row) for row in cur.fetchall()]

        # Stats
        stats = {"total": len(shorts), "pending": 0, "approved": 0, "rejected": 0}
        for s in shorts:
            st = s.get("review_status") or "pending"
            if st in stats:
                stats[st] += 1
            else:
                stats["pending"] += 1

        # Logs
        cur = conn.execute(
            "SELECT * FROM review_logs ORDER BY created_at DESC LIMIT 30"
        )
        logs = [dict(row) for row in cur.fetchall()]

        conn.close()
        return JSONResponse({"shorts": shorts, "stats": stats, "logs": logs})

    @app.post("/api/review/{short_id}")
    async def submit_review(short_id: int, request: Request):
        body = await request.json()
        conn = get_db(data_dir)
        _migrate_reviews(conn)

        now = datetime.now(timezone.utc).isoformat()

        # Insert review
        conn.execute("""
            INSERT INTO reviews (short_id, status, reviewer_notes, rating, frame_issues, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            short_id,
            body.get("status", "pending"),
            body.get("notes", ""),
            body.get("rating"),
            json.dumps(body.get("frame_issues", [])),
            now,
        ))

        # Log the action
        conn.execute("""
            INSERT INTO review_logs (short_id, action, details)
            VALUES (?, ?, ?)
        """, (
            short_id,
            body.get("status", "reviewed"),
            json.dumps({
                "notes": body.get("notes", "")[:200],
                "rating": body.get("rating"),
                "frame_issues_count": len(body.get("frame_issues", [])),
            }),
        ))

        # Update short status
        conn.execute(
            "UPDATE shorts SET status = ? WHERE id = ?",
            (body.get("status", "pending"), short_id),
        )

        # Feed back into quote scoring if rejected/needs_edit
        if body.get("status") in ("rejected", "needs_edit"):
            _apply_feedback_to_quotes(conn, short_id, body)

        conn.commit()
        conn.close()
        return JSONResponse({"ok": True})

    @app.get("/video/{path:path}")
    async def serve_video(path: str):
        # Serve video files from outputs directory
        video_path = Path(path)
        if not video_path.exists():
            video_path = output_dir / "video" / "finals" / video_path.name
        if not video_path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(video_path), media_type="video/mp4")

    return app


def _migrate_reviews(conn):
    """Create review tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            short_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            reviewer_notes TEXT,
            rating INTEGER,
            frame_issues TEXT,
            suggested_category TEXT,
            suggested_emotion TEXT,
            suggested_edit_style TEXT,
            reviewed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (short_id) REFERENCES shorts(id)
        );
        CREATE TABLE IF NOT EXISTS review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            short_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (short_id) REFERENCES shorts(id)
        );
    """)


def _apply_feedback_to_quotes(conn, short_id: int, body: dict):
    """
    When a Short is rejected or needs edit, decrease the viral_score
    of the quotes used in it. This creates a feedback loop that
    improves future curation.
    """
    cur = conn.execute("SELECT quote_ids FROM shorts WHERE id = ?", (short_id,))
    row = cur.fetchone()
    if not row or not row["quote_ids"]:
        return

    try:
        quote_ids = json.loads(row["quote_ids"])
    except (json.JSONDecodeError, TypeError):
        return

    # Decrease viral_score for quotes in rejected shorts
    penalty = 2 if body.get("status") == "rejected" else 1
    for qid in quote_ids:
        conn.execute(
            "UPDATE quotes SET viral_score = MAX(1, COALESCE(viral_score, 5) - ?) WHERE id = ?",
            (penalty, qid),
        )

    # Increment used_count
    for qid in quote_ids:
        conn.execute(
            "UPDATE quotes SET used_count = COALESCE(used_count, 0) + 1 WHERE id = ?",
            (qid,),
        )


# ── Entry point ──────────────────────────────────────────────────────


def run(
    settings: Settings,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> Path:
    log = build_logger("ex15", settings.output_dir / "logs" / "ex15.log")

    try:
        import uvicorn
        from fastapi import FastAPI
    except ImportError:
        msg = "FastAPI/uvicorn not installed. Run: pip install fastapi uvicorn"
        log.error(msg)
        rp = settings.output_dir / "logs" / "ex15_review_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(f"ex15 - ERROR: {msg}\n", encoding="utf-8")
        return rp

    app = _create_app(settings)
    if not app:
        log.error("Failed to create app")
        rp = settings.output_dir / "logs" / "ex15_review_report.txt"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text("ex15 - ERROR: Could not create app\n", encoding="utf-8")
        return rp

    log.info(f"Starting review dashboard at http://{host}:{port}")
    print(f"\n  Review Dashboard: http://{host}:{port}\n")

    uvicorn.run(app, host=host, port=port, log_level="info")

    # This only runs after server stops
    rp = settings.output_dir / "logs" / "ex15_review_report.txt"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("ex15 - Server stopped.\n", encoding="utf-8")
    return rp
