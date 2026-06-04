"""
TMDb Enriched: detailed metadata + LLM-powered iconic moment detection.

Goes beyond basic TMDb data to extract:
- Full cast with photos and character names
- User reviews (for quote material)
- Similar/recommended series (for cross-references)
- Season-by-season breakdown (for arc-specific content)
- LLM-identified iconic moments from synopsis (for targeted clips)

Usage:
    from integrations.tmdb_enriched import get_enriched_series, detect_iconic_moments

    data = get_enriched_series(tmdb_id=85552)  # "Yo Soy Betty, la Fea"
    moments = detect_iconic_moments(data, lang="es")
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import requests

log = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/"


def _key() -> str:
    return os.getenv("TMDB_API_KEY", "")


# ── Enriched series data ────────────────────────────────────────

def get_enriched_series(tmdb_id: int, lang: str = "es-MX") -> dict | None:
    """Get comprehensive series data from TMDb."""
    key = _key()
    if not key:
        return None

    try:
        resp = requests.get(
            f"{TMDB_BASE}/tv/{tmdb_id}",
            params={
                "api_key": key,
                "language": lang,
                "append_to_response": "credits,reviews,recommendations,similar,keywords,content_ratings,images",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        d = resp.json()

        # Parse cast with photos
        cast = []
        for c in d.get("credits", {}).get("cast", [])[:15]:
            cast.append({
                "name": c.get("name", ""),
                "character": c.get("character", ""),
                "photo": f"{TMDB_IMG}w185{c['profile_path']}" if c.get("profile_path") else None,
                "popularity": c.get("popularity", 0),
                "order": c.get("order", 99),
            })

        # Parse crew (directors, writers)
        crew = []
        for c in d.get("credits", {}).get("crew", []):
            if c.get("job") in ("Director", "Creator", "Writer", "Executive Producer"):
                crew.append({
                    "name": c.get("name", ""),
                    "job": c.get("job", ""),
                    "photo": f"{TMDB_IMG}w185{c['profile_path']}" if c.get("profile_path") else None,
                })

        # Parse reviews
        reviews = []
        for r in d.get("reviews", {}).get("results", [])[:5]:
            content = r.get("content", "")[:500]
            reviews.append({
                "author": r.get("author", ""),
                "rating": r.get("author_details", {}).get("rating"),
                "content": content,
                "created_at": r.get("created_at", ""),
            })

        # Parse recommendations + similar
        recommendations = []
        for r in d.get("recommendations", {}).get("results", [])[:8]:
            recommendations.append({
                "tmdb_id": r["id"],
                "title": r.get("name", ""),
                "overview": r.get("overview", "")[:200],
                "vote_average": r.get("vote_average", 0),
                "poster": f"{TMDB_IMG}w342{r['poster_path']}" if r.get("poster_path") else None,
            })

        similar = []
        for s in d.get("similar", {}).get("results", [])[:8]:
            similar.append({
                "tmdb_id": s["id"],
                "title": s.get("name", ""),
                "overview": s.get("overview", "")[:200],
                "vote_average": s.get("vote_average", 0),
            })

        # Seasons
        seasons = []
        for s in d.get("seasons", []):
            if s.get("season_number", 0) > 0:  # Skip specials
                seasons.append({
                    "season_number": s["season_number"],
                    "name": s.get("name", ""),
                    "episode_count": s.get("episode_count", 0),
                    "overview": s.get("overview", ""),
                    "air_date": s.get("air_date", ""),
                    "poster": f"{TMDB_IMG}w342{s['poster_path']}" if s.get("poster_path") else None,
                })

        return {
            "tmdb_id": tmdb_id,
            "title": d.get("name", ""),
            "original_title": d.get("original_name", ""),
            "overview": d.get("overview", ""),
            "tagline": d.get("tagline", ""),
            "first_air_date": d.get("first_air_date", ""),
            "last_air_date": d.get("last_air_date", ""),
            "status": d.get("status", ""),
            "number_of_seasons": d.get("number_of_seasons", 0),
            "number_of_episodes": d.get("number_of_episodes", 0),
            "genres": [g["name"] for g in d.get("genres", [])],
            "networks": [n["name"] for n in d.get("networks", [])],
            "production_countries": [c["name"] for c in d.get("production_countries", [])],
            "vote_average": d.get("vote_average", 0),
            "vote_count": d.get("vote_count", 0),
            "popularity": d.get("popularity", 0),
            "poster": f"{TMDB_IMG}w780{d['poster_path']}" if d.get("poster_path") else None,
            "backdrop": f"{TMDB_IMG}w1280{d['backdrop_path']}" if d.get("backdrop_path") else None,
            "keywords": [k["name"] for k in d.get("keywords", {}).get("results", [])],
            "cast": cast,
            "crew": crew,
            "reviews": reviews,
            "recommendations": recommendations,
            "similar": similar,
            "seasons": seasons,
        }

    except Exception as e:
        log.warning(f"TMDb enriched failed for {tmdb_id}: {e}")
        return None


def get_season_episodes(tmdb_id: int, season_number: int, lang: str = "es-MX") -> list[dict]:
    """Get episode-level details for a specific season."""
    key = _key()
    if not key:
        return []

    try:
        resp = requests.get(
            f"{TMDB_BASE}/tv/{tmdb_id}/season/{season_number}",
            params={"api_key": key, "language": lang},
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        d = resp.json()
        episodes = []
        for ep in d.get("episodes", []):
            episodes.append({
                "episode_number": ep.get("episode_number", 0),
                "name": ep.get("name", ""),
                "overview": ep.get("overview", ""),
                "air_date": ep.get("air_date", ""),
                "vote_average": ep.get("vote_average", 0),
                "still": f"{TMDB_IMG}w780{ep['still_path']}" if ep.get("still_path") else None,
            })
        return episodes

    except Exception as e:
        log.warning(f"TMDb season failed: {e}")
        return []


# ── LLM-powered iconic moment detection ────────────────────────

def detect_iconic_moments(
    series_data: dict,
    lang: str = "es",
    max_moments: int = 8,
) -> list[dict]:
    """
    Use LLM to identify the most iconic/viral-worthy moments from a series.

    Reads the TMDb synopsis, reviews, and season data to identify moments
    that would make great short-form video content.
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return _detect_moments_heuristic(series_data, lang)

    title = series_data.get("title", "")
    overview = series_data.get("overview", "")
    genres = ", ".join(series_data.get("genres", []))
    countries = ", ".join(series_data.get("production_countries", []))

    # Build season/episode context
    season_context = ""
    for s in series_data.get("seasons", [])[:5]:
        season_context += f"\nTemporada {s['season_number']}: {s.get('overview', '')[:200]}"

    # Build review quotes
    review_context = ""
    for r in series_data.get("reviews", [])[:3]:
        review_context += f"\n- {r['content'][:150]}"

    lang_instruction = "Responde COMPLETAMENTE en español." if lang == "es" else "Respond in English."

    prompt = f"""Analiza esta serie/novela y identifica los {max_moments} momentos más icónicos,
virales o emocionalmente impactantes que servirían para crear videos cortos (YouTube Shorts / TikTok).

{lang_instruction}

SERIE: {title}
PAÍS: {countries}
GÉNEROS: {genres}
SINOPSIS: {overview}

TEMPORADAS:
{season_context}

OPINIONES DEL PÚBLICO:
{review_context}

CAST PRINCIPAL: {', '.join(c['name'] + ' como ' + c['character'] for c in series_data.get('cast', [])[:5])}

Para cada momento, indica:
1. Qué sucede (descripción breve)
2. Por qué es viral/icónico
3. Emoción dominante
4. Quote o frase famosa de ese momento (real o probable)
5. En qué temporada/episodio aproximado ocurre

Devuelve JSON (sin markdown):
[
  {{
    "moment": "descripción del momento",
    "why_iconic": "por qué funcionaría como short",
    "emotion": "dark|epic|tragic|hopeful|shock",
    "quote": "frase icónica del momento",
    "season": 1,
    "episode_approx": 15,
    "virality_score": 0.9
  }}
]"""

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.6},
            },
            timeout=30,
        )

        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"```json?\s*", "", text).strip().rstrip("`")
        moments = json.loads(text)

        if isinstance(moments, list):
            log.info(f"Detected {len(moments)} iconic moments for '{title}'")
            return moments[:max_moments]

    except Exception as e:
        log.warning(f"LLM moment detection failed: {e}")

    return _detect_moments_heuristic(series_data, lang)


