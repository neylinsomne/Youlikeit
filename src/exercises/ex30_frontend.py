"""
ex30 - Frontend público multi-página con htmx.

Diferencia con ex28 (dashboard):
  - ex28 = dashboard analítico interno (métricas, ETL, datos crudos)
  - ex30 = frontend público de gestión (CRUD de contenido, workflow)

Páginas:
  /app                   - Home: pipeline status + acciones rápidas
  /app/movies            - Explorar películas descubiertas
  /app/quotes            - Explorar y filtrar quotes
  /app/shorts            - Gestionar shorts (status, preview)
  /app/curriculum        - Ver/modificar plan de curriculum
  /app/export            - Exportar datos

Stack: FastAPI + htmx + CSS Grid. Zero build step.
Se conecta a la API de ex29 internamente (no requiere token para UI).

Uso:
  python src/main.py ex30
  python src/main.py ex30 --port 8002
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from common.websocket_hub import ETLTracker


# ---------------------------------------------------------------------------
# CSS (diseño limpio, responsive)
# ---------------------------------------------------------------------------

CSS = """
:root {
    --bg: #fafafa; --bg2: #fff; --bg3: #f5f5f5;
    --text: #1a1a1a; --text2: #666; --accent: #2563eb;
    --accent2: #dbeafe; --success: #16a34a; --warning: #ca8a04;
    --danger: #dc2626; --card: #fff; --border: #e5e7eb; --radius: 8px;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.layout { display: grid; grid-template-columns: 200px 1fr; min-height: 100vh; }
.sidebar {
    background: var(--bg2); border-right: 1px solid var(--border);
    padding: 1.5rem 0.8rem; position: sticky; top: 0; height: 100vh;
}
.sidebar h2 { font-size: 1rem; color: var(--accent); padding: 0 0.5rem; margin-bottom: 1.5rem; }
.sidebar nav a {
    display: block; padding: 0.5rem 0.8rem; margin: 0.15rem 0; border-radius: var(--radius);
    color: var(--text2); font-size: 0.85rem;
}
.sidebar nav a:hover, .sidebar nav a.active {
    background: var(--accent2); color: var(--accent); text-decoration: none;
}

.main { padding: 1.5rem 2rem; max-width: 1200px; }
.main h1 { font-size: 1.4rem; margin-bottom: 1rem; }

.card {
    background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1.2rem; margin-bottom: 1rem; box-shadow: var(--shadow);
}
.card h3 { font-size: 0.95rem; color: var(--text2); margin-bottom: 0.6rem; }

.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.stat { text-align: center; }
.stat .num { font-size: 2rem; font-weight: 700; color: var(--accent); }
.stat .label { font-size: 0.8rem; color: var(--text2); }

.filters {
    display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: center;
}
.filters select, .filters input {
    padding: 0.4rem 0.6rem; border: 1px solid var(--border); border-radius: var(--radius);
    font-size: 0.85rem; background: var(--bg2);
}
.btn {
    display: inline-block; padding: 0.4rem 0.8rem; border-radius: var(--radius);
    font-size: 0.85rem; cursor: pointer; border: none; font-weight: 500;
}
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: #1d4ed8; text-decoration: none; }
.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.8rem; }

