#!/usr/bin/python3
"""Score `intervention` — Nudge or Correction — against the owner's own escapes.

The hook asks one question when the transcript tail says he pressed escape: is the message he
typed next an objection (a **Correction**, 1.0) or more work (a **Nudge**, 0.0)? #16 shipped that
question on two hand-run numbers and no script. This is the script.

  * **The ground truth is his, and it is hand-made.** `docs/research/own-transcripts.md` reads all
    46 interruptions in the corpus and tags each one; `experiments/conduct_classes.py` carries
    that table as `INTERRUPTIONS`, which is imported here rather than copied. QUEUE is a Nudge,
    EMPTY is unclassifiable, every other tag is a Correction.
  * **The state is the hook's own state**, built by `judge.prompt_state`: the message, clipped,
    and nothing beside it. A number measured on any other state does not transfer to the hook —
    that is the mistake this round is repaying.
  * **The free fact is scored beside the paid question.** `depth` — assistant messages into the
    turn when he pressed escape — is already on every line at no cost, and docs/signals.md claims
    it splits the two kinds. If depth alone separates them as well as Jev does, the question has
    not earned its request.

Nothing here writes into a live session; this is an offline pass over files.

Usage:
  /usr/bin/python3 experiments/intervention.py --dry-run     # locate and join, ask Jev nothing
  /usr/bin/python3 experiments/intervention.py               # the whole ground-truth bank
  /usr/bin/python3 experiments/intervention.py --sessions ebded00c,c3a84aea
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from overmind import judge, transcript  # noqa: E402  (after sys.path fix)

# The ground-truth bank and the corpus reading live in round 2's script; one copy, imported.
_SPEC = importlib.util.spec_from_file_location("conduct_classes",
                                               os.path.join(HERE, "conduct_classes.py"))
cc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cc)

FIRE = cc.FIRE  # p ≥ this is a Correction. Named, so it can be argued with.
PRICE_PER_MTOK_IN = cc.PRICE_PER_MTOK_IN
MATCH_SECONDS = 180  # the research doc's stamps are minute-precision; this is the join window
SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
DEPTH_SWEEP = (1, 2, 3, 4, 6, 10)  # "a shallow escape is a queue-jump" as a rule, for comparison
SECRET = re.compile(r"[A-Za-z0-9+_=-]{32,}")  # an unbroken run that long is a key, not prose
ATTEMPTS = 6  # per request: the endpoint resets a connection now and then, and one reset that
              # loses the other 44 answers is a run nobody can reproduce


# ---------------------------------------------------------------------------- reading the corpus

def escapes(path: str) -> list[dict]:
    """Every interruption in one transcript, with the message the owner sent next.

    Forward, one record at a time, through overmind.transcript — the same vocabulary the hook
    reads with. `depth` and `tools` are the turn as it stood when he pressed escape; `prompt` is
    what he typed afterwards, in full, which is what the hook hands to Jev.
    """
    found: list[dict] = []
    pending: dict | None = None
    depth = tools = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            kind = record.get("type")
            if kind == "assistant":
                depth += 1
                tools += len(transcript.tool_calls(record))
                continue
            if kind != "user":
                continue
            if transcript.is_interruption(record):
                pending = {"ts": str(record.get("timestamp") or ""), "depth": depth,
                           "tools": tools, "prompt": ""}
                found.append(pending)
                depth = tools = 0
                continue
            text = transcript.owner_message(record)
            if text is None:
                continue
            if pending is not None:
                pending["prompt"] = text
                pending = None
            depth = tools = 0
    return found


def bank(prefixes: list[str]) -> list[dict]:
    """The located escapes joined to the hand tag, in time order, session by session."""
    items = []
    for prefix in prefixes:
        path = cc.find_transcript(prefix)
        known = [(cc.parse_ts(ts), tag) for sid, ts, tag in cc.INTERRUPTIONS if sid == prefix]
        located = escapes(path)
        for hit in located:
            row = dict(hit, session_id=prefix, tag="", kind="unmatched")
            if hit["ts"] and known:
                best = min(known, key=lambda k: abs(k[0] - cc.parse_ts(hit["ts"])))
                if abs(best[0] - cc.parse_ts(hit["ts"])) <= MATCH_SECONDS:
                    row["tag"] = best[1]
                    row["kind"] = {"QUEUE": "nudge", "EMPTY": "unknown"}.get(best[1], "correction")
            items.append(row)
        print("%-10s %3d escapes located, %2d of them tagged"
              % (prefix, len(located), sum(1 for i in items
                                           if i["session_id"] == prefix and i["tag"])),
              file=sys.stderr)
    items.sort(key=lambda r: r["ts"])
    return items


# ---------------------------------------------------------------------------- scoring

def rate(values: list[float], at: float = FIRE) -> float:
    return round(sum(1 for v in values if v >= at) / len(values), 4) if values else 0.0


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def auc(corrections: list[float], nudges: list[float]) -> float:
    """Share of Correction/Nudge pairs the score orders right, ties at half. 0.50 is a coin flip."""
    if not corrections or not nudges:
        return 0.0
    wins = sum(1.0 if c > n else 0.5 if c == n else 0.0 for c in corrections for n in nudges)
    return round(wins / (len(corrections) * len(nudges)), 4)


def at_threshold(corrections: list[float], nudges: list[float], cut: float) -> dict:
    """One row of the sweep: what calling p ≥ cut a Correction gets right and gets wrong."""
    hits = sum(1 for p in corrections if p >= cut)
    false_alarms = sum(1 for p in nudges if p >= cut)
    total = len(corrections) + len(nudges)
    return {"cut": cut, "recall": round(hits / len(corrections), 4) if corrections else 0.0,
            "fire_nudge": round(false_alarms / len(nudges), 4) if nudges else 0.0,
            "precision": round(hits / (hits + false_alarms), 4) if hits + false_alarms else None,
            "accuracy": round((hits + len(nudges) - false_alarms) / total, 4) if total else 0.0}


def depth_rows(items: list[dict]) -> list[dict]:
    """The same table for the free fact: *a turn he let run this long was going wrong*."""
    corrections = [i["depth"] for i in items if i["kind"] == "correction"]
    nudges = [i["depth"] for i in items if i["kind"] == "nudge"]
    rows = []
    for cut in DEPTH_SWEEP:
        row = at_threshold([float(d) for d in corrections], [float(d) for d in nudges], float(cut))
        row["cut"] = cut
        rows.append(row)
    return rows


def ask_all(items: list[dict], key: str, workers: int) -> tuple[list[int], int]:
    """One Jev request per escape, on the hook's own state. Retries inside, then fails loudly."""
    latencies: list[int] = []
    tokens = 0

    def work(item: dict) -> tuple[dict, int, int]:
        scores, ms, tok = cc.ask(judge.prompt_state(item["prompt"]), judge.PROMPT, key, ATTEMPTS)
        item["p"] = scores["intervention"]
        return item, ms, tok

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (item, ms, tok) in enumerate(pool.map(work, items), 1):
            latencies.append(ms)
            tokens += tok
            if done % 10 == 0 or done == len(items):
                print("  scored %d/%d escapes" % (done, len(items)), file=sys.stderr)
    return latencies, tokens


