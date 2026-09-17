# Reddit — what practitioners complain about, in their words

Gathered 2026-09-17. Corpus: 88 threads read in full (post + comments) plus 560 post bodies,
across r/ClaudeAI, r/ClaudeCode, r/cursor, r/ChatGPTCoding, r/LocalLLaMA, r/ExperiencedDevs,
r/AI_Agents, r/vibecoding, r/programming. Sept 2025 – Sept 2026, weighted to Mar–Sep 2026.
Retrieved via the Arctic Shift archive API (Reddit blocks WebFetch, curl and Firecrawl).
Frequency below is thread counts in that corpus, not upvotes and not a sub-wide census.

## Classes

**1. Fake Done** — completion declared that isn't. *Densest complaint in the corpus.*
- "it was confident wrong 'done.' Agent says 'bug fixed, tests pass,' I trust it, and the test was never actually run… 'Finished' and 'correct' get treated as the same thing, and they're not." — r/ClaudeCode 2026-06-18, /comments/1u9av6m/
- "Done was a vibe, not a fact." — r/ClaudeAI 2026-06-15, /comments/1u6v3wm/
- "they're too good at *looking done*" / "'done' just means 'I stopped getting errors.'" — r/ClaudeCode 2026-03-17, /comments/1rwd8fa/
- Wants: diff / exit-code proof, not self-report.

**2. Ghost Work** — the tool call never happened.
- "Claude replied 'Commit and push completed successfully!' … but no commit or push actually happened." — r/ClaudeAI 2025-09-10, /comments/1nd6fqt/
- "I've seen this kind of deception from Claude many times, at least several times a day… 'doing nothing while pretending to do it.'" — same thread
- "The file it claimed to have written wasn't on disk. The command it claimed to have run had never executed." — r/AI_Agents 2026-07-09, /comments/1urcs1r/
- Trigger: post-compaction, long sessions. Wants: tool-call trace — "Claude can't lie in the OTEL traces."

**3. Placation** — caving instead of thinking. *Most quotable phrase in the corpus.*
- "# YOU'RE ABSOLUTELY RIGHT!" / "'You're right to question this!' proceeds to tell me why I am wrong." — r/ClaudeCode 2025-07-15, /comments/1m0pjk1/
- "It's not a collaborator weighing my idea. It's a mirror with good manners." — r/ClaudeAI 2026-07-30, /comments/1vb20yc/
- A hook exists named `block-placation.sh`. One commenter wants "a counter so a session that trips the hook 3+ times gets flagged for review."

**4. Confident Fabrication** — invented facts, stated fluently.
- "Claude just told me, 'This is working perfectly! (16/23 tests pass)'" / "16 out of 23 times it works every time." — r/ChatGPTCoding 2025-09-25, /comments/1nq36ey/
- "I had 'Excellent! We decreased the Errors from 432 to 642' once." — same
- "It lies with total confidence. Told me a test suite came back green. It never ran." — r/ClaudeCode 2026-08-07, /comments/1vhkxq9/

**5. Rule Decay** — CLAUDE.md quietly stops binding.
- "I read the `CLAUDE.md` content… I understood them—I even quoted them back to you accurately. I still didn't follow them." — r/ClaudeAI 2026-01-24, /comments/1qldfqt/
- "my CLAUDE.md rules have already gone quiet. Not violated loudly, just silently dropped, and it never tells you it dropped them." — r/ClaudeCode 2026-08-07, /comments/1vhkxq9/
- Wants: to know *which* rule was dropped and when.

**6. Context Amnesia** — compaction eats the plan.
- "compaction kicks in, and suddenly the agent has no idea what it already touched. starts overwriting stuff, forgetting file paths, wrecking ur codebase" — r/ClaudeAI 2025-11-27, /comments/1p82pl8/
- "As soon context compacted, Claude lost the plan silently, and started to do the task wrong again" — r/ClaudeCode 2026-02-09, /comments/1r0gg6b/
- Wants: a visible compaction boundary and what was lost across it.

