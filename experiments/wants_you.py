#!/usr/bin/python3
"""Score the **Wants you** rule against 200 Stops read by hand (#17).

docs/signals.md: Wants you is read from the text, never judged. v2 stopped asking Jev for it and
nothing replaced it. The obvious reading — *the reply ends in a question* — was wrong 3 times in
10 in an earlier survey, so the rule in `overmind/rules.py` is scored here before it is trusted.

  * **The text is the hook's own input**: `last_assistant_message` from the Stop payload, which
    Claude Code sends and ~/.claude/logs/stop.json has kept since it started to.
  * **The ground truth is a careful reading, made before any rule was written — by the same
    agent that then wrote the rule, so every number here is optimistic.** It is not the owner's
    judgment; his labels on the dashboard are what will say how good the rule is. 200 distinct
    final messages drawn at random (seed 17) from that log, each read in full and marked by one
    definition: *the message leaves open a question to him, or an explicit ask to decide, approve,
    choose, supply or do something the work waits on.* Not: a finished report, a status while
    background agents run, a question the message answers itself, a question quoted or put to a
    third party (a draft email), a suggestion stated as a statement. Two calls are named because a
    rule cannot see them: a conditional offer ("say the word if you want X") is **not** Wants you,
    and neither is "when the cable arrives, call me" — nothing waits on him now.
  * **The rule was written on the first 100 and is scored on the other 100**, which it never saw.
    Both are reported; only the held-out number is the rule's accuracy.
  * **The baseline is scored beside it**: the last non-empty line ends in a question mark.

Labels are keyed by the first 12 hex of the message's sha1, so no text lives in this repo. Nothing
here writes anywhere but experiments/results/.

Usage:
  /usr/bin/python3 experiments/wants_you.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from overmind import rules  # noqa: E402  (after sys.path fix)

_SPEC = importlib.util.spec_from_file_location("conduct_classes",
                                               os.path.join(HERE, "conduct_classes.py"))
cc = importlib.util.module_from_spec(_SPEC)  # the report's stylesheet and folds
_SPEC.loader.exec_module(cc)

STOPS = os.path.expanduser("~/.claude/logs/stop.json")
DEV = 100  # the first DEV labels are the ones the rule was written on

# (sha1[:12] of last_assistant_message, wants you), in the order they were drawn and read.
LABELS = [
    ("746c440e7543", True), ("336c55f20b66", True), ("e91b51219b81", True),
    ("17297d6d85be", False), ("fdcca4c54419", False), ("f1cf69451cee", False),
    ("9290dc04cf9e", True), ("51c9bf35d422", True), ("d048b573f4d7", False),
    ("ab609da1a6d5", True), ("743e7a66cf70", False), ("03bbc0e1c554", False),
    ("69773c7877d3", True), ("49bbe4ea4318", True), ("9da85dafd96a", False),
    ("45596af0d709", False), ("22ac4a7060f8", True), ("9d2376de5069", True),
    ("cfbabac6ae6f", False), ("38d18f6bd5b4", False), ("2fa338d2ff34", True),
    ("543b238d6ebf", True), ("81685a99e2cc", False), ("cbf9153f549c", False),
    ("3392c6d4c220", True), ("ba4a8a61b9ab", True), ("fb80d0ba6063", False),
    ("23f50cad4ae4", False), ("56d453ccff2e", False), ("f629d7a38318", True),
    ("303be2bef0b9", True), ("840f0a346884", False), ("c9dd7ad362f0", True),
    ("8c4be0175644", True), ("a73125bf7eeb", False), ("e03577268c56", True),
    ("bf9859cc6573", False), ("d3fb02274f30", False), ("995160029557", False),
    ("241eafbf1322", False), ("c06433ad95a4", False), ("ec84616453e8", False),
    ("c5cc461323fd", False), ("05587a66af71", False), ("f029303bc6dc", True),
    ("09670599b191", False), ("dd7e6874c73d", True), ("4e6dd5dbdba1", False),
    ("3f0de40742fa", False), ("d7c025733b6e", True), ("25abf6310fee", True),
    ("4c70c4f579b2", False), ("872188b78af2", False), ("57548198a436", False),
    ("d88efa0b012c", True), ("3f9204de425c", True), ("b75ca46f674f", True),
    ("f4f55fabddd8", False), ("2fcdfa164ccf", True), ("2774253054b1", False),
    ("c711452ed6cb", True), ("6d7bebb12c8d", True), ("d9827e708d1b", True),
    ("f4954438e9a8", False), ("e8d3822c41e1", True), ("a06094151961", False),
    ("718eff8c034c", False), ("2f89dcbea10e", True), ("70c8e736513c", True),
    ("6d600683f08d", True), ("172617ac18cd", True), ("b0ff314c8cfd", True),
    ("83117a30b2ef", True), ("1c6265436423", False), ("981d02abf1fb", False),
    ("feacc04ed020", True), ("e0add0bd0a47", True), ("c9f5839ee28f", True),
    ("0fc259a18930", False), ("613e93f543a8", True), ("c5dbf9399af8", False),
    ("812502d62238", False), ("be9630586714", True), ("bb8dba2ddce7", False),
    ("8c130d6d0147", False), ("e8abf32227dc", True), ("810fc369cb51", False),
    ("d442c76ea62e", False), ("4b4b25dd5c75", True), ("8615cad240f4", True),
    ("0a0f8ca79dc9", False), ("fb0ce1215907", False), ("738974bfa5db", False),
    ("b0c871c04fb4", False), ("b8cbb7203608", False), ("df6f0fba1b9e", True),
    ("dfb7db06e235", False), ("e8fa3300b050", False), ("55d9ce0fce03", True),
    ("8da701cbc6eb", False), ("90a3d52d90d7", True), ("56adc5f78411", False),
    ("0b39575a6636", True), ("d1e52d481e7a", True), ("40ffcb645039", False),
    ("21d21136b78f", False), ("eeb6ded769e5", False), ("71b2d94e56d2", False),
    ("2fcaaa0d9f59", False), ("a11cb3e3dc5d", False), ("f9b13c7c4770", True),
    ("cc4494bdf314", True), ("b91944931870", False), ("4afcab2a0127", True),
    ("0dadade10223", True), ("bbac5459c11e", False), ("10725bad74a6", True),
    ("2d87e8b535d0", True), ("67386e6433b5", True), ("b46f060cd019", False),
    ("36505a12a3e1", False), ("b3610d559191", True), ("2d08ba131b70", False),
    ("2c6230f4dd8c", True), ("74c532d7b3f0", True), ("9d1cac687048", False),
    ("659a64597300", False), ("6a8704593d03", False), ("30c39a8b9cdd", False),
    ("28117e757ee2", False), ("6448f02d6dae", True), ("a2842d056c51", True),
    ("d840c2576b81", False), ("08703491f28d", False), ("e07c6e7b66bd", False),
    ("e6ee5156fda9", False), ("77f8fd9d2e8a", False), ("7d84665cb10c", False),
    ("399f5a142b66", True), ("f72faed4cdea", False), ("37336df3a0c8", True),
    ("0cc7fc74c776", True), ("f3895a3ecf86", True), ("3dd4bcfc6dac", False),
    ("f3adc4d2945d", True), ("b70eb02940e9", True), ("534c55f937a2", True),
    ("e5fdceba6b11", True), ("e978ff80c42e", True), ("af7c6c816738", True),
    ("153b9214af8d", True), ("f95b47d338d5", False), ("81a89c3d6114", False),
    ("411df33c00db", True), ("dc14ef677792", False), ("9741ae8b0361", True),
    ("6d7246f3dc9a", True), ("c259380958c7", False), ("f3a4ec12325b", False),
    ("c7c6fa4d8faa", True), ("e5eb2308ced8", False), ("5076a25e533b", False),
    ("76549938fafa", False), ("7dfa5d5ac2f0", True), ("b02552076273", True),
    ("8536afc65d6f", False), ("4d3b5a95c720", False), ("b539c7404040", False),
    ("eed866be0aac", True), ("b9403498de95", True), ("7fd83ddb311c", True),
    ("5da97ddb01ae", False), ("df6520aa509c", True), ("8c9726c1ada6", False),
    ("253742d48b8a", True), ("884d128c0e4e", False), ("7dfd00ad3edf", True),
    ("f4973ae48862", True), ("70c95e533644", False), ("984acf345993", False),
    ("93bd1f2efa31", False), ("799e03bd87d6", False), ("97dfb327ddbe", True),
    ("f2d7af6cfa24", True), ("fc1629afe3e2", True), ("6ab0e65912bb", False),
    ("35e6132d3e67", False), ("0cd2569add75", True), ("e17757a625b9", True),
    ("1de428927bde", True), ("5d20249e5338", False), ("953341c4da60", True),
    ("5060948633ff", True), ("11571b29681f", False), ("d615a67ad256", True),
    ("ae5d7d7252bd", False), ("e24ed930bf5d", True), ("1c3644e217ff", True),
    ("336535f23a18", True), ("e4e0fe8862af", False),
]


def baseline(reply: str) -> bool:
    """The reply's last non-empty line ends in a question mark."""
    lines = [line.strip() for line in reply.strip().splitlines() if line.strip()]
    return bool(lines) and lines[-1].rstrip("*_ )»\"'").endswith("?")


