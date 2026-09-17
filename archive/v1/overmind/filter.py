"""JSONL parser for Claude Code conversation files.

Parses conversation JSONL, strips tool calls and non-text content,
returns only user and assistant text turns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Turn:
    """A single conversation turn with text content only."""

    role: str          # "user" or "assistant"
    text: str          # concatenated text content
    timestamp: str     # ISO 8601
    turn_number: int   # line number in JSONL (1-based)


def _extract_text(content: str | list[dict]) -> str:
    """Extract text from a message content field.

    Content is either a plain string or a list of typed blocks.
    For lists, only blocks with type "text" are kept.
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts)

    return ""


def _parse_line(line: str, line_number: int) -> Turn | None:
    """Parse a single JSONL line into a Turn, or None if it should be skipped."""
    try:
        entry = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    # Skip sidechain messages (sub-agent conversations)
    if entry.get("isSidechain", False):
        return None

    # Only keep user and assistant message types
    entry_type = entry.get("type", "")
    if entry_type not in ("user", "assistant"):
        return None

    message = entry.get("message")
    if not isinstance(message, dict):
        return None

    role = message.get("role", "")
    if role not in ("user", "assistant"):
        return None

    content = message.get("content")
    if content is None:
        return None

    text = _extract_text(content)
    if not text.strip():
        return None

    timestamp = entry.get("timestamp", "")

    return Turn(
        role=role,
        text=text.strip(),
        timestamp=timestamp,
        turn_number=line_number,
    )


def parse_jsonl(path: str) -> list[Turn]:
    """Parse a JSONL file, return only user+assistant text turns."""
    turns: list[Turn] = []
    filepath = Path(path)

    with filepath.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            turn = _parse_line(line, line_number)
            if turn is not None:
                turns.append(turn)

    return turns


def tail_jsonl(path: str, byte_offset: int = 0) -> tuple[list[Turn], int]:
    """Read new data since byte_offset, return filtered turns and new offset.

    Seeks directly to byte_offset instead of re-reading the entire file.
    Returns (new_turns, new_byte_offset) so the caller can pass the offset
    back on the next call.
    """
    turns: list[Turn] = []
    filepath = Path(path)

    with filepath.open("r", encoding="utf-8") as f:
        f.seek(byte_offset)

        # We don't know the absolute line number after seeking, so we
        # track a relative index from the offset.  For turn_number we
        # use the byte position of the line start as a stable identifier.
        for line in f:
            line_start = byte_offset
            byte_offset += len(line.encode("utf-8"))
            stripped = line.strip()
            if not stripped:
                continue
            turn = _parse_line(stripped, line_start)
            if turn is not None:
                turns.append(turn)

    return turns, byte_offset
