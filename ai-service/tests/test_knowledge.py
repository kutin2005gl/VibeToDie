import re

import pytest

from app import knowledge
from app.core import frontmatter
from app.knowledge import KnowledgeError

META = """---
doc_id: "QD-DEMO-2026-09"
doc_title: "Quy định mẫu"
owner_department: "cskh"
allowed_roles: ["executive", "cskh"]
status: "active"
supersedes: []
effective_date: "2026-01-01"
version: "1.0"
approved: false
language: "vi"
---
"""

GOOD = META + """
# QUY ĐỊNH MẪU

## Điều 1. Đổi trả

### Khoản 1.1. Đổi máy lỗi
Khách được đổi máy trong **30 ngày**   đầu (*"ví dụ"*), mã `SKU-1`.

- Áp dụng cho máy lỗi phần cứng.

### Khoản 1.2. Phí nhập lại
Thu phí 20%.

## Điều 2. Giao hàng

### Khoản 2.1. Phí giao
Miễn phí nội thành.
"""


@pytest.fixture
def sop_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DIR", tmp_path)
    return tmp_path


def _write(sop_dir, text, stem="qd-demo-2026-09"):
    (sop_dir / f"{stem}.md").write_text(text, encoding="utf-8")


def test_shipped_documents_give_38_chunks():
    """Khoản count per file is fixed in docs/plan/plan-rag.md (bước 1)."""
    docs = {d.doc_id: d for d in knowledge.load_documents()}
    assert {doc_id: len(d.chunks) for doc_id, d in docs.items()} == {
        "QC-BOD-2026-01": 10, "QD-IT-2026-02": 6, "QD-CSKH-2026-03": 7, "QD-VH-2026-04": 8, "QD-KT-2026-05": 7,
    }
    chunks = knowledge.load_chunks()
    assert len(chunks) == 38 and len({c.chunk_id for c in chunks}) == 38
    assert all(d.status == "active" and not d.approved and d.language == "vi" for d in docs.values())


def test_shipped_chunk_ids_match_their_khoan():
    for chunk in knowledge.load_chunks():
        number = chunk.chunk_id.split("#")[1]
        assert re.fullmatch(r"\d+\.\d+", number)
        assert chunk.title.split(" › ")[-1].startswith(f"Khoản {number}.")
        assert chunk.title.split(" › ")[1].startswith(f"Điều {number.split('.')[0]}.")


def test_shipped_departments_come_from_allowed_roles():
    by_doc = {c.chunk_id.split("#")[0]: c.departments for c in knowledge.load_chunks()}
    assert by_doc == {
        "QC-BOD-2026-01": ("executive",), "QD-IT-2026-02": ("executive", "it"),
        "QD-CSKH-2026-03": ("executive", "cskh"), "QD-VH-2026-04": ("executive", "cskh"),
        "QD-KT-2026-05": ("executive",),
    }


def test_shipped_text_has_no_markdown():
    for chunk in knowledge.load_chunks():
        for s in (chunk.text, chunk.title):
            assert "*" not in s and "`" not in s, chunk.chunk_id
            assert "  " not in s and "\n\n" not in s and s == s.strip(), chunk.chunk_id
        assert not any(line.startswith("#") for line in chunk.text.splitlines()), chunk.chunk_id


def test_chunks_are_cut_at_khoan(sop_dir):
    _write(sop_dir, GOOD)
    chunks = knowledge.load_chunks()
    assert [c.chunk_id for c in chunks] == ["QD-DEMO-2026-09#1.1", "QD-DEMO-2026-09#1.2", "QD-DEMO-2026-09#2.1"]
    first = chunks[0]
    assert first.title == "Quy định mẫu › Điều 1. Đổi trả › Khoản 1.1. Đổi máy lỗi"
    assert first.departments == ("executive", "cskh")
    assert first.text == 'Khách được đổi máy trong 30 ngày đầu ("ví dụ"), mã SKU-1.\n- Áp dụng cho máy lỗi phần cứng.'
    assert chunks[2].title == "Quy định mẫu › Điều 2. Giao hàng › Khoản 2.1. Phí giao"


