"""Proveedor de biblioteca local (MOVIES_DIR, típicamente la USB en E:).

Mejora sobre `movie_source.find_local_movie` (solo nombre de archivo, se
reescaneaba en cada llamada y no entendía episodios):
  - parsea película (título + año) y episodio (S01E02 / 1x02), con guessit si
    está instalado y regex como fallback;
  - toma el título de la carpeta de la serie cuando el archivo no lo trae
    ("Show/Season 1/S01E01.mkv");
  - cachea el escaneo por (ruta, tamaño, mtime) en memoria del proceso.
Los derechos se marcan `owned`: es la biblioteca del propio usuario.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from apps.media.models import RIGHTS_OWNED, MediaCandidate

VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".m2ts", ".ts"}
_EP_RE = re.compile(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})|\b(\d{1,2})x(\d{2,3})\b")
_YEAR_RE = re.compile(r"(?:^|[ ._(\[-])((?:19|20)\d{2})(?=$|[ ._)\]-])")
_SEASON_DIR_RE = re.compile(r"^(season|temporada|s)[ ._-]?\d+$", re.I)
_JUNK_RE = re.compile(
    r"\b(1080p|720p|2160p|480p|4k|bluray|brrip|bdrip|web[- ]?dl|webrip|hdtv|dvdrip|x264|x265|"
    r"h\.?264|h\.?265|hevc|aac|ac3|dts|remastered|extended|unrated|proper|repack)\b.*$", re.I)


@dataclass(frozen=True)
class ParsedName:
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None

    @property
    def kind(self) -> str:
        return "episode" if self.episode is not None else "movie"


def _clean(text: str) -> str:
    text = re.sub(r"[._]+", " ", text)
    text = _JUNK_RE.sub("", text)
    text = re.sub(r"[\[\(].*?[\]\)]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -")


def parse_filename(path: Path) -> ParsedName:
    """Extrae título/año/temporada/episodio de una ruta de video."""
    try:  # guessit es más robusto con nombres de releases reales
        from guessit import guessit  # type: ignore
        g = guessit(path.name)
        title = str(g.get("title") or "").strip()
        season, episode = g.get("season"), g.get("episode")
        if isinstance(episode, list):
            episode = episode[0]
        if title or episode is not None:
            if not title:
                title = _series_title_from_dirs(path)
            return ParsedName(title=title, year=g.get("year"),
                              season=season if episode is not None else None,
                              episode=episode)
    except ImportError:
        pass

    stem = path.stem
    season = episode = None
    m = _EP_RE.search(stem)
    if m:
        season = int(m.group(1) or m.group(3))
        episode = int(m.group(2) or m.group(4))
        stem_title = stem[: m.start()]
    else:
        stem_title = stem
    year = None
    ym = _YEAR_RE.search(stem_title)
    if ym:
        year = int(ym.group(1))
        stem_title = stem_title[: ym.start()] or stem_title
    title = _clean(stem_title)
    if not title and episode is not None:
        title = _series_title_from_dirs(path)
    return ParsedName(title=title or _clean(path.stem), year=year, season=season, episode=episode)


def _series_title_from_dirs(path: Path) -> str:
    for parent in path.parents:
        name = parent.name
        if name and not _SEASON_DIR_RE.match(name):
            return _clean(name)
    return ""


def _similarity(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz  # type: ignore
        return fuzz.token_set_ratio(a, b) / 100.0
    except ImportError:
        return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


class LocalLibraryProvider:
    name = "local"
    _cache: dict[tuple[str, int, int], ParsedName] = {}

    def __init__(self, root: str | Path | None = None):
        root = root or os.getenv("MOVIES_DIR") or os.getenv("LOCAL_MOVIES_DIR") or "E:/movies"
        self.root = Path(root)

    def scan(self) -> list[MediaCandidate]:
        if not self.root.is_dir():
            raise FileNotFoundError(f"MOVIES_DIR no disponible: {self.root}")
        out = []
        for dirpath, _dirs, files in os.walk(self.root):
            for fname in files:
                p = Path(dirpath) / fname
                if p.suffix.lower() not in VIDEO_EXTS or fname.startswith("."):
                    continue
                st = p.stat()
                key = (str(p), st.st_size, int(st.st_mtime))
                parsed = self._cache.get(key) or parse_filename(p)
                self._cache[key] = parsed
                out.append(MediaCandidate(
                    provider=self.name, external_id=str(p.relative_to(self.root)),
                    title=parsed.title, year=parsed.year, kind=parsed.kind,
                    season=parsed.season, episode=parsed.episode,
                    master_uri=str(p), proxy_uri=str(p), size_bytes=st.st_size,
                    rights=RIGHTS_OWNED,
                ))
        return out

    def search(self, title: str, year: int | None = None, *, limit: int = 10,
               min_score: float = 0.8) -> list[MediaCandidate]:
        scored = []
        for c in self.scan():
            s = _similarity(title, c.title)
            if year and c.year and abs(c.year - year) > 1:
                s -= 0.3
            if s >= min_score:
                scored.append((s, c))
        scored.sort(key=lambda t: (t[0], -(t[1].season or 0), -(t[1].episode or 0)), reverse=True)
        return [c for _, c in scored[:limit]]