def messages() -> dict[str, str]:
    with open(STOPS, encoding="utf-8") as handle:
        payloads = json.load(handle)
    out = {}
    for payload in payloads:
        said = payload.get("last_assistant_message") if isinstance(payload, dict) else None
        if isinstance(said, str) and said.strip():
            out.setdefault(hashlib.sha1(said.encode()).hexdigest()[:12], said)
    return out


def score(rule, rows: list[tuple[str, bool]]) -> dict:
    cells = Counter((rule(said), truth) for said, truth in rows)
    tp, fp, fn, tn = cells[True, True], cells[True, False], cells[False, True], cells[False, False]
    return {"n": len(rows), "accuracy": round((tp + tn) / len(rows), 3) if rows else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def main() -> None:
    text = messages()
    found = [(i, text[key], truth) for i, (key, truth) in enumerate(LABELS) if key in text]
    splits = {"held out (the rule's accuracy)": [(s, t) for i, s, t in found if i >= DEV],
              "written on": [(s, t) for i, s, t in found if i < DEV],
              "all": [(s, t) for _, s, t in found]}
    result = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S"),
              "labels": len(LABELS), "found_in_log": len(found),
              "wants_you_base_rate": round(sum(t for _, _, t in found) / len(found), 3),
              "rule": {k: score(rules.wants_you, v) for k, v in splits.items()},
              "baseline": {k: score(baseline, v) for k, v in splits.items()},
              "held_out_errors": [{"id": LABELS[i][0], "label": t, "rule": rules.wants_you(s)}
                                  for i, s, t in found if i >= DEV and rules.wants_you(s) != t]}
    folder = os.path.join(HERE, "results", "wants-you-" + result["generated"])
    os.makedirs(folder)
    with open(os.path.join(folder, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (cc.esc(k), *(
        "acc %(accuracy)s · prec %(precision)s · rec %(recall)s (tp %(tp)d fp %(fp)d fn %(fn)d tn %(tn)d)"
        % result[w][k] for w in ("rule", "baseline"))) for k in splits)
    held = result["rule"]["held out (the rule's accuracy)"]
    with open(os.path.join(folder, "report.html"), "w", encoding="utf-8") as handle:
        handle.write("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Wants you — #17 — %s</title><style>%s</style></head><body>
<h1>Wants you, read from the text</h1>
<p class="sub">Held out: accuracy %s, precision %s, recall %s on %d Stops the rule never saw.
%d of %d labels found in the log; %.0f%% of them want him. Optimistic: the labels were written by
the agent that wrote the rule, not by the owner.</p>%s</body></html>""" % (
            result["generated"], cc.CSS, held["accuracy"], held["precision"], held["recall"],
            held["n"], len(found), len(LABELS), 100 * result["wants_you_base_rate"],
            cc.fold("Every split, rule against the last-line baseline", "%d labels" % len(found),
                    "<table><thead><tr><th>split</th><th>rules.wants_you</th>"
                    "<th>last line ends in ?</th></tr></thead><tbody>%s</tbody></table>" % rows)))
    print(json.dumps(result, indent=1))
    print(folder)


if __name__ == "__main__":
    main()
