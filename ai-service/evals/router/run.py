"""Run the router cases through `POST /route` against the real Jev and print how each one was routed.

    cd ai
    python -m evals.router.run [--repeat N] [--cases evals/router/holdout.json]

`cases.json` is the set the router's wording was tuned on; `holdout.json` is never tuned against, so its
score is the honest one.

Needs TYPESAFE_API_KEY, from the environment or the repo's `.env`. Each case costs one Jev call per
repeat; no agent runs. A run passes when `router.decide` lands on the branch the case's labels imply.
Repeating shows which cases flip between runs: Jev's probabilities vary slightly from call to call.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

CASES = Path(__file__).with_name("cases.json")
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
BRANCH_OF = {"policy_lookup": "procedure", "multi_department": "multi", "no_fitting_agent": "unknown"}


def load_env(path: Path) -> None:
    """Set KEY=VALUE lines from `path` that the environment does not already define."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def expected(case: dict) -> str:
    if case["expected_missing"]:
        return "clarify"
    branch = BRANCH_OF.get(case["expected_choice"], "single")
    return f"single:{case['expected_choice']}" if branch == "single" else branch


def landed(got: dict) -> str:
    return f"single:{got['target']}" if got["branch"] == "single" else got["branch"]


def span(values: list[float]) -> str:
    low, high = min(values), max(values)
    return f"{low:.2f}" if high - low < 0.005 else f"{low:.2f}-{high:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="Jev calls per case")
    parser.add_argument("--cases", type=Path, default=CASES, help="JSON file of labelled cases")
    args = parser.parse_args()
    repeat = args.repeat
    sys.stdout.reconfigure(encoding="utf-8")
    load_env(ENV_FILE)
    # The eval measures routing, not permissions: ask as a user who may use every agent
    os.environ["AI_TRUST_IDENTITY_HEADERS"] = "1"
    every_department = {"x-user-id": "router-eval", "x-user-departments": "cskh,executive,it"}
    from fastapi.testclient import TestClient

    from app.main import app

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    runs: dict[str, list[dict]] = {case["id"]: [] for case in cases}
    # One event loop for every request, like uvicorn: the cached Jev client keeps its connections
    with TestClient(app) as client:
        for _ in range(repeat):
            for case in cases:
                resp = client.post("/route", json={"text": case["text"]}, headers=every_department)
                if resp.status_code != 200:
                    sys.exit(f"{case['id']}: /route returned {resp.status_code}: {resp.text}")
                runs[case["id"]].append(resp.json())

    print(f"{'id':<14} {'expected':<22} {'got':<28} {'conf':>9} {'missing':>9} {'covered':>9}  ok")
    for case in cases:
        got = runs[case["id"]]
        want = expected(case)
        branches = Counter(landed(g) for g in got)
        shown = ", ".join(f"{b}×{n}" if repeat > 1 else b for b, n in branches.most_common())
        hits = branches[want]
        mark = "✓" if hits == len(got) else "✗" if hits == 0 else "~"
        print(f"{case['id']:<14} {want[:22]:<22} {shown[:28]:<28} {span([g['confidence'] for g in got]):>9} "
              f"{span([g['missing_context'] for g in got]):>9} {span([g['covered'] for g in got]):>9}  {mark}")

    pairs = [(case, g) for case in cases for g in runs[case["id"]]]
    full = [(c, g) for c, g in pairs if not c["expected_missing"]]
    short = [(c, g) for c, g in pairs if c["expected_missing"]]
    flipped = [case["id"] for case in cases if len({landed(g) for g in runs[case["id"]]}) > 1]
    print()
    print("by expected branch      right/runs  wrong landings")
    groups: dict[str, list[dict]] = {}
    for c, g in pairs:
        groups.setdefault(expected(c).split(":")[0], []).append((c, g))
    for branch, members in groups.items():
        right = sum(landed(g) == expected(c) for c, g in members)
        wrong = Counter(landed(g) for c, g in members if landed(g) != expected(c))
        print(f"  {branch:<21} {right:>3}/{len(members):<6} {', '.join(f'{b}×{n}' for b, n in wrong.most_common())}")
    print()
    print(f"branch correct          {sum(landed(g) == expected(c) for c, g in pairs)}/{len(pairs)}")
    print(f"jev choice correct      {sum(g['choice'] == c['expected_choice'] for c, g in full)}/{len(full)}"
          "  (cases with full context)")
    print(f"missing info → clarify  {sum(g['branch'] == 'clarify' for _, g in short)}/{len(short)}"
          f"   false clarify on full requests: {sum(g['branch'] == 'clarify' for _, g in full)}")
    print(f"low_confidence          {sum(g['branch'] == 'low_confidence' for _, g in pairs)}")
    steered = [(c, g) for c, g in pairs if c.get("steer_to")]
    if steered:
        followed = sorted({c["id"] for c, g in steered if landed(g) == c["steer_to"]})
        print(f"followed steering       {sum(landed(g) == c['steer_to'] for c, g in steered)}/{len(steered)}"
              f"  {', '.join(followed)}")
    print(f"flipped between runs    {', '.join(flipped) or 'none'}")
    print(f"jev input tokens        {sum(g['usage'].get('input_tokens', 0) for _, g in pairs)}"
          f"  (model {pairs[0][1]['model']})")


if __name__ == "__main__":
    main()
