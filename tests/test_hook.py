"""The fail-safe contract: exit 0, silent stdout, one line per event, network mocked."""
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.error
from unittest import mock

from overmind import hook, judge, log
from tests import HERE, MARKER, TS, IsolatedHome, payload, rec, text, tool, transcript_file

HOOK = os.path.join(os.path.dirname(HERE), "overmind", "hook.py")
CANNED = {"model": "jev-1.13.0", "answers": {"risky": {"type": "noul", "noul": 0.98}},
          "usage": {"input_tokens": 371, "output_tokens": 12}}
INTERRUPTED_TURN = [rec("user", TS, "where does the coordinator hold the observable?"),
                    rec("assistant", TS, text("Let me check.")),
                    rec("assistant", TS, tool("Bash", command="rg observable app/")),
                    rec("user", TS, text(MARKER), interruptedMessageId="msg_1")]


class HookContract(IsolatedHome):
    def run_hook(self, stdin: bytes, key: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if not key:
            env.pop(judge.KEY_ENV)
        return subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, env=env, timeout=10)

    def piped(self, event: dict, key: bool = True) -> dict:
        proc = self.run_hook(json.dumps(event).encode(), key=key)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        return log.read(limit=1)[0]

    def test_a_prompt_after_an_interruption_is_recorded_with_its_depth(self) -> None:
        """The free label: he pressed escape, and this is the message that says which kind."""
        path = transcript_file(self.tmp.name, INTERRUPTED_TURN)
        line = self.piped(dict(payload("user_prompt_submit"), transcript_path=path,
                               prompt="stop. I asked a question."), key=False)
        self.assertEqual((line["interrupted"], line["depth"], line["tool_calls"]), (True, 2, 1))
        self.assertEqual(line["error"], "no_key", "the facts survive a Jev call that never happened")

    def test_a_prompt_after_an_ordinary_turn_costs_no_request_at_all(self) -> None:
        path = transcript_file(self.tmp.name, INTERRUPTED_TURN[:-1] + [rec("assistant", TS,
                                                                          text("It is in the coordinator."))])
        line = self.piped(dict(payload("user_prompt_submit"), transcript_path=path,
                               prompt="now fix it"), key=False)
        self.assertEqual((line["interrupted"], line["depth"]), (False, 3))
        self.assertEqual((line["answers"], line.get("error")), ({}, None), "facts, no request")
        self.assertNotIn("model", line)

    def test_missing_key_logs_no_key_where_a_question_would_have_been_asked(self) -> None:
        for name in ("stop", "user_prompt_submit", "pre_tool_use_bash"):
            with open(os.path.join(HERE, "payloads", name + ".json"), "rb") as f:
                proc = self.run_hook(f.read(), key=False)
            self.assertEqual((proc.returncode, proc.stdout), (0, b""), name)
        lines = log.read(limit=100)
        self.assertEqual([x["event"] for x in lines], ["Stop", "UserPromptSubmit", "PreToolUse"])
        self.assertEqual([x.get("error") for x in lines], [None, None, "no_key"],
                         "only the Bash call had a question to ask without a transcript")
        self.assertEqual([x["tail_error"] for x in lines[:2]], ["FileNotFoundError"] * 2)

    def test_malformed_payload_logs_error_class(self) -> None:
        with open(os.path.join(HERE, "payloads", "malformed.json"), "rb") as f:
            proc = self.run_hook(f.read())
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        self.assertEqual(log.read(limit=100)[0]["error"], "JSONDecodeError")
        proc = self.run_hook(b"[1, 2]")
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        self.assertEqual(log.read(limit=100)[1]["error"], "TypeError")
        proc = self.run_hook(b"")
        self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        self.assertEqual(len(log.read(limit=100)), 2, "empty stdin is nothing to judge, not an error")

    def test_nothing_to_judge_writes_nothing_even_without_key(self) -> None:
        body = json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Write",
                           "tool_input": {"file_path": "/x"}}).encode()
        for key in (True, False):
            proc = self.run_hook(body, key=key)
            self.assertEqual((proc.returncode, proc.stdout), (0, b""))
        with open(os.path.join(HERE, "payloads", "subagent_stop.json"), "rb") as f:
            self.assertEqual(self.run_hook(f.read()).returncode, 0)
        self.assertEqual(log.read(limit=100), [])

    def test_broken_import_still_exits_zero_and_silent(self) -> None:
        """A copy of hook.py whose sibling package lacks judge/log: the import inside main() fails."""
        os.makedirs(os.path.join(self.tmp.name, "overmind"))
        open(os.path.join(self.tmp.name, "overmind", "__init__.py"), "w").close()
        with open(HOOK, "rb") as src, open(os.path.join(self.tmp.name, "overmind", "hook.py"), "wb") as dst:
            dst.write(src.read())
        with open(os.path.join(HERE, "payloads", "stop.json"), "rb") as f:
            proc = subprocess.run([sys.executable, dst.name], input=f.read(), capture_output=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, b"", b""))
        self.assertEqual(log.read(limit=100), [])


