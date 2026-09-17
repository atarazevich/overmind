# Plan — Overmind v2

## Phase 1 — Observe
Hook on Stop, UserPromptSubmit, PreToolUse(Bash), SubagentStop. Per event: state → one Jev request → one JSONL line. Done when a day of normal work produces a log with no session ever slowed or broken, cost is measured, and a first look at the distributions exists as a report.

Questions, first set (all Noul):
- Stop: needs_owner (asks for a decision or answer before continuing) · claims_done · drifting (work not asked for) · stuck (repeating a failing attempt)
- UserPromptSubmit: sharp_turn (new direction vs. the current thread)
- PreToolUse Bash: risky (destructive or irreversible; complements cc-safety-net which blocks known patterns)
- SubagentStop: claims_more_than_shown (summary asserts work the transcript's tool calls don't show)

## Phase 2 — See and label
Dashboard: now (live sessions, latest signals), timeline (signals per session over time), history (distributions; calibration curve once labels exist). One-key label on every fired signal. Done when the owner has labeled 200 signals and the reliability curve per question is on the page.

## Phase 3 — Inject
Owner-opened. Candidates in order: speak only replies with needs_owner above threshold (replaces every-Stop `lore say`); warn on risky before the command runs; surface drift. Each behind its own switch, each with a named threshold justified by the phase-2 curve.
