"""Graphiti knowledge graph wrapper for Overmind temporal memory.

Uses Kuzu (embedded, local) as the graph backend and OpenAI for
entity/edge extraction and embeddings. Model configured in config.py.
Requires only OPENAI_API_KEY.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from overmind.config import GRAPHITI_MODEL, GRAPHITI_REASONING_EFFORT, get_data_dir


# ---------------------------------------------------------------------------
# Ontology: entity types
# ---------------------------------------------------------------------------

class Person(BaseModel):
    """A person involved in development conversations."""
    # "name" is a protected attribute on Graphiti's EntityNode, so we use "role" only.
    role: Optional[str] = None  # e.g. "user", "developer", "collaborator"


class Feature(BaseModel):
    """A software feature or capability."""
    # "name" is set by Graphiti from the extracted entity name.
    status: Optional[str] = None  # e.g. "planned", "active", "shipped"


class Decision(BaseModel):
    """An architectural or product decision."""
    description: Optional[str] = None
    context: Optional[str] = None


class Tool(BaseModel):
    """A development tool or technology."""
    # "name" is set by Graphiti from the extracted entity name.
    purpose: Optional[str] = None


class SourceFile(BaseModel):
    """A source code file referenced in conversation."""
    path: Optional[str] = None


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": Person,
    "Feature": Feature,
    "Decision": Decision,
    "Tool": Tool,
    "SourceFile": SourceFile,
}

# ---------------------------------------------------------------------------
# Ontology: edge types
# ---------------------------------------------------------------------------


class Decided(BaseModel):
    """User made a decision."""
    pass


class GaveFeedback(BaseModel):
    """User corrected or confirmed an approach."""
    sentiment: Optional[str] = None  # "correction" or "confirmation"


class Requested(BaseModel):
    """User asked for something."""
    priority: Optional[str] = None


class Attempted(BaseModel):
    """Assistant tried something."""
    outcome: Optional[str] = None  # "succeeded", "failed", "partial"


class Suggested(BaseModel):
    """Assistant proposed something."""
    pass


class Mentioned(BaseModel):
    """Either party referenced something in passing."""
    pass


EDGE_TYPES: dict[str, type[BaseModel]] = {
    "Decided": Decided,
    "GaveFeedback": GaveFeedback,
    "Requested": Requested,
    "Attempted": Attempted,
    "Suggested": Suggested,
    "Mentioned": Mentioned,
}

EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Person", "Decision"): ["Decided", "Suggested"],
    ("Person", "Feature"): ["Requested", "Mentioned", "Attempted", "Suggested"],
    ("Person", "Tool"): ["Mentioned", "Suggested"],
    ("Person", "SourceFile"): ["Mentioned"],
    ("Person", "Person"): ["GaveFeedback"],
    ("Decision", "Feature"): ["Mentioned"],
    ("Feature", "SourceFile"): ["Mentioned"],
    ("Feature", "Tool"): ["Mentioned"],
}


# ---------------------------------------------------------------------------
# Graph client
# ---------------------------------------------------------------------------


class OvermindGraph:
    """Wrapper around Graphiti with Kuzu backend for temporal memory."""

    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self.data_dir = get_data_dir(project_path)
        self.available: bool = False
        self._graphiti: object | None = None  # Graphiti instance, set in initialize()

    async def initialize(self) -> None:
        """Create driver, build indices. Call once after construction.

        If OPENAI_API_KEY is not set, logs a warning and sets
        ``self.available = False``. All other methods become no-ops.
        """
        openai_key = os.environ.get("OPENAI_API_KEY", "")

        if not openai_key:
            print(
                "[overmind] Graphiti unavailable: missing OPENAI_API_KEY",
                file=sys.stderr,
                flush=True,
            )
            self.available = False
            return

        # Lazy imports so the module loads even without graphiti installed
        from graphiti_core import Graphiti
        from graphiti_core.driver.kuzu_driver import KuzuDriver
        from graphiti_core.llm_client.config import LLMConfig
        from graphiti_core.llm_client.openai_client import OpenAIClient

        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(self.data_dir / "kuzu")

        import kuzu as _kuzu

        driver = KuzuDriver(db=db_path)
        # KuzuDriver doesn't set _database, but Graphiti.add_episode reads it
        # when a group_id is provided. Set it to the Kuzu default (empty string)
        # so that group_id comparison works correctly and avoids unnecessary clone().
        driver._database = ""  # type: ignore[attr-defined]

        # Graphiti's Kuzu search ops expect FTS indexes that setup_schema
        # doesn't create. Create them here.
        _conn = _kuzu.Connection(driver.db)
        try:
            _conn.execute(
                "CALL CREATE_FTS_INDEX('Entity', 'node_name_and_summary', ['name', 'summary'])"
            )
        except Exception:
            pass  # index may already exist
        try:
            _conn.execute(
                "CALL CREATE_FTS_INDEX('RelatesToNode_', 'edge_name_and_fact', ['name', 'fact'])"
            )
        except Exception:
            pass  # index may already exist
        try:
            _conn.execute(
                "CALL CREATE_FTS_INDEX('Episodic', 'episode_content', ['content', 'source', 'source_description'])"
            )
        except Exception:
            pass  # index may already exist
        try:
            _conn.execute(
                "CALL CREATE_FTS_INDEX('Community', 'community_name', ['name'])"
            )
        except Exception:
            pass  # index may already exist
        _conn.close()

        llm_client = OpenAIClient(
            config=LLMConfig(api_key=openai_key, model=GRAPHITI_MODEL),
            reasoning=GRAPHITI_REASONING_EFFORT,
        )

        graphiti = Graphiti(
            graph_driver=driver,
            llm_client=llm_client,
        )

        await graphiti.build_indices_and_constraints()

        self._graphiti = graphiti
        self.available = True
        print(
            f"[overmind] Graphiti initialized at {db_path}",
            file=sys.stderr,
            flush=True,
        )

    async def add_episode(
        self,
        session_id: str,
        turn_text: str,
        timestamp: str,
        source_description: str = "",
    ) -> None:
        """Add a conversation turn as an episode.

        Parameters
        ----------
        session_id:
            Groups episodes by conversation session.
        turn_text:
            The text content of the turn (e.g. "user: Fix the bug.").
        timestamp:
            ISO 8601 timestamp string.
        source_description:
            Optional description of the source.
        """
        if not self.available or self._graphiti is None:
            return

        from graphiti_core.nodes import EpisodeType

        try:
            ref_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ref_time = datetime.now(timezone.utc)

        try:
            await self._graphiti.add_episode(  # type: ignore[union-attr]
                name=f"turn-{session_id[:8]}",
                episode_body=turn_text,
                source_description=source_description or f"session {session_id}",
                reference_time=ref_time,
                source=EpisodeType.message,
                group_id=session_id,
                entity_types=ENTITY_TYPES,
                edge_types=EDGE_TYPES,
                edge_type_map=EDGE_TYPE_MAP,
            )
        except Exception as exc:
            print(
                f"[overmind] add_episode error: {exc}",
                file=sys.stderr,
                flush=True,
            )

    async def search_memory(
        self, query: str, num_results: int = 10
    ) -> list[dict[str, str | float | None]]:
        """Search the graph for relevant facts/entities.

        Returns a list of dicts with keys: ``fact``, ``created_at``,
        ``group_id``, ``valid_at``.
        """
        if not self.available or self._graphiti is None:
            return []

        try:
            edges = await self._graphiti.search(  # type: ignore[union-attr]
                query=query,
                num_results=num_results,
            )
        except Exception as exc:
            print(
                f"[overmind] search error: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return []

        results: list[dict[str, str | float | None]] = []
        for edge in edges:
            results.append({
                "fact": edge.fact,
                "created_at": edge.created_at.isoformat() if edge.created_at else None,
                "group_id": edge.group_id,
                "valid_at": edge.valid_at.isoformat() if edge.valid_at else None,
            })
        return results

    async def close(self) -> None:
        """Clean shutdown."""
        if self._graphiti is not None:
            try:
                await self._graphiti.close()  # type: ignore[union-attr]
            except Exception:
                pass
        self._graphiti = None
        self.available = False