def test_document_without_khoan_is_cut_at_dieu(sop_dir):
    _write(sop_dir, META + "\n# MẪU\n\n## Điều 1. Đổi trả\nĐổi trong 30 ngày.\n\n## Điều 2. Giao hàng\nMiễn phí.\n")
    chunks = knowledge.load_chunks()
    assert [(c.chunk_id, c.title, c.text) for c in chunks] == [
        ("QD-DEMO-2026-09#1", "Quy định mẫu › Điều 1. Đổi trả", "Đổi trong 30 ngày."),
        ("QD-DEMO-2026-09#2", "Quy định mẫu › Điều 2. Giao hàng", "Miễn phí."),
    ]


def test_superseded_document_is_listed_but_not_chunked(sop_dir):
    _write(sop_dir, GOOD)
    _write(sop_dir, GOOD.replace("QD-DEMO-2026-09", "QD-OLD-2025-01").replace('"active"', '"superseded"'), "qd-old-2025-01")
    docs = {d.doc_id: d for d in knowledge.load_documents()}
    assert docs["QD-OLD-2025-01"].status == "superseded" and len(docs["QD-OLD-2025-01"].chunks) == 3
    assert {c.chunk_id.split("#")[0] for c in knowledge.load_chunks()} == {"QD-DEMO-2026-09"}


@pytest.mark.parametrize("key", knowledge.REQUIRED)
def test_missing_frontmatter_field_names_file_and_field(sop_dir, key):
    _write(sop_dir, re.sub(rf"^{key}:.*\n", "", GOOD, flags=re.M))
    with pytest.raises(KnowledgeError, match=rf"qd-demo-2026-09\.md: frontmatter missing '{key}'"):
        knowledge.load_documents()


@pytest.mark.parametrize("broken, msg", [
    (GOOD.replace('doc_id: "QD-DEMO-2026-09"', 'doc_id: "QD-OTHER-2026-09"'), "does not match the file name"),
    (GOOD.replace('status: "active"', 'status: "draft"'), "status must be one of"),
    (GOOD.replace("approved: false", "approved: maybe"), "approved must be"),
    (GOOD.replace('allowed_roles: ["executive", "cskh"]', "allowed_roles: cskh"), "allowed_roles must be"),
    (GOOD.replace('allowed_roles: ["executive", "cskh"]', "allowed_roles: []"), "allowed_roles is empty"),
    (GOOD.replace("### Khoản 1.2. Phí nhập lại", "### Phí nhập lại"), "has no Khoản number"),
    (GOOD.replace("### Khoản 1.2.", "### Khoản 1.1."), "duplicate section"),
    (GOOD.replace("Thu phí 20%.", ""), "has no text"),
    (GOOD.replace("## Điều 2. Giao hàng\n", "## Điều 2. Giao hàng\nLời dẫn.\n"), "text outside any section"),
    (META + "Không có mục nào.\n", "text outside any section"),
    (META, "no sections"),
])
def test_broken_document_is_rejected(sop_dir, broken, msg):
    _write(sop_dir, broken)
    with pytest.raises(KnowledgeError, match=msg):
        knowledge.load_documents()


def test_frontmatter_drops_quotes_around_values_and_items():
    meta, body = frontmatter.split('---\na: "x: y"\nb: [\'p\', "q", r]\nc: it\'s\nd: []\n---\nbody\n')
    assert meta == {"a": "x: y", "b": ["p", "q", "r"], "c": "it's", "d": []}
    assert body == "body\n"
    with pytest.raises(frontmatter.FrontmatterError, match="bad frontmatter line"):
        frontmatter.split("---\nno colon\n---\n")