class InProcess(IsolatedHome):
    """main() with detach() patched to 'child', so the network path runs synchronously and mocked."""

    def setUp(self) -> None:
        super().setUp()
        with open(os.path.join(HERE, "payloads", "pre_tool_use_bash.json"), encoding="utf-8") as f:
            self.payload = f.read()

    def run_main(self, post, body: str = "") -> list:
        with mock.patch.object(hook, "detach", return_value=True), mock.patch.object(judge, "post", post), \
                mock.patch.object(sys, "stdin", io.StringIO(body or self.payload)), \
                mock.patch.object(sys, "stdout", io.StringIO()) as out:
            hook.main()
        self.assertEqual(out.getvalue(), "")
        return log.read(limit=10)

    def test_an_interruption_and_its_judgment_land_on_one_line(self) -> None:
        body = json.dumps(dict(payload("user_prompt_submit"),
                               transcript_path=transcript_file(self.tmp.name, INTERRUPTED_TURN),
                               prompt="stop. I asked a question."))
        answered = {"model": "jev-1.13.0", "usage": {"input_tokens": 120},
                    "answers": {"intervention": {"type": "noul", "noul": 0.934}}}
        line = self.run_main(mock.Mock(return_value=answered), body)[0]
        self.assertEqual((line["interrupted"], line["depth"], line["tool_calls"]), (True, 2, 1))
        self.assertEqual(line["answers"], {"intervention": 0.934})
        self.assertEqual(line["v"], 2)

    def test_success_line(self) -> None:
        lines = self.run_main(mock.Mock(return_value=CANNED))
        self.assertEqual(lines[0]["answers"], {"risky": 0.98})
        self.assertEqual(lines[0]["tool_name"], "Bash")

    def test_network_failure_becomes_error_line_that_keeps_its_facts(self) -> None:
        lines = self.run_main(mock.Mock(side_effect=urllib.error.URLError("timed out")))
        self.assertEqual(lines[0]["error"], "URLError")
        self.assertEqual((lines[0]["event"], lines[0]["answers"]), ("PreToolUse", {}))

    def test_a_failed_call_still_keeps_the_verdict_the_rule_gave_for_free(self) -> None:
        """`wrong_room` costs nothing and was already decided; the network is not its problem."""
        judge.remember_prompt(payload("stop")["session_id"], "why is the history view stale?")
        turn = [rec("assistant", TS, text("Let me fix it.")),
                rec("assistant", TS, tool("Write", file_path=os.path.expanduser("~/Projects/cmux/x.go")))]
        body = json.dumps(dict(payload("stop"),
                               transcript_path=transcript_file(self.tmp.name, turn, "stop.jsonl")))
        line = self.run_main(mock.Mock(side_effect=urllib.error.URLError("timed out")), body)[0]
        self.assertEqual((line["error"], line["answers"]), ("URLError", {"wrong_room": 1.0}))
        self.assertEqual(line["depth"], 2, "and the facts it had already read")
        self.assertIn("Projects/cmux", line["wrong_room_why"])

    def test_bad_response_becomes_error_line(self) -> None:
        lines = self.run_main(mock.Mock(return_value={"unexpected": True}))
        self.assertEqual(lines[0]["error"], "KeyError")


if __name__ == "__main__":
    unittest.main()
