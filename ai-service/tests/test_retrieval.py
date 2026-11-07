import unicodedata

import pytest

from app import knowledge
from app.core.retrieval import STOPWORDS, Bm25Index, Chunk, normalize, tokenize


def test_normalize_drops_marks_and_d():
    assert normalize("Hoàn Tiền ĐỔI TRẢ trong 30 ngày") == "hoan tien doi tra trong 30 ngay"


def test_normalize_same_for_nfc_and_nfd_input():
    text = "Đổi máy lỗi"
    assert normalize(unicodedata.normalize("NFD", text)) == normalize(text) == "doi may loi"


def test_tokenize_adds_bigrams_of_adjacent_syllables():
    assert tokenize("Trả góp 0%") == ["tra", "gop", "0", "tra_gop", "gop_0"]


def test_tokenize_same_with_and_without_marks():
    assert tokenize("phí nhập lại, hoàn tiền") == tokenize("phi nhap lai hoan tien")


def test_tokenize_empty():
    assert tokenize("") == []
    assert tokenize(" ,.- ") == []


@pytest.mark.parametrize("k1, b", [(-0.1, 0.75), (1.5, -0.1), (1.5, 1.1)])
def test_index_rejects_bad_parameters(k1, b):
    with pytest.raises(ValueError):
        Bm25Index([], k1=k1, b=b)


def test_tokenize_drops_stopwords_before_bigrams():
    assert tokenize("Phí của máy") == ["phi", "may", "phi_may"]


def test_tokenize_only_stopwords():
    assert tokenize("thì là của những gì") == []


def test_stopwords_are_in_normalized_form():
    assert all(word == normalize(word) and tokenize(word) == [] for word in STOPWORDS)


def chunk(chunk_id, text, departments=("cskh",), title="Quy định"):
    return Chunk(chunk_id=chunk_id, title=title, departments=departments, text=text)


CHUNKS = [
    chunk("CSKH#1", "Khách được đổi máy lỗi trong 30 ngày đầu."),
    chunk("CSKH#2", "Phí nhập lại máy là 20% khi hoàn tiền."),
    chunk("BOD#1", "Hạn mức phê duyệt hoàn tiền của ban giám đốc.", departments=("executive",)),
    chunk("ALL#1", "Giờ mở cửa cửa hàng từ 8 giờ đến 22 giờ.", departments=("*",)),
    chunk("IT#1", "Đổi mật khẩu.", title="Bảo mật › Khoản 1.1 Tài khoản", departments=("it",)),
]


def ids(hits):
    return [c.chunk_id for c, _ in hits]


def test_search_ranks_best_match_first():
    hits = Bm25Index(CHUNKS).search("đổi máy lỗi bao lâu", ["cskh"])
    assert ids(hits)[0] == "CSKH#1"
    assert [score for _, score in hits] == sorted((score for _, score in hits), reverse=True)


def test_search_scores_title_too():
    assert ids(Bm25Index(CHUNKS).search("tài khoản", ["it"])) == ["IT#1"]


def test_search_filters_departments_before_scoring():
    index = Bm25Index(CHUNKS)
    assert "BOD#1" not in ids(index.search("hạn mức phê duyệt ban giám đốc", ["cskh"]))
    assert ids(index.search("hạn mức phê duyệt ban giám đốc", ["executive"]))[0] == "BOD#1"


def test_search_any_department_chunk_is_visible_to_everyone():
    index = Bm25Index(CHUNKS)
    for departments in (["cskh"], ["it"], ["executive"]):
        assert ids(index.search("giờ mở cửa", departments)) == ["ALL#1"]


def test_search_without_departments_sees_nothing():
    assert Bm25Index(CHUNKS).search("giờ mở cửa", []) == []


def test_search_only_returns_matching_chunks_up_to_limit():
    index = Bm25Index(CHUNKS)
    assert set(ids(index.search("hoàn tiền", ["cskh", "executive"]))) == {"CSKH#2", "BOD#1"}
    assert len(index.search("máy", ["cskh"], limit=1)) == 1
    assert index.search("máy", ["cskh"], limit=0) == []


@pytest.mark.parametrize("query", ["", "   ", "thì là của những gì", "xyz qwerty"])
def test_search_empty_stopword_or_unknown_query_returns_nothing(query):
    assert Bm25Index(CHUNKS).search(query, ["cskh"]) == []


def test_search_on_empty_index():
    assert Bm25Index([]).search("đổi máy", ["cskh"]) == []


# --- On the real policy documents (app/knowledge/sop) ----------------------------------------

@pytest.fixture(scope="module")
def real():
    return Bm25Index(knowledge.load_chunks())


@pytest.mark.parametrize("query, departments, expected", [
    ("phí nhập lại hoàn tiền", ["cskh"], "QD-CSKH-2026-03#2.2"),
    ("bảo hành tối đa bao nhiêu ngày", ["cskh"], "QD-CSKH-2026-03#2.4"),
    ("xác thực OTP đơn trả trước", ["cskh"], "QD-VH-2026-04#2.2"),
    ("phân khu kho logic", ["it"], "QD-IT-2026-02#2.2"),
    ("nghỉ phép năm bao nhiêu ngày", ["executive"], "QC-BOD-2026-01#3.2"),
])
def test_real_ranks_expected_chunk_first(real, query, departments, expected):
    assert ids(real.search(query, departments))[0] == expected


@pytest.mark.parametrize("marked, bare", [
    ("phí nhập lại hoàn tiền", "phi nhap lai hoan tien"),
    ("đổi máy lỗi trong 30 ngày", "doi may loi trong 30 ngay"),
    ("giao hàng hỏa tốc nội thành", "giao hang hoa toc noi thanh"),
])
def test_real_unmarked_query_gives_same_result(real, marked, bare):
    assert real.search(marked, ["cskh"]) == real.search(bare, ["cskh"]) != []


def test_real_cskh_never_gets_executive_only_chunks(real):
    """Ask for every executive-only Khoản by its own title and text: cskh must get none of them."""
    hidden = [c for c in real.chunks if "cskh" not in c.departments]
    assert any(c.chunk_id.startswith("QC-BOD-") for c in hidden)
    for c in hidden:
        for query in (c.title, c.text):
            hits = real.search(query, ["cskh"], limit=len(real.chunks))
            assert all("cskh" in hit.departments for hit, _ in hits), c.chunk_id


def test_real_limit(real):
    assert len(real.search("hoàn tiền", ["executive"])) == 5
    assert len(real.search("hoàn tiền", ["executive"], limit=2)) == 2
    everything = real.search("hoàn tiền", ["executive"], limit=1000)
    assert 5 < len(everything) <= len(real.chunks)
