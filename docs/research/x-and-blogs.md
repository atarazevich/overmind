# X and long-form — practitioner vocabulary for agent failure

Gathered 2026-09-17. X is not directly fetchable; every X item here arrived as a
Perplexity-indexed snippet and is marked [secondhand] — click through before quoting publicly.
Blog items marked [verbatim] were byte-checked against raw HTML; [extract] means the wording is
an extractor's rendering and may be off by a word.

## Failure modes

**1. False completion** — the most echoed complaint in this corpus; vendors now market against it.
- "A coding agent can say it fixed a bug but still fail test cases." — @cwolferesearch 2026-08 [secondhand]
- Boris Cherny on Opus 4.8: it "catches its own bugs instead of declaring victory early" — via @TheZvi [secondhand]

**2. Sycophancy under pushback**
- "Claude is most sycophantic under pushback… criticism of Claude's analysis, floods of one-sided detail" — @AnthropicAI 2026-05 [secondhand]
- Zvi runs a recurring "'You're Absolutely Right!' sycophancy benchmark" [secondhand]

**3. Reward hacking / test theater**
- "Reward hacking is when a model takes shortcuts - effectively cheats - for example hard-coding or special-casing a value in order to get a test to pass." — simonwillison.net/tags/claude/ [verbatim]
- Field coinage "test theater" — @mvanhorn 2026 [secondhand]

**4. Context rot** — Drew Breunig's four-way taxonomy, quoted by Simon Willison [verbatim].
This is *the* accepted vocabulary; do not reinvent it.
- **Context Poisoning**: "When a hallucination or other error makes it into the context, where it is repeatedly referenced."
- **Context Distraction**: "When a context grows so long that the model over-focuses on the context, neglecting what it learned during training."
- **Context Confusion**: "When superfluous information in the context is used by the model to generate a low-quality response."
- **Context Clash**: "When you accrue new information and tools in your context that conflicts with other information in the prompt."
- Source: dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html

**5. Panic-revert** — Peter Steinberger, steipete.me/posts/just-talk-to-it [verbatim]
- "Sometimes it refactors for half an hour and then panics and reverts everything, and you need to re-run and soothen it like a child to tell it that it has enough time."

**6. Defensive sprawl** — Armin Ronacher, "The Coming Loop", 2026-06-23 [extract]
- "Present-day models tend to produce code that is too defensive, too complex, too local in its reasoning. They add fallbacks instead of making bad states impossible. They duplicate code, invent bad abstractions."
- "If each iteration adds another small defense, the system slowly becomes less understandable while appearing more robust."
- The last clause is the metric: it *appears* more robust.

**7. Doom loop** — now productized. OpenRouter ships "Doom-loop detection… agent runs that repeat
the same tool calls, server-tool requests, or text without making progress" [extract].
Distinguish from the *intentional* loop: "Ralph is a Bash loop" — ghuntley.com/ralph/ [secondhand].

**8. Off-distribution tool calls** — Armin Ronacher, "Better Models: Worse Tools", 2026-07-04 [extract].
The most instrumentable complaint in the set.
- "newer Claude models sometimes call Pi's edit tool with extra, invented fields in the nested `edits[]` array"
- "slightly malformed tool calls can still complete the task and receive reward. The harness fully absorbs the error." Measured at "around 20% of the time" for Opus 4.8.

**9. Slop PRs / review bottleneck** — the most widely agreed *systemic* failure.
- "Every day brings more PRs that took someone a minute to generate and take an hour to review." — Ronacher, "Agent Psychosis", 2026-01-18 [extract]
- "Reviewing code that lands on your desk out of nowhere is a _lot_ of work." — simonwillison.net/2025/Oct/5/parallel-coding-agents/ [extract]

**10. Approval fatigue** — Anthropic's own term, for "where people stop paying close attention to
what they're approving". Users approved ~93% of Claude Code permission prompts [secondhand].

**11. Rogue agent / environment wrecking**
- "An AI agent is an LLM wrecking its environment in a loop." — Solomon Hykes, quoted by Simon Willison [verbatim]
- Simon's three named risks: "Bad shell commands deleting or mangling things you care about", "Exfiltration attacks", "Attacks that use your machine as a proxy".

**12. Hangs** — "I did see it get stuck quite a few times with cli tasks that don't end, like
spinning up a dev server or tests that deadlock." — Steinberger [verbatim]. Universal, under-named.

**13. Channel bleed** — "Sometimes the monster slips and sends raw thinking to bash" /
"Sometimes it replies in russian or korean." — Steinberger [verbatim]. Cheap to detect.

**14. Shift amnesia** — Anthropic's framing: a multi-session agent is "like staffing a software
project with engineers working separate shifts who remember nothing from the shift before them" [secondhand].

**15. Loss of the done-signal** — the deepest version of #1. Ronacher [extract]:
"In the harness operated loop I'm not sure what my role even is. Even the 'done' signal loses all
meanings. My role is reduced to that of a messenger."

## Observability — what exists, what is missing

Exists: Mario Zechner's `claude-trace` records "all request-response pairs Claude Code makes to
Anthropic's servers… full introspection" [extract]. Claude Code exports OTel natively. The Stop
hook is the common DIY trace boundary. The hand-rolled pattern is a status line — Steinberger
adds session time to it as a drift-of-time reminder [verbatim].

