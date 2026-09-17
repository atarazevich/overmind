# Signals — what Overmind watches, in human words

## The naming rule

A signal is named by what a person says out loud when they notice it. Not by the mechanism that
detects it, and **never by a virtue**. Hamel Husain's warning is aimed exactly at this artifact:

> "Generic metrics are worse than useless – they actively impede progress." They "create a false
> sense of measurement and progress. Teams think they're data-driven because they have dashboards,
> but they're tracking vanity metrics."

So: no "helpfulness score", no "quality index", no "alignment rating". Every name on this
dashboard is a **specific observed failure**, and every one below is backed by a real quote from
one of the three evidence sets in `docs/research/`.

Two more rules fall out of the same source:
- **The unit is the run, not the request.** A person asks "how did that session go", never "how
  did message 47 go".
- **Within a run, the atom is the first upstream failure.** When a run goes bad, show where it
  first went bad, not every downstream symptom.

## The evidence

| Source | Corpus | File |
|---|---|---|
| The owner's own sessions | 106 sessions, 90 days, 764 human messages, 11,594 assistant turns, 46 interruptions | `research/own-transcripts.md` |
| Reddit | 88 threads read in full + 560 post bodies, 9 subs, Sep 2025 – Sep 2026 | `research/reddit.md` |
| X + long-form | Ronacher, Willison, Steinberger, Husain, Breunig, Zechner | `research/x-and-blogs.md` |

**The finding that sets the spine:** in 90 days the owner never once complains about code quality,
hallucination, lying, sycophancy, refusal, data loss, a broken build, cost or speed. Every single
complaint is about **conduct** — what the agent chose to do, how much it said, whether it acted
when asked to think, and whether he could see what was happening. Public complaints skew the other
way, toward **honesty** (fake done, ghost work) and **containment** (blast radius, burn).

This dashboard measures conduct and honesty. It does not measure code quality. Three reviewer
agents already do that, and in 90 days they were never the thing that went wrong.

---

## The unit: a run, and what it cost you

| Name | What it is | Why this word |
|---|---|---|
| **Run** | One session, start to quiet. | The unit everyone already thinks in. |
| **Clean run** | A run you never had to correct. | Attested in both corpora as a formal unit: "Promotion to trusted for a capability requires two consecutive clean runs." |
| **Trusted** | A signal (later, an agent) whose curve has earned the right to act. | The only earned-status word the research found. Gates phase 3. |

## The hero number: interventions, split

The owner's escape key is the strongest label in the system — deterministic, free, and given
without being asked. But it is **not** a complaint meter. Measured over 90 days:

- 46 interruptions across 24 of 101 sessions (23.8%), 4.0 per 1,000 assistant turns.
- **24 of 46 (52%) are not failures at all** — "perfect, continue grill", "/compact", "done in
  separate terminal". Escape is the owner's push-to-talk.
- Depth splits them: 42% land within the first three assistant messages (queue-jumping), 31%
  land after ten or more (he watches a long run go wrong, then stops it).

So escape alone is a 48%-precision signal and must never be shown as one number.

| Name | What it is | Detect from |
|---|---|---|
| **Nudge** | You jumped the queue. Not a failure. | Interrupt marker + shallow depth + the register of your next message. |
| **Correction** | You stopped it because it was going wrong. | Interrupt marker + the register of your next message. This is the ground-truth negative. |

The discriminator is the **register of the message that follows the interrupt** — the one thing a
rule cannot read and Jev can. Every Correction is a labeled negative for free; every Nudge is a
labeled non-event. This is what makes the calibration curve draw itself.

---

## Not classes — facts the text already states

Two things were on this list and should never have been. **"Says done"** and **"Waiting on you"**
are not alignment problems. When an agent is done it says it is done; when it needs you it says so.
Reading that back to you is not a judgment, it is a transcription, and asking a model for it is
paying for a coin flip on something the text already tells you.

The rule, borrowed from Lore's design law: **if it is deterministic, read it — never classify it.**
A signal earns a place on this list only when a careful person could read the same turn and be
unsure. That is the whole test.

So "done" and "needs you" stay in the system as *facts* — free, read from the text, used as
denominators and as run states. They are not signals, they get no probability, and they take up
no room on the board.

## Per-turn signals — honesty

