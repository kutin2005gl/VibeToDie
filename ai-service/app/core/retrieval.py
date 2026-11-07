"""Retrieval over document chunks. Which documents exist and how they are cut lives in `app.knowledge`.

Queries and chunks go through the same `tokenize`, so a query typed without Vietnamese tone marks
("doi tra 30 ngay") matches text written with them ("đổi trả 30 ngày").
"""

import logging
import math
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

ANY_DEPARTMENT = "*"
# RRF constant: larger k flattens the gap between ranks (60 is the value of the original RRF paper)
RRF_K = 60
# Hits each retriever ranks before fusion, so a chunk ranked low by one retriever can still be lifted by the other
FUSION_CANDIDATES = 20
# After the semantic retriever fails, seconds of BM25 alone before trying it again
SEMANTIC_RETRY_AFTER = 30.0

_WORD = re.compile(r"[a-z0-9]+")

# Function words and question filler, already in `normalize` form. A word is listed only when its unmarked
# form is not also a policy word: "ban" (bạn/bán), "chi" (chị/chi phí), "tai" (tại/tài khoản), "ma" (mà/mã)
# and "vay" (vậy/vay) stay out.
STOPWORDS = frozenset("""
    a cac cua co da duoc bi voi va la thi nay mot nhung khi neu rang hoac se
    gi nao sao khong oi nhe toi minh em
""".split())


@dataclass(frozen=True)
class Chunk:
    """One citable passage. `text` is the exact string a quote is checked against (core/contract.py)."""

    chunk_id: str
    title: str
    departments: tuple[str, ...]
    text: str


class Retriever(Protocol):
    def search(self, query: str, departments, limit: int = 5) -> list[tuple["Chunk", float]]: ...


def visible(chunk: "Chunk", allowed: set[str]) -> bool:
    """May a requester of the `allowed` departments see `chunk`? Nobody sees anything with no department."""
    return bool(allowed) and (ANY_DEPARTMENT in chunk.departments or not allowed.isdisjoint(chunk.departments))


def normalize(text: str) -> str:
    """NFC, lower case, tone and vowel marks dropped, `đ` → `d`: "Hoàn Tiền" → "hoan tien"."""
    text = unicodedata.normalize("NFC", text).lower().replace("đ", "d")
    bare = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", bare)


def tokenize(text: str) -> list[str]:
    """Syllables of `normalize(text)` minus stopwords, then each pair of adjacent ones ("hoan tien" → "hoan_tien")."""
    syllables = [s for s in _WORD.findall(normalize(text)) if s not in STOPWORDS]
    return syllables + [f"{a}_{b}" for a, b in zip(syllables, syllables[1:])]


class Bm25Index:
    """Okapi BM25 over `title` + `text` of `chunks`. `k1` caps how much a repeated term counts; `b` how much
    long chunks are penalised.

    Term statistics cover every chunk, so a chunk scores the same whoever asks; only which chunks are
    scored depends on the requester.
    """

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        if k1 < 0:
            raise ValueError("k1 must be >= 0")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1")
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        self._terms = [Counter(tokenize(f"{c.title}\n{c.text}")) for c in self.chunks]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._avg_length = sum(self._lengths) / len(self.chunks) if self.chunks else 0.0
        df = Counter(term for terms in self._terms for term in terms)
        n = len(self.chunks)
        self._idf = {term: math.log(1 + (n - k + 0.5) / (k + 0.5)) for term, k in df.items()}

    def search(self, query: str, departments, limit: int = 5) -> list[tuple[Chunk, float]]:
        """Chunks visible to `departments` that share a term with `query`, best first, at most `limit`.

        Visibility is checked before scoring, so a chunk outside the requester's departments is never ranked.
        A requester with no department sees nothing, not even `*` chunks.
        """
        allowed = set(departments)
        terms = [t for t in set(tokenize(query)) if t in self._idf]
        if not allowed or not terms or limit <= 0:
            return []
        hits = []
        for i, chunk in enumerate(self.chunks):
            if not visible(chunk, allowed):
                continue
            score = self._score(i, terms)
            if score > 0:
                hits.append((chunk, score))
        hits.sort(key=lambda hit: hit[1], reverse=True)
        return hits[:limit]

    def _score(self, i: int, terms: list[str]) -> float:
        tf, norm = self._terms[i], 1 - self.b + self.b * self._lengths[i] / self._avg_length
        return sum(
            self._idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * norm) for t in terms if t in tf
        )


def reciprocal_rank_fusion(rankings: Iterable[list[Chunk]], k: int = RRF_K) -> list[tuple[Chunk, float]]:
    """Sum of 1 / (k + rank) over the rankings that hold a chunk, best first. Only ranks count, so retrievers whose
    scores live on different scales (BM25, cosine) mix without tuning. A tie keeps the order of the first ranking."""
    if k < 0:
        raise ValueError("k must be >= 0")
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, 1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1 / (k + rank)
            chunks.setdefault(chunk.chunk_id, chunk)
    order = sorted(scores, key=scores.__getitem__, reverse=True)
    return [(chunks[chunk_id], scores[chunk_id]) for chunk_id in order]


class HybridIndex:
    """`lexical` (BM25) and `semantic` (vectors) fused by RRF, behind the same `search` as `Bm25Index`.

    Scores are RRF scores, not BM25: a caller that gates on a BM25 floor uses `lexical` for it. When `semantic`
    raises (database down, embedding server down), the answer is BM25 alone, with one warning, and `semantic`
    is left alone for `retry_after` seconds so every request does not wait on the same timeout.
    """

    def __init__(self, lexical: Bm25Index, semantic: Retriever, k: int = RRF_K,
                 candidates: int = FUSION_CANDIDATES, retry_after: float = SEMANTIC_RETRY_AFTER,
                 clock: Callable[[], float] = time.monotonic):
        if k < 0:
            raise ValueError("k must be >= 0")
        self.lexical = lexical
        self.semantic = semantic
        self.k = k
        self.candidates = candidates
        self.retry_after = retry_after
        self._clock = clock
        self._paused_until = float("-inf")

    @property
    def chunks(self) -> list[Chunk]:
        return self.lexical.chunks

    def search(self, query: str, departments, limit: int = 5) -> list[tuple[Chunk, float]]:
        if limit <= 0:
            return []
        depth = max(limit, self.candidates)
        lexical = self.lexical.search(query, departments, depth)
        semantic = self._semantic(query, departments, depth)
        if semantic is None:
            return lexical[:limit]
        fused = reciprocal_rank_fusion([[c for c, _ in lexical], [c for c, _ in semantic]], self.k)
        return fused[:limit]

    def _semantic(self, query: str, departments, limit: int) -> list[tuple[Chunk, float]] | None:
        if self._clock() < self._paused_until:
            return None
        try:
            hits = self.semantic.search(query, departments, limit)
        except Exception as exc:  # any failure of the second retriever degrades to BM25, never fails the search
            self._paused_until = self._clock() + self.retry_after
            log.warning("vector search failed, using BM25 only for %.0fs: %s: %s",
                        self.retry_after, type(exc).__name__, exc)
            return None
        # Defence in depth: the semantic side filters in SQL, this keeps a bug there from leaking a chunk
        allowed = set(departments)
        return [(c, score) for c, score in hits if visible(c, allowed)]
