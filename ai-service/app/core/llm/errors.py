"""LLM client errors, classified by whether a retry can help (ported from ref/core).

Each dialect maps its SDK's exceptions onto these, so the loop never depends on a provider.
"""


class LLMError(Exception):
    """Base class for every error raised by a model client."""


class LLMRequestError(LLMError):
    """The provider rejected the request; retrying the same request cannot succeed."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMAuthError(LLMRequestError):
    """401/403: the API key is wrong, expired or revoked. Never retried; an admin must fix it.

    The business swaps keys itself, so this is an expected operational error, not a bug.
    """


class LLMRefusedError(LLMError):
    """The model (or the provider's safety filter) declined the request; retrying will not help."""


class LLMUnavailableError(LLMError):
    """Every attempt failed with a retryable error; the cause is the last failure."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class LLMStreamInterrupted(LLMError):
    """The stream broke after events were already delivered, so it is not retried silently."""
