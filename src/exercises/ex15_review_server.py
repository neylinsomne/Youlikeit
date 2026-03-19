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
  - Soporte multi-idioma (es, en, pt)

Flujo:
  ex11/ex14 genera video → ex15 lo muestra para review → aprobado → ex12 sube

Uso:
  python src/main.py ex15
  python src/main.py ex15 --port 8080 --lang es
  python src/main.py ex15 --host 0.0.0.0 --port 8080 --lang en
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ── i18n ────────────────────────────────────────────────────────────

I18N = {
    "es": {
        "title": "Dashboard de Revisión de Shorts",
        "pending": "Pendientes",
        "approved": "Aprobados",
        "rejected": "Rechazados",
        "total": "Total",
        "no_shorts": "No hay Shorts para revisar",
        "no_shorts_hint": "Ejecuta el pipeline (ex04-ex11) para generar videos",
        "theme": "Tema",
        "notes_placeholder": "Notas: qué hizo bien, qué mejorar, qué está mal...",
        "add_frame": "+ Marcar frame con problema",
        "btn_approve": "Aprobar",
        "btn_edit": "Pedir edición",
        "btn_reject": "Rechazar",
        "no_video": "Sin video",
        "no_title": "Sin título",
        "history_title": "Historial de actividad",
        "frame_second": "Seg",
        "frame_desc": "Descripción...",
        "bad_cut": "Mal corte",
        "bad_text": "Texto ilegible",
        "bad_color": "Color malo",
        "wrong_scene": "Escena equivocada",
        "audio_issue": "Problema de audio",
        "timing": "Timing incorrecto",
        "other": "Otro",
        "error_save": "Error al guardar review",
        "lang_label": "Idioma",
        "strategy": "Estrategia",
        "view_strategy": "Ver estrategia de publicación",
        "no_strategy": "Sin estrategia (ejecutar ex17)",
    },
    "en": {
        "title": "Shorts Review Dashboard",
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
        "total": "Total",
        "no_shorts": "No Shorts to review",
        "no_shorts_hint": "Run the pipeline (ex04-ex11) to generate videos",
        "theme": "Theme",
        "notes_placeholder": "Notes: what was good, what to improve, what's wrong...",
        "add_frame": "+ Flag frame issue",
        "btn_approve": "Approve",
        "btn_edit": "Request edit",
        "btn_reject": "Reject",
        "no_video": "No video",
        "no_title": "No title",
        "history_title": "Activity log",
        "frame_second": "Sec",
        "frame_desc": "Description...",
        "bad_cut": "Bad cut",
        "bad_text": "Unreadable text",
        "bad_color": "Bad color",
        "wrong_scene": "Wrong scene",
        "audio_issue": "Audio issue",
        "timing": "Bad timing",
        "other": "Other",
        "error_save": "Error saving review",
        "lang_label": "Language",
        "strategy": "Strategy",
        "view_strategy": "View publish strategy",
        "no_strategy": "No strategy (run ex17)",
    },
    "pt": {
        "title": "Painel de Revisão de Shorts",
        "pending": "Pendentes",
        "approved": "Aprovados",
        "rejected": "Rejeitados",
        "total": "Total",
        "no_shorts": "Nenhum Short para revisar",
        "no_shorts_hint": "Execute o pipeline (ex04-ex11) para gerar vídeos",
        "theme": "Tema",
        "notes_placeholder": "Notas: o que ficou bom, o que melhorar, o que está errado...",
        "add_frame": "+ Marcar frame com problema",
        "btn_approve": "Aprovar",
        "btn_edit": "Pedir edição",
        "btn_reject": "Rejeitar",
        "no_video": "Sem vídeo",
        "no_title": "Sem título",
        "history_title": "Histórico de atividade",
        "frame_second": "Seg",
        "frame_desc": "Descrição...",
        "bad_cut": "Corte ruim",
        "bad_text": "Texto ilegível",
        "bad_color": "Cor ruim",
        "wrong_scene": "Cena errada",
        "audio_issue": "Problema de áudio",
        "timing": "Timing incorreto",
        "other": "Outro",
        "error_save": "Erro ao salvar revisão",
        "lang_label": "Idioma",
        "strategy": "Estratégia",
        "view_strategy": "Ver estratégia de publicação",
        "no_strategy": "Sem estratégia (executar ex17)",
    },
}


