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


from typing import Optional
def _validate_token(conn, token: str) -> Optional[dict]:
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
    from fastapi import FastAPI, HTTPException, Query, Request, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

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
        import sqlite3
        db_path = settings.data_dir / "shorts_pipeline.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        from common.db import SCHEMA
        conn.executescript(SCHEMA)
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
        has_timestamps: Optional[bool] = None,
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

    # --- Trending Music (ytmusicapi) ---

    @app.get("/api/music/trending")
    def get_trending_music(country: str = "CO", query: str = "", limit: int = 15):
        """Get trending songs with YouTube links."""
        try:
            from ytmusicapi import YTMusic
            yt = YTMusic()
            if query:
                results = yt.search(query, filter="songs", limit=limit)
            else:
                results = yt.search(f"trending songs {country} 2026", filter="songs", limit=limit)

            songs = []
            for r in results[:limit]:
                artists = ", ".join(a["name"] for a in r.get("artists", []))
                vid = r.get("videoId", "")
                songs.append({
                    "title": r.get("title", ""),
                    "artist": artists,
                    "duration": r.get("duration", ""),
                    "youtube_url": f"https://youtube.com/watch?v={vid}" if vid else "",
                    "youtube_music_url": f"https://music.youtube.com/watch?v={vid}" if vid else "",
                    "video_id": vid,
                    "thumbnail": r.get("thumbnails", [{}])[-1].get("url", "") if r.get("thumbnails") else "",
                    "album": r.get("album", {}).get("name", "") if r.get("album") else "",
                })
            return {"songs": songs, "country": country, "query": query}
        except Exception as e:
            import traceback; traceback.print_exc()
            return {"songs": [], "error": str(e)}

    # --- Serve static files (videos, images, panels) ---

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    @app.get("/api/files/{file_path:path}")
    def serve_file(file_path: str):
        """Serve output files (videos, images, panels)."""
        # Try direct path first (file_path may include outputs/ or data/)
        candidates = [
            Path(file_path),  # direct relative path
            Path(settings.output_dir) / file_path,
            Path(settings.data_dir) / file_path,
        ]
        # Strip leading outputs/ or data/ if already in file_path
        stripped = file_path
        for prefix in ("outputs/", "data/"):
            if file_path.startswith(prefix):
                stripped = file_path[len(prefix):]
                break
        candidates.append(Path(settings.output_dir) / stripped)
        candidates.append(Path(settings.data_dir) / stripped)

        for full in candidates:
            if full.exists() and full.is_file():
                media_type = None
                suffix = full.suffix.lower()
                if suffix == ".mp4":
                    media_type = "video/mp4"
                elif suffix in (".jpg", ".jpeg"):
                    media_type = "image/jpeg"
                elif suffix in (".png",):
                    media_type = "image/png"
                elif suffix in (".webp",):
                    media_type = "image/webp"
                elif suffix in (".wav",):
                    media_type = "audio/wav"
                return FileResponse(str(full), media_type=media_type)
        raise HTTPException(404, f"File not found: {file_path}")

    # --- Review endpoints ---

    @app.get("/api/review")
    def list_review_items(
        status: str = "",
        conn=Depends(get_conn),
        user=Depends(get_current_user),
    ):
        """List generated Shorts pending review."""
        conditions = []
        params = []
        if status:
            conditions.append("s.status = ?")
            params.append(status)
        else:
            conditions.append("s.status IN ('rendered','pending_review','draft')")

        where = " AND ".join(conditions) if conditions else "1=1"
        cur = conn.execute(f"""
            SELECT s.*, GROUP_CONCAT(sc.clip_id) as clip_ids
            FROM shorts s
            LEFT JOIN short_clips sc ON s.id = sc.short_id
            WHERE {where}
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    @app.post("/api/review/{short_id}/approve")
    def approve_short(short_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
        conn.execute("UPDATE shorts SET status='approved' WHERE id=?", (short_id,))
        conn.commit()
        return {"id": short_id, "status": "approved"}

    @app.post("/api/review/{short_id}/reject")
    def reject_short(short_id: int, body: dict, conn=Depends(get_conn), user=Depends(get_current_user)):
        reason = body.get("reason", "")
        conn.execute("UPDATE shorts SET status='rejected' WHERE id=?", (short_id,))
        conn.commit()
        return {"id": short_id, "status": "rejected", "reason": reason}

    @app.post("/api/review/{short_id}/issues")
    def add_issue(short_id: int, body: dict, conn=Depends(get_conn), user=Depends(get_current_user)):
        """Add a quality issue to a short."""
        issue_type = body.get("type", "other")
        start_s = body.get("start_s", 0)
        end_s = body.get("end_s", 0)
        note = body.get("note", "")
        conn.execute(
            """INSERT INTO short_issues (short_id, issue_type, start_s, end_s, note, reported_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (short_id, issue_type, start_s, end_s, note, user.get("username", "unknown")),
        )
        conn.commit()
        return {"short_id": short_id, "type": issue_type, "status": "added"}

    @app.get("/api/review/{short_id}/issues")
    def list_issues(short_id: int, conn=Depends(get_conn), user=Depends(get_current_user)):
        cur = conn.execute(
            "SELECT * FROM short_issues WHERE short_id = ? ORDER BY start_s",
            (short_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    # --- Home / Dashboard summary ---

    @app.get("/api/home")
    def home_dashboard(conn=Depends(get_conn)):
        """Public dashboard summary — no auth needed."""
        stats = {}
        for table in ["movies", "quotes", "shorts", "manga_series", "manga_quotes"]:
            try:
                cur = conn.execute(f"SELECT COUNT(*) as n FROM {table}")
                stats[table] = cur.fetchone()["n"]
            except Exception:
                stats[table] = 0

        # Clip library count
        try:
            cur = conn.execute("SELECT COUNT(*) as n FROM clip_library")
            stats["clips"] = cur.fetchone()["n"]
        except Exception:
            stats["clips"] = 0

        # Pipeline runs
        try:
            cur = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 10"
            )
            stats["recent_runs"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            stats["recent_runs"] = []

        # Analytics summary
        try:
            cur = conn.execute("""
                SELECT COALESCE(SUM(views),0) as views,
                       COALESCE(SUM(likes),0) as likes,
                       COALESCE(AVG(engagement_rate),0) as avg_engagement
                FROM analytics
            """)
            row = cur.fetchone()
            stats["total_views"] = row["views"]
            stats["total_likes"] = row["likes"]
            stats["avg_engagement"] = round(row["avg_engagement"], 4)
        except Exception:
            stats["total_views"] = 0
            stats["total_likes"] = 0
            stats["avg_engagement"] = 0

        return stats

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
