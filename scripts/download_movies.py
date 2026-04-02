"""Download movies for the pipeline — picks torrents with most seeders."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from common.movie_source import _tmdb_to_imdb, _get_torrentio_magnets, _qbit_add_torrent
from common.db import get_db
from pathlib import Path
import re

conn = get_db(Path(os.getenv("DATA_DIR", "data")))

# Movies from DB + classics
cur = conn.execute("""
    SELECT DISTINCT m.tmdb_id, m.title, m.year
    FROM movies m
    JOIN quotes q ON q.movie_id = m.id
    WHERE q.start_ms IS NOT NULL
    ORDER BY m.popularity DESC
    LIMIT 10
""")
db_movies = [(r["tmdb_id"], r["title"], r["year"]) for r in cur.fetchall()]

classics = [
    (550, "Fight Club", 1999),
    (680, "Pulp Fiction", 1994),
    (155, "The Dark Knight", 2008),
    (603, "The Matrix", 1999),
    (278, "The Shawshank Redemption", 1994),
]

seen = set()
movies = []
for tmdb_id, title, year in db_movies + classics:
    if tmdb_id not in seen:
        seen.add(tmdb_id)
        movies.append((tmdb_id, title, year or 0))

print(f"Processing {len(movies)} movies...\n")

added = 0
for tmdb_id, title, year in movies:
    imdb = _tmdb_to_imdb(tmdb_id)
    if not imdb:
        print(f"  SKIP {title}: no IMDB ID")
        continue

    magnets = _get_torrentio_magnets(imdb)
    if not magnets:
        print(f"  SKIP {title} ({imdb}): no torrents")
        continue

    # Parse seeders from title (format: "👤 249")
    for m in magnets:
        seeder_match = re.search(r"👤\s*(\d+)", m["title"])
        m["seeders"] = int(seeder_match.group(1)) if seeder_match else 0

    # Sort by seeders (most first), prefer 720p/1080p, 0.5-8GB max
    good = [m for m in magnets
            if m["quality"] in ("720p", "1080p")
            and 0.5 < m["size_gb"] < 8
            and m["seeders"] > 5]

    if not good:
        good = [m for m in magnets
                if m["quality"] in ("720p", "1080p")
                and 0.3 < m["size_gb"] < 10
                and m["seeders"] > 0]

    if not good:
        print(f"  SKIP {title}: no torrents with seeders")
        continue

    good.sort(key=lambda x: x["seeders"], reverse=True)
    best = good[0]

    ok = _qbit_add_torrent(best["magnet"])
    symbol = "OK" if ok else "FAIL"
    q = best["quality"]
    s = best["size_gb"]
    seeds = best["seeders"]
    h = best["hash"][:12]
    print(f"  [{symbol}] {title} ({year}) | {q} | {s:.1f}GB | {seeds} seeds | {h}")
    if ok:
        added += 1

print(f"\nAdded {added} movies to qBittorrent")
print("Monitor: http://localhost:8090")
conn.close()
