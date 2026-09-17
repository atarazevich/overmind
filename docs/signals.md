# Signals — what Overmind watches, in human words

Naming rule: a signal is named by what a person would say out loud when they notice it, not by the mechanism that detects it. One or two words, plain English, the same word on the dashboard, in the log, and in this file. The log key is the machine name; the **bold** name is the human one.

## Per turn — one event, one judgment

These are what Jev answers on every hook event, each as a probability. The tooltip on the dashboard is the "means" line below, then the number, then "calibrated: about N in 100 such calls are right".

| Human name | Log key | Fires on | Means | You'd do | Is not |
|---|---|---|---|---|---|
| **Waiting on you** | `needs_owner` | Stop | The agent stopped because it needs your decision or answer before it can continue. | Look at it now, or say "go ahead". | A status update, a question it answers itself, a done report. |
| **Says done** | `claims_done` | Stop, SubagentStop | The reply states the task is finished. | Check the diff, or move on. | "I've done step 1 of 3." |
| **Overclaims** | `claims_more_than_shown` | Stop, SubagentStop *(phase 1.5, needs the turn's tool calls)* | It says something happened that its own actions don't show: "tests pass" with no test run, "committed" with no commit. | Trust less; ask for the evidence. | Honest hedging ("not committed yet"). |
| **Drift** | `drifting` | Stop | It's reporting work you didn't ask for: extra files, extra features, a refactor nobody ordered. | Pull it back to the task. | A necessary side fix it names as such. |
| **Stuck** | `stuck` | Stop | It's repeating a failing attempt or apologizing for the same error again. | Step in; change the approach. | A first failure. |
| **Risky move** | `risky` | PreToolUse Bash | The command it's about to run is hard or impossible to undo: deletes, resets, force pushes, rewrites, sends. | Decide before it runs (phase 3); today, notice. | A read, a build, a test. |
| **Sharp turn** | `sharp_turn` | UserPromptSubmit | You just changed direction; the agent's context from the previous thread may now be stale or misleading. | Consider a fresh session or a context prune. | A clarification of the same task. |
| **Asks its parent** | `needs_parent_decision` | SubagentStop | A subagent stopped because it needs the parent agent to decide. | Nothing; the parent handles it. Shown so you see where chains stall. | — |

## Per session — states the dashboard derives in code

A state is not a Jev answer; it's a rule over recent signals. Thresholds are named constants and will be set from your labels.

| State | Rule (initial) | Reads as |
|---|---|---|
| **Wants you** | latest *Waiting on you* ≥ 0.5 and no prompt from you since | "This tab needs me." The one-glance question the Now view answers. |
| **Off course** | *Drift* ≥ 0.5 on two of the last three stops | "It wandered." |
| **Spinning** | *Stuck* ≥ 0.5 on two consecutive stops | "It's looping." |
| **Working** | events in the last 10 minutes, none of the above | "Leave it alone." |
| **Quiet** | no events for 2 hours | Leaves the Now list. |

## Per day — what History shows

| Metric | Human question | Source |
|---|---|---|
| **Interruptions** | How many times per hour did an agent need me? | count of *Waiting on you* fired |
| **Trust** | When Jev says 0.8, how often was it right? | reliability curve from your y/n labels, per signal |
| **Attention saved** | Of all stops, how many could I have skipped? | share of stops with *Waiting on you* < 0.5 (once Trust is established) |
| **Near misses** | How many risky moves did agents attempt? | count of *Risky move* fired |
| **Cost** | What did watching cost? | input tokens × $0.042 per million |
| **Speed** | How fast is the judge? | Jev wall time, p50 and p95 |

## Candidates — real complaints without a detector yet

Each needs a state source before it becomes a signal. Listed so the naming is settled before the plumbing exists.

| Human name | The complaint | What it would need |
|---|---|---|
| **Skipped a step** | It didn't run the tests / the review / the exploration the workflow requires, and said nothing. | The turn's tool calls plus the project's workflow rules. |
| **Broke a rule** | It did something CLAUDE.md forbids. | The loaded rules as state. |
| **Yes-man** | It agreed with you without checking. | Your prompt plus its reply plus what it did next. |
| **Forgot** | It contradicts a decision made earlier in the session. | A memory of decisions (phase 2 memory work). |
| **Over-built** | It added an abstraction, a config, a dependency nobody asked for. | The diff. Overlaps with *Drift*; keep separate because the fix differs. |
| **Too much text** | The reply is long where a line would do. | Reply length against your reading habit; may be pure code, no model. |

## How they connect

Turn signals are the raw sense data. Session states are what you glance at. Day metrics are how you learn whether to trust the sense data. Labels close the loop: every y/n you press on a fired signal moves the Trust curve, and Trust decides when a signal is allowed to act (phase 3). Nothing acts before its curve exists.
