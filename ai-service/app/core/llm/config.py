"""Model configuration as data: the business plugs in any market model by config, not code.

A config names an API dialect, the model, and a reference to its API key. Keys never live in a
config object: `api_key_ref` is resolved when a client is built (`env:NAME` now; a `db:` scheme
when the Director's admin dashboard stores keys). Never log a resolved key.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.llm.types import Usage

# Most market models speak one of these three APIs:
# - anthropic: Claude (API, Bedrock/Vertex via base_url when supported)
# - openai_responses: OpenAI GPT / o-series through the Responses API
# - openai_compat: Chat Completions shape (DeepSeek, Qwen, Mistral, Groq, OpenRouter, Gemini's
#   OpenAI endpoint, self-hosted vLLM/Ollama)
Dialect = Literal["anthropic", "openai_responses", "openai_compat"]

_Positive = Annotated[float, Field(gt=0)]


class ModelConfigError(ValueError):
    """A config is unusable: unknown key scheme, missing key, or a model that cannot run the loop."""


class Capabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # The agent loop and `final_answer` need native tool calling; a config without it is rejected
    tool_calling: bool = True
    parallel_tool_calls: bool = True
    # False for models that reject an effort / reasoning setting: the dialect then omits it
    reasoning_effort: bool = True
    # openai_compat only: send `reasoning_content` back in history. Some providers require it
    # during tool loops, others reject it, so it is off unless the provider documents it
    send_reasoning_back: bool = False


class PeakPricing(BaseModel):
    """Prices a provider charges in its busy hours instead of the config's own prices."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    price_input_per_mtok: Annotated[float, Field(ge=0)]
    price_output_per_mtok: Annotated[float, Field(ge=0)]
    # Local time of the hours below, as an offset: no time zone database is needed
    utc_offset_hours: Annotated[int, Field(ge=-12, le=14)] = 0
    # Tuples, not lists: configs are hashed to cache one client per config (clients.client_for)
    # 0 is Monday
    weekdays: tuple[Annotated[int, Field(ge=0, le=6)], ...] = tuple(range(7))
    # "08:00-11:00": start included, end excluded
    hours: tuple[Annotated[str, Field(pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")], ...]

    def covers(self, at: datetime) -> bool:
        local = at.astimezone(timezone(timedelta(hours=self.utc_offset_hours)))
        if local.weekday() not in self.weekdays:
            return False
        now = local.strftime("%H:%M")
        return any(start <= now < end for start, end in (h.split("-") for h in self.hours))


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Name the business refers to, e.g. "claude-main"; model tiers map onto these ids
    id: Annotated[str, Field(min_length=1)]
    dialect: Dialect
    model: Annotated[str, Field(min_length=1)]
    base_url: str | None = None
    # Where the API key comes from: "env:ANTHROPIC_API_KEY" (later "db:<key id>")
    api_key_ref: Annotated[str, Field(pattern=r"^[a-z]+:.+$")]
    capabilities: Capabilities = Field(default_factory=Capabilities)
    max_output_tokens: Annotated[int, Field(gt=0)] = 16_000
    # Passed through to the provider as-is: values differ per dialect (Claude: low..max;
    # OpenAI: none/minimal..xhigh). The provider rejects an unknown value with a clear 400
    effort: str | None = None
    # anthropic only: server-side refusal fallback ("default" routes by refusal category).
    # Not every Claude model or platform accepts it, so it is opt-in per config
    fallbacks: Literal["default"] | None = None
    connect_timeout: _Positive = 10.0
    # Longest silence allowed while waiting for the response or between stream events
    read_timeout: _Positive = 120.0
    max_attempts: Annotated[int, Field(ge=1)] = 4
    backoff_base: _Positive = 0.5
    backoff_max: _Positive = 8.0
    # USD per million tokens, for the usage and cost statistics; None when unknown
    price_input_per_mtok: Annotated[float, Field(ge=0)] | None = None
    price_output_per_mtok: Annotated[float, Field(ge=0)] | None = None
    peak: PeakPricing | None = None

    def cost(self, usage: Usage, at: datetime) -> float | None:
        """USD for `usage` spent at `at`; None when the prices are unknown."""
        prices = self.peak if self.peak is not None and self.peak.covers(at) else self
        if prices.price_input_per_mtok is None or prices.price_output_per_mtok is None:
            return None
        return (usage.prompt_tokens * prices.price_input_per_mtok
                + usage.completion_tokens * prices.price_output_per_mtok) / 1_000_000

    @model_validator(mode="after")
    def _check(self) -> "ModelConfig":
        if not self.capabilities.tool_calling:
            raise ValueError(
                f"model config {self.id!r}: the agent loop needs native tool calling"
            )
        if self.fallbacks is not None and self.dialect != "anthropic":
            raise ValueError(f"model config {self.id!r}: fallbacks is an anthropic-only option")
        return self


def resolve_api_key(ref: str) -> str:
    """Read the key `ref` points to. The error never contains the key itself."""
    scheme, _, name = ref.partition(":")
    if scheme == "env":
        value = os.environ.get(name, "")
        if not value:
            raise ModelConfigError(f"API key variable {name} is not set")
        return value
    raise ModelConfigError(f"unsupported api_key_ref scheme {scheme!r} (supported: env)")
