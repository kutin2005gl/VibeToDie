"""Measure what the procedure branch retrieves, against labelled questions. Offline: no model, no network, no key.

    cd ai
    python -m evals.rag.run [--cases evals/rag/cases.json] [--retriever bm25|vector|hybrid] [--sweep]

Every case is run through `procedure.retrieve`, the function the runtime calls, so the numbers are the runtime's.
A case is `{id, group, text, departments, expected_chunks, pair?}`: `expected_chunks` lists the chunk ids that
count as a right answer (any one is enough) or is "none" when the documents the requester may see do not back
the question. `pair` names the accented case an unaccented one repeats.

Printed per group: recall@3 (an accepted chunk among the first three), MRR (1 / rank of the first accepted chunk),
no-basis accuracy (retrieve came back empty), and leaks: returned chunks whose departments exclude the case's
(must be 0; the exit code is 1 otherwise). The top BM25 score of each case, before the threshold, shows whether
one score cut-off can tell the two kinds of case apart. `--sweep` repeats the run over a grid of k1 and b
(bm25) or of the RRF k (hybrid), then over a grid of the two no-basis thresholds.

`--retriever` picks what ranks the passages; bm25 (the default) is the only one that stays offline:
    bm25    Bm25Index, the runtime's default
    vector  the stored chunk vectors alone (knowledge/vector.py), nearest first
    hybrid  both fused by RRF (HybridIndex), as with AI_RETRIEVER=hybrid
vector and hybrid need AI_DATABASE_URL and EMBEDDING_URL, with the chunks loaded (python -m app.knowledge.ingest).
In every mode the no-basis gate of `procedure.retrieve` is judged on BM25, as at runtime, so only the passages
handed to the agent change; the top cosine of each case is printed to show whether a vector gate could work.
Unlike the runtime, a failing vector search aborts the run instead of falling back to BM25.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from app.core.context import RequestContext
from app.core.llm.embeddings import client_from_env
from app.core.retrieval import ANY_DEPARTMENT, RRF_K, Bm25Index, HybridIndex
from app.knowledge import load_chunks
from app.knowledge.vector import PostgresChunkVectors, VectorIndex
from app.services import procedure

CASES = Path(__file__).with_name("cases.json")
RECALL_AT = 3
K1_GRID = (0.9, 1.2, 1.5, 1.8, 2.1)
B_GRID = (0.4, 0.55, 0.75, 0.9)
RRF_K_GRID = (0, 10, 30, 60, 100)
SCORE_GRID = (8.0, 9.0, 10.0, 11.0, 12.0)
COVERAGE_GRID = (0.45, 0.5, 0.55, 0.6, 0.65)
RETRIEVERS = ("bm25", "vector", "hybrid")


@dataclass
class Result:
    case: dict
    got: list[str]  # chunk ids retrieve returned, best first
    top_score: float  # best BM25 score among the chunks the requester may see, threshold ignored
    leaks: list[str]
    top_similarity: float | None = None  # best cosine among them, None without vectors

    @property
    def expected(self) -> list[str]:
        return [] if self.case["expected_chunks"] == "none" else self.case["expected_chunks"]

    @property
    def rank(self) -> int | None:
        """1-based rank of the first accepted chunk, None when retrieve missed it."""
        return next((i for i, cid in enumerate(self.got, 1) if cid in self.expected), None)

    @property
    def ok(self) -> bool:
        if not self.expected:
            return not self.got
        return self.rank is not None and self.rank <= RECALL_AT


def load_cases(path: Path, known: dict[str, tuple[str, ...]]) -> list[dict]:
    """The cases in `path`; a malformed one, or an expected chunk id that does not exist, aborts the run."""
    cases = json.loads(path.read_text(encoding="utf-8"))
    ids = {case.get("id") for case in cases}
    problems = []
    for case in cases:
        name = case.get("id", "?")
        missing = {"id", "group", "text", "departments", "expected_chunks"} - case.keys()
        if missing:
            problems.append(f"{name}: missing {sorted(missing)}")
            continue
        expected = case["expected_chunks"]
        if expected != "none" and not (isinstance(expected, list) and expected):
            problems.append(f"{name}: expected_chunks must be a non-empty list or \"none\"")
            continue
        problems += [f"{name}: unknown chunk {cid}" for cid in ([] if expected == "none" else expected) if cid not in known]
        if "pair" in case and case["pair"] not in ids:
            problems.append(f"{name}: pair {case['pair']} is not a case")
    if len(ids) != len(cases):
        problems.append("duplicate case ids")
    if problems:
        sys.exit("bad cases:\n  " + "\n  ".join(problems))
    return cases


class CachedQueries:
    """The embedding client, with each question embedded once per run however many grid points ask for it."""

    def __init__(self, client) -> None:
        self.client = client
        self.model = client.model
        self.dimensions = client.dimensions
        self._seen: dict[str, list[float]] = {}

    def embed_queries(self, texts):
        missing = [t for t in dict.fromkeys(texts) if t not in self._seen]
        if missing:
            self._seen.update(zip(missing, self.client.embed_queries(missing)))
        return [self._seen[t] for t in texts]

    def embed_passages(self, texts):
        return self.client.embed_passages(texts)


class Strict:
    """The vector side, keeping every failure: HybridIndex falls back to BM25 on one, which would quietly
    turn a hybrid run into a BM25 run."""

    def __init__(self, inner: VectorIndex) -> None:
        self.inner = inner
        self.failures: list[str] = []

    def search(self, query, departments, limit=5):
        try:
            return self.inner.search(query, departments, limit)
        except Exception as exc:
            self.failures.append(f"{type(exc).__name__}: {exc}")
            raise


@dataclass
class VectorOnly:
    """Vector ranking, with the BM25 side kept for the no-basis gate as `procedure.retrieve` reads it."""

    lexical: Bm25Index
    semantic: Strict

    def search(self, query, departments, limit=5):
        return self.semantic.search(query, departments, limit)


def semantic_from_env(chunks) -> Strict:
    url = os.environ.get("AI_DATABASE_URL", "").strip()
    embedder = client_from_env()
    if not url or embedder is None:
        sys.exit("--retriever vector|hybrid needs AI_DATABASE_URL and EMBEDDING_URL")
    return Strict(VectorIndex(chunks, PostgresChunkVectors(url), CachedQueries(embedder)))


def build_index(mode: str, chunks, semantic: Strict | None, k: int = RRF_K):
    lexical = Bm25Index(chunks)
    if mode == "bm25":
        return lexical
    if mode == "vector":
        return VectorOnly(lexical, semantic)
    return HybridIndex(lexical, semantic, k=k)


def run_case(case: dict, known: dict[str, tuple[str, ...]]) -> Result:
    ctx = RequestContext(user_id="rag-eval", departments=tuple(case["departments"]))
    got = list(procedure.retrieve(case["text"], ctx))
    index = procedure.sop_index()
    best = getattr(index, "lexical", index).search(case["text"], ctx.departments, 1)
    semantic = getattr(index, "semantic", None)
    nearest = semantic.search(case["text"], ctx.departments, 1) if semantic is not None else None
    visible = lambda cid: ANY_DEPARTMENT in known[cid] or set(known[cid]) & set(case["departments"])
    return Result(case, got, best[0][1] if best else 0.0, [cid for cid in got if not visible(cid)],
                  None if nearest is None else (nearest[0][1] if nearest else 0.0))


def run_all(cases: list[dict], known: dict[str, tuple[str, ...]]) -> list[Result]:
    return [run_case(case, known) for case in cases]


def summarize(results: list[Result]) -> dict:
    """Metrics over `results`; each is None when the group has no case it applies to."""
    answerable = [r for r in results if r.expected]
    silent = [r for r in results if not r.expected]
    return {
        "recall": sum(r.ok for r in answerable) / len(answerable) if answerable else None,
        "mrr": sum(1 / r.rank if r.rank else 0 for r in answerable) / len(answerable) if answerable else None,
        "none_acc": sum(r.ok for r in silent) / len(silent) if silent else None,
        "leaks": sum(len(r.leaks) for r in results),
    }


def fmt(value: float | None) -> str:
    return "  -  " if value is None else f"{value:.2f}"


def groups_of(results: list[Result]) -> dict[str, list[Result]]:
    groups: dict[str, list[Result]] = {}
    for r in results:
        groups.setdefault(r.case["group"], []).append(r)
    return groups


def print_cases(results: list[Result]) -> None:
    print(f"{'id':<5} {'group':<17} {'dept':<10} {'top':>6} {'cos':>5} {'rank':>4}  ok  returned")
    for r in results:
        rank = r.rank if r.rank else "-"
        mark = "ok" if r.ok else "XX"
        cos = "-" if r.top_similarity is None else f"{r.top_similarity:.3f}"
        print(f"{r.case['id']:<5} {r.case['group']:<17} {','.join(r.case['departments']):<10} {r.top_score:>6.2f} {cos:>5} {rank!s:>4}  {mark}  "
              f"{', '.join(r.got) or '(nothing)'}{'  LEAK ' + ','.join(r.leaks) if r.leaks else ''}")


def print_summary(results: list[Result]) -> None:
    print(f"\n{'group':<17} {'n':>3} {'recall@' + str(RECALL_AT):>9} {'MRR':>6} {'no-basis':>9} {'leaks':>6}")
    for name, rows in [*groups_of(results).items(), ("all", results)]:
        s = summarize(rows)
        print(f"{name:<17} {len(rows):>3} {fmt(s['recall']):>9} {fmt(s['mrr']):>6} {fmt(s['none_acc']):>9} {s['leaks']:>6}")


def print_score_split(results: list[Result]) -> None:
    """Top scores of the cases the documents back and of those they do not: separable only if the ranges do not meet."""
    backed = sorted(r.top_score for r in results if r.expected)
    unbacked = sorted(r.top_score for r in results if not r.expected)
    print(f"\ntop score, backed cases:   {backed[0]:.2f} .. {backed[-1]:.2f}  (lowest three: {', '.join(f'{s:.2f}' for s in backed[:3])})")
    print(f"top score, unbacked cases: {unbacked[0]:.2f} .. {unbacked[-1]:.2f}  (highest three: {', '.join(f'{s:.2f}' for s in unbacked[-3:])})")
    verdict = "the score alone separates them" if backed[0] > unbacked[-1] else "ranges overlap: the score alone does not separate them"
    print(f"score threshold now {procedure.MIN_RETRIEVAL_SCORE} (coverage {procedure.MIN_QUESTION_COVERAGE}): {verdict}")
    if results and results[0].top_similarity is not None:
        backed = sorted(r.top_similarity for r in results if r.expected)
        unbacked = sorted(r.top_similarity for r in results if not r.expected)
        print(f"top cosine, backed cases:   {backed[0]:.3f} .. {backed[-1]:.3f}  (lowest three: {', '.join(f'{s:.3f}' for s in backed[:3])})")
        print(f"top cosine, unbacked cases: {unbacked[0]:.3f} .. {unbacked[-1]:.3f}  (highest three: {', '.join(f'{s:.3f}' for s in unbacked[-3:])})")
        verdict = "cosine alone separates them" if backed[0] > unbacked[-1] else "ranges overlap: cosine alone does not separate them"
        print(f"cosine: {verdict}")


def row(label: str, s: dict) -> str:
    return f"{label} {fmt(s['recall']):>9} {fmt(s['mrr']):>6} {fmt(s['none_acc']):>9} {s['leaks']:>6}"


def sweep(cases: list[dict], known: dict[str, tuple[str, ...]], mode: str, semantic: Strict | None) -> None:
    chunks = load_chunks()
    header = f"{'recall@' + str(RECALL_AT):>9} {'MRR':>6} {'no-basis':>9} {'leaks':>6}"
    if mode == "bm25":
        print(f"{'k1':>4} {'b':>5} {header}")
        for k1 in K1_GRID:
            for b in B_GRID:
                index = Bm25Index(chunks, k1=k1, b=b)
                with patch.object(procedure, "sop_index", lambda index=index: index):
                    print(row(f"{k1:>4} {b:>5}", summarize(run_all(cases, known))))
    elif mode == "hybrid":
        print(f"{'rrf k':>5} {header}")
        for k in RRF_K_GRID:
            index = build_index(mode, chunks, semantic, k)
            with patch.object(procedure, "sop_index", lambda index=index: index):
                print(row(f"{k:>5}", summarize(run_all(cases, known))))
    index = build_index(mode, chunks, semantic)
    print(f"\n{mode}, no-basis thresholds\n{'score':>5} {'cover':>5} {header}")
    for score in SCORE_GRID:
        for coverage in COVERAGE_GRID:
            with patch.object(procedure, "sop_index", lambda: index), \
                    patch.object(procedure, "MIN_RETRIEVAL_SCORE", score), \
                    patch.object(procedure, "MIN_QUESTION_COVERAGE", coverage):
                print(row(f"{score:>5} {coverage:>5}", summarize(run_all(cases, known))))


def fail_on_vector_errors(semantic: Strict | None) -> None:
    if semantic is not None and semantic.failures:
        sys.exit(f"FAIL: vector search failed {len(semantic.failures)} times, so the numbers would be BM25's: "
                 f"{semantic.failures[0]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=CASES, help="JSON file of labelled cases")
    parser.add_argument("--retriever", choices=RETRIEVERS, default="bm25", help="what ranks the passages")
    parser.add_argument("--sweep", action="store_true",
                        help="repeat over a grid of k1 and b (bm25) or RRF k (hybrid), then of the two thresholds")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    chunks = load_chunks()
    known = {c.chunk_id: c.departments for c in chunks}
    cases = load_cases(args.cases, known)
    semantic = semantic_from_env(chunks) if args.retriever != "bm25" else None
    print(f"retriever: {args.retriever}" + (f" ({semantic.inner.embedder.model})" if semantic else ""))
    if args.sweep:
        sweep(cases, known, args.retriever, semantic)
        fail_on_vector_errors(semantic)
        return
    index = build_index(args.retriever, chunks, semantic)
    with patch.object(procedure, "sop_index", lambda: index):
        results = run_all(cases, known)
    fail_on_vector_errors(semantic)
    print_cases(results)
    print_summary(results)
    print_score_split(results)
    if any(r.leaks for r in results):
        sys.exit("FAIL: a chunk outside the requester's departments was retrieved")


if __name__ == "__main__":
    main()
