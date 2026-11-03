"""El proxy que mide bytes, contra un origen HTTP local con soporte Range."""
from __future__ import annotations

import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.media.range_proxy import CountingRangeProxy

PAYLOAD = bytes(range(256)) * 4096          # 1 MiB


class _Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        if rng:
            start, _, end = rng.removeprefix("bytes=").partition("-")
            start = int(start)
            end = int(end) if end else len(PAYLOAD) - 1
            body = PAYLOAD[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(PAYLOAD)}")
        else:
            body = PAYLOAD
            self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def origin_url():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Origin)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/film.mkv"
    srv.shutdown()
    srv.server_close()


@pytest.mark.integration
def test_proxy_forwards_range_and_counts_only_requested_bytes(origin_url):
    with CountingRangeProxy(origin_url) as proxy:
        assert proxy.url.endswith("/media.mkv")
        req = urllib.request.Request(proxy.url, headers={"Range": "bytes=1000-1999"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read()
            assert resp.status == 206
            assert resp.headers["Content-Range"] == f"bytes 1000-1999/{len(PAYLOAD)}"
    assert body == PAYLOAD[1000:2000]
    assert proxy.upstream_bytes == 1000
    assert proxy.requests == ["GET bytes=1000-1999"]
