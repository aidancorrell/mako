"""Retry utility for transient tool failures."""

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Exception types that indicate transient failures worth retrying
TRANSIENT_EXCEPTIONS = (TimeoutError, OSError, ConnectionError)


async def retry_with_backoff(
    fn: Callable[..., Awaitable[T]],
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    retryable: tuple[type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    **kwargs,
) -> T:
    """Call an async function with exponential backoff on transient errors.

    Args:
        fn: The async function to call.
        max_retries: Number of retries after the first failure (total attempts = max_retries + 1).
        base_delay: Base delay in seconds (doubled each retry, with jitter).
        retryable: Tuple of exception types that trigger a retry.
    """
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable as e:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning(
                "Transient error (%s), retrying in %.1fs (attempt %d/%d)",
                e, delay, attempt + 1, max_retries,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Unreachable")  # pragma: no cover
