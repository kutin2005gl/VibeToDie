"""Admin view of the agents: what each mandate file says, with the model every provider profile gives its tier."""

from typing import Any

from app import mandates
from app.services.clients import CATALOG


def listing() -> list[dict[str, Any]]:
    out = []
    for name in mandates.names():
        m = mandates.load(name)
        out.append({
            "name": m.name,
            "description": m.description,
            "tools": list(m.tools),
            "includes": list(m.includes),
            "departments": list(m.departments),
            "model_tier": m.model_tier,
            "effort": m.effort,
            # Model config id per provider profile (e.g. {"anthropic": "claude-sonnet"}); ids, so a model not chosen yet never fails here
            "models": {profile: tiers[m.model_tier] for profile, tiers in CATALOG.profiles.items()},
            "prompt": m.system_prompt,
        })
    return out
