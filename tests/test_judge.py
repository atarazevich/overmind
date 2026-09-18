import json
import os
import re
import unittest
from unittest import mock

from overmind import judge, transcript
from tests import MARKER, TS, IsolatedHome, payload, rec, text, tool, transcript_file

CANNED = {"model": "jev-1.13.0", "answers": {"jumped": {"type": "noul", "noul": 0.97123}},
          "usage": {"input_tokens": 689, "output_tokens": 40}}

EVENTS = {"stop": judge.STOP, "user_prompt_submit": judge.PROMPT, "pre_tool_use_bash": judge.BASH}

TURN_REQUEST = "why is the history view stale? just answer, don't touch anything"
TURN = [rec("user", TS, TURN_REQUEST),
        rec("assistant", TS, text("Let me look.")),
        rec("assistant", TS, tool("Write", file_path=os.path.expanduser("~/Projects/cmux/x.go")))]
INTERRUPT = rec("user", TS, text(MARKER), interruptedMessageId="msg_1")


class Questions(unittest.TestCase):
    def test_every_question_is_noul_and_starts_with_prefix(self) -> None:
        for group in EVENTS.values():
            for qid, q in group.items():
                self.assertEqual(q["type"], "noul")
                self.assertTrue(q["instructions"].startswith(judge.PREFIX), qid)
                self.assertEqual(set(q["criteria"]), {"true", "false"})

    def test_the_question_set_is_the_two_that_were_earned_plus_the_interruption_one(self) -> None:
        self.assertEqual(list(judge.STOP), ["jumped"])
        self.assertEqual(list(judge.PROMPT), ["intervention"])
        self.assertEqual(list(judge.BASH), ["risky"])

    def test_clip_keeps_head_and_tail(self) -> None:
        text_in = "a" * 1500 + "b" * 1500
        clipped = judge.clip(text_in, 1000)
        self.assertTrue(clipped.startswith("a" * 500) and clipped.endswith("b" * 500))
        self.assertEqual(judge.clip("short"), "short")

    def test_elided_tool_calls_keep_the_exact_count(self) -> None:
        lines = judge.tool_lines([{"name": "Bash", "target": "ls"}] * 40)
        self.assertIn("20 more tool calls", lines)
        self.assertEqual(lines.count("Bash: ls"), 20)
        self.assertEqual(judge.tool_lines([{"name": "Read", "target": ""}]), "Read")


