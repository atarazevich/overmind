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
        facts = {"depth": 4, "tool_calls": 7, "state_source": "payload+tail"}
        line = log.event_line("jev-1.13.0", 812, 689, {"jumped": 0.9}, facts,
                              event="Stop", session_id="sid", cwd="demo")
        self.assertEqual(list(line), ["ts", "v", "event", "session_id", "cwd", "depth", "tool_calls",
                                      "state_source", "answers", "model", "ms", "input_tokens"])
        self.assertEqual(line["v"], 2)
        self.assertTrue(line["ts"].endswith("+00:00") and len(line["ts"]) == 29)
        full = log.event_line("m", 1, 2, {}, None, event="PreToolUse", session_id="sid", cwd="demo",
                              tool_name="Bash")
        self.assertEqual(full["tool_name"], "Bash")

    def test_fact_line_is_a_line_no_request_was_made_for(self) -> None:
        line = log.fact_line({"interrupted": False, "depth": 2}, event="UserPromptSubmit",
                             session_id="sid", cwd="demo")
        self.assertEqual(list(line), ["ts", "v", "event", "session_id", "cwd", "interrupted",
                                      "depth", "answers"])
        self.assertEqual((line["answers"], line["interrupted"]), ({}, False))
        self.assertNotIn("model", line, "no model means no request was made")

    def test_error_line_keeps_the_facts_it_already_read(self) -> None:
        self.assertEqual(set(log.error_line("Stop", "sid", "no_key")),
                         {"ts", "v", "event", "session_id", "error"})
        with_facts = log.error_line("UserPromptSubmit", "sid", "URLError", {"interrupted": True})
        self.assertEqual(with_facts["interrupted"], True)
        self.assertEqual(with_facts["error"], "URLError")

    def test_read_since_and_limit(self) -> None:
        self.assertEqual(log.read(), [])
        for i in range(4):
            log.append({"ts": "2026-09-17T19:00:0%d.000+00:00" % i, "i": i})
        log.append({"ts": "2026-09-17T19:00:04.000+00:00", "i": 4, "error": "no_key"})
        ids = lambda lines: [x["i"] for x in lines]  # noqa: E731
        self.assertEqual(ids(log.read()), [0, 1, 2, 3, 4], "error lines are included")
        self.assertEqual(ids(log.read(since="2026-09-17T19:00:01.000+00:00")), [2, 3, 4], "strictly after")
        self.assertEqual(ids(log.read(limit=2)), [3, 4])
        self.assertEqual(ids(log.read(since="2026-09-17T19:00:00.000+00:00", limit=2)), [3, 4])

    def test_label_line_and_append_to_labels_path(self) -> None:
        line = log.label_line("2026-09-17T19:00:00.000+00:00", "sid", "needs_owner", 0.91, "y")
        self.assertEqual(list(line), ["ts", "event_ts", "session_id", "question", "prob", "label"])
        log.append(line, log.labels_path())
        self.assertEqual(log.read_jsonl(log.labels_path()), [line])
        self.assertEqual(stat.S_IMODE(os.stat(log.labels_path()).st_mode), 0o600)
        self.assertFalse(os.path.exists(log.events_path()), "labels never touch the events log")


if __name__ == "__main__":
    unittest.main()
