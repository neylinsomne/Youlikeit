"""
Culture Feed: scrapes trending celebrity news, entertainment, and pop culture.
Feeds Pop Oracle persona with fresh cross-reference material.

Sources (all free):
- Google Trends (already integrated via pytrends)
- NewsAPI (100 req/day free)
- Wikipedia API (unlimited, no key)
- TMDb Person API (already have key)
- RSS feeds (Variety, Deadline, Entertainment Weekly)

Usage:
    python -m common.culture_feed --full    # Run full pipeline
    python -m common.culture_feed --trends  # Just Google Trends
    python -m common.culture_feed --news    # Just news headlines
"""
import os
import re
import json
import sqlite3
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

log = logging.getLogger(__name__)

# RSS feeds for entertainment news
RSS_FEEDS = {
    "variety": "https://variety.com/feed/",
    "deadline": "https://deadline.com/feed/",
    "screenrant": "https://screenrant.com/feed/",
    "cbr": "https://www.cbr.com/feed/",  # comics/manga news
    "animenewsnetwork": "https://www.animenewsnetwork.com/all/rss.xml",
}

# Celebrity/entertainment related Google Trends categories
CULTURE_TRENDS_QUERIES = [
    "celebrity news today",
    "trending actor",
    "movie controversy",
    "anime trending",
    "manga release",
    "director interview",
    "oscar nominations",
    "celebrity scandal",
]


def fetch_rss_headlines(max_per_feed: int = 5) -> list:
    """Fetch entertainment headlines from RSS feeds."""
    import requests

    headlines = []
    for source, url in RSS_FEEDS.items():
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "YouLikeIt/1.0 (content research bot)"
            })
            if resp.status_code != 200:
                continue

            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:max_per_feed]

            for item in items:
                title = item.findtext("title", "").strip()
                description = item.findtext("description", "").strip()
                link = item.findtext("link", "").strip()
                pub_date = item.findtext("pubDate", "").strip()

                # Clean HTML from description
                description = re.sub(r'<[^>]+>', '', description)[:300]

                if title:
                    headlines.append({
                        "title": title,
                        "description": description,
                        "source": source,
                        "url": link,
                        "date": pub_date,
                        "type": "entertainment_news",
                    })

        except Exception as e:
            log.warning(f"RSS {source} failed: {e}")

    log.info(f"Fetched {len(headlines)} RSS headlines from {len(RSS_FEEDS)} feeds")
    return headlines


def fetch_trending_people() -> list:
    """Get trending people/celebrities from Google Trends."""
    try:
        from pytrends.request import TrendReq

        pytrends = TrendReq(hl='en-US', tz=300)
        trending = pytrends.trending_searches(pn='united_states')

        people = []
        for term in trending[0].tolist()[:20]:
            # Filter: likely a person name (2+ words, capitalized)
            words = term.split()
            if len(words) >= 2 and all(w[0].isupper() for w in words if w[0].isalpha()):
                people.append({
                    "name": term,
                    "type": "trending_person",
                    "source": "google_trends",
                })

        log.info(f"Found {len(people)} trending people")
        return people

    except Exception as e:
        log.warning(f"Google Trends failed: {e}")
        return []


def fetch_wikipedia_context(person_name: str) -> Optional[dict]:
    """Get quick Wikipedia summary for a person."""
    import requests

    try:
        resp = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/" +
                            quote_plus(person_name.replace(" ", "_")),
                            timeout=10)
        if resp.status_code != 200:
            return None

        data = resp.json()
        return {
            "name": person_name,
            "summary": data.get("extract", "")[:500],
            "description": data.get("description", ""),
            "thumbnail": data.get("thumbnail", {}).get("source", ""),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        }
    except Exception:
        return None


def fetch_tmdb_person(person_name: str) -> Optional[dict]:
    """Get actor/director info from TMDb."""
    import requests

    api_key = os.getenv("TMDB_API_KEY", "")
    if not api_key:
        return None

    try:
        resp = requests.get("https://api.themoviedb.org/3/search/person",
                            params={"api_key": api_key, "query": person_name},
                            timeout=10)
        results = resp.json().get("results", [])
        if not results:
            return None

        person = results[0]
        person_id = person["id"]

        # Get full details
        details = requests.get(f"https://api.themoviedb.org/3/person/{person_id}",
                               params={"api_key": api_key, "append_to_response": "movie_credits"},
                               timeout=10).json()

        # Get top movies
        movies = details.get("movie_credits", {}).get("cast", [])
        top_movies = sorted(movies, key=lambda m: m.get("popularity", 0), reverse=True)[:5]

        return {
            "name": details.get("name", person_name),
            "known_for": details.get("known_for_department", ""),
            "biography": (details.get("biography") or "")[:300],
            "birthday": details.get("birthday"),
            "top_movies": [{"title": m["title"], "year": m.get("release_date", "")[:4],
                            "character": m.get("character", "")} for m in top_movies],
        }
    except Exception:
        return None