# ---------------------------------------------------------------------------- reporting

def verdict(summary: dict) -> str:
    """Mechanical, and hostile to the question: it has to beat the free fact to keep its request."""
    if summary["n_correction"] < 5 or summary["n_nudge"] < 5:
        return "no evidence"
    if summary["lift"] < 0.20:
        return "drop — it does not separate the two kinds"
    if summary["auc"] <= summary["depth_auc"]:
        return "drop — depth is free and orders them as well"
    return "keep"


def summarise(items: list[dict], meta: dict) -> dict:
    corrections = [i["p"] for i in items if i["kind"] == "correction"]
    nudges = [i["p"] for i in items if i["kind"] == "nudge"]
    depth_c = [float(i["depth"]) for i in items if i["kind"] == "correction"]
    depth_n = [float(i["depth"]) for i in items if i["kind"] == "nudge"]
    summary = {
        "n_correction": len(corrections), "n_nudge": len(nudges),
        "fire_correction": rate(corrections), "fire_nudge": rate(nudges),
        "mean_correction": mean(corrections), "mean_nudge": mean(nudges),
        "auc": auc(corrections, nudges), "depth_auc": auc(depth_c, depth_n),
        "sweep": [at_threshold(corrections, nudges, cut) for cut in SWEEP],
        "depth_sweep": depth_rows(items),
    }
    summary["lift"] = round(summary["fire_correction"] - summary["fire_nudge"], 4)
    summary["mean_lift"] = round(summary["mean_correction"] - summary["mean_nudge"], 4)
    summary["at_fire"] = at_threshold(corrections, nudges, FIRE)
    summary["best_depth"] = max(summary["depth_sweep"], key=lambda r: r["accuracy"])
    summary["verdict"] = verdict(summary)
    summary.update(meta)
    return summary


