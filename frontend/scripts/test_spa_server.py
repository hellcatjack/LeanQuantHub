from __future__ import annotations

from functools import partial
from threading import Thread
from http.server import ThreadingHTTPServer

import httpx

from spa_server import SPARequestHandler


def _start_server(directory: str) -> tuple[ThreadingHTTPServer, str]:
    handler = partial(SPARequestHandler, directory=directory)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def test_spa_server_sets_no_cache_for_html(tmp_path):
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    httpd, base_url = _start_server(str(tmp_path))
    try:
        resp = httpx.get(f"{base_url}/data", timeout=2)
        cache_control = resp.headers.get("cache-control", "")
        assert "no-cache" in cache_control
    finally:
        httpd.shutdown()
