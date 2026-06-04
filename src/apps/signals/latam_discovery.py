"""
LatAm Content Discovery: novelas, series y peliculas de cada pais.

Sources:
- TMDb API (free, key in .env): discover TV/movies by country + language
- SensaCine MX RSS: entertainment news in Spanish
- Google Trends (pytrends): trending in CO, MX, AR, CL, PE
- OpenSubtitles: Spanish subtitles for quote extraction

Each country has cultural context that feeds the persona knowledge.
"""

from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)


# ── Country profiles ────────────────────────────────────────────

LATAM_COUNTRIES = {
    "CO": {
        "name": "Colombia",
        "tmdb_code": "CO",
        "lang": "es",
        "google_trends_pn": "colombia",
        "cultural_tags": ["novela", "narco-serie", "comedia", "realismo magico"],
        "iconic_shows": [
            "Yo soy Betty, la fea", "Sin senos sí hay paraíso",
            "Pasión de Gavilanes", "La reina del flow",
            "Pablo Escobar: El patrón del mal", "Café con aroma de mujer",
        ],
        "hashtags": ["#novelascolombianas", "#colombia", "#betylafea", "#rcn", "#caracoltv"],
    },
    "MX": {
        "name": "México",
        "tmdb_code": "MX",
        "lang": "es",
        "google_trends_pn": "mexico",
        "cultural_tags": ["telenovela", "cine de oro", "comedia", "narcotrafic"],
        "iconic_shows": [
            "La Rosa de Guadalupe", "Rebelde", "El Señor de los Cielos",
            "La Casa de las Flores", "Club de Cuervos", "Teresa",
        ],
        "hashtags": ["#telenovelas", "#mexico", "#televisa", "#tvAzteca", "#rebelde"],
    },
    "AR": {
        "name": "Argentina",
        "tmdb_code": "AR",
        "lang": "es",
        "google_trends_pn": "argentina",
        "cultural_tags": ["drama psicologico", "humor acido", "cine independiente", "thriller"],
        "iconic_shows": [
            "El Secreto de sus Ojos", "Relatos Salvajes", "Mujeres Asesinas",
            "Los Simuladores", "Monzón", "El Marginal",
        ],
        "hashtags": ["#cineargentino", "#argentina", "#relatossalvajes", "#telefe", "#eltrece"],
    },
    "CL": {
        "name": "Chile",
        "tmdb_code": "CL",
        "lang": "es",
        "google_trends_pn": "chile",
        "cultural_tags": ["thriller social", "drama politico", "docuficcion"],
        "iconic_shows": [
            "Los 80", "El Reemplazante", "El Club", "Prófugos",
        ],
        "hashtags": ["#serieschilenas", "#chile", "#tvn", "#canal13"],
    },
    "PE": {
        "name": "Perú",
        "tmdb_code": "PE",
        "lang": "es",
        "google_trends_pn": "peru",
        "cultural_tags": ["costumbrismo", "humor popular", "drama familiar"],
        "iconic_shows": [
            "Al Fondo Hay Sitio", "De Vuelta al Barrio", "Soledad",
        ],
        "hashtags": ["#seriesperuanas", "#peru", "#alfondohaysitio", "#americatv"],
    },
    "VE": {
        "name": "Venezuela",
        "tmdb_code": "VE",
        "lang": "es",
        "google_trends_pn": "venezuela",
        "cultural_tags": ["telenovela clasica", "drama", "romance"],
        "iconic_shows": [
            "Acorralada", "Ciudad Bendita", "Cosita Rica",
        ],
        "hashtags": ["#novelasvenezolanas", "#venezuela", "#venevision"],
    },
}


# ── TMDb Discovery ──────────────────────────────────────────────

TMDB_BASE = "https://api.themoviedb.org/3"


def _tmdb_key() -> str:
    return os.getenv("TMDB_API_KEY", "")


