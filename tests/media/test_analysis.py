"""Descarga segmentada en paralelo (con reanudación) + comando de una pasada."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.media import analysis

PAYLOAD = bytes((i * 7) % 251 for i in range(3 * 1024 * 1024 + 123))     # ~3 MiB, no múltiplo


class _Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    hits: list = []

    def log_message(self, *a):
        pass

    def _headers(self, status, length, extra=None):
        self.send_response(status)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def do_HEAD(self):
        self._headers(200, len(PAYLOAD))

    def do_GET(self):
        rng = self.headers.get("Range")
        type(self).hits.append(rng)
        start, _, end = rng.removeprefix("bytes=").partition("-")
        start, end = int(start), int(end) if end else len(PAYLOAD) - 1
        body = PAYLOAD[start:end + 1]
        self._headers(206, len(body), {"Content-Range": f"bytes {start}-{end}/{len(PAYLOAD)}"})
        self.wfile.write(body)


@pytest.fixture
def origin():
    _Origin.hits = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Origin)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/proxy.mp4"
    srv.shutdown()
    srv.server_close()


@pytest.mark.unit
def test_plan_chunks_covers_everything_once():
    chunks = analysis.plan_chunks(10, 4)
    assert chunks == [(0, 3), (4, 7), (8, 9)]
    assert analysis.plan_chunks(8, 4) == [(0, 3), (4, 7)]


@pytest.mark.integration
def test_download_parallel_is_byte_exact(origin, tmp_path):
    dest = analysis.download_parallel(origin, tmp_path / "proxy.mp4", connections=4,
                                      chunk_bytes=256 * 1024)
    assert dest.read_bytes() == PAYLOAD
    assert len(_Origin.hits) == len(analysis.plan_chunks(len(PAYLOAD), 256 * 1024))
    assert not (tmp_path / "proxy.mp4.parts.json").exists()


@pytest.mark.integration
def test_download_parallel_resumes_only_missing_chunks(origin, tmp_path):
    chunk = 256 * 1024
    chunks = analysis.plan_chunks(len(PAYLOAD), chunk)
    dest = tmp_path / "proxy.mp4"
    part = tmp_path / "proxy.mp4.part"
    done = list(range(0, len(chunks), 2))                # la mitad ya bajada
    buf = bytearray(len(PAYLOAD))
    for i in done:
        s, e = chunks[i]
        buf[s:e + 1] = PAYLOAD[s:e + 1]
    part.write_bytes(bytes(buf))
    (tmp_path / "proxy.mp4.parts.json").write_text(json.dumps({"size": len(PAYLOAD), "done": done}))

    analysis.download_parallel(origin, dest, connections=3, chunk_bytes=chunk)
    assert dest.read_bytes() == PAYLOAD
    assert len(_Origin.hits) == len(chunks) - len(done)


@pytest.mark.unit
def test_single_pass_cmd_outputs_audio_and_scdet_in_one_read():
    cmd = analysis.build_single_pass_cmd("proxy.mp4", "a.wav", scdet_threshold=12)
    assert cmd.count("-i") == 1
    assert "a.wav" in cmd and cmd[-3:] == ["-f", "null", "-"]
    assert "scale=320:-2,scdet=threshold=12" in cmd
    assert "-loglevel" not in cmd            # scdet reporta en nivel info
