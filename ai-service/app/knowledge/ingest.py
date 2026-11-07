"""Loads the policy chunks and their embeddings into Postgres (pgvector), so the DB matches `sop/*.md`.

    cd ai && .venv/Scripts/python scripts/ingest_knowledge.py            # or: python -m app.knowledge.ingest
    ... --dry-run                                                        # report only, no embedding, no writes

Needs `AI_DATABASE_URL` and `EMBEDDING_URL` (EMBEDDING_MODEL and EMBEDDING_DIMENSIONS if not the e5-small
defaults). Chunks come from `load_documents()`; nothing here parses the files again. Running it twice in a
row changes nothing and does not call the embedding server the second time.

No vector index: under about 1,000 chunks a sequential scan is fast enough and exact, while HNSW/IVFFlat
only approximate. Revisit past that size, or if a query takes longer than the model call it feeds.
"""

import hashlib
import sys
from dataclasses import dataclass, field
from typing import Protocol

from app.core.llm.embeddings import EmbeddingClient, client_from_env
from app.core.retrieval import ANY_DEPARTMENT
from app.knowledge import Document, load_documents

# e5-small reads at most 512 tokens and silently drops the rest of a longer text
MAX_TOKENS = 512
# Tokens per whitespace word of Vietnamese; the e5 tokenizer gave 1.31 on the 38 chunks (31/10), 1.4 leaves a margin.
# No tokenizer is shipped, so this only warns; the server cuts (or, with auto_truncate off, rejects) the excess
TOKENS_PER_WORD = 1.4


@dataclass(frozen=True)
class Row:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    departments: tuple[str, ...]
    # What is embedded: the title carries the section path, which the question often shares
    embedded: str

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.embedded.encode()).hexdigest()


@dataclass
class Report:
    embedded: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    documents: int = 0
    longest: tuple[str, int] = ("", 0)
    too_long: list[tuple[str, int]] = field(default_factory=list)
    reembedded_all: bool = False


class KnowledgeStore(Protocol):
    def prepare(self, model: str, dimensions: int) -> bool:
        """Create the tables. True when vectors of another model or size were wiped, so all need embedding."""
    def sync_documents(self, documents: list[Document]) -> None: ...
    def existing(self) -> dict[str, tuple[str, str]]:
        """chunk_id → (text_hash, model) of every stored chunk."""
    def upsert(self, rows: list[Row], vectors: list[list[float]], model: str) -> None: ...
    def refresh(self, rows: list[Row]) -> None:
        """Rewrite title, text and departments of chunks whose embedding is still valid."""
    def delete(self, chunk_ids: list[str]) -> None: ...


def rows_of(documents: list[Document]) -> list[Row]:
    """Chunks of the active documents, as `load_chunks()` would give them."""
    return [Row(c.chunk_id, doc.doc_id, c.title, c.text, c.departments, f"{c.title}\n{c.text}")
            for doc in documents if doc.status == "active" for c in doc.chunks]


def estimated_tokens(row: Row) -> int:
    return round(len(row.embedded.split()) * TOKENS_PER_WORD)


def _measured(report: Report, rows: list[Row]) -> Report:
    sizes = [(r.chunk_id, estimated_tokens(r)) for r in rows]
    report.longest = max(sizes, key=lambda s: s[1], default=("", 0))
    report.too_long = [s for s in sizes if s[1] > MAX_TOKENS]
    return report


def ingest(documents: list[Document], store: KnowledgeStore, embedder: EmbeddingClient | None) -> Report:
    """Bring the store in line with `documents`. `embedder` may be None only when nothing needs embedding."""
    rows = rows_of(documents)
    report = _measured(Report(documents=len(documents)), rows)

    model = embedder.model if embedder else ""
    dimensions = embedder.dimensions if embedder else 0
    report.reembedded_all = store.prepare(model, dimensions) if embedder else False
    before = store.existing()
    store.sync_documents(documents)

    stored = store.existing()
    wanted = {r.chunk_id for r in rows}
    stale = [r for r in rows if stored.get(r.chunk_id) != (r.text_hash, model)]
    report.unchanged = [r.chunk_id for r in rows if r not in stale]
    report.deleted = sorted(set(before) - wanted)

    if stale:
        if embedder is None:
            raise RuntimeError("chunks need embedding but EMBEDDING_URL is not set")
        store.upsert(stale, embedder.embed_passages([r.embedded for r in stale]), model)
        report.embedded = [r.chunk_id for r in stale]
    unchanged = set(report.unchanged)
    store.refresh([r for r in rows if r.chunk_id in unchanged])
    # sync_documents already dropped the chunks of removed or superseded documents; this is the rest
    store.delete(sorted(set(stored) - wanted))
    return report


