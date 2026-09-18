#!/usr/bin/python3
"""Does the hook's transcript tail reach the owner's previous message — before #17 and after it?

Hook v2 read the last 256 KB of a transcript backwards to his previous message, and on its first
day live 18 of 40 prompt lines said the window ran out first. This replays the tail, old and new,
at every moment the hook runs in the owner's real transcripts.

  * **A moment** is a transcript as it stood when a hook fired: before one of his prompts, before a
    `<task-notification>` (Claude Code delivers a background agent's return as a UserPromptSubmit
    too), and before each `stop_hook_summary` record, which Claude Code writes after the Stop
    hooks ran. The file is replayed at that length by reporting that size to `os.fstat` — neither
    implementation reads past `st_size`, so the replay is exact without copying a byte. Each
    transcript is walked forward once; every moment and every live line is placed from that walk.
  * **The filter is the hook's own**: a prompt `transcript.is_notification` calls a notification
    writes no line after #17, and the same predicate decides it here.
  * **The old tail is the old code**, the `overmind/` tree at BEFORE, extracted with `git archive`.
    The parent-process timing runs that tree's `hook.py` too.
  * **The bounds are work, not time**, so the rates are exact and the same on any machine at any
    load. MAX_LINES and MAX_PARSED are swept, each with the others as shipped; each moment the
    shipped tail leaves exhausted is attributed to the bound that stopped it by lifting the
    bounds one at a time.
  * **The live log is replayed too**: every v2 prompt and Stop line in events.jsonl written before
    LIVE_UNTIL, at the transcript length its timestamp implies. On prompt lines the old tail must
    reproduce the `depth` the line was written with, or the replay is not measuring what ran.
    Stop lines replay deeper, because a record's timestamp is when it was made and not when it
    reached the disk: the turn's last records are not on disk yet when the Stop hook reads it.
    So each clean live Stop is cut back by the depth it was logged short, which must reproduce
    the logged depth, and its `reply` is set against the whole turn's twice: as the hook read it,
    and with the turn's final message appended as the hook now does. The final message is the
    whole turn's last assistant prose, which is what `last_assistant_message` carries.
  * **The parent is timed whole**: `hook.py`, old and new interleaved, as a process on real and
    adversarial transcripts, wall time and the child's CPU time, with the load average recorded.

Nothing here writes into a live session or the live log; OVERMIND_HOME is a temporary folder.

Usage:
  /usr/bin/python3 experiments/tail_reach.py
  /usr/bin/python3 experiments/tail_reach.py --launches 10     # fewer parent launches
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
import types
from collections import Counter
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from overmind import log, transcript  # noqa: E402  (after sys.path fix)

_SPEC = importlib.util.spec_from_file_location("conduct_classes",
                                               os.path.join(HERE, "conduct_classes.py"))
cc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cc)

BEFORE = "54f7f46"  # the last commit with the 256 KB window
NEAR_S = 5.0  # a prompt record this close to a prompt line's timestamp is that line's prompt
SWEEP = {"MAX_LINES": (1000, 2000, 5000, 10000),
         "MAX_PARSED": (1 << 20, 2 << 20, 3 << 20, 4 << 20)}  # each swept with the others shipped
BOUNDS = ("MAX_LINES", "MAX_PARSED", "MAX_BYTES")  # lifted in this order to say which stopped a scan
LIFTED = 10 ** 12  # a bound no transcript reaches
LIVE_UNTIL = "2026-09-18T19:00"  # the hook runs from this working tree; #17 reached it here
KINDS = ("prompt", "notification", "stop")


def load_before(folder: str) -> types.ModuleType:
    """The `overmind/` tree at BEFORE, extracted into `folder`, and its transcript module."""
    archive = subprocess.run(["git", "-C", ROOT, "archive", BEFORE, "overmind"],
                             check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", folder], input=archive, check=True)
    spec = importlib.util.spec_from_file_location(
        "transcript_before", os.path.join(folder, "overmind", "transcript.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp(ts: str) -> float | None:
    try:
        return cc.parse_ts(ts)
    except ValueError:
        return None


def walk(path: str) -> list[dict]:
    """One forward pass over a transcript: every top-level record's byte span, its time, what the
    hook would take it for, and the prose of an assistant record."""
    out = []
    end = 0
    with open(path, "rb") as handle:
        for raw in handle:
            start, end = end, end + len(raw)
            try:
                record = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            said = ""
            if record.get("type") == "user" and record.get("toolUseResult") is None:
                said = transcript.record_text(record) or ""
            kind = None
            if record.get("subtype") == "stop_hook_summary":  # written after the Stop hooks ran
                kind = "stop"
            elif said and transcript.is_notification(said):
                kind = "notification"
            elif said:
                mine = transcript.owner_message(record)
                if mine:
                    kind, said = "prompt", mine
            assistant = record.get("type") == "assistant"
            out.append({"start": start, "end": end, "at": stamp(str(record.get("timestamp") or "")),
                        "ts": str(record.get("timestamp") or ""), "kind": kind, "said": said,
                        "assistant": assistant,
                        "words": transcript.assistant_text(record) if assistant else ""})
    return out


def moments(walked: dict[str, list[dict]]) -> list[dict]:
    """Every moment a hook fired, with the distance back to his previous message as the forward
    pass measures it — the answer the tail is trying to reach."""
    out = []
    for path, records in walked.items():
        last_owner = None
        for r in records:
            if r["kind"]:
                out.append({"kind": r["kind"], "path": path, "offset": r["start"], "ts": r["ts"],
                            "submitted": r["said"] if r["kind"] != "stop" else "",
                            "distance": None if last_owner is None else r["start"] - last_owner})
            if r["kind"] == "prompt":
                last_owner = r["start"]
    return out


def live_lines(walked: dict[str, list[dict]]) -> list[dict]:
    """v2 prompt and Stop lines from the live log, each placed at the transcript length its
    timestamp implies, and each prompt classified by the record written beside it.

    A record's timestamp is when it was made, not when it reached the disk, so that length holds
    the whole turn even where the hook read less of it. For a Stop the logged `depth` says how
    much less: `score` cuts the replay back by that many assistant records, whose offsets are
    kept here, to get the transcript the hook actually read. `final` is the turn's last prose,
    what the payload's `last_assistant_message` carries."""
    by_session = {os.path.basename(path)[:-len(".jsonl")]: path for path in walked}
    out = []
    for line in log.read():
        path = by_session.get(str(line.get("session_id")))
        when = stamp(str(line.get("ts") or ""))
        if line.get("v") != 2 or line.get("event") not in ("UserPromptSubmit", "Stop") \
                or str(line.get("ts") or "") >= LIVE_UNTIL or not path or when is None:
            continue  # not a v2 line, or a synthetic timing session, or a transcript since deleted
        records = walked[path]
        offset = max((r["end"] for r in records if r["at"] is not None and r["at"] <= when),
                     default=0)
        row = {"kind": "stop" if line["event"] == "Stop" else "prompt", "path": path,
               "offset": offset, "ts": line["ts"], "submitted": "",
               "logged_depth": line.get("depth"),
               "logged_exhausted": bool(line.get("tail_exhausted")),
               "logged_error": str(line.get("tail_error") or "")}
        if row["kind"] == "prompt":
            near = [r for r in records if r["said"] and r["at"] is not None
                    and abs(r["at"] - when) <= NEAR_S]
            if near:
                row["submitted"] = min(near, key=lambda r: abs(r["at"] - when))["said"]
                if transcript.is_notification(row["submitted"]):
                    row["kind"] = "notification"
        else:
            written = [r for r in records if r["end"] <= offset]
            row["final"] = next((r["words"] for r in reversed(written) if r["words"]), "")
            row["assistant_starts"] = [r["start"] for r in written if r["assistant"]][-8:]
        out.append(row)
    return out


