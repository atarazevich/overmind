# Overmind

A background process that watches your Claude Code conversations and injects thoughts when something gets missed.

## Why

Claude Code is stateless between turns. It follows instructions, but it doesn't step back and ask "wait, are we skipping a step?" the way a human collaborator would. If you tell it to fix a bug and push, it will — without exploring first, without running code review, without creating an issue for the side-thread you mentioned.

Overmind is the part of your brain that notices you forgot something. It monitors the conversation in real time, compares what's happening against your development standards, and speaks up only when a concrete gap persists. It also remembers past sessions — decisions you made, feedback you gave — and surfaces them when they're relevant to what you're working on now.

## How it works

```
You type /overmind in Claude Code
    |
    v
Background process starts, watches the session's conversation log
    |
    v
Every few turns, it strips the conversation to user + assistant text
(no tool calls, no file contents — just what was said)
    |
    v
Sends the stripped turns to Sonnet with a strict prompt:
"Is a development standard being missed? Say so, or say nothing."
    |
    v
If Sonnet flags something, Overmind holds it for one more cycle.
If the conversation self-corrects, it stays silent.
If the gap persists, it emits a single thought.
    |
    v
Claude Code's Monitor catches the thought and injects it
into the conversation as a notification.
```

## What it catches

Overmind checks adherence to seven standards. These are configurable via the prompt in `prompts/adherence.md`.

- **Jumping to code without exploring.** You asked for a fix, the assistant started writing code without reading the existing implementation first.
- **Pushing without code review.** The workflow says review before push. If a commit happens and no review was requested, Overmind speaks up.
- **Future work discussed but not tracked.** You mentioned something should be done later, but no GitHub issue was created.
- **Docs not updated.** A feature changed but the feature doc or decisions log wasn't touched.
- **User feedback ignored.** You gave a correction, the assistant acknowledged it, then did the opposite.
- **Multi-step work without task tracking.** A complex change started with no plan or task list.
- **Workflow steps skipped.** The expected flow is explore, plan, develop, review, commit. Overmind notices when steps are dropped.

## What it remembers

Overmind stores past conversations in a temporal knowledge graph (Graphiti + Kuzu). Entities and relationships are extracted automatically:

| What gets stored | Example |
|---|---|
| Decisions | "User decided to use a feature flag for the rollout" |
| Feedback | "User said: don't delegate the whole task to one sub-agent" |
| Requests | "User requested a settings page with persistent preferences" |
| Attempts | "Assistant attempted to fix the auth refresh race condition" |
| Suggestions | "Assistant suggested a sliding window for the streaming parser" |

Each fact carries a timestamp and session reference. When current work relates to a past decision or correction, Overmind surfaces it:

```
[recall] 2026-03-15 — User decided to use a feature flag for the rollout. | session e18b1726
[feedback] 2026-04-01 — User said: don't delegate the whole task to one sub-agent. | session 5a40b5fd
```

## Patience

Overmind is designed to stay quiet unless something actually matters. Three rules enforce this:

1. **Debounce.** It accumulates 3-8 turns before evaluating. Rapid messages don't trigger rapid thoughts.

2. **Self-correction grace.** When something looks off, it holds the concern for one more evaluation cycle. If the conversation fixes itself (you said "wait, let's explore first"), the concern is silently discarded.

3. **No repeats.** Same concern is never raised twice in a session.

## Install

```bash
cd ~/Projects
git clone https://github.com/atarazevich/overmind.git
cd overmind
pip install -e .
```

Then make the skill discoverable to Claude Code by symlinking (or copying) it into your skills directory:

```bash
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/overmind" ~/.claude/skills/overmind
# or, if you'd rather copy:
# cp -R skills/overmind ~/.claude/skills/overmind
```

Verify:

```bash
ls ~/.claude/skills/overmind/SKILL.md
```

### Requirements

- Python 3.10+
- Claude Code installed (Overmind calls `claude -p` for evaluations)
- `OPENAI_API_KEY` in your environment (for Graphiti entity extraction and embeddings)

