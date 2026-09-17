"""The conduct-classes experiment: question contract, turn segmentation, truncation, rules.

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

from tests import rec, text, tool

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "conduct_classes", os.path.join(os.path.dirname(HERE), "experiments", "conduct_classes.py"))
cc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cc)


def a_turn(steps: list, request: str = "look at it", index: int = 0) -> cc.Turn:
    """A closed Turn from [(prose, [(tool_name, target), ...]), ...] — one entry per message."""
    turn = cc.Turn(index, "2026-09-01T10:00:00Z", request, index - 1)
    for body, tools in steps:
        content = (text(body) if body else []) + [
            {"type": "tool_use", "name": name,
             "input": {"command" if name == "Bash" else "file_path": target}}
            for name, target in tools]
        turn.add({"timestamp": "2026-09-01T10:00:00Z",
                  "message": {"role": "assistant", "content": content}})
    return turn.close()


class Questions(unittest.TestCase):
    def test_every_question_is_noul_and_starts_with_prefix(self) -> None:
        from overmind import judge
        for label, questions in (("R1", cc.R1), ("R2", cc.R2)):
            for key, question in questions.items():
                self.assertEqual(question["type"], "noul", label + "." + key)
                self.assertTrue(question["instructions"].startswith(judge.PREFIX), key)
                self.assertEqual(set(question["criteria"]), {"true", "false"}, key)

    def test_every_backticked_path_is_a_key_of_its_own_state(self) -> None:
        view = cc.view_of(a_turn([("done", [("Bash", "ls")])]))
        for questions, state in ((cc.R1, cc.r1_state(view, "look at it", "/tmp/demo")),
                                 (cc.R2, cc.r2_state(view, "look at it", "/tmp/demo"))):
            for key, question in questions.items():
                for path in re.findall(r"`([^`]+)`", json.dumps(question)):
                    self.assertIn(path, state, "%s references `%s`" % (key, path))

    def test_round_two_covers_round_one_plus_caving_and_names_what_it_cannot_measure(self) -> None:
        self.assertEqual(list(cc.R1), ["no_receipts", "too_much", "wrong_room", "jumped",
                                       "yap", "lost_you", "missed_point", "spinning"])
        self.assertEqual(list(cc.R2), ["too_much", "jumped", "lost_you", "missed_point",
                                       "spinning", "caving"])
        self.assertEqual(list(cc.RULES), ["yap", "wrong_room", "no_receipts"])
        self.assertEqual(set(cc.R2) | set(cc.RULES), set(cc.R1) | {"caving"})
        self.assertEqual(set(cc.RULES), set(cc.RULE_NOTES), "every rule says what it fires on")
        self.assertEqual(set(cc.RULES), set(cc.RULE_LIMITS), "every rule says what it gets wrong")
        self.assertEqual(set(cc.NOT_MEASURABLE), {"rule_dropped", "burn"})
        self.assertEqual(cc.KEY_ALIASES["spinning"], "stuck")  # docs/signals.md calls it that

    def test_every_hand_tag_maps_to_a_class_that_exists_or_is_named_as_unclaimed(self) -> None:
        known = set(cc.R2) | set(cc.RULES)
        for tag, classes in cc.TAG_CLASS.items():
            self.assertTrue(set(classes) <= known, "%s maps outside the classes" % tag)
        tagged = {tag for _, _, tag in cc.INTERRUPTIONS} - {"QUEUE", "EMPTY"}
        self.assertEqual(tagged - set(cc.TAG_CLASS), set(cc.TAG_UNMAPPED),
                         "a correction tag is neither mapped to a class nor named as unclaimed")


class State(unittest.TestCase):
    def test_long_values_are_clipped_in_the_middle_not_at_the_ends(self) -> None:
        view = cc.view_of(a_turn([("A" * 9000 + "Z" * 9000, [])]))
        r1 = cc.r1_state(view, "B" * 4000 + "Y" * 4000, "/tmp/demo")
        r2 = cc.r2_state(view, "B" * 4000 + "Y" * 4000, "/tmp/demo")
        self.assertTrue(r1["owner_request"].startswith("B") and r1["owner_request"].endswith("Y"))
        self.assertLessEqual(len(r1["owner_request"]), cc.MAX_OWNER_CHARS + 3)
        self.assertTrue(r2["owner_asked"].startswith("B") and r2["owner_asked"].endswith("Y"))
        self.assertLessEqual(len(r2["owner_asked"]), cc.MAX_ASKED_CHARS + 3)
        self.assertGreater(len(r2["owner_asked"]), len(r1["owner_request"]),
                           "round 2 leads with his words and gives them more room")

    def test_elided_tool_calls_keep_the_exact_count(self) -> None:
        view = cc.view_of(a_turn([("ok", [("Bash", "x")] * 40)]))
        state = cc.r1_state(view, "go", "/tmp/demo")
        self.assertEqual(state["tool_call_count"], 40)
        self.assertIn("20 more tool calls", state["tool_calls"])


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


class Truncation(unittest.TestCase):
    """The matched control rests on this: a turn has to be readable as it stood at depth n."""

    def turn(self) -> cc.Turn:
        return a_turn([("first", [("Bash", "one")]),
                       ("second", [("Bash", "two"), ("Bash", "two")]),
                       ("third", [("Write", "/tmp/demo/x.py")])])

    def test_a_view_at_depth_n_holds_only_the_first_n_messages(self) -> None:
        cut = cc.view_of(self.turn(), 2)
        self.assertEqual(cut["depth"], 2)
        self.assertEqual(cut["reply"], "first\n\nsecond")
        self.assertEqual(cut["reply_chars"], len("first") + len("second"))
        self.assertEqual(cut["tool_call_count"], 3)
        self.assertNotIn("/tmp/demo/x.py", [c["target"] for c in cut["tool_calls"]])

    def test_the_full_view_is_the_turn_and_matches_what_close_stored(self) -> None:
        turn = self.turn()
        full = cc.view_of(turn)
        self.assertEqual(full["depth"], turn["assistant_messages"], 3)
        self.assertEqual(full["tool_call_count"], turn["tool_call_count"], 4)
        self.assertEqual(full["reply"], turn["reply"])

    def test_a_repeated_call_is_counted_as_a_free_fact(self) -> None:
        self.assertEqual(cc.view_of(self.turn())["repeated_calls"], 1)
        self.assertEqual(cc.view_of(self.turn(), 1)["repeated_calls"], 0)


class Matching(unittest.TestCase):
    """For a correction at depth n, the control is clean turns cut to n, nearest on tool count."""

    def pool(self) -> list:
        session = {"prefix": "clean", "cwd": "/tmp/demo"}
        shallow = a_turn([("a", [])], index=1)
        near = a_turn([("a", [("Bash", "1")]), ("b", [("Bash", "2")]), ("c", [])], index=2)
        far = a_turn([("a", [("Bash", "1")] * 6), ("b", []), ("c", [])], index=3)
        return [(session, shallow), (session, near), (session, far)]

    def test_only_turns_deep_enough_are_eligible_and_the_nearest_on_tools_come_first(self) -> None:
        correction = a_turn([("x", [("Bash", "a")]), ("y", [("Bash", "b")])], index=9)
        picked = cc.matched_controls(correction, self.pool(), 5)
        self.assertEqual([t["i"] for _, t, _ in picked], [2, 3], "the 1-message turn cannot be cut to 2")
        self.assertEqual({d for _, _, d in picked}, {2}, "every control is cut to the correction's depth")

    def test_the_control_is_capped_and_deterministic(self) -> None:
        correction = a_turn([("x", []), ("y", [])], index=9)
        first = cc.matched_controls(correction, self.pool(), 1)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, cc.matched_controls(correction, self.pool(), 1))


class Rules(unittest.TestCase):
    """A deterministic detector is still a claim about the world, so it gets tests too."""

    HOME = cc.HOME  # rooms are read relative to $HOME, so the test has to live there too

    def fire(self, rule, steps: list, request: str, cwd: str = "") -> bool:
        cwd = cwd or self.HOME + "/Projects/voice"
        return rule(cc.view_of(a_turn(steps, request)), request, cwd)[0]

    def test_yap_is_length_against_length(self) -> None:
        long_reply = [("L" * (cc.YAP_MIN_CHARS + 10), [])]
        self.assertTrue(self.fire(cc.rule_yap, long_reply, "why?"))
        self.assertFalse(self.fire(cc.rule_yap, [("short", [])], "why?"))
        self.assertFalse(self.fire(cc.rule_yap, long_reply, "Q" * cc.YAP_MIN_CHARS),
                         "a long answer to a long question is not yapping")

    def test_wrong_room_reads_the_turn_calls_through_the_shared_rule(self) -> None:
        """The rule itself is tested in tests/test_rules.py; this is the turn reaching it."""
        other = [("", [("Write", self.HOME + "/Projects/cmux/main.go")])]
        self.assertTrue(self.fire(cc.rule_wrong_room, other, "fix the parser"))
        self.assertFalse(self.fire(cc.rule_wrong_room, other, "fix the parser in cmux"))

    def test_no_receipts_wants_the_call_that_would_have_produced_the_claim(self) -> None:
        claim = "All done and committed."
        self.assertTrue(self.fire(cc.rule_no_receipts, [(claim, [])], "ship it"))
        self.assertFalse(self.fire(cc.rule_no_receipts,
                                   [(claim, [("Bash", "git commit -m 'x'")])], "ship it"))
        self.assertFalse(self.fire(cc.rule_no_receipts,
                                   [("Nothing is committed yet.", [])], "ship it"),
                         "a hedge is not a claim")
        self.assertFalse(self.fire(cc.rule_no_receipts, [("Ready to push.", [])], "ship it"))


class Verdicts(unittest.TestCase):
    def row(self, **kw: float) -> dict:
        base = {"n_correction": 19, "fire_correction": 0.3, "fire_matched": 0.3,
                "lift_matched": 0.0, "mean_lift_matched": 0.0}
        base.update(kw)
        return base

    def test_the_verdict_comes_from_the_matched_control_alone(self) -> None:
        self.assertEqual(cc.verdict(self.row(n_correction=2)), "no evidence")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.6, fire_matched=0.3,
                                             lift_matched=0.30)), "keep")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.4, fire_matched=0.28,
                                             lift_matched=0.12, mean_lift_matched=0.11)), "keep")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.9, fire_matched=0.8,
                                             lift_matched=0.10)), "rewrite",
                         "a question true of nearly every turn failed as a question")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.0, fire_matched=0.05,
                                             lift_matched=-0.05)), "rewrite")
        self.assertEqual(cc.verdict(self.row(fire_correction=0.35, fire_matched=0.3,
                                             lift_matched=0.05)), "drop",
                         "it fires at ordinary rates on both sides and separates nothing")

    def test_a_correction_beating_its_own_control_is_what_paired_win_counts(self) -> None:
        corr = [{"key": "a", "r2": {"x": 0.8}}, {"key": "b", "r2": {"x": 0.1}}]
        matched = [{"for": ["a"], "r2": {"x": 0.2}}, {"for": ["a"], "r2": {"x": 0.3}},
                   {"for": ["b"], "r2": {"x": 0.4}}, {"for": ["b"], "r2": {"x": 0.5}}]
        self.assertEqual(cc.paired_win(corr, matched, "x", "r2"), 0.5)
        self.assertEqual(cc.paired_win(corr[:1], matched, "x", "r2"), 1.0)


if __name__ == "__main__":
    unittest.main()