def replay(tail_fn, path: str, offset: int, bounds: dict | None = None,
           **kwargs: str) -> tuple[dict, float]:
    """The tail as it ran when the file was `offset` bytes long, under `bounds`, and its ms."""
    bounds = {"MAX_LINES": transcript.MAX_LINES, **(bounds or {})}
    with mock.patch.object(os, "fstat", lambda fd: types.SimpleNamespace(st_size=offset)), \
            mock.patch.multiple(transcript, **bounds):
        t0 = time.perf_counter()
        result = tail_fn(path, **kwargs)
        ms = (time.perf_counter() - t0) * 1000
    return result, ms


def clean(row: dict) -> bool:
    """A live line whose logged depth is exact: it read cleanly, and the old tail, replayed,
    reached his message. Lines from before 602bf60 carry no `tail_exhausted` even when the window
    ran out, so the log's own flag is not enough."""
    return not (row["logged_error"] or row["logged_exhausted"] or row["old_exhausted"])


def score(rows: list[dict], before: types.ModuleType) -> None:
    for row in rows:
        at, asked = (row["path"], row["offset"]), row["submitted"]
        old, row["old_ms"] = replay(before.tail, *at, submitted=asked)
        new, row["new_ms"] = replay(transcript.tail, *at, submitted=asked)
        row["old_exhausted"], row["new_exhausted"] = old["exhausted"], new["exhausted"]
        row["old_depth"], row["new_depth"] = old["depth"], new["depth"]
        row["exhausted_at"] = {
            "%s=%d" % (bound, value): replay(transcript.tail, *at, {bound: value},
                                             submitted=asked)[0]["exhausted"]
            for bound, values in SWEEP.items() for value in values}
        if new["exhausted"]:
            lifted: dict = {}
            for bound in BOUNDS:
                lifted[bound] = LIFTED
                if not replay(transcript.tail, *at, lifted, submitted=asked)[0]["exhausted"]:
                    row["stopped_by"] = bound
                    break
        row["line_after"] = row["kind"] != "notification"  # the hook writes none for these
        if "assistant_starts" not in row or not clean(row):
            continue
        missed = old["depth"] - row["logged_depth"]  # assistant records not on disk yet
        if 0 <= missed <= len(row["assistant_starts"]):
            read = row["assistant_starts"][-missed] if missed else row["offset"]
            as_ran = replay(transcript.tail, row["path"], read)[0]
            fixed = replay(transcript.tail, row["path"], read, said=row["final"])[0]
            row["as_ran_depth_matches_log"] = as_ran["depth"] == row["logged_depth"]
            row["reply_whole_as_ran"] = as_ran["reply"] == new["reply"]
            row["reply_whole_with_final"] = fixed["reply"] == new["reply"]


