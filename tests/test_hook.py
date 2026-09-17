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
from tests import HERE, IsolatedHome

HOOK = os.path.join(os.path.dirname(HERE), "overmind", "hook.py")
CANNED = {"model": "jev-1.13.0", "answers": {"risky": {"type": "noul", "noul": 0.98}},
          "usage": {"input_tokens": 371, "output_tokens": 12}}


class HookContract(IsolatedHome):
    def run_hook(self, stdin: bytes, key: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if not key:
            env.pop(judge.KEY_ENV)
        return subprocess.run([sys.executable, HOOK], input=stdin, capture_output=True, env=env, timeout=10)

    def test_missing_key_logs_no_key(self) -> None:
        for name in ("stop", "user_prompt_submit", "pre_tool_use_bash", "subagent_stop"):
            with open(os.path.join(HERE, "payloads", name + ".json"), "rb") as f:
                proc = self.run_hook(f.read(), key=False)
            self.assertEqual((proc.returncode, proc.stdout), (0, b""), name)
        self.assertEqual([x["error"] for x in log.read(limit=100)], ["no_key"] * 4)
        self.assertEqual([x["event"] for x in log.read(limit=100)], ["Stop", "UserPromptSubmit", "PreToolUse", "SubagentStop"])

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

    def run_main(self, post) -> list:
        with mock.patch.object(hook, "detach", return_value=True), mock.patch.object(judge, "post", post), \
                mock.patch.object(sys, "stdin", io.StringIO(self.payload)), \
                mock.patch.object(sys, "stdout", io.StringIO()) as out:
            hook.main()
        self.assertEqual(out.getvalue(), "")
        return log.read(limit=10)

    def test_success_line(self) -> None:
        lines = self.run_main(mock.Mock(return_value=CANNED))
        self.assertEqual(lines[0]["answers"], {"risky": 0.98})
        self.assertEqual(lines[0]["tool_name"], "Bash")

    def test_network_failure_becomes_error_line(self) -> None:
        lines = self.run_main(mock.Mock(side_effect=urllib.error.URLError("timed out")))
        self.assertEqual(lines[0]["error"], "URLError")
        self.assertEqual(lines[0]["event"], "PreToolUse")

    def test_bad_response_becomes_error_line(self) -> None:
        lines = self.run_main(mock.Mock(return_value={"unexpected": True}))
        self.assertEqual(lines[0]["error"], "KeyError")


if __name__ == "__main__":
    unittest.main()
