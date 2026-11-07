"""Builds the model client for a config. A run is pinned to the client it starts with."""

from typing import Any

from app.core.llm.config import ModelConfig
from app.core.llm.dialects.anthropic_messages import AnthropicClient
from app.core.llm.dialects.openai_compat import OpenAICompatClient
from app.core.llm.dialects.openai_responses import OpenAIResponsesClient
from app.core.llm.types import ModelClient

_DIALECTS: dict[str, type[AnthropicClient | OpenAIResponsesClient | OpenAICompatClient]] = {
    "anthropic": AnthropicClient,
    "openai_responses": OpenAIResponsesClient,
    "openai_compat": OpenAICompatClient,
}


def build_client(config: ModelConfig, *, http_client: Any = None) -> ModelClient:
    """Raises `ModelConfigError` when the API key cannot be resolved."""
    return _DIALECTS[config.dialect](config, http_client=http_client)
