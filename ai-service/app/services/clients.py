"""The model and router clients a request runs on, built once and reused across runs."""

import os
from functools import lru_cache

from fastapi import HTTPException

from app import mandates
from app.core import router
from app.core.llm import ModelClient, ModelConfig, ModelConfigError
from app.core.llm.catalog import load_catalog
from app.core.llm.fake import schema_answer_client
from app.core.llm.registry import build_client

CATALOG = load_catalog()
FAKE = "fake"


def fake_allowed() -> bool:
    return os.environ.get("AI_ALLOW_FAKE") == "1"


@lru_cache(maxsize=32)
def client_for(config: ModelConfig) -> ModelClient:
    """One client per model config, so HTTP connections are reused across runs."""
    return build_client(config)


@lru_cache(maxsize=1)
def jev_client() -> router.Jev:
    """One Jev client per process, so HTTP connections are reused across runs."""
    return router.jev_from_env()


def check_provider(provider: str) -> None:
    """Reject an unusable provider before anything is spent on the request."""
    if provider == FAKE:
        if not fake_allowed():
            raise HTTPException(status_code=503, detail="fake provider is disabled (set AI_ALLOW_FAKE=1)")
    elif provider not in CATALOG.profiles:
        raise HTTPException(status_code=422, detail=f"unknown provider {provider!r}")


def model_for(provider: str, mandate: mandates.Mandate) -> tuple[ModelClient, str]:
    """The client and model name `mandate` runs on for `provider`, picked by its tier and effort."""
    check_provider(provider)
    if provider == FAKE:
        return schema_answer_client(mandate.output_schema), FAKE
    try:
        config = CATALOG.select(provider, mandate.model_tier, mandate.effort)  # type: ignore[arg-type]
        return client_for(config), config.model
    except ModelConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def config_for(provider: str, mandate: mandates.Mandate) -> ModelConfig | None:
    """The config `mandate` runs on for `provider`, for its prices; None for the fake provider."""
    if provider == FAKE:
        return None
    try:
        return CATALOG.select(provider, mandate.model_tier, mandate.effort)  # type: ignore[arg-type]
    except ModelConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