table { width: 100%; border-collapse: collapse; }
th, td { padding: 0.5rem 0.6rem; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
th { color: var(--text2); font-weight: 600; font-size: 0.8rem; }
tr:hover { background: var(--bg3); }

.tag {
    display: inline-block; padding: 0.1rem 0.4rem; border-radius: 10px;
    font-size: 0.7rem; font-weight: 600;
}
.tag-blue { background: #dbeafe; color: #1e40af; }
.tag-green { background: #dcfce7; color: #166534; }
.tag-yellow { background: #fef3c7; color: #92400e; }
.tag-red { background: #fecaca; color: #991b1b; }

.pagination { display: flex; gap: 0.5rem; justify-content: center; margin-top: 1rem; }
.pagination a, .pagination span {
    padding: 0.3rem 0.6rem; border: 1px solid var(--border); border-radius: var(--radius);
    font-size: 0.85rem;
}
.pagination span { background: var(--accent); color: #fff; border-color: var(--accent); }

.empty { text-align: center; padding: 3rem; color: var(--text2); }

@media (max-width: 768px) {
    .layout { grid-template-columns: 1fr; }
    .sidebar { position: static; height: auto; display: flex; padding: 0.5rem; overflow-x: auto; }
    .sidebar h2 { display: none; }
    .sidebar nav { display: flex; gap: 0.3rem; }
    .sidebar nav a { white-space: nowrap; font-size: 0.8rem; }
    .grid-3 { grid-template-columns: 1fr; }
}
"""

BASE = Template("""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$title - YT Shorts Manager</title>
    <style>$css</style>
    <script src="https://unpkg.com/htmx.org@2.0.4" integrity="sha384-HGfztofotfshcF7+8n44JQL2oJmowVChPTg48S+jvZoztPfvwD79OC/LTtG6dMp+" crossorigin="anonymous"></script>
</head>
<body>
<div class="layout">
    <aside class="sidebar">
        <h2>Manager</h2>
        <nav>
            <a href="/app" $n_home>Home</a>
            <a href="/app/movies" $n_movies>Películas</a>
            <a href="/app/quotes" $n_quotes>Quotes</a>
            <a href="/app/shorts" $n_shorts>Shorts</a>
            <a href="/app/curriculum" $n_curriculum>Curriculum</a>
            <a href="/app/export" $n_export>Exportar</a>
        </nav>
    </aside>
    <main class="main">$content</main>
</div>
</body></html>""")


def _nav(page, current):
    return 'class="active"' if page == current else ""


def _html(title, content, page):
    return BASE.substitute(
        title=title, css=CSS, content=content,
        n_home=_nav("home", page), n_movies=_nav("movies", page),
        n_quotes=_nav("quotes", page), n_shorts=_nav("shorts", page),
        n_curriculum=_nav("curriculum", page), n_export=_nav("export", page),
    )


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def _home(conn):
    stats = {}
    for t in ["movies", "quotes", "shorts"]:
        cur = conn.execute(f"SELECT COUNT(*) as n FROM {t}")
        stats[t] = cur.fetchone()["n"]
    cur = conn.execute("SELECT COUNT(*) as n FROM quotes WHERE category IS NOT NULL")
    stats["classified"] = cur.fetchone()["n"]
    cur = conn.execute("SELECT COUNT(*) as n FROM quotes WHERE learning_type IS NOT NULL")
    stats["with_lessons"] = cur.fetchone()["n"]
    cur = conn.execute("SELECT COUNT(*) as n FROM curriculum_plan WHERE status = 'planned'")
    stats["planned"] = cur.fetchone()["n"]

    return f"""
    <h1>Pipeline Home</h1>
    <div class="grid-3">
        <div class="card stat"><div class="num">{stats['movies']}</div><div class="label">Películas</div></div>
        <div class="card stat"><div class="num">{stats['quotes']}</div><div class="label">Quotes totales</div></div>
        <div class="card stat"><div class="num">{stats['classified']}</div><div class="label">Clasificadas</div></div>
        <div class="card stat"><div class="num">{stats['with_lessons']}</div><div class="label">Con lección</div></div>
        <div class="card stat"><div class="num">{stats['shorts']}</div><div class="label">Shorts</div></div>
        <div class="card stat"><div class="num">{stats['planned']}</div><div class="label">En curriculum</div></div>
    </div>
    <div class="card">
        <h3>Acciones rápidas</h3>
        <div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin-top:0.5rem">
            <a href="/app/quotes?has_timestamps=true&learning_type=" class="btn btn-primary">Quotes listas para Short</a>
            <a href="/app/curriculum" class="btn btn-primary">Ver plan de curriculum</a>
            <a href="/app/export" class="btn btn-primary">Exportar datos</a>
        </div>
    </div>
    """


def _movies_page(conn, page_num=1, search=""):
    per_page = 25
    offset = (page_num - 1) * per_page

    if search:
        cur = conn.execute(
            "SELECT COUNT(*) as n FROM movies WHERE title LIKE ?",
            (f"%{search}%",),
        )
        total = cur.fetchone()["n"]
        cur = conn.execute(
            "SELECT * FROM movies WHERE title LIKE ? ORDER BY popularity DESC LIMIT ? OFFSET ?",
            (f"%{search}%", per_page, offset),
        )
    else:
        cur = conn.execute("SELECT COUNT(*) as n FROM movies")
        total = cur.fetchone()["n"]
        cur = conn.execute(
            "SELECT * FROM movies ORDER BY popularity DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        )
    movies = cur.fetchall()
    pages = (total + per_page - 1) // per_page

    # Count quotes per movie
    quote_counts = {}
    cur = conn.execute("SELECT movie_id, COUNT(*) as n FROM quotes GROUP BY movie_id")
    for r in cur.fetchall():
        quote_counts[r["movie_id"]] = r["n"]

    rows = ""
    for m in movies:
        qc = quote_counts.get(m["id"], 0)
        rows += f"""<tr>
            <td>{m['title']}</td>
            <td>{m['year'] or '—'}</td>
            <td>{m['popularity']:.0f}</td>
            <td>{qc}</td>
            <td>{(m['genre'] or '')[:30]}</td>
        </tr>"""

    pagination = ""
    if pages > 1:
        pagination = '<div class="pagination">'
        for p in range(1, min(pages + 1, 10)):
            if p == page_num:
                pagination += f'<span>{p}</span>'
            else:
                qs = f"?page={p}" + (f"&search={search}" if search else "")
                pagination += f'<a href="/app/movies{qs}">{p}</a>'
        pagination += '</div>'

    search_val = search.replace('"', '&quot;')
    return f"""
    <h1>Películas ({total})</h1>
    <div class="filters">
        <form method="get" action="/app/movies" style="display:flex;gap:0.5rem">
            <input name="search" placeholder="Buscar..." value="{search_val}">
            <button class="btn btn-primary btn-sm" type="submit">Buscar</button>
        </form>
    </div>
    <table>
        <thead><tr><th>Título</th><th>Año</th><th>Popularidad</th><th>Quotes</th><th>Género</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="5" class="empty">Sin películas</td></tr>'}</tbody>
    </table>
    {pagination}
    """


def _quotes_page(conn, page_num=1, category="", emotion="", learning_type=""):
    per_page = 30
    offset = (page_num - 1) * per_page
    conditions = []
    params: list = []

    if category:
        conditions.append("q.category = ?")
        params.append(category)
    if emotion:
        conditions.append("q.emotion = ?")
        params.append(emotion)
    if learning_type:
        conditions.append("q.learning_type = ?")
        params.append(learning_type)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    cur = conn.execute(f"SELECT COUNT(*) as n FROM quotes q {where}", params)
    total = cur.fetchone()["n"]

    cur = conn.execute(f"""
        SELECT q.*, m.title as movie_title FROM quotes q
        JOIN movies m ON q.movie_id = m.id
        {where}
        ORDER BY q.viral_score DESC NULLS LAST, q.confidence DESC
        LIMIT ? OFFSET ?
    """, (*params, per_page, offset))
    quotes = cur.fetchall()
    pages = (total + per_page - 1) // per_page

    # Get distinct filter values
    cur = conn.execute("SELECT DISTINCT category FROM quotes WHERE category IS NOT NULL ORDER BY category")
    categories = [r["category"] for r in cur.fetchall()]
    cur = conn.execute("SELECT DISTINCT emotion FROM quotes WHERE emotion IS NOT NULL ORDER BY emotion")
    emotions = [r["emotion"] for r in cur.fetchall()]
    cur = conn.execute("SELECT DISTINCT learning_type FROM quotes WHERE learning_type IS NOT NULL ORDER BY learning_type")
    learning_types = [r["learning_type"] for r in cur.fetchall()]

    cat_options = '<option value="">Todas</option>' + "".join(
        f'<option value="{c}" {"selected" if c == category else ""}>{c}</option>' for c in categories
    )
    emo_options = '<option value="">Todas</option>' + "".join(
        f'<option value="{e}" {"selected" if e == emotion else ""}>{e}</option>' for e in emotions
    )
    lt_options = '<option value="">Todos</option>' + "".join(
        f'<option value="{l}" {"selected" if l == learning_type else ""}>{l}</option>' for l in learning_types
    )

    rows = ""
    for q in quotes:
        cat_tag = f'<span class="tag tag-blue">{q["category"]}</span>' if q["category"] else ""
        emo_tag = f'<span class="tag tag-yellow">{q["emotion"]}</span>' if q["emotion"] else ""
        lt_tag = f'<span class="tag tag-green">{q["learning_type"]}</span>' if q["learning_type"] else ""
        vs = q["viral_score"] or 0
        rows += f"""<tr>
            <td title="{(q['text'] or '').replace('"', '&quot;')}">{(q['text'] or '')[:60]}...</td>
            <td>{q['movie_title'][:25]}</td>
            <td>{cat_tag} {emo_tag}</td>
            <td>{lt_tag}</td>
            <td>{vs}</td>
        </tr>"""

    pagination = ""
    if pages > 1:
        pagination = '<div class="pagination">'
        qs_base = f"category={category}&emotion={emotion}&learning_type={learning_type}"
        for p in range(1, min(pages + 1, 10)):
            if p == page_num:
                pagination += f'<span>{p}</span>'
            else:
                pagination += f'<a href="/app/quotes?page={p}&{qs_base}">{p}</a>'
        pagination += '</div>'

    return f"""
    <h1>Quotes ({total})</h1>
    <form class="filters" method="get" action="/app/quotes">
        <select name="category" onchange="this.form.submit()">{cat_options}</select>
        <select name="emotion" onchange="this.form.submit()">{emo_options}</select>
        <select name="learning_type" onchange="this.form.submit()">{lt_options}</select>
    </form>
    <table>
        <thead><tr><th>Texto</th><th>Película</th><th>Cat/Emoción</th><th>Lección</th><th>Viral</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="5" class="empty">Sin quotes</td></tr>'}</tbody>
    </table>
    {pagination}
    """


def _shorts_page(conn, status=""):
    conditions = []
    params: list = []
    if status:
        conditions.append("s.status = ?")
        params.append(status)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    cur = conn.execute(f"""
        SELECT s.*, a.views, a.likes, a.retention_avg, a.engagement_rate
        FROM shorts s
        LEFT JOIN analytics a ON a.short_id = s.id
        {where}
        ORDER BY s.created_at DESC
        LIMIT 50
    """, params)
    shorts = cur.fetchall()

    status_options = '<option value="">Todos</option>'
    for st in ["pending", "rendered", "uploaded"]:
        status_options += f'<option value="{st}" {"selected" if st == status else ""}>{st}</option>'

    rows = ""
    for s in shorts:
        st_class = {"uploaded": "tag-green", "rendered": "tag-blue", "pending": "tag-yellow"}.get(s["status"], "")
        rows += f"""<tr>
            <td>{s['title'] or s['theme_query'] or '—'}</td>
            <td><span class="tag {st_class}">{s['status']}</span></td>
            <td>{s['views'] or 0:,}</td>
            <td>{s['likes'] or 0:,}</td>
            <td>{s['retention_avg'] or 0:.1f}%</td>
            <td>{(s['created_at'] or '')[:10]}</td>
        </tr>"""

    return f"""
    <h1>Shorts</h1>
    <form class="filters" method="get" action="/app/shorts">
        <select name="status" onchange="this.form.submit()">{status_options}</select>
    </form>
    <table>
        <thead><tr><th>Título</th><th>Status</th><th>Views</th><th>Likes</th><th>Retention</th><th>Fecha</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="empty">Sin shorts</td></tr>'}</tbody>
    </table>
    """


def _curriculum_page(conn):
    cur = conn.execute("SELECT * FROM curriculum_plan ORDER BY position LIMIT 30")
    plan = cur.fetchall()

    rows = ""
    for p in plan:
        st_class = {"completed": "tag-green", "in_progress": "tag-blue", "planned": "tag-yellow", "skipped": "tag-red"}.get(p["status"], "")
        rows += f"""<tr>
            <td>{p['position']}</td>
            <td>{p['suggested_query']}</td>
            <td><span class="tag tag-blue">{p['target_learning_type']}</span></td>
            <td>{p['target_category']}</td>
            <td>{p['target_emotion'] or '—'}</td>
            <td><span class="tag {st_class}">{p['status']}</span></td>
        </tr>"""

    return f"""
    <h1>Plan de Curriculum</h1>
    <table>
        <thead><tr><th>#</th><th>Query sugerida</th><th>Tipo aprendizaje</th><th>Categoría</th><th>Emoción</th><th>Status</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="empty">Sin plan. Ejecuta ex33.</td></tr>'}</tbody>
    </table>
    """


def _export_page():
    return """
    <h1>Exportar datos</h1>
    <div class="card">
        <h3>Exportar pipeline completo</h3>
        <p style="color:var(--text2);margin:0.5rem 0">Genera CSV/JSON de todas las tablas + reporte del canal + backup de BD.</p>
        <p style="margin-top:0.8rem;font-size:0.9rem">
            Ejecuta desde terminal:<br>
            <code style="background:var(--bg3);padding:0.3rem 0.5rem;border-radius:4px;font-size:0.85rem">
                python src/main.py ex35
            </code>
        </p>
        <p style="margin-top:0.5rem;font-size:0.9rem">
            Para JSON:<br>
            <code style="background:var(--bg3);padding:0.3rem 0.5rem;border-radius:4px;font-size:0.85rem">
                python src/main.py ex35 --format json
            </code>
        </p>
    </div>
    """


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def build_frontend_app(settings: Settings):
    try:
        from fastapi import FastAPI, Query as QParam
        from fastapi.responses import HTMLResponse
    except ImportError:
        raise ImportError("FastAPI required: pip install fastapi uvicorn")

    app = FastAPI(title="YT Shorts Manager")

    def page(title, content, nav):
        return HTMLResponse(_html(title, content, nav))

    @app.get("/app", response_class=HTMLResponse)
    def home():
        conn = get_db(settings.data_dir)
        c = _home(conn)
        conn.close()
        return page("Home", c, "home")

    @app.get("/app/movies", response_class=HTMLResponse)
    def movies(page_num: int = QParam(1, alias="page"), search: str = ""):
        conn = get_db(settings.data_dir)
        c = _movies_page(conn, page_num, search)
        conn.close()
        return page("Películas", c, "movies")

    @app.get("/app/quotes", response_class=HTMLResponse)
    def quotes(
        page_num: int = QParam(1, alias="page"),
        category: str = "",
        emotion: str = "",
        learning_type: str = "",
    ):
        conn = get_db(settings.data_dir)
        c = _quotes_page(conn, page_num, category, emotion, learning_type)
        conn.close()
        return page("Quotes", c, "quotes")

    @app.get("/app/shorts", response_class=HTMLResponse)
    def shorts(status: str = ""):
        conn = get_db(settings.data_dir)
        c = _shorts_page(conn, status)
        conn.close()
        return page("Shorts", c, "shorts")

    @app.get("/app/curriculum", response_class=HTMLResponse)
    def curriculum():
        conn = get_db(settings.data_dir)
        c = _curriculum_page(conn)
        conn.close()
        return page("Curriculum", c, "curriculum")

    @app.get("/app/export", response_class=HTMLResponse)
    def export_page():
        return page("Exportar", _export_page(), "export")

    return app


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    host: str = "127.0.0.1",
    port: int = 8002,
) -> Path:
    log = build_logger("ex30", settings.output_dir / "logs" / "ex30.log")
    tracker = ETLTracker("ex30")

    tracker.extract_start()
    log.info("Starting frontend on %s:%d", host, port)

    print(f"\n{'='*60}")
    print(f"  YT Shorts Manager (Frontend)")
    print(f"  http://{host}:{port}/app")
    print(f"  Pages: /app /app/movies /app/quotes /app/shorts /app/curriculum /app/export")
    print(f"{'='*60}\n")

    app = build_frontend_app(settings)

    try:
        import uvicorn
        tracker.complete({"status": "running"})
        uvicorn.run(app, host=host, port=port, log_level="info")
    except ImportError:
        log.error("uvicorn not installed")
        print("ERROR: pip install uvicorn")

    return settings.output_dir / "logs" / "ex30_frontend.log"
