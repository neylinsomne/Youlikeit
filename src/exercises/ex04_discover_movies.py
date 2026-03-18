"""
ex04 - Descubrir peliculas y frases celebres.

Flujo:
  1. TMDB API → peliculas por modo (trending, genero, año, rating, etc.)
  2. Wikiquote → frases famosas por pelicula (scraping, gratis)
  3. Guarda todo en SQLite

Modos de descubrimiento:
  trending    → lo mas popular esta semana
  classics    → mejor puntuadas de todos los tiempos
  genre       → por genero (action, drama, thriller, horror, scifi, comedy, crime)
  year        → peliculas de un año especifico
  now_playing → en cines ahora (hype actual)
  search      → buscar por nombre

Uso:
  python main.py ex04                                    # trending + classics
  python main.py ex04 --mode genre --genre action
  python main.py ex04 --mode genre --genre horror
  python main.py ex04 --mode year --year 1994
  python main.py ex04 --mode search --query "tarantino"
  python main.py ex04 --mode now_playing
  python main.py ex04 --max-movies 30
"""

import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from common.config import Settings
from common.db import get_db, insert_movie, insert_quote
from common.logger import build_logger

TMDB_BASE = "https://api.themoviedb.org/3"
WIKIQUOTE_API = "https://en.wikiquote.org/w/api.php"

# TMDB genre IDs
GENRE_MAP = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "scifi": 878,
    "sci-fi": 878,
    "thriller": 53,
    "war": 10752,
    "western": 37,
}


# ── TMDB helpers ─────────────────────────────────────────────────────


def _parse_tmdb_results(data: dict) -> list[dict]:
    """Parse TMDB API response into our movie format."""
    movies = []
    for m in data.get("results", []):
        movies.append(
            {
                "tmdb_id": m["id"],
                "title": m.get("title", ""),
                "original_title": m.get("original_title", ""),
                "year": int(m.get("release_date", "0000")[:4]) if m.get("release_date") else None,
                "genre": json.dumps(m.get("genre_ids", [])),
                "popularity": m.get("popularity", 0),
                "poster_path": m.get("poster_path", ""),
                "overview": m.get("overview", ""),
            }
        )
    return movies


def _tmdb_get(api_key: str, endpoint: str, params: dict, pages: int = 2) -> list[dict]:
    """Generic paginated TMDB GET request."""
    movies = []
    for page in range(1, pages + 1):
        params["page"] = page
        params["api_key"] = api_key
        params.setdefault("language", "en-US")
        resp = requests.get(f"{TMDB_BASE}{endpoint}", params=params, timeout=15)
        if resp.status_code != 200:
            break
        movies.extend(_parse_tmdb_results(resp.json()))
    return movies


# ── Discovery modes ──────────────────────────────────────────────────


def discover_trending(api_key: str, pages: int = 2) -> list[dict]:
    """Trending this week."""
    return _tmdb_get(api_key, "/trending/movie/week", {}, pages)


def discover_classics(api_key: str, pages: int = 2) -> list[dict]:
    """Top rated classics (high vote count + high rating)."""
    return _tmdb_get(
        api_key,
        "/discover/movie",
        {"sort_by": "vote_count.desc", "vote_average.gte": 7},
        pages,
    )


def discover_by_genre(api_key: str, genre: str, pages: int = 2) -> list[dict]:
    """Movies by genre, sorted by popularity."""
    genre_id = GENRE_MAP.get(genre.lower())
    if not genre_id:
        return []
    return _tmdb_get(
        api_key,
        "/discover/movie",
        {
            "with_genres": str(genre_id),
            "sort_by": "vote_count.desc",
            "vote_average.gte": 6.5,
        },
        pages,
    )


def discover_by_year(api_key: str, year: int, pages: int = 2) -> list[dict]:
    """Best movies from a specific year."""
    return _tmdb_get(
        api_key,
        "/discover/movie",
        {
            "primary_release_year": year,
            "sort_by": "vote_count.desc",
            "vote_average.gte": 6,
        },
        pages,
    )


def discover_now_playing(api_key: str, pages: int = 2) -> list[dict]:
    """Currently in theaters."""
    return _tmdb_get(api_key, "/movie/now_playing", {}, pages)


def discover_search(api_key: str, query: str, pages: int = 2) -> list[dict]:
    """Search by title, actor, director, etc."""
    return _tmdb_get(api_key, "/search/movie", {"query": query}, pages)


# ── Wikiquote: frases celebres ────────────────────────────────────────


