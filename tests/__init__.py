import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))


TS = "2026-09-18T10:00:00.000Z"
MARKER = "[Request interrupted by user for tool use]"


def payload(name: str) -> dict:
    with open(os.path.join(HERE, "payloads", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def rec(kind: str, ts: str, content: object, **extra: object) -> str:
    """One transcript record as Claude Code writes it: type, timestamp, message, and the flags."""
    line = {"type": kind, "timestamp": ts, "sessionId": "s-1", "cwd": "/tmp/demo",
            "message": {"role": kind, "content": content}}
    line.update(extra)
    return json.dumps(line, separators=(",", ":"))  # compact, as Claude Code writes it


def text(body: str) -> list:
    return [{"type": "text", "text": body}]


def tool(name: str, **tool_input: object) -> list:
    return [{"type": "tool_use", "name": name, "input": tool_input}]


def transcript_file(folder: str, lines: list, name: str = "s.jsonl", end: str = "\n") -> str:
    """Write a transcript fixture and return its path, for a payload's `transcript_path`."""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + end)
    return path


class IsolatedHome(unittest.TestCase):
    """A throwaway OVERMIND_HOME and a fake key in the environment for the duration of each test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"OVERMIND_HOME": self.tmp.name, "TYPESAFE_API_KEY": "test-key-XYZ"})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()
