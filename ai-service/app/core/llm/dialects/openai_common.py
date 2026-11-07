"""What the two OpenAI-SDK dialects share: client construction and error classification."""

from typing import Any

import openai

from app.core.llm.config import ModelConfig, resolve_api_key
from app.core.llm.errors import LLMAuthError, LLMError, LLMRequestError


def make_client(config: ModelConfig, http_client: Any = None) -> openai.AsyncOpenAI:
    # The SDK's own retries are off: attempts are counted in `stream_with_retries`
    return openai.AsyncOpenAI(
        api_key=resolve_api_key(config.api_key_ref),
        base_url=config.base_url,
        max_retries=0,
        timeout=openai.Timeout(config.read_timeout, connect=config.connect_timeout),
        http_client=http_client,
    )


def classify(exc: Exception) -> LLMError | None:
    """Fatal error for `exc`, or None when a retry may help (429, 5xx, network)."""
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LLMAuthError(f"openai {exc.status_code}: {exc.message}", exc.status_code)
    if isinstance(exc, openai.APIConnectionError):
        return None
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code == 429 or exc.status_code >= 500:
            return None
        return LLMRequestError(f"openai {exc.status_code}: {exc.message}", exc.status_code)
    return LLMRequestError(f"openai error: {exc}")
