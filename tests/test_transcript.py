"""Reading the tail of a transcript: what it counts, where it stops, and how it fails.

Every failure mode here is one the hook meets on the owner's machine — a transcript that does not
exist yet, one it may not read, one being written to as it reads, one larger than the window.
None of them may raise: the hook logs what it has and carries on.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

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
        self.assertEqual((last["depth"], last["error"], last["exhausted"]), (3, "", False))
        self.assertEqual([c["name"] for c in last["tool_calls"]], ["Read", "Write"])
        self.assertEqual(last["tool_calls"][1]["target"], "/Users/x/Projects/cmux/main.go")

    def test_the_turn_carries_back_his_request_and_the_prose_that_answered_it(self) -> None:
        """Both are state the Stop question was measured on; the tail walks past them anyway."""
        path = self.write(self.turn([rec("assistant", TS, text("Done — History.swift."))]))
        last = transcript.tail(path)
        self.assertEqual(last["owner_asked"], "why is the history view stale? just answer, "
                                              "don't touch anything")
        self.assertEqual(last["reply"], "Let me look at the coordinator.\n\nDone — History.swift.")

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
        self.assertEqual(last, {"interrupted": False, "depth": 0, "tool_calls": [], "reply": "",
                                "owner_asked": "", "exhausted": False,
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

    def test_a_record_nested_past_the_parser_is_dropped_like_any_other_bad_line(self) -> None:
        path = self.write(self.turn() + ["[" * 100000 + "]" * 100000])
        self.assertEqual((transcript.tail(path)["depth"], transcript.tail(path)["error"]), (3, ""))

    def test_his_message_a_megabyte_back_is_reached(self) -> None:
        """#17: tool results put his previous message past 256 KB for 18% of his prompts."""
        filler = rec("user", TS, [{"type": "tool_result", "content": "x" * 20000}])
        path = self.write([rec("user", TS, "the thing he asked for, long ago")]
                          + [rec("assistant", TS, tool("Bash", command="ls")), filler] * 60)
        self.assertGreater(os.path.getsize(path), 4 * transcript.CHUNK_BYTES)
        last = transcript.tail(path, "and now?")
        self.assertEqual((last["depth"], len(last["tool_calls"])), (60, 60))
        self.assertEqual((last["exhausted"], last["owner_asked"]),
                         (False, "the thing he asked for, long ago"))

    def test_the_byte_cap_bounds_the_read_and_the_counts_are_then_lower_bounds(self) -> None:
        """Beyond MAX_BYTES there is no reading: his message is out of sight, not searched for."""
        filler = rec("user", TS, [{"type": "tool_result", "content": "x" * 2000}])
        path = self.write([rec("user", TS, "the thing he asked for, long ago")]
                          + [rec("assistant", TS, text("step")), filler] * 40)
        with mock.patch.object(transcript, "MAX_BYTES", 20000), \
                mock.patch.object(transcript, "CHUNK_BYTES", 3000):
            last = transcript.tail(path)
        self.assertEqual(last["error"], "")
        self.assertGreater(last["depth"], 0)
        self.assertLess(last["depth"], 40, "it stops at the cap, it does not read the file")
        self.assertIs(last["exhausted"], True, "it never reached his message: these are lower bounds")

    def test_the_line_cap_bounds_the_scan_whatever_the_lines_look_like(self) -> None:
        """One-token lines cost per line, not per byte: 8 MB of them is seconds uncapped."""
        path = self.write([rec("user", TS, "the thing he asked for")]
                          + ["{}"] * (2 * transcript.MAX_LINES) + self.turn()[1:])
        last = transcript.tail(path)
        self.assertIs(last["exhausted"], True)
        self.assertEqual(last["depth"], 3, "the turn itself is still whole")
        with mock.patch.object(transcript, "MAX_LINES", 0):
            spent = transcript.tail(self.write(self.turn(), "s-2.jsonl"))
        self.assertEqual((spent["depth"], spent["exhausted"]), (0, True),
                         "a scan out of lines is exhausted, never a quiet turn")

    def test_the_bound_is_work_so_the_same_file_gets_the_same_answer(self) -> None:
        """The reach does not depend on how busy the machine is: one line more or less decides."""
        path = self.write(self.turn([rec("assistant", TS, text("done"))]), end="")  # his is 6th
        with mock.patch.object(transcript, "MAX_LINES", 6):
            self.assertEqual(transcript.tail(path)["exhausted"], False)
        with mock.patch.object(transcript, "MAX_LINES", 5):
            self.assertEqual(transcript.tail(path)["exhausted"], True)

    def test_a_giant_tool_result_in_the_turn_is_passed_without_being_held(self) -> None:
        """#17's review: a 7 MB tool result three records back cost 17–61 ms and exhausted the
        clocked scan every time. It is read past by its start and never joined whole."""
        giant = rec("user", TS, [{"type": "tool_result", "tool_use_id": "t1",
                                  "content": "x" * (7 * 1024 * 1024)}])
        path = self.write([rec("user", TS, "screenshot the page"),
                           rec("assistant", TS, tool("Bash", command="shot")), giant,
                           rec("assistant", TS, text("done"))])
        last = transcript.tail(path)
        self.assertEqual((last["exhausted"], last["owner_asked"], last["depth"]),
                         (False, "screenshot the page", 2))
        with open(path, "rb") as handle:
            kept = {size: len(line) for line, size in
                    transcript.lines_back(handle, os.path.getsize(path))}
        biggest = max(kept)
        self.assertGreater(biggest, 7 * 1024 * 1024)
        self.assertLessEqual(kept[biggest], 2 * transcript.CHUNK_BYTES, "its start, not the line")

    def test_a_line_too_long_to_parse_that_is_not_a_tool_result_ends_the_scan(self) -> None:
        """It might be his message; unparsed it cannot be told apart, so the scan says so."""
        path = self.write([rec("user", TS, "the older request"),
                           rec("assistant", TS, text("older")),
                           rec("user", TS, "a paste " * 2000),
                           rec("assistant", TS, text("reading your paste"))])
        with mock.patch.object(transcript, "MAX_PARSED", 4096), \
                mock.patch.object(transcript, "CHUNK_BYTES", 1024):
            last = transcript.tail(path)
        self.assertEqual((last["depth"], last["exhausted"], last["owner_asked"]), (1, True, ""),
                         "never read past as a quiet line, never parsed")

    def test_the_parse_budget_is_spent_across_lines_and_tool_results_cost_none_of_it(self) -> None:
        """Eight records of 1 KB each need a parse; tool results between them never do."""
        filler = rec("user", TS, [{"type": "tool_result", "content": "x" * 5000}])
        steps = [rec("assistant", TS, text("step " * 200)), filler] * 8
        path = self.write([rec("user", TS, "the thing he asked for")] + steps)
        with mock.patch.object(transcript, "MAX_PARSED", 6000):
            capped = transcript.tail(path)
        self.assertEqual((capped["exhausted"], capped["depth"]), (True, 5))
        with mock.patch.object(transcript, "MAX_PARSED", 10000):
            self.assertEqual(transcript.tail(path)["owner_asked"], "the thing he asked for",
                             "40 KB of tool results in the way, and none of it was parsed")

    def test_a_stops_final_message_closes_the_reply_once(self) -> None:
        """Claude Code writes the transcript behind the Stop hook: the payload's final message is
        often not on disk yet, and sometimes it is."""
        final = "Done — History.swift is fixed."
        missing = transcript.tail(self.write(self.turn()), said=final)
        self.assertEqual(missing["reply"], "Let me look at the coordinator.\n\n" + final)
        written = transcript.tail(self.write(self.turn([rec("assistant", TS, text(final))]),
                                             "s-2.jsonl"), said="  " + final + "\n")
        self.assertEqual(written["reply"], missing["reply"], "on disk already: not twice")
        self.assertEqual(transcript.tail(self.write(self.turn(), "s-3.jsonl"))["reply"],
                         "Let me look at the coordinator.")

    def test_a_window_that_reached_the_start_of_the_file_is_not_exhausted(self) -> None:
        """Nothing further back to read is not the same failure as a scan that ran out."""
        last = transcript.tail(self.write([rec("assistant", TS, text("resumed, mid-thought"))]))
        self.assertEqual((last["depth"], last["exhausted"], last["owner_asked"]), (1, False, ""))

    def test_lines_come_back_whole_and_last_first_whatever_the_chunk(self) -> None:
        lines = [b"a" * n for n in (0, 1, 5, 64, 3, 200, 0, 7)]
        path = os.path.join(self.tmp.name, "lines.jsonl")
        with open(path, "wb") as handle:
            handle.write(b"\n".join(lines))
        whole = [(line, len(line)) for line in lines[::-1]]
        for chunk in (1, 2, 3, 7, 64, 1 << 20):
            with open(path, "rb") as handle, mock.patch.object(transcript, "CHUNK_BYTES", chunk):
                self.assertEqual(list(transcript.lines_back(handle, os.path.getsize(path))),
                                 whole, "chunk %d" % chunk)
        with open(path, "rb") as handle, mock.patch.object(transcript, "MAX_BYTES", 12), \
                mock.patch.object(transcript, "CHUNK_BYTES", 5):
            self.assertEqual(list(transcript.lines_back(handle, os.path.getsize(path))),
                             [(b"a" * 7, 7), (b"", 0)],
                             "the line the cap cuts through is never yielded")

    def test_a_line_past_max_parsed_comes_back_as_its_start_and_its_true_size(self) -> None:
        line = bytes(range(97, 123)) * 40  # 1,040 bytes, no newline in it
        path = os.path.join(self.tmp.name, "long.jsonl")
        with open(path, "wb") as handle:
            handle.write(b"x\n" + line + b"\ny")
        for chunk in (7, 64, 100):
            with open(path, "rb") as handle, mock.patch.object(transcript, "CHUNK_BYTES", chunk), \
                    mock.patch.object(transcript, "MAX_PARSED", 3 * chunk):
                got = list(transcript.lines_back(handle, os.path.getsize(path)))
            self.assertEqual([size for _, size in got], [1, len(line), 1], "chunk %d" % chunk)
            start = got[1][0]
            self.assertTrue(line.startswith(start) and chunk <= len(start) <= 2 * chunk,
                            "chunk %d kept %d bytes" % (chunk, len(start)))

    def test_a_tool_result_is_skipped_by_its_bytes_whatever_it_quotes(self) -> None:
        """An agent reading transcripts returns the marker, and Bash returns `"interrupted":false`
        on every call; neither is the owner pressing escape."""
        quoted = rec("user", TS, [{"type": "tool_result", "content": MARKER + "] in a transcript"}],
                     toolUseResult={"stdout": "", "interrupted": False})
        path = self.write(self.turn([quoted, rec("assistant", TS, text("done"))]))
        last = transcript.tail(path)
        self.assertEqual((last["interrupted"], last["depth"], last["exhausted"]), (False, 4, False))

    def test_an_empty_file_and_a_file_of_junk_are_simply_empty(self) -> None:
        self.assertEqual(transcript.tail(self.write([], end=""))["depth"], 0)
        self.assertEqual(transcript.tail(self.write(["not json", "[1,2]", "null"]))["depth"], 0)