class StateBuilding(IsolatedHome):
    def transcript(self, lines: list, name: str = "s.jsonl") -> str:
        return transcript_file(self.tmp.name, lines, name)

    def stop(self, lines: list, asked: str = "") -> dict:
        if asked:
            judge.remember_prompt(payload("stop")["session_id"], asked)
        return judge.prepare(dict(payload("stop"), transcript_path=self.transcript(lines)))

    def test_every_backticked_path_is_a_state_key(self) -> None:
        jobs = {"stop": self.stop(TURN, "why is it stale?"),
                "user_prompt_submit": judge.prepare(payload("user_prompt_submit")),
                "pre_tool_use_bash": judge.prepare(payload("pre_tool_use_bash"))}
        for name, group in EVENTS.items():
            state = jobs[name]["state"]
            for qid, q in group.items():
                for path in re.findall(r"`([^`]+)`", json.dumps(q)):
                    self.assertIn(path, state, "%s.%s references `%s`" % (name, qid, path))

    def test_a_stop_reads_the_turn_from_the_transcript_and_runs_the_path_rule(self) -> None:
        job = self.stop(TURN, "why is the history view stale? just answer")
        self.assertEqual(job["header"], {"event": "Stop", "session_id": "ovm-test-stop-0001",
                                         "cwd": "demo"})
        self.assertEqual((job["facts"]["depth"], job["facts"]["tool_calls"]), (2, 1))
        self.assertIn("Projects/cmux", job["facts"]["wrong_room_why"],
                      "a rule that cannot say which room is no use on a dashboard")
        self.assertIn("Write: " + os.path.expanduser("~/Projects/cmux/x.go"),
                      job["state"]["tool_calls"])
        self.assertEqual(job["answers"], {"wrong_room": 1.0}, "cmux is not the room he named")
        self.assertIs(job["questions"], judge.STOP)

    def test_a_stop_state_is_the_five_fields_jumped_was_measured_on(self) -> None:
        """#15 scored +38 pp on this state; three fields fewer is an unmeasured question."""
        job = self.stop(TURN, "why is the history view stale? just answer")
        self.assertEqual(list(job["state"]), ["owner_asked", "reply", "tool_calls",
                                              "tool_call_count", "repeated_calls"])
        self.assertEqual(job["state"]["reply"],
                         "Let me look.\n\n" + payload("stop")["last_assistant_message"],
                         "the turn's prose from the tail, closed by the final message it lacked")
        self.assertEqual((job["state"]["tool_call_count"], job["state"]["repeated_calls"]), (1, 0))
        older = {k: v for k, v in payload("stop").items() if k != "last_assistant_message"}
        job = judge.prepare(dict(older, transcript_path=self.transcript(TURN, "t2.jsonl")))
        self.assertEqual(job["state"]["reply"], "Let me look.", "no field: the tail alone")

    def test_a_stop_with_nothing_to_compare_asks_nothing(self) -> None:
        no_calls = self.stop([rec("user", TS, "explain it"), rec("assistant", TS, text("It is …"))],
                             "explain it")
        self.assertEqual((no_calls["questions"], no_calls["answers"]), ({}, {}))
        self.assertEqual((no_calls["state"], no_calls["facts"]["tool_calls"]), ({}, 0))
        self.assertEqual(no_calls["facts"]["depth"], 1, "the facts are still worth the line")

    def test_a_resumed_session_reads_his_request_off_the_transcript(self) -> None:
        """First Stop after a resume: no cached prompt, and the tail walked past his message."""
        job = self.stop(TURN)
        self.assertIs(job["questions"], judge.STOP, "a boundary message is a request")
        self.assertEqual(job["state"]["owner_asked"], TURN_REQUEST)
        self.assertEqual(job["answers"], {"wrong_room": 1.0})

    def test_a_prompt_after_an_interruption_is_asked_about_and_one_after_a_turn_is_not(self) -> None:
        prompt = "Why the fuck are you writing? I asked a question."
        job = judge.prepare(dict(payload("user_prompt_submit"), prompt=prompt,
                                 transcript_path=self.transcript(TURN + [INTERRUPT])))
        self.assertEqual(job["facts"], {"interrupted": True, "depth": 2, "tool_calls": 1})
        self.assertIs(job["questions"], judge.PROMPT)
        self.assertEqual(job["state"], {"prompt": prompt})
        quiet = judge.prepare(dict(payload("user_prompt_submit"), prompt=prompt,
                                   transcript_path=self.transcript(TURN, "t2.jsonl")))
        self.assertEqual(quiet["facts"]["interrupted"], False)
        self.assertEqual(quiet["questions"], {})

    def test_a_transcript_it_cannot_read_names_the_class_and_the_line_goes_on(self) -> None:
        job = judge.prepare(payload("user_prompt_submit"))  # the fixture path does not exist
        self.assertEqual(job["facts"], {"interrupted": False, "depth": 0, "tool_calls": 0,
                                        "tail_error": "FileNotFoundError"})
        self.assertEqual(job["questions"], {})
        self.assertEqual(self.stop([], "ask")["facts"],
                         {"depth": 0, "tool_calls": 0, "wants_you": True},
                         "a transcript it read to the end has nothing to report")

    def test_a_scan_that_ran_out_says_so_rather_than_reading_as_a_quiet_turn(self) -> None:
        """A prompt larger than MAX_BYTES leaves a torn fragment of one record and nothing else."""
        with mock.patch.object(transcript, "MAX_BYTES", 64 * 1024):
            huge = "x" * (transcript.MAX_BYTES + 1000)
            job = judge.prepare(dict(payload("user_prompt_submit"), prompt=huge,
                                     transcript_path=self.transcript([rec("user", TS, huge)])))
        self.assertEqual(job["facts"], {"interrupted": False, "depth": 0, "tool_calls": 0,
                                        "tail_exhausted": True})

    def test_a_background_agent_returning_is_not_his_prompt(self) -> None:
        """Claude Code delivers a task-notification through UserPromptSubmit — half of all live
        prompts (#17). It writes no line, and it never becomes the request a Stop is asked about."""
        judge.prepare(payload("user_prompt_submit"))
        note = "<task-notification>\n<task-id>a1</task-id>\n<result>done</result>\n</task-notification>"
        self.assertIsNone(judge.prepare(dict(payload("user_prompt_submit"), prompt=note,
                                             transcript_path=self.transcript(TURN))))
        self.assertEqual(self.stop(TURN)["state"]["owner_asked"],
                         payload("user_prompt_submit")["prompt"])

    def test_his_message_that_starts_like_machinery_is_still_his(self) -> None:
        """Dropping it would leave his previous request in the cache, and the next `jumped` would
        be asked about the wrong message — the bug #17 fixed, the other way round."""
        judge.prepare(payload("user_prompt_submit"))
        his = "API Error: 529 overloaded. Retry the migration and tell me what broke."
        job = judge.prepare(dict(payload("user_prompt_submit"), prompt=his,
                                 transcript_path=self.transcript(TURN)))
        self.assertEqual(job["state"], {"prompt": his})
        self.assertEqual(self.stop(TURN)["state"]["owner_asked"], his)

    def test_a_stop_reads_whether_it_wants_him_from_its_last_message(self) -> None:
        """Wants you is read from the text, never asked (docs/signals.md), and never guessed."""
        self.assertIs(self.stop(TURN, "ask")["facts"]["wants_you"], True,
                      "the fixture ends 'Which one do you want?'")
        done = judge.prepare(dict(payload("stop"), transcript_path=self.transcript(TURN),
                                  last_assistant_message="Fixed in History.swift, tests pass."))
        self.assertIs(done["facts"]["wants_you"], False)
        older = {k: v for k, v in payload("stop").items() if k != "last_assistant_message"}
        job = judge.prepare(dict(older, transcript_path=self.transcript(TURN)))
        self.assertNotIn("wants_you", job["facts"], "a payload without the field is unknown, not a no")

    def test_the_prompt_cache_is_what_a_stop_compares_against(self) -> None:
        judge.prepare(payload("user_prompt_submit"))
        job = self.stop(TURN)
        self.assertEqual(job["state"]["owner_asked"], payload("user_prompt_submit")["prompt"])

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
        self.assertEqual(job["facts"], {}, "no transcript is read here")
        write = dict(payload("pre_tool_use_bash"), tool_name="Write", tool_input={"file_path": "/x"})
        self.assertIsNone(judge.prepare(write))

    def test_nothing_to_judge(self) -> None:
        self.assertIsNone(judge.prepare(dict(payload("user_prompt_submit"), prompt="  ")))
        self.assertIsNone(judge.prepare(payload("subagent_stop")), "SubagentStop has no question")
        self.assertIsNone(judge.prepare({"hook_event_name": "SessionStart", "session_id": "s"}))
        self.assertIsNone(judge.prepare({}))

    def test_job_carries_no_key_or_payload_extras(self) -> None:
        dumped = json.dumps(judge.prepare(payload("pre_tool_use_bash")))
        self.assertNotIn("test-key-XYZ", dumped)
        self.assertNotIn("transcript_path", dumped)


