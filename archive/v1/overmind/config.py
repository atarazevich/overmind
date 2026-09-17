"""Configuration constants for Overmind."""

import hashlib
import os
from pathlib import Path

# Polling
POLL_INTERVAL_SECONDS: float = 2.0

# Debounce
QUIET_PERIOD_SECONDS: float = 10.0
MIN_TURNS_BEFORE_EVAL: int = 3
MAX_TURNS_FORCE_EVAL: int = 8

# Session liveness — exit if no new turns for this long
INACTIVITY_TIMEOUT_SECONDS: float = float(os.environ.get("OVERMIND_TIMEOUT", "300"))  # 5 min
PARENT_CHECK_INTERVAL: int = 10  # check parent every N poll cycles

# Context window for evaluation
MAX_CONTEXT_TURNS: int = 15

# No-repeat tracking: compare first N chars of emitted thought
DEDUP_PREFIX_LENGTH: int = 50

# Paths
LOG_DIR: Path = Path(__file__).resolve().parent.parent / "logs"
PROMPTS_DIR: Path = Path(__file__).resolve().parent.parent / "prompts"
ADHERENCE_PROMPT: Path = PROMPTS_DIR / "adherence.md"
RECALL_PROMPT: Path = PROMPTS_DIR / "recall.md"
DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"

# Claude CLI (for adherence/recall evaluation)
CLAUDE_CMD: list[str] = ["claude", "-p", "--bare", "--model", "sonnet"]

# Graphiti LLM (for entity extraction, summarization)
GRAPHITI_MODEL: str = os.environ.get("GRAPHITI_MODEL", "gpt-5.4-mini")
GRAPHITI_REASONING_EFFORT: str = os.environ.get("GRAPHITI_REASONING_EFFORT", "low")

# Claude Code project directory
CLAUDE_PROJECTS_DIR: Path = Path.home() / ".claude" / "projects"


def encode_project_path(path: str) -> str:
    """Encode a project path the way Claude Code does it.

    Replaces ``/`` with ``-`` and ``.`` with ``-``.
    ``/Users/alex/Projects/myapp`` becomes ``-Users-alex-Projects-myapp``.
    ``/Users/alex/.claude`` becomes ``-Users-alex--claude``.
    """
    return path.replace("/", "-").replace(".", "-")


def find_project_dir(project_path: str) -> Path | None:
    """Find the Claude Code project directory for a given project path.

    Instead of encoding the path and hoping it matches, search the
    ``~/.claude/projects/`` directory for one whose name ends with the
    encoded tail of the project path.  This handles any encoding scheme.

    Returns the matching directory Path, or None if not found.
    """
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return None

    # Build a suffix from the last two path components (e.g. "Projects-myapp")
    parts = Path(project_path).parts
    if len(parts) >= 2:
        suffix = "-".join(parts[-2:])
    elif parts:
        suffix = parts[-1]
    else:
        return None

    for candidate in CLAUDE_PROJECTS_DIR.iterdir():
        if candidate.is_dir() and candidate.name.endswith(suffix):
            return candidate

    # Fallback: try exact encoding
    encoded = encode_project_path(project_path)
    exact = CLAUDE_PROJECTS_DIR / encoded
    if exact.is_dir():
        return exact

    return None


def get_project_hash(project_path: str) -> str:
    """Return a short hash of the project path for data directory naming."""
    return hashlib.sha256(project_path.encode()).hexdigest()[:8]


def get_data_dir(project_path: str) -> Path:
    """Return the Kuzu data directory for a given project path."""
    return DATA_DIR / get_project_hash(project_path)
