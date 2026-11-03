"""tiny local dashboard: `mobileforge serve` then open http://localhost:8765"""

from __future__ import annotations

import http.server
import mimetypes
import urllib.parse
from pathlib import Path

from .config import RESULTS_DIR, RUNS_DIR
from .report import index_page
from .state import CheckpointStore


def serve(port: int = 8765) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet
            pass

        def send(self, body: bytes, ctype: str = "text/html; charset=utf-8", code: int = 200):
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            if path in ("/", "/index.html"):
                summary = RESULTS_DIR / "summary.html"
                frag = summary.read_text(encoding="utf-8") if summary.exists() else ""
                return self.send(index_page(CheckpointStore().runs(), frag).encode("utf-8"))
            for prefix, root in (("/runs/", RUNS_DIR), ("/results/", RESULTS_DIR)):
                if path.startswith(prefix):
                    target = (root / path[len(prefix):]).resolve()
                    # never serve anything outside the runs and results folders
                    if root.resolve() in target.parents and target.is_file() and "repo" not in target.relative_to(root.resolve()).parts[1:2]:
                        ctype = mimetypes.guess_type(str(target))[0] or "text/plain"
                        return self.send(target.read_bytes(), ctype)
            self.send(b"not found", "text/plain", 404)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"dashboard running at http://localhost:{port}  (ctrl+c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
