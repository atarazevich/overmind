"""The tail of a Claude Code session transcript: what the last turn did, and whether it was stopped.

The synchronous part of the hook reads this, so it is bounded by construction: seek to the last
TAIL_BYTES, keep the last MAX_LINES of that window, scan them **backwards** to the owner's
previous message. Never a forward read, never a second seek — a transcript here runs to 24 MB and
the corpus to 310 MB.

Two bounds and not one, because bytes bound the work only while the lines are records: the fullest
256 KB window in the corpus holds 244 of them and costs ~1 ms, while 256 KB of one-token junk is
20,000 lines and costs 46 ms of the parent's 50 ms budget. The byte cap bounds what is read, the
line cap bounds what is parsed, and together they bound the time (≤5 ms for a full window either
way, measured).

A scan that reaches the edge of that window without meeting the owner's previous message says so
in `exhausted`: the counts are then lower bounds and `interrupted` is unknown rather than false.
A window that simply reached the start of the file is not exhausted — there was nothing further
back to read. Every other failure is the caller's to ignore: a missing file, a permission error, a
line torn in half by the window edge or by a write in flight, a record of an unexpected shape.
`tail` returns what it read and names the error class; it never raises.

This module is also the transcript vocabulary the offline passes read with — the interruption
markers, the junk prefixes, the block readers — imported from here by experiments/, so there is
one reading of a transcript in this repo and not two.
"""
from __future__ import annotations

import json
import os
import re

TAIL_BYTES = 256 * 1024  # covers the whole turn for 96% of the owner's 46 interruptions
MAX_LINES = 2000  # records parsed out of that window; the corpus's fullest window holds 244
MATCH_CHARS = 200  # enough of two messages to say they are the same message

# Verified corpus-wide in docs/research/own-transcripts.md §Method: these two strings, no others.
MARKER = "[Request interrupted by user"
JUNK_PREFIXES = ("<command-", "<local-command", "<bash-", "Caveat:", "<system-reminder",
                 "<task-notification>", "This session is being continued", "API Error",
                 "<analysis>", "<policy-", MARKER)
SLASH = "<command-name>"
TARGET_KEYS = ("file_path", "path", "command", "url", "pattern", "notebook_path", "query",
               "subagent_type", "description", "name", "prompt")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def strip_reminders(text: str) -> str:
    return REMINDER.sub("", text)


def blocks(message: object) -> list[dict]:
    """Content blocks of a transcript message, normalised: a bare string becomes one text block."""
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def tool_target(block: dict) -> str:
    """The one field of a tool call that says what it acts on: a path, a command, a url."""
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        return ""
    for key in TARGET_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def tool_calls(record: dict) -> list[dict]:
    """Every tool call an assistant record makes, in the order it makes them."""
    return [{"name": str(b.get("name") or "?"), "target": tool_target(b)}
            for b in blocks(record.get("message")) if b.get("type") == "tool_use"]


def assistant_text(record: dict) -> str:
    """The prose of one assistant message: its text blocks, without its tool calls."""
    said = (str(b.get("text") or "").strip() for b in blocks(record.get("message"))
            if b.get("type") == "text")
    return "\n".join(part for part in said if part)


def record_text(record: dict) -> str | None:
    """Concatenated text of a user record, or None when it carries a tool result instead."""
    parts = []
    for block in blocks(record.get("message")):
        if block.get("type") == "tool_result":
            return None
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return strip_reminders("\n".join(parts)).strip()


def slash_name(text: str) -> str | None:
    """`/gu` out of `<command-message>gu</command-message><command-name>/gu</command-name>`."""
    if SLASH not in text:
        return None
    name = text.split(SLASH, 1)[1].split("</command-name>", 1)[0].strip()
    args = text.split("<command-args>", 1)[1].split("</command-args>", 1)[0].strip() \
        if "<command-args>" in text else ""
    return (name + " " + args).strip() or None


def human_text(record: dict) -> str | None:
    """The owner's own words in a user record, or None when it is not one of his messages."""
    if record.get("isMeta") or record.get("toolUseResult") is not None:
        return None
    text = record_text(record)
    if text is None or not text or text.startswith(JUNK_PREFIXES):
        return None
    return text


