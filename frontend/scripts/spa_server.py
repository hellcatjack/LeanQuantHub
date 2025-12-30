import argparse
import http.server
from pathlib import Path
from urllib.parse import urlparse


class SPARequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def _rewrite_path(self) -> None:
        parsed = urlparse(self.path)
        request_path = parsed.path.lstrip("/")
        if not request_path:
            return
        target = Path(self.directory or ".") / request_path
        if not target.exists():
            self.path = "/index.html"

    def do_GET(self) -> None:
        self._rewrite_path()
        super().do_GET()

    def do_HEAD(self) -> None:
        self._rewrite_path()
        super().do_HEAD()


def main() -> None:
    parser = argparse.ArgumentParser(description="Static SPA server with fallback.")
    parser.add_argument("--dir", default="dist", help="Directory to serve")
    parser.add_argument("--bind", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8081, help="Port to listen on")
    args = parser.parse_args()

    handler = lambda *hargs, **hkwargs: SPARequestHandler(  # noqa: E731
        *hargs, directory=args.dir, **hkwargs
    )
    server_class = http.server.ThreadingHTTPServer
    server_class.allow_reuse_address = True
    with server_class((args.bind, args.port), handler) as httpd:
        httpd.daemon_threads = True
        print(f"Serving {args.dir} on {args.bind}:{args.port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