def discover_series_by_country(
    country_code: str,
    page: int = 1,
    sort_by: str = "popularity.desc",
    max_results: int = 20,
) -> list[dict]:
    """Discover TV series from a specific LatAm country via TMDb."""
    key = _tmdb_key()
    if not key:
        log.warning("TMDB_API_KEY not set")
        return []

    params = {
        "api_key": key,
        "with_original_language": "es",
        "with_origin_country": country_code,
        "sort_by": sort_by,
        "page": page,
    }

    try:
        resp = requests.get(f"{TMDB_BASE}/discover/tv", params=params, timeout=10)
        if resp.status_code != 200:
            log.warning(f"TMDb discover/tv failed: {resp.status_code}")
            return []

        results = resp.json().get("results", [])[:max_results]
        series = []
        for r in results:
            series.append({
                "tmdb_id": r["id"],
                "title": r.get("name", ""),
                "original_title": r.get("original_name", ""),
                "overview": r.get("overview", ""),
                "first_air_date": r.get("first_air_date", ""),
                "popularity": r.get("popularity", 0),
                "vote_average": r.get("vote_average", 0),
                "vote_count": r.get("vote_count", 0),
                "country": country_code,
                "country_name": LATAM_COUNTRIES.get(country_code, {}).get("name", country_code),
                "type": "tv",
                "poster_path": r.get("poster_path", ""),
            })
        return series

    except Exception as e:
        log.warning(f"TMDb discover failed for {country_code}: {e}")
        return []


def discover_movies_by_country(
    country_code: str,
    page: int = 1,
    max_results: int = 20,
) -> list[dict]:
    """Discover movies from a specific LatAm country via TMDb."""
    key = _tmdb_key()
    if not key:
        return []

    params = {
        "api_key": key,
        "with_original_language": "es",
        "region": country_code,
        "sort_by": "popularity.desc",
        "page": page,
    }

    try:
        resp = requests.get(f"{TMDB_BASE}/discover/movie", params=params, timeout=10)
        results = resp.json().get("results", [])[:max_results]
        return [{
            "tmdb_id": r["id"],
            "title": r.get("title", ""),
            "original_title": r.get("original_title", ""),
            "overview": r.get("overview", ""),
            "release_date": r.get("release_date", ""),
            "popularity": r.get("popularity", 0),
            "vote_average": r.get("vote_average", 0),
            "country": country_code,
            "country_name": LATAM_COUNTRIES.get(country_code, {}).get("name", country_code),
            "type": "movie",
        } for r in results]
    except Exception as e:
        log.warning(f"TMDb movies failed for {country_code}: {e}")
        return []


