import dataclasses

import pytest

from app import knowledge
from app.core.llm.embeddings import FakeEmbeddingClient
from app.knowledge.ingest import MAX_TOKENS, InMemoryKnowledgeStore, ingest, rows_of, schema


def run(store, embedder, documents=None):
    return ingest(documents or knowledge.load_documents(), store, embedder)


def edit_first_chunk(documents, **changes):
    doc = documents[0]
    chunk = dataclasses.replace(doc.chunks[0], **changes)
    documents[0] = dataclasses.replace(doc, chunks=(chunk, *doc.chunks[1:]))
    return chunk


def test_first_run_embeds_every_chunk_of_load_chunks():
    store, fake = InMemoryKnowledgeStore(), FakeEmbeddingClient()
    report = run(store, fake)
    assert sorted(store.chunks) == sorted(c.chunk_id for c in knowledge.load_chunks())
    assert len(report.embedded) == 38 and not report.unchanged and not report.deleted
    assert all(t.startswith("passage: ") for t in fake.seen)


def test_second_run_changes_nothing_and_does_not_call_the_embedder():
    store = InMemoryKnowledgeStore()
    run(store, FakeEmbeddingClient())
    again = FakeEmbeddingClient()
    report = run(store, again)
    assert again.seen == [] and not report.embedded and len(report.unchanged) == 38


def test_only_a_changed_chunk_is_embedded_again():
    store = InMemoryKnowledgeStore()
    documents = knowledge.load_documents()
    run(store, FakeEmbeddingClient(), documents)
    edited = edit_first_chunk(documents, text=documents[0].chunks[0].text + " Bổ sung.")
    fake = FakeEmbeddingClient()
    report = run(store, fake, documents)
    assert report.embedded == [edited.chunk_id] and len(fake.seen) == 1
    assert store.chunks[edited.chunk_id]["text"].endswith("Bổ sung.")


def test_a_changed_department_list_is_stored_without_embedding_again():
    store = InMemoryKnowledgeStore()
    documents = knowledge.load_documents()
    run(store, FakeEmbeddingClient(), documents)
    moved = edit_first_chunk(documents, departments=("*",))
    fake = FakeEmbeddingClient()
    run(store, fake, documents)
    assert fake.seen == [] and store.chunks[moved.chunk_id]["departments"] == ("*",)


def test_chunks_missing_from_the_documents_are_deleted():
    store = InMemoryKnowledgeStore()
    documents = knowledge.load_documents()
    run(store, FakeEmbeddingClient(), documents)
    doc = documents[0]
    gone = doc.chunks[0].chunk_id
    documents[0] = dataclasses.replace(doc, chunks=doc.chunks[1:])
    report = run(store, FakeEmbeddingClient(), documents)
    assert report.deleted == [gone] and gone not in store.chunks


def test_a_superseded_document_loses_its_chunks_but_stays_listed():
    store = InMemoryKnowledgeStore()
    documents = knowledge.load_documents()
    run(store, FakeEmbeddingClient(), documents)
    doc = documents[0]
    documents[0] = dataclasses.replace(doc, status="superseded")
    report = run(store, FakeEmbeddingClient(), documents)
    assert set(report.deleted) == {c.chunk_id for c in doc.chunks}
    assert doc.doc_id in store.documents
    assert not any(v["doc_id"] == doc.doc_id for v in store.chunks.values())


def test_changing_the_model_embeds_everything_again():
    store = InMemoryKnowledgeStore()
    run(store, FakeEmbeddingClient(model="e5-small"))
    report = run(store, FakeEmbeddingClient(model="bge-m3"))
    assert report.reembedded_all and len(report.embedded) == 38
    assert {c["model"] for c in store.chunks.values()} == {"bge-m3"}


def test_changing_the_size_embeds_everything_again():
    store = InMemoryKnowledgeStore()
    run(store, FakeEmbeddingClient(dimensions=384))
    report = run(store, FakeEmbeddingClient(dimensions=1024))
    assert report.reembedded_all and all(len(c["embedding"]) == 1024 for c in store.chunks.values())


def test_without_an_embedder_chunks_that_need_embedding_are_an_error():
    with pytest.raises(RuntimeError, match="EMBEDDING_URL"):
        run(InMemoryKnowledgeStore(), None)


def test_report_names_the_longest_chunk_and_flags_those_over_the_limit():
    report = run(InMemoryKnowledgeStore(), FakeEmbeddingClient())
    ids = {r.chunk_id for r in rows_of(knowledge.load_documents())}
    assert report.longest[0] in ids
    assert all(tokens > MAX_TOKENS for _, tokens in report.too_long)


def test_schema_takes_the_size_from_the_model():
    assert "vector(384)" in schema(384) and "vector(1024)" in schema(1024)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema(384)
