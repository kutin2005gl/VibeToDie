"""Model catalog: which model configs exist, and which one each (provider profile, tier) uses.

Loaded from a JSON file (`app/models.json`, or `AI_MODELS_FILE`). It holds no keys, only
`api_key_ref`s. `${NAME}` in `model` / `base_url` is read from the environment when a config is
selected, so a provider whose model is not chosen yet (OPENAI_MODEL, gate B-01) fails only when
used. The Director's admin dashboard will replace the file later.
"""

import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.llm.config import ModelConfig, ModelConfigError, resolve_api_key

Tier = Literal["strong", "standard", "cheap"]
TIERS: tuple[Tier, ...] = ("strong", "standard", "cheap")
DEFAULT_FILE = Path(__file__).resolve().parents[2] / "models.json"

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    models: tuple[ModelConfig, ...]
    # Provider profile → model config id per tier, e.g. {"anthropic": {"strong": "claude-opus"}}
    profiles: dict[str, dict[Tier, str]]

    @model_validator(mode="after")
    def _check(self) -> "Catalog":
        ids = [model.id for model in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate model ids: {sorted(ids)}")
        for name, tiers in self.profiles.items():
            missing = [tier for tier in TIERS if tier not in tiers]
            if missing:
                raise ValueError(f"profile {name!r} has no model for tiers {missing}")
            unknown = sorted(set(tiers.values()) - set(ids))
            if unknown:
                raise ValueError(f"profile {name!r} refers to unknown models {unknown}")
        return self

    def select(self, profile: str, tier: Tier, effort: str | None = None) -> ModelConfig:
        """The config for `tier` in `profile`, with env vars expanded and `effort` applied."""
        if profile not in self.profiles:
            raise ModelConfigError(f"unknown provider profile {profile!r}")
        config = next(m for m in self.models if m.id == self.profiles[profile][tier])
        update: dict[str, object] = {"model": _expand(config.model)}
        if config.base_url:
            update["base_url"] = _expand(config.base_url)
        if effort:
            update["effort"] = effort
        return config.model_copy(update=update)

    def configured(self) -> list[str]:
        """Profiles whose every tier resolves to a model name and an API key."""
        ready = []
        for profile in self.profiles:
            try:
                for tier in TIERS:
                    resolve_api_key(self.select(profile, tier).api_key_ref)
            except ModelConfigError:
                continue
            ready.append(profile)
        return ready


def load_catalog(path: str | Path | None = None) -> Catalog:
    source = Path(path or os.environ.get("AI_MODELS_FILE") or DEFAULT_FILE)
    return Catalog.model_validate_json(source.read_text(encoding="utf-8"))


def _expand(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        found = os.environ.get(name, "")
        if not found:
            raise ModelConfigError(f"{name} is not set")
        return found

    return _VAR.sub(replace, value)
