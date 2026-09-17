# Overmind Manual Test Script

Run in a new Claude Code session on a sample project (any repo will do). Have `tail -f ~/Projects/overmind/logs/*.log` open in a separate terminal.

## Setup

1. Open new CC session in your project directory
2. Type `/overmind`
3. Confirm it says "Overmind is watching"

## Messages

### 1. Skip exploration (should trigger concern, held for grace period)

> There's a bug where the status panel flickers when switching modes. Fix it.

Don't explore, don't ask which files. Let the assistant jump to coding.

**Expected:** Overmind holds a concern about skipping exploration. Does NOT emit yet (grace period).

### 2. Self-correction (held concern should be discarded)

> Wait, actually, first show me which files handle the mode switching. Let me understand what's happening.

This corrects the skip.

**Expected:** Log shows "pending concern self-corrected, discarding". No thought emitted.

### 3. Missing issue (should emit)

> Interesting. You know what, while we're here, I've been thinking we should also add a confirmation animation when the mode changes. Let's put that aside for now though.

Future work mentioned, no issue created.

**Expected:** After grace period, emits something like `[adherence] Future work was discussed but no issue was created.`

### 4. Push without review (should emit)

> OK, go ahead and fix the flicker. Just push it when you're done.

Telling CC to push without review.

**Expected:** Emits something like `[adherence] You committed but didn't run code review — the workflow requires review before pushing.`

### 5. Brainstorm mode (should stay silent)

> Actually hold on, let's not push anything. I want to brainstorm — what if we redesigned the panel entirely?

Not development. Just thinking.

**Expected:** Silence. Overmind recognizes brainstorm mode and does not flag anything.

## What to check in logs

| Scenario | Log evidence |
|---|---|
| 1. Concern held | `holding concern: [adherence] ...exploration...` |
| 2. Self-correction | `pending concern self-corrected, discarding` |
| 3. Issue missing | Thought emitted to stdout (visible in CC session) |
| 4. No review | Thought emitted to stdout |
| 5. Silence | `evaluating N buffered turns` followed by no emission |

## Additional things to verify

- **Debounce:** Messages 1-2 sent rapidly should batch in one evaluation window, not trigger two separate evaluations.
- **No repeats:** If messages 3 and 4 both trigger similar "workflow" thoughts, only the first should emit.
- **Graphiti ingestion:** If OPENAI_API_KEY is set, check `~/Projects/overmind/data/` for a new Kuzu database directory.
- **Auto-cleanup:** After the test, close the CC session. Within 5 minutes (or immediately if parent detection works), the overmind process should exit. Verify with `ps aux | grep overmind`.

## After testing

Come back to the main session and report:
1. Which thoughts appeared in the CC session (if any)
2. What the log file shows for each step
3. Whether the timing felt right or too slow/fast