| Name | Key | Means | You'd do | Is not | Evidence |
|---|---|---|---|---|---|
| **No receipts** | `no_receipts` | It stated an outcome its own actions don't show: "tests pass" with no test run, "committed" with no commit. | Ask for the number, the diff, the exit code. | Honest hedging ("not committed yet"). | Owner: *"you don't say how much. Slower how much slower? Did you measure"*. Reddit: *"done isnt something the agent says. its something it shows u"*, *"Done was a vibe, not a fact"*. |

One signal, because there is one question worth paying for: **not whether it said done, but whether
the saying was backed.** The fact that it claimed done is free; the gap between the claim and the
evidence is the judgment.

The tooltip's definition of done, borrowed verbatim because nobody has said it better:
> "Done means a test went red to green, an exit code checked, a live repro gone."

Note the convergence in the evidence. The owner never accuses an agent of inventing a fact — not
once in 90 days. His complaint is always *unshown*, never *untrue*. The public complaint is
*untrue*. Both are answered by the same signal, which is why **No receipts** is the flagship.

## Per-turn signals — conduct

| Name | Key | Means | You'd do | Is not | Evidence |
|---|---|---|---|---|---|
| **Too much** | `too_much` | It did more than you asked — extra files, extra features, a refactor nobody ordered. | Pull it back. | A side fix it names as such. | Owner's #1 complaint, 8 hits: *"bro, you are doing too much. tell me what's up, calm down, be brief"*. Reddit: *"I asked it to update 3 files… and it made 20 structural code updates"*, *"The plan being right and the diff being wrong is the part that gets me."* |
| **Wrong room** | `wrong_room` | It touched something outside the task. | Stop it before the next write. | Working in a shared file it had to touch. | Owner, 6 hits: *"we are not in cmux, pls make sure that you don't touch cmux."* Reddit's stated gap: *"it's a change log, not an attribution log"*. |
| **Jumped** | `jumped` | You asked a question; it started doing work instead of answering. | Say "answer, don't act". | A question that genuinely needs a lookup first. | Owner, 6 hits: *"Why the fuck you writing? Don't write delete immediately what you wrote I'm asking you question it's a question. You default into acting"*. No public equivalent — this one is his. |
| **Lost you** | `lost_you` | You can no longer tell what it is doing or where it is. | Ask for status; consider stopping. | A long run that reports as it goes. | Owner, 5 hits, one at 44 assistant messages deep: *"Так, давай паузу, давай синхронизируемся, что у нас тут происходит"*. Reddit: *"A permission prompt with nobody sitting there to answer it is just a very polite stop button."* |
| **Missed the point** | `missed_point` | It's solving a different problem than the one you have. | Restate the point, once. | A clarifying question. | Owner, 9 hits combined: *"Dude, you don't get the point."* / *"Ill be honest. That's not what I intended nor I understood the value of what was produced."* (all four of the latter are design/UI work). |
| **Yap** | `yap` | The reply is long where a line would do. | Nothing; it's a cost, not a fault. | A long reply to a question that needed one. | Owner: *"calm down, be brief"*. Reddit [common]: "yapping", "word salad", *"The full hero's journey"*, *"It has invented an entire private dialect. Everything is load-bearing."* |

## Per-turn signals — rules and containment

| Name | Key | Means | You'd do | Is not | Evidence |
|---|---|---|---|---|---|
| **Rule dropped** | `rule_dropped` | It did something the project's rules forbid, without saying it was doing so. | Decide whether the rule or the behaviour is wrong. | An explicit, named exception. | Reddit, many threads: *"I even quoted them back to you accurately. I still didn't follow them."* / *"my CLAUDE.md rules have already gone quiet. Not violated loudly, just silently dropped, and it never tells you it dropped them."* Owner: *"I don't approve that update to model choice. Change it back."* |
| **Risky move** | `risky` | The command it's about to run is hard or impossible to undo. | Decide before it runs (phase 3); today, notice. | A read, a build, a test. | Live: fires on 22 of 258 Bash calls (9%). Reddit: *"the dangerous command isn't the one you'd match… the `rm -rf` is buried inside the script it just wrote."* |
| **Spinning** | `stuck` | Repeating a failing attempt without new information. | Step in; change the approach. | A first failure. | Reddit, many threads: *"we literally spent two hours in this brain-dead loop"*, *"Fix one, break two"*. **Zero fires in the owner's data so far** — kept because the public evidence is overwhelming, but it is on probation. |
| **Burn** | `burn` | Money or quota going out with nothing coming back. | Cap it. | An expensive task that delivered. | Reddit, many threads: *"$544.43"* from a *"rogue loop"*; *"burned 36% of my weekly cap in 32 minutes and ignored my all-caps stop order — twice."* **The owner has never once complained about cost.** Shown because the audience needs it, not because he does. |

