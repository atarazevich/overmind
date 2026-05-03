"""Tests for overmind.watch — debounce logic, dedup, evaluation triggering, recall."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from overmind.config import (
    MAX_CONTEXT_TURNS,
    MAX_TURNS_FORCE_EVAL,
    MIN_TURNS_BEFORE_EVAL,
    QUIET_PERIOD_SECONDS,
)
from overmind.filter import Turn
from overmind.watch import (
    WatchLoop,
    _call_claude,
    _evaluate,
    _evaluate_recall,
    _extract_keywords,
    _format_transcript,
)


def _make_turn(role: str = "user", text: str = "hello", n: int = 1) -> Turn:
    return Turn(role=role, text=text, timestamp="2026-04-01T10:00:00.000Z", turn_number=n)


class TestDebounce:
    """Tests for debounce logic in WatchLoop._should_evaluate."""

    def test_no_eval_below_min_turns(self) -> None:
        """Should not evaluate with fewer than MIN_TURNS_BEFORE_EVAL turns."""
        loop = WatchLoop("/dev/null")
        loop.buffer = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL - 1)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1
        assert not loop._should_evaluate()

    def test_no_eval_during_activity(self) -> None:
        """Should not evaluate when turns arrived recently (within quiet period)."""
        loop = WatchLoop("/dev/null")
        loop.buffer = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic()  # just now
        assert not loop._should_evaluate()

    def test_eval_after_quiet_period(self) -> None:
        """Should evaluate when quiet period elapsed and enough turns buffered."""
        loop = WatchLoop("/dev/null")
        loop.buffer = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1
        assert loop._should_evaluate()

    def test_force_eval_at_max_turns(self) -> None:
        """Should force evaluation when buffer reaches MAX_TURNS_FORCE_EVAL."""
        loop = WatchLoop("/dev/null")
        loop.buffer = [_make_turn(n=i) for i in range(MAX_TURNS_FORCE_EVAL)]
        loop.last_turn_time = time.monotonic()  # even if just arrived
        assert loop._should_evaluate()

    def test_extending_window_resets_quiet(self) -> None:
        """New turns arriving extend the quiet period window."""
        loop = WatchLoop("/dev/null")
        loop.buffer = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]

        # Set last_turn_time to almost past quiet period
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS + 1
        assert not loop._should_evaluate()

        # Simulate a new turn arriving (resets the timer)
        loop.buffer.append(_make_turn(n=99))
        loop.last_turn_time = time.monotonic()
        assert not loop._should_evaluate()

    def test_should_evaluate_with_explicit_buffer(self) -> None:
        """_should_evaluate accepts an explicit buffer to check."""
        loop = WatchLoop("/dev/null")
        loop.buffer = []  # empty self.buffer
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1

        explicit = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        assert loop._should_evaluate(buffer=explicit)
        assert not loop._should_evaluate()  # self.buffer still empty


class TestNoRepeatTracking:
    """Tests for dedup logic in WatchLoop._emit."""

    def test_first_emit_goes_through(self, capsys: pytest.CaptureFixture[str]) -> None:
        """First time a thought is emitted, it prints."""
        loop = WatchLoop("/dev/null")
        loop._emit("[adherence] You forgot to explore.")
        captured = capsys.readouterr()
        assert "[adherence] You forgot to explore." in captured.out

    def test_duplicate_suppressed(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Same thought emitted twice — second time is suppressed."""
        loop = WatchLoop("/dev/null")
        loop._emit("[adherence] You forgot to explore first.")
        loop._emit("[adherence] You forgot to explore first.")
        captured = capsys.readouterr()
        # Only one occurrence in stdout
        assert captured.out.count("[adherence]") == 1

    def test_different_thoughts_both_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Different thoughts are both emitted."""
        loop = WatchLoop("/dev/null")
        loop._emit("[adherence] Missing exploration step.")
        loop._emit("[adherence] No code review before push.")
        captured = capsys.readouterr()
        assert captured.out.count("[adherence]") == 2


class TestFormatTranscript:
    """Tests for _format_transcript."""

    def test_basic_format(self) -> None:
        turns = [
            _make_turn("user", "Fix the bug."),
            _make_turn("assistant", "I'll look into it."),
        ]
        result = _format_transcript(turns)
        assert "[user] Fix the bug." in result
        assert "[assistant] I'll look into it." in result

    def test_empty_turns(self) -> None:
        assert _format_transcript([]) == ""


class TestCallClaude:
    """Tests for _call_claude — shared async subprocess helper."""

    @pytest.mark.asyncio
    async def test_returns_matching_line(self) -> None:
        """When claude returns a line with an accepted prefix, it's returned."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"[adherence] You skipped exploration.", b"")
        )
        mock_proc.returncode = 0

        with patch("overmind.watch.asyncio.create_subprocess_exec", return_value=mock_proc):
            from overmind.config import ADHERENCE_PROMPT
            result = await _call_claude(ADHERENCE_PROMPT, "test input", ["[adherence]"])
        assert result == "[adherence] You skipped exploration."

    @pytest.mark.asyncio
    async def test_none_response_returns_none(self) -> None:
        """When claude returns 'none', returns None."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"none", b""))
        mock_proc.returncode = 0

        with patch("overmind.watch.asyncio.create_subprocess_exec", return_value=mock_proc):
            from overmind.config import ADHERENCE_PROMPT
            result = await _call_claude(ADHERENCE_PROMPT, "test input", ["[adherence]"])
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_input_returns_none(self) -> None:
        """Empty input text returns None without calling subprocess."""
        from overmind.config import ADHERENCE_PROMPT
        result = await _call_claude(ADHERENCE_PROMPT, "   ", ["[adherence]"])
        assert result is None

    @pytest.mark.asyncio
    async def test_cli_error_returns_none(self) -> None:
        """When claude CLI fails, returns None."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: model not found"))
        mock_proc.returncode = 1

        with patch("overmind.watch.asyncio.create_subprocess_exec", return_value=mock_proc):
            from overmind.config import ADHERENCE_PROMPT
            result = await _call_claude(ADHERENCE_PROMPT, "test input", ["[adherence]"])
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self) -> None:
        """When claude CLI times out, returns None."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.returncode = None

        with patch("overmind.watch.asyncio.create_subprocess_exec", return_value=mock_proc):
            from overmind.config import ADHERENCE_PROMPT
            result = await _call_claude(ADHERENCE_PROMPT, "test input", ["[adherence]"])
        assert result is None


class TestEvaluate:
    """Tests for _evaluate — now async, delegates to _call_claude."""

    @pytest.mark.asyncio
    async def test_adherence_thought_returned(self) -> None:
        """When claude returns an adherence line, _evaluate returns it."""
        with patch("overmind.watch._call_claude", return_value="[adherence] You skipped exploration."):
            turns = [_make_turn("user", "Fix it."), _make_turn("assistant", "Done.")]
            result = await _evaluate(turns)
        assert result == "[adherence] You skipped exploration."

    @pytest.mark.asyncio
    async def test_none_response_returns_none(self) -> None:
        """When claude returns None, _evaluate returns None."""
        with patch("overmind.watch._call_claude", return_value=None):
            turns = [_make_turn("user", "Hello.")]
            result = await _evaluate(turns)
        assert result is None


class TestEvaluateTruncation:
    """Tests for _evaluate truncating to MAX_CONTEXT_TURNS."""

    @pytest.mark.asyncio
    async def test_truncates_to_max_context_turns(self) -> None:
        """When more turns than MAX_CONTEXT_TURNS are passed, only the last N appear in the transcript."""
        captured_input: list[str] = []

        async def mock_call_claude(prompt_path, input_text, prefixes):
            captured_input.append(input_text)
            return None

        # Create more turns than the limit, using unique markers
        num_turns = MAX_CONTEXT_TURNS + 10
        turns = [_make_turn("user", f"TURN_MARKER_{i:04d}", n=i) for i in range(num_turns)]

        with patch("overmind.watch._call_claude", side_effect=mock_call_claude):
            await _evaluate(turns)

        transcript_input = captured_input[0]

        # Early turns (those truncated away) should NOT be present
        truncated_count = num_turns - MAX_CONTEXT_TURNS
        for i in range(truncated_count):
            assert f"TURN_MARKER_{i:04d}" not in transcript_input, (
                f"TURN_MARKER_{i:04d} should have been truncated"
            )

        # The last MAX_CONTEXT_TURNS turns should all be present
        for i in range(truncated_count, num_turns):
            assert f"TURN_MARKER_{i:04d}" in transcript_input, (
                f"TURN_MARKER_{i:04d} should be in the transcript"
            )


class TestSelfCorrectionGrace:
    """Tests for the pending concern / self-correction grace mechanism."""

    @pytest.mark.asyncio
    async def test_concern_held_on_first_eval(self) -> None:
        """A concern is not emitted immediately — it's held as pending."""
        loop = WatchLoop("/dev/null")
        eval_turns = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1

        with patch("overmind.watch._evaluate", return_value="[adherence] Missing exploration."):
            await loop._try_evaluate(eval_turns)

        assert loop.pending_concern is not None
        assert loop.pending_concern[0] == "[adherence] Missing exploration."

    @pytest.mark.asyncio
    async def test_concern_emitted_after_two_cycles(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A concern that persists across two evaluation cycles is emitted."""
        loop = WatchLoop("/dev/null")
        thought = "[adherence] Missing exploration."

        # First cycle: concern is held
        eval_turns = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1
        with patch("overmind.watch._evaluate", return_value=thought):
            await loop._try_evaluate(eval_turns)
        assert loop.pending_concern is not None

        # Second cycle: same concern persists — should emit
        eval_turns = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1
        with patch("overmind.watch._evaluate", return_value=thought):
            await loop._try_evaluate(eval_turns)

        captured = capsys.readouterr()
        assert "[adherence] Missing exploration." in captured.out
        assert loop.pending_concern is None

    @pytest.mark.asyncio
    async def test_concern_discarded_on_self_correction(self) -> None:
        """A concern is discarded if the next evaluation returns none."""
        loop = WatchLoop("/dev/null")

        # First cycle: concern is held
        eval_turns = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1
        with patch("overmind.watch._evaluate", return_value="[adherence] Missing exploration."):
            await loop._try_evaluate(eval_turns)
        assert loop.pending_concern is not None

        # Second cycle: self-corrected — no concern
        eval_turns = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL)]
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1
        with patch("overmind.watch._evaluate", return_value=None):
            await loop._try_evaluate(eval_turns)

        assert loop.pending_concern is None


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    """Tests for _extract_keywords."""

    def test_basic_extraction(self) -> None:
        """Extracts meaningful words, skips stopwords."""
        turns = [_make_turn("user", "Fix the TokenRefresher network race in TypeScript.")]
        keywords = _extract_keywords(turns)
        assert "tokenrefresher" in keywords
        assert "network" in keywords
        assert "the" not in keywords

    def test_empty_turns(self) -> None:
        """Empty turns produce empty keywords."""
        assert _extract_keywords([]) == ""

    def test_deduplication(self) -> None:
        """Repeated words don't appear multiple times."""
        turns = [
            _make_turn("user", "Fix TokenRefresher TokenRefresher TokenRefresher"),
        ]
        keywords = _extract_keywords(turns)
        assert keywords.count("tokenrefresher") == 1


# ---------------------------------------------------------------------------
# Recall evaluation
# ---------------------------------------------------------------------------


class TestEvaluateRecall:
    """Tests for _evaluate_recall — now async, delegates to _call_claude."""

    @pytest.mark.asyncio
    async def test_recall_thought_returned(self) -> None:
        """When claude returns a recall line, _evaluate_recall returns it."""
        with patch("overmind.watch._call_claude", return_value="[recall] 2026-03-15 — Decided to use debounce. | session e18b1726"):
            result = await _evaluate_recall("test transcript", [{"fact": "test", "created_at": "2026-03-15", "group_id": "e18b1726", "valid_at": None}])
        assert result is not None
        assert result.startswith("[recall]")

    @pytest.mark.asyncio
    async def test_feedback_thought_returned(self) -> None:
        """When claude returns a feedback line, _evaluate_recall returns it."""
        with patch("overmind.watch._call_claude", return_value="[feedback] 2026-04-01 — User said: don't delegate. | session 5a40b5fd"):
            result = await _evaluate_recall("test transcript", [{"fact": "test", "created_at": "2026-04-01", "group_id": "5a40b5fd", "valid_at": None}])
        assert result is not None
        assert result.startswith("[feedback]")

    @pytest.mark.asyncio
    async def test_none_response(self) -> None:
        """When _call_claude returns None, _evaluate_recall returns None."""
        with patch("overmind.watch._call_claude", return_value=None):
            result = await _evaluate_recall("test transcript", [{"fact": "test", "created_at": "2026-04-01", "group_id": "x", "valid_at": None}])
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_memory_results(self) -> None:
        """Empty memory results return None without calling CLI."""
        result = await _evaluate_recall("test transcript", [])
        assert result is None


# ---------------------------------------------------------------------------
# Recall integration in WatchLoop
# ---------------------------------------------------------------------------


class TestRecallInWatchLoop:
    """Tests for recall integration in the watch loop."""

    def test_graph_none_skips_recall(self) -> None:
        """When graph is None, recall-related paths are inert."""
        loop = WatchLoop("/dev/null", graph=None)
        assert loop.graph is None
        # _try_recall should be a no-op
        # (we test indirectly: no graph means no keyword extraction or search)

    @pytest.mark.asyncio
    async def test_try_recall_skipped_without_graph(self) -> None:
        """_try_recall returns immediately when graph is None."""
        loop = WatchLoop("/dev/null", graph=None)
        eval_turns = [_make_turn("user", "Fix the bug.", n=i) for i in range(5)]
        # Should not raise
        await loop._try_recall(eval_turns)

    @pytest.mark.asyncio
    async def test_try_recall_queries_graph(self) -> None:
        """_try_recall queries the graph and calls _evaluate_recall."""
        mock_graph = AsyncMock()
        mock_graph.available = True
        mock_graph.search_memory = AsyncMock(return_value=[
            {"fact": "User prefers exploration before coding", "created_at": "2026-03-15T10:00:00Z", "group_id": "abc123", "valid_at": None},
        ])

        loop = WatchLoop("/dev/null", graph=mock_graph)
        eval_turns = [_make_turn("user", "Fix the TokenRefresher crash.", n=i) for i in range(5)]

        with patch("overmind.watch._evaluate_recall", return_value="[recall] 2026-03-15 — test recall. | session abc123") as mock_eval:
            await loop._try_recall(eval_turns)

        mock_graph.search_memory.assert_called_once()
        mock_eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_recall_thought_emitted(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When recall returns a thought, it's emitted to stdout."""
        mock_graph = AsyncMock()
        mock_graph.available = True
        mock_graph.search_memory = AsyncMock(return_value=[
            {"fact": "test fact", "created_at": "2026-03-15", "group_id": "abc", "valid_at": None},
        ])

        loop = WatchLoop("/dev/null", graph=mock_graph)
        eval_turns = [_make_turn("user", "Fix the TokenRefresher crash.", n=i) for i in range(5)]

        with patch("overmind.watch._evaluate_recall", return_value="[recall] 2026-03-15 — test recall. | session abc"):
            await loop._try_recall(eval_turns)

        captured = capsys.readouterr()
        assert "[recall]" in captured.out

    @pytest.mark.asyncio
    async def test_recall_dedup_applied(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Recall thoughts are subject to the same dedup as adherence thoughts."""
        mock_graph = AsyncMock()
        mock_graph.available = True
        mock_graph.search_memory = AsyncMock(return_value=[
            {"fact": "test fact", "created_at": "2026-03-15", "group_id": "abc", "valid_at": None},
        ])

        loop = WatchLoop("/dev/null", graph=mock_graph)
        eval_turns = [_make_turn("user", "Fix the TokenRefresher crash.", n=i) for i in range(5)]

        recall_thought = "[recall] 2026-03-15 — test recall about TokenRefresher. | session abc"
        with patch("overmind.watch._evaluate_recall", return_value=recall_thought):
            await loop._try_recall(eval_turns)
            await loop._try_recall(eval_turns)

        captured = capsys.readouterr()
        # Should only appear once due to dedup
        assert captured.out.count("[recall]") == 1


# ---------------------------------------------------------------------------
# Buffer snapshot (Issue 1: recall sees same buffer as evaluate)
# ---------------------------------------------------------------------------


class TestBufferSnapshot:
    """Tests that both evaluations see the same buffer snapshot."""

    @pytest.mark.asyncio
    async def test_both_evaluations_see_same_snapshot(self) -> None:
        """_try_evaluate and _try_recall receive the same eval_turns list."""
        loop = WatchLoop("/dev/null")
        turns = [_make_turn(n=i) for i in range(MIN_TURNS_BEFORE_EVAL + 2)]
        loop.buffer = list(turns)
        loop.last_turn_time = time.monotonic() - QUIET_PERIOD_SECONDS - 1

        eval_snapshot = list(loop.buffer)

        evaluate_received: list[list[Turn]] = []
        recall_received: list[list[Turn]] = []

        async def mock_evaluate(t):
            evaluate_received.append(t)
            return None

        async def mock_recall(t):
            recall_received.append(t)

        with (
            patch.object(loop, "_try_evaluate", side_effect=mock_evaluate),
            patch.object(loop, "_try_recall", side_effect=mock_recall),
        ):
            # Simulate what run_async does
            eval_turns = list(loop.buffer)
            await loop._try_evaluate(eval_turns)
            if loop._should_evaluate(eval_turns):
                await loop._try_recall(eval_turns)

        assert len(evaluate_received) == 1
        assert len(recall_received) == 1
        assert evaluate_received[0] is recall_received[0]  # same list object


# ---------------------------------------------------------------------------
# Live ingestion
# ---------------------------------------------------------------------------


class TestLiveIngestion:
    """Tests for live ingestion of turns into Graphiti during watch."""

    @pytest.mark.asyncio
    async def test_ingest_called_for_new_turns(self) -> None:
        """_ingest_turns calls graph.add_episode for each turn."""
        mock_graph = AsyncMock()
        mock_graph.available = True

        loop = WatchLoop("/dev/null", graph=mock_graph)
        turns = [
            _make_turn("user", "Hello", n=1),
            _make_turn("assistant", "Hi there", n=2),
        ]

        await loop._ingest_turns(turns)

        assert mock_graph.add_episode.call_count == 2

    @pytest.mark.asyncio
    async def test_ingest_skipped_without_graph(self) -> None:
        """_ingest_turns is a no-op when graph is None."""
        loop = WatchLoop("/dev/null", graph=None)
        turns = [_make_turn("user", "Hello", n=1)]
        # Should not raise
        await loop._ingest_turns(turns)

    @pytest.mark.asyncio
    async def test_ingest_skipped_when_unavailable(self) -> None:
        """_ingest_turns is a no-op when graph is not available."""
        mock_graph = AsyncMock()
        mock_graph.available = False

        loop = WatchLoop("/dev/null", graph=mock_graph)
        turns = [_make_turn("user", "Hello", n=1)]
        await loop._ingest_turns(turns)

        mock_graph.add_episode.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_error_does_not_crash(self) -> None:
        """Errors in _ingest_turns are caught and logged, not propagated."""
        mock_graph = AsyncMock()
        mock_graph.available = True
        mock_graph.add_episode = AsyncMock(side_effect=RuntimeError("test error"))

        loop = WatchLoop("/dev/null", graph=mock_graph)
        turns = [_make_turn("user", "Hello", n=1)]
        # Should not raise
        await loop._ingest_turns(turns)