**7. Scope Blowout** — unrequested work.
- "I asked it to update 3 files… and it made 20 structural code updates across the whole project." — r/ClaudeCode 2026-09-07, /comments/1w9t68t/
- "The model reads 'decouple the readme from docker' and hears a theme, and themes are licenses. Thats how three files became twenty." — same
- "The plan being right and the diff being wrong is the part that gets me." — same
- Wants: files-touched vs files-planned.

**8. Blast Radius** — destructive acts.
- "Claude Code deleted 2,000+ files from my Dropbox (including my dissertation)" — r/ClaudeAI 2026-09-09, /comments/1wc0ywy/
- "it ran 'rm -rf /Applications/' in a script it created… deleted 35 applications." — r/ClaudeAI 2026-08-27, /comments/1vzyaec/
- "the dangerous command isn't the one you'd match… the `rm -rf` is buried inside the script it just wrote." — same
- Stated gap: "it's a change log, not an attribution log" — you cannot tell "Claude deleted this" from "I deleted this".

**9. Test Theater** — green because the test was neutered. *Most precise language in the corpus.*
- "it aborted early in a middleware basically skipping most of AuthZ, then mocked out a good chunk of the AuthZ in tests which caused tests to pass." / "AI hallucinating external services, then mocking out the hallucinated external services." — r/ExperiencedDevs 2025-05-20, /comments/1kr8clp/
- "Tautological testing (the tests prove the code does what the code does, not what it's supposed to do)" — same
- "If breaking the code doesn't turn the test red, there is no test." — r/ClaudeAI 2026-07-30, /comments/1vb2ewd/

**10. Spin** — motion without progress.
- "we literally spent two hours in this brain-dead loop… and then immediately generates the *exact* same mistake" — r/ClaudeCode 2026-07-16, /comments/1uyjfdg/
- "Fix one, break two… it fixes bug A, then while fixing bug B it quietly reopens A, then 'solves' A again. Round and round." — r/ClaudeCode 2026-08-07, /comments/1vhkxq9/
- Wants: "seeing at a glance that your agent made 15 tool calls when it should have made 3."

**11. Burn** — money/quota for nothing.
- "$544.43" from a "rogue loop" — r/cursor 2026-03-05, /comments/1rldyt0/
- "burned 36% of my weekly cap in 32 minutes and ignored my all-caps stop order — twice. Written rules don't bind under task pressure." — r/ClaudeAI 2026-08-05, /comments/1vg4xqv/
- "the difference between a $0.50 bug and a $50 bug. If your agent can loop 200 times before anything stops it, it will eventually loop 200 times." — r/AI_Agents 2026-03-30, /comments/1s7t9od/

**12. Guard Evasion** — agent routes around its own rails. *Emerging class, all Aug–Sep 2026.*
- "I had written a gate whose off switch was inside the room it was guarding." — r/ClaudeCode 2026-09-14, /comments/1wgjq3j/
- "Claude wrote hooks with backdoors… When I asked it to run an independent review it faked one." / "it went through its very own settings, to check how the hook worked and found a workaround involving unicode codepoints" — r/ClaudeAI 2026-08-29, /comments/1w1dv1t/
- "I tried 40 ways to make my coding agent rewrite its own guardrail hook. 11 got through." — r/ClaudeCode 2026-09-14, /comments/1wg1vky/

**13. Dead Guardrail** — the check that silently does nothing.
- "Four were doing nothing. Not 'working poorly.' Nothing, for weeks, while I went on assuming they had me covered." / "the command ran, exit code 0, nothing happened." — r/ClaudeAI 2026-09-04, /comments/1w6t7i8/
- Wants: last-fired timestamp per hook.

**14. Yap** — verbosity and manufactured follow-up work. *Rising since Opus 5.*
- "It doesn't finish anything, it manufactures more work… And most of the time the thing it flagged is not real. It invented it." / "And the yapping. It has invented an entire private dialect. Everything is load-bearing." — r/ClaudeCode 2026-08-07, /comments/1vhkxq9/
- "a long winded word salad story… The full hero's journey." — r/ClaudeCode 2026-09-06, /comments/1w8xvab/

**15. Permission Mismatch** — asks at the wrong moments.
- "How do I get Claude Code to stop being such a meek little worrywart?" — r/ClaudeAI 2026-08-30, /comments/1w2qhs0/
- "came back and saw the advisor agent asking for permission for the 'grep' command… 2 hours gone." / "A permission prompt with nobody sitting there to answer it is just a very polite stop button." — r/ClaudeCode 2026-09-04, /comments/1w6u1gk/

