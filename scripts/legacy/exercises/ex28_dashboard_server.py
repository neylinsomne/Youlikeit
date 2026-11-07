"""
ex28 - Dashboard analítico con htmx + Canvas API (sin React, sin npm).

Stack:
  - FastAPI sirviendo HTML con Jinja2-like templates (string.Template)
  - htmx 2.0 desde CDN (14KB) para interactividad sin JS frameworks
  - Canvas API vanilla para gráficas (retención, engagement, distribución)
  - WebSocket para progreso ETL en tiempo real
  - CSS Grid responsive, dark mode, zero build step

Páginas:
  /                     - Overview: KPIs + gráficas principales
  /retention            - Curvas de retención + eventos
  /lessons              - Lesson performance + curriculum
  /audience             - Demographics + segmentos
  /knowledge            - Knowledge base + insights
  /goals                - Metas + progreso
  /etl                  - ETL monitor (WebSocket live)

Diseño:
  - Sidebar con navegación
  - Cards para KPIs
  - Canvas para gráficas
  - htmx para cargar secciones sin recargar

Uso:
  python src/main.py ex28
  python src/main.py ex28 --port 8000
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from string import Template

from core.config import Settings
from core.db import get_db
from utils.logger import build_logger
from utils.websocket_hub import ETLTracker, create_ws_endpoint, get_recent_events


# ---------------------------------------------------------------------------
# HTML Templates (zero build step, zero Jinja2 dependency)
# ---------------------------------------------------------------------------

CSS = """
:root {
    --bg: #0f0f0f; --bg2: #1a1a2e; --bg3: #16213e;
    --text: #e0e0e0; --text2: #a0a0a0; --accent: #e94560;
    --accent2: #0f3460; --success: #4ecca3; --warning: #f0a500;
    --card: #1a1a2e; --border: #2a2a4a; --radius: 8px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.layout { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
.sidebar {
    background: var(--bg2); padding: 1.5rem 1rem; border-right: 1px solid var(--border);
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
}
.sidebar h2 { color: var(--accent); font-size: 1.1rem; margin-bottom: 1.5rem; }
.sidebar nav a {
    display: block; padding: 0.6rem 0.8rem; margin: 0.2rem 0;
    border-radius: var(--radius); color: var(--text2); font-size: 0.9rem;
}
.sidebar nav a:hover, .sidebar nav a.active {
    background: var(--accent2); color: var(--text); text-decoration: none;
}

.main { padding: 2rem; max-width: 1400px; }
.main h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: var(--text); }

.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
.kpi-card {
    background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1.2rem; text-align: center;
}
.kpi-card .value { font-size: 2rem; font-weight: 700; color: var(--accent); }
.kpi-card .label { font-size: 0.8rem; color: var(--text2); margin-top: 0.3rem; }

.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
.chart-card {
    background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1.2rem;
}
.chart-card h3 { font-size: 0.95rem; margin-bottom: 0.8rem; color: var(--text2); }
.chart-card canvas { width: 100% !important; height: 250px !important; }

table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.85rem; }
th { color: var(--text2); font-weight: 600; }
tr:hover { background: var(--bg3); }

