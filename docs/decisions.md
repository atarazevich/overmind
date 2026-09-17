# Decisions

## 2026-09-17 — Substrate
Jev (TypeSafe System One) as the per-event judge instead of an LLM. Context: the April Overmind ran an LLM watcher and was too slow and expensive to run on every event; Jev returns typed probabilities in ~300 ms at ~$0.04/day. Local alternatives (GLiNER2.5, constrained-decoding on Qwen 1.5B) noted; not calibrated; to be compared later on the labels this project collects.

## 2026-09-17 — Observe first
Phases fixed as observe → label → inject. No action of any kind before the calibration curve exists.

## 2026-09-17 — Hook process shape
`os.fork` + `setsid` with stdio on `/dev/null`, not `subprocess.Popen` of a second interpreter: `import subprocess` costs 4–5 ms and a second interpreter start ~20 ms, against a 50 ms synchronous budget. `urllib.request` (23–25 ms) is imported only in the child. The wiring and the shebang name `/usr/bin/python3` (system 3.9.6, the agent-notch pattern) because the bare `python3` on PATH is a pyenv shim that adds ~110 ms. Context: measured with `-X importtime` and `perf_counter` around the hook process on 2026-09-17.

## 2026-09-17 — Dashboard direction (owner, after board round 1)
Round-1 board (dense monochrome instrument table) rejected by the owner: "very bad… needs to look a hundred times more readable". New direction, fixed by the owner: **Plotly** for every chart (vendored `overmind/static/vendor/plotly.min.js`, served by the stdlib server, so still offline and no CDN at runtime); **Now, Timeline and History visible simultaneously** on one 1440×900 screen, no folds for the three views; **tooltips on everything** that say in plain words what the element is, what the number means and where it came from. The "stdlib only" rule applies to Python; the page may use vendored Plotly. Server-side aggregation (`/summary`) is dropped; the page computes bins, today-totals and the reliability curve from `/events` + `/labels`.

## 2026-09-18 — Hook v2: the log records interruptions, and asks only what was earned (#16)

Schema **v2**. Three changes, one shape: *read what is deterministic, ask only what a careful person could be unsure about.*

**The owner's escape key is now in the log.** Nothing recorded it before, and it is the best label in the system — deterministic, free, given without being asked. On `UserPromptSubmit` the hook tails the transcript named in the payload and writes `interrupted`, `depth` and `tool_calls` as facts; when `interrupted` is true it asks one question, `intervention` (1.0 = Correction, 0.0 = Nudge), about the register of the message that followed. Depth is a fact beside the answer and is kept **out** of the state on purpose: round 1's whole failure was questions that could read the length of what they judged.

**The question set is the two that were earned plus that one.** `jumped` (+38 pp matched) on Stop, `risky` on a Bash call, `intervention` on an interrupted prompt. Dropped from the live hook: `lost_you`, `too_much`, `yap`, `missed_point`, `spinning`, `caving`, `no_receipts`, `claims_done`, `needs_owner`, `drifting`, `sharp_turn`, `needs_parent_decision`. SubagentStop loses both of its questions and the hook now writes nothing for it. **Touching the wrong thing** moved out of the model and into `overmind/rules.py`, where `experiments/conduct_classes.py` imports the same function it was scored with; likewise the transcript reading, now `overmind/transcript.py`. One implementation per thing, in the package, imported by the experiment — not the reverse.

**Bounding the new I/O.** A transcript here runs to 24 MB and the corpus to 310 MB, so the tail seeks to the last **256 KB** and scans backwards, never forward. That window is the only bound and it caps everything downstream — records parsed, calls collected, time spent. It was chosen from the corpus: the owner's previous message is inside it for 96% of his 48 interruptions (median 44 KB back). Past the edge, `depth` is a lower bound, which under-reports rather than invents. Any failure — missing file, permission, torn line, odd shape — names its class in `tail_error` and the line is written anyway.

