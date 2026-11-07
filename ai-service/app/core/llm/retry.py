"""Retry policy shared by every dialect (ported from ref/core/llm/client.py).

The SDKs' own retries are switched off so attempts are counted in one place. A failure is retried
only while no event has been delivered: once output reached the caller, a silent retry would
duplicate it, so the failure surfaces as `LLMStreamInterrupted` instead.
"""

from collections.abc import AsyncIterator, Awaitable, Callable

from app.core.llm.config import ModelConfig
from app.core.llm.errors import LLMError, LLMStreamInterrupted, LLMUnavailableError
from app.core.llm.types import StreamEvent

# Maps an SDK exception to a fatal error, or None when a retry may help
Classify = Callable[[Exception], LLMError | None]


async def stream_with_retries(
    attempt: Callable[[int], AsyncIterator[StreamEvent]],
    *,
    sdk_errors: tuple[type[Exception], ...],
    classify: Classify,
    config: ModelConfig,
    sleep: Callable[[float], Awaitable[None]],
    rand: Callable[[], float],
) -> AsyncIterator[StreamEvent]:
    """Run `attempt(n)` until it completes, retrying retryable SDK errors before any output."""
    number = 0
    while True:
        number += 1
        delivered = False
        try:
            async for event in attempt(number):
                delivered = True
                yield event
            return
        except sdk_errors as exc:
            if delivered:
                raise LLMStreamInterrupted(f"stream broke after output: {exc}") from exc
            fatal = classify(exc)
            if fatal is not None:
                raise fatal from exc
            if number >= config.max_attempts:
                raise LLMUnavailableError(
                    f"gave up after {number} attempts: {exc}", attempts=number
                ) from exc
            await sleep(backoff(config, number, rand))


def backoff(config: ModelConfig, attempt: int, rand: Callable[[], float]) -> float:
    """Full jitter: a uniform delay up to an exponentially growing cap."""
    cap = min(config.backoff_max, config.backoff_base * 2 ** (attempt - 1))
    return cap * rand()
