"""Tests for overmind.ingest — batch ingestion of conversations into Graphiti."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from overmind.config import encode_project_path, find_project_dir


class TestEncodeProjectPath:
    """Tests for the project path encoding helper."""

    def test_basic_encoding(self) -> None:
        assert encode_project_path("/Users/alex/Projects/myapp") == "-Users-alex-Projects-myapp"

    def test_root_path(self) -> None:
        assert encode_project_path("/") == "-"

    def test_no_slashes(self) -> None:
        assert encode_project_path("simple") == "simple"

    def test_multiple_slashes(self) -> None:
        assert encode_project_path("/a/b/c/d") == "-a-b-c-d"

    def test_dot_encoding(self) -> None:
        """Dots are encoded as hyphens, matching Claude Code's behavior."""
        assert encode_project_path("/Users/alex/.claude") == "-Users-alex--claude"

    def test_dotfile_in_path(self) -> None:
        """Dotfiles produce double hyphens (slash-dot -> dash-dash)."""
        assert encode_project_path("/Users/alex/.config/app") == "-Users-alex--config-app"


class TestFindProjectDir:
    """Tests for find_project_dir — suffix-based directory search."""

    def test_finds_by_suffix(self, tmp_path: Path) -> None:
        """Finds a project directory by matching the tail of the path."""
        projects_dir = tmp_path / ".claude" / "projects"
        target = projects_dir / "-Users-alex-Projects-myapp"
        target.mkdir(parents=True)

        with patch("overmind.config.CLAUDE_PROJECTS_DIR", projects_dir):
            result = find_project_dir("/Users/alex/Projects/myapp")
        assert result == target

    def test_finds_dotpath_by_suffix(self, tmp_path: Path) -> None:
        """Finds a dotfile project directory by suffix matching."""
        projects_dir = tmp_path / ".claude" / "projects"
        target = projects_dir / "-Users-alex--claude"
        target.mkdir(parents=True)

        with patch("overmind.config.CLAUDE_PROJECTS_DIR", projects_dir):
            # The suffix for /.claude would be "-claude" but the dir has "--claude"
            # because the dot becomes a dash. The suffix matching uses path parts,
            # not raw encoding, so it should still find the right directory.
            # ".claude" -> suffix is ".claude" from path parts, but on disk it's "--claude"
            # This tests the fallback to exact encoding.
            result = find_project_dir("/Users/alex/.claude")
        assert result == target

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Returns None when no matching directory exists."""
        projects_dir = tmp_path / ".claude" / "projects"
        projects_dir.mkdir(parents=True)

        with patch("overmind.config.CLAUDE_PROJECTS_DIR", projects_dir):
            result = find_project_dir("/Users/alex/Projects/nonexistent")
        assert result is None

    def test_returns_none_when_projects_dir_missing(self, tmp_path: Path) -> None:
        """Returns None when the projects directory itself doesn't exist."""
        with patch("overmind.config.CLAUDE_PROJECTS_DIR", tmp_path / "nonexistent"):
            result = find_project_dir("/Users/alex/Projects/myapp")
        assert result is None


class TestIngestDiscovery:
    """Test that ingest correctly discovers JSONL files."""

    @pytest.mark.asyncio
    async def test_discovers_jsonl_files(self, tmp_path: Path) -> None:
        """Ingest finds all .jsonl files in the project directory."""
        from overmind.ingest import _ingest

        project_path = "/Users/test/Projects/myapp"

        # Create mock Claude projects directory with the encoded name
        encoded = encode_project_path(project_path)
        claude_dir = tmp_path / ".claude" / "projects" / encoded
        claude_dir.mkdir(parents=True)

        # Write two session files
        for session_id in ["session-001", "session-002"]:
            jsonl_path = claude_dir / f"{session_id}.jsonl"
            lines = [
                {
                    "type": "user",
                    "isSidechain": False,
                    "message": {"role": "user", "content": f"Hello from {session_id}"},
                    "timestamp": "2026-04-01T10:00:00.000Z",
                },
                {
                    "type": "assistant",
                    "isSidechain": False,
                    "message": {"role": "assistant", "content": f"Response in {session_id}"},
                    "timestamp": "2026-04-01T10:00:01.000Z",
                },
            ]
            with jsonl_path.open("w") as f:
                for obj in lines:
                    f.write(json.dumps(obj) + "\n")

        # Mock the graph client
        mock_graph = AsyncMock()
        mock_graph.available = True
        mock_graph.initialize = AsyncMock()
        mock_graph.add_episode = AsyncMock()
        mock_graph.close = AsyncMock()

        with (
            patch("overmind.config.CLAUDE_PROJECTS_DIR", tmp_path / ".claude" / "projects"),
            patch("overmind.ingest.find_project_dir", return_value=claude_dir),
            patch("overmind.ingest.OvermindGraph", return_value=mock_graph),
        ):
            await _ingest(project_path)

        # Should have called add_episode for each turn (2 sessions x 2 turns)
        assert mock_graph.add_episode.call_count == 4
        mock_graph.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_empty_sessions(self, tmp_path: Path) -> None:
        """Ingest skips JSONL files that produce no text turns."""
        from overmind.ingest import _ingest

        project_path = "/Users/test/Projects/empty"
        encoded = encode_project_path(project_path)

        claude_dir = tmp_path / ".claude" / "projects" / encoded
        claude_dir.mkdir(parents=True)

        # Write a session with only tool calls (no text turns)
        jsonl_path = claude_dir / "empty-session.jsonl"
        lines = [
            {
                "type": "assistant",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
                },
                "timestamp": "2026-04-01T10:00:00.000Z",
            }
        ]
        with jsonl_path.open("w") as f:
            for obj in lines:
                f.write(json.dumps(obj) + "\n")

        mock_graph = AsyncMock()
        mock_graph.available = True
        mock_graph.initialize = AsyncMock()
        mock_graph.add_episode = AsyncMock()
        mock_graph.close = AsyncMock()

        with (
            patch("overmind.config.CLAUDE_PROJECTS_DIR", tmp_path / ".claude" / "projects"),
            patch("overmind.ingest.find_project_dir", return_value=claude_dir),
            patch("overmind.ingest.OvermindGraph", return_value=mock_graph),
        ):
            await _ingest(project_path)

        # No add_episode calls for empty sessions
        mock_graph.add_episode.assert_not_called()