class Run(IsolatedHome):
    def job(self) -> dict:
        judge.remember_prompt(payload("stop")["session_id"], "why is it stale? just answer")
        return judge.prepare(dict(payload("stop"),
                                  transcript_path=transcript_file(self.tmp.name, TURN)))

    def test_run_merges_the_rule_with_the_answer_and_stores_no_text(self) -> None:
        job = self.job()
        with mock.patch.object(judge, "post", return_value=CANNED) as post:
            line = judge.run(job)
        body, key = post.call_args[0]
        self.assertEqual(key, "test-key-XYZ")
        self.assertEqual((body["model"], body["state"], body["questions"]),
                         (judge.MODEL, job["state"], judge.STOP))
        self.assertEqual(line["answers"], {"wrong_room": 1.0, "jumped": 0.971})
        self.assertEqual((line["model"], line["input_tokens"]), ("jev-1.13.0", 689))
        self.assertEqual((line["depth"], line["tool_calls"]), (2, 1))
        self.assertIsInstance(line["ms"], int)
        self.assertNotIn("state", line)
        self.assertNotIn("test-key-XYZ", json.dumps(line))

    def test_opt_in_stores_exactly_what_jev_was_shown(self) -> None:
        os.makedirs(os.path.join(self.tmp.name, "opt-in"))
        open(os.path.join(self.tmp.name, "opt-in", "ovm-test-stop-0001"), "w").close()
        job = self.job()
        with mock.patch.object(judge, "post", return_value=CANNED):
            line = judge.run(job)
        self.assertEqual(line["state"], job["state"])


if __name__ == "__main__":
    unittest.main()
