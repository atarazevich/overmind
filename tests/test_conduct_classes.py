"""The conduct-classes experiment: question contract and turn segmentation.

No network and no real transcripts here — segmentation runs against a synthetic .jsonl written
into a temp dir, so the test says what the segmenter does rather than what the corpus happens
to contain.
"""
import importlib.util
import json
import os
import re
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "conduct_classes", os.path.join(os.path.dirname(HERE), "experiments", "conduct_classes.py"))
cc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cc)


def rec(kind: str, ts: str, content: object, **extra: object) -> str:
    line = {"type": kind, "timestamp": ts, "sessionId": "s-1", "cwd": "/tmp/demo",
            "message": {"role": kind, "content": content}}
    line.update(extra)
    return json.dumps(line)


def text(body: str) -> list:
    return [{"type": "text", "text": body}]


def tool(name: str, **tool_input: object) -> list:
    return [{"type": "tool_use", "name": name, "input": tool_input}]


class Questions(unittest.TestCase):
    def test_every_question_is_noul_and_starts_with_prefix(self) -> None:
        from overmind import judge
        for key, question in cc.CONDUCT.items():
            self.assertEqual(question["type"], "noul", key)
            self.assertTrue(question["instructions"].startswith(judge.PREFIX), key)
            self.assertEqual(set(question["criteria"]), {"true", "false"}, key)

    def test_every_backticked_path_is_a_state_key(self) -> None:
        turn = {"tool_calls": [{"name": "Bash", "target": "ls"}], "tool_call_count": 1,
                "reply": "done"}
        state = cc.turn_state(turn, "look at it", "/tmp/demo")
        for key, question in cc.CONDUCT.items():
            for path in re.findall(r"`([^`]+)`", json.dumps(question)):
                self.assertIn(path, state, "%s references `%s`" % (key, path))

    def test_classes_are_the_eight_conduct_signals_and_name_the_two_that_are_not(self) -> None:
        self.assertEqual(list(cc.CONDUCT), ["no_receipts", "too_much", "wrong_room", "jumped",
                                            "yap", "lost_you", "missed_point", "spinning"])
        self.assertEqual(set(cc.NOT_MEASURABLE), {"rule_dropped", "burn"})
        self.assertEqual(cc.KEY_ALIASES["spinning"], "stuck")  # docs/signals.md calls it that


class State(unittest.TestCase):
    def test_long_values_are_clipped_in_the_middle_not_at_the_ends(self) -> None:
        turn = {"tool_calls": [], "tool_call_count": 0,
                "reply": "A" * cc.MAX_REPLY_CHARS + "Z" * cc.MAX_REPLY_CHARS}
        state = cc.turn_state(turn, "B" * 4000 + "Y" * 4000, "/tmp/demo")
        self.assertTrue(state["owner_request"].startswith("B") and state["owner_request"].endswith("Y"))
        self.assertLessEqual(len(state["owner_request"]), cc.MAX_OWNER_CHARS + 3)

    def test_elided_tool_calls_keep_the_exact_count(self) -> None:
        turn = {"tool_calls": [{"name": "Bash", "target": "x"}] * 4, "tool_call_count": 40,
                "reply": "ok"}
        state = cc.turn_state(turn, "go", "/tmp/demo")
        self.assertEqual(state["tool_call_count"], 40)
        self.assertIn("36 more tool calls", state["tool_calls"])