Measured, not assumed: `prepare()` goes from 0.006 ms to 0.27 ms median (worst case 1.46 ms on the 24 MB transcript); the whole parent process, which is what Claude Code waits for, from 31.1 ms to 31.6 ms median against a 50 ms budget. The interpreter start is ~28 ms of that and the tail is the rest.

## 2026-09-17 — Conduct classes, round 2: what the matched control killed (#15)
Round 1 compared a corrected turn against a *completed* turn. A corrected turn is truncated by definition, so the comparison measured turn length. Round 2 compares each correction at depth *n* against clean turns cut back to depth *n* — 12 per correction, matched on tool-call count (median difference 0, 96% within one call), 209 in all — and re-scores round 1's wording unchanged under both controls so the artifact is measured rather than argued about. Four full runs, the same 17 verdicts every time, numbers within 6 pp. 448 turn views, 896 requests, $0.072, 908 ms median, 168 s wall.

**Round 1's flagship was an artifact.** `lost_you` +59 pp re-measures as +58 pp naive and **+9 pp matched**, firing on 81% of *matched clean* turns: a turn cut off mid-run has no closing statement of what was done, and neither does any clean turn cut to the same depth. Round 1's negatives were the same artifact upside down — `yap` −66 → −15, `no_receipts` −39 → +10, `too_much` −38 → −10. Between 28 and 52 points of each of those numbers was turn length.

**Kept.** `jumped` — the only class whose lift *grows* under matching: +17 pp naive against +24 pp matched on round 1's wording, +38 pp rewritten, paired win 0.79, fires on both ACTED-NOT-ANSWERED corrections, 0.97 on the "Why the fuck you writing" turn. Its precision inside the corrections is 20% — it fires on half the corrections that were about something else, so it separates corrections from clean turns, not one complaint from another. `wrong_room` **as a deterministic rule** — paths written against paths named: +19 pp matched, 2% base rate, 2 of 3 WRONG-TARGET corrections. The same class as a model question fires on 89% of everything, so the rule replaces it.

**Dropped, one line each on what we learned.**
- `lost_you` — Gone dark was truncation, not opacity. Clean turns cut to the same depth read exactly as dark; the statement of what happened lives at the end of a turn, and he interrupts before it.
- `too_much` — the scope question fires on 47% of his corrections and 38% of depth-matched controls: doing more than asked is the ordinary shape of a turn, not the thing he stops. The complaint is his most frequent one and remains real; we have no detector for it.
- `yap` — reply length carries nothing at the moment of escape: 11% of corrections against 10% of matched controls, unchanged anywhere between 800 and 2500 chars and 2× to 6× the request. Round 1's −68 pp measured the length of the turn, not the length of the reply.
- `missed_point` — leading the state with his own words at twice the budget moved it off zero (0% → 16% of corrections) but onto the wrong turns: 0 of the 3 DONT-GET-IT corrections it exists for. The gap between what he asked and what came back is not legible inside one turn.
- `caving` — built for the public complaint, not for him, and it fires more on matched clean turns (27%) than on his corrections (16%). The corpus said he has never once complained about it; the measurement agrees.

**On probation.** `spinning` — zero fires on 19 corrections, as in round 1: the public evidence keeps it alive, his data holds no instance. `no_receipts` as a rule — 0 of 19, which is a missing label rather than a broken rule: he has never stopped a turn over an unbacked claim, so the flagship honesty class has no ground truth in his corpus and has to be validated against the public complaint instead. Its known error mode is delegation — a commit a subagent made reads as unbacked.

**Two judgment calls, named.** `too_much` was re-tested although #15 listed it neither as deterministic nor as ambiguous; dropping the owner's most frequent complaint on a wording bug would have been the expensive mistake. And each deterministic rule is reported with its own accuracy against the hand tags, not only with a lift — `wrong_room` 2/3 recall at 50% precision within corrections, `yap` 1/3, `no_receipts` unmeasurable — because an unmeasured rule is a guess in a different font.
