"""Tests for overmind.filter — JSONL parsing and filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from overmind.filter import Turn, parse_jsonl, tail_jsonl

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_conversation.jsonl"


def _write_jsonl(lines: list[dict], tmp_path: Path) -> str:
    """Write a list of dicts as JSONL to a file under tmp_path, return path."""
    path = tmp_path / "test.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")
    return str(path)


class TestParseJsonl:
    """Tests for parse_jsonl."""

    def test_user_text_string_content(self, tmp_path: Path) -> None:
        """User messages with plain string content are kept."""
        lines = [
            {
                "type": "user",
                "isSidechain": False,
                "message": {"role": "user", "content": "Fix the bug."},
                "timestamp": "2026-04-01T10:00:00.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 1
        assert turns[0].role == "user"
        assert turns[0].text == "Fix the bug."

    def test_user_text_array_content(self, tmp_path: Path) -> None:
        """User messages with array content keep only text blocks."""
        lines = [
            {
                "type": "user",
                "isSidechain": False,
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello there."},
                        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "result"}]},
                    ],
                },
                "timestamp": "2026-04-01T10:00:00.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 1
        assert turns[0].text == "Hello there."

    def test_assistant_text_blocks_kept(self, tmp_path: Path) -> None:
        """Assistant messages keep text blocks, drop thinking blocks."""
        lines = [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Let me think..."},
                        {"type": "text", "text": "Here is my answer."},
                    ],
                },
                "timestamp": "2026-04-01T10:00:05.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 1
        assert turns[0].role == "assistant"
        assert turns[0].text == "Here is my answer."

    def test_tool_use_entries_dropped(self, tmp_path: Path) -> None:
        """Assistant entries with only tool_use content produce no turn."""
        lines = [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
                    ],
                },
                "timestamp": "2026-04-01T10:00:06.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 0

    def test_tool_result_entries_dropped(self, tmp_path: Path) -> None:
        """User entries with only tool_result content produce no turn."""
        lines = [
            {
                "type": "user",
                "isSidechain": False,
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "ok"}]},
                    ],
                },
                "timestamp": "2026-04-01T10:00:07.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 0

    def test_sidechain_entries_skipped(self, tmp_path: Path) -> None:
        """Entries with isSidechain=True are skipped."""
        lines = [
            {
                "type": "assistant",
                "isSidechain": True,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Sub-agent research output."}],
                },
                "timestamp": "2026-04-01T10:00:21.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 0

    def test_non_message_types_skipped(self, tmp_path: Path) -> None:
        """Entries with types like permission-mode, file-history-snapshot, attachment are skipped."""
        lines = [
            {"type": "permission-mode", "permissionMode": "bypassPermissions", "sessionId": "test"},
            {"type": "file-history-snapshot", "messageId": "m1", "snapshot": {}, "isSnapshotUpdate": False},
            {
                "type": "attachment",
                "isSidechain": False,
                "attachment": {"type": "hook_success"},
                "timestamp": "2026-04-01T10:00:00.000Z",
            },
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 0

    def test_empty_text_after_filtering_skipped(self, tmp_path: Path) -> None:
        """Entries where all content blocks are non-text produce no turn."""
        lines = [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "Hmm..."},
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}},
                    ],
                },
                "timestamp": "2026-04-01T10:00:10.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 0

    def test_assistant_string_content(self, tmp_path: Path) -> None:
        """Assistant messages with plain string content are kept."""
        lines = [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {"role": "assistant", "content": "Done. The fix is applied."},
                "timestamp": "2026-04-01T10:00:15.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 1
        assert turns[0].text == "Done. The fix is applied."

    def test_sample_conversation_fixture(self) -> None:
        """Parse the sample fixture and verify expected turn count."""
        turns = parse_jsonl(str(SAMPLE))
        # The fixture has 20 lines. Expected text turns:
        # line 3: user text string
        # line 4: assistant text (thinking dropped, text kept)
        # line 7: assistant text + tool_use (text kept)
        # line 9: assistant string content
        # line 10: user text string
        # line 12: assistant text + tool_use (text kept)
        # line 15: assistant text
        # line 16: user text string
        # line 17: assistant text + tool_use (text kept)
        # line 19: assistant string content
        # line 20: user text string
        # line 21: assistant text
        # Sidechain (line 11) is skipped
        # Pure tool_use/tool_result lines are skipped
        assert len(turns) == 12
        roles = {t.role for t in turns}
        assert roles == {"user", "assistant"}

    def test_multiple_text_blocks_concatenated(self, tmp_path: Path) -> None:
        """Multiple text blocks in one message are joined with newlines."""
        lines = [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "First paragraph."},
                        {"type": "text", "text": "Second paragraph."},
                    ],
                },
                "timestamp": "2026-04-01T10:00:30.000Z",
            }
        ]
        turns = parse_jsonl(_write_jsonl(lines, tmp_path))
        assert len(turns) == 1
        assert turns[0].text == "First paragraph.\nSecond paragraph."


class TestTailJsonl:
    """Tests for tail_jsonl (byte-offset based)."""

    def test_tail_from_beginning(self) -> None:
        """With byte_offset=0, tail_jsonl returns the same turns as parse_jsonl."""
        turns_full = parse_jsonl(str(SAMPLE))
        turns_tail, _offset = tail_jsonl(str(SAMPLE), byte_offset=0)
        assert len(turns_full) == len(turns_tail)

    def test_tail_incremental(self) -> None:
        """Two consecutive tail_jsonl calls cover the full file without overlap."""
        turns_first, mid_offset = tail_jsonl(str(SAMPLE), byte_offset=0)
        assert mid_offset > 0

        # Read from where we left off
        turns_second, end_offset = tail_jsonl(str(SAMPLE), byte_offset=mid_offset)

        # Nothing new — the file hasn't grown
        assert turns_second == []
        assert end_offset == mid_offset

    def test_tail_partial_read(self, tmp_path: Path) -> None:
        """Appending to a file between calls yields only the new turns."""
        path = tmp_path / "growing.jsonl"
        line_a = json.dumps({
            "type": "user", "isSidechain": False,
            "message": {"role": "user", "content": "First."},
            "timestamp": "2026-04-01T10:00:00.000Z",
        })
        line_b = json.dumps({
            "type": "assistant", "isSidechain": False,
            "message": {"role": "assistant", "content": "Second."},
            "timestamp": "2026-04-01T10:00:01.000Z",
        })

        # Write first line
        path.write_text(line_a + "\n", encoding="utf-8")
        turns1, offset1 = tail_jsonl(str(path), byte_offset=0)
        assert len(turns1) == 1
        assert turns1[0].text == "First."

        # Append second line
        with path.open("a", encoding="utf-8") as f:
            f.write(line_b + "\n")

        turns2, offset2 = tail_jsonl(str(path), byte_offset=offset1)
        assert len(turns2) == 1
        assert turns2[0].text == "Second."
        assert offset2 > offset1

    def test_tail_past_end(self) -> None:
        """tail_jsonl with byte_offset beyond file size returns empty."""
        turns, offset = tail_jsonl(str(SAMPLE), byte_offset=999999)
        assert turns == []
