"""Admin report: what the runs of the last N days did and cost, summed from their saved traces."""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any

# Days are cut in staff time (Vietnam, no daylight saving)
LOCAL = timezone(timedelta(hours=7))
MAX_DAYS = 366
TOP_TOOLS = 10


def window_start(days: int, now: datetime | None = None) -> datetime:
    """Midnight (staff time) of the first of the last `days` days, today included."""
    today = (now or datetime.now(timezone.utc)).astimezone(LOCAL).date()
    return datetime.combine(today - timedelta(days=days - 1), time.min, tzinfo=LOCAL)


def _usage() -> dict[str, Any]:
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0}


def _add_call(total: dict[str, Any], event: dict[str, Any]) -> None:
    total["input_tokens"] += event.get("prompt_tokens") or 0
    total["output_tokens"] += event.get("completion_tokens") or 0
    if event.get("cost_usd") is None:
        total["unpriced_calls"] += 1
    else:
        total["cost_usd"] += event["cost_usd"]


def build(runs: list[dict[str, Any]], days: int, now: datetime | None = None) -> dict[str, Any]:
    """`runs` are the runs saved since `window_start(days)`, each with its `events` (the message-like trace events)."""
    start = window_start(days, now)
    labels = [(start + timedelta(days=i)).strftime("%m-%d") for i in range(days)]
    per_day = {d: {"day": d, "runs": 0, "events": 0, "by_agent": defaultdict(int), "by_type": defaultdict(int),
                   **_usage()} for d in labels}
    agents: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    tools: dict[str, int] = defaultdict(int)
    rooms: dict[int, dict[str, Any]] = {}
    totals = {"llm_calls": 0, "tool_calls": 0, "errors": 0, **_usage()}

    for run in runs:
        started = run["started_at"].astimezone(LOCAL)
        day = per_day.get(started.strftime("%m-%d"))
        if day is None:
            continue
        day["runs"] += 1
        for k in ("input_tokens", "output_tokens", "cost_usd", "unpriced_calls"):
            day[k] += run[k]
            totals[k] += run[k]
        room = rooms.setdefault(run["session_id"], {"id": run["session_id"], "title": run["title"], "runs": 0,
                                                    "last": run["started_at"], **_usage()})
        room["runs"] += 1
        room["last"] = max(room["last"], run["started_at"])
        for k in ("input_tokens", "output_tokens", "cost_usd", "unpriced_calls"):
            room[k] += run[k]

        for e in run["events"]:
            kind, agent = e["event"], e.get("agent")
            day["events"] += 1
            day["by_type"][kind] += 1
            if agent:
                day["by_agent"][agent] += 1
                a = agents.setdefault(agent, {"agent": agent, "sessions": set(), "llm_calls": 0, "tool_calls": 0,
                                              "errors": 0, "last": run["started_at"], **_usage()})
                a["sessions"].add(run["session_id"])
                a["last"] = max(a["last"], run["started_at"])
            if kind == "llm_call":
                totals["llm_calls"] += 1
                m = models.setdefault(e["model"], {"model": e["model"], "calls": 0, **_usage()})
                m["calls"] += 1
                _add_call(m, e)
                if agent:
                    a["llm_calls"] += 1
                    _add_call(a, e)
            elif kind == "tool_call":
                totals["tool_calls"] += 1
                tools[e["name"]] += 1
                if agent:
                    a["tool_calls"] += 1
            elif (kind == "tool_result" and e.get("is_error")) or kind == "run_failed":
                totals["errors"] += 1
                if agent:
                    a["errors"] += 1

    by_cost = lambda row: -row["cost_usd"]  # noqa: E731
    return {
        "days": days,
        "stats": {**totals, "agents": len(agents), "rooms": len(rooms), "runs": sum(r["runs"] for r in rooms.values()),
                  "models": len(models)},
        "per_day": [{**d, "by_agent": dict(d["by_agent"]), "by_type": dict(d["by_type"])} for d in per_day.values()],
        "per_agent": sorted(({**a, "sessions": len(a["sessions"])} for a in agents.values()), key=by_cost),
        "per_model": sorted(models.values(), key=by_cost),
        "per_room": sorted(rooms.values(), key=by_cost),
        "top_tools": [{"name": n, "count": c} for n, c in sorted(tools.items(), key=lambda t: -t[1])[:TOP_TOOLS]],
    }
