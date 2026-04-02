"""
ex07 - Buscar escenas por tema usando ChromaDB (busqueda semantica).

Permite armar shorts multi-pelicula buscando por concepto:
  "epic revenge moment" → escenas de venganza de 5 peliculas distintas
  "romantic confession"  → declaraciones romanticas
  "villain monologue"    → monologos de villanos

Tambien puede buscar en SQLite con texto simple si no hay ChromaDB.

Uso:
  python main.py ex07 --query "epic confrontation"
  python main.py ex07 --query "villain speech" --max-results 10
  python main.py ex07 --query "love confession" --unique-movies
"""

import json
from pathlib import Path

from common.config import Settings
from common.db import get_db, get_quotes_with_timestamps
from common.logger import build_logger


def search_chromadb(query: str, data_dir: Path, n_results: int = 15) -> list[dict]:
    """Semantic search using ChromaDB."""
    try:
        import chromadb
    except ImportError:
        return []

    db_path = data_dir / "chromadb"
    if not db_path.exists():
        return []

    client = chromadb.PersistentClient(path=str(db_path))

    try:
        collection = client.get_collection("movie_quotes")
    except Exception:
        return []

    # Filter by viral_score >= 5 if classification data exists
    where_filter = None
    try:
        # Check if any documents have viral_score metadata
        sample = collection.peek(limit=1)
        if sample and sample["metadatas"] and "viral_score" in sample["metadatas"][0]:
            where_filter = {"viral_score": {"$gte": 5}}
    except Exception:
        pass

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where_filter,
    )

    scenes = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0
            scenes.append(
                {
                    "text": doc,
                    "movie_title": meta.get("movie_title", "Unknown"),
                    "movie_id": meta.get("movie_id", 0),
                    "start_ms": meta.get("start_ms", 0),
                    "end_ms": meta.get("end_ms", 0),
                    "character": meta.get("character", ""),
                    "confidence": meta.get("confidence", 0),
                    "semantic_score": round(1 - distance, 3) if distance else 0,
                    "category": meta.get("category", ""),
                    "emotion": meta.get("emotion", ""),
                    "viral_score": meta.get("viral_score", 0),
                    "edit_style": meta.get("edit_style", ""),
                    "scene_type": meta.get("scene_type", ""),
                }
            )
    return scenes


def search_sqlite_simple(query: str, conn, n_results: int = 15) -> list[dict]:
    """Simple text search fallback using SQLite LIKE."""
    words = query.lower().split()
    conditions = " AND ".join(f"LOWER(q.text) LIKE ?" for _ in words)
    params = [f"%{w}%" for w in words]

    cur = conn.execute(
        f"""SELECT q.*, m.title as movie_title
            FROM quotes q
            JOIN movies m ON q.movie_id = m.id
            WHERE q.start_ms IS NOT NULL AND ({conditions})
            ORDER BY q.confidence DESC
            LIMIT ?""",
        params + [n_results],
    )
    return [dict(r) for r in cur.fetchall()]


def filter_for_short(
    scenes: list[dict],
    max_clip_duration_s: int = 6,
    unique_movies: bool = True,
    target_count: int = 5,
) -> list[dict]:
    """
    Filter and select scenes suitable for a multi-clip Short.

    Rules:
      - Each clip <= max_clip_duration_s (default 6s for copyright safety)
      - Prefer diversity: one clip per movie if unique_movies=True
      - Sort by confidence/semantic_score
    """
    # Filter by duration
    valid = []
    for s in scenes:
        duration_s = (s.get("end_ms", 0) - s.get("start_ms", 0)) / 1000
        if 0 < duration_s <= max_clip_duration_s:
            valid.append(s)

    if not valid:
        # Relax duration constraint - take everything
        valid = [s for s in scenes if s.get("start_ms")]

    # Sort by best score
    sort_key = "semantic_score" if valid and "semantic_score" in valid[0] else "confidence"
    valid.sort(key=lambda x: x.get(sort_key, 0), reverse=True)

    # Enforce unique movies if requested
    if unique_movies:
        seen_movies = set()
        filtered = []
        for s in valid:
            movie_key = s.get("movie_title", s.get("movie_id", ""))
            if movie_key not in seen_movies:
                seen_movies.add(movie_key)
                filtered.append(s)
        valid = filtered

    return valid[:target_count]


