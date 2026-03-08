"""Shared utilities for message channels."""


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks that fit a platform's limit.

    Tries to split on newlines first, then on spaces, then hard-cuts.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a newline
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1 or split_at < max_length // 2:
            # Try to split at a space
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1 or split_at < max_length // 2:
            # Hard cut
            split_at = max_length

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()

    return chunks