def fetch_wikiquote_quotes(movie_title: str) -> list[dict]:
    """Scrape quotes from Wikiquote for a given movie title."""
    headers = {"User-Agent": "ShortsAutomation/1.0 (educational project)"}

    # Step 1: search for the page
    resp = requests.get(
        WIKIQUOTE_API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": f"{movie_title} film",
            "srnamespace": "0",
            "srlimit": "3",
            "format": "json",
        },
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        return []

    results = resp.json().get("query", {}).get("search", [])
    if not results:
        return []

    # Pick best match - prefer exact title match
    page_title = results[0]["title"]
    for r in results:
        if r["title"].lower().strip() == movie_title.lower().strip():
            page_title = r["title"]
            break

    # Step 2: get page content as parsed HTML
    resp = requests.get(
        WIKIQUOTE_API,
        params={
            "action": "parse",
            "page": page_title,
            "prop": "text",
            "format": "json",
        },
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        return []

    parse_data = resp.json().get("parse", {})
    html = parse_data.get("text", {}).get("*", "")
    if not html:
        return []

    # Step 3: extract quotes from the HTML
    soup = BeautifulSoup(html, "html.parser")
    quotes = []

    for li in soup.find_all("li"):
        text = li.get_text(strip=True)

        if len(text) < 10 or len(text) > 500:
            continue

        if any(skip in text.lower() for skip in ["external links", "see also", "wikipedia", "category:", "[edit]"]):
            continue

        # Try to extract character name from bold text
        character = None
        bold = li.find("b")
        if bold:
            char_text = bold.get_text(strip=True)
            if len(char_text) < 40 and ":" in text:
                character = char_text.rstrip(":")

        clean_text = re.sub(r"\s+", " ", text).strip()
        if character and clean_text.startswith(character):
            clean_text = clean_text[len(character):].lstrip(":").strip()

        if len(clean_text) >= 10:
            quotes.append(
                {
                    "text": clean_text[:500],
                    "character_name": character,
                }
            )

    return quotes


# ── Entry point ───────────────────────────────────────────────────────


def run(
    settings: Settings,
    max_movies: int = 10,
    tmdb_api_key: str = "",
    mode: str = "trending",
    genre: str = "",
    year: int = 0,
    query: str = "",
) -> Path:
    log = build_logger("ex04", settings.output_dir / "logs" / "ex04.log")
    conn = get_db(settings.data_dir)

    if not tmdb_api_key:
        import os
        tmdb_api_key = os.getenv("TMDB_API_KEY", "")

    report_lines = ["ex04 - Discover Movies & Quotes", "=" * 40, ""]
    report_lines.append(f"Mode: {mode}")

    # ── Phase 1: discover movies ──
    all_movies = []
    if tmdb_api_key:
        if mode == "trending":
            log.info("Fetching trending movies...")
            all_movies.extend(discover_trending(tmdb_api_key))
            log.info("Fetching popular classics...")
            all_movies.extend(discover_classics(tmdb_api_key))

        elif mode == "genre":
            if not genre:
                log.error(f"Use --genre with one of: {', '.join(sorted(GENRE_MAP.keys()))}")
                report_lines.append(f"ERROR: --genre required. Options: {', '.join(sorted(GENRE_MAP.keys()))}")
                report_path = settings.output_dir / "logs" / "ex04_discover_report.txt"
                report_path.write_text("\n".join(report_lines), encoding="utf-8")
                conn.close()
                return report_path
            log.info(f"Fetching {genre} movies...")
            all_movies.extend(discover_by_genre(tmdb_api_key, genre, pages=3))
            report_lines.append(f"Genre: {genre}")

        elif mode == "year":
            if not year:
                log.error("Use --year YYYY")
                report_lines.append("ERROR: --year required (e.g. --year 1994)")
                report_path = settings.output_dir / "logs" / "ex04_discover_report.txt"
                report_path.write_text("\n".join(report_lines), encoding="utf-8")
                conn.close()
                return report_path
            log.info(f"Fetching best movies from {year}...")
            all_movies.extend(discover_by_year(tmdb_api_key, year, pages=3))
            report_lines.append(f"Year: {year}")

        elif mode == "now_playing":
            log.info("Fetching movies currently in theaters...")
            all_movies.extend(discover_now_playing(tmdb_api_key))

        elif mode == "search":
            if not query:
                log.error("Use --query 'search term'")
                report_lines.append("ERROR: --query required for search mode")
                report_path = settings.output_dir / "logs" / "ex04_discover_report.txt"
                report_path.write_text("\n".join(report_lines), encoding="utf-8")
                conn.close()
                return report_path
            log.info(f"Searching for: {query}...")
            all_movies.extend(discover_search(tmdb_api_key, query, pages=2))
            report_lines.append(f"Search: {query}")

        elif mode == "all":
            log.info("Fetching from ALL sources...")
            all_movies.extend(discover_trending(tmdb_api_key))
            all_movies.extend(discover_classics(tmdb_api_key))
            all_movies.extend(discover_now_playing(tmdb_api_key))
            for g in ["action", "thriller", "crime", "drama", "scifi", "horror"]:
                all_movies.extend(discover_by_genre(tmdb_api_key, g, pages=1))

        else:
            log.error(f"Unknown mode: {mode}. Use: trending, genre, year, now_playing, search, all")
            report_lines.append(f"ERROR: Unknown mode '{mode}'")
            report_path = settings.output_dir / "logs" / "ex04_discover_report.txt"
            report_path.write_text("\n".join(report_lines), encoding="utf-8")
            conn.close()
            return report_path

        log.info(f"  Total raw results: {len(all_movies)}")
    else:
        log.warning("No TMDB_API_KEY found. Using fallback list of iconic movies.")
        fallback = [
            {"tmdb_id": 238, "title": "The Godfather", "year": 1972},
            {"tmdb_id": 680, "title": "Pulp Fiction", "year": 1994},
            {"tmdb_id": 278, "title": "The Shawshank Redemption", "year": 1994},
            {"tmdb_id": 155, "title": "The Dark Knight", "year": 2008},
            {"tmdb_id": 13, "title": "Forrest Gump", "year": 1994},
            {"tmdb_id": 550, "title": "Fight Club", "year": 1999},
            {"tmdb_id": 603, "title": "The Matrix", "year": 1999},
            {"tmdb_id": 120, "title": "The Lord of the Rings: The Fellowship of the Ring", "year": 2001},
            {"tmdb_id": 11, "title": "Star Wars", "year": 1977},
            {"tmdb_id": 274, "title": "The Silence of the Lambs", "year": 1991},
            {"tmdb_id": 769, "title": "GoodFellas", "year": 1990},
            {"tmdb_id": 497, "title": "The Green Mile", "year": 1999},
            {"tmdb_id": 389, "title": "12 Angry Men", "year": 1957},
            {"tmdb_id": 240, "title": "The Godfather Part II", "year": 1974},
            {"tmdb_id": 424, "title": "Schindler's List", "year": 1993},
        ]
        for f in fallback:
            f.setdefault("original_title", f["title"])
            f.setdefault("genre", "[]")
            f.setdefault("popularity", 100)
            f.setdefault("poster_path", "")
            f.setdefault("overview", "")
        all_movies = fallback

    # Deduplicate by tmdb_id
    seen_ids = set()
    unique_movies = []
    for m in all_movies:
        if m["tmdb_id"] not in seen_ids:
            seen_ids.add(m["tmdb_id"])
            unique_movies.append(m)
    all_movies = unique_movies[:max_movies]

    # Save to DB
    movie_count = 0
    for m in all_movies:
        insert_movie(conn, **m)
        movie_count += 1

    log.info(f"Saved {movie_count} movies to database")
    report_lines.append(f"Movies discovered: {movie_count}")
    report_lines.append("")

    # Show what was found
    report_lines.append("Movies found:")
    for i, m in enumerate(all_movies):
        year_str = m.get("year", "?")
        report_lines.append(f"  {i+1}. {m['title']} ({year_str})")

    report_lines.append("")

    # ── Phase 2: scrape quotes from Wikiquote ──
    log.info("Scraping quotes from Wikiquote...")
    total_quotes = 0

    for m in all_movies:
        title = m["title"]
        log.info(f"  Wikiquote: {title}")

        cur = conn.execute("SELECT id FROM movies WHERE tmdb_id = ?", (m["tmdb_id"],))
        row = cur.fetchone()
        if not row:
            continue
        movie_id = row["id"]

        # Check if we already have quotes for this movie
        cur = conn.execute(
            "SELECT COUNT(*) as cnt FROM quotes WHERE movie_id = ? AND source = 'wikiquote'",
            (movie_id,),
        )
        if cur.fetchone()["cnt"] > 0:
            log.info(f"    Already have quotes, skipping")
            continue

        quotes = fetch_wikiquote_quotes(title)
        for q in quotes[:30]:
            insert_quote(
                conn,
                movie_id=movie_id,
                text=q["text"],
                character_name=q.get("character_name"),
                start_ms=None,
                end_ms=None,
                source="wikiquote",
                confidence=0,
            )
            total_quotes += 1

        log.info(f"    Extracted {len(quotes[:30])} quotes")

    report_lines.append(f"Quotes extracted: {total_quotes}")
    report_lines.append("")

    # ── Summary ──
    cur = conn.execute("SELECT COUNT(*) as cnt FROM movies")
    report_lines.append(f"Total movies in DB: {cur.fetchone()['cnt']}")
    cur = conn.execute("SELECT COUNT(*) as cnt FROM quotes")
    report_lines.append(f"Total quotes in DB: {cur.fetchone()['cnt']}")
    cur = conn.execute("SELECT COUNT(*) as cnt FROM quotes WHERE start_ms IS NOT NULL")
    report_lines.append(f"Quotes with timestamps: {cur.fetchone()['cnt']}")

    report_path = settings.output_dir / "logs" / "ex04_discover_report.txt"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    log.info(f"Report saved to {report_path}")

    conn.close()
    return report_path