class InMemoryKnowledgeStore:
    """Tests: the same contract as Postgres, without a database."""

    def __init__(self) -> None:
        self.chunks: dict[str, dict] = {}
        self.documents: dict[str, Document] = {}
        self.dimensions = 0

    def prepare(self, model: str, dimensions: int) -> bool:
        wiped = bool(self.chunks) and (self.dimensions != dimensions
                                       or any(c["model"] != model for c in self.chunks.values()))
        if wiped:
            self.chunks.clear()
        self.dimensions = dimensions
        return wiped

    def sync_documents(self, documents):
        self.documents = {d.doc_id: d for d in documents}
        keep = {d.doc_id for d in documents if d.status == "active"}
        self.chunks = {k: v for k, v in self.chunks.items() if v["doc_id"] in keep}

    def existing(self):
        return {k: (v["text_hash"], v["model"]) for k, v in self.chunks.items()}

    def upsert(self, rows, vectors, model):
        for row, vector in zip(rows, vectors, strict=True):
            self.chunks[row.chunk_id] = {"doc_id": row.doc_id, "title": row.title, "text": row.text,
                                         "departments": row.departments, "text_hash": row.text_hash,
                                         "model": model, "embedding": vector}

    def refresh(self, rows):
        for row in rows:
            self.chunks[row.chunk_id].update(title=row.title, text=row.text, departments=row.departments)

    def delete(self, chunk_ids):
        for chunk_id in chunk_ids:
            self.chunks.pop(chunk_id, None)

    def nearest(self, vector, departments, model, limit):
        """`vector.ChunkVectors` without Postgres; vectors are unit length, so the dot product is the cosine."""
        allowed = set(departments)
        hits = [(chunk_id, sum(a * b for a, b in zip(vector, c["embedding"], strict=True)))
                for chunk_id, c in self.chunks.items()
                if c["model"] == model and (ANY_DEPARTMENT in c["departments"] or allowed & set(c["departments"]))]
        hits.sort(key=lambda hit: hit[1], reverse=True)
        return hits[:limit]


