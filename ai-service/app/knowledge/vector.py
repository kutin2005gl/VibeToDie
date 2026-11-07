"""Vector search over the `chunks` table that `ingest.py` fills, and the choice of index for `sop_index()`.

`AI_RETRIEVER` picks the index:
    bm25    (default) BM25 in memory, as before step 8
    hybrid  BM25 and vectors fused by RRF (core/retrieval.py); needs AI_DATABASE_URL and EMBEDDING_URL

Hybrid stays opt-in until the RAG eval shows it does no worse than BM25 (plan-rag step 8, "Đánh giá"). When
it cannot start, or the database or embedding server fails later, search falls back to BM25 with a warning.
"""

import logging
import os
import threading
from collections.abc import Sequence
from typing import Protocol

from app.core.llm.embeddings import EmbeddingClient, client_from_env
from app.core.retrieval import ANY_DEPARTMENT, Bm25Index, Chunk, HybridIndex, visible

log = logging.getLogger(__name__)

RETRIEVERS = ("bm25", "hybrid")
# Seconds to wait for Postgres before the search falls back to BM25
CONNECT_TIMEOUT = 3

# Departments are filtered here, before ranking, so a chunk the requester may not see is never read out of
# the table. `model` keeps vectors of another model out, should an ingest with a new model be half done.
NEAREST = """
SELECT chunk_id, 1 - (embedding <=> %(vector)s::vector) AS similarity
FROM chunks
WHERE model = %(model)s AND (departments && %(departments)s::text[] OR %(any)s = ANY(departments))
ORDER BY embedding <=> %(vector)s::vector
LIMIT %(limit)s
"""


class ChunkVectors(Protocol):
    def nearest(self, vector: list[float], departments: Sequence[str], model: str,
                limit: int) -> list[tuple[str, float]]:
        """(chunk_id, cosine similarity) of the stored chunks visible to `departments`, closest first."""


class PostgresChunkVectors:
    """One connection, opened on the first search and opened again after an error."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._conn = None
        self._lock = threading.Lock()

    def nearest(self, vector, departments, model, limit):
        from app.knowledge.ingest import _literal

        params = {"vector": _literal(vector), "model": model, "departments": list(departments),
                  "any": ANY_DEPARTMENT, "limit": limit}
        with self._lock:
            try:
                return [(r[0], float(r[1])) for r in self._connection().execute(NEAREST, params)]
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _connection(self):
        if self._conn is None or self._conn.closed:
            import psycopg

            # Neon's pooler does not keep prepared statements between connections (as in store/sessions.py)
            self._conn = psycopg.connect(self.url, autocommit=True, prepare_threshold=None,
                                         connect_timeout=CONNECT_TIMEOUT)
        return self._conn


class VectorIndex:
    """Chunks ranked by cosine similarity of their stored embedding to the question's, same `search` as BM25.

    The files stay the source of truth: a stored row whose chunk left the documents, or whose departments no
    longer let the requester see it (ingest not run since), is dropped.
    """

    def __init__(self, chunks: list[Chunk], vectors: ChunkVectors, embedder: EmbeddingClient) -> None:
        self.chunks = list(chunks)
        self._by_id = {c.chunk_id: c for c in self.chunks}
        self.vectors = vectors
        self.embedder = embedder

    def search(self, query: str, departments, limit: int = 5) -> list[tuple[Chunk, float]]:
        allowed = set(departments)
        if not allowed or not query.strip() or limit <= 0:
            return []
        vector = self.embedder.embed_queries([query])[0]
        hits = []
        for chunk_id, similarity in self.vectors.nearest(vector, sorted(allowed), self.embedder.model, limit):
            chunk = self._by_id.get(chunk_id)
            if chunk is not None and visible(chunk, allowed):
                hits.append((chunk, similarity))
        return hits


def index_from_env(chunks: list[Chunk]) -> Bm25Index | HybridIndex:
    lexical = Bm25Index(chunks)
    mode = os.environ.get("AI_RETRIEVER", "bm25").strip().lower() or "bm25"
    if mode not in RETRIEVERS:
        log.warning("AI_RETRIEVER=%r is not one of %s; using BM25", mode, ", ".join(RETRIEVERS))
        return lexical
    if mode == "bm25":
        return lexical
    url = os.environ.get("AI_DATABASE_URL", "").strip()
    embedder = client_from_env()
    if not url or embedder is None:
        log.warning("AI_RETRIEVER=hybrid needs AI_DATABASE_URL and EMBEDDING_URL; using BM25")
        return lexical
    return HybridIndex(lexical, VectorIndex(chunks, PostgresChunkVectors(url), embedder))
