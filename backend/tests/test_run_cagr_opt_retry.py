import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from scripts import run_cagr_opt  # noqa: E402


class _SlowThenOkHandler(BaseHTTPRequestHandler):
    call_count = 0

    def do_GET(self):
        type(self).call_count += 1
        if type(self).call_count == 1:
            time.sleep(0.2)
        payload = {"ok": True, "calls": type(self).call_count}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


class _FailOnceHandler(BaseHTTPRequestHandler):
    call_count = 0

    def do_GET(self):
        type(self).call_count += 1
        if type(self).call_count == 1:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"error")
            return
        body = json.dumps({"ok": True, "calls": type(self).call_count}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return

def _serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_request_json_retries_on_timeout(tmp_path: Path) -> None:
    TCPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowThenOkHandler)
    host, port = server.server_address
    thread = _serve_in_thread(server)
    try:
        url = f"http://{host}:{port}/"
        result = run_cagr_opt._request_json(
            "GET",
            url,
            timeout=0.05,
            max_retries=2,
            retry_sleep=0.01,
        )
        assert result["ok"] is True
        assert result["calls"] >= 2
    finally:
        server.shutdown()
        thread.join(timeout=1)


def test_request_json_retries_on_http_500(tmp_path: Path) -> None:
    TCPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FailOnceHandler)
    host, port = server.server_address
    thread = _serve_in_thread(server)
    try:
        url = f"http://{host}:{port}/"
        result = run_cagr_opt._request_json(
            "GET",
            url,
            timeout=1,
            max_retries=1,
            retry_sleep=0.01,
        )
        assert result["ok"] is True
        assert result["calls"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=1)
