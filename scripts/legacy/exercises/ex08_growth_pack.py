"""
ex08 - Generar pack de crecimiento para YouTube Shorts + TikTok.

Incluye:
  - Hashtags tematicos (desde query + escenas)
  - Hashtags trending de TikTok (Creative Center publico)
  - Canciones trending de TikTok (Creative Center publico)
  - Plantillas de titulo/caption y checklist de publicacion

Uso:
  python src/main.py ex08 --query "frases de villanos"
  python src/main.py ex08 --query "motivacion gym" --country-code MX
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, unquote

import requests

from core.config import Settings
from utils.logger import build_logger


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "your", "you",
    "los", "las", "para", "con", "que", "como", "una", "uno", "por", "del", "de", "el", "la",
    "movie", "movies", "short", "shorts", "video", "scene", "escena", "frase", "frases",
}


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-zA-Z0-9]{3,}", text.lower())
    return [t for t in toks if t not in STOPWORDS]


def _latest_manifest(manifests_dir: Path) -> dict:
    if not manifests_dir.exists():
        return {}
    files = sorted(manifests_dir.glob("short_manifest_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {}
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_keywords(query: str, manifest: dict, limit: int = 15) -> list[str]:
    tokens: list[str] = []
    tokens.extend(_tokenize(query))

    for clip in manifest.get("clips", []):
        tokens.extend(_tokenize(clip.get("movie_title", "")))
        tokens.extend(_tokenize(clip.get("quote", "")))

    score: dict[str, int] = {}
    for t in tokens:
        score[t] = score.get(t, 0) + 1

    ranked = sorted(score.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in ranked[:limit]]


def _yt_suggestions(query: str) -> list[str]:
    # Endpoint libre de autocompletado para ideas de titulos/keywords.
    url = (
        "https://suggestqueries.google.com/complete/search"
        f"?client=firefox&ds=yt&q={quote_plus(query)}"
    )
    try:
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [str(s).strip() for s in data[1][:20] if str(s).strip()]
    except Exception:
        return []
    return []


def _tiktok_trending_hashtags() -> list[str]:
    url = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        html = requests.get(url, headers=headers, timeout=15).text
    except Exception:
        return []

    tags = re.findall(r"/creativecenter/hashtag/([^/]+)/pc/en", html, flags=re.IGNORECASE)
    uniq = []
    seen = set()
    for t in tags:
        tag = t.strip().lower()
        if tag and tag not in seen:
            seen.add(tag)
            uniq.append(tag)
    return uniq[:100]


def _tiktok_trending_songs(country_code: str = "CO", period: int = 7) -> list[dict]:
    url = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        html = requests.get(url, headers=headers, timeout=15).text
    except Exception:
        return []

    slugs = re.findall(r"/creativecenter/song/([^\"\s?]+)\?countryCode=([A-Z]{2})&period=([0-9]+)", html)
    if not slugs:
        slugs = [(m, country_code, str(period)) for m in re.findall(r"/creativecenter/song/([^\"\s?]+)", html)]

    songs = []
    seen = set()
    for raw_slug, cc, per in slugs:
        slug = unquote(raw_slug)
        if slug in seen:
            continue
        seen.add(slug)

        # El slug suele terminar en un id numerico; lo removemos para un titulo legible.
        title = re.sub(r"-[0-9]{8,}$", "", slug)
        title = title.replace("-", " ").strip().title()

        songs.append(
            {
                "title": title,
                "country_code": cc,
                "period_days": int(per) if str(per).isdigit() else period,
                "source": f"https://ads.tiktok.com/business/creativecenter/song/{raw_slug}?countryCode={cc}&period={per}",
                "license_hint": "Preferir audios con etiqueta 'Approved for business use' dentro de TikTok.",
            }
        )

    return songs[:80]


def _rank_song_candidates(songs: list[dict], keywords: list[str], limit: int = 12) -> list[dict]:
    if not songs:
        return []

    kws = set(keywords)
    ranked = []
    for s in songs:
        title_tokens = set(_tokenize(s.get("title", "")))
        overlap = len(kws.intersection(title_tokens))
        bonus = 1 if any(x in s.get("title", "").lower() for x in ["love", "sad", "epic", "night", "vibe"]) else 0
        ranked.append((overlap + bonus, s))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in ranked[:limit]]


def _build_song_hashtag_graph(
    songs: list[dict],
    tt_hashtags: list[str],
    keywords: list[str],
) -> list[dict]:
    """
    Build a trend graph: song -> related hashtags.

    Cross-references song titles with trending hashtags by shared keywords.
    This helps identify which song + hashtag combos maximize discoverability.

    Output: list of { song_title, song_source, related_hashtags, relevance_score }
    """
    if not songs:
        return []

    kws = set(keywords)
    graph = []

    for song in songs:
        title = song.get("title", "")
        title_tokens = set(_tokenize(title))

        # Find hashtags that share keywords with this song
        related = []
        for tag in tt_hashtags:
            tag_tokens = set(_tokenize(tag))
            # Match if hashtag overlaps with song title or theme keywords
            song_overlap = len(title_tokens & tag_tokens)
            theme_overlap = len(kws & tag_tokens)
            if song_overlap > 0 or theme_overlap > 0:
                related.append({
                    "hashtag": f"#{tag}",
                    "match_type": "song_match" if song_overlap > 0 else "theme_match",
                    "overlap_score": song_overlap + theme_overlap,
                })

        # Also check if the song title itself could be a hashtag
        title_as_tag = re.sub(r"[^a-zA-Z0-9]", "", title.lower())
        if title_as_tag and len(title_as_tag) >= 4:
            related.append({
                "hashtag": f"#{title_as_tag}",
                "match_type": "song_name",
                "overlap_score": 3,
            })

        # Sort related hashtags by overlap
        related.sort(key=lambda x: x["overlap_score"], reverse=True)

        # Calculate overall relevance: how well this song fits the theme
        relevance = sum(r["overlap_score"] for r in related[:5])

        graph.append({
            "song_title": title,
            "song_source": song.get("source", ""),
            "related_hashtags": related[:8],
            "relevance_score": relevance,
            "upload_instruction": (
                f"En TikTok: buscar '{title}' en Sonidos al crear el video. "
                f"En YouTube Shorts: buscar '{title}' en la biblioteca de audio. "
                f"Bajar volumen del audio original y usar esta cancion como sonido principal."
            ),
        })

    # Sort by relevance
    graph.sort(key=lambda x: x["relevance_score"], reverse=True)
    return graph


def _build_hashtags(keywords: list[str], yt_suggest: list[str], tt_trending: list[str]) -> tuple[list[str], list[str]]:
    base_yt = ["#shorts", "#youtubeshorts", "#shortsvideo"]
    base_tt = ["#tiktok", "#parati", "#fyp"]

    kw_tags = [f"#{k.replace(' ', '')}" for k in keywords[:12]]

    yt_from_suggest = []
    for s in yt_suggest[:15]:
        toks = _tokenize(s)
        if toks:
            yt_from_suggest.append("#" + "".join(toks[:2]))

    tt_relevant = []
    kws = set(keywords)
    for t in tt_trending:
        if t in kws or any(k in t for k in list(kws)[:8]):
            tt_relevant.append(f"#{t}")
    if len(tt_relevant) < 5:
        tt_relevant.extend([f"#{t}" for t in tt_trending[:8 - len(tt_relevant)]])

    yt = _dedupe(base_yt + kw_tags + yt_from_suggest)[:12]
    tt = _dedupe(base_tt + kw_tags + tt_relevant)[:10]
    return yt, tt


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for i in items:
        x = i.strip()
        if not x:
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def run(
    settings: Settings,
    query: str = "epic movie moment",
    country_code: str = "CO",
    period_days: int = 7,
) -> Path:
    logs_dir = settings.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log = build_logger("ex08", logs_dir / "ex08.log")

    manifest = _latest_manifest(settings.output_dir / "manifests")
    keywords = _extract_keywords(query, manifest)
    log.info("Keywords: %s", keywords)

    yt_suggest = _yt_suggestions(query)
    tt_hashtags = _tiktok_trending_hashtags()
    tt_songs = _tiktok_trending_songs(country_code=country_code, period=period_days)

    yt_hashtags, tt_best_hashtags = _build_hashtags(keywords, yt_suggest, tt_hashtags)
    tt_song_candidates = _rank_song_candidates(tt_songs, keywords)
    song_hashtag_graph = _build_song_hashtag_graph(tt_songs, tt_hashtags, keywords)

    yt_title_templates = [
        f"{query.title()} in 20s",
        f"Top scene: {query}",
        f"{query.title()} | movie short",
    ]
    tt_caption_templates = [
        f"POV: {query}",
        f"Si te gusta {query}, mira esto 👀",
        f"{query} en version short",
    ]

    pack = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "theme_query": query,
        "country_code": country_code,
        "period_days": period_days,
        "keywords": keywords,
        "youtube": {
            "title_templates": yt_title_templates,
            "description_template": (
                f"Short tematico sobre {query}. "
                "Edit rapido, hook en primeros 2 segundos y CTA breve al final."
            ),
            "hashtags": yt_hashtags,
            "upload_checklist": [
                "Hook fuerte en los primeros 2 segundos.",
                "Formato 9:16 (1080x1920), 24-60 fps.",
                "Duracion 15-35s para retencion alta.",
                "Subtitulos quemados y titulo legible en zona segura.",
                "Mini CTA: seguir, comentar palabra clave o parte 2.",
            ],
        },
        "tiktok": {
            "caption_templates": tt_caption_templates,
            "hashtags": tt_best_hashtags,
            "song_candidates": tt_song_candidates,
            "song_hashtag_graph": song_hashtag_graph[:5],
            "audio_instructions": {
                "strategy": (
                    "NO mezclar audio en el video. El video se sube SIN musica de fondo. "
                    "La cancion se selecciona EN LA PLATAFORMA al publicar. "
                    "Esto permite que el contenido aparezca cuando alguien busca por esa cancion."
                ),
                "tiktok_steps": [
                    "1. Crear video > Sonidos > buscar la cancion recomendada",
                    "2. Ajustar volumen: voz original al 80-100%, cancion al 15-25%",
                    "3. El video aparecera en la pagina de ese sonido = descubrimiento organico",
                ],
                "youtube_steps": [
                    "1. YouTube Studio > Crear Short > Agregar sonido",
                    "2. Buscar la cancion en la biblioteca de audio",
                    "3. Ajustar mezcla de volumen desde el editor",
                ],
                "recommended_song": song_hashtag_graph[0] if song_hashtag_graph else None,
            },
            "upload_checklist": [
                "Seleccionar audio trending EN LA PLATAFORMA (no mezclado en el video).",
                "Ajustar volumen: voz clara + musica de fondo baja (15-25%).",
                "Mantener ritmo de corte cada 1-2.5 segundos.",
                "Texto en pantalla con contraste alto.",
                "Publicar en 2 ventanas horarias y comparar retencion.",
                "Usar los hashtags que coinciden con la cancion (ver song_hashtag_graph).",
                "Validar derechos: preferir 'Approved for business use'.",
            ],
            "free_note": (
                "La deteccion usa Creative Center publico (gratis). "
                "Para uso comercial, valida dentro de TikTok que el audio este habilitado para negocio."
            ),
        },
    }

    out_dir = settings.output_dir / "metadata"
    out_dir.mkdir(parents=True, exist_ok=True)

    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", query.strip())[:50] or "theme"
    out_json = out_dir / f"ex08_growth_pack_{safe}.json"
    out_json.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")

    out_txt = out_dir / f"ex08_growth_pack_{safe}.txt"
    lines = [
        "ex08 - Growth Pack",
        "=" * 40,
        f"Theme: {query}",
        f"Keywords: {', '.join(keywords[:12])}",
        "",
        "YouTube hashtags:",
        " ".join(pack["youtube"]["hashtags"]),
        "",
        "TikTok hashtags:",
        " ".join(pack["tiktok"]["hashtags"]),
        "",
        "AUDIO STRATEGY:",
        "  Video se sube SIN musica. La cancion se selecciona EN LA PLATAFORMA.",
        "  Esto hace que el contenido aparezca al buscar por esa cancion.",
        "",
        "Recommended songs (select on platform):",
    ]
    for s in tt_song_candidates[:10]:
        lines.append(f"- {s['title']} ({s['source']})")

    if song_hashtag_graph:
        lines.append("")
        lines.append("Song-Hashtag Graph (best combos for discoverability):")
        lines.append("-" * 50)
        for entry in song_hashtag_graph[:5]:
            lines.append(f"  Song: {entry['song_title']} (relevance: {entry['relevance_score']})")
            related = entry.get("related_hashtags", [])
            if related:
                tags_str = " ".join(r["hashtag"] for r in related[:5])
                lines.append(f"    Use with: {tags_str}")
            lines.append(f"    {entry['upload_instruction']}")
            lines.append("")

    out_txt.write_text("\n".join(lines), encoding="utf-8")
    log.info("Growth pack saved to %s", out_json)
    return out_json
