"""Addon de Stremio de PRUEBA: hace de "addon propio" mientras se construye el real.

Cumple el contrato de docs/architecture/STREMIO_ADDON.md:
  - manifest con un catálogo de películas que acepta búsqueda por texto;
  - streams con enlaces http de archive.org (las 3 películas ya indexadas en el estudio);
  - un stream torrent de ejemplo, para ver que el estudio lo descarta;
  - opcional: sirve tus propios archivos con Range (--media-dir), como lo haría un Jellyfin/NAS.

Uso:
    python scripts/testing/mock_stremio_addon.py [--port 7010] [--media-dir E:/movies]
    # .env:
    STREMIO_ADDON_URL=http://127.0.0.1:7010/manifest.json
    STREMIO_OWN_HOSTS=127.0.0.1          # solo si usas --media-dir

Escucha solo en 127.0.0.1. Solo stdlib.
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

VIDEO_EXTS = {".mp4", ".m4v", ".mkv", ".webm", ".mov"}
IA = "https://archive.org/download"
FILMS = [
    {"id": "ylk:notld", "name": "Night of the Living Dead", "releaseInfo": "1968",
     "url": f"{IA}/Night.Of.The.Living.Dead_1080p/NightOfTheLivingDead_1080p.mkv"},
    {"id": "ylk:horror-express", "name": "Horror Express", "releaseInfo": "1972",
     "url": f"{IA}/HorrorExpress1972/HorrorExpress.mkv"},
    {"id": "ylk:grave-of-the-vampire", "name": "Grave of the Vampire", "releaseInfo": "1974",
     "url": f"{IA}/Grave_of_the_Vampire_movie/Grave-of-the-Vampire.mp4"},
]
MANIFEST = {
    "id": "org.youlikeit.mock",
    "version": "0.1.0",
    "name": "YouLikeIt (prueba)",
    "description": "Addon de prueba: dominio público de archive.org y, opcional, archivos propios.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["movie"],
    "idPrefixes": ["ylk:"],
    "catalogs": [{"type": "movie", "id": "ylk-pd", "name": "YouLikeIt",
                  "extra": [{"name": "search", "isRequired": False}]}],
}


def _local_films(media_dir: Path | None, port: int) -> list[dict]:
    if not media_dir or not media_dir.is_dir():
        return []
    out = []
    for p in sorted(media_dir.rglob("*")):
        if p.suffix.lower() in VIDEO_EXTS and p.is_file():
            rel = p.relative_to(media_dir).as_posix()
            year = re.search(r"(19\d\d|20\d\d)", p.stem)
            out.append({"id": f"ylk:file:{rel}", "name": re.sub(r"[._]+", " ", p.stem).strip(),
                        "releaseInfo": year.group(1) if year else "",
                        "url": f"http://127.0.0.1:{port}/media/{quote(rel)}",
                        "filename": p.name, "size": p.stat().st_size})
    return out


def make_handler(media_dir: Path | None, port: int):
    films = FILMS + _local_films(media_dir, port)
    by_id = {f["id"]: f for f in films}

    class Handler(BaseHTTPRequestHandler):
        def _json(self, obj: dict, status: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")     # lo pide la app de Stremio
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = unquote(self.path.split("?", 1)[0])
            if path == "/manifest.json":
                return self._json(MANIFEST)
            m = re.fullmatch(r"/catalog/movie/ylk-pd(?:/search=(.*))?\.json", path)
            if m:
                q = (m.group(1) or "").lower().strip()
                metas = [{"id": f["id"], "type": "movie", "name": f["name"], "releaseInfo": f["releaseInfo"]}
                         for f in films if q in f["name"].lower()]
                return self._json({"metas": metas})
            m = re.fullmatch(r"/meta/movie/(.+)\.json", path)
            if m and m.group(1) in by_id:
                f = by_id[m.group(1)]
                return self._json({"meta": {"id": f["id"], "type": "movie", "name": f["name"],
                                            "releaseInfo": f["releaseInfo"]}})
            m = re.fullmatch(r"/stream/movie/(.+)\.json", path)
            if m:
                f = by_id.get(m.group(1))
                if not f:
                    return self._json({"streams": []})
                streams = [{"name": "YouLikeIt", "title": f["name"], "url": f["url"],
                            "behaviorHints": {k: v for k, v in (("filename", f.get("filename")),
                                                                ("videoSize", f.get("size"))) if v}}]
                if f["id"] == "ylk:notld":   # ejemplo: el estudio debe descartarlo
                    streams.append({"name": "torrent (ejemplo)", "infoHash": "0" * 40})
                return self._json({"streams": streams})
            if path.startswith("/media/") and media_dir:
                return self._file(path[len("/media/"):])
            return self._json({"error": "not found"}, 404)

        def _file(self, rel: str) -> None:
            root = media_dir.resolve()
            target = (root / rel).resolve()
            if root not in target.parents or not target.is_file():
                return self._json({"error": "not found"}, 404)
            size = target.stat().st_size
            start, end = 0, size - 1
            rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start = int(rng.group(1))
                    end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                else:                                   # bytes=-N (los últimos N)
                    start = max(size - int(rng.group(2)), 0)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "video/mp4" if target.suffix.lower() in (".mp4", ".m4v") else
                             "video/x-matroska" if target.suffix.lower() == ".mkv" else "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            if self.command == "HEAD":
                return
            with target.open("rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        do_HEAD = do_GET  # noqa: N815 — mismos headers, sin cuerpo (el indexer pregunta Accept-Ranges con HEAD)

        def log_message(self, fmt: str, *args) -> None:
            print(f"[mock-addon] {self.command} {unquote(self.path)[:120]} -> {args[1] if len(args) > 1 else ''}")

    return Handler, films


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=7010)
    ap.add_argument("--media-dir", type=Path, default=None, help="Carpeta con tus videos (se sirven con Range)")
    args = ap.parse_args()
    handler, films = make_handler(args.media_dir, args.port)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Addon de prueba con {len(films)} películas en http://127.0.0.1:{args.port}/manifest.json  (Ctrl+C para salir)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
