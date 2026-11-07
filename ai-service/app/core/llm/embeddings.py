"""Text embeddings from a self-hosted server (`EMBEDDING_URL`, OpenAI-style `/v1/embeddings`).

Policy text never leaves the machine (REQUIREMENTS.md:187), so there is no hosted dialect here. The
client is synchronous: retrieval (`Bm25Index.search`) is synchronous too.

e5 models were trained with a prefix: `query: ` on a question, `passage: ` on a document. Without it
quality drops clearly, so `embed_queries` / `embed_passages` add it and callers never do.
"""

import hashlib
import math
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.llm.errors import LLMAuthError, LLMError, LLMRequestError, LLMUnavailableError

QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_DIMENSIONS = 384
# Texts per HTTP call: the server rejects a batch above its own limit (TEI: 32 by default)
BATCH_SIZE = 16

_WORD = re.compile(r"\w+", re.UNICODE)


class EmbeddingClient(Protocol):
    model: str
    dimensions: int

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingConfig:
    url: str
    model: str = DEFAULT_MODEL
    dimensions: int = DEFAULT_DIMENSIONS
    timeout: float = 30.0
    max_attempts: int = 3
    backoff_base: float = 0.5

    @classmethod
    def from_env(cls) -> "EmbeddingConfig | None":
        """None when `EMBEDDING_URL` is unset: the caller then stays on BM25."""
        url = os.environ.get("EMBEDDING_URL", "").strip()
        if not url:
            return None
        # Empty counts as unset, as in .env.example
        return cls(url=url.rstrip("/"),
                   model=os.environ.get("EMBEDDING_MODEL", "").strip() or DEFAULT_MODEL,
                   dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "").strip() or DEFAULT_DIMENSIONS))


class HttpEmbeddingClient:
    def __init__(self, config: EmbeddingConfig, *, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.config = config
        self.model = config.model
        self.dimensions = config.dimensions
        self._http = http or httpx.Client(timeout=config.timeout)
        self._sleep = sleep

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([QUERY_PREFIX + t for t in texts])

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([PASSAGE_PREFIX + t for t in texts])

    def _embed(self, prefixed: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(prefixed), BATCH_SIZE):
            out.extend(self._post(prefixed[start:start + BATCH_SIZE]))
        return out

    def _post(self, batch: list[str]) -> list[list[float]]:
        """One request, retried on network errors, 429 and 5xx; any other 4xx is final."""
        last: Exception | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                response = self._http.post(f"{self.config.url}/v1/embeddings",
                                           json={"model": self.model, "input": batch})
            except httpx.TransportError as exc:
                last = exc
            else:
                if response.status_code in (401, 403):
                    raise LLMAuthError(f"embedding server refused the credentials ({response.status_code})",
                                       response.status_code)
                if response.status_code == 429 or response.status_code >= 500:
                    last = LLMError(f"embedding server answered {response.status_code}")
                elif response.status_code >= 400:
                    raise LLMRequestError(f"embedding request rejected ({response.status_code}): "
                                          f"{response.text[:200]}", response.status_code)
                else:
                    return self._vectors(response.json(), len(batch))
            if attempt < self.config.max_attempts:
                self._sleep(self.config.backoff_base * 2 ** (attempt - 1))
        raise LLMUnavailableError(f"embedding server unavailable after {self.config.max_attempts} attempts: {last}",
                                  attempts=self.config.max_attempts)

    def _vectors(self, body: dict, expected: int) -> list[list[float]]:
        data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in data]
        if len(vectors) != expected:
            raise LLMRequestError(f"embedding server returned {len(vectors)} vectors for {expected} texts")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise LLMRequestError(f"embedding has {len(vector)} dimensions, EMBEDDING_DIMENSIONS is {self.dimensions}")
        return vectors


class FakeEmbeddingClient:
    """Deterministic offline vectors: words hashed into buckets, so texts sharing words are close.

    `seen` records every text exactly as it would be sent (prefix included), for tests.
    """

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS, model: str = "fake-embedding") -> None:
        self.dimensions = dimensions
        self.model = model
        self.seen: list[str] = []

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([QUERY_PREFIX + t for t in texts])

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([PASSAGE_PREFIX + t for t in texts])

    def _embed(self, prefixed: list[str]) -> list[list[float]]:
        self.seen.extend(prefixed)
        return [self._vector(text) for text in prefixed]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in _WORD.findall(text.lower()):
            bucket = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % self.dimensions
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def client_from_env() -> EmbeddingClient | None:
    config = EmbeddingConfig.from_env()
    return HttpEmbeddingClient(config) if config else None
