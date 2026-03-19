"""
ex17 - Estrategia de publicacion por video.

Cruza:
  - Video generado (ex11/ex16)
  - Grafo de tendencias (ex13)
  - Growth pack (ex08)
  - Clasificacion del video (ex10)
  - Historial de reviews (ex15)

Genera una estrategia de publicacion personalizada POR VIDEO,
incluyendo titulo, hashtags, cancion recomendada, y horarios.

Uso:
  python src/main.py ex17 --query "villain monologue"
  python src/main.py ex17 --query "epic fight" --platform both
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from common.config import Settings
from common.db import get_db
from common.logger import build_logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _load_json(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_query_slug(query: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:50] or "theme"


# ---------------------------------------------------------------------------
# Channel profiles per language
# ---------------------------------------------------------------------------

# Each language maps to its own channel config.
# In production, this comes from a config file or .env.
# For now, it's a dict that the user populates.

DEFAULT_CHANNEL_PROFILES: dict[str, dict] = {
    "es": {
        "youtube_channel_name": "",  # e.g. "@MovieMoments_ES"
        "tiktok_username": "",       # e.g. "@moviemoments.es"
        "subtitle_lang": "es",       # OpenSubtitles language code
        "tmdb_lang": "es-CO",        # TMDB language param
        "wikiquote_lang": "es",      # es.wikiquote.org
        "hashtag_base_yt": ["#shorts", "#youtubeshorts", "#peliculas", "#cine"],
        "hashtag_base_tt": ["#tiktok", "#parati", "#fyp", "#peliculas"],
        "caption_style": "casual_es",  # POV:, Si te gusta X mira esto
        "country_code": "CO",
    },
    "en": {
        "youtube_channel_name": "",
        "tiktok_username": "",
        "subtitle_lang": "en",
        "tmdb_lang": "en-US",
        "wikiquote_lang": "en",
        "hashtag_base_yt": ["#shorts", "#youtubeshorts", "#movies", "#cinema"],
        "hashtag_base_tt": ["#tiktok", "#fyp", "#foryou", "#movies"],
        "caption_style": "casual_en",
        "country_code": "US",
    },
    "pt": {
        "youtube_channel_name": "",
        "tiktok_username": "",
        "subtitle_lang": "pt",
        "tmdb_lang": "pt-BR",
        "wikiquote_lang": "pt",
        "hashtag_base_yt": ["#shorts", "#youtubeshorts", "#filmes", "#cinema"],
        "hashtag_base_tt": ["#tiktok", "#fyp", "#paravocê", "#filmes"],
        "caption_style": "casual_pt",
        "country_code": "BR",
    },
}


def _load_channel_profiles(data_dir: Path) -> dict[str, dict]:
    """Load channel profiles from config file, falling back to defaults."""
    config_path = data_dir / "channel_profiles.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_CHANNEL_PROFILES


def _get_channel_profile(data_dir: Path, lang: str) -> dict:
    """Get channel profile for a specific language."""
    profiles = _load_channel_profiles(data_dir)
    return profiles.get(lang, profiles.get("es", {}))


# ---------------------------------------------------------------------------
# Gather inputs from previous steps
# ---------------------------------------------------------------------------

def _gather_video(output_dir: Path, query: str) -> dict:
    """Find the latest rendered video for this query."""
    finals_dir = output_dir / "video" / "finals"
    slug = _safe_query_slug(query)

    video = _find_latest_file(finals_dir, f"*{slug}*.mp4")
    if not video:
        video = _find_latest_file(finals_dir, "*.mp4")

    if not video:
        return {"found": False, "path": None}

    return {
        "found": True,
        "path": str(video),
        "filename": video.name,
        "size_mb": round(video.stat().st_size / (1024 * 1024), 2),
    }


def _gather_growth_pack(output_dir: Path, query: str) -> dict:
    """Load the latest growth pack for this query."""
    slug = _safe_query_slug(query)
    meta_dir = output_dir / "metadata"
    path = meta_dir / f"ex08_growth_pack_{slug}.json"
    if not path.exists():
        path = _find_latest_file(meta_dir, "ex08_growth_pack_*.json")
    return _load_json(path)


def _gather_trend_graph(output_dir: Path, query: str) -> dict:
    """Load the latest trend graph for this query."""
    slug = _safe_query_slug(query)
    graphs_dir = output_dir / "graphs"
    path = _find_latest_file(graphs_dir, f"*{slug}*.json")
    if not path:
        path = _find_latest_file(graphs_dir, "ex13_*.json")
    return _load_json(path)


def _gather_curation(output_dir: Path, query: str) -> dict:
    """Load the latest curation (clip ranking) for this query."""
    slug = _safe_query_slug(query)
    cur_dir = output_dir / "curation"
    path = _find_latest_file(cur_dir, f"ex09_curation_{slug}_*.json")
    return _load_json(path)


def _gather_manifest(output_dir: Path, query: str) -> dict:
    """Load the latest video manifest."""
    slug = _safe_query_slug(query)
    man_dir = output_dir / "manifests"
    path = _find_latest_file(man_dir, f"*{slug}*.json")
    if not path:
        path = _find_latest_file(man_dir, "short_manifest_*.json")
    return _load_json(path)


def _gather_review_history(conn, query: str) -> list[dict]:
    """Get past review feedback for similar queries to learn from rejections."""
    cur = conn.execute(
        """SELECT r.status, r.reviewer_notes, r.rating, r.suggested_category,
                  r.suggested_emotion, r.suggested_edit_style, r.frame_issues,
                  s.theme_query, s.title
           FROM reviews r
           JOIN shorts s ON r.short_id = s.id
           WHERE s.theme_query LIKE ?
           ORDER BY r.created_at DESC
           LIMIT 10""",
        (f"%{query}%",),
    )
    rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Build strategy
# ---------------------------------------------------------------------------

def _select_best_song(growth_pack: dict, trend_graph: dict) -> dict | None:
    """Pick the best song by cross-referencing growth pack and trend graph."""
    # From growth pack song-hashtag graph
    song_graph = growth_pack.get("tiktok", {}).get("song_hashtag_graph", [])
    if song_graph:
        return {
            "title": song_graph[0].get("song_title", ""),
            "source": song_graph[0].get("song_source", ""),
            "related_hashtags": [
                h.get("hashtag", "") for h in song_graph[0].get("related_hashtags", [])[:5]
            ],
            "relevance_score": song_graph[0].get("relevance_score", 0),
            "upload_instruction": song_graph[0].get("upload_instruction", ""),
            "selection_reason": "highest relevance in song-hashtag graph",
        }

    # Fallback: top song candidate from growth pack
    candidates = growth_pack.get("tiktok", {}).get("song_candidates", [])
    if candidates:
        return {
            "title": candidates[0].get("title", ""),
            "source": candidates[0].get("source", ""),
            "related_hashtags": [],
            "relevance_score": 0,
            "upload_instruction": f"Buscar '{candidates[0].get('title', '')}' en Sonidos de TikTok",
            "selection_reason": "top ranked song candidate",
        }

    return None


def _pick_hashtags(
    growth_pack: dict,
    trend_graph: dict,
    platform: str,
    best_song: dict | None,
    channel_profile: dict | None = None,
) -> list[str]:
    """Select hashtags optimized for the platform, cross-referencing song."""
    # Start with language-specific base hashtags if channel profile exists
    if channel_profile:
        key = "hashtag_base_yt" if platform == "youtube" else "hashtag_base_tt"
        base = list(channel_profile.get(key, []))
    elif platform == "youtube":
        base = growth_pack.get("youtube", {}).get("hashtags", [])
    else:
        base = growth_pack.get("tiktok", {}).get("hashtags", [])

    # Add hashtags related to the selected song
    if best_song:
        song_tags = best_song.get("related_hashtags", [])
        for tag in song_tags:
            if tag not in base:
                base.append(tag)

    # Add high-centrality hashtags from trend graph
    top_nodes = trend_graph.get("top_hashtags_by_centrality", [])
    for node in top_nodes[:3]:
        tag = f"#{node}" if not node.startswith("#") else node
        if tag not in base:
            base.append(tag)

    return base[:15]  # Platform limits


def _generate_title(query: str, manifest: dict, platform: str) -> str:
    """Generate platform-optimized title."""
    clips = manifest.get("clips", [])
    movie_names = list({c.get("movie_title", "") for c in clips if c.get("movie_title")})

    if platform == "youtube":
        if len(movie_names) >= 2:
            return f"{query.title()} | {' vs '.join(movie_names[:3])}"
        elif len(movie_names) == 1:
            return f"{query.title()} - {movie_names[0]}"
        return f"{query.title()} | Best Movie Moments"
    else:
        # TikTok: shorter, more casual
        if movie_names:
            return f"POV: {query} ({movie_names[0]})"
        return f"POV: {query}"


def _learn_from_rejections(reviews: list[dict]) -> dict:
    """
    Analyze past review rejections to generate avoidance rules.

    Returns guidance dict that future steps can use to avoid
    repeating mistakes.
    """
    if not reviews:
        return {"has_history": False, "lessons": []}

    lessons = []
    rejected = [r for r in reviews if r.get("status") == "rejected"]
    approved = [r for r in reviews if r.get("status") == "approved"]

    for rej in rejected[:5]:
        notes = rej.get("reviewer_notes", "") or ""
        if notes:
            lessons.append({
                "type": "rejection",
                "query": rej.get("theme_query", ""),
                "note": notes,
                "suggested_fix": {
                    "category": rej.get("suggested_category"),
                    "emotion": rej.get("suggested_emotion"),
                    "edit_style": rej.get("suggested_edit_style"),
                },
            })

    avg_rating = 0
    if approved:
        ratings = [a.get("rating", 0) or 0 for a in approved]
        avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0

    return {
        "has_history": True,
        "total_reviews": len(reviews),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "avg_approved_rating": avg_rating,
        "lessons": lessons,
    }


def _estimate_best_times(country_code: str = "CO") -> dict:
    """
    Suggest upload times based on country.
    Extensible: in the future this can pull from analytics APIs.
    """
    # General best times by region (based on public social media studies)
    schedules = {
        "CO": {"youtube": "18:00-20:00", "tiktok": "19:00-21:00", "timezone": "America/Bogota"},
        "MX": {"youtube": "19:00-21:00", "tiktok": "20:00-22:00", "timezone": "America/Mexico_City"},
        "ES": {"youtube": "20:00-22:00", "tiktok": "21:00-23:00", "timezone": "Europe/Madrid"},
        "US": {"youtube": "17:00-19:00", "tiktok": "18:00-20:00", "timezone": "America/New_York"},
        "AR": {"youtube": "19:00-21:00", "tiktok": "20:00-22:00", "timezone": "America/Argentina/Buenos_Aires"},
    }
    return schedules.get(country_code, schedules["US"])


def _build_strategy(
    query: str,
    platform: str,
    video_info: dict,
    growth_pack: dict,
    trend_graph: dict,
    curation: dict,
    manifest: dict,
    reviews: list[dict],
    country_code: str,
    channel_profile: dict | None = None,
) -> dict:
    """Build the full publish strategy for one platform."""

    best_song = _select_best_song(growth_pack, trend_graph)
    hashtags = _pick_hashtags(growth_pack, trend_graph, platform, best_song, channel_profile)
    title = _generate_title(query, manifest, platform)
    times = _estimate_best_times(country_code)
    lessons = _learn_from_rejections(reviews)

    # Build description from growth pack
    if platform == "youtube":
        desc_template = growth_pack.get("youtube", {}).get("description_template", "")
        category_id = 24  # Entertainment
    else:
        desc_template = ""
        category_id = None

    strategy = {
        "platform": platform,
        "title": title,
        "hashtags": hashtags,
        "hashtags_string": " ".join(hashtags),
        "best_upload_time": times.get(platform, "18:00-20:00"),
        "timezone": times.get("timezone", "UTC"),
    }

    if platform == "youtube":
        strategy["description"] = desc_template
        strategy["category_id"] = category_id
        strategy["tags"] = [h.lstrip("#") for h in hashtags if h.startswith("#")]
        strategy["privacy"] = "private"  # Default safe: review first
        strategy["checklist"] = growth_pack.get("youtube", {}).get("upload_checklist", [])
    else:
        # TikTok
        caption = f"{title} {' '.join(hashtags[:8])}"
        strategy["caption"] = caption[:150]  # TikTok limit
        strategy["sound"] = best_song
        strategy["sound_search_instructions"] = (
            best_song.get("upload_instruction", "") if best_song else
            "Buscar audio trending en la seccion de Sonidos"
        )
        strategy["checklist"] = growth_pack.get("tiktok", {}).get("upload_checklist", [])

    # Cross-reference: how song and hashtags reinforce each other
    if best_song:
        song_hashtag_overlap = set(best_song.get("related_hashtags", [])) & set(hashtags)
        strategy["song_hashtag_synergy"] = {
            "song": best_song.get("title", ""),
            "overlapping_hashtags": list(song_hashtag_overlap),
            "synergy_score": len(song_hashtag_overlap),
            "note": (
                f"La cancion '{best_song.get('title', '')}' comparte "
                f"{len(song_hashtag_overlap)} hashtags con tu seleccion. "
                "Esto maximiza la probabilidad de aparecer en multiples feeds de descubrimiento."
            ),
        }

    # Lessons from past rejections
    if lessons.get("has_history"):
        strategy["review_lessons"] = lessons

    return strategy


# ---------------------------------------------------------------------------
# Extensibility hooks
# ---------------------------------------------------------------------------

class EdgeWeightContext:
    """
    Extensible edge weight context for the trend graph.

    Future additions:
      - Slang/jargon dictionaries per country
      - Cultural context mappings
      - Synonym expansion via LLM
      - Temporal decay (trends lose weight over time)

    For now, this is a placeholder that stores metadata
    so the schema is ready when these features are added.
    """

    def __init__(self):
        # Reserved for future slang/jargon mappings
        # Format: {"term": {"synonyms": [...], "region": "CO", "weight_modifier": 1.5}}
        self.slang_registry: dict[str, dict] = {}

        # Reserved for cultural context
        # Format: {"region": {"boosted_themes": [...], "avoided_themes": [...]}}
        self.cultural_context: dict[str, dict] = {}

        # Reserved for temporal decay config
        self.decay_half_life_days: int = 7

    def register_slang(self, term: str, synonyms: list[str], region: str = "global", weight_modifier: float = 1.0):
        """Register a slang term with its synonyms and weight modifier."""
        self.slang_registry[term.lower()] = {
            "synonyms": [s.lower() for s in synonyms],
            "region": region,
            "weight_modifier": weight_modifier,
        }

    def register_cultural_context(self, region: str, boosted: list[str] = None, avoided: list[str] = None):
        """Register cultural preferences for a region."""
        self.cultural_context[region] = {
            "boosted_themes": boosted or [],
            "avoided_themes": avoided or [],
        }

    def adjust_weight(self, base_weight: float, term: str, region: str = "global") -> float:
        """
        Adjust an edge weight considering slang and cultural context.

        Currently returns base_weight unchanged.
        When slang/cultural data is populated, this will modify weights.
        """
        modifier = 1.0

        # Slang modifier
        entry = self.slang_registry.get(term.lower())
        if entry and (entry["region"] == "global" or entry["region"] == region):
            modifier *= entry["weight_modifier"]

        # Cultural boost/penalty
        ctx = self.cultural_context.get(region, {})
        if term.lower() in [t.lower() for t in ctx.get("boosted_themes", [])]:
            modifier *= 1.3
        if term.lower() in [t.lower() for t in ctx.get("avoided_themes", [])]:
            modifier *= 0.5

        return base_weight * modifier

    def to_dict(self) -> dict:
        return {
            "slang_registry_count": len(self.slang_registry),
            "cultural_regions": list(self.cultural_context.keys()),
            "decay_half_life_days": self.decay_half_life_days,
            "note": "Extensible context for edge weights. Populate via register_slang() and register_cultural_context().",
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    settings: Settings,
    query: str = "epic movie moment",
    platform: str = "both",
    country_code: str = "CO",
    lang: str = "es",
) -> Path:
    log = build_logger("ex17", settings.output_dir / "logs" / "ex17.log")
    conn = get_db(settings.data_dir)

    # 0) Load channel profile for this language
    channel_profile = _get_channel_profile(settings.data_dir, lang)
    # Override country_code from channel profile if available
    if channel_profile.get("country_code"):
        country_code = channel_profile["country_code"]

    # 1) Gather all inputs
    log.info("Gathering inputs for query: %s (lang=%s)", query, lang)
    video_info = _gather_video(settings.output_dir, query)
    growth_pack = _gather_growth_pack(settings.output_dir, query)
    trend_graph = _gather_trend_graph(settings.output_dir, query)
    curation = _gather_curation(settings.output_dir, query)
    manifest = _gather_manifest(settings.output_dir, query)
    reviews = _gather_review_history(conn, query)

    # Google Trends: is this topic hot right now?
    google_trends = {}
    try:
        from common.trends import get_topic_interest, get_cinema_trends
        google_trends = get_topic_interest(query, geo=country_code)
        if google_trends.get("is_hot"):
            log.info("Google Trends: '%s' is HOT (%s, interest=%d). Good time to publish!",
                     query, google_trends["trend_direction"], google_trends["current_interest"])
        else:
            trending_now = get_cinema_trends(geo=country_code, limit=5)
            if trending_now:
                suggestions = [t["topic"] for t in trending_now[:3]]
                log.info("Google Trends: '%s' is not trending. Consider: %s", query, ", ".join(suggestions))
                google_trends["alternative_topics"] = suggestions
    except Exception as e:
        log.info("Google Trends not available: %s", e)

    if not growth_pack:
        log.warning("No growth pack found. Run ex08 first for better results.")
    if not video_info.get("found"):
        log.warning("No rendered video found. Run ex11 or ex16 first.")

    # 2) Build strategies
    platforms = ["youtube", "tiktok"] if platform == "both" else [platform]
    strategies = {}

    for plat in platforms:
        strategies[plat] = _build_strategy(
            query=query,
            platform=plat,
            video_info=video_info,
            growth_pack=growth_pack,
            trend_graph=trend_graph,
            curation=curation,
            manifest=manifest,
            reviews=reviews,
            country_code=country_code,
            channel_profile=channel_profile,
        )

    # 3) Edge weight context (extensible for future slang/jargon)
    edge_ctx = EdgeWeightContext()
    # Example: pre-register some common slang
    # In the future, these come from a config file or LLM analysis
    edge_ctx.register_slang("slay", ["dominar", "arrasar", "epic"], region="global", weight_modifier=1.3)
    edge_ctx.register_slang("no cap", ["de verdad", "sin mentir", "for real"], region="US", weight_modifier=1.2)
    edge_ctx.register_slang("parcero", ["amigo", "bro", "friend"], region="CO", weight_modifier=1.4)
    edge_ctx.register_cultural_context("CO", boosted=["reggaeton", "humor", "drama"], avoided=[])
    edge_ctx.register_cultural_context("US", boosted=["trending", "viral", "challenge"], avoided=[])

    # 4) Build output
    slug = _safe_query_slug(query)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query": query,
        "lang": lang,
        "country_code": country_code,
        "channel_profile": channel_profile,
        "video": video_info,
        "platform_strategies": strategies,
        "google_trends": google_trends,
        "edge_weight_context": edge_ctx.to_dict(),
        "review_status": "pending",
        "reviewer_notes": None,
    }

    out_dir = settings.output_dir / "publish"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"ex17_strategy_{slug}_{ts}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) Human-readable report
    txt_path = out_dir / f"ex17_strategy_{slug}_{ts}.txt"
    lines = [
        "ex17 - Publish Strategy Report",
        "=" * 55,
        f"Query: {query}",
        f"Country: {country_code}",
        f"Video: {'FOUND - ' + video_info.get('filename', '') if video_info.get('found') else 'NOT FOUND (run ex11/ex16)'}",
        "",
    ]

    for plat, strat in strategies.items():
        lines.append(f"--- {plat.upper()} ---")
        lines.append(f"  Title: {strat.get('title', '')}")
        lines.append(f"  Hashtags: {strat.get('hashtags_string', '')}")
        lines.append(f"  Best time: {strat.get('best_upload_time', '')} ({strat.get('timezone', '')})")

        if plat == "tiktok" and strat.get("sound"):
            song = strat["sound"]
            lines.append(f"  Song: {song.get('title', '')} (relevance: {song.get('relevance_score', 0)})")
            lines.append(f"  Search: {strat.get('sound_search_instructions', '')}")

            synergy = strat.get("song_hashtag_synergy", {})
            if synergy:
                lines.append(f"  Song-Hashtag synergy: {synergy.get('synergy_score', 0)} overlapping tags")

        if plat == "youtube":
            lines.append(f"  Privacy: {strat.get('privacy', 'private')}")
            lines.append(f"  Category: {strat.get('category_id', '')}")

        lessons = strat.get("review_lessons", {})
        if lessons.get("has_history"):
            lines.append(f"  Review history: {lessons['approved_count']} approved, {lessons['rejected_count']} rejected")
            for lesson in lessons.get("lessons", [])[:3]:
                lines.append(f"    - Rejected: {lesson.get('note', '')[:100]}")

        lines.append(f"  Checklist:")
        for item in strat.get("checklist", []):
            lines.append(f"    [ ] {item}")
        lines.append("")

    if google_trends:
        lines.append("--- GOOGLE TRENDS ---")
        lines.append(f"  Topic: {google_trends.get('topic', query)}")
        lines.append(f"  Interest: {google_trends.get('current_interest', '?')}/100")
        lines.append(f"  Direction: {google_trends.get('trend_direction', '?')}")
        lines.append(f"  Hot right now: {'YES — publish ASAP' if google_trends.get('is_hot') else 'No'}")
        alt = google_trends.get("alternative_topics", [])
        if alt:
            lines.append(f"  Trending alternatives: {', '.join(alt)}")
        lines.append("")

    lines.append("--- EDGE WEIGHT CONTEXT (extensible) ---")
    lines.append(f"  Slang terms registered: {edge_ctx.to_dict()['slang_registry_count']}")
    lines.append(f"  Cultural regions: {', '.join(edge_ctx.to_dict()['cultural_regions']) or 'none'}")
    lines.append("  Note: Add slang/jargon via EdgeWeightContext.register_slang()")
    lines.append("  Note: Add cultural context via EdgeWeightContext.register_cultural_context()")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    # 6) Register in DB if video exists
    if video_info.get("found"):
        try:
            conn.execute(
                """INSERT INTO shorts (title, theme_query, output_file, status)
                   VALUES (?, ?, ?, 'pending_review')""",
                (
                    strategies.get("youtube", strategies.get("tiktok", {})).get("title", query),
                    query,
                    video_info.get("path", ""),
                ),
            )
            conn.commit()
            log.info("Registered short in DB for review.")
        except Exception as e:
            log.warning("Could not register short in DB: %s", e)

    conn.close()
    log.info("Publish strategy saved to %s", json_path)
    return json_path