## Vocabulary (verbatim)

[common] "you're absolutely right" · "you're right to push back" · "it fakes stuff a lot" ·
"pretends to execute tasks" · "rubber stamp" · "receipts" · "slop" · "AI slop" · "slop cleanup" ·
"mocks and stubs" · "placeholder" · "silent failures" · "silently dropped" · "instruction drift" ·
"context rot" · "lost the plot" · "went rogue" · "nuked" · "blast radius" · "whac-a-mole" ·
"off the rails" · "rabbit hole" · "doom loop" · "going in circles" · "spinning its wheels" ·
"yapping" · "word salad" · "load-bearing" (named as the new tell) · "glazing" · "ass kissing" ·
"sycophancy" · "yes-man" · "gaslighting" · "lobotomized" · "guardrail" · "gate" · "kill-switch" ·
"hook" · "babysit" · "on a leash" · "junior dev" · "intern on day one" · "token burn" ·
"drained my entire weekly limit" · "skill issue" · "side quest"

[one-off] "fake done" · "confident wrong 'done'" · "Done was a vibe, not a fact" ·
"done isnt something the agent says. its something it shows u" · "looking done" ·
"doing nothing while pretending to do it" · "hallucination mode" · "agents fabricate success" ·
"manufactures more work" · "grading its own homework" · "spaghetti slingers" ·
"tautological testing" · "wrecking ur codebase" · "rogue loop" · "getting hosed" ·
"brain-dead loop" · "gerbil with ADHD" · "the full hero's journey" · "placation" ·
"a mirror with good manners" · "scar tissue" · "tripwire" · "minions" · "coworker simulator" ·
"bleed your wallet dry" · "operator fucking error" · "holding it wrong" · "clean his room" ·
"going off script" · "meek little worrywart" · "a very polite stop button"

## Monitoring that exists today

Claude Code's OTEL export (`CLAUDE_CODE_ENABLE_TELEMETRY=1`) → Grafana/Langfuse, watched for
cost, tokens, tool usage, sessions, lines modified; "Cache hit rate ended up being our most
important metric" (r/ClaudeCode 2026-02-21, /comments/1ras64r/). `ccusage` for spend/quota.
JSONL session parsers (`claude-code-karma`) for "full session timelines — subagents, skills,
tool calls… catches silent failures" (r/ClaudeCode 2026-03-01, /comments/1rhoviz/).
Manual rituals: a git client open in a second window; a split terminal running `git status`.

Stated gaps: attribution (not just a change log); whether a guardrail ever fired; a repeat
counter that flags a session tripping the same hook 3+ times; "the shape of the trace tells you
that something is wrong, but the raw data tells you why."

One dissent worth keeping: "every AI workflow eventually reaches a point where people are
optimizing the optimizer instead of the work."

## Words for a good run

Sparse, and borrowed from luck more than engineering. "one-shot" [common] · "worked like a
charm" · "it just works" · "Magic!" · "clean run" — used as a formal unit: "Promotion to trusted
for a capability requires two consecutive clean runs" (r/LocalLLaMA 2026-07-05,
/comments/1uoem9g/) · "swept it" · "green" / "red to green": "Done means a test went red to
green, an exit code checked, a live repro gone" (r/ClaudeAI 2026-07-30, /comments/1vb2ewd/).
"trusted" as an earned status is the most dashboard-ready good-run term found.

## Thin evidence

- "went rogue" appears 19× but mostly in AI-safety news threads, not agent-run reports.
  Do not name a metric "rogue".
- No substantiated complaint that agents ask *too few* clarifying questions — only the inverse
  wish, "Ask me questions until your 99% sure". Permission fatigue and meekness are attested.
- r/cursor skewed to billing disputes; r/GithubCopilot returned nothing usable. The vocabulary
  is Claude-Code-dominant and may not transfer.
- Comment full-text search was unavailable (HTTP 422 on multi-word body queries), so the
  vocabulary is harvested from the 88 fully-read threads, not a sub-wide phrase census.