def owner_message(record: dict) -> str | None:
    """His words, or the slash command he ran — both are him taking his turn."""
    text = human_text(record)
    if text is not None:
        return text
    raw = record_text(record)
    return slash_name(raw) if raw and raw.startswith("<command-") else None


def is_interruption(record: dict) -> bool:
    return bool(record.get("interruptedMessageId")) or any(
        b.get("type") == "text" and str(b.get("text") or "").lstrip().startswith(MARKER)
        for b in blocks(record.get("message")))


def same_message(one: str, other: str) -> bool:
    """Whether two records are the same message, on their first MATCH_CHARS of collapsed text."""
    return " ".join(one.split())[:MATCH_CHARS] == " ".join(other.split())[:MATCH_CHARS]


def window(path: str) -> tuple[list[bytes], bool]:
    """The last TAIL_BYTES of the file as whole lines, and whether anything was left out of them.

    The first line of a seeked window is half a record and is dropped rather than guessed at; the
    last line may be half a record too, from a write in flight, and fails to parse in `tail`.
    """
    with open(path, "rb") as handle:
        start = max(0, os.fstat(handle.fileno()).st_size - TAIL_BYTES)
        handle.seek(start)
        chunk = handle.read(TAIL_BYTES)
    lines = chunk.split(b"\n")
    if start:
        lines = lines[1:]
    return lines[-MAX_LINES:], bool(start) or len(lines) > MAX_LINES


def tail(path: str, submitted: str = "") -> dict:
    """The turn as it stands right now: {interrupted, depth, tool_calls, reply, owner_asked,
    exhausted, error}.

    `depth` is the assistant messages since the owner's previous message, `tool_calls` and `reply`
    what they did and said, all counted backwards until that message or until the window runs out.
    `interrupted` is an interruption marker inside that same stretch: the owner pressed escape on
    this turn. `owner_asked` is the message the scan stopped at — his request, which a Stop needs
    and the prompt cache has only for a session this hook saw begin.

    `exhausted` is the window running out before that message: the counts are lower bounds, which
    under-reports rather than invents, and `interrupted` is unknown rather than false. Nothing with
    this flag may be read as a clean turn — a prompt longer than the window on its own leaves a
    torn fragment of one record and would otherwise look exactly like one.

    `submitted` is the prompt of a UserPromptSubmit event. Claude Code may or may not have written
    it to the transcript before the hook runs, so a first owner message equal to it is read past
    as the current one instead of being taken for the boundary.
    """
    out: dict = {"interrupted": False, "depth": 0, "tool_calls": [], "reply": "",
                 "owner_asked": "", "exhausted": False, "error": ""}
    try:
        lines, cut = window(path)
    except Exception as exc:  # noqa: BLE001 — the contract is: report the class, return what we have
        out["error"] = type(exc).__name__
        return out
    out["exhausted"] = cut
    steps: list[list[dict]] = []
    prose: list[str] = []
    skip_submitted = bool(submitted)
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (ValueError, RecursionError):
            continue  # a line torn by the window edge, or nested past what a parser will follow
        if not isinstance(record, dict) or record.get("isSidechain"):
            continue
        kind = record.get("type")
        if kind == "assistant":
            out["depth"] += 1
            steps.append(tool_calls(record))
            said = assistant_text(record)
            if said:
                prose.append(said)
            continue
        if kind != "user":
            continue
        if is_interruption(record):
            out["interrupted"] = True
            continue
        text = owner_message(record)
        if text is None:
            continue  # a tool result, a hook's injection, a slash expansion: part of the turn
        if skip_submitted and not out["depth"] and not out["interrupted"] \
                and same_message(text, submitted):
            skip_submitted = False
            continue
        out["owner_asked"] = text  # his previous message: the turn starts here
        out["exhausted"] = False
        break
    out["tool_calls"] = [call for step in reversed(steps) for call in step]
    out["reply"] = "\n\n".join(reversed(prose))
    return out
