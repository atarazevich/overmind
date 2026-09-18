"""JSONL append and read for Overmind. Schema v2: ids, timestamps, numbers; text only on opt-in.

Runtime dir: ~/Library/Application Support/Overmind (override with OVERMIND_HOME, used by tests).

**v2 (2026-09-18, #16).** Lines carry the facts read from the payload and the transcript tail
beside the answers: `interrupted` / `depth` / `tool_calls` on UserPromptSubmit, `depth` /
`tool_calls` / `wants_you` on Stop, `tail_error` when the tail failed, `tail_exhausted` when it
ran out before the owner's previous message, `wrong_room_why` when that rule fired. A line with no
`model` is a line no Jev request was made for — the facts and the free rules alone.
v1 lines stay exactly as written and the dashboard reads both: it keys on `answers` and `ts`,
which neither version moved.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

V = 2
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


def fact_line(facts: dict, answers: dict[str, float] | None = None, **header: str) -> dict:
    """A line written without asking Jev: the header, the facts, and whatever the rules decided.

    header: event, session_id, cwd and, when present, tool_name. facts: what the payload and the
    transcript tail said — free, read rather than judged, and the denominators of every rate."""
    return {"ts": now(), "v": V, **header, **facts, "answers": answers or {}}


def event_line(model: str, ms: int, input_tokens: int | None, answers: dict[str, float],
               facts: dict | None = None, **header: str) -> dict:
    """A fact line plus what the Jev request returned and cost."""
    return {**fact_line(facts or {}, answers, **header), "model": model, "ms": ms,
            "input_tokens": input_tokens}


def error_line(event: str, session_id: str, error: str, facts: dict | None = None,
               answers: dict[str, float] | None = None) -> dict:
    """What is known when something threw. The facts and the rules' own verdicts ride along: a
    transcript tail that already said the owner interrupted, and a rule that already said the turn
    wrote in another room, are not worth losing to a failed network call — both were free."""
    return {"ts": now(), "v": V, "event": event, "session_id": session_id, **(facts or {}),
            "answers": answers or {}, "error": error}


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
