"""The Postgres store against a real pgvector database. Skipped without AI_TEST_DATABASE_URL.

It drops and recreates the `documents` and `chunks` tables, so point it at a throwaway database, never the
one that holds sessions:
    docker run -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=t pgvector/pgvector:pg17
    AI_TEST_DATABASE_URL=postgresql://postgres:t@127.0.0.1:55432/postgres pytest tests/test_ingest_postgres.py
"""

import dataclasses
import os

import pytest

from app import knowledge
from app.core.llm.embeddings import FakeEmbeddingClient
from app.knowledge.ingest import PostgresKnowledgeStore, ingest

URL = os.environ.get("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="AI_TEST_DATABASE_URL not set")


@pytest.fixture
def store():
    s = PostgresKnowledgeStore(URL)
    s.conn.execute("DROP TABLE IF EXISTS chunks, documents")
    yield s
    s.close()


def count(store, table="chunks"):
    return store.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_first_run_stores_every_chunk_and_the_second_embeds_nothing(store):
    report = ingest(knowledge.load_documents(), store, FakeEmbeddingClient())
    assert len(report.embedded) == 38 and count(store) == 38 and count(store, "documents") == 5
    again = FakeEmbeddingClient()
    report = ingest(knowledge.load_documents(), store, again)
    assert again.seen == [] and len(report.unchanged) == 38


def test_vectors_and_departments_are_stored(store):
    ingest(knowledge.load_documents(), store, FakeEmbeddingClient())
    departments, dims = store.conn.execute(
        "SELECT departments, vector_dims(embedding) FROM chunks WHERE chunk_id = 'QD-CSKH-2026-03#2.1'").fetchone()
    assert dims == 384 and "cskh" in departments


def test_a_superseded_document_and_a_removed_chunk_leave_the_table(store):
    documents = knowledge.load_documents()
    ingest(documents, store, FakeEmbeddingClient())
    first, second = documents[0], documents[1]
    documents[0] = dataclasses.replace(first, status="superseded")
    documents[1] = dataclasses.replace(second, chunks=second.chunks[1:])
    report = ingest(documents, store, FakeEmbeddingClient())
    assert set(report.deleted) == {c.chunk_id for c in first.chunks} | {second.chunks[0].chunk_id}
    assert count(store) == 38 - len(first.chunks) - 1 and count(store, "documents") == 5


def test_a_new_model_size_recreates_the_vector_column(store):
    ingest(knowledge.load_documents(), store, FakeEmbeddingClient(dimensions=384))
    report = ingest(knowledge.load_documents(), store, FakeEmbeddingClient(dimensions=1024, model="bge-m3"))
    assert report.reembedded_all and count(store) == 38
    assert store.conn.execute("SELECT DISTINCT vector_dims(embedding) FROM chunks").fetchall() == [(1024,)]


def test_a_new_model_with_the_same_size_embeds_again(store):
    ingest(knowledge.load_documents(), store, FakeEmbeddingClient(model="a"))
    report = ingest(knowledge.load_documents(), store, FakeEmbeddingClient(model="b"))
    assert report.reembedded_all and store.conn.execute("SELECT DISTINCT model FROM chunks").fetchall() == [("b",)]


def test_vector_search_filters_departments_in_sql(store):
    from app.knowledge.vector import PostgresChunkVectors, VectorIndex

    embedder = FakeEmbeddingClient()
    ingest(knowledge.load_documents(), store, embedder)
    vectors = PostgresChunkVectors(URL)
    try:
        raw = vectors.nearest(embedder.embed_queries(["phê duyệt chi"])[0], ["cskh"], embedder.model, 38)
        assert raw and not any(cid.startswith(("QC-BOD", "QD-KT")) for cid, _ in raw)
        assert [s for _, s in raw] == sorted((s for _, s in raw), reverse=True)
        assert vectors.nearest(embedder.embed_queries(["x"])[0], ["cskh"], "other-model", 5) == []
        hits = VectorIndex(knowledge.load_chunks(), vectors, embedder).search("đổi máy lỗi", ("cskh",), 3)
        assert hits[0][0].chunk_id.startswith("QD-CSKH-2026-03#")
    finally:
        vectors.close()
