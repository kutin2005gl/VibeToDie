"""Run the end-to-end cases through `POST /run` and write one graded row per case and rep.

    cd ai
    python -m evals.e2e.run --variant baseline [--reps 2] [--only t01,t06]
    python -m evals.e2e.run --variant dry --dry-run          # no model, no Jev, no spend

Rows go to `<repo>/.claude/hillclimb/nexus-e2e/<variant>/results.jsonl` in the layout the
single-agent-loop scripts read (compare.py, estimate.py, chain_coverage.py), with a
`meta.json` beside it recording how the run was made.

The clock is pinned to 2026-10-20 so return windows do not drift between variants. A case
passes when every `must` group has a match, no `must_not` pattern matches, and the request
queued no action. Patterns run on the staff-facing `output`, lowercased with Vietnamese
diacritics removed and digit separators dropped ("3.081.667" → "3081667").
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
REPO = HERE.resolve().parents[2]
CASES = HERE / "cases.json"
FLOW = REPO / ".claude" / "hillclimb" / "nexus-e2e"
PINNED_NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
PROVIDER = "anthropic"  # default; every variant compared with another must use the same one


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", text)


def grade(case: dict[str, Any], output: str, actions: list[dict[str, Any]]) -> tuple[dict[str, float], list[str]]:
    """{pass, checks} and the names of the checks that failed."""
    text = normalize(output)
    failed = [f"must[{i}]" for i, group in enumerate(case["must"]) if not any(re.search(p, text) for p in group)]
    failed += [f"must_not[{i}]: {p}" for i, group in enumerate(case["must_not"])
               for p in group if re.search(p, text)]
    if actions:
        failed.append(f"unexpected actions: {[a['name'] for a in actions]}")
    total = len(case["must"]) + len(case["must_not"]) + 1
    return {"pass": float(not failed), "checks": round(1 - len(failed) / total, 3)}, failed


class Counting:
    """Wraps a model client and books each completed call to the agent it ran for."""

    def __init__(self, inner: Any, agent: str, book: dict[str, dict[str, int]]) -> None:
        self._inner, self._agent, self._book = inner, agent, book

    async def stream(self, messages, tools=None):
        async for event in self._inner.stream(messages, tools):
            usage = getattr(event, "usage", None)
            if usage is not None and hasattr(event, "message"):
                entry = self._book.setdefault(self._agent, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
                entry["calls"] += 1
                entry["input_tokens"] += usage.prompt_tokens
                entry["output_tokens"] += usage.completion_tokens
            yield event


def install(book: dict[str, dict[str, int]], dry: bool, provider: str) -> str:
    """Patch the clock, count model calls per agent, and in a dry run stand in for Jev and the model."""
    from app.services import clients, formatting

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return PINNED_NOW.astimezone(tz)

    formatting.datetime = Clock
    real_model_for = clients.model_for

    def model_for(provider, mandate):
        llm, model = real_model_for(provider, mandate)
        return Counting(llm, mandate.name, book), model

    clients.model_for = model_for
    if not dry:
        return provider
    os.environ["AI_ALLOW_FAKE"] = "1"

    class StubJev:
        async def system_one(self, state, questions):
            return {"model": "stub", "usage": {}, "answers": {
                "route": {"type": "choice", "choice": "orders", "confidence": 0.9, "probabilities": {"orders": 1.0}},
                "missing_context": {"type": "noul", "noul": 0.1}, "covered": {"type": "noul", "noul": 0.9}}}

    clients.jev_client = lambda: StubJev()
    return clients.FAKE


def commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "ai/app"], cwd=REPO, capture_output=True, text=True).stdout
        return sha + ("+dirty" if dirty.strip() else "")
    except OSError:
        return "unknown"


def regrade(variant: str, cases_file: Path) -> None:
    """Grade the stored outputs of `variant` again with the current checks (after a check bug is fixed)."""
    cases = {c["id"]: c for c in json.loads(cases_file.read_text(encoding="utf-8"))}
    path = FLOW / variant / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.with_suffix(".jsonl.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    for row in rows:
        row["tags"] = cases[row["prompt_id"]]["tags"]
        if row["status"] == "ok":
            before = row["grade"]["pass"]
            row["grade"], row["failed_checks"] = grade(cases[row["prompt_id"]], row["output"], row["actions"])
            if row["grade"]["pass"] != before:
                print(f"{row['prompt_id']} rep{row['rep']}: pass {before} -> {row['grade']['pass']} {row['failed_checks']}")
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--start-rep", type=int, default=1, help="number of the first rep, to refill later reps")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--provider", default=PROVIDER, help="provider profile from models.json")
    parser.add_argument("--dry-run", action="store_true", help="fake provider and stub Jev: checks the plumbing for free")
    parser.add_argument("--regrade", action="store_true", help="grade the variant's stored outputs again; no model call")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.regrade:
        return regrade(args.variant, args.cases)
    sys.path.insert(0, str(HERE.parents[1]))
    from evals.router.run import ENV_FILE, load_env

    load_env(ENV_FILE)
    os.environ["AI_TRUST_IDENTITY_HEADERS"] = "1"
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.clients import CATALOG

    book: dict[str, dict[str, int]] = {}
    provider = install(book, args.dry_run, args.provider)
    only = {i for i in args.only.split(",") if i}
    cases = [c for c in json.loads(args.cases.read_text(encoding="utf-8")) if not only or c["id"] in only]
    out_dir = FLOW / args.variant
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"variant": args.variant, "provider": provider, "commit": commit(), "args": sys.argv[1:],
            "pinned_now": PINNED_NOW.isoformat(), "started": datetime.now(timezone.utc).isoformat(),
            "models": dict(CATALOG.profiles.get(provider, {})) if provider != "fake" else {"all": "fake"}}

    with TestClient(app) as client, (out_dir / "results.jsonl").open("a", encoding="utf-8") as results:
        for rep in range(args.start_rep, args.start_rep + args.reps):
            for case in cases:
                book.clear()
                headers = {"x-user-id": f"e2e-{case['id']}", "x-user-departments": case["departments"]}
                started = time.monotonic()
                resp = client.post("/run", json={"task_id": 1, "text": case["text"], "provider": provider}, headers=headers)
                latency = round(time.monotonic() - started, 2)
                body = resp.json()
                ok = resp.status_code == 200
                output = body.get("output", "") if ok else ""
                actions = body.get("pending_actions", []) if ok else []
                scores, failed = grade(case, output, actions) if ok else ({"pass": 0.0, "checks": 0.0}, [f"HTTP {resp.status_code}"])
                row = {
                    "prompt_id": case["id"], "rep": rep, "variant": args.variant, "tags": case["tags"],
                    "grade": scores, "failed_checks": failed, "status": "ok" if ok else "error",
                    "error": None if ok else body.get("detail"), "latency_s": latency,
                    "in_tokens": sum(a["input_tokens"] for a in book.values()),
                    "out_tokens": sum(a["output_tokens"] for a in book.values()),
                    "model_calls": sum(a["calls"] for a in book.values()),
                    "by_agent": {name: {"calls": a["calls"], "input_tokens": a["input_tokens"]} for name, a in book.items()},
                    "actions": actions, "model": body.get("model") if ok else None,
                    "agent": body.get("agent") if ok else None,
                    "branch": (body.get("route") or {}).get("branch") if ok else None, "output": output,
                    # The trace to read when a task gets worse: a worker's final, or the plan and steps with rejections
                    "result": body.get("result") if ok else None,
                }
                results.write(json.dumps(row, ensure_ascii=False) + "\n")
                results.flush()
                mark = "✓" if scores["pass"] else "✗"
                print(f"{case['id']} rep{rep} {mark} {row['branch'] or '-':<15} agents={list(book)} "
                      f"calls={row['model_calls']} in={row['in_tokens']} out={row['out_tokens']} {latency}s {failed or ''}")

    meta["finished"] = datetime.now(timezone.utc).isoformat()
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
