# ai-service

FastAPI service that routes requests and runs the agents. The API contract is in the root [README.md](../README.md#api); layout and commands are in [CLAUDE.md](../CLAUDE.md).

## Policy knowledge in Postgres (plan-rag step 8)

`app/knowledge/sop/*.md` are cut into chunks (`app/knowledge/__init__.py`). Today `search_sop` and the `procedure` branch search them with BM25 in memory. Step 8 adds the same chunks to Postgres with an embedding each (pgvector), produced by a self-hosted `multilingual-e5-small`, so policy text never leaves the machine.

| Variable | Meaning |
| --- | --- |
| `AI_DATABASE_URL` | Postgres for sessions and for the `documents` / `chunks` tables |
| `EMBEDDING_URL` | Base URL of the embedding server (`/v1/embeddings`); compose sets `http://embedding:80` |
| `EMBEDDING_MODEL` | Default `intfloat/multilingual-e5-small` |
| `EMBEDDING_DIMENSIONS` | Default `384`; must match the model (`bge-m3`: 1024) |
| `AI_RETRIEVER` | `bm25` (default) or `hybrid`: BM25 and vector search fused by RRF (`app/knowledge/vector.py`) |

The `embedding` service in `docker-compose.yml` is TEI (CPU) with no published port. It needs about 2 GB of RAM (1536m was killed while warming up) and 465 MB of weights in the `embeddingdata` volume. The first start downloads the weights from Hugging Face; later starts reuse the volume. Only model files come from Hugging Face; policy text is never sent anywhere. TEI `cpu-1.8` ignores `HF_HUB_OFFLINE`, so a start without internet works only once the volume holds the weights.

```bash
docker compose up -d --no-deps embedding   # first start: downloads the weights
```

`ai` depends on `embedding` as an optional dependency: if it never gets healthy (no weights and no internet, out of memory), `ai` still starts and searches with BM25.

Load the chunks (safe to repeat; the second run embeds nothing):

```bash
# inside the compose network (db and embedding are not published)
docker compose run --rm --no-deps -e AI_DATABASE_URL=postgres://nexus:nexus-dev-only@db:5432/nexus?sslmode=disable ai python -m app.knowledge.ingest
# or from the host, with AI_DATABASE_URL and EMBEDDING_URL pointing at reachable servers
cd ai && .venv/Scripts/python scripts/ingest_knowledge.py [--dry-run]
```

It embeds only new or edited chunks, rewrites title/text/departments of the others, deletes chunks that left the documents (or belong to a `superseded` one), and starts over when `EMBEDDING_MODEL` or `EMBEDDING_DIMENSIONS` changes, so vectors of two models are never mixed. It prints the longest chunk and warns about any that the model would cut at 512 tokens; run it again after adding documents.

Search with vectors: set `AI_RETRIEVER=hybrid` (plus `AI_DATABASE_URL` and `EMBEDDING_URL`, after the chunks are loaded). `search_sop` and the `procedure` branch then get BM25 and the nearest vectors fused by RRF (`core/retrieval.py`, `HybridIndex`); departments are filtered in the SQL query. Whether the documents back a question is still decided on BM25 (`services/procedure.py`), because an RRF score says how a chunk ranks, not how well it matches. Without the database or the embedding server, or when either fails, search falls back to BM25 with a warning and tries vectors again after 30 seconds. Hybrid stays off by default until the RAG eval shows it does no worse than BM25.

The Postgres store has its own tests: `AI_TEST_DATABASE_URL=postgresql://... pytest tests/test_ingest_postgres.py` (throwaway database only: it drops `documents` and `chunks`).

Compare the retrievers on the 40 labelled cases of `evals/rag` (vector and hybrid need both servers reachable from where it runs, with the chunks loaded; a vector failure stops the run rather than falling back to BM25):

```bash
cd ai && .venv/Scripts/python -m evals.rag.run --retriever hybrid [--sweep]   # bm25 (default, offline) | vector | hybrid
```

On `multilingual-e5-small` hybrid matched BM25 (recall@3 1.00, MRR 0.89 vs 0.90) and vectors alone lost most unaccented questions, so `bm25` stays the default; the numbers are in `docs/plan/plan-rag.md` (step 8).
