"""JSONL append and read for Overmind. Schema v1: ids, timestamps, numbers; text only on opt-in.

Runtime dir: ~/Library/Application Support/Overmind (override with OVERMIND_HOME, used by tests).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

V = 1


def home() -> str:
    return os.environ.get("OVERMIND_HOME") or os.path.expanduser("~/Library/Application Support/Overmind")


def events_path() -> str:
    return os.path.join(home(), "events.jsonl")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def event_line(model: str, ms: int, input_tokens: int | None, answers: dict[str, float], **header: str) -> dict:
    """header: event, session_id, cwd and, when present, agent_type / tool_name."""
    return {"ts": now(), "v": V, **header, "model": model, "ms": ms, "input_tokens": input_tokens,
            "answers": answers, "state_source": "payload"}


def error_line(event: str, session_id: str, error: str) -> dict:
    return {"ts": now(), "v": V, "event": event, "session_id": session_id, "error": error}


def append(line: dict) -> None:
    """One write() with O_APPEND, so concurrent hooks never interleave lines."""
    path = events_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = (json.dumps(line, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def tail(n: int) -> list[dict]:
    try:
        with open(events_path(), "rb") as f:
            lines = f.read().splitlines()[-n:]
    except FileNotFoundError:
        return []
    return [json.loads(x) for x in lines if x.strip()]