def launch(argv: list[str], body: bytes, env: dict) -> tuple[float, float]:
    """One process: wall ms, and the CPU ms it spent (user + system)."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    proc = subprocess.run(["/usr/bin/python3"] + argv, input=body, capture_output=True, env=env,
                          timeout=60)
    wall = (time.perf_counter() - t0) * 1000
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert (proc.returncode, proc.stdout) == (0, b""), (argv, proc)
    return wall, ((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)) * 1000


def spread(values: list[float], qs: tuple = (0.5, 0.95)) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {}
    return {**{"p%d" % round(q * 100): ordered[min(len(ordered) - 1, int(q * len(ordered)))]
               for q in qs}, "max": ordered[-1]}


def hook_launches(n: int, before_dir: str, work: str) -> dict:
    """The whole parent process, old and new interleaved, on five transcripts."""
    his = '{"type":"user","message":{"content":"the thing he asked"}}\n'
    cases = {}

    def fixture(name: str, body: str) -> str:
        path = os.path.join(work, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    cases["his message three records back"] = fixture(
        "typical", his + '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\n')
    cases["the same, with a 7 MB tool result between"] = fixture(
        "giant", his + '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash",'
        '"input":{"command":"shot"}}]}}\n'
        + json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "x" * (7 << 20)}]}},
            separators=(",", ":")) + "\n"
        '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\n')
    biggest = max(glob.glob(os.path.join(cc.PROJECTS, "*", "*.jsonl")), key=os.path.getsize)
    cases["largest real transcript (%d MB)" % (os.path.getsize(biggest) >> 20)] = biggest
    cases["8 MB of one-token lines"] = fixture("junk", his + "{}\n" * (transcript.MAX_BYTES // 3))
    record = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "step " * 400},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls " * 50}}]}})
    cases["8 MB of records that all need a parse"] = fixture(
        "parse", his + (record + "\n") * (transcript.MAX_BYTES // len(record)))
    env = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
    env["OVERMIND_HOME"] = os.path.join(work, "home")
    hooks = {"before": [os.path.join(before_dir, "overmind", "hook.py")],
             "after": [os.path.join(ROOT, "overmind", "hook.py")]}
    out: dict = {"load_before": os.getloadavg()[0]}

    def timed(runs: list[tuple[float, float]]) -> dict:
        return {"wall": spread([r[0] for r in runs]), "cpu": spread([r[1] for r in runs])}

    for name, path in cases.items():
        body = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "tail-reach",
                           "cwd": ROOT, "transcript_path": path,
                           "prompt": "what is the status"}).encode()
        runs: dict = {"before": [], "after": []}
        for _ in range(n):
            for which in runs:
                runs[which].append(launch(hooks[which], body, env))
        out[name] = {which: timed(t) for which, t in runs.items()}
    out["bare /usr/bin/python3 -c pass"] = {
        "python": timed([launch(["-c", "pass"], b"", env) for _ in range(n)])}
    out["load_after"] = os.getloadavg()[0]
    return out


def rate(rows: list[dict], key: str) -> str:
    hit = sum(1 for r in rows if r[key])
    return "%d of %d (%.1f%%)" % (hit, len(rows), 100.0 * hit / len(rows)) if rows else "—"


def summary(rows: list[dict], live: list[dict]) -> dict:
    corpus = {k: [r for r in rows if r["kind"] == k] for k in KINDS}
    lines_before = corpus["prompt"] + corpus["notification"]
    prompts = [r for r in live if r["kind"] != "stop" and clean(r)]
    stops = [r for r in live if r["kind"] == "stop"]
    compared = [r for r in stops if "reply_whole_as_ran" in r]
    deeper = [r["old_depth"] - r["logged_depth"] for r in stops if clean(r)]
    exhausted = [r for r in rows if r["new_exhausted"]]
    return {
        "corpus": {k: {"n": len(v), "before": rate(v, "old_exhausted"),
                       "after": rate(v, "new_exhausted"),
                       "distance_kb": {q: kb / 1024 for q, kb in spread(
                           [r["distance"] for r in v if r["distance"] is not None],
                           (0.5, 0.9, 0.99)).items()}}
                   for k, v in corpus.items()},
        "prompt_lines": {"before": rate(lines_before, "old_exhausted"),
                         "after": rate([r for r in lines_before if r["line_after"]],
                                       "new_exhausted")},
        "shipped": {"MAX_BYTES": transcript.MAX_BYTES, "MAX_LINES": transcript.MAX_LINES,
                    "MAX_PARSED": transcript.MAX_PARSED},
        "still_exhausted_stopped_by": dict(Counter(r["stopped_by"] for r in exhausted)),
        "exhausted_at": {at: {k: "%.1f%%" % (100.0 * sum(1 for r in v if r["exhausted_at"][at])
                                             / len(v)) for k, v in corpus.items()}
                         for at in rows[0]["exhausted_at"]},
        "tail_ms": {"before": spread([r["old_ms"] for r in rows]),
                    "after": spread([r["new_ms"] for r in rows])},
        "live": {
            "replay_depth_matches_log": "%d of %d" % (
                sum(1 for r in prompts if r["old_depth"] == r["logged_depth"]), len(prompts)),
            "stop_replay_deeper_by": {str(d): n for d, n in sorted(Counter(deeper).items())},
            "prompt_lines_before": rate([r for r in live if r["kind"] != "stop"], "old_exhausted"),
            "notifications_among_them": sum(1 for r in live if r["kind"] == "notification"),
            "prompt_lines_after": rate([r for r in live if r["kind"] == "prompt"], "new_exhausted"),
            "stops_before": rate(stops, "old_exhausted"),
            "stops_after": rate(stops, "new_exhausted"),
            "stop_cut_back_reproduces_logged_depth": rate(compared, "as_ran_depth_matches_log"),
            "stop_reply_whole_as_ran": rate(compared, "reply_whole_as_ran"),
            "stop_reply_whole_with_final_message": rate(compared, "reply_whole_with_final"),
        },
    }


def table(head: list[str], body: list[list[str]]) -> str:
    return "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        "".join("<th>%s</th>" % cc.esc(h) for h in head),
        "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % cc.esc(str(c)) for c in row)
                for row in body))


def report(folder: str, result: dict) -> None:
    s, launches = result["summary"], result["launches"]
    live = s["live"]
    timing = [[case] + ["%.0f / %.0f ms wall, %.0f ms cpu" % (
        t["wall"]["p50"], t["wall"]["p95"], t["cpu"]["p50"]) for t in v.values()]
        for case, v in launches.items() if isinstance(v, dict)]
    body = "".join([
        cc.fold("By kind of moment", "distance back to his message, KB", table(
            ["moment", "n", "exhausted before", "exhausted after", "distance p50 / p90 / p99"],
            [[k, v["n"], v["before"], v["after"], " / ".join(
                "%.0f" % x for x in v["distance_kb"].values())] for k, v in s["corpus"].items()])
            + "<p>Still exhausted after, by the bound that stopped the scan: %s.</p>"
            % cc.esc(json.dumps(s["still_exhausted_stopped_by"]))),
        cc.fold("The count bounds swept", "exhausted, each bound alone moved", table(
            ["bound"] + list(KINDS), [[at] + [v[k] for k in KINDS]
                                      for at, v in s["exhausted_at"].items()])),
        cc.fold("The live log replayed", "%s prompt lines, %s Stops" % (
            live["prompt_lines_after"], live["stops_after"]), table(
            ["measure", "value"], [[k, v] for k, v in live.items()])),
        cc.fold("The parent process", "median / p95 wall, median cpu; load %.1f → %.1f" % (
            launches["load_before"], launches["load_after"]),
            table(["case", "before", "after"], timing)),
        cc.fold("Method", "bounds are work, so these rates are exact",
                "<pre>%s</pre>" % cc.esc(__doc__ or "")),
    ])
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Tail reach — #17 — %s</title><style>%s</style></head><body>
<h1>Does the tail reach his previous message?</h1>
<p class="sub">%d moments in the owner's transcripts, old tail (%s) against the shipped one
(MAX_BYTES %d MB, MAX_LINES %d, MAX_PARSED %d MB). Generated %s at load %.1f.</p>
<div class="cards">%s</div>%s</body></html>""" % (
        result["generated"], cc.CSS, sum(v["n"] for v in s["corpus"].values()), BEFORE,
        s["shipped"]["MAX_BYTES"] >> 20, s["shipped"]["MAX_LINES"], s["shipped"]["MAX_PARSED"] >> 20,
        result["generated"], launches["load_before"],
        "".join('<div class="card"><b>%s → %s</b><span>%s</span></div>' % (
            b.split(" (")[-1].rstrip(")"), a.split(" (")[-1].rstrip(")"), label)
            for label, b, a in (
                ("prompt lines exhausted", s["prompt_lines"]["before"], s["prompt_lines"]["after"]),
                ("his prompts", s["corpus"]["prompt"]["before"], s["corpus"]["prompt"]["after"]),
                ("stops", s["corpus"]["stop"]["before"], s["corpus"]["stop"]["after"]))),
        body)
    with open(os.path.join(folder, "report.html"), "w", encoding="utf-8") as handle:
        handle.write(page)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launches", type=int, default=30)
    args = parser.parse_args()
    walked = {path: walk(path) for path in sorted(glob.glob(os.path.join(cc.PROJECTS, "*",
                                                                         "*.jsonl")))}
    rows, live = moments(walked), live_lines(walked)
    del walked
    with tempfile.TemporaryDirectory() as before_dir, tempfile.TemporaryDirectory() as work:
        before = load_before(before_dir)
        score(rows, before)
        score(live, before)
        launches = hook_launches(args.launches, before_dir, work)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    result = {"generated": generated, "before": BEFORE, "summary": summary(rows, live),
              "launches": launches}
    folder = os.path.join(HERE, "results", "tail-reach-" + generated)
    os.makedirs(folder)
    with open(os.path.join(folder, "result.json"), "w", encoding="utf-8") as handle:
        live_rows = [{k: v for k, v in r.items() if k not in ("submitted", "final")} for r in live]
        json.dump({**result, "live": live_rows}, handle, indent=1)
    report(folder, result)
    print(json.dumps(result, indent=1))
    print(folder)


if __name__ == "__main__":
    main()
