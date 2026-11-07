"""Proxy HTTP local que reenvía pedidos con Range y CUENTA los bytes bajados.

Sirve para medir el criterio de la Fase 1 ("un clip de 10 s baja < 5 % del
archivo"): ffmpeg lee de http://127.0.0.1:<port>/... y el proxy pide al origen
solo los rangos que ffmpeg solicita. Usa urllib (stdlib) para no depender de
requests ni del guard de red de los tests.
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from urllib.parse import urlparse

_CHUNK = 64 * 1024
_PASS_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified")


class CountingRangeProxy:
    """Context manager:

        with CountingRangeProxy(url) as proxy:
            ffmpeg(... -i proxy.url ...)
        print(proxy.upstream_bytes, proxy.requests)
    """

    def __init__(self, upstream_url: str, *, timeout: float = 30.0):
        self.upstream_url = upstream_url
        self.timeout = timeout
        self.upstream_bytes = 0
        self.requests: list[str] = []          # Range pedidos (para depurar)
        self._lock = threading.Lock()
        self._resolved: str | None = None      # URL final tras redirects (dnXXX.archive.org)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        assert self._server is not None, "usar dentro de `with`"
        ext = PurePosixPath(urlparse(self.upstream_url).path).suffix
        return f"http://127.0.0.1:{self._server.server_address[1]}/media{ext}"

    def _add(self, n: int) -> None:
        with self._lock:
            self.upstream_bytes += n

    def __enter__(self) -> CountingRangeProxy:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"     # una respuesta por conexión: simple y robusto

            def log_message(self, *args):      # silencio
                pass

            def _forward(self, method: str) -> None:
                headers = {"User-Agent": "youlikeit-media/1.0"}
                rng = self.headers.get("Range")
                if rng:
                    headers["Range"] = rng
                with proxy._lock:
                    proxy.requests.append(f"{method} {rng or 'full'}")
                target = proxy._resolved or proxy.upstream_url
                req = urllib.request.Request(target, headers=headers, method=method)
                try:
                    resp = urllib.request.urlopen(req, timeout=proxy.timeout)
                except urllib.error.HTTPError as e:
                    self.send_response(e.code)
                    self.end_headers()
                    return
                with resp:
                    proxy._resolved = resp.geturl()
                    self.send_response(resp.status)
                    for h in _PASS_HEADERS:
                        if resp.headers.get(h):
                            self.send_header(h, resp.headers[h])
                    self.end_headers()
                    if method == "HEAD":
                        return
                    try:
                        while True:
                            chunk = resp.read(_CHUNK)
                            if not chunk:
                                break
                            proxy._add(len(chunk))
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        pass  # ffmpeg cerró: saltó a otro rango o terminó

            def do_GET(self):
                self._forward("GET")

            def do_HEAD(self):
                self._forward("HEAD")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