def generate_short_manifest(
    scenes: list[dict],
    theme: str,
    output_dir: Path,
) -> Path:
    """
    Generate a JSON manifest that the FFmpeg cutting step (future) can consume.

    Output format ready for FFmpeg filter_complex generation.
    """
    manifest = {
        "theme": theme,
        "clips_count": len(scenes),
        "total_duration_ms": sum(s.get("end_ms", 0) - s.get("start_ms", 0) for s in scenes),
        "clips": [],
    }

    for i, scene in enumerate(scenes):
        manifest["clips"].append(
            {
                "index": i,
                "movie_title": scene.get("movie_title", ""),
                "movie_id": scene.get("movie_id", 0),
                "quote": scene["text"][:200],
                "character": scene.get("character", ""),
                "start_ms": scene.get("start_ms", 0),
                "end_ms": scene.get("end_ms", 0),
                "duration_s": round((scene.get("end_ms", 0) - scene.get("start_ms", 0)) / 1000, 2),
                "confidence": scene.get("confidence", 0),
            }
        )

    # Save manifest
    safe_theme = theme.replace(" ", "_").replace("/", "_")[:50]
    manifest_path = output_dir / f"short_manifest_{safe_theme}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


# ── Entry point ───────────────────────────────────────────────────────


def run(
    settings: Settings,
    query: str = "epic movie moment",
    max_results: int = 10,
    unique_movies: bool = True,
) -> Path:
    log = build_logger("ex07", settings.output_dir / "logs" / "ex07.log")
    conn = get_db(settings.data_dir)

    report_lines = ["ex07 - Search Scenes by Theme", "=" * 40, ""]
    report_lines.append(f"Query: \"{query}\"")
    report_lines.append(f"Max results: {max_results}")
    report_lines.append(f"Unique movies: {unique_movies}")
    report_lines.append("")

    # Try ChromaDB first (semantic search)
    log.info(f"Searching for: \"{query}\"")
    scenes = search_chromadb(query, settings.data_dir, n_results=max_results * 2)

    if scenes:
        log.info(f"ChromaDB returned {len(scenes)} results")
        report_lines.append(f"Search engine: ChromaDB (semantic)")
    else:
        # Fallback to SQLite text search
        log.info("ChromaDB not available, using SQLite text search")
        scenes = search_sqlite_simple(query, conn, n_results=max_results * 2)
        report_lines.append(f"Search engine: SQLite (text match)")

    if not scenes:
        report_lines.append("\nNo matching scenes found.")
        report_lines.append("Run ex04 → ex05 → ex06 first to populate the database.")
        report_path = settings.output_dir / "logs" / "ex07_search_report.txt"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")
        conn.close()
        return report_path

    log.info(f"Found {len(scenes)} raw results")
    report_lines.append(f"Raw results: {len(scenes)}")

    # Filter for Short suitability
    selected = filter_for_short(
        scenes,
        max_clip_duration_s=6,
        unique_movies=unique_movies,
        target_count=min(max_results, 5),
    )

    report_lines.append(f"Selected for Short: {len(selected)}")
    report_lines.append("")

    # Display results
    report_lines.append("Selected scenes:")
    report_lines.append("-" * 60)
    total_duration = 0

    for i, s in enumerate(selected):
        duration_s = (s.get("end_ms", 0) - s.get("start_ms", 0)) / 1000
        total_duration += duration_s

        start_fmt = _ms_to_timestamp(s.get("start_ms", 0))
        end_fmt = _ms_to_timestamp(s.get("end_ms", 0))
        score = s.get("semantic_score") or s.get("confidence", 0)

        report_lines.append(f"\n  Clip {i + 1}: {s.get('movie_title', 'Unknown')}")
        report_lines.append(f"    Quote: \"{s['text'][:100]}\"")
        if s.get("character"):
            report_lines.append(f"    Character: {s['character']}")
        report_lines.append(f"    Time: {start_fmt} → {end_fmt} ({duration_s:.1f}s)")
        report_lines.append(f"    Score: {score}")

        log.info(
            f"  Clip {i + 1}: {s.get('movie_title')} @ {start_fmt}-{end_fmt} "
            f"({duration_s:.1f}s) - \"{s['text'][:50]}...\""
        )

    report_lines.append(f"\nTotal Short duration: {total_duration:.1f}s")

    # Generate manifest for FFmpeg
    if selected:
        manifests_dir = settings.output_dir / "manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = generate_short_manifest(selected, query, manifests_dir)
        report_lines.append(f"Manifest saved: {manifest_path}")
        log.info(f"Manifest saved: {manifest_path}")

    report_path = settings.output_dir / "logs" / "ex07_search_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report saved to {report_path}")

    conn.close()
    return report_path


def _ms_to_timestamp(ms: int) -> str:
    s = ms // 1000
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
