"""Batch ingest past Claude Code conversations into Graphiti.

Usage::

    python -m overmind.ingest ~/Projects/my-project
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from overmind.config import find_project_dir
from overmind.filter import parse_jsonl
from overmind.graphiti_client import OvermindGraph


async def _ingest(project_path: str) -> None:
    """Ingest all JSONL conversations for a project into Graphiti."""
    jsonl_dir = find_project_dir(project_path)

    if jsonl_dir is None or not jsonl_dir.is_dir():
        print(
            f"Error: no Claude Code project directory found for {project_path}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    jsonl_files = sorted(jsonl_dir.glob("*.jsonl"))
    if not jsonl_files:
        print(f"No JSONL files found in {jsonl_dir}", file=sys.stderr)
        raise SystemExit(1)

    graph = OvermindGraph(project_path)
    await graph.initialize()

    if not graph.available:
        print(
            "Error: Graphiti not available (check API keys)", file=sys.stderr
        )
        raise SystemExit(1)

    total_sessions = 0
    total_turns = 0

    for jsonl_file in jsonl_files:
        session_id = jsonl_file.stem
        turns = parse_jsonl(str(jsonl_file))

        if not turns:
            continue

        for turn in turns:
            await graph.add_episode(
                session_id=session_id,
                turn_text=f"{turn.role}: {turn.text}",
                timestamp=turn.timestamp,
                source_description=f"session {session_id}",
            )

        total_turns += len(turns)
        total_sessions += 1
        print(
            f"Ingested session {session_id}: {len(turns)} turns",
            file=sys.stderr,
            flush=True,
        )

    await graph.close()
    print(
        f"\nDone. Sessions: {total_sessions}, Turns: {total_turns}",
        file=sys.stderr,
        flush=True,
    )


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) != 2:
        print(f"Usage: python -m overmind.ingest <project-path>", file=sys.stderr)
        raise SystemExit(1)

    project_path = str(Path(sys.argv[1]).resolve())
    asyncio.run(_ingest(project_path))


if __name__ == "__main__":
    main()
