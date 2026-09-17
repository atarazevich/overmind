import json
import os
import stat
import unittest

from overmind import log
from tests import IsolatedHome


class Log(IsolatedHome):
    def test_append_creates_file_one_line_per_call(self) -> None:
        log.append({"a": 1})
        log.append({"b": "ünïcode"})
        with open(log.events_path(), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual([json.loads(x) for x in lines], [{"a": 1}, {"b": "ünïcode"}])
        self.assertEqual(stat.S_IMODE(os.stat(log.events_path()).st_mode), 0o600)

    def test_event_line_shape(self) -> None:
        line = log.event_line("jev-1.13.0", 812, 689, {"needs_owner": 0.9}, event="Stop", session_id="sid", cwd="demo")
        self.assertEqual(list(line), ["ts", "v", "event", "session_id", "cwd", "model", "ms", "input_tokens",
                                      "answers", "state_source"])
        self.assertEqual(line["v"], 1)
        self.assertTrue(line["ts"].endswith("+00:00") and len(line["ts"]) == 29)
        full = log.event_line("m", 1, 2, {}, event="PreToolUse", session_id="sid", cwd="demo", tool_name="Bash")
        self.assertEqual(full["tool_name"], "Bash")

    def test_error_line_shape(self) -> None:
        self.assertEqual(set(log.error_line("Stop", "sid", "no_key")), {"ts", "v", "event", "session_id", "error"})

    def test_tail(self) -> None:
        self.assertEqual(log.tail(5), [])
        for i in range(4):
            log.append({"i": i})
        self.assertEqual([x["i"] for x in log.tail(2)], [2, 3])


if __name__ == "__main__":
    unittest.main()
