"""Workspace memory — reads personality and memory files from the workspace."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Files loaded on startup, in order
PERSONALITY_FILES = ["SOUL.md", "IDENTITY.md"]
MEMORY_FILES = ["MEMORY.md"]

# Size limits to prevent context window exhaustion
MAX_FILE_SIZE = 50_000  # 50KB per file
MAX_TOTAL_SIZE = 200_000  # 200KB total across all memory/personality


def _read_capped(path: Path, label: str) -> str:
    """Read a file with size cap. Returns empty string if too large."""
    size = path.stat().st_size
    if size > MAX_FILE_SIZE:
        logger.warning("Skipping %s: %d bytes exceeds %d byte limit", label, size, MAX_FILE_SIZE)
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_personality(workspace_path: Path) -> str:
    """Load personality files (SOUL.md, IDENTITY.md) from workspace."""
    parts: list[str] = []
    for filename in PERSONALITY_FILES:
        path = workspace_path / filename
        if path.exists():
            content = _read_capped(path, filename)
            if content:
                parts.append(content)
                logger.info("Loaded personality file: %s", filename)
    return "\n\n".join(parts)


def load_memory(workspace_path: Path) -> str:
    """Load memory files (MEMORY.md) from workspace."""
    parts: list[str] = []
    total_size = 0

    for filename in MEMORY_FILES:
        path = workspace_path / filename
        if path.exists():
            content = _read_capped(path, filename)
            if content:
                total_size += len(content)
                if total_size > MAX_TOTAL_SIZE:
                    logger.warning("Memory total size limit reached, skipping remaining files")
                    break
                parts.append(content)
                logger.info("Loaded memory file: %s", filename)

    # Also load any files in workspace/memory/
    memory_dir = workspace_path / "memory"
    if memory_dir.is_dir():
        for md_file in sorted(memory_dir.glob("*.md")):
            content = _read_capped(md_file, f"memory/{md_file.name}")
            if content:
                total_size += len(content)
                if total_size > MAX_TOTAL_SIZE:
                    logger.warning("Memory total size limit reached, skipping remaining files")
                    break
                parts.append(f"## {md_file.stem}\n\n{content}")
                logger.info("Loaded memory file: memory/%s", md_file.name)

    return "\n\n".join(parts)
