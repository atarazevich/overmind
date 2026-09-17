import json
import os
import re
import unittest
from unittest import mock

from overmind import judge
from tests import IsolatedHome, payload

CANNED = {"model": "jev-1.13.0", "answers": {"needs_owner": {"type": "noul", "noul": 0.97123},
                                              "claims_done": {"type": "noul", "noul": 0.02},
                                              "drifting": {"type": "noul", "noul": 0.1},
                                              "stuck": {"type": "noul", "noul": 0.0}},
          "usage": {"input_tokens": 689, "output_tokens": 40}}

EVENTS = {"stop": judge.STOP, "user_prompt_submit": judge.PROMPT, "pre_tool_use_bash": judge.BASH,
          "subagent_stop": judge.SUBAGENT}


class Questions(unittest.TestCase):
    def test_every_question_is_noul_and_starts_with_prefix(self) -> None:
        for group in EVENTS.values():
            for qid, q in group.items():
                self.assertEqual(q["type"], "noul")
                self.assertTrue(q["instructions"].startswith(judge.PREFIX), qid)
                self.assertEqual(set(q["criteria"]), {"true", "false"})

    def test_question_ids_per_event(self) -> None:
        self.assertEqual(list(judge.STOP), ["needs_owner", "claims_done", "drifting", "stuck"])
        self.assertEqual(list(judge.PROMPT), ["sharp_turn"])
        self.assertEqual(list(judge.BASH), ["risky"])
        self.assertEqual(list(judge.SUBAGENT), ["claims_done", "needs_parent_decision"])

    def test_clip_keeps_head_and_tail(self) -> None:
        text = "a" * 1500 + "b" * 1500
        clipped = judge.clip(text, 1000)
        self.assertTrue(clipped.startswith("a" * 500) and clipped.endswith("b" * 500))
        self.assertEqual(judge.clip("short"), "short")


class StateBuilding(IsolatedHome):
    def test_every_backticked_path_is_a_state_key(self) -> None:
        for name, group in EVENTS.items():
            state = judge.prepare(payload(name))["state"]
            for qid, q in group.items():
                for path in re.findall(r"`([^`]+)`", json.dumps(q)):
                    self.assertIn(path, state, "%s.%s references `%s`" % (name, qid, path))

    def test_stop_state(self) -> None:
        job = judge.prepare(payload("stop"))
        self.assertEqual(job["header"], {"event": "Stop", "session_id": "ovm-test-stop-0001", "cwd": "demo"})
        self.assertEqual(set(job["state"]), {"reply", "cwd", "background_tasks", "stop_hook_active", "last_user_prompt"})
        self.assertEqual(job["state"]["background_tasks"], 0)
        self.assertIs(job["state"]["stop_hook_active"], False)
        self.assertEqual(job["state"]["last_user_prompt"], "")
        self.assertIs(job["questions"], judge.STOP)

    def test_prompt_cache_feeds_next_prompt_and_stop(self) -> None:
        first = judge.prepare(payload("user_prompt_submit"))
        self.assertEqual(first["state"]["previous_prompt"], "")
        second = judge.prepare(dict(payload("user_prompt_submit"), prompt="Now add tests for it."))
        self.assertEqual(second["state"]["previous_prompt"], payload("user_prompt_submit")["prompt"])
        self.assertEqual(second["state"]["prompt"], "Now add tests for it.")
        stop = judge.prepare(payload("stop"))
        self.assertEqual(stop["state"]["last_user_prompt"], "Now add tests for it.")

    def test_cache_is_per_session_filename_safe_and_private(self) -> None:
        judge.prepare(dict(payload("user_prompt_submit"), session_id="../evil/../id", prompt="one"))
        self.assertEqual(judge.cached_prompt("../evil/../id"), "one")
        self.assertEqual(judge.cached_prompt("other-session"), "")
        (name,) = os.listdir(os.path.join(self.tmp.name, "prompts"))
        self.assertTrue(name.startswith("__"))
        self.assertEqual(os.stat(os.path.join(self.tmp.name, "prompts", name)).st_mode & 0o777, 0o600)

    def test_bash_only(self) -> None:
        job = judge.prepare(payload("pre_tool_use_bash"))
        self.assertEqual(job["header"]["tool_name"], "Bash")
        self.assertEqual(job["state"], {"command": "git push --force origin main", "cwd": "demo"})
        write = dict(payload("pre_tool_use_bash"), tool_name="Write", tool_input={"file_path": "/x"})
        self.assertIsNone(judge.prepare(write))

    def test_subagent_state(self) -> None:
        job = judge.prepare(payload("subagent_stop"))
        self.assertEqual(job["header"]["agent_type"], "Explore")
        self.assertEqual(set(job["state"]), {"reply", "agent_type"})
        self.assertIs(job["questions"], judge.SUBAGENT)

    def test_nothing_to_judge(self) -> None:
        self.assertIsNone(judge.prepare(dict(payload("stop"), last_assistant_message="  ")))
        self.assertIsNone(judge.prepare({"hook_event_name": "SessionStart", "session_id": "s"}))
        self.assertIsNone(judge.prepare({}))

    def test_job_carries_no_key_or_payload_extras(self) -> None:
        dumped = json.dumps(judge.prepare(payload("stop")))
        self.assertNotIn("test-key-XYZ", dumped)
        self.assertNotIn("transcript_path", dumped)


class Run(IsolatedHome):
    def test_run_builds_line_without_text(self) -> None:
        job = judge.prepare(payload("stop"))
        with mock.patch.object(judge, "post", return_value=CANNED) as post:
            line = judge.run(job)
        body, key = post.call_args[0]
        self.assertEqual(key, "test-key-XYZ")
        self.assertEqual((body["model"], body["state"], body["questions"]), (judge.MODEL, job["state"], judge.STOP))
        self.assertEqual(line["answers"], {"needs_owner": 0.971, "claims_done": 0.02, "drifting": 0.1, "stuck": 0.0})
        self.assertEqual(line["model"], "jev-1.13.0")
        self.assertEqual(line["input_tokens"], 689)
        self.assertIsInstance(line["ms"], int)
        self.assertEqual(line["state_source"], "payload")
        self.assertNotIn("text", line)
        self.assertNotIn("test-key-XYZ", json.dumps(line))

    def test_opt_in_stores_clipped_text_and_compared_prompt(self) -> None:
        os.makedirs(os.path.join(self.tmp.name, "opt-in"))
        open(os.path.join(self.tmp.name, "opt-in", "ovm-test-stop-0001"), "w").close()
        judge.prepare(payload("user_prompt_submit"))
        long_reply = "x" * (judge.MAX_TEXT + 100)
        job = judge.prepare(dict(payload("stop"), last_assistant_message=long_reply))
        with mock.patch.object(judge, "post", return_value=CANNED):
            line = judge.run(job)
        self.assertEqual(line["text"], judge.clip(long_reply))
        self.assertEqual(line["compared_to"], payload("user_prompt_submit")["prompt"])


if __name__ == "__main__":
    unittest.main()
