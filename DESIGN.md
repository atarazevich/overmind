# Overmind — Design

Proactive thought injection for Claude Code sessions. Monitors conversation, checks adherence to development standards, recalls relevant past context, and surfaces thoughts only when useful.

## How it works

Overmind is a Claude Code skill. You type `/overmind` and it starts a background process via Monitor(). The process tails the current session's JSONL, strips it to user+assistant messages (no tool calls), and periodically evaluates whether a thought should surface.

A thought is a plain text line emitted to stdout. Monitor catches it and injects it into the CC session as a notification.

## Architecture

```
CC session
  │
  ├─ /overmind starts Monitor on: python ~/Projects/overmind/overmind/watch.py <session-jsonl-path>
  │
  ├─ watch.py tails the JSONL file
  │   ├─ filters out tool_use, tool_result → keeps only user + assistant text
  │   ├─ accumulates turns in a debounce window
  │   ├─ when window closes, pipes stripped turns to:
  │   │     claude -p --model sonnet --system-prompt-file prompts/adherence.md
  │   ├─ if Sonnet returns a thought → emit to stdout → Monitor injects it
  │   └─ if Sonnet says nothing relevant → silence
  │
  └─ simultaneously, extracted conversation data → Graphiti (Kuzu local) for long-term memory
```

## Model invocation — zero setup

The monitoring model is called via Claude Code headless mode:

```bash
echo "<stripped conversation turns>" | claude -p --model sonnet --system-prompt-file prompts/adherence.md
```

No API keys. No SDK. No config. Uses the host CC installation's auth. If CC is installed, Overmind works.

## Conversation filtering

The JSONL format has one JSON object per line. Each has a `message` field with `role` and `content`. Content can be a string or an array of typed blocks.

**Keep:** entries where role is `user` or `assistant` AND content is plain text (type `text`)
**Drop:** all `tool_use`, `tool_result`, `system` entries. All content blocks that aren't `type: text`.

This reduces a typical conversation from thousands of tokens to hundreds.

## Thought types

### Adherence
Surfaces when a development standard is being missed in the current session.

```
[adherence] Did we forget to run code review before pushing?
```

No timestamp — it's about right now.

### Recall
Surfaces relevant context from past sessions stored in Graphiti.

```
[recall] 2026-03-15 — User gave feedback: always explore before coding.
↳ session e18b1726, turns 12-15
```

Timestamp + session reference. CC can read that JSONL range to get full context.

### Feedback
Surfaces when past user feedback is relevant to current work.

```
[feedback] 2026-04-01 — User said: don't delegate the whole task to one sub-agent.
↳ session 5a40b5fd, turns 8-10
```

## Patience mechanism

Three rules:

1. **Debounce window.** Accumulate 3-8 turns before evaluating. If messages arrive within 10s of each other, extend the window. Never evaluate mid-burst.

2. **Self-correction grace.** When something looks off, hold the concern internally for 2-3 more turns. If the conversation self-corrects, discard. Only emit if the gap persists.

3. **No repeats.** Track emitted thought topics in a set. Same topic = no second alert in this session.

## What gets saved to Graphiti

Same stripped conversation — user+assistant text only. Saved as episodes. Graphiti extracts entities and edges automatically.

### Edge types

| Edge | Meaning | Example |
|------|---------|---------|
| decided | User made a decision | User → decided → use a feature flag for rollout |
| gave_feedback | User corrected or confirmed approach | User → gave_feedback → always explore before coding |
| requested | User asked for something | User → requested → settings page with persistence |
| attempted | Assistant tried something | You → attempted → fix the auth refresh race |
| suggested | Assistant proposed something | You → suggested → sliding window for streaming |
| mentioned | Either party referenced in passing | User → mentioned → Graphiti for temporal memory |

Each edge carries: timestamp, session_id, turn_range, project_scope.

### Entity types

- **Person** — the user, collaborators
- **Feature** — feature names, components, capabilities
- **Decision** — architectural/product choices
- **Tool** — libraries, frameworks, services
- **File** — source files referenced in conversation

## Infrastructure

- **Monitoring model:** Sonnet via `claude -p --model sonnet` (zero setup, uses host CC auth)
- **Graph database:** Kuzu (embedded, local file, zero server) via `graphiti-core[kuzu]`. Data lives in `~/Projects/overmind/data/<project-hash>/`
- **Memory scope:** Per-project. Conversations partitioned by project path.
- **Chat history source:** Claude Code JSONL files in `~/.claude/projects/<project-path>/`

## Project structure

```
~/Projects/overmind/
  overmind/
    __init__.py
    watch.py            # background process — tails JSONL, debounce, evaluate, emit
    ingest.py           # batch ingestion of past conversations into Graphiti
    filter.py           # strips tool calls from JSONL, extracts user+assistant text
    config.py           # paths, thresholds, debounce settings
    graphiti_client.py  # Graphiti/Kuzu connection and episode storage
  prompts/
    adherence.md        # system prompt for adherence checking
    recall.md           # system prompt for deciding when to surface past context
  data/                 # Kuzu databases per project (gitignored)
  tests/
    test_filter.py
    test_watch.py
  pyproject.toml
  DESIGN.md
  .gitignore

~/.claude/skills/overmind.md    # CC skill definition
```

## Skill invocation

```
/overmind                  # start monitoring current session
/overmind stop             # stop monitoring
/overmind ingest           # batch-ingest past conversations into Graphiti
/overmind status           # show connection, last thought, turns processed
```

## Build phases

### Phase 1 — Adherence monitor (no database)
- filter.py: parse JSONL, strip tool calls
- watch.py: tail file, debounce, pipe to `claude -p`, emit thoughts
- prompts/adherence.md: the adherence prompt
- skill definition: ~/.claude/skills/overmind.md
- Tests for filter and debounce logic

### Phase 2 — Graphiti integration (temporal memory)
- graphiti_client.py: Kuzu setup, episode storage
- ingest.py: batch process past JSONLs
- prompts/recall.md: recall evaluation prompt
- recall thought type in watch.py
- Tests for ingestion and retrieval

### Phase 3 — Feedback loop
- Detect and store user feedback edges specifically
- Surface relevant past feedback during similar situations
- Feedback thought type in watch.py
