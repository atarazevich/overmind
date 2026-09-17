#!/usr/bin/python3
"""Overmind hook: one Claude Code event on stdin → one Jev request → one JSONL line.

Fail-safe contract: exit 0 always, never write to stdout, finish the synchronous part in < 50 ms.
The parent reads stdin, builds the state, forks; the child (own session, stdio on /dev/null)
does the network call and the append. Any exception becomes an error line.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def detach() -> bool:
    """Fork. Parent returns False and exits; child returns True in its own session with stdio closed."""
    if os.fork():
        return False
    os.setsid()
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    return True


def main() -> None:
    event = sid = ""
    job = None
    try:
        from overmind import judge, log

        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise TypeError("payload is not an object")
        event, sid = str(payload.get("hook_event_name") or ""), str(payload.get("session_id") or "")
        job = judge.prepare(payload)
        if job is None:
            return
        if not job["questions"]:  # nothing worth paying for: the facts are the line
            log.append(log.fact_line(job["facts"], job["answers"], **job["header"]))
            return
        if not os.environ.get(judge.KEY_ENV):
            log.append(log.error_line(event, sid, "no_key", job["facts"]))
            return
        if detach():
            log.append(judge.run(job))
    except Exception as exc:  # noqa: BLE001 — the contract is: log the class, exit 0
        try:
            from overmind import log

            log.append(log.error_line(event, sid, type(exc).__name__, job["facts"] if job else None))
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
