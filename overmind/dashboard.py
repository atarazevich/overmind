"""Local dashboard server: python3 -m overmind.dashboard → http://127.0.0.1:8767

Serves static/dashboard.html, vendored scripts under /vendor/, and JSON over events.jsonl, labels.jsonl
and ~/.claude/sessions. The page does its own aggregation from /events + /labels. Read-only except
POST /label, which appends to labels.jsonl. Event lines pass through as written: `state` — exactly
what Jev was shown — appears only when the hook stored it for an opted-in session.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from overmind import log

HOST, PORT = "127.0.0.1", 8767
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PAGE = os.path.join(STATIC, "dashboard.html")
VENDOR = os.path.join(STATIC, "vendor")
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css"}
DEFAULT_LIMIT = 20000  # a day is ~2000 events
MAX_BODY = 64 * 1024


def sessions_dir() -> str:
    return os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "sessions")


def sessions() -> list[dict]:
    """Live Claude Code sessions from <config>/sessions/<pid>.json; unreadable or shapeless files are skipped."""
    out = []
    for path in sorted(glob.glob(os.path.join(sessions_dir(), "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and isinstance(d.get("sessionId"), str):
            out.append({"session_id": d["sessionId"], "name": d.get("name"), "cwd": d.get("cwd"),
                        "status": d.get("status")})
    return out


def label_from(body: object) -> dict:
    """Validate a POST /label body against the events log and build the line; ValueError names the fault.
    The stored probability is the event's own answer, never the client's."""
    if not isinstance(body, dict):
        raise ValueError("body is not an object")
    for key in ("event_ts", "session_id", "question"):
        if not isinstance(body.get(key), str) or not body[key]:
            raise ValueError(key)
    if body.get("label") not in log.LABELS:
        raise ValueError("label")
    answers = next((e.get("answers") for e in reversed(log.read())
                    if e.get("ts") == body["event_ts"] and e.get("session_id") == body["session_id"]), None)
    if not isinstance(answers, dict) or body["question"] not in answers:
        raise ValueError("event")
    return log.label_line(body["event_ts"], body["session_id"], body["question"],
                          float(answers[body["question"]]), body["label"])


class Handler(BaseHTTPRequestHandler):
    timeout = 5  # a client that stops mid-body cannot hold a thread

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            with open(PAGE, "rb") as f:
                return self.send_bytes(200, TYPES[".html"], f.read())
        if url.path.startswith("/vendor/"):
            return self.send_vendor(url.path[len("/vendor/"):])
        if url.path == "/events":
            try:
                limit = int(query.get("limit", [DEFAULT_LIMIT])[0])
                if limit < 1:
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"error": "limit"})
            return self.send_json(200, log.read(query.get("since", [None])[0] or None, limit))
        if url.path == "/sessions":
            return self.send_json(200, sessions())
        if url.path == "/labels":
            return self.send_json(200, log.read_jsonl(log.labels_path()))
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/label":
            return self.send_json(404, {"error": "not found"})
        try:
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                raise ValueError("content-type")
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                raise ValueError("body")
            line = label_from(json.loads(self.rfile.read(length).decode("utf-8")))
        except (ValueError, UnicodeDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})
        log.append(line, log.labels_path())
        self.send_json(200, line)

    def send_vendor(self, name: str) -> None:
        """A file directly inside static/vendor, by real path, or 404."""
        path = os.path.realpath(os.path.join(VENDOR, name))
        if os.path.dirname(path) != os.path.realpath(VENDOR) or not os.path.isfile(path):
            return self.send_json(404, {"error": "not found"})
        with open(path, "rb") as f:
            self.send_bytes(200, TYPES.get(os.path.splitext(path)[1], "application/octet-stream"), f.read())

    def send_json(self, code: int, obj: object) -> None:
        self.send_bytes(code, "application/json; charset=utf-8", log.dumps(obj).encode("utf-8"))

    def send_bytes(self, code: int, content_type: str, data: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        """The page polls every 5 s; only failures reach stderr."""
        if isinstance(code, int) and code >= 400:
            super().log_request(code, size)


def main() -> None:
    with ThreadingHTTPServer((HOST, PORT), Handler) as server:
        print("Overmind dashboard: http://%s:%d/" % server.server_address, file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
