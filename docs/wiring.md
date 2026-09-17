# Wiring the observer hook into `~/.claude/settings.json`

Done by the owner's main thread, by hand, one entry at a time. Never by a subagent.

## Before

1. Back up: `cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)`
2. Check the key is in the environment Claude Code inherits: `zsh -c 'source ~/.zshrc; echo ${#TYPESAFE_API_KEY}'` prints a non-zero length. If it is missing, every event logs `{"error":"no_key"}` instead of answers.
3. Run the offline tests: `cd ~/Projects/overmind && /usr/bin/python3 -m unittest` (all pass).
4. Pipe one payload: `/usr/bin/python3 ~/Projects/overmind/overmind/hook.py < ~/Projects/overmind/tests/payloads/stop.json` returns at once, prints nothing; `~/Projects/overmind/overmind/tail.py 3` shows the line within ~1 s.

## Interpreter

The command names `/usr/bin/python3` (the system Python, 3.9+), the same binary the agent-notch hook uses and the one in the hook's shebang. A bare `python3` would resolve to the pyenv shim, which adds ~110 ms per launch and would break the < 50 ms synchronous budget.

## The entries

Three are live. The fourth, SubagentStop, no longer has a question to ask: the hook reads its payload and returns without writing. Leaving it wired costs one interpreter start per subagent and nothing else; remove it whenever convenient.

Each is one object to append to the existing array for that event under `"hooks"`. `"async": true` lets Claude continue without waiting; the hook forks anyway, so the parent returns in ~20 ms either way. `"timeout": 10` is not enforced on async hooks but documents the budget (Jev call times out at 5 s).

### 1. Stop

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "\"/usr/bin/python3\" \"/Users/drtarazevich/Projects/overmind/overmind/hook.py\"",
      "async": true,
      "timeout": 10
    }
  ]
}
```

### 2. UserPromptSubmit

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "\"/usr/bin/python3\" \"/Users/drtarazevich/Projects/overmind/overmind/hook.py\"",
      "async": true,
      "timeout": 10
    }
  ]
}
```

### 3. PreToolUse (Bash only)

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "\"/usr/bin/python3\" \"/Users/drtarazevich/Projects/overmind/overmind/hook.py\"",
      "async": true,
      "timeout": 10
    }
  ]
}
```

### 4. SubagentStop — wired, and now silent

The entry, if it is still there, has the same shape as the Stop one. It writes nothing since #16 and can be deleted.

## After each entry

Start a new Claude Code session (settings are read at launch), do one turn, and watch: `~/Projects/overmind/overmind/tail.py 10`. A line per event with `answers` means it works; a line with `error` names the failing class; no line at all means the entry did not fire (check the event name and matcher). Add the next entry only after the previous one shows lines.

A Stop or a UserPromptSubmit line with `"tail_error"` means the hook could not read that session's transcript: the answers it could still give are there, `depth` and `interrupted` are not. `"state_source":"payload+tail"` is the healthy case.

## Opt-in text for one session

```
mkdir -p "$HOME/Library/Application Support/Overmind/opt-in" && touch "$HOME/Library/Application Support/Overmind/opt-in/<session_id>"
```

Lines for that session then carry `state` — exactly what Jev was shown, which is the prompt for UserPromptSubmit, the command for a Bash call, and his request beside the turn's tool calls for a Stop. That is what a fired signal has to be labeled against. Remove the file to stop.

## Undo

Delete the entry from `settings.json` (or restore the backup). The hook leaves nothing running; the log stays in `~/Library/Application Support/Overmind/`.