def fetch_newsapi(query: str = "celebrity entertainment", max_results: int = 10) -> list:
    """Fetch news from NewsAPI (100 req/day free)."""
    import requests

    api_key = os.getenv("NEWSAPI_KEY", "")
    if not api_key:
        log.info("NEWSAPI_KEY not set, skipping NewsAPI")
        return []

    try:
        resp = requests.get("https://newsapi.org/v2/everything",
                            params={
                                "apiKey": api_key,
                                "q": query,
                                "language": "en",
                                "sortBy": "publishedAt",
                                "pageSize": max_results,
                            }, timeout=10)

        articles = resp.json().get("articles", [])
        return [{
            "title": a.get("title", ""),
            "description": (a.get("description") or "")[:300],
            "source": a.get("source", {}).get("name", ""),
            "url": a.get("url", ""),
            "date": a.get("publishedAt", ""),
            "type": "news",
        } for a in articles]

    except Exception as e:
        log.warning(f"NewsAPI failed: {e}")
        return []


def generate_cross_refs_from_culture(
    conn: sqlite3.Connection,
    headlines: list,
    persona_id: int = 3,  # Pop Oracle by default
    gemini_key: str = "",
) -> int:
    """Use Gemini to connect culture news to existing works in the DB."""
    import requests

    if not gemini_key:
        gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        log.warning("No Gemini key, skipping cross-ref generation")
        return 0

    # Get existing works
    works = conn.execute("SELECT DISTINCT source_work FROM cross_references UNION SELECT title FROM movies LIMIT 20").fetchall()
    work_titles = [w[0] for w in works if w[0]]

    if not work_titles:
        work_titles = ["Berserk", "One Piece", "Death Note", "Attack on Titan"]

    count = 0
    for headline in headlines[:5]:  # Max 5 to save API calls
        title = headline.get("title", "")
        desc = headline.get("description", "")
        if not title:
            continue

        prompt = f"""Given this entertainment/celebrity news headline, find ONE witty connection to a manga, anime, or movie.

NEWS: {title}
CONTEXT: {desc[:200]}

WORKS TO CONNECT TO (pick one): {', '.join(work_titles[:10])}

Return JSON (no markdown):
{{
    "work": "the work you're connecting to",
    "connection": "1-2 sentence witty Pop Oracle style connection (conversational, funny, shareable)",
    "relevance": 0.5-1.0
}}

If no good connection exists, return {{"work": null}}"""

        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.7}},
                timeout=20)

            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r'```json?\s*', '', text).strip().rstrip('`')
            result = json.loads(text)

            if result.get("work") and result.get("connection"):
                # Save as persona knowledge with expiry
                expires = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""INSERT INTO persona_knowledge
                    (persona_id, knowledge_type, content, source, relevance_score, expires_at)
                    VALUES (?, 'trend', ?, ?, ?, ?)""",
                    (persona_id, f"[{title}] {result['connection']}", headline.get("source", "rss"),
                     result.get("relevance", 0.7), expires))
                count += 1
                log.info(f"  Cross-ref: {title[:40]} → {result['work']}")

        except Exception as e:
            log.warning(f"Gemini cross-ref failed for '{title[:30]}': {e}")

    conn.commit()
    log.info(f"Generated {count} culture cross-references")
    return count


def run_culture_pipeline(db_path: str = "data/shorts_pipeline.db", full: bool = True):
    """Run the complete culture feed pipeline."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Ensure tables exist
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS culture_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            source TEXT,
            url TEXT,
            event_type TEXT,
            related_people TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        );
    """)

    log.info("=== Culture Feed Pipeline ===")

    # 1. RSS headlines
    headlines = fetch_rss_headlines(max_per_feed=5)

    # 2. Trending people
    people = fetch_trending_people()

    # 3. Wikipedia context for trending people
    enriched_people = []
    for p in people[:5]:
        wiki = fetch_wikipedia_context(p["name"])
        tmdb = fetch_tmdb_person(p["name"])
        enriched_people.append({
            **p,
            "wiki": wiki,
            "tmdb": tmdb,
        })

    # 4. NewsAPI (if key available)
    news = fetch_newsapi("celebrity movie anime", max_results=10)
    headlines.extend(news)

    # 5. Save to DB
    expires = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    for h in headlines:
        conn.execute("""INSERT OR IGNORE INTO culture_events
            (title, description, source, url, event_type, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (h["title"], h.get("description", ""), h.get("source", ""),
             h.get("url", ""), h.get("type", "news"), expires))

    for p in enriched_people:
        bio = ""
        if p.get("wiki"):
            bio = p["wiki"].get("summary", "")[:200]
        if p.get("tmdb"):
            movies = ", ".join(m["title"] for m in p["tmdb"].get("top_movies", [])[:3])
            bio += f" Known for: {movies}"

        conn.execute("""INSERT OR IGNORE INTO culture_events
            (title, description, source, event_type, related_people, expires_at)
            VALUES (?, ?, 'google_trends', 'trending_person', ?, ?)""",
            (f"Trending: {p['name']}", bio, p["name"], expires))

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM culture_events WHERE expires_at > datetime('now')").fetchone()[0]
    log.info(f"Culture events in DB: {total}")

    # 6. Generate cross-refs (uses Gemini, ~5 calls)
    if full:
        generate_cross_refs_from_culture(conn, headlines)

    conn.close()
    log.info("=== Culture Feed Complete ===")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    db = sys.argv[-1] if len(sys.argv) > 2 else "data/shorts_pipeline.db"

    if "--trends" in sys.argv:
        people = fetch_trending_people()
        for p in people:
            print(f"  {p['name']}")
    elif "--news" in sys.argv:
        headlines = fetch_rss_headlines()
        for h in headlines[:10]:
            print(f"  [{h['source']:15s}] {h['title'][:80]}")
    else:
        run_culture_pipeline(db, full="--full" in sys.argv)
