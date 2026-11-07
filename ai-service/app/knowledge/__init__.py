"""Knowledge: the company's policy documents (`sop/*.md`), cut into citable chunks.

Each file starts with frontmatter (core/frontmatter.py):
    ---
    doc_id: "QD-CSKH-2026-03"       # file name is doc_id in lower case
    doc_title: "..."
    owner_department: "cskh"
    allowed_roles: ["executive", "cskh"]   # departments that may read it; [*] = everyone
    status: "active"                # active | superseded
    supersedes: []                  # doc_ids
    effective_date: "2026-01-01"
    version: "2.1"
    approved: false                 # true once the owner signs it off
    language: "vi"
    ---

The body is cut at `###` (Khoản); a document without `###` is cut at `##` (Điều). A chunk is cited as
`{doc_id}#{number}`, e.g. `QD-CSKH-2026-03#2.1`. Its `text` is cleaned here and nowhere else, because a
claim's quote is matched against exactly that string.

Superseded documents are listed by `load_documents()` but give no chunks to `load_chunks()`.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.core import frontmatter
from app.core.retrieval import Bm25Index, Chunk, HybridIndex

DIR = Path(__file__).parent / "sop"
STATUSES = ("active", "superseded")
REQUIRED = (
    "doc_id", "doc_title", "owner_department", "allowed_roles", "status", "supersedes",
    "effective_date", "version", "approved", "language",
)
LISTS = ("allowed_roles", "supersedes")

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_NUMBER = {3: re.compile(r"^Khoản\s+(\d+(?:\.\d+)*)"), 2: re.compile(r"^Điều\s+(\d+)")}
_MARKUP = re.compile(r"\*+|`")


class KnowledgeError(ValueError):
    pass


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    owner_department: str
    departments: tuple[str, ...]
    status: str
    supersedes: tuple[str, ...]
    effective_date: str
    version: str
    approved: bool
    language: str
    chunks: tuple[Chunk, ...]


def load_documents() -> list[Document]:
    return [_load(path) for path in sorted(DIR.glob("*.md"))]


def load_chunks() -> list[Chunk]:
    """Chunks of every active document, in file and section order."""
    return [c for doc in load_documents() if doc.status == "active" for c in doc.chunks]


@cache
def sop_index() -> Bm25Index | HybridIndex:
    """The policy index, built on the first search rather than at import; every caller (`search_sop`,
    `procedure.retrieve`) shares it and its database connection. BM25, or hybrid per `AI_RETRIEVER` (vector.py)."""
    from app.knowledge.vector import index_from_env

    return index_from_env(load_chunks())


def _load(path: Path) -> Document:
    name = path.name
    try:
        meta, body = frontmatter.split(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    except frontmatter.FrontmatterError as e:
        raise KnowledgeError(f"{name}: {e}") from e

    missing = [key for key in REQUIRED if key not in meta]
    if missing:
        raise KnowledgeError(f"{name}: frontmatter missing {', '.join(map(repr, missing))}")
    for key in LISTS:
        if not isinstance(meta[key], list):
            raise KnowledgeError(f"{name}: {key} must be a [list]")
    if not meta["allowed_roles"]:
        raise KnowledgeError(f"{name}: allowed_roles is empty")
    if meta["doc_id"].lower() != path.stem:
        raise KnowledgeError(f"{name}: doc_id {meta['doc_id']!r} does not match the file name")
    if meta["status"] not in STATUSES:
        raise KnowledgeError(f"{name}: status must be one of {', '.join(STATUSES)}")
    if meta["approved"] not in ("true", "false"):
        raise KnowledgeError(f"{name}: approved must be true or false")

    departments = tuple(meta["allowed_roles"])
    return Document(
        doc_id=meta["doc_id"],
        title=meta["doc_title"],
        owner_department=meta["owner_department"],
        departments=departments,
        status=meta["status"],
        supersedes=tuple(meta["supersedes"]),
        effective_date=meta["effective_date"],
        version=meta["version"],
        approved=meta["approved"] == "true",
        language=meta["language"],
        chunks=tuple(_chunks(name, meta["doc_id"], meta["doc_title"], departments, body)),
    )


def _chunks(name: str, doc_id: str, doc_title: str, departments: tuple[str, ...], body: str) -> list[Chunk]:
    """Cut `body` at the deepest of `###`/`##` it uses; text outside every chunk is an error, not dropped."""
    lines = body.split("\n")
    level = 3 if any(line.startswith("### ") for line in lines) else 2
    chunks: list[Chunk] = []
    parent = ""  # the current `##` heading when cutting at `###`
    heading, text = "", []

    def close() -> None:
        if not heading:
            return
        m = _NUMBER[level].match(heading)
        if not m:
            raise KnowledgeError(f"{name}: heading {heading!r} has no {'Khoản' if level == 3 else 'Điều'} number")
        cleaned = _clean("\n".join(text))
        if not cleaned:
            raise KnowledgeError(f"{name}: {heading!r} has no text")
        chunk_id = f"{doc_id}#{m.group(1)}"
        if any(c.chunk_id == chunk_id for c in chunks):
            raise KnowledgeError(f"{name}: duplicate section {chunk_id}")
        title = " › ".join(p for p in (doc_title, parent, heading) if p)
        chunks.append(Chunk(chunk_id=chunk_id, title=title, departments=departments, text=cleaned))

    for line in lines:
        m = _HEADING.match(line)
        depth = len(m.group(1)) if m else 0
        if m and depth <= level:
            close()
            heading, text = "", []
            if depth == level:
                heading = _clean(m.group(2))
            elif depth == 2:
                parent = _clean(m.group(2))
        elif heading:
            text.append(m.group(2) if m else line)
        elif line.strip():
            raise KnowledgeError(f"{name}: text outside any section: {line.strip()[:60]!r}")
    close()
    if not chunks:
        raise KnowledgeError(f"{name}: no sections to cut at")
    return chunks


def _clean(text: str) -> str:
    """Drop markdown emphasis and code marks, collapse spaces in each line, drop blank lines."""
    lines = (" ".join(_MARKUP.sub("", line).split()) for line in text.split("\n"))
    return "\n".join(line for line in lines if line)