def _detect_moments_heuristic(series_data: dict, lang: str) -> list[dict]:
    """Fallback moment detection without LLM — uses keywords and patterns."""
    moments = []
    title = series_data.get("title", "")
    overview = series_data.get("overview", "")
    cast = series_data.get("cast", [])

    # Generate moments from genres + overview keywords
    keyword_moments = {
        "traición": {"emotion": "dark", "why": "Las traiciones generan reacción fuerte"},
        "amor": {"emotion": "hopeful", "why": "Romance siempre conecta emocionalmente"},
        "muerte": {"emotion": "tragic", "why": "Momentos de pérdida son virales"},
        "secreto": {"emotion": "dark", "why": "Revelaciones de secretos generan suspenso"},
        "venganza": {"emotion": "epic", "why": "La venganza es uno de los temas más populares"},
        "transformación": {"emotion": "epic", "why": "Los makeovers y transformaciones son adictivos"},
        "sacrificio": {"emotion": "tragic", "why": "El sacrificio por otros siempre conmueve"},
        "reencuentro": {"emotion": "hopeful", "why": "Los reencuentros generan alegría viral"},
    } if lang == "es" else {
        "betrayal": {"emotion": "dark", "why": "Betrayals generate strong reactions"},
        "love": {"emotion": "hopeful", "why": "Romance always connects emotionally"},
        "death": {"emotion": "tragic", "why": "Moments of loss go viral"},
        "secret": {"emotion": "dark", "why": "Secret reveals create suspense"},
        "revenge": {"emotion": "epic", "why": "Revenge is one of the most popular themes"},
    }

    lower_overview = overview.lower()
    for keyword, meta in keyword_moments.items():
        if keyword in lower_overview:
            moments.append({
                "moment": f"Momento de {keyword} en {title}",
                "why_iconic": meta["why"],
                "emotion": meta["emotion"],
                "quote": "",
                "season": 1,
                "episode_approx": 1,
                "virality_score": 0.6,
            })

    # Add character-based moments
    if cast and len(cast) >= 2:
        moments.append({
            "moment": f"El enfrentamiento entre {cast[0]['character']} y {cast[1]['character']}" if lang == "es"
                      else f"The confrontation between {cast[0]['character']} and {cast[1]['character']}",
            "why_iconic": "Conflictos entre protagonistas son memorables",
            "emotion": "epic",
            "quote": "",
            "season": 1,
            "episode_approx": 1,
            "virality_score": 0.7,
        })

    return moments[:5]
