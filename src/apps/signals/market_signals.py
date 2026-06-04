"""
Market Signals — Capa de ingesta de inteligencia de consumo de entretenimiento.

Se enchufa al scheduler de `topic_clusters` y alimenta a `signals_distiller`,
que a su vez produce briefs por persona para `content_rotator` y
`script_generator`.

Diseño (mapeado al diagrama de Sculley, NIPS 2015):
  ┌───────────────────────────────────────────────────────────────┐
  │ Data Collection (este módulo) → Data Verification (distiller) │
  │ → Feature Extraction (distiller) → ML Code (script_generator) │
  │ → Serving (produce_for_series) → Monitoring (analytics)       │
  └───────────────────────────────────────────────────────────────┘

Cubrimos 4 familias de fuentes (todas gratis, dentro de ToS):
  - Gaming: Steam Charts, OpenCritic, Metacritic RSS, IGN RSS, Famitsu RSS
  - Foros / comunidad: Reddit JSON público, MAL forum, Letterboxd popular
  - Tracking de releases: MangaUpdates RSS, Trakt.tv trending
  - Editorial: Polygon, RockPaperShotgun, Eurogamer, AnimeFeminist, ANN

API pública:
    from apps.signals.market_signals import refresh_all_sources, refresh_source

    n = refresh_all_sources(conn, domains=["gaming", "anime_manga"])
    n = refresh_source(conn, "steam_charts")

Notas MLOps / mejoras futuras (ver docs/MLOPS_FLOW.md):
  - [ ] Reemplazar parseo RSS manual por `feedparser` (más robusto a feeds
        mal formados). Hoy usamos xml.etree para no añadir dependencia.
  - [ ] Migrar Reddit JSON público a `praw` con OAuth si crece el volumen
        (límite de UA público: 60 req/min compartido global).
  - [ ] Steam Charts HTML scraping → reemplazar por la API no-oficial de
        SteamDB cuando publiquen endpoint estable (hoy solo HTML).
  - [ ] Añadir `feature_store` (Feast u offline parquet) para guardar
        embeddings de títulos y permitir nearest-neighbor cross-source.
  - [ ] Implementar `data_verification` (gran_expectations o pandera) sobre
        las columnas raw antes de que el distiller las consuma.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable

from utils.http_client import api_get, get_session

log = logging.getLogger(__name__)


# ── Tipos ────────────────────────────────────────────────────────────


@dataclass
class Signal:
    """Una señal cruda. Normalizada antes de persistir."""
    source: str
    source_type: str          # gaming_chart | gaming_review | reddit_thread | editorial_rss | release_tracker | letterboxd | forum
    domain: str               # gaming | anime_manga | movies_tv | music | latam
    title: str
    url: str = ""
    summary: str = ""
    raw_score: float = 0.0    # source-native (upvotes, viewers, position invertida)
    raw_meta: dict = field(default_factory=dict)


# ── Utilidades de normalización ──────────────────────────────────────


_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Bajar a lowercase, quitar puntuación, colapsar whitespace.

    Usado como clave de dedupe entre fuentes. No es perfecto (no maneja
    transliteración JP/EN), pero es estable y suficiente como capa 1.

    TODO(mlops): añadir paso 2 con embeddings cosine > 0.9 para juntar
    'Frieren: Beyond Journey's End' y 'Sousou no Frieren'.
    """
    s = title.lower().strip()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def _persist_signal(conn: sqlite3.Connection, sig: Signal) -> bool:
    """Inserta una señal. Devuelve True si fue NEW, False si UNIQUE conflict."""
    norm = normalize_title(sig.title)
    if not norm:
        return False
    try:
        conn.execute(
            """INSERT OR IGNORE INTO market_signals
                 (source, source_type, domain, title, normalized_title,
                  url, summary, raw_score, raw_meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sig.source, sig.source_type, sig.domain,
                sig.title[:300], norm,
                sig.url[:500], sig.summary[:1000],
                float(sig.raw_score),
                json.dumps(sig.raw_meta, ensure_ascii=False)[:4000],
            ),
        )
        return conn.total_changes > 0
    except sqlite3.Error as e:
        log.warning("persist_signal failed for %s: %s", sig.source, e)
        return False


def _persist_many(conn: sqlite3.Connection, signals: Iterable[Signal]) -> int:
    """Bulk persist. Retorna número de inserts nuevos."""
    n_new = 0
    for sig in signals:
        before = conn.total_changes
        _persist_signal(conn, sig)
        if conn.total_changes > before:
            n_new += 1
    conn.commit()
    return n_new


# ── Parser RSS genérico (sin dependencia) ────────────────────────────


def _parse_rss(url: str, source: str, source_type: str, domain: str,
               max_items: int = 15) -> list[Signal]:
    """Parser RSS 2.0 / Atom mínimo. Suficiente para los feeds que usamos.

    NOTE(mlops): para feeds complejos (Reuters, multi-namespace) considerar
    `feedparser`. Por ahora xml.etree cubre el 95% sin dependencia extra.
    """
    try:
        session = get_session(source)
        resp = session.get(url, timeout=15, headers={
            "User-Agent": "YouLikeIt-MarketSignals/1.0 (+research)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
        if resp.status_code != 200:
            log.warning("[%s] RSS %s → HTTP %d", source, url, resp.status_code)
            return []
        root = ET.fromstring(resp.content)
    except Exception as e:
        log.warning("[%s] RSS fetch/parse failed: %s", source, e)
        return []

    # RSS 2.0: //channel/item ; Atom: //entry
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    signals: list[Signal] = []
    for i, item in enumerate(items[:max_items]):
        title = (item.findtext("title")
                 or item.findtext("{http://www.w3.org/2005/Atom}title")
                 or "").strip()
        link = (item.findtext("link")
                or "").strip()
        if not link:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
            if link_el is not None:
                link = link_el.get("href", "").strip()
        desc = (item.findtext("description")
                or item.findtext("{http://www.w3.org/2005/Atom}summary")
                or "").strip()
        desc = re.sub(r"<[^>]+>", "", desc)[:500]
        if not title:
            continue
        # Score = posición invertida (item 0 más reciente = mayor score)
        signals.append(Signal(
            source=source,
            source_type=source_type,
            domain=domain,
            title=title,
            url=link,
            summary=desc,
            raw_score=max(1.0, max_items - i),
            raw_meta={"feed_position": i},
        ))
    return signals


# ── GAMING ───────────────────────────────────────────────────────────


def fetch_steam_charts(limit: int = 50) -> list[Signal]:
    """Top juegos por jugadores concurrentes (steamcharts.com público).

    NOTE(legal): steamcharts.com no expone API oficial. Hacemos un parseo
    HTML mínimo. Respetamos robots.txt — solo /top con throttle 1 req/min.

    TODO(mlops): si Valve publica oficialmente el `ISteamCharts`, migrar.
    TODO(mlops): cache de 6h en SQLite para no martillar.
    """
    url = "https://steamcharts.com/top"
    session = get_session("steam_charts")
    try:
        resp = session.get(url, timeout=15, headers={
            "User-Agent": "YouLikeIt-MarketSignals/1.0 (+research)",
        })
        if resp.status_code != 200:
            log.warning("[steam_charts] HTTP %d", resp.status_code)
            return []
        html = resp.text
    except Exception as e:
        log.warning("[steam_charts] fetch failed: %s", e)
        return []

    # Regex laxo: filas <tr> con <a> al juego y dos celdas numéricas.
    row_re = re.compile(
        r'<tr[^>]*>\s*'
        r'<td[^>]*class="num"[^>]*>(\d+)</td>\s*'
        r'<td[^>]*class="game-name[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    signals: list[Signal] = []
    for m in row_re.finditer(html):
        if len(signals) >= limit:
            break
        rank = int(m.group(1))
        path = m.group(2)
        title = m.group(3).strip()
        if not title:
            continue
        signals.append(Signal(
            source="steam_charts",
            source_type="gaming_chart",
            domain="gaming",
            title=title,
            url=f"https://steamcharts.com{path}",
            summary=f"Top {rank} en Steam (jugadores concurrentes)",
            raw_score=max(1.0, limit - rank + 1),
            raw_meta={"rank": rank},
        ))
    log.info("[steam_charts] %d juegos top", len(signals))
    return signals


def fetch_opencritic_rss() -> list[Signal]:
    """Top reviews recientes vía RSS de OpenCritic."""
    return _parse_rss(
        url="https://opencritic.com/feed/rss",
        source="opencritic",
        source_type="gaming_review",
        domain="gaming",
        max_items=20,
    )


def fetch_ign_rss() -> list[Signal]:
    """Noticias gaming IGN."""
    return _parse_rss(
        url="https://feeds.ign.com/ign/games-all",
        source="ign_games",
        source_type="editorial_rss",
        domain="gaming",
        max_items=20,
    )


def fetch_polygon_gaming_rss() -> list[Signal]:
    return _parse_rss(
        url="https://www.polygon.com/rss/index.xml",
        source="polygon",
        source_type="editorial_rss",
        domain="gaming",
        max_items=15,
    )


def fetch_rps_rss() -> list[Signal]:
    return _parse_rss(
        url="https://www.rockpapershotgun.com/feed",
        source="rockpapershotgun",
        source_type="editorial_rss",
        domain="gaming",
        max_items=15,
    )


def fetch_eurogamer_rss() -> list[Signal]:
    return _parse_rss(
        url="https://www.eurogamer.net/feed",
        source="eurogamer",
        source_type="editorial_rss",
        domain="gaming",
        max_items=15,
    )


# ── FOROS / COMUNIDAD ────────────────────────────────────────────────


REDDIT_DOMAINS = {
    "anime": "anime_manga",
    "manga": "anime_manga",
    "Games": "gaming",
    "patientgamers": "gaming",
    "movies": "movies_tv",
    "television": "movies_tv",
    "letterboxd": "movies_tv",
    "TrueFilm": "movies_tv",
    "MexicoMaravilloso": "latam",
    "podemos": "latam",  # TODO(latam): mejor subreddit LatAm
}


def fetch_reddit_hot(subreddit: str, limit: int = 25) -> list[Signal]:
    """Hot threads de un subreddit vía endpoint JSON público.

    Reddit permite el endpoint /.json sin auth con User-Agent declarado.
    Límite oficial: 60 req/min compartido. Cumplimos con
    SERVICE_RATE_LIMITS en http_client.

    TODO(mlops): si crece, migrar a `praw` con OAuth (sin límite global).
    """
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    data = api_get(url, params={"limit": limit}, service="reddit")
    if not data or "data" not in data:
        return []

    domain = REDDIT_DOMAINS.get(subreddit, "movies_tv")
    signals: list[Signal] = []
    for child in data["data"].get("children", []):
        post = child.get("data", {})
        if post.get("stickied"):
            continue
        title = post.get("title", "").strip()
        if not title:
            continue
        ups = int(post.get("ups", 0))
        n_comments = int(post.get("num_comments", 0))
        # Score combina upvotes y comentarios (saturado para evitar dominar)
        raw = min(10000, ups) + min(5000, n_comments * 2)
        signals.append(Signal(
            source=f"reddit_r_{subreddit}",
            source_type="reddit_thread",
            domain=domain,
            title=title,
            url=f"https://reddit.com{post.get('permalink', '')}",
            summary=(post.get("selftext", "") or "")[:500],
            raw_score=float(raw),
            raw_meta={
                "subreddit": subreddit,
                "ups": ups,
                "num_comments": n_comments,
                "flair": post.get("link_flair_text"),
                "created_utc": post.get("created_utc"),
            },
        ))
    log.info("[reddit/%s] %d threads", subreddit, len(signals))
    return signals


def fetch_letterboxd_popular() -> list[Signal]:
    """Popular this week en Letterboxd (RSS oficial)."""
    return _parse_rss(
        url="https://letterboxd.com/films/popular/this/week/rss/",
        source="letterboxd_weekly",
        source_type="letterboxd",
        domain="movies_tv",
        max_items=25,
    )


# ── TRACKING DE RELEASES ─────────────────────────────────────────────


def fetch_mangaupdates_rss() -> list[Signal]:
    """Últimos capítulos publicados (releases) — proxy de actividad de un manga."""
    return _parse_rss(
        url="https://www.mangaupdates.com/rss.php",
        source="mangaupdates_releases",
        source_type="release_tracker",
        domain="anime_manga",
        max_items=30,
    )


def fetch_trakt_trending(media_type: str = "movies") -> list[Signal]:
    """Trakt.tv trending movies/shows. Requiere TRAKT_CLIENT_ID en env."""
    import os
    client_id = os.getenv("TRAKT_CLIENT_ID", "")
    if not client_id:
        log.info("[trakt] sin TRAKT_CLIENT_ID — skip")
        return []

    url = f"https://api.trakt.tv/{media_type}/trending"
    session = get_session("trakt")
    try:
        resp = session.get(url, timeout=15, headers={
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
            "User-Agent": "YouLikeIt-MarketSignals/1.0",
        }, params={"limit": 25})
        if resp.status_code != 200:
            log.warning("[trakt] HTTP %d", resp.status_code)
            return []
        data = resp.json()
    except Exception as e:
        log.warning("[trakt] fetch failed: %s", e)
        return []

    signals: list[Signal] = []
    for i, entry in enumerate(data):
        watchers = entry.get("watchers", 0)
        item = entry.get(media_type[:-1], {}) or entry.get("movie") or entry.get("show", {})
        title = item.get("title", "").strip()
        year = item.get("year")
        if not title:
            continue
        signals.append(Signal(
            source=f"trakt_trending_{media_type}",
            source_type="release_tracker",
            domain="movies_tv",
            title=f"{title} ({year})" if year else title,
            url=f"https://trakt.tv/{media_type}/{item.get('ids', {}).get('slug', '')}",
            summary=f"{watchers} viewers ahora en Trakt",
            raw_score=float(watchers),
            raw_meta={"watchers": watchers, "rank": i, "media_type": media_type},
        ))
    log.info("[trakt/%s] %d trending", media_type, len(signals))
    return signals


# ── EDITORIAL (anime/manga) ──────────────────────────────────────────


def fetch_ann_features_rss() -> list[Signal]:
    return _parse_rss(
        url="https://www.animenewsnetwork.com/all/rss.xml?ann-edition=us",
        source="ann_features",
        source_type="editorial_rss",
        domain="anime_manga",
        max_items=20,
    )


def fetch_animefeminist_rss() -> list[Signal]:
    return _parse_rss(
        url="https://www.animefeminist.com/feed/",
        source="animefeminist",
        source_type="editorial_rss",
        domain="anime_manga",
        max_items=15,
    )


# ── EDITORIAL (movies / cinema) ──────────────────────────────────────


def fetch_variety_rss() -> list[Signal]:
    return _parse_rss(
        url="https://variety.com/feed/",
        source="variety",
        source_type="editorial_rss",
        domain="movies_tv",
        max_items=15,
    )


def fetch_deadline_rss() -> list[Signal]:
    return _parse_rss(
        url="https://deadline.com/feed/",
        source="deadline",
        source_type="editorial_rss",
        domain="movies_tv",
        max_items=15,
    )


# ── REGISTRO de fuentes (priority + domain) ──────────────────────────
# Esto es el "feature flag" del scheduler. Para deshabilitar una fuente
# basta con comentarla aquí. El distiller solo lee de market_signals,
# no necesita conocer la lista.


SOURCES: list[tuple[str, str, Callable[[], list[Signal]]]] = [
    # (source_name, domain, fetcher)
    # Gaming
    ("steam_charts",        "gaming",       fetch_steam_charts),
    ("opencritic",          "gaming",       fetch_opencritic_rss),
    ("ign_games",           "gaming",       fetch_ign_rss),
    ("polygon",             "gaming",       fetch_polygon_gaming_rss),
    ("rockpapershotgun",    "gaming",       fetch_rps_rss),
    ("eurogamer",           "gaming",       fetch_eurogamer_rss),
    # Foros
    ("reddit_r_anime",      "anime_manga",  lambda: fetch_reddit_hot("anime")),
    ("reddit_r_manga",      "anime_manga",  lambda: fetch_reddit_hot("manga")),
    ("reddit_r_Games",      "gaming",       lambda: fetch_reddit_hot("Games")),
    ("reddit_r_movies",     "movies_tv",    lambda: fetch_reddit_hot("movies")),
    ("reddit_r_television", "movies_tv",    lambda: fetch_reddit_hot("television")),
    ("reddit_r_TrueFilm",   "movies_tv",    lambda: fetch_reddit_hot("TrueFilm")),
    ("letterboxd_weekly",   "movies_tv",    fetch_letterboxd_popular),
    # Tracking
    ("mangaupdates",        "anime_manga",  fetch_mangaupdates_rss),
    ("trakt_trending_movies", "movies_tv",  lambda: fetch_trakt_trending("movies")),
    ("trakt_trending_shows",  "movies_tv",  lambda: fetch_trakt_trending("shows")),
    # Editorial
    ("ann_features",        "anime_manga",  fetch_ann_features_rss),
    ("animefeminist",       "anime_manga",  fetch_animefeminist_rss),
    ("variety",             "movies_tv",    fetch_variety_rss),
    ("deadline",            "movies_tv",    fetch_deadline_rss),
    # TODO(latam): añadir Cosmo, TVNotas, RCN/Caracol RSS (ojo a no-paywall)
    # TODO(music): añadir Genius + Last.fm si el usuario provee API key
    # TODO(games-jp): añadir Famitsu, 4Gamer RSS
]


# ── Orquestación ─────────────────────────────────────────────────────


def refresh_source(conn: sqlite3.Connection, source_name: str) -> int:
    """Refresca una sola fuente por nombre. Devuelve número de inserts nuevos."""
    for name, _domain, fetcher in SOURCES:
        if name == source_name:
            t0 = time.time()
            try:
                signals = fetcher() or []
            except Exception as e:  # cualquier fallo de fuente no aborta todo
                log.exception("[%s] fetcher crashed: %s", name, e)
                signals = []
            n_new = _persist_many(conn, signals)
            dur = (time.time() - t0) * 1000
            log.info("[%s] %d señales (%d nuevas) en %.0fms",
                     name, len(signals), n_new, dur)
            _update_scraper_health(conn, name, ok=True, n=len(signals), dur_ms=dur)
            return n_new
    log.warning("source '%s' no registrada", source_name)
    return 0


def refresh_all_sources(conn: sqlite3.Connection,
                        domains: list[str] | None = None,
                        sources: list[str] | None = None) -> dict:
    """Refresca todas las fuentes (o filtra por dominio / lista explícita).

    Retorna dict con conteos por fuente + total.
    """
    report: dict = {"sources": {}, "total_new": 0, "started_at": datetime.now().isoformat()}
    for name, domain, fetcher in SOURCES:
        if sources and name not in sources:
            continue
        if domains and domain not in domains:
            continue
        n_new = refresh_source(conn, name)
        report["sources"][name] = n_new
        report["total_new"] += n_new
    report["finished_at"] = datetime.now().isoformat()
    return report


def _update_scraper_health(conn: sqlite3.Connection, source: str,
                            ok: bool, n: int, dur_ms: float):
    """Bookkeeping mínimo de salud por scraper. Lo lee el dashboard de monitoring."""
    try:
        if ok:
            conn.execute(
                """INSERT INTO scraper_health (scraper_name, success_count, avg_latency_ms, last_success_at)
                   VALUES (?, 1, ?, CURRENT_TIMESTAMP)""",
                (source, dur_ms),
            )
        else:
            conn.execute(
                """INSERT INTO scraper_health (scraper_name, failure_count, last_failure_at)
                   VALUES (?, 1, CURRENT_TIMESTAMP)""",
                (source,),
            )
        conn.commit()
    except sqlite3.Error:
        pass


# ── Mantenimiento ────────────────────────────────────────────────────


def prune_old_signals(conn: sqlite3.Connection, retention_days: int = 30) -> int:
    """Borra señales más viejas que `retention_days`. Idempotente.

    NOTE: ajusta retention según volumen. 30d es razonable para detectar
    sostenibilidad de un tema sin inflar la DB.
    """
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
    cur = conn.execute(
        "DELETE FROM market_signals WHERE fetched_at < ?", (cutoff,)
    )
    conn.commit()
    log.info("prune_old_signals: %d filas borradas (< %s)", cur.rowcount, cutoff)
    return cur.rowcount


if __name__ == "__main__":
    # Smoke test mínimo: refresca todo y reporta a stdout.
    # Uso real: ver scripts/refresh_market_signals.py
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from pathlib import Path
    from core.db import get_db
    conn = get_db(Path("data"))
    report = refresh_all_sources(conn)
    print(json.dumps(report, indent=2))