# ── HTML Template ────────────────────────────────────────────────────

def _render_lang_buttons(lang: str) -> str:
    """Render language switcher buttons (extracted for Python 3.10 compat)."""
    buttons = []
    for l in I18N.keys():
        active = " active" if l == lang else ""
        buttons.append(
            '<button class="lang-btn' + active + '" '
            "onclick=\"switchLang('" + l + "')\">" + l.upper() + "</button>"
        )
    return "".join(buttons)


def _build_html(lang: str = "es") -> str:
    """Build the review HTML with i18n strings injected."""
    t = I18N.get(lang, I18N["es"])
    t_json = json.dumps(t, ensure_ascii=False)
    langs_available = json.dumps(list(I18N.keys()))

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['title']}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0a0a0a; color: #e0e0e0; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .top-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }}
        h1 {{ color: #fff; font-size: 1.8em; }}
        .lang-switcher {{ display: flex; gap: 6px; align-items: center; }}
        .lang-switcher label {{ color: #888; font-size: 0.85em; margin-right: 4px; }}
        .lang-btn {{ padding: 4px 10px; border: 1px solid #ffffff30; border-radius: 6px; background: none;
                     color: #888; cursor: pointer; font-size: 0.8em; text-transform: uppercase; }}
        .lang-btn.active {{ background: #5bc0de33; color: #5bc0de; border-color: #5bc0de; }}
        .lang-btn:hover {{ border-color: #5bc0de; color: #5bc0de; }}

        .stats {{ display: flex; gap: 15px; margin-bottom: 30px; justify-content: center; }}
        .stat {{ background: #1a1a2e; padding: 15px 25px; border-radius: 12px; text-align: center; }}
        .stat-num {{ font-size: 2em; font-weight: bold; }}
        .stat-label {{ font-size: 0.85em; color: #888; margin-top: 4px; }}
        .stat.pending .stat-num {{ color: #f0ad4e; }}
        .stat.approved .stat-num {{ color: #5cb85c; }}
        .stat.rejected .stat-num {{ color: #d9534f; }}

        .shorts-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; }}
        .short-card {{ background: #16213e; border-radius: 16px; overflow: hidden; transition: transform 0.2s; }}
        .short-card:hover {{ transform: translateY(-3px); }}
        .short-card video {{ width: 100%; max-height: 400px; object-fit: contain; background: #000; }}
        .short-info {{ padding: 16px; }}
        .short-title {{ font-size: 1.1em; font-weight: 600; margin-bottom: 8px; }}
        .short-meta {{ font-size: 0.85em; color: #888; margin-bottom: 12px; }}
        .short-meta span {{ margin-right: 12px; }}

        .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: 600; }}
        .status-pending {{ background: #f0ad4e33; color: #f0ad4e; }}
        .status-approved {{ background: #5cb85c33; color: #5cb85c; }}
        .status-rejected {{ background: #d9534f33; color: #d9534f; }}
        .status-needs_edit {{ background: #5bc0de33; color: #5bc0de; }}

        .review-form {{ margin-top: 12px; padding-top: 12px; border-top: 1px solid #ffffff15; }}
        .stars {{ display: flex; gap: 4px; margin-bottom: 10px; direction: rtl; }}
        .stars label {{ cursor: pointer; font-size: 1.5em; color: #444; transition: color 0.15s; }}
        .stars input {{ display: none; }}
        .stars label:hover, .stars label:hover ~ label, .stars input:checked ~ label {{ color: #f0ad4e; }}

        textarea {{ width: 100%; background: #0d1b2a; border: 1px solid #ffffff20; border-radius: 8px;
                   color: #e0e0e0; padding: 10px; font-size: 0.9em; resize: vertical; min-height: 60px; }}
        textarea:focus {{ outline: none; border-color: #5bc0de; }}

        .btn-group {{ display: flex; gap: 8px; margin-top: 10px; }}
        .btn {{ padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;
               font-size: 0.85em; transition: opacity 0.2s; }}
        .btn:hover {{ opacity: 0.85; }}
        .btn-approve {{ background: #5cb85c; color: #fff; }}
        .btn-reject {{ background: #d9534f; color: #fff; }}
        .btn-edit {{ background: #5bc0de; color: #fff; }}

        .strategy-link {{ display: inline-block; margin-top: 8px; color: #5bc0de; font-size: 0.85em;
                          text-decoration: none; border-bottom: 1px dashed #5bc0de40; }}
        .strategy-link:hover {{ border-color: #5bc0de; }}

        .frame-issues {{ margin-top: 10px; }}
        .frame-issue {{ display: flex; gap: 8px; margin-bottom: 6px; align-items: center; }}
        .frame-issue input[type=number] {{ width: 80px; background: #0d1b2a; border: 1px solid #ffffff20;
                                           border-radius: 6px; color: #e0e0e0; padding: 5px 8px; }}
        .frame-issue select {{ background: #0d1b2a; border: 1px solid #ffffff20; border-radius: 6px;
                               color: #e0e0e0; padding: 5px 8px; }}
        .frame-issue input[type=text] {{ flex: 1; background: #0d1b2a; border: 1px solid #ffffff20;
                                         border-radius: 6px; color: #e0e0e0; padding: 5px 8px; }}
        .add-frame-btn {{ background: none; border: 1px dashed #ffffff30; color: #888; padding: 6px 12px;
                          border-radius: 6px; cursor: pointer; font-size: 0.8em; margin-top: 4px; }}
        .add-frame-btn:hover {{ border-color: #5bc0de; color: #5bc0de; }}

        .history {{ margin-top: 30px; }}
        .history h2 {{ margin-bottom: 15px; color: #888; font-size: 1.1em; }}
        .log-entry {{ padding: 8px 12px; background: #1a1a2e; border-radius: 8px; margin-bottom: 6px;
                      font-size: 0.85em; display: flex; justify-content: space-between; }}
        .log-action {{ font-weight: 600; }}
        .log-time {{ color: #666; }}

        .empty-state {{ text-align: center; padding: 60px 20px; color: #666; }}
        .empty-state p {{ margin-top: 10px; }}

        .strategy-panel {{ background: #1a1a2e; border-radius: 12px; padding: 16px; margin-top: 10px;
                           display: none; font-size: 0.85em; }}
        .strategy-panel.open {{ display: block; }}
        .strategy-row {{ display: flex; justify-content: space-between; padding: 4px 0;
                         border-bottom: 1px solid #ffffff08; }}
        .strategy-row:last-child {{ border: none; }}
        .strategy-key {{ color: #888; }}
        .strategy-val {{ color: #e0e0e0; text-align: right; max-width: 60%; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="top-bar">
            <h1>{t['title']}</h1>
            <div class="lang-switcher">
                <label>{t['lang_label']}:</label>
                {_render_lang_buttons(lang)}
            </div>
        </div>
        <div class="stats" id="stats"></div>
        <div class="shorts-grid" id="shorts-grid"></div>
        <div class="history" id="history"></div>
    </div>

    <script>
        const T = {t_json};
        const LANGS = {langs_available};
        const CURRENT_LANG = '{lang}';

        function switchLang(lang) {{
            window.location.href = '/?lang=' + lang;
        }}

        async function loadDashboard() {{
            const resp = await fetch('/api/shorts');
            const data = await resp.json();
            renderStats(data.stats);
            renderShorts(data.shorts, data.strategies || {{}});
            renderHistory(data.logs);
        }}

        function renderStats(stats) {{
            document.getElementById('stats').innerHTML = `
                <div class="stat pending"><div class="stat-num">${'${stats.pending}'}</div><div class="stat-label">${'${T.pending}'}</div></div>
                <div class="stat approved"><div class="stat-num">${'${stats.approved}'}</div><div class="stat-label">${'${T.approved}'}</div></div>
                <div class="stat rejected"><div class="stat-num">${'${stats.rejected}'}</div><div class="stat-label">${'${T.rejected}'}</div></div>
                <div class="stat"><div class="stat-num">${'${stats.total}'}</div><div class="stat-label">${'${T.total}'}</div></div>
            `;
        }}

        function renderShorts(shorts, strategies) {{
            const grid = document.getElementById('shorts-grid');
            if (!shorts.length) {{
                grid.innerHTML = `<div class="empty-state"><h2>${'${T.no_shorts}'}</h2><p>${'${T.no_shorts_hint}'}</p></div>`;
                return;
            }}
            grid.innerHTML = shorts.map(s => {{
                const strat = strategies[s.theme_query] || null;
                return `
                <div class="short-card" data-id="${'${s.id}'}">
                    ${'${s.output_file ? `<video controls preload="metadata" src="/video/${encodeURIComponent(s.output_file)}"></video>` : `<div style="height:200px;background:#000;display:flex;align-items:center;justify-content:center;color:#666">${T.no_video}</div>`}'}
                    <div class="short-info">
                        <div class="short-title">${'${s.title || T.no_title}'}</div>
                        <div class="short-meta">
                            <span>${'${T.theme}'}: ${'${s.theme_query || "-"}'}</span>
                            <span class="status-badge status-${'${s.review_status || "pending"}'}">${'${s.review_status || "pending"}'}</span>
                            ${'${s.rating ? "★".repeat(s.rating) : ""}'}
                        </div>
                        ${'${strat ? `<a class="strategy-link" href="#" onclick="toggleStrategy(${s.id}); return false;">${T.view_strategy}</a><div class="strategy-panel" id="strat-${s.id}">${renderStrategyPanel(strat)}</div>` : `<span style="font-size:0.8em;color:#666">${T.no_strategy}</span>`}'}
                        <div class="review-form">
                            <div class="stars">
                                ${'${[5,4,3,2,1].map(n => `<input type="radio" name="rating-${s.id}" id="star-${s.id}-${n}" value="${n}"><label for="star-${s.id}-${n}">★</label>`).join("")}'}
                            </div>
                            <textarea id="notes-${'${s.id}'}" placeholder="${'${T.notes_placeholder}'}">${'${s.reviewer_notes || ""}'}</textarea>
                            <div class="frame-issues" id="frames-${'${s.id}'}">
                                <div class="add-frame-btn" onclick="addFrameIssue(${'${s.id}'})">${'${T.add_frame}'}</div>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-approve" onclick="submitReview(${'${s.id}'}, 'approved')">${'${T.btn_approve}'}</button>
                                <button class="btn btn-edit" onclick="submitReview(${'${s.id}'}, 'needs_edit')">${'${T.btn_edit}'}</button>
                                <button class="btn btn-reject" onclick="submitReview(${'${s.id}'}, 'rejected')">${'${T.btn_reject}'}</button>
                            </div>
                        </div>
                    </div>
                </div>`;
            }}).join('');
        }}

        function renderStrategyPanel(strat) {{
            if (!strat) return '';
            let html = '';
            for (const [plat, data] of Object.entries(strat)) {{
                html += `<div style="margin-bottom:8px;font-weight:600;color:#5bc0de">${'${plat.toUpperCase()}'}</div>`;
                if (data.title) html += `<div class="strategy-row"><span class="strategy-key">Title</span><span class="strategy-val">${'${data.title}'}</span></div>`;
                if (data.hashtags_string) html += `<div class="strategy-row"><span class="strategy-key">Hashtags</span><span class="strategy-val">${'${data.hashtags_string}'}</span></div>`;
                if (data.best_upload_time) html += `<div class="strategy-row"><span class="strategy-key">Best time</span><span class="strategy-val">${'${data.best_upload_time}'} ${'${data.timezone || ""}'}</span></div>`;
                if (data.sound) html += `<div class="strategy-row"><span class="strategy-key">Sound</span><span class="strategy-val">${'${data.sound.title || ""}'}</span></div>`;
            }}
            return html;
        }}

        function toggleStrategy(id) {{
            const el = document.getElementById('strat-' + id);
            if (el) el.classList.toggle('open');
        }}

        function addFrameIssue(shortId) {{
            const container = document.getElementById(`frames-${'${shortId}'}`);
            const div = document.createElement('div');
            div.className = 'frame-issue';
            div.innerHTML = `
                <input type="number" placeholder="${'${T.frame_second}'}" min="0" step="0.5" class="frame-sec">
                <select class="frame-type">
                    <option value="bad_cut">${'${T.bad_cut}'}</option>
                    <option value="bad_text">${'${T.bad_text}'}</option>
                    <option value="bad_color">${'${T.bad_color}'}</option>
                    <option value="wrong_scene">${'${T.wrong_scene}'}</option>
                    <option value="audio_issue">${'${T.audio_issue}'}</option>
                    <option value="timing">${'${T.timing}'}</option>
                    <option value="other">${'${T.other}'}</option>
                </select>
                <input type="text" placeholder="${'${T.frame_desc}'}" class="frame-desc">
            `;
            container.insertBefore(div, container.lastElementChild);
        }}

        async function submitReview(shortId, status) {{
            const notes = document.getElementById(`notes-${'${shortId}'}`).value;
            const ratingEl = document.querySelector(`input[name="rating-${'${shortId}'}"]:checked`);
            const rating = ratingEl ? parseInt(ratingEl.value) : null;

            const frameEls = document.querySelectorAll(`#frames-${'${shortId}'} .frame-issue`);
            const frameIssues = [];
            frameEls.forEach(el => {{
                const sec = el.querySelector('.frame-sec')?.value;
                const type = el.querySelector('.frame-type')?.value;
                const desc = el.querySelector('.frame-desc')?.value;
                if (sec) frameIssues.push({{ frame_s: parseFloat(sec), issue_type: type, description: desc || '' }});
            }});

            const resp = await fetch(`/api/review/${'${shortId}'}`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ status, notes, rating, frame_issues: frameIssues }})
            }});

            if (resp.ok) {{
                loadDashboard();
            }} else {{
                alert(T.error_save);
            }}
        }}

        function renderHistory(logs) {{
            const container = document.getElementById('history');
            if (!logs.length) return;
            container.innerHTML = `<h2>${'${T.history_title}'}</h2>` +
                logs.slice(0, 20).map(l => `
                    <div class="log-entry">
                        <span><span class="log-action">${'${l.action}'}</span> — ${'${l.details || ""}'}</span>
                        <span class="log-time">${'${l.created_at}'}</span>
                    </div>
                `).join('');
        }}

        loadDashboard();
        setInterval(loadDashboard, 30000);
    </script>
</body>
</html>"""


# ── Server ───────────────────────────────────────────────────────────


def _load_strategies(output_dir: Path) -> dict:
    """Load all publish strategies from ex17 keyed by theme_query."""
    pub_dir = output_dir / "publish"
    if not pub_dir.exists():
        return {}

    strategies = {}
    for f in sorted(pub_dir.glob("ex17_strategy_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            query = data.get("query", "")
            if query and query not in strategies:
                strategies[query] = data.get("platform_strategies", {})
        except Exception:
            continue
    return strategies


def _create_app(settings: Settings, lang: str = "es"):
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
    async def dashboard(request: Request):
        # Allow language switch via query param
        req_lang = request.query_params.get("lang", lang)
        if req_lang not in I18N:
            req_lang = lang
        return _build_html(req_lang)

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

        # Load publish strategies from ex17
        strategies = _load_strategies(output_dir)

        conn.close()
        return JSONResponse({"shorts": shorts, "stats": stats, "logs": logs, "strategies": strategies})

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
    lang: str = "es",
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

    app = _create_app(settings, lang=lang)
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