def get_series_details(tmdb_id: int) -> dict | None:
    """Get full details of a TV series including seasons, cast, and keywords."""
    key = _tmdb_key()
    if not key:
        return None

    try:
        resp = requests.get(
            f"{TMDB_BASE}/tv/{tmdb_id}",
            params={"api_key": key, "append_to_response": "credits,keywords", "language": "es-MX"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        d = resp.json()
        cast = d.get("credits", {}).get("cast", [])[:10]
        creators = d.get("created_by", [])

        return {
            "tmdb_id": tmdb_id,
            "title": d.get("name", ""),
            "overview": d.get("overview", ""),
            "first_air_date": d.get("first_air_date", ""),
            "status": d.get("status", ""),
            "number_of_seasons": d.get("number_of_seasons", 0),
            "number_of_episodes": d.get("number_of_episodes", 0),
            "genres": [g["name"] for g in d.get("genres", [])],
            "networks": [n["name"] for n in d.get("networks", [])],
            "cast": [{"name": c["name"], "character": c.get("character", "")} for c in cast],
            "creators": [c["name"] for c in creators],
            "keywords": [k["name"] for k in d.get("keywords", {}).get("results", [])],
            "vote_average": d.get("vote_average", 0),
            "popularity": d.get("popularity", 0),
        }
    except Exception as e:
        log.warning(f"TMDb details failed for {tmdb_id}: {e}")
        return None


# ── RSS feeds en español ────────────────────────────────────────

LATAM_RSS_FEEDS = {
    "sensacine_mx": "https://www.sensacine.com.mx/rss/noticias.xml",
}


def fetch_latam_headlines(max_per_feed: int = 8) -> list[dict]:
    """Fetch entertainment headlines from Spanish-language RSS feeds."""
    headlines = []

    for source, url in LATAM_RSS_FEEDS.items():
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

                description = re.sub(r'<[^>]+>', '', description)[:300]

                if title:
                    headlines.append({
                        "title": title,
                        "description": description,
                        "source": source,
                        "url": link,
                        "date": pub_date,
                        "lang": "es",
                    })
        except Exception as e:
            log.warning(f"RSS {source} failed: {e}")

    log.info(f"Fetched {len(headlines)} LatAm headlines")
    return headlines


# ── Google Trends LatAm ─────────────────────────────────────────

def fetch_latam_trends(countries: list[str] | None = None) -> list[dict]:
    """Get trending searches in LatAm countries."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.warning("pytrends not installed")
        return []

    countries = countries or ["CO", "MX", "AR", "CL", "PE"]
    all_trends = []

    for code in countries:
        pn = LATAM_COUNTRIES.get(code, {}).get("google_trends_pn", "")
        if not pn:
            continue

        try:
            pytrends = TrendReq(hl='es', tz=300)
            trending = pytrends.trending_searches(pn=pn)

            for term in trending[0].tolist()[:10]:
                all_trends.append({
                    "term": term,
                    "country": code,
                    "country_name": LATAM_COUNTRIES[code]["name"],
                    "source": "google_trends",
                })
        except Exception as e:
            log.warning(f"Google Trends {code} failed: {e}")

    log.info(f"Fetched {len(all_trends)} LatAm trends")
    return all_trends


# ── Theme generation for scheduler ──────────────────────────────

def generate_latam_themes(max_themes: int = 10) -> list[dict]:
    """
    Generate content themes from LatAm sources for the scheduler.
    Mixes: popular series by country + fresh headlines + trending topics.
    """
    themes = []

    # 1. Top series from each country (rotate)
    for code in ["CO", "MX", "AR", "CL", "PE"]:
        series = discover_series_by_country(code, max_results=3)
        for s in series[:2]:
            overview = s.get("overview", "")[:100]
            themes.append({
                "query": s["title"],
                "category": "novela",
                "country": code,
                "country_name": s["country_name"],
                "description": overview,
                "tmdb_id": s["tmdb_id"],
                "type": "tv",
                "source": "tmdb_discover",
            })

    # 2. Headlines
    headlines = fetch_latam_headlines(max_per_feed=5)
    for h in headlines[:5]:
        themes.append({
            "query": re.sub(r'\[.*?\]', '', h["title"]).strip()[:80],
            "category": "noticias",
            "country": "MX",
            "description": h.get("description", "")[:200],
            "source": "rss_sensacine",
        })

    # Deduplicate by title
    seen = set()
    unique = []
    for t in themes:
        key = t["query"].lower()[:30]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique[:max_themes]


# ── Build context for narration prompt ──────────────────────────

def build_latam_context(
    series_title: str,
    country_code: str = "",
    tmdb_id: int = 0,
) -> dict:
    """
    Build the full context dict for build_narration_prompt() for a LatAm show.
    Fetches details from TMDb and enriches with cultural context.
    """
    context = {
        "series_title": series_title,
        "arc_name": "",
        "creator": "",
        "summary": "",
        "cross_refs": [],
    }

    # Get TMDb details if we have an ID
    if tmdb_id:
        details = get_series_details(tmdb_id)
        if details:
            context["series_title"] = details.get("title", series_title)
            context["summary"] = details.get("overview", "")
            context["arc_name"] = f"Temporada 1-{details.get('number_of_seasons', '?')}"

            # Creator = country + creators/networks
            country_name = LATAM_COUNTRIES.get(country_code, {}).get("name", country_code)
            creators = ", ".join(details.get("creators", []))
            networks = ", ".join(details.get("networks", []))
            context["creator"] = f"{country_name} — {networks}" + (f" (creador: {creators})" if creators else "")

            # Cast for cross-references
            cast = details.get("cast", [])[:5]
            if cast:
                cast_text = ", ".join(f"{c['name']} como {c['character']}" for c in cast if c.get("character"))
                context["summary"] += f"\nReparto: {cast_text}"

            # Genres
            genres = details.get("genres", [])
            if genres:
                context["summary"] += f"\nGéneros: {', '.join(genres)}"

    # Cultural cross-references
    country_info = LATAM_COUNTRIES.get(country_code, {})
    if country_info:
        iconic = country_info.get("iconic_shows", [])
        # Find shows from the same country to compare
        same_country = [s for s in iconic if s.lower() != series_title.lower()]
        if same_country:
            context["cross_refs"].append(
                f"Del mismo país ({country_info['name']}): {', '.join(same_country[:3])}"
            )

        # Add cultural tags
        tags = country_info.get("cultural_tags", [])
        if tags:
            context["cross_refs"].append(
                f"Tradición de {country_info['name']}: {', '.join(tags)}"
            )

    # Add a cross-country comparison
    other_countries = [c for c in LATAM_COUNTRIES if c != country_code]
    if other_countries:
        other = LATAM_COUNTRIES[other_countries[0]]
        context["cross_refs"].append(
            f"Para comparar: las series de {other['name']} ({', '.join(other['iconic_shows'][:2])})"
        )

    return context
