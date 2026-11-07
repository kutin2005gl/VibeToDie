"""Vector search and RRF (plan-rag step 8), offline: fake embeddings and the in-memory chunk store."""

import logging

import pytest

from app import knowledge
from app.core.context import RequestContext
from app.core.llm.embeddings import FakeEmbeddingClient
from app.core.llm.errors import LLMUnavailableError
from app.core.retrieval import Bm25Index, Chunk, HybridIndex, reciprocal_rank_fusion
from app.knowledge import vector
from app.knowledge.ingest import InMemoryKnowledgeStore, ingest
from app.knowledge.vector import VectorIndex, index_from_env
from app.services import procedure


def chunk(chunk_id, departments=("cskh",), text="x"):
    return Chunk(chunk_id=chunk_id, title=chunk_id, departments=departments, text=text)


A, B, C, D = (chunk(i) for i in "ABCD")


@pytest.fixture(scope="module")
def store():
    """The real 38 chunks, embedded with the fake client."""
    s = InMemoryKnowledgeStore()
    ingest(knowledge.load_documents(), s, FakeEmbeddingClient())
    return s


@pytest.fixture
def chunks():
    return knowledge.load_chunks()


def vector_index(chunks, store, embedder=None):
    return VectorIndex(chunks, store, embedder or FakeEmbeddingClient())


class Failing:
    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc or LLMUnavailableError("embedding server unavailable", attempts=3)

    def search(self, query, departments, limit=5):
        self.calls += 1
        raise self.exc


class Fixed:
    """A semantic retriever that returns the same hits whatever is asked."""

    def __init__(self, hits):
        self.hits = hits

    def search(self, query, departments, limit=5):
        return self.hits[:limit]


# --- RRF ---

def test_rrf_sums_reciprocal_ranks():
    fused = dict((c.chunk_id, s) for c, s in reciprocal_rank_fusion([[A, B, C], [B, D]], k=60))
    assert fused == pytest.approx({"A": 1 / 61, "B": 1 / 62 + 1 / 61, "C": 1 / 63, "D": 1 / 62})


def test_rrf_ranks_a_chunk_both_retrievers_find_above_one_only_one_ranks_first():
    assert [c.chunk_id for c, _ in reciprocal_rank_fusion([[A, B, C], [D, B, C]])] == ["B", "C", "A", "D"]


def test_rrf_tie_keeps_the_first_ranking_order():
    assert [c.chunk_id for c, _ in reciprocal_rank_fusion([[A, C], [B, D]])] == ["A", "B", "C", "D"]


def test_rrf_k_changes_how_much_rank_matters():
    # A is first in one ranking only, B second and third; a small k favours A's single first place
    rankings = [[A, B], [C, D, B]]
    small = [c.chunk_id for c, _ in reciprocal_rank_fusion(rankings, k=0)]
    large = [c.chunk_id for c, _ in reciprocal_rank_fusion(rankings, k=1000)]
    assert small[0] == "A" and large[0] == "B"


def test_rrf_rejects_negative_k():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[A]], k=-1)


def test_rrf_empty():
    assert reciprocal_rank_fusion([[], []]) == []


# --- vector search ---

def test_vector_search_ranks_the_matching_chunk_first(chunks, store):
    hits = vector_index(chunks, store).search("đổi máy lỗi trong 30 ngày 1-đổi-1", ("cskh",), 3)
    assert hits and hits[0][0].chunk_id.startswith("QD-CSKH-2026-03#")
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_vector_search_embeds_the_question_with_the_query_prefix(chunks, store):
    embedder = FakeEmbeddingClient()
    vector_index(chunks, store, embedder).search("đổi trả", ("cskh",), 3)
    assert embedder.seen == ["query: đổi trả"]


def test_vector_search_never_returns_a_chunk_outside_the_departments(chunks, store):
    for question in ("hạn mức phê duyệt của ban giám đốc", "quy trình chi tiền", "đổi máy lỗi"):
        hits = vector_index(chunks, store).search(question, ("cskh",), 38)
        assert hits
        assert all("cskh" in c.departments or "*" in c.departments for c, _ in hits)
        assert not any(c.chunk_id.startswith(("QC-BOD", "QD-KT")) for c, _ in hits)