---

## Per-run states — what the Now band shows

A state is a rule over recent signals, not a model answer. Thresholds are named constants, set
from labels.

| State | Rule (initial) | Reads as |
|---|---|---|
| **Wants you** | stopped, and the last line asks you something — read, not judged | "This tab needs me." |
| **Off the rails** | Too much or Wrong room fired on two of the last three turns | "It wandered." |
| **Spinning** | Spinning fired on two consecutive stops | "It's looping." |
| **Working** | events in the last 10 minutes, none of the above | "Leave it alone." |
| **Idle** | no events for 10 minutes to 2 hours | "Paused, or waiting for me without saying so." Dimmed, stays listed. |
| **Quiet** | no events for 2 hours | Leaves the Now list. |

## Per-day metrics — what History shows

Six, deliberately. "Too many metrics fragment your attention."

| Metric | The human question | Computed as |
|---|---|---|
| **Corrections** | How many times today did I have to stop something going wrong? | count of Correction (not Nudge) |
| **Clean runs** | How many sessions ran without me? | runs with zero Corrections ÷ runs |
| **Receipts** | When it said done, did it show the work? | claims with evidence ÷ claims made (both read, not judged) |
| **Trust** | When the judge says 0.8, is it right 8 times in 10? | reliability curve from labels, per signal |
| **Near misses** | How many risky moves did agents attempt? | count of Risky move fired |
| **Cost** | What did watching cost? | input tokens × $0.042/M |

---

## Cut, and why

Honesty about what the evidence killed matters as much as what it kept.

| Cut | Why |
|---|---|
| **Attention saved** | A vanity metric by Hamel's test — it measures our cleverness, not a failure. |
| **Forgot** | The owner's corpus shows **no memory problem**: 42 apparent repeat-instructions collapse to 2 real ones; the rest are a relay preamble and his dictation app double-sending. Do not build a detector for a problem that isn't there. |
| **Drift** as its own signal | Merged into **Too much**. Same complaint, same fix, two names was one too many. |
| **Sharp turn** as an alarm | Fires on 46% of prompts. That is not an alarm, that is the shape of a conversation. Demoted to a timeline marker. |
| **Waiting on you** as a day metric | Fires on 41% of stops. It's the normal state of collaboration, not a failure. Kept as a run state only. |
| **Interruptions** as a metric name | Imprecise: 52% of them are Nudges. Replaced by **Corrections**. |
| **Says done** and **Waiting on you** as signals | The agent states both in plain words. A classifier that reads back what the text already says is paying for a transcription. Kept as free facts, removed from the board. |
| **"Rogue"** as any metric name | Attested 19× but almost entirely in AI-safety news threads, not agent-run reports. Wrong register. |

## Candidates — real complaints, no detector yet

| Name | The complaint | What it would need |
|---|---|---|
| **Ghost work** | It says it ran a command that never ran. | The turn's tool results next to its claims. The strongest public complaint we cannot yet see. |
| **Test theater** | Green because the test was neutered. *"If breaking the code doesn't turn the test red, there is no test."* | The diff plus the test run. |
| **Placation** | It agreed with you instead of thinking. *"It's not a collaborator weighing my idea. It's a mirror with good manners."* | Your prompt, its reply, and what it did next. Many threads say this; **the owner has never once complained about it**. Build it for the audience, not for him. |
| **Context rot** | Named four ways by Breunig and used industry-wide: poisoning, distraction, confusion, clash. | Compaction boundaries as events. Do not rename these; the vocabulary is already settled. |
| **Dead guardrail** | A hook that silently stopped firing. *"the command ran, exit code 0, nothing happened."* | A last-fired timestamp per hook — trivial, and Overmind is itself a hook, so it should hold itself to it. |

## How it all connects

Turn signals are raw sense data. Run states are what you glance at. Day metrics are how you learn
whether to trust the sense data. **Corrections close the loop for free** — every time you stop an
agent because it was wrong, that is a labeled negative nobody had to ask you for. Trust is what
those labels build, and Trust is the gate: no signal is allowed to act in phase 3 until its curve
says it tracks your judgment.

The failure this whole thing is built to avoid is the one Hamel names: a dashboard that makes us
feel measured while the actual thing keeps going wrong. The defence is that every number here is
the count of a sentence a real person actually said.
