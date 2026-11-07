"""The procedure branch: policy passages found for a question before the knowledge agent runs."""

from app.core.context import RequestContext
from app.core.retrieval import tokenize
from app.knowledge import sop_index

# A passage counts as relevant when it scores at least MIN_RETRIEVAL_SCORE (BM25) and holds at least
# MIN_QUESTION_COVERAGE of the question's syllables; when none does, nothing in the documents backs the question.
# Set by the RAG eval (plan-rag step 6): see its Tiến độ entry for the measurements.
# Both are judged on BM25 even with the hybrid index: RRF scores only say how a chunk ranks, never how well it
# matches (the nearest vector is always "first"), so they cannot carry a no-basis floor. Hybrid changes which
# passages the agent gets, not whether the documents back the question; a vector-based floor needs the eval first.
MIN_RETRIEVAL_SCORE = 10.0
MIN_QUESTION_COVERAGE = 0.55
# Passages put in the agent's <retrieved> block
RETRIEVE_LIMIT = 4
# Shown to staff when no passage backs the question; the model is not called
NO_BASIS = "Không tìm thấy quy định liên quan trong tài liệu bạn được xem."


def retrieve(text: str, ctx: RequestContext) -> dict[str, dict[str, str]]:
    """Relevant passages of the documents the requester may see, best first: {chunk_id: {title, text}}.

    Same shape as `search_sop` returns, so a claim cites either with ref.path = chunk_id.
    """
    index = sop_index()
    hits = index.search(text, ctx.departments, RETRIEVE_LIMIT)
    # The BM25 side of a hybrid index, or the index itself when it is BM25
    lexical = getattr(index, "lexical", index)
    best_lexical = lexical.search(text, ctx.departments, 1) if lexical is not index else hits[:1]
    asked = {t for t in tokenize(text) if "_" not in t}
    if not hits or not best_lexical or not asked:
        return {}
    # Score alone lets a question that only shares generic words with a long passage through; coverage catches
    # it, since the rest of the question is missing from the passage. Only the best hit is judged, and the rest
    # of the top hits go to the agent with it: the right passage may rank second and score below the floor
    best, score = best_lexical[0]
    covered = len(asked & set(tokenize(f"{best.title}\n{best.text}")))
    if score < MIN_RETRIEVAL_SCORE or covered / len(asked) < MIN_QUESTION_COVERAGE:
        return {}
    return {c.chunk_id: {"title": c.title, "text": c.text} for c, _ in hits}