def test_vector_search_filters_in_the_store_not_after(chunks):
    seen = []

    class Recording:
        def nearest(self, vector, departments, model, limit):
            seen.append((tuple(departments), limit))
            return []

    VectorIndex(chunks, Recording(), FakeEmbeddingClient()).search("đổi máy", ("it", "cskh"), 4)
    assert seen == [(("cskh", "it"), 4)]


def test_vector_search_with_no_department_sees_nothing_and_calls_nothing(chunks, store):
    embedder = FakeEmbeddingClient()
    assert vector_index(chunks, store, embedder).search("đổi máy", (), 5) == []
    assert embedder.seen == []


def test_vector_search_drops_rows_the_files_no_longer_hold_or_allow(chunks, store):
    # The store answers with a chunk that left the documents and one the requester may no longer see
    class Stale:
        def nearest(self, vector, departments, model, limit):
            return [("GONE#1", 0.9), ("QC-BOD-2026-01#1.1", 0.8), ("QD-CSKH-2026-03#2.1", 0.7)]

    hits = VectorIndex(chunks, Stale(), FakeEmbeddingClient()).search("x", ("cskh",), 5)
    assert [c.chunk_id for c, _ in hits] == ["QD-CSKH-2026-03#2.1"]


def test_vector_search_ignores_vectors_of_another_model(chunks, store):
    assert vector_index(chunks, store, FakeEmbeddingClient(model="other")).search("đổi máy", ("cskh",), 5) == []


# --- hybrid ---

def test_hybrid_fuses_bm25_and_vectors(chunks, store):
    lexical = Bm25Index(chunks)
    hybrid = HybridIndex(lexical, vector_index(chunks, store))
    hits = hybrid.search("đổi máy lỗi", ("cskh",), 4)
    assert len(hits) == 4
    assert all(0 < s <= 2 / 61 for _, s in hits)
    assert hits[0][0].chunk_id in {c.chunk_id for c, _ in lexical.search("đổi máy lỗi", ("cskh",), 4)}


def test_hybrid_lifts_a_chunk_bm25_ranks_low_when_vectors_rank_it_first(chunks):
    lexical = Bm25Index(chunks)
    bm25 = [c for c, _ in lexical.search("đổi máy lỗi", ("cskh",), 20)]
    low = bm25[5]
    hybrid = HybridIndex(lexical, Fixed([(low, 0.99)]))
    assert hybrid.search("đổi máy lỗi", ("cskh",), 3)[0][0] == low


def test_hybrid_keeps_the_department_filter_even_if_vectors_leak(chunks):
    bod = next(c for c in chunks if c.chunk_id.startswith("QC-BOD"))
    hybrid = HybridIndex(Bm25Index(chunks), Fixed([(bod, 1.0)]))
    assert bod not in [c for c, _ in hybrid.search("phê duyệt", ("cskh",), 38)]


def test_hybrid_with_no_department_sees_nothing(chunks, store):
    assert HybridIndex(Bm25Index(chunks), vector_index(chunks, store)).search("đổi máy", (), 5) == []


def test_hybrid_falls_back_to_bm25_with_one_warning_when_vectors_fail(chunks, caplog):
    lexical = Bm25Index(chunks)
    failing = Failing()
    hybrid = HybridIndex(lexical, failing)
    with caplog.at_level(logging.WARNING, logger="app.core.retrieval"):
        hits = hybrid.search("đổi máy lỗi", ("cskh",), 4)
    assert hits == lexical.search("đổi máy lỗi", ("cskh",), 4)
    assert len(caplog.records) == 1 and "BM25 only" in caplog.records[0].getMessage()


def test_hybrid_falls_back_on_a_database_error(chunks):
    lexical = Bm25Index(chunks)
    hybrid = HybridIndex(lexical, Failing(OSError("connection refused")))
    assert hybrid.search("trả góp", ("cskh",), 3) == lexical.search("trả góp", ("cskh",), 3)


def test_hybrid_pauses_vectors_after_a_failure_then_tries_again(chunks):
    now = [0.0]
    failing = Failing()
    hybrid = HybridIndex(Bm25Index(chunks), failing, retry_after=30, clock=lambda: now[0])
    hybrid.search("đổi máy", ("cskh",), 3)
    now[0] = 29.0
    hybrid.search("đổi máy", ("cskh",), 3)
    assert failing.calls == 1
    now[0] = 30.0
    hybrid.search("đổi máy", ("cskh",), 3)
    assert failing.calls == 2


