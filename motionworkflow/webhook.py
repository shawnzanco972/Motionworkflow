"""Callback-only receiver for Enhancor, behind a temporary Cloudflare tunnel.

Adapted from the Genjutsu workflow (MIT, Sirio Berati). Enhancor requires a
webhook URL; this receiver only accepts small JSON POSTs on a random path and
never touches jobs, files or keys. Polling stays the source of truth. The
public tunnel exposes this receiver only, never the app.
"""
from __future__ import annotations

import atexit
import http.server
import json
import re
import secrets
import shutil
import subprocess
import threading

_url: str | None = None  # this process's live callback URL
_started = False


def available() -> bool:
    return shutil.which("cloudflared") is not None


def start_tunnel(on_ready=print) -> threading.Thread:
    """Start the receiver and tunnel in a daemon thread for this process."""
    global _started
    _started = True
    executable = shutil.which("cloudflared")
    if not executable:
        raise RuntimeError("cloudflared is not installed. macOS: brew install cloudflared · "
                           "Linux: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
    route = "/callback/" + secrets.token_urlsafe(24)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_error(404)

        def do_POST(self):
            if self.path != route:
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if not 0 < size <= 65536:
                self.send_error(413)
                return
            try:
                json.loads(self.rfile.read(size))
            except ValueError:
                self.send_error(400)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"received":true}')

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = subprocess.Popen(
        [executable, "tunnel", "--url", f"http://127.0.0.1:{server.server_port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    atexit.register(proc.terminate)

    def watch():
        global _url
        try:
            for line in proc.stdout:
                match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if match and not _url:
                    _url = match.group(0) + route
                    on_ready("Enhancor callback tunnel ready.")
        finally:
            _url = None
            server.shutdown()

    thread = threading.Thread(target=watch, daemon=True, name="webhook-tunnel")
    thread.start()
    return thread



def current_url() -> str | None:
    return _url


def ensure(timeout: float = 45) -> str | None:
    """Return this process's callback URL, starting the tunnel once if needed."""
    import time

    if not _started and available():
        start_tunnel(on_ready=lambda _msg: None)
    deadline = time.time() + timeout
    while _started and time.time() < deadline:
        if _url:
            return _url
        time.sleep(0.5)
    return _url
