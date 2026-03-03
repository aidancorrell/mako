"""Workspace file tools — read/write files within the workspace only.

All paths are validated by SecurityGuard to stay within the workspace jail.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Read File ---

READ_FILE_NAME = "read_file"
READ_FILE_DESCRIPTION = (
    "Read a file from the workspace. Paths are relative to the workspace root. "
    "Use this to read SOUL.md, MEMORY.md, notes, or any workspace file."
)
READ_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File path relative to workspace (e.g. 'SOUL.md', 'memory/notes.md')",
        },
    },
    "required": ["path"],
}

# --- Write File ---

WRITE_FILE_NAME = "write_file"
WRITE_FILE_DESCRIPTION = (
    "Write content to a file in the workspace. Creates parent directories if needed. "
    "Paths are relative to the workspace root."
)
WRITE_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "File path relative to workspace (e.g. 'memory/notes.md')",
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file",
        },
    },
    "required": ["path", "content"],
}


def _make_read_handler(workspace_path: Path):
    async def read_file(path: str) -> str:
        """Read a file from the workspace."""
        # SecurityGuard.validate_path is called by the registry before this runs
        target = (workspace_path / path).resolve()
        if not target.exists():
            return f"Error: File not found: {path}"
        if not target.is_file():
            return f"Error: Not a file: {path}"
        return target.read_text(encoding="utf-8")

    return read_file


def _make_write_handler(workspace_path: Path):
    async def write_file(path: str, content: str) -> str:
        """Write content to a file in the workspace."""
        target = (workspace_path / path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {path}"

    return write_file


def register_workspace_tools(registry, workspace_path: Path) -> None:
    """Register read_file and write_file tools."""
    registry.register(
        name=READ_FILE_NAME,
        description=READ_FILE_DESCRIPTION,
        parameters=READ_FILE_PARAMETERS,
        handler=_make_read_handler(workspace_path),
    )
    registry.register(
        name=WRITE_FILE_NAME,
        description=WRITE_FILE_DESCRIPTION,
        parameters=WRITE_FILE_PARAMETERS,
        handler=_make_write_handler(workspace_path),
    )