class Records(unittest.TestCase):
    """The vocabulary the experiments read transcripts with, shared with the hook."""

    def test_a_notification_is_the_whole_shape_and_nothing_he_typed(self) -> None:
        """A background agent's return arrives as a prompt; his own message must never be taken
        for one, or the prompt cache keeps his previous request and `jumped` asks about that."""
        note = ("<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n"
                "<result>done</result>\n</task-notification>")
        self.assertTrue(transcript.is_notification(note), "bare, as the transcript and most "
                                                          "payloads have it")
        self.assertTrue(transcript.is_notification(
            note + "\nFull transcript available at: /private/tmp/claude/tasks/a1.output"))
        self.assertTrue(transcript.is_notification(
            note + "\nRead the output file to retrieve the result: /var/folders/x/a1.output\n"))
        self.assertTrue(transcript.is_notification(note + "\n" + note), "two at once")
        for his in ("API Error: 500 from the server — what now?",
                    "Caveat: this one is urgent, fix the parser",
                    "<system-reminder> is showing in my output, why?",
                    note + "\nand also check the parser",
                    note + "\nFull transcript available at: x\nthen fix it",
                    "<task-notification> without its closing tag, typed by hand"):
            self.assertFalse(transcript.is_notification(his), his)

    def test_an_interruption_is_the_marker_or_the_id(self) -> None:
        self.assertTrue(transcript.is_interruption(json.loads(rec("user", TS, text(MARKER)))))
        self.assertTrue(transcript.is_interruption(
            json.loads(rec("user", TS, "anything", interruptedMessageId="msg_1"))))
        self.assertFalse(transcript.is_interruption(json.loads(rec("user", TS, "carry on"))))

    def test_a_reminder_is_stripped_and_a_target_is_collapsed(self) -> None:
        wrapped = "keep this<system-reminder>not this</system-reminder> and this"
        self.assertEqual(transcript.record_text(json.loads(rec("user", TS, text(wrapped)))),
                         "keep this and this")
        block = {"type": "tool_use", "name": "Bash", "input": {"command": "git   log\n --oneline"}}
        self.assertEqual(transcript.tool_target(block), "git log --oneline")
        self.assertEqual(transcript.tool_target({"type": "tool_use", "name": "X"}), "")


if __name__ == "__main__":
    unittest.main()
