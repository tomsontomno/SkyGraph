"""Local static server for the explorer UI.

Serves explorer/static at ``/`` and the built bundles at ``/bundles/``.  It binds to a loopback
address and never reaches out to the network; the only external requests are the OpenStreetMap tiles
the browser fetches for the Leaflet map, and the page falls back to its own SVG map without them.
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path
from typing import List
from urllib.parse import unquote, urlsplit

STATIC_DIR = Path(__file__).resolve().parent / 'static'


class ExplorerHandler(http.server.SimpleHTTPRequestHandler):
    """Static handler with two roots and no directory listings.

    Path handling drops ``.``/``..`` segments outright, so a request can never escape either root.
    """
    static_dir: Path = STATIC_DIR
    bundle_dir: Path = Path('.')
    verbose: bool = False

    def translate_path(self, path: str) -> str:
        parts = [p for p in unquote(urlsplit(path).path).split('/') if p and p not in ('.', '..')]
        if parts and parts[0] == 'bundles':
            root, rest = self.bundle_dir, parts[1:]
        else:
            root, rest = self.static_dir, parts
        target = root.joinpath(*rest) if rest else root / 'index.html'
        if target.is_dir():
            target = target / 'index.html'
        return str(target)

    def list_directory(self, path):
        self.send_error(404, "No directory listing")
        return None

    def log_message(self, fmt: str, *args) -> None:
        if self.verbose:
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def end_headers(self) -> None:
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def serve(bundle_dir: Path, host: str = '127.0.0.1', port: int = 8765, verbose: bool = False) -> List[str]:
    """Serve until interrupted.  Returns the log lines printed before the loop starts.

    Precondition: ``bundle_dir`` exists and holds at least one bundle plus index.json.
    """
    if not STATIC_DIR.is_dir():
        raise FileNotFoundError(f"static assets missing: {STATIC_DIR}")
    if not (bundle_dir / 'index.json').is_file():
        raise FileNotFoundError(f"no bundles in {bundle_dir}; run 'python -m explorer build' first")

    handler = type('BoundExplorerHandler', (ExplorerHandler,),
                   {'static_dir': STATIC_DIR, 'bundle_dir': bundle_dir, 'verbose': verbose})
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((host, port), handler) as httpd:
        lines = [f"Explorer läuft auf http://{host}:{port}/",
                 f"Bundles aus {bundle_dir}",
                 "Beenden mit Strg+C"]
        print('\n'.join(lines), flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer beendet.", flush=True)
        return lines
