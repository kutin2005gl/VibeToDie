from unittest.mock import patch

import pytest

from app.core.llm.embeddings import FakeEmbeddingClient
from app.core.llm.errors import LLMUnavailableError
from app.knowledge import load_chunks, load_documents
from app.knowledge.ingest import InMemoryKnowledgeStore, ingest
from app.knowledge.vector import VectorIndex
from app.services import procedure
from evals.rag import run


@pytest.fixture(scope="module")
def results():
    known = {c.chunk_id: c.departments for c in load_chunks()}
    return run.run_all(run.load_cases(run.CASES, known), known)


def test_no_case_gets_a_chunk_outside_the_requesters_departments(results):
    assert [r.case["id"] for r in results if r.leaks] == []


def test_the_labelled_cases_meet_the_bar_set_in_plan_rag_step_6(results):
    summary = run.summarize(results)
    assert summary["recall"] >= 0.9
    assert summary["none_acc"] == 1.0


def test_every_unaccented_case_repeats_an_accented_one_with_the_same_answer(results):
    by_id = {r.case["id"]: r.case for r in results}
    for r in results:
        if r.case["group"] == "unaccented":
            paired = by_id[r.case["pair"]]
            assert paired["group"] != "unaccented"
            assert (paired["departments"], paired["expected_chunks"]) == (r.case["departments"], r.case["expected_chunks"])


# --- vector and hybrid modes (fake embeddings, no database) ---

@pytest.fixture(scope="module")
def fake_semantic():
    store = InMemoryKnowledgeStore()
    ingest(load_documents(), store, FakeEmbeddingClient())
    return run.Strict(VectorIndex(load_chunks(), store, run.CachedQueries(FakeEmbeddingClient())))


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_vector_modes_keep_the_bm25_no_basis_gate_and_leak_nothing(mode, fake_semantic):
    chunks = load_chunks()
    known = {c.chunk_id: c.departments for c in chunks}
    index = run.build_index(mode, chunks, fake_semantic)
    with patch.object(procedure, "sop_index", lambda: index):
        results = run.run_all(run.load_cases(run.CASES, known), known)
    summary = run.summarize(results)
    assert summary["none_acc"] == 1.0 and summary["leaks"] == 0
    assert all(r.top_similarity is not None for r in results)
    assert fake_semantic.failures == []


def test_a_vector_failure_is_kept_even_though_hybrid_falls_back(fake_semantic):
    class Down:
        embedder = FakeEmbeddingClient()

        def search(self, query, departments, limit=5):
            raise LLMUnavailableError("embedding server unavailable", attempts=3)

    strict = run.Strict(Down())
    index = run.build_index("hybrid", load_chunks(), strict)
    assert index.search("đổi máy lỗi", ["cskh"], 3)  # BM25 still answers
    assert len(strict.failures) == 1
    with pytest.raises(SystemExit):
        run.fail_on_vector_errors(strict)


def test_each_question_is_embedded_once():
    client = FakeEmbeddingClient()
    cached = run.CachedQueries(client)
    cached.embed_queries(["a", "b"])
    cached.embed_queries(["b", "a", "c"])
    assert client.seen == ["query: a", "query: b", "query: c"]