def quote(item: dict, width: int = 400) -> str:
    """What he said next, as the artifacts may keep it: collapsed, clipped, tokens taken out.

    Jev is shown the message whole, exactly as the hook would show it. What is written to disk is
    this, because he pastes keys into a session and a results folder lives in the repo.
    """
    text = SECRET.sub("…redacted…", " ".join(item["prompt"].split()))
    return (text[:width] + "…") if len(text) > width else (text or "(no message followed)")


def sweep_table(rows: list[dict], label: str) -> str:
    return cc.md_table([label, "Fires on Corrections", "Fires on Nudges", "Precision", "Accuracy"],
                       [["%s" % r["cut"], cc.pct(r["recall"]), cc.pct(r["fire_nudge"]),
                         "—" if r["precision"] is None else cc.pct(r["precision"]),
                         cc.pct(r["accuracy"])] for r in rows])


def write_validation(path: str, s: dict, items: list[dict]) -> None:
    scored = [i for i in items if "p" in i]
    body = [
        "# `intervention` — Nudge or Correction, measured", "",
        "The hook pays for one question when the owner presses escape: **does the message he sent "
        "next object to what the assistant was doing?** 1.0 is a Correction, 0.0 a Nudge. The "
        "state is the hook's own — `judge.prompt_state`, the message and nothing else — so this "
        "number is the number the hook carries.", "",
        "Ground truth: the %d interruptions hand-read in `docs/research/own-transcripts.md`. QUEUE "
        "is a Nudge, every other tag is a Correction, EMPTY is unclassifiable. %d located in the "
        "transcripts, %d of them with a message to judge: **%d Corrections, %d Nudges**."
        % (len(cc.INTERRUPTIONS), s["located"], len(scored), s["n_correction"], s["n_nudge"]), "",
        "| | Corrections | Nudges | Separation |", "|---|---|---|---|",
        "| Fires (p ≥ %.2f) | %s | %s | **%s** |"
        % (FIRE, cc.pct(s["fire_correction"]), cc.pct(s["fire_nudge"]), cc.pp(s["lift"])),
        "| Mean p | %.3f | %.3f | **%+.3f** |"
        % (s["mean_correction"], s["mean_nudge"], s["mean_lift"]),
        "", "**AUC %.2f** — the chance it scores a Correction above a Nudge, ties at half; 0.50 is "
        "a coin flip. At the firing threshold: precision %s, accuracy %s."
        % (s["auc"], "—" if s["at_fire"]["precision"] is None else cc.pct(s["at_fire"]["precision"]),
           cc.pct(s["at_fire"]["accuracy"])),
        "", "**Verdict: %s.**" % s["verdict"], "",
        "## The threshold", "",
        "Firing at %.2f is a choice, not a fact. Here it is at six of them." % FIRE, "",
        sweep_table(s["sweep"], "p ≥"), "",
        "## Against the free fact", "",
        "`depth` — assistant messages into the turn when he pressed escape — is on the line "
        "already and costs nothing. docs/signals.md says it splits the two kinds (42%% land in the "
        "first three messages, 31%% after ten). If it separated them as well as the question does, "
        "the question would not be worth a request. Depth AUC **%.2f** against the question's "
        "**%.2f**; the best depth rule here is *correction if depth ≥ %s*, accuracy %s, against "
        "the question's %s." % (s["depth_auc"], s["auc"], s["best_depth"]["cut"],
                                cc.pct(s["best_depth"]["accuracy"]), cc.pct(s["at_fire"]["accuracy"])),
        "", sweep_table(s["depth_sweep"], "depth ≥"), "",
        "## Every escape, with what he said next", "",
        cc.md_table(["When", "Session", "Kind", "Tag", "depth", "p", "Read right?"],
                    [[i["ts"][:16].replace("T", " "), "`%s`" % i["session_id"], i["kind"],
                      i["tag"] or "—", str(i["depth"]), "%.3f" % i["p"],
                      "yes" if (i["p"] >= FIRE) == (i["kind"] == "correction") else "**no**"
                      if i["kind"] in ("correction", "nudge") else "—"]
                     for i in scored]), "",
    ]
    for item in scored:
        body += ["> %s" % quote(item),
                 "", "`%s` · %s · %s · depth %d · **p %.3f**"
                 % (item["session_id"], item["ts"][:16].replace("T", " "),
                    item["kind"] + (" (%s)" % item["tag"] if item["tag"] else ""),
                    item["depth"], item["p"]), ""]
    body += ["---", "", "Cost $%.4f over %d requests · median %d ms · p95 %d ms · %d input tokens."
             % (s["cost_usd"], s["requests"], s["latency_ms"]["median"], s["latency_ms"]["p95"],
                s["input_tokens"]), ""]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(body))


