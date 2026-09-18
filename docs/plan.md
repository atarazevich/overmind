# Plan — Overmind v2

## Phase 1 — Observe
Hook on Stop, UserPromptSubmit, PreToolUse(Bash), SubagentStop. Per event: state → one Jev request → one JSONL line. Done when a day of normal work produces a log with no session ever slowed or broken, cost is measured, and a first look at the distributions exists as a report.

Questions, second set (all Noul), after #14 and #15 scored the first one — see `docs/signals.md` §"What survived measurement":
- Stop: jumped (he asked a question; the turn acted) — the only conduct class that survived the truncation-matched control, at +38 pp. Beside it, in code and free: wrong_room (paths the turn wrote against paths his message named, +19 pp as a rule).
- UserPromptSubmit: intervention (Nudge or Correction) — asked only when the transcript tail says the previous turn ended in an interruption. `interrupted`, `depth` and `tool_calls` are recorded as facts either way.
- PreToolUse Bash: risky (destructive or irreversible; complements cc-safety-net which blocks known patterns)
- SubagentStop: nothing. Both of its questions were dropped, so the hook returns without writing.

Twelve questions from the first set are gone, not deferred: `lost_you`, `too_much`, `yap`, `missed_point`, `spinning`, `caving`, `no_receipts`, `claims_done`, `needs_owner`, `drifting`, `sharp_turn`, `needs_parent_decision`. A line says what the transcript read could not give it: `tail_error` names a read that failed, `tail_exhausted` a window that ran out before the owner's previous message.

## Phase 2 — See and label
Dashboard: now (live sessions, latest signals), timeline (signals per session over time), history (distributions; calibration curve once labels exist). One-key label on every fired signal. Done when the owner has labeled 200 signals and the reliability curve per question is on the page.

## Phase 3 — Inject
Owner-opened. Candidates in order, now that measurement has cut the list: warn on `risky` before the command runs (the safety candidate, 9% of Bash calls); say it out loud when `jumped` fires (*"you asked a question and it started working"*, the one conduct class that survived). Each behind its own switch, each with a named threshold justified by the phase-2 curve — and that curve now draws itself from the Corrections the hook records for free.
