from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from aeo_audit import audit_url


class handler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        url = (params.get("url") or [""])[0].strip()
        self.run_audit(url)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            self.send_json({"error": "Request body must be JSON."}, status=400)
            return
        self.run_audit(str(payload.get("url", "")).strip())

    def run_audit(self, url: str) -> None:
        if not url:
            self.send_json({"error": "Provide a URL to audit."}, status=400)
            return
        if not url.startswith(("http://", "https://")):
            self.send_json({"error": "URL must start with http:// or https://."}, status=400)
            return
        try:
            self.send_json(audit_url(url, timeout=12))
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=502)