.tag {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600;
}
.tag-success { background: #1a4a3a; color: var(--success); }
.tag-warning { background: #4a3a1a; color: var(--warning); }
.tag-accent { background: #3a1a2a; color: var(--accent); }

.bar { display: inline-block; height: 16px; background: var(--accent); border-radius: 3px; min-width: 2px; }
.bar-success { background: var(--success); }

.etl-log { background: #111; border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1rem; font-family: monospace; font-size: 0.8rem; max-height: 500px;
    overflow-y: auto; white-space: pre-wrap; }
.etl-event { padding: 0.3rem 0; border-bottom: 1px solid #222; }
.etl-event .ts { color: var(--text2); }
.etl-event .stage-extract { color: #64b5f6; }
.etl-event .stage-transform { color: #f0a500; }
.etl-event .stage-load { color: var(--success); }
.etl-event .stage-complete { color: var(--accent); font-weight: bold; }
.etl-event .stage-error { color: #f44336; }

.empty { text-align: center; padding: 3rem; color: var(--text2); }

@media (max-width: 768px) {
    .layout { grid-template-columns: 1fr; }
    .sidebar { position: static; height: auto; display: flex; overflow-x: auto; padding: 0.5rem; }
    .sidebar h2 { display: none; }
    .sidebar nav { display: flex; gap: 0.5rem; }
    .sidebar nav a { white-space: nowrap; }
    .chart-grid { grid-template-columns: 1fr; }
}
"""

BASE_HTML = Template("""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$title - YouTube Shorts Dashboard</title>
    <style>$css</style>
    <script src="https://unpkg.com/htmx.org@2.0.4" integrity="sha384-HGfztofotfshcF7+8n44JQL2oJmowVChPTg48S+jvZoztPfvwD79OC/LTtG6dMp+" crossorigin="anonymous"></script>
    <script src="https://unpkg.com/htmx-ext-ws@2.0.2/ws.js"></script>
</head>
<body>
<div class="layout">
    <aside class="sidebar">
        <h2>YT Shorts</h2>
        <nav>
            <a href="/" $nav_overview>Overview</a>
            <a href="/retention" $nav_retention>Retención</a>
            <a href="/lessons" $nav_lessons>Lecciones</a>
            <a href="/audience" $nav_audience>Audiencia</a>
            <a href="/knowledge" $nav_knowledge>Insights</a>
            <a href="/goals" $nav_goals>Metas</a>
            <a href="/etl" $nav_etl>ETL Live</a>
        </nav>
    </aside>
    <main class="main">
        $content
    </main>
</div>
$scripts
</body>
</html>""")


def _nav_active(page: str, current: str) -> str:
    return 'class="active"' if page == current else ""


def _render_page(title: str, content: str, page: str, scripts: str = "") -> str:
    return BASE_HTML.substitute(
        title=title, css=CSS, content=content,
        nav_overview=_nav_active("overview", page),
        nav_retention=_nav_active("retention", page),
        nav_lessons=_nav_active("lessons", page),
        nav_audience=_nav_active("audience", page),
        nav_knowledge=_nav_active("knowledge", page),
        nav_goals=_nav_active("goals", page),
        nav_etl=_nav_active("etl", page),
        scripts=scripts,
    )


# ---------------------------------------------------------------------------
# Canvas chart helper (vanilla JS)
# ---------------------------------------------------------------------------

CHART_JS = """
function drawBarChart(canvasId, labels, values, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.offsetWidth;
    const h = canvas.height = canvas.offsetHeight || 250;
    ctx.clearRect(0, 0, w, h);

    const max = Math.max(...values, 1);
    const barW = Math.max(8, (w - 60) / labels.length - 4);
    const startX = 50;

    // Y axis
    ctx.strokeStyle = '#2a2a4a'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = h - 30 - (i / 4) * (h - 50);
        ctx.beginPath(); ctx.moveTo(startX, y); ctx.lineTo(w, y); ctx.stroke();
        ctx.fillStyle = '#a0a0a0'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText((max * i / 4).toFixed(1), startX - 5, y + 4);
    }

    // Bars
    labels.forEach((label, i) => {
        const x = startX + i * (barW + 4);
        const barH = (values[i] / max) * (h - 50);
        const y = h - 30 - barH;

        ctx.fillStyle = color || '#e94560';
        ctx.beginPath();
        ctx.roundRect(x, y, barW, barH, 3);
        ctx.fill();

        // Label
        ctx.fillStyle = '#a0a0a0'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
        ctx.save(); ctx.translate(x + barW/2, h - 5); ctx.rotate(-0.5);
        ctx.fillText(label.substring(0, 12), 0, 0);
        ctx.restore();
    });
}

function drawLineChart(canvasId, data, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.offsetWidth;
    const h = canvas.height = canvas.offsetHeight || 250;
    ctx.clearRect(0, 0, w, h);

    if (!data.length) return;
    const max = Math.max(...data, 1);
    const startX = 50; const endX = w - 10;
    const stepX = (endX - startX) / Math.max(1, data.length - 1);

    // Grid
    ctx.strokeStyle = '#2a2a4a'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = h - 30 - (i / 4) * (h - 50);
        ctx.beginPath(); ctx.moveTo(startX, y); ctx.lineTo(w, y); ctx.stroke();
        ctx.fillStyle = '#a0a0a0'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText((max * i / 4).toFixed(0) + '%', startX - 5, y + 4);
    }

    // Line
    ctx.beginPath(); ctx.strokeStyle = color || '#e94560'; ctx.lineWidth = 2;
    data.forEach((v, i) => {
        const x = startX + i * stepX;
        const y = h - 30 - (v / max) * (h - 50);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Area fill
    const lastX = startX + (data.length - 1) * stepX;
    ctx.lineTo(lastX, h - 30); ctx.lineTo(startX, h - 30); ctx.closePath();
    ctx.fillStyle = (color || '#e94560') + '20'; ctx.fill();
}
"""


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def _build_overview(conn) -> str:
    """Build overview page with KPIs and charts."""
    # KPIs
    stats = {}
    for table in ["movies", "quotes", "shorts"]:
        cur = conn.execute(f"SELECT COUNT(*) as n FROM {table}")
        stats[table] = cur.fetchone()["n"]

    cur = conn.execute("""
        SELECT COALESCE(SUM(views), 0) as views,
               COALESCE(SUM(likes), 0) as likes,
               COALESCE(AVG(retention_avg), 0) as ret,
               COALESCE(AVG(engagement_rate), 0) as eng
        FROM analytics WHERE platform = 'youtube'
    """)
    row = cur.fetchone()

    kpis = f"""
    <h1>Dashboard Overview</h1>
    <div class="kpi-grid">
        <div class="kpi-card"><div class="value">{stats['movies']}</div><div class="label">Películas</div></div>
        <div class="kpi-card"><div class="value">{stats['quotes']}</div><div class="label">Quotes</div></div>
        <div class="kpi-card"><div class="value">{stats['shorts']}</div><div class="label">Shorts</div></div>
        <div class="kpi-card"><div class="value">{row['views']:,}</div><div class="label">Total Views</div></div>
        <div class="kpi-card"><div class="value">{row['ret']:.1f}%</div><div class="label">Avg Retention</div></div>
        <div class="kpi-card"><div class="value">{row['eng']:.4f}</div><div class="label">Avg Engagement</div></div>
    </div>
    """

    # Category distribution chart data
    cur = conn.execute("""
        SELECT category, COUNT(*) as n FROM quotes
        WHERE category IS NOT NULL GROUP BY category ORDER BY n DESC
    """)
    cat_data = [(r["category"], r["n"]) for r in cur.fetchall()]
    cat_labels = json.dumps([c[0] for c in cat_data])
    cat_values = json.dumps([c[1] for c in cat_data])

    # Learning type distribution
    cur = conn.execute("""
        SELECT learning_type, COUNT(*) as n FROM quotes
        WHERE learning_type IS NOT NULL GROUP BY learning_type ORDER BY n DESC
    """)
    lt_data = [(r["learning_type"], r["n"]) for r in cur.fetchall()]
    lt_labels = json.dumps([l[0] for l in lt_data])
    lt_values = json.dumps([l[1] for l in lt_data])

    charts = f"""
    <div class="chart-grid">
        <div class="chart-card">
            <h3>Distribución por Categoría</h3>
            <canvas id="catChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>Distribución por Tipo de Aprendizaje</h3>
            <canvas id="ltChart"></canvas>
        </div>
    </div>
    <script>
    {CHART_JS}
    drawBarChart('catChart', {cat_labels}, {cat_values}, '#e94560');
    drawBarChart('ltChart', {lt_labels}, {lt_values}, '#4ecca3');
    </script>
    """

    # Recent shorts table
    cur = conn.execute("""
        SELECT s.title, s.status, s.theme_query, s.created_at,
               a.views, a.likes, a.retention_avg
        FROM shorts s
        LEFT JOIN analytics a ON a.short_id = s.id
        ORDER BY s.created_at DESC LIMIT 10
    """)
    rows = cur.fetchall()
    table_rows = ""
    for r in rows:
        status_class = "tag-success" if r["status"] == "uploaded" else "tag-warning"
        table_rows += f"""<tr>
            <td>{r['title'] or r['theme_query'] or '—'}</td>
            <td><span class="tag {status_class}">{r['status']}</span></td>
            <td>{r['views'] or 0:,}</td>
            <td>{r['retention_avg'] or 0:.1f}%</td>
            <td>{(r['created_at'] or '')[:10]}</td>
        </tr>"""

    table = f"""
    <h3 style="margin-top:1rem">Últimos Shorts</h3>
    <table>
        <thead><tr><th>Título/Query</th><th>Status</th><th>Views</th><th>Retention</th><th>Fecha</th></tr></thead>
        <tbody>{table_rows if table_rows else '<tr><td colspan="5" class="empty">Sin shorts aún</td></tr>'}</tbody>
    </table>
    """

    return kpis + charts + table


def _build_retention_page(conn) -> str:
    """Retention curves and events page."""
    # Get analytics with retention data
    cur = conn.execute("""
        SELECT a.id, a.platform_video_id, a.views, a.retention_avg, a.retention_3s,
               s.title, s.theme_query
        FROM analytics a
        LEFT JOIN shorts s ON a.short_id = s.id
        WHERE a.retention_curve_fetched = 1
        ORDER BY a.retention_avg DESC
        LIMIT 20
    """)
    videos = [dict(r) for r in cur.fetchall()]

    content = "<h1>Curvas de Retención</h1>"

    if not videos:
        return content + '<div class="empty">Sin datos de retención. Ejecuta ex24 primero.</div>'

    # Summary events
    cur = conn.execute("""
        SELECT event_type, COUNT(*) as n, AVG(magnitude) as avg_mag
        FROM retention_events GROUP BY event_type ORDER BY n DESC
    """)
    events = cur.fetchall()

    content += '<div class="kpi-grid">'
    for e in events:
        content += f'<div class="kpi-card"><div class="value">{e["n"]}</div><div class="label">{e["event_type"]}</div></div>'
    content += '</div>'

    # Table with htmx to load individual curves
    content += """
    <table>
        <thead><tr><th>Video</th><th>Views</th><th>Ret Avg</th><th>Hook 3s</th><th>Curva</th></tr></thead>
        <tbody>
    """
    for v in videos:
        title = v["title"] or v["theme_query"] or v["platform_video_id"] or "—"
        content += f"""<tr>
            <td>{title[:40]}</td>
            <td>{v['views']:,}</td>
            <td>{v['retention_avg']:.1f}%</td>
            <td>{v['retention_3s']:.1f}%</td>
            <td><button hx-get="/htmx/retention/{v['id']}" hx-target="#curve-{v['id']}" hx-swap="innerHTML">Ver</button></td>
        </tr>
        <tr><td colspan="5" id="curve-{v['id']}"></td></tr>"""

    content += "</tbody></table>"
    return content


def _build_lessons_page(conn) -> str:
    """Lesson performance + curriculum plan page."""
    # Learning type stats
    cur = conn.execute("""
        SELECT q.learning_type, COUNT(*) as n,
               AVG(a.retention_avg) as avg_ret,
               AVG(a.engagement_rate) as avg_eng
        FROM quotes q
        LEFT JOIN shorts s ON s.quote_ids LIKE '%' || q.id || '%'
        LEFT JOIN analytics a ON a.short_id = s.id
        WHERE q.learning_type IS NOT NULL
        GROUP BY q.learning_type
        ORDER BY avg_ret DESC
    """)
    lt_stats = [dict(r) for r in cur.fetchall()]

    content = "<h1>Lecciones & Curriculum</h1>"

    # Performance table
    content += '<h3>Rendimiento por Tipo de Aprendizaje</h3><table>'
    content += '<thead><tr><th>Tipo</th><th>Quotes</th><th>Ret Avg</th><th>Engagement</th><th>Distribución</th></tr></thead><tbody>'
    max_n = max((s["n"] for s in lt_stats), default=1)
    for s in lt_stats:
        bar_w = max(4, int(s["n"] / max_n * 200))
        ret = f"{s['avg_ret']:.1f}%" if s["avg_ret"] else "—"
        eng = f"{s['avg_eng']:.4f}" if s["avg_eng"] else "—"
        content += f"""<tr>
            <td>{s['learning_type']}</td>
            <td>{s['n']}</td>
            <td>{ret}</td>
            <td>{eng}</td>
            <td><div class="bar" style="width:{bar_w}px"></div></td>
        </tr>"""
    content += '</tbody></table>'

    # Curriculum plan
    cur = conn.execute("""
        SELECT position, suggested_query, target_learning_type,
               target_category, target_emotion, status
        FROM curriculum_plan
        ORDER BY position
        LIMIT 20
    """)
    plan = cur.fetchall()

    content += '<h3 style="margin-top:2rem">Plan de Curriculum</h3>'
    if plan:
        content += '<table><thead><tr><th>#</th><th>Query</th><th>Tipo</th><th>Categoría</th><th>Status</th></tr></thead><tbody>'
        for p in plan:
            status_class = "tag-success" if p["status"] == "completed" else "tag-warning"
            content += f"""<tr>
                <td>{p['position']}</td>
                <td>{p['suggested_query']}</td>
                <td><span class="tag tag-accent">{p['target_learning_type']}</span></td>
                <td>{p['target_category']}</td>
                <td><span class="tag {status_class}">{p['status']}</span></td>
            </tr>"""
        content += '</tbody></table>'
    else:
        content += '<div class="empty">Sin plan de curriculum. Ejecuta ex33 primero.</div>'

    return content


def _build_audience_page(conn) -> str:
    """Demographics and audience segments page."""
    content = "<h1>Audiencia</h1>"

    # Demographics
    cur = conn.execute("""
        SELECT dimension, dimension_value, viewer_percentage
        FROM audience_demographics
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM audience_demographics)
        ORDER BY dimension, viewer_percentage DESC
    """)
    demo = [dict(r) for r in cur.fetchall()]

    if demo:
        # Group by dimension
        by_dim: dict[str, list] = {}
        for d in demo:
            dim = d["dimension"]
            if dim not in by_dim:
                by_dim[dim] = []
            by_dim[dim].append(d)

        for dim, items in by_dim.items():
            content += f'<h3>{dim.replace("_", " ").title()}</h3><table>'
            content += '<thead><tr><th>Valor</th><th>%</th><th></th></tr></thead><tbody>'
            max_pct = max(i["viewer_percentage"] for i in items)
            for i in items:
                bar_w = max(4, int(i["viewer_percentage"] / max(max_pct, 1) * 200))
                content += f"""<tr>
                    <td>{i['dimension_value']}</td>
                    <td>{i['viewer_percentage']:.1f}%</td>
                    <td><div class="bar bar-success" style="width:{bar_w}px"></div></td>
                </tr>"""
            content += '</tbody></table>'
    else:
        content += '<div class="empty">Sin demographics. Ejecuta ex26 primero.</div>'

    # Segments
    cur = conn.execute("SELECT * FROM audience_segments ORDER BY size DESC")
    segments = [dict(r) for r in cur.fetchall()]

    content += '<h3 style="margin-top:2rem">Segmentos de Audiencia (DBSCAN)</h3>'
    if segments:
        content += '<table><thead><tr><th>Segmento</th><th>Tamaño</th><th>Ruido</th><th>Características</th></tr></thead><tbody>'
        for seg in segments:
            chars = ""
            try:
                chars = ", ".join(json.loads(seg.get("characteristics", "[]"))[:3])
            except (json.JSONDecodeError, TypeError):
                chars = str(seg.get("characteristics", ""))[:80]
            content += f"""<tr>
                <td>{seg['segment_name']}</td>
                <td>{seg['size']}</td>
                <td>{seg['noise_count']}</td>
                <td>{chars}</td>
            </tr>"""
        content += '</tbody></table>'
    else:
        content += '<div class="empty">Sin segmentos. Ejecuta ex26 primero.</div>'

    return content


def _build_knowledge_page(conn) -> str:
    """Knowledge base page."""
    cur = conn.execute("""
        SELECT * FROM knowledge_base
        WHERE is_active = 1
        ORDER BY confidence DESC, created_at DESC
        LIMIT 50
    """)
    insights = [dict(r) for r in cur.fetchall()]

    content = "<h1>Knowledge Base</h1>"
    content += f'<p style="color:var(--text2)">{len(insights)} insights activos</p>'

    if not insights:
        return content + '<div class="empty">Sin insights aún. Ejecuta ex21, ex25, ex32.</div>'

    content += '<table><thead><tr><th>Categoría</th><th>Topic</th><th>Título</th><th>Confianza</th><th>Fuente</th></tr></thead><tbody>'
    for i in insights:
        conf_pct = int(i["confidence"] * 100)
        content += f"""<tr>
            <td><span class="tag tag-accent">{i['category']}</span></td>
            <td>{i['topic']}</td>
            <td>{i['title'][:60]}</td>
            <td>{conf_pct}%</td>
            <td>{i['source'] or '—'}</td>
        </tr>"""
    content += '</tbody></table>'
    return content


def _build_goals_page(conn) -> str:
    """Goals and progress page."""
    cur = conn.execute("SELECT * FROM goals ORDER BY status, created_at DESC")
    goals = [dict(r) for r in cur.fetchall()]

    content = "<h1>Metas</h1>"
    if not goals:
        return content + '<div class="empty">Sin metas definidas. Ejecuta ex23 --set-goal.</div>'

    content += '<table><thead><tr><th>Métrica</th><th>Actual</th><th>Meta</th><th>Progreso</th><th>Status</th><th>Deadline</th></tr></thead><tbody>'
    for g in goals:
        progress = round(g["current_value"] / max(g["target_value"], 0.01) * 100, 1)
        bar_w = min(200, max(4, int(progress * 2)))
        bar_color = "bar-success" if progress >= 100 else ""
        status_class = "tag-success" if g["status"] == "achieved" else "tag-warning"
        content += f"""<tr>
            <td>{g['metric']}</td>
            <td>{g['current_value']:.1f}</td>
            <td>{g['target_value']:.1f}</td>
            <td><div class="bar {bar_color}" style="width:{bar_w}px"></div> {progress:.0f}%</td>
            <td><span class="tag {status_class}">{g['status']}</span></td>
            <td>{g['deadline'] or '—'}</td>
        </tr>"""
    content += '</tbody></table>'
    return content


def _build_etl_page() -> str:
    """ETL live monitor with WebSocket."""
    events = get_recent_events(30)

    event_html = ""
    for e in events:
        stage_class = f"stage-{e.get('stage', 'extract')}"
        data_str = json.dumps(e.get("data", {}), ensure_ascii=False)[:120]
        event_html += f'<div class="etl-event"><span class="ts">{e.get("ts", "")[:19]}</span> <span class="{stage_class}">[{e.get("source", "")}:{e.get("stage", "")}]</span> {data_str}</div>'

    content = f"""
    <h1>ETL Monitor <span class="tag tag-success">LIVE</span></h1>
    <div id="etl-log" class="etl-log" hx-ext="ws" ws-connect="/ws">
        <div id="etl-events">{event_html}</div>
    </div>
    <script>
    // WebSocket for live ETL events
    const logEl = document.getElementById('etl-log');
    const eventsEl = document.getElementById('etl-events');
    let ws;
    function connectWS() {{
        ws = new WebSocket('ws://' + window.location.host + '/ws');
        ws.onmessage = function(e) {{
            try {{
                const msg = JSON.parse(e.data);
                if (msg.type === 'catchup' && msg.events) {{
                    msg.events.forEach(addEvent);
                }} else {{
                    addEvent(msg);
                }}
                logEl.scrollTop = logEl.scrollHeight;
            }} catch(err) {{}}
        }};
        ws.onclose = function() {{ setTimeout(connectWS, 3000); }};
    }}
    function addEvent(e) {{
        const div = document.createElement('div');
        div.className = 'etl-event';
        const stageClass = 'stage-' + (e.stage || 'extract');
        const data = JSON.stringify(e.data || {{}}).substring(0, 120);
        div.innerHTML = '<span class="ts">' + (e.ts || '').substring(0,19) + '</span> '
            + '<span class="' + stageClass + '">[' + (e.source||'') + ':' + (e.stage||'') + ']</span> ' + data;
        eventsEl.appendChild(div);
        // Keep last 200 events
        while (eventsEl.children.length > 200) eventsEl.removeChild(eventsEl.firstChild);
    }}
    connectWS();
    </script>
    """
    return content


# ---------------------------------------------------------------------------
# FastAPI app builder
# ---------------------------------------------------------------------------

def build_dashboard_app(settings: Settings):
    """Build the dashboard FastAPI app."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse
    except ImportError:
        raise ImportError("FastAPI required: pip install fastapi uvicorn")

    app = FastAPI(title="YouTube Shorts Dashboard")
    create_ws_endpoint(app)

    def _page(title, content, page, scripts=""):
        return HTMLResponse(_render_page(title, content, page, scripts))

    @app.get("/", response_class=HTMLResponse)
    def overview():
        conn = get_db(settings.data_dir)
        content = _build_overview(conn)
        conn.close()
        return _page("Overview", content, "overview")

    @app.get("/retention", response_class=HTMLResponse)
    def retention():
        conn = get_db(settings.data_dir)
        content = _build_retention_page(conn)
        conn.close()
        return _page("Retención", content, "retention")

    @app.get("/htmx/retention/{analytics_id}", response_class=HTMLResponse)
    def htmx_retention_curve(analytics_id: int):
        """htmx partial: render a single retention curve as canvas."""
        conn = get_db(settings.data_dir)
        cur = conn.execute(
            "SELECT audience_retention FROM retention_curves WHERE analytics_id = ? ORDER BY second",
            (analytics_id,),
        )
        data = [r["audience_retention"] * 100 for r in cur.fetchall()]
        conn.close()

        if not data:
            return HTMLResponse('<div class="empty">Sin datos de curva</div>')

        canvas_id = f"curve_canvas_{analytics_id}"
        data_json = json.dumps(data)
        return HTMLResponse(f"""
        <div class="chart-card" style="margin:0.5rem 0">
            <canvas id="{canvas_id}" style="width:100%;height:150px"></canvas>
        </div>
        <script>{CHART_JS}; drawLineChart('{canvas_id}', {data_json}, '#4ecca3');</script>
        """)

    @app.get("/lessons", response_class=HTMLResponse)
    def lessons():
        conn = get_db(settings.data_dir)
        content = _build_lessons_page(conn)
        conn.close()
        return _page("Lecciones", content, "lessons")

    @app.get("/audience", response_class=HTMLResponse)
    def audience():
        conn = get_db(settings.data_dir)
        content = _build_audience_page(conn)
        conn.close()
        return _page("Audiencia", content, "audience")

    @app.get("/knowledge", response_class=HTMLResponse)
    def knowledge():
        conn = get_db(settings.data_dir)
        content = _build_knowledge_page(conn)
        conn.close()
        return _page("Insights", content, "knowledge")

    @app.get("/goals", response_class=HTMLResponse)
    def goals():
        conn = get_db(settings.data_dir)
        content = _build_goals_page(conn)
        conn.close()
        return _page("Metas", content, "goals")

    @app.get("/etl", response_class=HTMLResponse)
    def etl():
        content = _build_etl_page()
        return _page("ETL Live", content, "etl")

    return app


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> Path:
    log = build_logger("ex28", settings.output_dir / "logs" / "ex28.log")
    tracker = ETLTracker("ex28")

    tracker.extract_start()
    log.info("Starting dashboard on %s:%d", host, port)
    tracker.extract_done({"host": host, "port": port})

    print(f"\n{'='*60}")
    print(f"  YouTube Shorts Dashboard")
    print(f"  http://{host}:{port}")
    print(f"  Pages: / /retention /lessons /audience /knowledge /goals /etl")
    print(f"  WebSocket: ws://{host}:{port}/ws")
    print(f"{'='*60}\n")

    app = build_dashboard_app(settings)

    try:
        import uvicorn
        tracker.complete({"status": "running"})
        uvicorn.run(app, host=host, port=port, log_level="info")
    except ImportError:
        log.error("uvicorn not installed. Install: pip install uvicorn")
        print("ERROR: pip install uvicorn")

    return settings.output_dir / "logs" / "ex28_dashboard.log"
