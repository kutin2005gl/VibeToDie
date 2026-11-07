import json

import pytest
from pydantic import ValidationError

from app import mandates
from app.core.llm import ModelConfigError
from app.core.llm.catalog import TIERS, Catalog, load_catalog

MODEL = {"dialect": "anthropic", "model": "claude-x", "api_key_ref": "env:K"}


def catalog(**overrides) -> Catalog:
    data = {
        "models": [{"id": "a", **MODEL}, {"id": "b", **MODEL, "model": "${MODEL_B}"}],
        "profiles": {"p": {"strong": "a", "standard": "a", "cheap": "b"}},
    }
    return Catalog.model_validate({**data, **overrides})


def test_tiers_match_the_mandate_tiers():
    assert TIERS == mandates.MODEL_TIERS


def test_shipped_catalog_maps_every_tier():
    shipped = load_catalog()
    assert set(shipped.profiles) == {"anthropic", "openai", "deepseek"}
    models = {tier: shipped.profiles["anthropic"][tier] for tier in TIERS}
    # Sonnet plans and reviews as well as Opus did on the Coordinator scenarios, for far less
    assert models == {"strong": "claude-sonnet", "standard": "claude-sonnet", "cheap": "claude-haiku"}


def test_select_applies_effort_and_expands_env(monkeypatch):
    c = catalog()
    selected = c.select("p", "strong", "high")
    assert (selected.model, selected.effort) == ("claude-x", "high")
    with pytest.raises(ModelConfigError, match="MODEL_B is not set"):
        c.select("p", "cheap")
    monkeypatch.setenv("MODEL_B", "claude-y")
    assert c.select("p", "cheap").model == "claude-y"
    with pytest.raises(ModelConfigError, match="unknown provider profile"):
        c.select("nope", "strong")


def test_configured_requires_keys_and_models(monkeypatch):
    monkeypatch.delenv("K", raising=False)
    monkeypatch.delenv("MODEL_B", raising=False)
    assert catalog().configured() == []
    monkeypatch.setenv("K", "sk")
    assert catalog().configured() == []  # MODEL_B still missing
    monkeypatch.setenv("MODEL_B", "claude-y")
    assert catalog().configured() == ["p"]


@pytest.mark.parametrize("profiles, match", [
    ({"p": {"strong": "a", "standard": "a"}}, "no model for tiers"),
    ({"p": {"strong": "a", "standard": "a", "cheap": "zz"}}, "unknown models"),
])
def test_catalog_validation(profiles, match):
    with pytest.raises(ValidationError, match=match):
        catalog(profiles=profiles)
    with pytest.raises(ValidationError, match="duplicate"):
        catalog(models=[{"id": "a", **MODEL}, {"id": "a", **MODEL}])


def test_load_catalog_from_env_path(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"models": [{"id": "a", **MODEL}],
                                "profiles": {"x": {t: "a" for t in TIERS}}}), encoding="utf-8")
    monkeypatch.setenv("AI_MODELS_FILE", str(path))
    assert list(load_catalog().profiles) == ["x"]