# --- which index sop_index() builds ---

@pytest.fixture
def env(monkeypatch):
    for name in ("AI_RETRIEVER", "AI_DATABASE_URL", "EMBEDDING_URL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_bm25_is_the_default(env, chunks):
    env.setenv("AI_DATABASE_URL", "postgresql://x")
    env.setenv("EMBEDDING_URL", "http://embedding")
    assert type(index_from_env(chunks)) is Bm25Index


@pytest.mark.parametrize("missing", ["AI_DATABASE_URL", "EMBEDDING_URL"])
def test_hybrid_without_db_or_embedding_falls_back_to_bm25(env, chunks, missing, caplog):
    env.setenv("AI_RETRIEVER", "hybrid")
    env.setenv("AI_DATABASE_URL", "postgresql://x")
    env.setenv("EMBEDDING_URL", "http://embedding")
    env.delenv(missing)
    with caplog.at_level(logging.WARNING, logger="app.knowledge.vector"):
        assert type(index_from_env(chunks)) is Bm25Index
    assert "using BM25" in caplog.text


def test_unknown_retriever_falls_back_to_bm25(env, chunks, caplog):
    env.setenv("AI_RETRIEVER", "vectors")
    with caplog.at_level(logging.WARNING, logger="app.knowledge.vector"):
        assert type(index_from_env(chunks)) is Bm25Index
    assert "not one of" in caplog.text


def test_hybrid_builds_without_touching_the_network(env, chunks):
    env.setenv("AI_RETRIEVER", "hybrid")
    env.setenv("AI_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    env.setenv("EMBEDDING_URL", "http://127.0.0.1:1")
    index = index_from_env(chunks)
    assert isinstance(index, HybridIndex) and isinstance(index.semantic.vectors, vector.PostgresChunkVectors)


def test_hybrid_with_an_unreachable_database_answers_with_bm25(env, chunks):
    # A real HybridIndex wired from env: the embedding call fails first, the search still answers
    env.setenv("AI_RETRIEVER", "hybrid")
    env.setenv("AI_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    env.setenv("EMBEDDING_URL", "http://127.0.0.1:1")
    index = index_from_env(chunks)
    index.semantic.embedder._sleep = lambda _: None
    assert index.search("đổi máy lỗi", ("cskh",), 3) == index.lexical.search("đổi máy lỗi", ("cskh",), 3)


# --- procedure.retrieve on the hybrid index ---

def ctx(*departments):
    return RequestContext(user_id="u", departments=departments)


@pytest.fixture
def hybrid_sop(monkeypatch, chunks, store):
    index = HybridIndex(Bm25Index(chunks), vector_index(chunks, store))
    monkeypatch.setattr(procedure, "sop_index", lambda: index)
    return index


def test_procedure_on_hybrid_still_cites_the_backed_passage(hybrid_sop):
    got = procedure.retrieve("Khách mua máy bị lỗi trong 30 ngày có được đổi máy mới không?", ctx("cskh"))
    assert "QD-CSKH-2026-03#2.1" in got and len(got) <= procedure.RETRIEVE_LIMIT


def test_procedure_on_hybrid_blocks_a_question_the_documents_do_not_back(hybrid_sop):
    # Vectors always return a nearest chunk; the no-basis gate stays on BM25, so nothing goes to the agent
    assert procedure.retrieve("Thời tiết Hà Nội hôm nay thế nào?", ctx("cskh")) == {}


def test_procedure_on_hybrid_never_hands_over_another_department(hybrid_sop):
    got = procedure.retrieve("Hạn mức phê duyệt chi của ban giám đốc là bao nhiêu?", ctx("cskh"))
    assert not any(cid.startswith(("QC-BOD", "QD-KT")) for cid in got)


def test_procedure_on_hybrid_with_vectors_down_matches_bm25(monkeypatch, chunks):
    question = "Khách mua máy bị lỗi trong 30 ngày có được đổi máy mới không?"
    monkeypatch.setattr(procedure, "sop_index", lambda: Bm25Index(chunks))
    bm25 = procedure.retrieve(question, ctx("cskh"))
    index = HybridIndex(Bm25Index(chunks), Failing())
    monkeypatch.setattr(procedure, "sop_index", lambda: index)
    assert procedure.retrieve(question, ctx("cskh")) == bm25