def fold(title: str, note: str, body: str) -> str:
    """One closed section of the report. Level 0 stays on one screen; everything else folds."""
    return ('<details><summary><h2>%s</h2><span class="dim">%s</span></summary>'
            '<div class="body">%s</div></details>' % (cc.esc(title), cc.esc(note), body))


def write_report(path: str, s: dict, items: list[dict]) -> None:
    scored = [i for i in items if "p" in i]
    cards = [("corrections", s["n_correction"]), ("nudges", s["n_nudge"]),
             ("fires on corrections", cc.pct(s["fire_correction"])),
             ("fires on nudges", cc.pct(s["fire_nudge"])),
             ("separation", cc.pp(s["lift"])), ("auc", "%.2f" % s["auc"]),
             ("depth auc", "%.2f" % s["depth_auc"]), ("cost", "$%.4f" % s["cost_usd"])]

    def rows(sweep: list[dict], label: str) -> str:
        return ('<table><thead><tr><th>%s</th><th class="n">Corrections</th>'
                '<th class="n">Nudges</th><th class="n">Precision</th><th class="n">Accuracy</th>'
                '</tr></thead><tbody>%s</tbody></table>'
                % (label, "".join(
                    '<tr><td class="mono">%s</td><td class="n sep">%s</td><td class="n dim">%s</td>'
                    '<td class="n">%s</td><td class="n"><b>%s</b></td></tr>'
                    % (r["cut"], cc.pct(r["recall"]), cc.pct(r["fire_nudge"]),
                       "—" if r["precision"] is None else cc.pct(r["precision"]),
                       cc.pct(r["accuracy"])) for r in sweep)))

    quotes = "".join(
        '<p><span class="mono dim">%s · %s · depth %d</span> <b class="%s">%s</b>%s '
        '<span class="mono">p %.3f</span>%s<blockquote>%s</blockquote></p>'
        % (cc.esc(i["ts"][:16].replace("T", " ")), cc.esc(i["session_id"]), i["depth"],
           "sep" if i["kind"] == "correction" else "dim", i["kind"],
           ' <span class="dim">%s</span>' % cc.esc(i["tag"]) if i["tag"] else "", i["p"],
           "" if (i["p"] >= FIRE) == (i["kind"] == "correction")
           else ' <span class="dead">read wrong</span>', cc.esc(quote(i)))
        for i in scored)

    method = (
        "<p>One request per escape, on the state the hook itself builds "
        "(<code>judge.prompt_state</code>): the message he typed, clipped middle-out at %d chars, "
        "and nothing else. <code>depth</code> is kept out of it on purpose — a question able to "
        "read the length of what it judges goes on to measure the length.</p>"
        "<p>Ground truth is the hand classification of <code>docs/research/own-transcripts.md</code>"
        ", carried in <code>experiments/conduct_classes.py</code> as <code>INTERRUPTIONS</code> and "
        "joined to the located escapes by timestamp within %d s. QUEUE is a Nudge, EMPTY is "
        "unclassifiable, every other tag is a Correction.</p>"
        "<p class=\"dim\">%d escapes located across %d sessions, %d tagged and answered. "
        "Model %s. Generated %s.</p>"
        % (judge.MAX_TEXT, MATCH_SECONDS, s["located"], s["session_count"], len(scored),
           cc.esc(s["model"]), cc.esc(s["generated_at"])))

    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>intervention — Nudge or Correction — %(stamp)s</title><style>%(css)s</style></head><body>
