"""The detectors that are rules, not questions.

docs/signals.md: *if it is deterministic, read it — never classify it.* **Touching the wrong
thing** was a model question in round 1 and fired on 89% of everything; as paths written against
paths named it is +19 pp on the truncation-matched control at a 2% base rate (#15), so it lives
here, in code, and costs nothing per event.

Written for experiments/conduct_classes.py, which scored it, and imported from there so the hook
and the experiment run the same rule rather than two that drift apart. **Wants you** lives here
for the same reason, scored by experiments/wants_you.py (#17). Stdlib only, no state, no clock:
given the same turn it says the same thing forever.
"""
from __future__ import annotations

import os
import re

HOME = os.path.expanduser("~")
SESSION_SIDECAR = "/.claude/projects/"  # Claude Code's own per-project folder, slug for a path

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# A Bash call counts as touching something only if it changes something, and only the paths that
# come *after* the verb count — `grep /Applications/… ` is a read, `open /Applications/…` is not
# the same sentence. Reading another project is not the complaint; writing into it is.
MUTATING_BASH = ("rm ", "rmdir ", "mv ", "cp ", "mkdir ", "touch ", "chmod ", "chown ", "ln -s",
                 "git commit", "git push", "git add", "git checkout", "git reset", "git rm",
                 "git mv", "git stash", "git merge", "sed -i", "tee ", ">>", "> ", "open ",
                 "npm install", "pip install", "brew install", "defaults write", "trash ",
                 "curl -o", "cat >", "python3 -c", "killall ")
# Writing here is scratch work, not a room anyone is protective of.
NEUTRAL_ROOMS = ("/tmp", "/private", "/var", "/dev")

# The mark a middle-out clip leaves in the middle of a target: written by judge.clip, read by
# paths_in below. It lives here, on the side that imports nothing from this package, because the
# other arrangement is a judge ↔ rules import cycle for three characters.
CLIP_MARK = " … "


def room_of(path: str, cwd: str) -> str:
    """The room a path belongs to: `Projects/voice`, `.claude`, `/tmp`. Relative paths are cwd's.

    Rooms are read relative to $HOME, because that is where this person's projects live. Outside
    $HOME the first segment is the room — `/Applications` and `/tmp` are rooms, not neighbours.
    """
    path = path.strip().strip("'\"`,;)").rstrip("\\")
    if path.startswith("~"):
        path = HOME + path[1:]
    if not path.startswith("/"):
        return room_of(cwd, "/") if cwd else ""
    if path.startswith(HOME + SESSION_SIDECAR):
        # ~/.claude/projects/-Users-x-Projects-voice/... is voice's own sidecar, not another room.
        slug = path[len(HOME) + len(SESSION_SIDECAR):].split("/")[0]
        return room_of(slug.replace("-", "/"), cwd) if slug.startswith("-") else ".claude"
    if path.startswith(HOME + "/"):
        parts = [p for p in path[len(HOME) + 1:].split("/") if p]
        if not parts:
            return "~"
        return parts[0] if parts[0].startswith(".") else "/".join(parts[:2])
    return "/" + path.lstrip("/").split("/")[0]


def paths_in(text: str) -> list[str]:
    """Every absolute or home-relative path-looking token in a command line.

    A target clipped middle-out leaves half a path either side of the cut — `/Users/x/Projec` —
    and those halves are dropped rather than guessed at.
    """
    head, cut, tail = text.partition(CLIP_MARK)
    tokens = head.replace("=", " ").split()
    if cut:
        tokens = tokens[:-1] + tail.replace("=", " ").split()[1:]
    out = []
    for token in tokens:
        token = token.strip("'\"`,;()").rstrip("\\")
        if (token.startswith("/") or token.startswith("~/")) and token.count("/") >= 2:
            out.append(token)
    return out


def wrong_room(calls: list[dict], owner_request: str, cwd: str) -> tuple[bool, str]:
    """Paths written to, against the rooms `owner_request` names and the room the session is in.

    `calls` are {name, target} in the order the turn made them. Returns (fired, why).
    """
    here = room_of(cwd, cwd)
    named = {w.strip(".,:;()'\"`") for w in owner_request.lower().replace("/", " ").split()}
    named.discard("")
    outside = []
    for call in calls:
        target = call["target"]
        if call["name"] in WRITE_TOOLS:
            candidates = [target]
        elif call["name"] == "Bash":
            at = min((target.find(m) for m in MUTATING_BASH if m in target), default=-1)
            if at < 0:
                continue
            candidates = paths_in(target[at:])
        else:
            continue
        for path in candidates:
            room = room_of(path, cwd)
            if not room or room.startswith(NEUTRAL_ROOMS) or room == here:
                continue
            if room.split("/")[-1].lower().lstrip(".") in named:
                continue
            outside.append(room)
    if not outside:
        return False, ""
    return True, "wrote in %s, and the turn is in %s" % (", ".join(sorted(set(outside))[:3]),
                                                         here or "?")


# **Wants you** is read, never judged (docs/signals.md): the agent's last paragraph to him holds a
# question or asks him for something. Measured by experiments/wants_you.py against 200 Stops read
# by hand — 0.89 accurate on the 100 it was not written on, where "the last line ends in a
# question mark" is 0.77. Optimistic: the agent that wrote the rule also wrote the labels, so the
# number is not the owner's judgment. Its false alarms are conditional offers ("say the word").
# Every pattern here costs time linear in the reply: HRULE's whitespace never crosses a line, and
# ASKS, whose unanchored Cyrillic half costs ~0.5 µs a character, reads ASK_CHARS at most.
FENCE = re.compile(r"```.*?(?:```|$)", re.S)
HRULE = re.compile(r"^[^\S\n]*(?:-{3,}|\*{3,}|_{3,})[^\S\n]*$", re.M)
PARAGRAPH = re.compile(r"\n\s*\n")
ASKS = re.compile(
    r"\b(?:want me to|should i|shall i|do you want|would you like|your call|tell me|let me know"
    r"|say the word|waiting on you|waiting for you|awaiting your"
    r"|your (?:answer|decision|approval|go-ahead))\b"
    r"|(?:скажи|напиши|отпиши|подтверди|кинь|скинь|хочешь"
    r"|жду (?:тво|вывод|ответ|результат команды))", re.I)
ASK_CHARS = 2000  # the end of the last paragraph that is read; the longest of 1,072 real ones is 968


def wants_you(reply: str) -> bool:
    """Whether the last paragraph the agent says to him asks him something.

    Only the words said to him count: no code, no table rows, no quoted lines, and no draft
    written for someone else — a reply that ends on a horizontal rule is closing a quoted draft.
    """
    text = FENCE.sub("", reply).strip()
    parts = HRULE.split(text)
    if len(parts) > 2 and not parts[-1].strip():
        text = "\n".join(parts[:-2])
    text = "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith(("|", ">"))).strip()
    last = PARAGRAPH.split(text)[-1][-ASK_CHARS:]
    return "?" in last or bool(ASKS.search(last))
