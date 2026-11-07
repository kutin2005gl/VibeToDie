import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.llm import LLMStreamInterrupted, LLMUnavailableError, ModelConfig, ModelConfigError, Usage
from app.core.llm.config import resolve_api_key
from app.core.llm.dialects.anthropic_messages import AnthropicClient
from app.core.llm.dialects.openai_compat import OpenAICompatClient
from app.core.llm.dialects.openai_responses import OpenAIResponsesClient
from app.core.llm.fake import completion
from app.core.llm.registry import build_client
from app.core.llm.retry import backoff, stream_with_retries


def config(**overrides) -> ModelConfig:
    values = {"id": "m", "dialect": "anthropic", "model": "claude-opus-5-5", "api_key_ref": "env:TEST_KEY"}
    return ModelConfig(**{**values, **overrides})


def test_config_rejects_models_without_tool_calling_and_misplaced_options():
    with pytest.raises(ValidationError, match="tool calling"):
        config(capabilities={"tool_calling": False})
    with pytest.raises(ValidationError, match="anthropic-only"):
        config(dialect="openai_compat", fallbacks="default")
    with pytest.raises(ValidationError):
        config(api_key_ref="sk-raw-key-not-a-ref")
    with pytest.raises(ValidationError):
        config(unknown_field=1)


def test_cost_uses_the_peak_prices_in_the_local_peak_hours():
    peak = {"price_input_per_mtok": 2.0, "price_output_per_mtok": 4.0, "utc_offset_hours": 7,
            "weekdays": [0, 1, 2, 3, 4], "hours": ["08:00-11:00", "13:00-17:00"]}
    priced = config(price_input_per_mtok=1.0, price_output_per_mtok=2.0, peak=peak)
    usage = Usage(1_000_000, 500_000)
    vietnam = timezone(timedelta(hours=7))
    # 2026-10-26 is a Monday
    assert priced.cost(usage, datetime(2026, 10, 26, 10, tzinfo=vietnam)) == 4.0
    assert priced.cost(usage, datetime(2026, 10, 26, 12, tzinfo=vietnam)) == 2.0
    assert priced.cost(usage, datetime(2026, 10, 26, 11, tzinfo=vietnam)) == 2.0  # the end is excluded
    assert priced.cost(usage, datetime(2026, 10, 31, 9, tzinfo=vietnam)) == 2.0  # Saturday
    # 02:00 UTC is 09:00 in Vietnam
    assert priced.cost(usage, datetime(2026, 10, 26, 2, tzinfo=timezone.utc)) == 4.0
    assert config().cost(usage, datetime(2026, 10, 26, 10, tzinfo=vietnam)) is None
    hash(priced)  # one client is cached per config, so a config with peak prices must stay hashable
    with pytest.raises(ValidationError):
        config(peak={**peak, "hours": ["8h-11h"]})


def test_api_key_is_resolved_from_env_and_never_echoed(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-secret")
    assert resolve_api_key("env:TEST_KEY") == "sk-secret"
    monkeypatch.delenv("TEST_KEY")
    with pytest.raises(ModelConfigError, match="TEST_KEY is not set"):
        resolve_api_key("env:TEST_KEY")
    with pytest.raises(ModelConfigError, match="scheme 'db'"):
        resolve_api_key("db:key-1")


@pytest.mark.parametrize(
    "dialect, client_type",
    [("anthropic", AnthropicClient), ("openai_responses", OpenAIResponsesClient), ("openai_compat", OpenAICompatClient)],
)
def test_registry_builds_the_client_for_each_dialect(monkeypatch, dialect, client_type):
    monkeypatch.setenv("TEST_KEY", "sk-secret")
    assert isinstance(build_client(config(dialect=dialect)), client_type)


def test_registry_fails_fast_without_a_key(monkeypatch):
    monkeypatch.delenv("TEST_KEY", raising=False)
    with pytest.raises(ModelConfigError):
        build_client(config())


class SdkError(Exception):
    pass


async def collect(stream):
    return [event async for event in stream]


def retrying(attempt, classify=lambda exc: None, **overrides):
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    stream = stream_with_retries(
        attempt, sdk_errors=(SdkError,), classify=classify, config=config(**overrides),
        sleep=sleep, rand=lambda: 1.0,
    )
    return stream, slept


def test_retry_until_success_with_backoff():
    async def attempt(number):
        if number < 3:
            raise SdkError("503")
        yield completion(content="ok")

    stream, slept = retrying(attempt)
    events = asyncio.run(collect(stream))
    assert events[-1].message.content == "ok"
    assert slept == [0.5, 1.0]


def test_retry_gives_up_after_max_attempts():
    async def attempt(number):
        raise SdkError("503")
        yield

    stream, _ = retrying(attempt, max_attempts=2)
    with pytest.raises(LLMUnavailableError, match="2 attempts"):
        asyncio.run(collect(stream))


def test_fatal_errors_are_not_retried():
    calls = []

    async def attempt(number):
        calls.append(number)
        raise SdkError("401")
        yield

    stream, _ = retrying(attempt, classify=lambda exc: ModelConfigError("bad key"))
    with pytest.raises(ModelConfigError):
        asyncio.run(collect(stream))
    assert calls == [1]


def test_no_silent_retry_after_output_was_delivered():
    async def attempt(number):
        yield completion(content="partial")
        raise SdkError("connection reset")

    stream, _ = retrying(attempt)
    with pytest.raises(LLMStreamInterrupted):
        asyncio.run(collect(stream))


def test_backoff_is_capped():
    assert backoff(config(), 10, lambda: 1.0) == 8.0
