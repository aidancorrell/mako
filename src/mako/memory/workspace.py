"""Workspace memory — reads personality and memory files from the workspace."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Files loaded on startup, in order
PERSONALITY_FILES = ["SOUL.md", "IDENTITY.md"]
MEMORY_FILES = ["MEMORY.md"]


def load_personality(workspace_path: Path) -> str:
    """Load personality files (SOUL.md, IDENTITY.md) from workspace."""
    parts: list[str] = []
    for filename in PERSONALITY_FILES:
        path = workspace_path / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
                logger.info("Loaded personality file: %s", filename)
    return "\n\n".join(parts)


def load_memory(workspace_path: Path) -> str:
    """Load memory files (MEMORY.md) from workspace."""
    parts: list[str] = []
    for filename in MEMORY_FILES:
        path = workspace_path / filename
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
                logger.info("Loaded memory file: %s", filename)

    # Also load any files in workspace/memory/
    memory_dir = workspace_path / "memory"
    if memory_dir.is_dir():
        for md_file in sorted(memory_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"## {md_file.stem}\n\n{content}")
                logger.info("Loaded memory file: memory/%s", md_file.name)

    return "\n\n".join(parts)
