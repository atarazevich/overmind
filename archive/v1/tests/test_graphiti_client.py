"""Tests for overmind.graphiti_client — graph wrapper, ontology, graceful degradation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from overmind.graphiti_client import (
    EDGE_TYPE_MAP,
    EDGE_TYPES,
    ENTITY_TYPES,
    OvermindGraph,
)

# ---------------------------------------------------------------------------
# Ontology sanity checks (no API keys needed)
# ---------------------------------------------------------------------------


class TestOntology:
    """Verify the ontology schema is consistent."""

    def test_entity_types_are_pydantic_models(self) -> None:
        for name, cls in ENTITY_TYPES.items():
            assert hasattr(cls, "model_fields"), f"{name} is not a Pydantic model"

    def test_edge_types_are_pydantic_models(self) -> None:
        for name, cls in EDGE_TYPES.items():
            assert hasattr(cls, "model_fields"), f"{name} is not a Pydantic model"

    def test_edge_type_map_references_valid_entity_types(self) -> None:
        for (src, tgt), edges in EDGE_TYPE_MAP.items():
            assert src in ENTITY_TYPES, f"Unknown entity type in edge map: {src}"
            assert tgt in ENTITY_TYPES, f"Unknown entity type in edge map: {tgt}"
            for edge_name in edges:
                assert edge_name in EDGE_TYPES, f"Unknown edge type in map: {edge_name}"


# ---------------------------------------------------------------------------
# Graceful degradation (no API keys)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """OvermindGraph should degrade gracefully when API keys are missing."""

    @pytest.mark.asyncio
    async def test_initialize_without_keys(self, tmp_path) -> None:
        """initialize() sets available=False and logs when keys are missing."""
        env = os.environ.copy()
        env.pop("OPENAI_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            graph = OvermindGraph(str(tmp_path / "test-project"))
            await graph.initialize()
            assert graph.available is False

    @pytest.mark.asyncio
    async def test_add_episode_noop_when_unavailable(self, tmp_path) -> None:
        """add_episode returns silently when graph is unavailable."""
        graph = OvermindGraph(str(tmp_path / "test-project"))
        graph.available = False
        # Should not raise
        await graph.add_episode(
            session_id="test-session",
            turn_text="user: Hello",
            timestamp="2026-04-01T10:00:00.000Z",
        )

    @pytest.mark.asyncio
    async def test_search_memory_empty_when_unavailable(self, tmp_path) -> None:
        """search_memory returns empty list when graph is unavailable."""
        graph = OvermindGraph(str(tmp_path / "test-project"))
        graph.available = False
        results = await graph.search_memory("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_close_safe_when_not_initialized(self, tmp_path) -> None:
        """close() doesn't raise when graph was never initialized."""
        graph = OvermindGraph(str(tmp_path / "test-project"))
        await graph.close()


# ---------------------------------------------------------------------------
# Integration tests (need real API keys)
# ---------------------------------------------------------------------------

_has_keys = bool(os.environ.get("OPENAI_API_KEY"))


@pytest.mark.skipif(not _has_keys, reason="OPENAI_API_KEY not set")
class TestIntegration:
    """Integration tests that require real API keys and a Kuzu database."""

    @pytest.mark.asyncio
    async def test_initialize_creates_database(self, tmp_path) -> None:
        """OvermindGraph creates a Kuzu database directory on init."""
        graph = OvermindGraph(str(tmp_path / "test-project"))
        await graph.initialize()
        assert graph.available is True
        assert graph.data_dir.exists()
        await graph.close()

    @pytest.mark.asyncio
    async def test_add_and_search(self, tmp_path) -> None:
        """Episodes added can be found via search."""
        graph = OvermindGraph(str(tmp_path / "test-project"))
        await graph.initialize()
        assert graph.available is True

        await graph.add_episode(
            session_id="test-session-001",
            turn_text="user: We decided to use Kuzu as the embedded graph database.",
            timestamp="2026-04-01T10:00:00.000Z",
            source_description="test session",
        )

        results = await graph.search_memory("Kuzu graph database", num_results=5)
        assert len(results) > 0
        # At least one result should mention Kuzu
        facts = " ".join(r.get("fact", "") or "" for r in results)
        assert "kuzu" in facts.lower() or "graph" in facts.lower()

        await graph.close()