def schema(dimensions: int) -> str:
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS documents (
    doc_id           TEXT PRIMARY KEY,
    title            TEXT    NOT NULL,
    owner_department TEXT    NOT NULL,
    allowed_roles    TEXT[]  NOT NULL,
    status           TEXT    NOT NULL,
    supersedes       TEXT[]  NOT NULL,
    effective_date   TEXT    NOT NULL,
    version          TEXT    NOT NULL,
    approved         BOOLEAN NOT NULL,
    language         TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id    TEXT PRIMARY KEY,
    doc_id      TEXT        NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    title       TEXT        NOT NULL,
    text        TEXT        NOT NULL,
    departments TEXT[]      NOT NULL,
    text_hash   TEXT        NOT NULL,
    model       TEXT        NOT NULL,
    embedding   vector({dimensions}) NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresKnowledgeStore:
    def __init__(self, url: str) -> None:
        import psycopg

        # Neon's pooler does not keep prepared statements between connections (as in store/sessions.py)
        self.conn = psycopg.connect(url, autocommit=True, prepare_threshold=None)

    def close(self) -> None:
        self.conn.close()

    def prepare(self, model: str, dimensions: int) -> bool:
        self.conn.execute(schema(dimensions))
        # pgvector keeps the size of `vector(N)` in atttypmod
        row = self.conn.execute(
            "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ).fetchone()
        stored_dimensions = row[0] if row else dimensions
        other_model = self.conn.execute("SELECT count(*) FROM chunks WHERE model <> %s", (model,)).fetchone()[0]
        if stored_dimensions == dimensions and not other_model:
            return False
        # Vectors of two models are not comparable: start over rather than mix them
        with self.conn.transaction():
            self.conn.execute("DELETE FROM chunks")
            if stored_dimensions != dimensions:
                self.conn.execute("ALTER TABLE chunks DROP COLUMN embedding")
                self.conn.execute(f"ALTER TABLE chunks ADD COLUMN embedding vector({dimensions}) NOT NULL")
        return True

    def sync_documents(self, documents: list[Document]) -> None:
        with self.conn.transaction():
            for d in documents:
                self.conn.execute(
                    "INSERT INTO documents (doc_id, title, owner_department, allowed_roles, status, supersedes, "
                    "effective_date, version, approved, language) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (doc_id) DO UPDATE SET title = EXCLUDED.title, "
                    "owner_department = EXCLUDED.owner_department, allowed_roles = EXCLUDED.allowed_roles, "
                    "status = EXCLUDED.status, supersedes = EXCLUDED.supersedes, "
                    "effective_date = EXCLUDED.effective_date, version = EXCLUDED.version, "
                    "approved = EXCLUDED.approved, language = EXCLUDED.language",
                    (d.doc_id, d.title, d.owner_department, list(d.departments), d.status, list(d.supersedes),
                     d.effective_date, d.version, d.approved, d.language))
            # Chunks of a document that is gone go with it (ON DELETE CASCADE)
            self.conn.execute("DELETE FROM documents WHERE doc_id <> ALL(%s)", ([d.doc_id for d in documents],))
            # A superseded document stays listed but gives no chunks
            self.conn.execute("DELETE FROM chunks WHERE doc_id IN (SELECT doc_id FROM documents WHERE status <> 'active')")

    def existing(self) -> dict[str, tuple[str, str]]:
        return {r[0]: (r[1], r[2]) for r in self.conn.execute("SELECT chunk_id, text_hash, model FROM chunks")}

    def upsert(self, rows: list[Row], vectors: list[list[float]], model: str) -> None:
        with self.conn.transaction():
            for row, vector in zip(rows, vectors, strict=True):
                self.conn.execute(
                    "INSERT INTO chunks (chunk_id, doc_id, title, text, departments, text_hash, model, embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector) ON CONFLICT (chunk_id) DO UPDATE SET "
                    "doc_id = EXCLUDED.doc_id, title = EXCLUDED.title, text = EXCLUDED.text, "
                    "departments = EXCLUDED.departments, text_hash = EXCLUDED.text_hash, model = EXCLUDED.model, "
                    "embedding = EXCLUDED.embedding, updated_at = now()",
                    (row.chunk_id, row.doc_id, row.title, row.text, list(row.departments), row.text_hash, model,
                     _literal(vector)))

    def refresh(self, rows: list[Row]) -> None:
        with self.conn.transaction():
            for row in rows:
                # Only when something changed, so a second run writes nothing
                self.conn.execute(
                    "UPDATE chunks SET title = %s, text = %s, departments = %s, updated_at = now() "
                    "WHERE chunk_id = %s AND (title, text, departments) IS DISTINCT FROM (%s, %s, %s::text[])",
                    (row.title, row.text, list(row.departments), row.chunk_id,
                     row.title, row.text, list(row.departments)))

    def delete(self, chunk_ids: list[str]) -> None:
        self.conn.execute("DELETE FROM chunks WHERE chunk_id = ANY(%s)", (chunk_ids,))


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in vector) + "]"


def main(argv: list[str] | None = None) -> int:
    import os

    args = sys.argv[1:] if argv is None else argv
    documents = load_documents()
    if "--dry-run" in args:
        print(summary(_dry_run(documents)))
        return 0
    url = os.environ.get("AI_DATABASE_URL")
    embedder = client_from_env()
    if not url or embedder is None:
        print("set AI_DATABASE_URL and EMBEDDING_URL (or pass --dry-run)", file=sys.stderr)
        return 2
    store = PostgresKnowledgeStore(url)
    try:
        report = ingest(documents, store, embedder)
    finally:
        store.close()
    print(summary(report))
    return 0


def _dry_run(documents: list[Document]) -> Report:
    rows = rows_of(documents)
    return _measured(Report(documents=len(documents), embedded=[r.chunk_id for r in rows]), rows)


def summary(report: Report) -> str:
    lines = [f"{report.documents} documents; embedded {len(report.embedded)}, unchanged {len(report.unchanged)}, "
             f"deleted {len(report.deleted)}"]
    if report.reembedded_all:
        lines.append("model or size changed: every stored vector was wiped and embedded again")
    lines.append(f"longest chunk: {report.longest[0]} (about {report.longest[1]} tokens, limit {MAX_TOKENS})")
    lines += [f"WARNING {chunk_id}: about {tokens} tokens, the model drops the tail" for chunk_id, tokens in report.too_long]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