Without `OPENAI_API_KEY`, Overmind runs in adherence-only mode — it watches for standard violations but doesn't recall past sessions.

## Use

```
/overmind              Start monitoring the current session
/overmind stop         Stop monitoring
/overmind ingest       Batch-import past conversations into the knowledge graph
/overmind status       Show whether monitor is running and last thought
```

### Watching the logs

From any terminal:

```bash
tail -f ~/Projects/overmind/logs/*.log
```

The log shows every evaluation cycle — what turns were read, whether a concern was held or emitted, and when the process decides to stay silent.

### Ingesting past conversations

To populate the knowledge graph with your existing conversation history:

```bash
python -m overmind.ingest ~/Projects/your-project
```

This reads all Claude Code JSONL files for that project and feeds them into Graphiti.

## Architecture

```
~/.claude/skills/overmind/SKILL.md    Claude Code skill definition
~/Projects/overmind/
    overmind/
        watch.py              Background process (tail, debounce, evaluate, emit)
        filter.py             JSONL parser — strips tool calls, keeps conversation
        graphiti_client.py    Kuzu graph wrapper with entity/edge ontology
        ingest.py             Batch import past conversations
        config.py             All thresholds and model settings
    prompts/
        adherence.md          System prompt for standard-checking evaluations
        recall.md             System prompt for memory recall evaluations
    data/                     Kuzu databases per project (gitignored)
    logs/                     Session logs for debug visibility (gitignored)
    tests/
```

### Process lifecycle

Each `/overmind` invocation starts one `watch.py` process for that session. Multiple sessions each get their own process. All processes for the same project share a single Kuzu database — memories from session A are available in session B.

The process exits automatically when:
- The parent Claude Code process dies
- No new conversation turns arrive for 5 minutes

### Model usage

| Purpose | Model | Why |
|---|---|---|
| Adherence/recall evaluation | Sonnet via `claude -p --bare` | Uses CC auth, zero setup |
| Entity extraction (Graphiti) | gpt-5.4-mini | Cheap, fast, good structured output |
| Embeddings (Graphiti) | OpenAI default | Required by Graphiti for search |

Model names are configurable via environment variables (`GRAPHITI_MODEL`, `GRAPHITI_REASONING_EFFORT`) or in `config.py`.

## Limitations

**Evaluation quality depends on the prompt.** The adherence prompt (`prompts/adherence.md`) is a fixed checklist. If your development standards differ from the defaults, edit the prompt. Overmind doesn't learn your standards — you configure them.

**No real-time injection.** There's a delay between the conversation progressing and Overmind reacting. The debounce window (3-8 turns + 10s quiet period) plus the `claude -p` evaluation time means thoughts arrive 15-30 seconds after the relevant conversation happened. By then, the moment may have passed.

**Token cost.** Each evaluation cycle calls `claude -p` with Sonnet. A typical session triggers 10-30 evaluations. Graphiti ingestion calls gpt-5.4-mini per turn for entity extraction. For an active 1-hour session, expect $0.50-2.00 in API costs across both models.

**Recall precision is early-stage.** Graphiti's entity extraction from conversational text is imperfect. Entity resolution (knowing that "the auth bug" and "TokenRefresher race" are the same thing) depends on the LLM's extraction quality. False negatives are common; false positives are rare but possible.

**Single-machine only.** The Kuzu database is a local file. There's no sync between machines. If you work on a laptop and a desktop, each has its own memory.

**Conversation visibility is one-way.** Overmind reads the conversation but cannot see tool outputs (file contents, command results, search results). It only knows what the user said and what the assistant said in plain text. If the assistant explored a file silently via a tool call and the user never mentioned it, Overmind doesn't know the exploration happened.

**Self-correction grace can miss fast mistakes.** If a violation happens and is acted on within the same evaluation window (before Overmind even evaluates), it will never be caught. The grace period is a feature, but it means some real violations slip through when they're immediately executed.

## Status

Early prototype. Built April 2026. The adherence monitor works and has been tested on real sessions. The temporal memory (Graphiti integration) is functional but the recall quality needs tuning with real conversation data. Expect rough edges.
