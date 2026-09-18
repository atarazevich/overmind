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


if __name__ == "__main__":
    unittest.main()