<h1>`intervention`: is the message after the escape an objection?</h1>
<p class="sub">%(n)d of his own escapes, hand-tagged. 1.0 is a Correction, 0.0 a Nudge ·
 fires at p&nbsp;&ge;&nbsp;%(fire).2f · verdict <b>%(verdict)s</b></p>
<div class="cards">%(cards)s</div>
<table><thead><tr><th>&nbsp;</th><th class="n">Corrections</th><th class="n">Nudges</th>
<th class="n">Separation</th></tr></thead><tbody>
<tr><td>Fires (p &ge; %(fire).2f)</td><td class="n sep">%(fc)s</td><td class="n dim">%(fn)s</td>
<td class="n"><b>%(lift)s</b></td></tr>
<tr><td>Mean p</td><td class="n">%(mc).3f</td><td class="n dim">%(mn).3f</td>
<td class="n"><b>%(ml)+.3f</b></td></tr>
</tbody></table>
%(folds)s
</body></html>""" % {
        "stamp": cc.esc(s["generated_at"]), "css": cc.CSS, "fire": FIRE,
        "n": len(scored), "verdict": cc.esc(s["verdict"]),
        "cards": "".join('<div class="card"><b>%s</b><span>%s</span></div>' % (v, k)
                         for k, v in cards),
        "fc": cc.pct(s["fire_correction"]), "fn": cc.pct(s["fire_nudge"]),
        "lift": cc.pp(s["lift"]), "mc": s["mean_correction"], "mn": s["mean_nudge"],
        "ml": s["mean_lift"],
        "folds": "".join([
            fold("The threshold", "%.2f is a choice, not a fact" % FIRE, rows(s["sweep"], "p ≥")),
            fold("Against the free fact",
                    "depth auc %.2f vs %.2f" % (s["depth_auc"], s["auc"]),
                    "<p><code>depth</code> is on the line already and costs nothing. If it "
                    "separated the two kinds as well as the question does, the question would not "
                    "be worth a request.</p>" + rows(s["depth_sweep"], "depth ≥")),
            fold("Every escape, with what he said next", "%d answered" % len(scored), quotes),
            fold("Method and cost", "$%.4f · %d requests" % (s["cost_usd"], s["requests"]),
                    method + "<p>%d input tokens at $%.3f/Mtok = $%.4f. Latency: median %d ms, "
                    "p95 %d ms, max %d ms.</p>"
                    % (s["input_tokens"], PRICE_PER_MTOK_IN, s["cost_usd"],
                       s["latency_ms"]["median"], s["latency_ms"]["p95"], s["latency_ms"]["max"])),
        ]),
    }
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)


# ---------------------------------------------------------------------------- run

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sessions", default="", help="comma-separated prefixes, default: the whole bank")
    ap.add_argument("--workers", type=int, default=5, help="concurrent Jev requests")
    ap.add_argument("--dry-run", action="store_true", help="locate and join, ask Jev nothing")
    ap.add_argument("--out", default="", help="results directory (default: timestamped)")
    args = ap.parse_args(argv)

    prefixes = ([p for p in args.sessions.split(",") if p.strip()]
                or sorted({sid for sid, _, _ in cc.INTERRUPTIONS}))
    key = os.environ.get(judge.KEY_ENV, "")
    if not key and not args.dry_run:
        raise SystemExit("%s is not set; export it in ~/.zshrc" % judge.KEY_ENV)

    items = bank(prefixes)
    located = len(items)
    askable = [i for i in items if i["kind"] in ("correction", "nudge") and i["prompt"].strip()]
    print("\n%d escapes located · %d tagged and answerable · %d corrections · %d nudges"
          % (located, len(askable), sum(1 for i in askable if i["kind"] == "correction"),
             sum(1 for i in askable if i["kind"] == "nudge")), file=sys.stderr)
    if args.dry_run:
        for item in askable:
            print("  ESC %s %s depth=%-3d %-10s %s"
                  % (item["session_id"], item["ts"][:16], item["depth"], item["kind"],
                     quote(item, 70)), file=sys.stderr)
        return 0

    started = time.monotonic()
    latencies, tokens = ask_all(askable, key, args.workers)
    ordered = sorted(latencies)
    summary = summarise(askable, {
        "experiment": "intervention", "schema": 1, "question": "intervention",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": judge.MODEL, "fire_threshold": FIRE, "located": located,
        "session_count": len(prefixes), "answered": len(askable),
        "requests": len(latencies), "input_tokens": tokens,
        "cost_usd": round(tokens * PRICE_PER_MTOK_IN / 1e6, 6),
        "latency_ms": {"median": int(statistics.median(ordered)) if ordered else 0,
                       "p95": ordered[int(len(ordered) * 0.95) - 1] if ordered else 0,
                       "max": ordered[-1] if ordered else 0},
        "wall_s": round(time.monotonic() - started, 1),
    })

    out = args.out or os.path.join(HERE, "results", "intervention-" + time.strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(out, exist_ok=True)
    stored = [dict({k: v for k, v in i.items() if k != "prompt"}, quote=quote(i)) for i in items]
    with open(os.path.join(out, "escapes.json"), "w", encoding="utf-8") as handle:
        json.dump({"meta": {k: v for k, v in summary.items() if k != "sweep"}, "escapes": stored},
                  handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    write_validation(os.path.join(out, "validation.md"), summary, items)
    write_report(os.path.join(out, "report.html"), summary, items)

    print("\n%s" % out, file=sys.stderr)
    print("  corrections %s fire · nudges %s fire · lift %s · auc %.2f (depth %.2f) · %s"
          % (cc.pct(summary["fire_correction"]), cc.pct(summary["fire_nudge"]),
             cc.pp(summary["lift"]), summary["auc"], summary["depth_auc"], summary["verdict"]),
          file=sys.stderr)
    print("  cost $%.4f · %d requests · median %d ms · wall %.1f s"
          % (summary["cost_usd"], summary["requests"], summary["latency_ms"]["median"],
             summary["wall_s"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
