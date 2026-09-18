"""Touching the wrong thing, as a rule. A deterministic detector is still a claim about the world.

The cases are the ones the experiment scored it on (#15): a write into another project fires, a
write into a room he named does not, a read never does, and this project's own sidecar under
~/.claude/projects is this project.
"""
import unittest

from overmind import rules

HOME = rules.HOME  # rooms are read relative to $HOME, so the test has to live there too
HERE = HOME + "/Projects/voice"


def call(name: str, target: str) -> dict:
    return {"name": name, "target": target}


class WrongRoom(unittest.TestCase):
    def fired(self, calls: list, request: str, cwd: str = HERE) -> bool:
        return rules.wrong_room(calls, request, cwd)[0]

    def test_a_write_outside_the_room_fires_unless_he_named_the_room(self) -> None:
        other = [call("Write", HOME + "/Projects/cmux/main.go")]
        self.assertTrue(self.fired(other, "fix the parser"))
        self.assertFalse(self.fired(other, "fix the parser in cmux"),
                         "a room he named is a room he permitted")
        self.assertFalse(self.fired([call("Write", HERE + "/a.py")], "fix it"))

    def test_reading_another_project_is_not_the_complaint(self) -> None:
        self.assertFalse(self.fired([call("Read", HOME + "/Projects/cmux/m.go")], "fix it"))
        self.assertFalse(self.fired([call("Bash", "grep -r todo " + HOME + "/Projects/cmux")],
                                    "fix it"))
        self.assertTrue(self.fired([call("Bash", "rm " + HOME + "/Projects/cmux/m.go")], "fix it"),
                        "a mutating command counts by the paths after its verb")

    def test_the_session_sidecar_is_the_session_own_room(self) -> None:
        sidecar = HOME + "/.claude/projects/" + HOME.replace("/", "-") + "-Projects-voice/x.jsonl"
        self.assertFalse(self.fired([call("Write", sidecar)], "fix it"))
        self.assertTrue(self.fired([call("Write", HOME + "/.claude/settings.json")], "fix it"))

    def test_scratch_space_is_nobody_room(self) -> None:
        self.assertFalse(self.fired([call("Write", "/tmp/notes.md")], "fix it"))

    def test_why_names_the_rooms_it_found(self) -> None:
        fired, why = rules.wrong_room([call("Write", HOME + "/Projects/cmux/main.go")],
                                      "fix the parser", HERE)
        self.assertTrue(fired)
        self.assertIn("Projects/cmux", why)
        self.assertIn("Projects/voice", why)
        self.assertEqual(rules.wrong_room([], "fix it", HERE), (False, ""))



class WantsYou(unittest.TestCase):
    """Read, never judged: the agent's last paragraph to him asks him something (#17). The cases
    are the shapes experiments/wants_you.py found in 200 real Stops, the misses included."""

    def test_a_question_or_an_ask_in_the_last_paragraph_wants_him(self) -> None:
        self.assertTrue(rules.wants_you("Committed. Ready to push. Want me to go ahead?"))
        self.assertTrue(rules.wants_you("Two options above.\n\nYour call — ship now, or wait a week."))
        self.assertTrue(rules.wants_you("Скрипт готов.\n\nКинь вывод — если чисто, даю отмашку."))
        self.assertFalse(rules.wants_you("Committed as `4621dff`. The system is converging."))

    def test_what_is_not_said_to_him_does_not_count(self) -> None:
        draft = "Here's the draft:\n\n---\n\nHi Aldo,\n\nUp for a call next week?\n\n---"
        self.assertFalse(rules.wants_you(draft), "a question in a draft is for its recipient")
        self.assertFalse(rules.wants_you("Hooks now:\n\n| Stop | \"Orders?\" |\n| Start | ready |"))
        self.assertFalse(rules.wants_you("Done.\n\n```\nread -p 'continue?'\n```"))

    def test_only_the_last_paragraph_is_read(self) -> None:
        """A measured miss: a question followed by a closing paragraph is not seen."""
        self.assertFalse(rules.wants_you("Is that your phone?\n\nRestarting closes every session."))

    def test_a_conditional_offer_reads_as_wanting_him(self) -> None:
        """The measured false alarm: six of seven on the held-out set are this shape."""
        self.assertTrue(rules.wants_you("All set. Say the word if you want the rest done too."))

    def test_what_it_reads_is_bounded_whatever_the_reply(self) -> None:
        """The hook runs this on every Stop. A paragraph is read to its last ASK_CHARS, and a run
        of blank lines is one separator, not a search per line (29 s for 20,000 of them, before)."""
        self.assertTrue(rules.wants_you("x" * 50000 + " Скажи, если чисто"))
        self.assertFalse(rules.wants_you("Tell me " + "x" * rules.ASK_CHARS),
                         "an ask further back than ASK_CHARS in one paragraph is not read")
        self.assertTrue(rules.wants_you("Done." + "\n" * 20000 + "Ship it now?"))
        self.assertFalse(rules.wants_you("Draft:\n\n" + " \n" * 20000 + "---\nHi?\n---"))

if __name__ == "__main__":
    unittest.main()
