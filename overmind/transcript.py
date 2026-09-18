"""The tail of a Claude Code session transcript: what the last turn did, and whether it was stopped.

The hook reads this on every prompt and every turn end, so it is bounded by construction: read the
file **backwards**, CHUNK_BYTES at a time, until the owner's previous message. Never a forward
read — a transcript here runs to 24 MB and the corpus to 310 MB.

The bounds count work, never time, so the same transcript gets the same answer on an idle machine
and on one running twenty agents (#17). Each bounds one thing that costs. MAX_BYTES bounds what is
read. MAX_LINES bounds the per-line cost, which is what one-token junk runs up. MAX_PARSED bounds
what parsing costs, in all: a line that would take the scan past it is not parsed, and one longer
than it is never even joined, only its start is kept, and a tool result is known from its start.
The distance his message sits back is mostly tool results — two thirds of a transcript's bytes,
one of them 7 MB — and a tool result is never his message nor an interruption, so the scan knows
one by its bytes and never parses it.

A scan that stops at a bound without meeting the owner's previous message says so in `exhausted`:
the counts are then lower bounds and `interrupted` is unknown rather than false. The line MAX_PARSED
stops it at could have been his message; unparsed, it cannot say. A scan that reached the start of
the file is not exhausted — there was nothing further back to read. Every other failure is the
caller's to ignore: a missing file, a permission error, a line torn in half by the MAX_BYTES edge
or by a write in flight, a record of an unexpected shape. `tail` returns what it read and names
the error class; it never raises.

This module is also the transcript vocabulary the offline passes read with — the interruption
markers, the junk prefixes, the block readers — imported from here by experiments/, so there is
one reading of a transcript in this repo and not two.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from io import BufferedReader

CHUNK_BYTES = 256 * 1024  # one read; his previous message is 65 KB back for the median prompt
MAX_BYTES = 8 * 1024 * 1024  # how far back the scan may read at all
MAX_LINES = 5000  # lines looked at, parsed or not; 2,000 already reach all the byte cap allows
MAX_PARSED = 3 * 1024 * 1024  # bytes parsed in all; a scan that reached him parsed 1.7 MB at most
MATCH_CHARS = 200  # enough of two messages to say they are the same message

# Verified corpus-wide in docs/research/own-transcripts.md §Method: these two strings, no others.
MARKER = "[Request interrupted by user"
# Bytes that only JSON structure can hold — inside a string every quote is escaped — so a line
# carrying them is a tool result, whatever its content says, and is known without parsing it.
# Claude Code writes them 221 bytes into every tool result of the owner's top-level transcripts,
# so a line's start is enough to find them in.
TOOL_RESULT = b'"type":"tool_result"'
# A background agent's return, which Claude Code delivers through UserPromptSubmit as if he had
# typed it. The payload ends at the closing tag or on one of these lines; the transcript record
# ends at the tag.
NOTIFICATION = ("<task-notification>", "</task-notification>")
NOTIFICATION_TRAILERS = ("Full transcript available at: ",
                         "Read the output file to retrieve the result: ")
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


def is_notification(prompt: str) -> bool:
    """Whether a UserPromptSubmit prompt is a background agent's return rather than his message.

    Only the whole shape counts: it opens with the tag, and after the last closing tag comes
    nothing, or one of Claude Code's trailer lines. A message he types that merely starts like
    machinery is his, and must not be dropped.
    """
    opening, closing = NOTIFICATION
    text = prompt.strip()
    if not text.startswith(opening) or closing not in text:
        return False
    after = text.rsplit(closing, 1)[1].strip()
    return not after or ("\n" not in after and after.startswith(NOTIFICATION_TRAILERS))


def is_interruption(record: dict) -> bool:
    return bool(record.get("interruptedMessageId")) or any(
        b.get("type") == "text" and str(b.get("text") or "").lstrip().startswith(MARKER)
        for b in blocks(record.get("message")))


def same_message(one: str, other: str) -> bool:
    """Whether two records are the same message, on their first MATCH_CHARS of collapsed text."""
    return " ".join(one.split())[:MATCH_CHARS] == " ".join(other.split())[:MATCH_CHARS]


def lines_back(handle: BufferedReader, end: int) -> Iterator[tuple[bytes, int]]:
    """(line, size) for each line before byte `end`, last first, read CHUNK_BYTES at a time and
    none past MAX_BYTES.

    A line up to MAX_PARSED bytes comes back whole. A longer one can never be parsed, so it comes
    back as its first chunk or two, never joined whole, however long it is: past MAX_PARSED only
    the pieces nearest its start are kept, and the size says the rest was dropped. The line the
    MAX_BYTES edge cuts through is half a record and is never yielded; the last line may be half a
    record too, from a write in flight, and fails to parse in `tail`.
    """
    floor = max(0, end - MAX_BYTES)
    later: list[bytes] = []  # the line that straddles chunks, its pieces last first
    size = 0
    while end > floor:
        start = max(floor, end - CHUNK_BYTES)
        handle.seek(start)
        pieces = handle.read(end - start).split(b"\n")
        end = start
        later.append(pieces[-1])  # a middle piece of that line, or its start
        size += len(pieces[-1])
        if size > MAX_PARSED:
            later = later[-2:]  # its start, at least a whole chunk of it, is all ever kept
        if len(pieces) > 1:
            yield b"".join(reversed(later)), size
            yield from ((piece, len(piece)) for piece in reversed(pieces[1:-1]))
            later, size = [pieces[0]], len(pieces[0])
    if not floor:
        yield b"".join(reversed(later)), size  # the first line of the file


def tail(path: str, submitted: str = "", said: str = "") -> dict:
    """The turn as it stands right now: {interrupted, depth, tool_calls, reply, owner_asked,
    exhausted, error}.

    `depth` is the assistant messages since the owner's previous message, `tool_calls` and `reply`
    what they did and said, all counted backwards until that message or until a bound stops it.
    `interrupted` is an interruption marker inside that same stretch: the owner pressed escape on
    this turn. `owner_asked` is the message the scan stopped at — his request, which a Stop needs
    and the prompt cache has only for a session this hook saw begin.

    `exhausted` is the scan stopping at a bound before that message: the counts are lower bounds,
    which under-reports rather than invents, and `interrupted` is unknown rather than false.
    Nothing with this flag may be read as a clean turn — a prompt longer than MAX_BYTES on its own
    leaves a torn fragment of one record and would otherwise look exactly like one.

    `submitted` is the prompt of a UserPromptSubmit event. Claude Code may or may not have written
    it to the transcript before the hook runs, so a first owner message equal to it is read past
    as the current one instead of being taken for the boundary.

    `said` is a Stop's `last_assistant_message`, the same problem from the other end: Claude Code
    writes the transcript asynchronously, and when Stop fires the turn's last records are often
    not on disk yet. It closes `reply` unless the last prose on disk is that same message.
    """
    out: dict = {"interrupted": False, "depth": 0, "tool_calls": [], "reply": "",
                 "owner_asked": "", "exhausted": False, "error": ""}
    steps: list[list[dict]] = []
    prose: list[str] = []
    skip_submitted = bool(submitted)
    parsed = 0
    try:
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            out["exhausted"] = True
            for seen, (raw, length) in enumerate(lines_back(handle, size)):
                if seen == MAX_LINES:
                    break
                if TOOL_RESULT in raw:
                    continue  # never his message, never an interruption: none in the corpus is
                parsed += length
                if parsed > MAX_PARSED:
                    break  # not a tool result, and past what may be parsed: it could be his message
                try:
                    record = json.loads(raw)
                except (ValueError, RecursionError):
                    continue  # blank, torn by an edge, or nested past what a parser will follow
                if not isinstance(record, dict) or record.get("isSidechain"):
                    continue
                kind = record.get("type")
                if kind == "assistant":
                    out["depth"] += 1
                    steps.append(tool_calls(record))
                    words = assistant_text(record)
                    if words:
                        prose.append(words)
                    continue
                if kind != "user":
                    continue
                if is_interruption(record):
                    out["interrupted"] = True
                    continue
                text = owner_message(record)
                if text is None:
                    continue  # a hook's injection, a slash expansion: part of the turn
                if skip_submitted and not out["depth"] and not out["interrupted"] \
                        and same_message(text, submitted):
                    skip_submitted = False
                    continue
                out["owner_asked"] = text  # his previous message: the turn starts here
                out["exhausted"] = False
                break
            else:
                out["exhausted"] = size > MAX_BYTES  # read to the start of the file, or to the cap
    except Exception as exc:  # noqa: BLE001 — the contract is: report the class, return what we have
        out["error"] = type(exc).__name__
    if said.strip() and not (prose and same_message(prose[0], said)):
        prose.insert(0, said.strip())
    out["tool_calls"] = [call for step in reversed(steps) for call in step]
    out["reply"] = "\n\n".join(reversed(prose))
    return out
