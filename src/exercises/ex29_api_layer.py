"""
ex29 - API REST unificada con auth por token, roles y paginación.

Endpoints:
  GET  /api/movies          - Listar películas (paginado)
  GET  /api/quotes          - Listar quotes (filtros: category, emotion, learning_type)
  GET  /api/shorts          - Listar shorts (filtro: status)
  GET  /api/analytics       - Métricas de videos
  GET  /api/analytics/:id/retention - Curva de retención de un video
  GET  /api/knowledge       - Knowledge base (insights)
  GET  /api/curriculum      - Plan de curriculum
  GET  /api/goals           - Metas activas
  GET  /api/segments        - Segmentos de audiencia
  GET  /api/ab-tests        - A/B tests
  GET  /api/demographics    - Demographics
  GET  /api/status          - Estado del pipeline
  POST /api/auth/token      - Obtener token con username
  WS   /ws                  - WebSocket para progreso ETL en tiempo real

Auth: Token-based con secrets.token_hex(). Roles: admin, reviewer, agent.
Paginación: ?page=1&per_page=20
Filtros: ?category=villain&emotion=anger&learning_type=ethics

Zero dependencias externas al proyecto (usa FastAPI ya en requirements).

Uso:
  python src/main.py ex29
  python src/main.py ex29 --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger
from common.websocket_hub import ETLTracker, create_ws_endpoint, get_recent_events


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_or_create_token(conn, username: str) -> dict:
    """Get existing valid token or create new one."""
    # Check existing valid token
    cur = conn.execute("""
        SELECT ut.token, ut.expires_at, u.role, u.display_name
        FROM user_tokens ut
        JOIN users u ON ut.user_id = u.id
        WHERE u.username = ?
          AND (ut.expires_at IS NULL OR ut.expires_at > datetime('now'))
        ORDER BY ut.created_at DESC
        LIMIT 1
    """, (username,))
    row = cur.fetchone()
    if row:
        return {
            "token": row["token"],
            "expires_at": row["expires_at"],
            "role": row["role"],
            "display_name": row["display_name"],
        }

    # Create user if not exists
    cur = conn.execute("SELECT id, role, display_name FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    if not user:
        conn.execute(
            "INSERT INTO users (username, role, display_name) VALUES (?, 'reviewer', ?)",
            (username, username),
        )
        conn.commit()
        cur = conn.execute("SELECT id, role, display_name FROM users WHERE username = ?", (username,))
        user = cur.fetchone()

    # Generate token
    token = secrets.token_hex(32)
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    conn.execute(
        "INSERT INTO user_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
        (user["id"], token, expires),
    )
    conn.commit()

    return {
        "token": token,
        "expires_at": expires,
        "role": user["role"],
        "display_name": user["display_name"],
    }


def _validate_token(conn, token: str) -> dict | None:
    """Validate a bearer token. Returns user info or None."""
    cur = conn.execute("""
        SELECT u.id, u.username, u.role, u.display_name
        FROM user_tokens ut
        JOIN users u ON ut.user_id = u.id
        WHERE ut.token = ?
          AND (ut.expires_at IS NULL OR ut.expires_at > datetime('now'))
    """, (token,))
    row = cur.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def _paginate(query: str, params: tuple, conn, page: int = 1, per_page: int = 20) -> dict:
    """Execute a query with pagination. Returns {items, page, per_page, total}."""
    # Count total
    count_query = f"SELECT COUNT(*) as total FROM ({query})"
    total = conn.execute(count_query, params).fetchone()["total"]

    # Apply pagination
    offset = (page - 1) * per_page
    paginated_query = f"{query} LIMIT ? OFFSET ?"
    cur = conn.execute(paginated_query, (*params, per_page, offset))
    items = [dict(r) for r in cur.fetchall()]

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page,
    }


# ---------------------------------------------------------------------------
# FastAPI app builder
# ---------------------------------------------------------------------------

def build_app(settings: Settings):
    """Build the FastAPI application with all endpoints."""
    try:
        from fastapi import FastAPI, HTTPException, Query, Request, Depends
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError("FastAPI is required. Install: pip install fastapi uvicorn")

    app = FastAPI(
        title="YouTube Shorts Pipeline API",
        description="API unificada para el pipeline de automatización de YouTube Shorts",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # WebSocket endpoint for real-time ETL progress
    create_ws_endpoint(app)

    def get_conn():
        conn = get_db(settings.data_dir)
        try:
            yield conn
        finally:
            conn.close()

    def get_current_user(request: Request, conn=Depends(get_conn)):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(401, "Missing Bearer token. POST /api/auth/token first.")
        token = auth[7:]
        user = _validate_token(conn, token)
        if not user:
            raise HTTPException(401, "Invalid or expired token")
        return user

    # ── Auth ──

    @app.post("/api/auth/token")
    def create_token(request_body: dict, conn=Depends(get_conn)):
        username = request_body.get("username", "").strip()
        if not username:
            raise HTTPException(400, "username is required")
        result = _get_or_create_token(conn, username)
        return result

    # ── Movies ──

    @app.get("/api/movies")
    def list_movies(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        search: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if search:
            query = "SELECT * FROM movies WHERE title LIKE ? OR original_title LIKE ? ORDER BY popularity DESC"
            params = (f"%{search}%", f"%{search}%")
        else:
            query = "SELECT * FROM movies ORDER BY popularity DESC"
            params = ()
        return _paginate(query, params, conn, page, per_page)

    # ── Quotes ──

    @app.get("/api/quotes")
    def list_quotes(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        category: str = "",
        emotion: str = "",
        learning_type: str = "",
        has_timestamps: bool | None = None,
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
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
        if has_timestamps is True:
            conditions.append("q.start_ms IS NOT NULL")
        elif has_timestamps is False:
            conditions.append("q.start_ms IS NULL")

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT q.*, m.title as movie_title
            FROM quotes q
            JOIN movies m ON q.movie_id = m.id
            WHERE {where}
            ORDER BY q.viral_score DESC, q.confidence DESC
        """
        return _paginate(query, tuple(params), conn, page, per_page)

    # ── Shorts ──

    @app.get("/api/shorts")
    def list_shorts(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        status: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if status:
            query = "SELECT * FROM shorts WHERE status = ? ORDER BY created_at DESC"
            params = (status,)
        else:
            query = "SELECT * FROM shorts ORDER BY created_at DESC"
            params = ()
        return _paginate(query, params, conn, page, per_page)

    # ── Analytics ──

    @app.get("/api/analytics")
    def list_analytics(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        sort_by: str = "views",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        allowed_sorts = {"views", "likes", "engagement_rate", "retention_avg", "impressions", "scraped_at"}
        sort_col = sort_by if sort_by in allowed_sorts else "views"
        query = f"""
            SELECT a.*, s.title as short_title, s.theme_query
            FROM analytics a
            LEFT JOIN shorts s ON a.short_id = s.id
            ORDER BY a.{sort_col} DESC
        """
        return _paginate(query, (), conn, page, per_page)

    @app.get("/api/analytics/{analytics_id}/retention")
    def get_retention(
        analytics_id: int,
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        # Retention curve
        cur = conn.execute("""
            SELECT second, audience_retention, quote_id, category, edit_style
            FROM retention_curves
            WHERE analytics_id = ?
            ORDER BY second
        """, (analytics_id,))
        curve = [dict(r) for r in cur.fetchall()]

        # Events
        cur = conn.execute("""
            SELECT event_type, second_start, second_end, magnitude, content_at_event
            FROM retention_events
            WHERE analytics_id = ?
            ORDER BY second_start
        """, (analytics_id,))
        events = [dict(r) for r in cur.fetchall()]

        return {"analytics_id": analytics_id, "curve": curve, "events": events}

    # ── Knowledge Base ──

    @app.get("/api/knowledge")
    def list_knowledge(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        topic: str = "",
        category: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        conditions = ["is_active = 1"]
        params: list = []
        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if category:
            conditions.append("category = ?")
            params.append(category)
        where = " AND ".join(conditions)
        query = f"SELECT * FROM knowledge_base WHERE {where} ORDER BY confidence DESC"
        return _paginate(query, tuple(params), conn, page, per_page)

    # ── Curriculum ──

    @app.get("/api/curriculum")
    def list_curriculum(
        status: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if status:
            cur = conn.execute(
                "SELECT * FROM curriculum_plan WHERE status = ? ORDER BY position",
                (status,),
            )
        else:
            cur = conn.execute("SELECT * FROM curriculum_plan ORDER BY position")
        return [dict(r) for r in cur.fetchall()]

    # ── Goals ──

    @app.get("/api/goals")
    def list_goals(
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        cur = conn.execute("SELECT * FROM goals ORDER BY status, created_at DESC")
        return [dict(r) for r in cur.fetchall()]

    # ── Segments ──

    @app.get("/api/segments")
    def list_segments(
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        cur = conn.execute("SELECT * FROM audience_segments ORDER BY size DESC")
        return [dict(r) for r in cur.fetchall()]

    # ── A/B Tests ──

    @app.get("/api/ab-tests")
    def list_ab_tests(
        status: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if status:
            cur = conn.execute(
                "SELECT * FROM ab_tests WHERE status = ? ORDER BY started_at DESC",
                (status,),
            )
        else:
            cur = conn.execute("SELECT * FROM ab_tests ORDER BY started_at DESC")
        return [dict(r) for r in cur.fetchall()]

    # ── Demographics ──

    @app.get("/api/demographics")
    def list_demographics(
        dimension: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if dimension:
            cur = conn.execute(
                "SELECT * FROM audience_demographics WHERE dimension = ? ORDER BY snapshot_date DESC, viewer_percentage DESC",
                (dimension,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM audience_demographics ORDER BY snapshot_date DESC, viewer_percentage DESC LIMIT 200"
            )
        return [dict(r) for r in cur.fetchall()]

    # ── Pipeline Status ──

    @app.get("/api/status")
    def pipeline_status(conn=Depends(get_conn)):
        """Public endpoint - no auth required. Pipeline health overview."""
        stats = {}

        for table in ["movies", "quotes", "shorts", "analytics"]:
            cur = conn.execute(f"SELECT COUNT(*) as n FROM {table}")
            stats[table] = cur.fetchone()["n"]

        cur = conn.execute("""
            SELECT COALESCE(SUM(views), 0) as total_views,
                   COALESCE(AVG(engagement_rate), 0) as avg_engagement,
                   COALESCE(AVG(retention_avg), 0) as avg_retention
            FROM analytics WHERE platform = 'youtube'
        """)
        row = cur.fetchone()
        stats["total_views"] = row["total_views"]
        stats["avg_engagement"] = round(row["avg_engagement"], 4)
        stats["avg_retention"] = round(row["avg_retention"], 2)

        # Recent ETL events
        stats["recent_events"] = get_recent_events(10)

        return stats

    # ── Audit Log ──

    @app.get("/api/audit")
    def list_audit(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=50),
        entity_type: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if user["role"] != "admin":
            raise HTTPException(403, "Admin role required for audit log")
        if entity_type:
            query = "SELECT * FROM audit_log WHERE entity_type = ? ORDER BY created_at DESC"
            params = (entity_type,)
        else:
            query = "SELECT * FROM audit_log ORDER BY created_at DESC"
            params = ()
        return _paginate(query, params, conn, page, per_page)

    # --- Pipeline execution (trigger from frontend) ---

    @app.post("/api/pipeline/run")
    def run_pipeline(
        request: dict,
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        """Trigger a pipeline run from the frontend."""
        import subprocess, json, threading
        pipeline = request.get("pipeline", "manga")
        params = request.get("params", {})

        # Record the run
        cur = conn.execute(
            """INSERT INTO pipeline_runs (pipeline, trigger, params)
               VALUES (?, 'frontend', ?)""",
            (pipeline, json.dumps(params)),
        )
        conn.commit()
        run_id = cur.lastrowid

        # Build command
        cmd_parts = ["python", "src/main.py"]
        if pipeline == "manga":
            cmd_parts += ["ex36", "--media-type", params.get("media_type", "all"),
                         "--max-movies", str(params.get("max_series", 15))]
        elif pipeline == "movies":
            cmd_parts += ["ex04", "--max-movies", str(params.get("max_movies", 12)),
                         "--mode", params.get("mode", "trending")]
        elif pipeline == "learn":
            cmd_parts += ["ex31", "--batch-size", "50"]

        def _run_in_background(run_id, cmd_parts, data_dir):
            import sqlite3
            c = sqlite3.connect(str(data_dir / "shorts_pipeline.db"))
            try:
                subprocess.run(cmd_parts, capture_output=True, timeout=300)
                c.execute("UPDATE pipeline_runs SET status='completed', finished_at=CURRENT_TIMESTAMP WHERE id=?", (run_id,))
            except Exception as e:
                c.execute("UPDATE pipeline_runs SET status='failed', finished_at=CURRENT_TIMESTAMP WHERE id=?", (run_id,))
            c.commit()
            c.close()

        t = threading.Thread(target=_run_in_background, args=(run_id, cmd_parts, settings.data_dir))
        t.daemon = True
        t.start()

        return {"run_id": run_id, "pipeline": pipeline, "status": "started"}

    @app.get("/api/pipeline/runs")
    def list_pipeline_runs(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=50),
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        return _paginate(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC",
            (), conn, page, per_page,
        )

    # --- Clip Library ---

    @app.get("/api/clips")
    def list_clips(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=50),
        category: str = "",
        source_type: str = "",
        search: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        """List clips from the library with optional filters."""
        conditions = []
        params = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if source_type:
            conditions.append("source_type = ?")
            params.append(source_type)
        if search:
            conditions.append("(title LIKE ? OR description LIKE ? OR tags LIKE ?)")
            params.extend([f"%{search}%"] * 3)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return _paginate(
            f"SELECT * FROM clip_library{where} ORDER BY times_used DESC, created_at DESC",
            tuple(params), conn, page, per_page,
        )

    @app.get("/api/clips/{clip_id}/usage")
    def clip_usage(clip_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
        """Show which shorts used this clip."""
        cur = conn.execute(
            """SELECT sc.*, s.title as short_title, s.status as short_status
               FROM short_clips sc
               JOIN shorts s ON sc.short_id = s.id
               WHERE sc.clip_id = ?
               ORDER BY sc.created_at DESC""",
            (clip_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    @app.get("/api/clips/search")
    def search_clips_semantic(
        q: str = Query("", description="Semantic search query"),
        limit: int = Query(10, ge=1, le=50),
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        """Semantic search across clip library using ChromaDB."""
        if not q:
            return []
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(settings.data_dir / "chroma"))
            collection = client.get_or_create_collection("clip_library")
            results = collection.query(query_texts=[q], n_results=limit)
            clip_ids = [int(cid) for cid in (results.get("ids", [[]])[0])]
            if not clip_ids:
                return []
            placeholders = ",".join("?" * len(clip_ids))
            cur = conn.execute(
                f"SELECT * FROM clip_library WHERE id IN ({placeholders})",
                clip_ids,
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            # Fallback to text search
            cur = conn.execute(
                """SELECT * FROM clip_library
                   WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?
                   ORDER BY times_used DESC LIMIT ?""",
                (f"%{q}%", f"%{q}%", f"%{q}%", limit),
            )
            return [dict(r) for r in cur.fetchall()]

    # --- Manga-specific endpoints ---

    @app.get("/api/manga/series")
    def list_manga_series(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=50),
        media_type: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if media_type:
            return _paginate(
                "SELECT * FROM manga_series WHERE media_type = ? ORDER BY composite_score DESC",
                (media_type,), conn, page, per_page,
            )
        return _paginate(
            "SELECT * FROM manga_series ORDER BY composite_score DESC",
            (), conn, page, per_page,
        )

    @app.get("/api/manga/quotes")
    def list_manga_quotes(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=50),
        category: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        if category:
            return _paginate(
                """SELECT mq.*, ms.title as series_title
                   FROM manga_quotes mq JOIN manga_series ms ON mq.series_id = ms.id
                   WHERE mq.category = ? ORDER BY mq.viral_score DESC""",
                (category,), conn, page, per_page,
            )
        return _paginate(
            """SELECT mq.*, ms.title as series_title
               FROM manga_quotes mq JOIN manga_series ms ON mq.series_id = ms.id
               ORDER BY mq.viral_score DESC""",
            (), conn, page, per_page,
        )

    return app


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> Path:
    log = build_logger("ex29", settings.output_dir / "logs" / "ex29.log")
    tracker = ETLTracker("ex29")

    tracker.extract_start()
    log.info("Starting API server on %s:%d", host, port)
    tracker.extract_done({"host": host, "port": port})

    # Generate a default admin token for convenience
    conn = get_db(settings.data_dir)
    admin_token = _get_or_create_token(conn, "admin")
    conn.close()

    log.info("Admin token: %s", admin_token["token"])
    print(f"\n{'='*60}")
    print(f"  YouTube Shorts Pipeline API")
    print(f"  http://{host}:{port}")
    print(f"  Docs: http://{host}:{port}/docs")
    print(f"  WebSocket: ws://{host}:{port}/ws")
    print(f"  Admin token: {admin_token['token']}")
    print(f"{'='*60}\n")

    app = build_app(settings)

    try:
        import uvicorn
        tracker.complete({"status": "running"})
        uvicorn.run(app, host=host, port=port, log_level="info")
    except ImportError:
        log.error("uvicorn not installed. Install: pip install uvicorn")
        print("ERROR: pip install uvicorn")

    out = settings.output_dir / "logs" / "ex29_api.log"
    return out
