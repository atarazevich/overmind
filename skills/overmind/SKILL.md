---
name: overmind
description: Start Overmind — proactive thought injection that monitors conversation adherence to development standards and surfaces relevant past context from the knowledge graph.
user_invocable: true
---

# Overmind — Proactive Thought Injection

When the user invokes /overmind, start a background monitor process that watches the current conversation and surfaces thoughts when development standards are being missed. If OPENAI_API_KEY is set, it also recalls relevant context from past sessions via Graphiti.

## Start monitoring

Find the current session's JSONL file path. Session JSONL files live at:

```
~/.claude/projects/<encoded-project-path>/<session-id>.jsonl
```

To find the current session's file:
1. Get the cwd and encode it: replace every `/` with `-`
2. List `~/.claude/projects/<encoded>/` sorted by modification time (`ls -t`)
3. The most recently modified `.jsonl` file is the current session

Then start the monitor:
```
python3 -m overmind.watch <session-jsonl-path>
```

(Requires `pip install -e .` from the cloned repo first.)

The watch process will:
- Monitor adherence to development standards (always)
- Initialize Graphiti for temporal memory if OPENAI_API_KEY is set
- Ingest new turns into the knowledge graph as they arrive
- Query past context and surface relevant recalls

Tell the user: "Overmind is watching. I'll surface thoughts if something gets missed."

If OPENAI_API_KEY is not set, tell the user: "Overmind is watching (adherence only — set OPENAI_API_KEY for temporal memory)."

## /overmind stop

Kill the monitor process. Tell the user: "Overmind stopped."

## /overmind ingest

Batch-ingest past conversations for the current project into Graphiti:

```
python3 -m overmind.ingest <absolute-project-path>
```

This reads all JSONL files from the project's Claude Code directory, parses them, and feeds each turn into the knowledge graph. Requires OPENAI_API_KEY.

## /overmind status

Report whether the monitor is running, how many turns have been processed, and the last thought emitted (if any).
