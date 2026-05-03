#!/usr/bin/env python3
"""Overmind watch process — monitors CC conversation for adherence gaps and recalls past context."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from overmind.graphiti_client import OvermindGraph

from overmind.config import (
    ADHERENCE_PROMPT,
    CLAUDE_CMD,
    DEDUP_PREFIX_LENGTH,
    INACTIVITY_TIMEOUT_SECONDS,
    LOG_DIR,
    MAX_CONTEXT_TURNS,
    MAX_TURNS_FORCE_EVAL,
    MIN_TURNS_BEFORE_EVAL,
    PARENT_CHECK_INTERVAL,
    POLL_INTERVAL_SECONDS,
    QUIET_PERIOD_SECONDS,
    RECALL_PROMPT,
)
from overmind.filter import Turn, tail_jsonl

# ---------------------------------------------------------------------------
# Logging — writes to both stderr and ~/Projects/overmind/logs/<session>.log
# ---------------------------------------------------------------------------

_log_file = None


def _log(msg: str) -> None:
    """Write a debug line to stderr and the session log file."""
    global _log_file
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr, flush=True)
    if _log_file is not None:
        try:
            _log_file.write(line + "\n")
            _log_file.flush()
        except Exception:
            pass


def _init_log(session_id: str) -> None:
    """Open the log file for this session."""
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{session_id}.log"
    _log_file = open(log_path, "a", encoding="utf-8")
    _log(f"Log opened: {log_path}")

# Common stopwords for keyword extraction
_STOPWORDS: frozenset[str] = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could must need to of in on at by for with from "
    "and or but not no nor so yet both either neither each every all any few more "
    "most other some such than too very just about above after again also as before "
    "between into through during out up down off over under here there when where "
    "how what which who whom this that these those it its i me my we our you your "
    "he him his she her they them their let get got make made if then else while".split()
)


def _format_transcript(turns: list[Turn]) -> str:
    """Format turns into a plain transcript for the evaluation prompt."""
    lines: list[str] = []
    for turn in turns:
        lines.append(f"[{turn.role}] {turn.text}")
    return "\n\n".join(lines)


async def _call_claude(
    prompt_path: Path,
    input_text: str,
    accepted_prefixes: list[str],
) -> str | None:
    """Shell out to claude CLI with a system prompt, return the first matching line or None.

    Parameters
    ----------
    prompt_path:
        Path to the system prompt file.
    input_text:
        Text piped to claude's stdin.
    accepted_prefixes:
        Lines in the response must start with one of these to be returned.
    """
    if not input_text.strip():
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            *CLAUDE_CMD, "--system-prompt-file", str(prompt_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=input_text.encode()),
            timeout=60,
        )
    except asyncio.TimeoutError:
        _log("claude CLI timeout")
        return None
    except (FileNotFoundError, OSError) as exc:
        _log(f"claude CLI error: {exc}")
        return None

    if proc.returncode != 0:
        stderr_text = stderr_bytes.decode(errors="replace").strip()
        _log(f"claude CLI exit {proc.returncode}: {stderr_text}")
        return None

    response = stdout_bytes.decode(errors="replace").strip()

    if not response or response.lower() == "none":
        return None

    for line in response.splitlines():
        line = line.strip()
        if any(line.startswith(prefix) for prefix in accepted_prefixes):
            return line

    return None


async def _evaluate(turns: list[Turn]) -> str | None:
    """Evaluate conversation turns for adherence issues."""
    context = turns[-MAX_CONTEXT_TURNS:]
    transcript = _format_transcript(context)
    return await _call_claude(ADHERENCE_PROMPT, transcript, ["[adherence]"])


def _extract_keywords(turns: list[Turn], max_keywords: int = 10) -> str:
    """Extract top keywords from recent turns for memory search."""
    words: dict[str, int] = {}
    for turn in turns[-5:]:
        for word in turn.text.split():
            cleaned = word.strip(".,;:!?()[]{}\"'`").lower()
            if len(cleaned) > 2 and cleaned not in _STOPWORDS:
                words[cleaned] = words.get(cleaned, 0) + 1

    sorted_words = sorted(words, key=lambda w: words[w], reverse=True)
    return " ".join(sorted_words[:max_keywords])


async def _evaluate_recall(transcript: str, memory_results: list[dict[str, str | float | None]]) -> str | None:
    """Evaluate recall: check if memory results are relevant to the current conversation."""
    if not memory_results:
        return None

    memory_lines: list[str] = []
    for result in memory_results:
        fact = result.get("fact", "")
        date = (result.get("valid_at") or result.get("created_at") or "unknown")
        # Truncate the ISO timestamp to date only
        if isinstance(date, str) and "T" in date:
            date = date.split("T")[0]
        session = result.get("group_id", "unknown")
        memory_lines.append(f"- fact: \"{fact}\" | date: {date} | session: {session}")

    prompt_input = (
        f"=== CURRENT CONVERSATION ===\n{transcript}\n\n"
        f"=== MEMORY RESULTS ===\n" + "\n".join(memory_lines)
    )

    return await _call_claude(RECALL_PROMPT, prompt_input, ["[recall]", "[feedback]"])


class WatchLoop:
    """Main watch loop with debounce, dedup, recall, and live ingestion."""

    def __init__(self, jsonl_path: str, graph: OvermindGraph | None = None) -> None:
        self.jsonl_path = jsonl_path
        self.graph = graph
        self.session_id: str = Path(jsonl_path).stem
        self.byte_offset: int = 0
        self.buffer: list[Turn] = []
        self.last_turn_time: float = 0.0
        self.last_activity_time: float = 0.0  # tracks ANY new data for liveness
        self.emitted: set[str] = set()
        self.pending_concern: tuple[str, int] | None = None  # (thought, turns_seen)
        self.running: bool = True
        self._parent_pid: int = os.getppid()
        self._poll_count: int = 0

    def _is_session_dead(self) -> bool:
        """Check if the session has ended — parent died or inactivity timeout."""
        # Check parent process every N polls
        self._poll_count += 1
        if self._poll_count % PARENT_CHECK_INTERVAL == 0:
            try:
                os.kill(self._parent_pid, 0)  # signal 0 = check if alive
            except OSError:
                _log(f"parent process {self._parent_pid} is dead, exiting")
                return True

        # Check inactivity timeout
        if self.last_activity_time > 0:
            idle = time.monotonic() - self.last_activity_time
            if idle > INACTIVITY_TIMEOUT_SECONDS:
                _log(f"no activity for {idle:.0f}s, exiting")
                return True

        return False

    def _should_evaluate(self, buffer: list[Turn] | None = None) -> bool:
        """Decide whether to trigger evaluation based on debounce rules.

        When ``buffer`` is provided, its length is used instead of ``self.buffer``.
        """
        buf = buffer if buffer is not None else self.buffer
        if len(buf) < MIN_TURNS_BEFORE_EVAL:
            return False

        # Force evaluation if buffer is at max capacity
        if len(buf) >= MAX_TURNS_FORCE_EVAL:
            return True

        # Trigger if quiet period has elapsed since last turn
        elapsed = time.monotonic() - self.last_turn_time
        return elapsed >= QUIET_PERIOD_SECONDS

    def _dedup_key(self, thought: str) -> str:
        """Extract dedup key from a thought."""
        return thought[:DEDUP_PREFIX_LENGTH]

    def _emit(self, thought: str) -> None:
        """Emit a thought to stdout if not already emitted."""
        key = self._dedup_key(thought)
        if key in self.emitted:
            _log(f"suppressed duplicate: {key!r}")
            return

        self.emitted.add(key)
        print(thought, flush=True)

    def _poll(self) -> list[Turn]:
        """Check for new turns in the JSONL file. Returns new turns."""
        try:
            new_turns, new_offset = tail_jsonl(self.jsonl_path, self.byte_offset)
        except (FileNotFoundError, OSError) as exc:
            _log(f"read error: {exc}")
            return []

        self.byte_offset = new_offset
        if new_turns:
            self.buffer.extend(new_turns)
            now = time.monotonic()
            self.last_turn_time = now
            self.last_activity_time = now
            _log(f"+{len(new_turns)} turns, buffer={len(self.buffer)}, offset={self.byte_offset}")

        return new_turns

    async def _ingest_turns(self, turns: list[Turn]) -> None:
        """Fire-and-forget ingestion of new turns into Graphiti."""
        if self.graph is None:
            return
        if not getattr(self.graph, "available", False):
            return

        for turn in turns:
            try:
                await self.graph.add_episode(
                    session_id=self.session_id,
                    turn_text=f"{turn.role}: {turn.text}",
                    timestamp=turn.timestamp,
                )
            except Exception as exc:
                _log(f"ingest error: {exc}")

    async def _try_recall(self, eval_turns: list[Turn]) -> None:
        """Query memory and evaluate recall if graph is available.

        Parameters
        ----------
        eval_turns:
            The snapshot of turns to use for keyword extraction and transcript.
            This avoids reading from ``self.buffer`` which may have been trimmed.
        """
        if self.graph is None:
            return
        if not getattr(self.graph, "available", False):
            return

        keywords = _extract_keywords(eval_turns)
        if not keywords:
            return

        try:
            memory_results = await self.graph.search_memory(keywords, num_results=10)
        except Exception as exc:
            _log(f"memory search error: {exc}")
            return

        if not memory_results:
            return

        transcript = _format_transcript(eval_turns[-MAX_CONTEXT_TURNS:])
        thought = await _evaluate_recall(transcript, memory_results)
        if thought:
            self._emit(thought)

    async def _try_evaluate(self, eval_turns: list[Turn]) -> None:
        """Evaluate if debounce conditions are met.

        Parameters
        ----------
        eval_turns:
            The snapshot of turns to evaluate. This avoids reading from
            ``self.buffer`` which may be trimmed after evaluation.

        Implements self-correction grace: a concern must survive two
        consecutive evaluation cycles before being emitted.  If the next
        evaluation returns 'none', the pending concern is discarded.
        """
        if not self._should_evaluate(eval_turns):
            return

        _log(f"evaluating {len(eval_turns)} buffered turns")

        thought = await _evaluate(eval_turns)

        if self.pending_concern is not None:
            pending_thought, _pending_seen = self.pending_concern
            if thought and self._dedup_key(thought) == self._dedup_key(pending_thought):
                # Same concern persisted across two cycles — emit
                self._emit(thought)
                self.pending_concern = None
            else:
                # Conversation self-corrected — discard the pending concern
                _log("pending concern self-corrected, discarding")
                self.pending_concern = None
                # If the new evaluation raised a *different* concern, hold it
                if thought:
                    self.pending_concern = (thought, len(eval_turns))
        elif thought:
            # First time seeing this concern — hold it for the grace period
            self.pending_concern = (thought, len(eval_turns))
            _log(f"holding concern: {thought[:60]}")

    async def run_async(self) -> None:
        """Async main loop: poll, ingest, debounce, evaluate, recall."""
        _log(f"Overmind watching: {self.jsonl_path}")

        # Initialize times so we don't immediately evaluate or timeout
        now = time.monotonic()
        self.last_turn_time = now
        self.last_activity_time = now

        while self.running:
            # Self-cleanup: exit if session is dead
            if self._is_session_dead():
                _log("session ended, cleaning up")
                break

            new_turns = self._poll()

            # Fire-and-forget live ingestion
            if new_turns:
                asyncio.create_task(self._ingest_turns(new_turns))

            # Snapshot the buffer so both evaluations see the same data
            eval_turns = list(self.buffer)

            # Adherence evaluation (async — shells out to claude)
            await self._try_evaluate(eval_turns)

            # Recall evaluation (async — queries Graphiti then shells out)
            if self._should_evaluate(eval_turns):
                await self._try_recall(eval_turns)

            # Trim buffer after both evaluations complete
            self.buffer = self.buffer[-MIN_TURNS_BEFORE_EVAL:]

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def run(self) -> None:
        """Synchronous entry point — runs the async loop."""
        asyncio.run(self.run_async())


def _handle_signal(signum: int, _frame: object) -> None:
    """Handle SIGTERM for clean shutdown."""
    _log(f"received signal {signum}, shutting down")
    raise SystemExit(0)


async def _async_main(jsonl_path: str) -> None:
    """Async entry point: initialize graph and run the watch loop."""
    # The JSONL lives at ~/.claude/projects/<encoded-path>/<session>.jsonl
    # Use the encoded directory name directly as the project identifier —
    # decoding is lossy (hyphens vs directory separators are ambiguous).
    jsonl = Path(jsonl_path)
    session_id = jsonl.stem
    encoded_project = jsonl.parent.name

    _init_log(session_id)

    graph = None
    try:
        from overmind.graphiti_client import OvermindGraph

        graph = OvermindGraph(encoded_project)
        await graph.initialize()
        if not graph.available:
            graph = None
    except Exception as exc:
        _log(f"Graphiti init failed: {exc}")
        graph = None

    loop = WatchLoop(jsonl_path, graph=graph)
    try:
        await loop.run_async()
    finally:
        if graph is not None:
            await graph.close()


def main() -> None:
    """Entry point: parse args and run the watch loop."""
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <session-jsonl-path>", file=sys.stderr)
        raise SystemExit(1)

    jsonl_path = sys.argv[1]
    if not Path(jsonl_path).exists():
        print(f"Error: file not found: {jsonl_path}", file=sys.stderr)
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        asyncio.run(_async_main(jsonl_path))
    except (KeyboardInterrupt, SystemExit):
        _log("Overmind stopped.")


if __name__ == "__main__":
    main()
