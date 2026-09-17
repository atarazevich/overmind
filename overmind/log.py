"""JSONL append and read for Overmind. Schema v1: ids, timestamps, numbers; text only on opt-in.

Runtime dir: ~/Library/Application Support/Overmind (override with OVERMIND_HOME, used by tests).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

V = 1
LABELS = ("y", "n", "s")  # the owner's mark on a fired signal: right, wrong, skip


def home() -> str:
    return os.environ.get("OVERMIND_HOME") or os.path.expanduser("~/Library/Application Support/Overmind")


def events_path() -> str:
    return os.path.join(home(), "events.jsonl")


def labels_path() -> str:
    return os.path.join(home(), "labels.jsonl")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def event_line(model: str, ms: int, input_tokens: int | None, answers: dict[str, float], **header: str) -> dict:
    """header: event, session_id, cwd and, when present, agent_type / tool_name."""
    return {"ts": now(), "v": V, **header, "model": model, "ms": ms, "input_tokens": input_tokens,
            "answers": answers, "state_source": "payload"}


def error_line(event: str, session_id: str, error: str) -> dict:
    return {"ts": now(), "v": V, "event": event, "session_id": session_id, "error": error}


def label_line(event_ts: str, session_id: str, question: str, prob: float, label: str) -> dict:
    """The owner's mark on one fired signal; prob is the event's own probability for that question."""
    return {"ts": now(), "event_ts": event_ts, "session_id": session_id, "question": question,
            "prob": prob, "label": label}


def append(line: dict, path: str | None = None) -> None:
    """One write() with O_APPEND, so concurrent writers never interleave lines. File is created 0600.
    Default path is the events log; the dashboard passes labels_path()."""
    path = path or events_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = (dumps(line) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def read_jsonl(path: str) -> list[dict]:
    try:
        with open(path, "rb") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(x) for x in lines if x.strip()]


def read(since: str | None = None, limit: int | None = None) -> list[dict]:
    """Event lines (errors included) with ts after `since`, the last `limit` of them.

    `since` is a ts as written by now() (same format, so string order is time order); None means all."""
    lines = read_jsonl(events_path())
    if since:
        lines = [x for x in lines if x.get("ts", "") > since]
    return lines[-limit:] if limit else lines