class Segmentation(unittest.TestCase):
    def transcript(self, lines: list) -> str:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.tmp.name, "s-1.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        return path

    def test_owner_and_agent_turns_alternate_and_tool_calls_land_on_the_agent_turn(self) -> None:
        path = self.transcript([
            rec("user", "2026-09-01T10:00:00Z", "fix the parser"),
            rec("assistant", "2026-09-01T10:00:05Z", text("On it.")),
            rec("assistant", "2026-09-01T10:00:06Z", tool("Read", file_path="/a/parser.py")),
            rec("user", "2026-09-01T10:00:07Z", [{"type": "tool_result", "content": "..."}]),
            rec("assistant", "2026-09-01T10:00:09Z", text("Fixed.")),
            rec("user", "2026-09-01T10:00:20Z", "thanks"),
        ])
        turns = cc.segment(path, "s-1")["turns"]
        self.assertEqual([t["role"] for t in turns], ["owner", "agent", "owner"])
        agent = turns[1]
        self.assertEqual(agent["tool_call_count"], 1)
        self.assertEqual(agent["tool_calls"], [{"name": "Read", "target": "/a/parser.py"}])
        self.assertEqual(agent["assistant_messages"], 3)
        self.assertEqual(agent["reply"], "On it.\n\nFixed.")
        self.assertIs(agent["interrupted"], False)
        self.assertIs(agent["has_request"], True)
        self.assertEqual(agent.owner_request, "fix the parser")

    def test_an_interruption_closes_the_turn_and_takes_his_next_message_as_the_quote(self) -> None:
        path = self.transcript([
            rec("user", "2026-09-01T10:00:00Z", "why is it slow?"),
            rec("assistant", "2026-09-01T10:00:02Z", tool("Write", file_path="/a/fix.py")),
            rec("user", "2026-09-01T10:00:03Z", text("[Request interrupted by user for tool use]"),
                interruptedMessageId="msg_1"),
            rec("user", "2026-09-01T10:00:40Z", "Don't write. I asked a question."),
            rec("assistant", "2026-09-01T10:00:45Z", text("Understood.")),
        ])
        turns = cc.segment(path, "s-1")["turns"]
        self.assertEqual([t["role"] for t in turns], ["owner", "agent", "owner", "agent"])
        self.assertIs(turns[1]["interrupted"], True)
        self.assertEqual(turns[1]["owner_next_message"], "Don't write. I asked a question.")
        self.assertNotIn("owner_next_message", turns[3])

    def test_a_slash_command_is_an_owner_turn_and_its_expansion_is_the_request(self) -> None:
        path = self.transcript([
            rec("user", "2026-09-01T10:00:00Z",
                "<command-message>gu</command-message>\n<command-name>/gu</command-name>"),
            rec("user", "2026-09-01T10:00:00Z", text("Read-only. Never commit."), isMeta=True),
            rec("assistant", "2026-09-01T10:00:02Z", text("Reading.")),
        ])
        turns = cc.segment(path, "s-1")["turns"]
        self.assertEqual(turns[0]["role"], "owner")
        self.assertEqual(turns[0]["source"], "slash")
        self.assertEqual(turns[0]["text"], "/gu — Read-only. Never commit.")
        self.assertIs(turns[1]["has_request"], True)

    def test_sidechain_and_junk_records_are_ignored(self) -> None:
        path = self.transcript([
            rec("user", "2026-09-01T10:00:00Z", "<task-notification>agent done</task-notification>"),
            rec("assistant", "2026-09-01T10:00:01Z", text("sub"), isSidechain=True),
            rec("user", "2026-09-01T10:00:02Z", "real message"),
            rec("assistant", "2026-09-01T10:00:03Z", text("real reply")),
        ])
        turns = cc.segment(path, "s-1")["turns"]
        self.assertEqual([t["role"] for t in turns], ["owner", "agent"])
        self.assertEqual(turns[0]["text"], "real message")
        self.assertIs(turns[1]["has_request"], True)

    def test_a_turn_before_any_request_is_marked_unscoreable(self) -> None:
        path = self.transcript([
            rec("assistant", "2026-09-01T10:00:00Z", text("resumed work")),
            rec("user", "2026-09-01T10:00:10Z", "ok"),
        ])
        turns = cc.segment(path, "s-1")["turns"]
        self.assertIs(turns[0]["has_request"], False)


class Verdicts(unittest.TestCase):
    def row(self, **kw: float) -> dict:
        base = {"n_correction": 10, "fire_correction": 0.0, "fire_clean": 0.0, "lift": 0.0,
                "mean_lift": 0.0}
        base.update(kw)
        return base

    def test_the_verdicts_say_what_a_person_would_say(self) -> None:
        self.assertEqual(cc.verdict(self.row(n_correction=2)), "no evidence")
        self.assertEqual(cc.verdict(self.row(fire_clean=0.9, fire_correction=0.95, lift=0.05)),
                         "fires on everything")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.0, fire_clean=0.02, lift=-0.02)),
                         "never fires")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.2, fire_clean=0.4, lift=-0.2)),
                         "fires backwards")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.6, fire_clean=0.3, lift=0.3)),
                         "separates")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.31, fire_clean=0.3, lift=0.01)),
                         "does not separate")


if __name__ == "__main__":
    unittest.main()
