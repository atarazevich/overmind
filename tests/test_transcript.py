"""Reading the tail of a transcript: what it counts, where it stops, and how it fails.

Every failure mode here is one the hook meets on the owner's machine — a transcript that does not
exist yet, one it may not read, one being written to as it reads, one larger than the window.
None of them may raise: the hook logs what it has and carries on.
"""
import json
import os
import tempfile
import unittest

from overmind import transcript
from tests import MARKER, TS, rec, text, tool, transcript_file


class Tail(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, lines: list, name: str = "s-1.jsonl", end: str = "\n") -> str:
        return transcript_file(self.tmp.name, lines, name, end)

    def turn(self, extra: list = ()) -> list:
        """His question, three assistant messages, two tool calls, one tool result."""
        return [
            rec("user", TS, "why is the history view stale? just answer, don't touch anything"),
            rec("assistant", TS, text("Let me look at the coordinator.")),
            rec("assistant", TS, tool("Read", file_path="/Users/x/Projects/voice/History.swift")),
            rec("user", TS, [{"type": "tool_result", "content": "… 400 lines …"}]),
            rec("assistant", TS, tool("Write", file_path="/Users/x/Projects/cmux/main.go")),
        ] + list(extra)

    def test_an_interruption_closing_the_turn_is_seen_with_its_depth_and_its_calls(self) -> None:
        path = self.write(self.turn([rec("user", TS, text(MARKER), interruptedMessageId="msg_1")]))
        last = transcript.tail(path, "Why the fuck are you writing? I asked a question.")
        self.assertIs(last["interrupted"], True)
        self.assertEqual((last["depth"], last["error"]), (3, ""))
        self.assertEqual([c["name"] for c in last["tool_calls"]], ["Read", "Write"])
        self.assertEqual(last["tool_calls"][1]["target"], "/Users/x/Projects/cmux/main.go")

    def test_a_turn_that_finished_is_not_an_interruption(self) -> None:
        path = self.write(self.turn([rec("assistant", TS, text("Done — fixed in History.swift."))]))
        last = transcript.tail(path, "now do the tests")
        self.assertIs(last["interrupted"], False)
        self.assertEqual((last["depth"], len(last["tool_calls"])), (4, 2))

    def test_the_prompt_is_read_past_whether_or_not_it_is_written_yet(self) -> None:
        """Claude Code may write the submitted prompt before the hook runs, or after it."""
        submitted = "Why the fuck are you writing? I asked a question."
        interrupted = self.turn([rec("user", TS, text(MARKER), interruptedMessageId="msg_1")])
        before = transcript.tail(self.write(interrupted), submitted)
        after = transcript.tail(self.write(interrupted + [rec("user", TS, submitted)], "s-2.jsonl"),
                                submitted)
        self.assertEqual(after, before)
        self.assertIs(after["interrupted"], True)

    def test_counting_stops_at_his_previous_message(self) -> None:
        path = self.write([rec("assistant", TS, text("older turn")),
                           rec("assistant", TS, tool("Bash", command="git log")),
                           rec("user", TS, text(MARKER), interruptedMessageId="old")] + self.turn())
        last = transcript.tail(path)
        self.assertEqual((last["depth"], len(last["tool_calls"])), (3, 2))
        self.assertIs(last["interrupted"], False, "an older interruption is not this turn's")

    def test_a_slash_command_he_ran_is_a_boundary_too(self) -> None:
        path = self.write([rec("user", TS, "the older thing"),
                           rec("assistant", TS, text("older")),
                           rec("user", TS, "<command-message>compact</command-message>"
                                       "\n<command-name>/compact</command-name>"),
                           rec("assistant", TS, text("compacting")),
                           rec("assistant", TS, tool("Bash", command="ls"))])
        self.assertEqual(transcript.tail(path)["depth"], 2)

    def test_machinery_belongs_to_the_turn_and_never_ends_it(self) -> None:
        path = self.write([rec("user", TS, "fix the parser"),
                           rec("assistant", TS, text("on it")),
                           rec("user", TS, "<task-notification>agent done</task-notification>"),
                           rec("user", TS, text("Read-only. Never commit."), isMeta=True),
                           rec("assistant", TS, text("sidechain"), isSidechain=True),
                           rec("assistant", TS, text("still going"))])
        self.assertEqual(transcript.tail(path)["depth"], 2, "the sidechain is another session")

    def test_a_missing_file_names_the_error_and_costs_nothing(self) -> None:
        last = transcript.tail(os.path.join(self.tmp.name, "nope.jsonl"))
        self.assertEqual(last, {"interrupted": False, "depth": 0, "tool_calls": [],
                                "error": "FileNotFoundError"})
        self.assertEqual(transcript.tail("")["error"], "FileNotFoundError")
        self.assertEqual(transcript.tail(self.tmp.name)["error"], "IsADirectoryError")

    @unittest.skipIf(os.geteuid() == 0, "root reads everything")
    def test_a_file_it_may_not_read_names_the_error(self) -> None:
        path = self.write(self.turn())
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o600)
        self.assertEqual(transcript.tail(path)["error"], "PermissionError")

    def test_a_torn_line_is_dropped_rather_than_guessed_at(self) -> None:
        path = self.write(self.turn([rec("assistant", TS, text("done"))]), end="\n")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"type":"assistant","message":{"role":"assis')  # a write in flight
        last = transcript.tail(path)
        self.assertEqual((last["depth"], last["error"]), (4, ""))

    def test_the_window_bounds_the_read_and_the_counts_are_then_lower_bounds(self) -> None:
        """Beyond TAIL_BYTES there is no reading: his message is out of sight, not searched for."""
        filler = rec("user", TS, [{"type": "tool_result", "content": "x" * 20000}])
        path = self.write([rec("user", TS, "the thing he asked for, long ago")]
                          + [rec("assistant", TS, text("step")), filler] * 40)
        size = os.path.getsize(path)
        self.assertGreater(size, transcript.TAIL_BYTES, "the fixture has to exceed the window")
        last = transcript.tail(path)
        self.assertEqual(last["error"], "")
        self.assertGreater(last["depth"], 0)
        self.assertLess(last["depth"], 40, "it stops at the window, it does not read the file")
        self.assertLessEqual(sum(len(line) + 1 for line in transcript.window(path)),
                             transcript.TAIL_BYTES, "the window is the only bound there is")

    def test_an_empty_file_and_a_file_of_junk_are_simply_empty(self) -> None:
        self.assertEqual(transcript.tail(self.write([], end=""))["depth"], 0)
        self.assertEqual(transcript.tail(self.write(["not json", "[1,2]", "null"]))["depth"], 0)


class Records(unittest.TestCase):
    """The vocabulary the experiments read transcripts with, shared with the hook."""

    def test_an_interruption_is_the_marker_or_the_id(self) -> None:
        self.assertTrue(transcript.is_interruption(json.loads(rec("user", TS, text(MARKER)))))
        self.assertTrue(transcript.is_interruption(
            json.loads(rec("user", TS, "anything", interruptedMessageId="msg_1"))))
        self.assertFalse(transcript.is_interruption(json.loads(rec("user", TS, "carry on"))))

    def test_his_words_exclude_the_machinery_and_include_a_slash_command(self) -> None:
        self.assertEqual(transcript.owner_message(json.loads(rec("user", TS, "real message"))),
                         "real message")
        self.assertIsNone(transcript.owner_message(json.loads(rec("user", TS, text(MARKER)))))
        self.assertIsNone(transcript.owner_message(
            json.loads(rec("user", TS, [{"type": "tool_result", "content": "…"}]))))
        slash = "<command-message>gu</command-message><command-name>/gu</command-name>"
        self.assertEqual(transcript.owner_message(json.loads(rec("user", TS, slash))), "/gu")

    def test_a_reminder_is_stripped_and_a_target_is_collapsed(self) -> None:
        wrapped = "keep this<system-reminder>not this</system-reminder> and this"
        self.assertEqual(transcript.record_text(json.loads(rec("user", TS, text(wrapped)))),
                         "keep this and this")
        block = {"type": "tool_use", "name": "Bash", "input": {"command": "git   log\n --oneline"}}
        self.assertEqual(transcript.tool_target(block), "git log --oneline")
        self.assertEqual(transcript.tool_target({"type": "tool_use", "name": "X"}), "")


if __name__ == "__main__":
    unittest.main()