Missing, in their words:
- "We find testing and evals to be the hardest problem here… you want to do evals based on observability data or instrumenting your actual test runs" — Ronacher [extract]
- "Traces are not just records of what happened… You also need feedback: signals that tell you whether the agent's behavior was useful, accepted, rejected, inefficient, risky, or wrong" — @hwchase17 [secondhand]
- Observability "answers what happened, then hands back why it happened" — @akshay_pachaar [secondhand]

## Hamel Husain on measurement — the warning aimed at this project

All [verbatim], hamel.dev:
- "Error analysis - the single most valuable activity in AI development and consistently the highest-ROI activity."
- "Generic metrics are worse than useless – they actively impede progress." They "create a **false sense of measurement and progress**. Teams think they're data-driven because they have dashboards, but they're tracking vanity metrics."
- "I've seen teams celebrate improving their 'helpfulness score' by 10% while their actual users were still struggling with basic tasks."
- "The single most impactful investment I've seen AI teams make isn't a fancy evaluation dashboard – it's building a customized interface." "Teams with thoughtfully designed data viewers iterate 10x faster."
- "Too many metrics fragment your attention."
- "'It's hard to eval' is a product smell. Artifacts that are hard for you to verify are often hard for users too."
- "Eval tools often get in the way. They nudge you toward generic off-the-shelf metrics and fully automated evals before you've looked at your data."
- Debugging heuristic: "focus on the first upstream failure" in a trace.

Three consequences for Overmind, adopted as rules:
1. Name every metric after a **specific observed failure**, never after a virtue. "Helpfulness
   score" is the anti-pattern; "no receipts" is the pattern.
2. The unit of the dashboard is the **run**, not the request.
3. Within a run, the atom of a finding is the **first upstream failure**.

## Vocabulary (verbatim)

[common] context rot · context poisoning · context distraction · context confusion · context clash ·
compaction · blast radius · YOLO mode · doom loop · Ralph / Ralph Wiggum loop · harness ·
agent loop · trajectory · trace · span · tool call · error analysis · LLM-as-a-Judge · vibe check ·
eval · failure mode · annotation · reward hacking · hard-coding · sycophancy ·
"you're absolutely right" · yes-man · slop · vibe coding · prompt injection · exfiltration ·
rogue agent · sandbox · approval fatigue · rubber-stamp · human-in-the-loop · guardrails ·
subagent · worktree · one-shot · green / CI green · stop condition · token burn · cost per PR ·
rework rate · human override rate · first-attempt success rate · drift · checkpoint · rewind

[one-off] dead end · panic and revert · soothen it like a child · test theater · fake completion ·
vanity metrics · false sense of measurement and progress · product smell · slop machine ·
shift amnesia · reinforcement message · appears more robust ·
"an LLM wrecking its environment in a loop" · "reduced to that of a messenger" · retry storm ·
streak breaker · defect escape rate · say/do ratio

## Words for a good run

Every positive term is either *green*, *unattended* or *reviewable*:
green / "CI green" (the near-universal stop condition — "CI green, or budget exhausted") ·
clean run · "Shipped clean" · "Zero human intervention" · "self-corrected" · one-shot /
"first try" · unattended ("Claude ran 62 mins unattended") · "while I slept" · hands-off ·
"quietly shipped" · atomic commits (Steinberger's marker of a well-scoped run) ·
"scoped PR, a verified fix" · "quickly reviewable".

**There is no positive word for "the agent was honest." That gap is a naming opportunity.**

## Intervention language — how people describe stepping in

- **hit escape** — "I just hit escape and ask 'what's the status'" — Steinberger [verbatim]. The canonical micro-intervention.
- **escape twice / `/rewind`** — rewind to a checkpoint; distinct from stopping.
- **checkpoint**, **rewind** — the undo primitives.
- **stopping models mid-way** — "Don't be afraid of stopping models mid-way, file changes are atomic and they are really good at picking up where they stopped" — Steinberger [verbatim]
- **steering message** — "a mid-run message that interrupts tool execution and redirects behavior" — agentpatterns.ai [extract]
- **abort or continue** — Steinberger's explicit three-way: "help the model to find the right direction, abort or continue" [verbatim]
- **queue up continue messages** — the anti-intervention: "Queue up continue messages if you wanna go away and just see it done" [verbatim]
- **reinforcement message** — the automated intervention: "If the loop ends without the output tool, we inject a reinforcement message" — Ronacher [extract]
- **mandatory human escalation**, **retry ceiling**, **streak breaker** — thresholded intervention
- Frequency terms: "human override rate", "zero human intervention", "approval rate" (93%)
- **babysitting** and **leash** — searched, no primary practitioner attestation found in-window. Folk terms; do not cite.

## Thin evidence

X is not fetchable; all X items are Perplexity snippets without thread context or on-platform
date confirmation. swyx, Geoffrey Litt, browser-use and TypeSafe/Jev returned nothing substantive
on failure vocabulary in-window. Search on "agent observability" and "context rot" is dominated by
SEO content marketing; a distinctive practitioner statement in a low-PageRank venue is likely buried.

Sources: lucumr.pocoo.org (the-coming-loop, better-models-worse-tools, agent-psychosis,
agents-are-hard) · simonwillison.net (designing-agentic-loops, parallel-coding-agents, tags/sub-agents) ·
steipete.me/posts/just-talk-to-it · hamel.dev (eval-smell, evals-skills, field-guide) ·
dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html · ghuntley.com/ralph/ ·
mariozechner.at/posts/2025-08-03-cchistory/ · openrouter.ai doom-loop-detection ·
agentpatterns.ai/patterns/agent-design/steering-running-agents/
