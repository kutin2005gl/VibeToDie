import json

import httpx
import pytest

from app.core.llm.embeddings import (
    BATCH_SIZE, EmbeddingConfig, FakeEmbeddingClient, HttpEmbeddingClient,
)
from app.core.llm.errors import LLMAuthError, LLMRequestError, LLMUnavailableError

CONFIG = EmbeddingConfig(url="http://embedding", dimensions=3)


def client(handler):
    return HttpEmbeddingClient(CONFIG, http=httpx.Client(transport=httpx.MockTransport(handler)),
                               sleep=lambda _: None)


def echo(requests):
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        # Reversed on purpose: the client must restore the input order from `index`
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(i), 0.0, 0.0]}
                                                  for i in reversed(range(len(body["input"])))]})
    return handler


def test_queries_and_passages_get_the_e5_prefix():
    sent = []
    c = client(echo(sent))
    c.embed_queries(["đổi máy lỗi"])
    c.embed_passages(["Khách được đổi máy"])
    assert sent[0]["input"] == ["query: đổi máy lỗi"]
    assert sent[1]["input"] == ["passage: Khách được đổi máy"]
    assert sent[0]["model"] == "intfloat/multilingual-e5-small"


def test_fake_client_records_prefixed_texts():
    fake = FakeEmbeddingClient()
    fake.embed_queries(["a"])
    fake.embed_passages(["b"])
    assert fake.seen == ["query: a", "passage: b"]


def test_fake_vectors_are_deterministic_unit_length_and_share_words():
    fake = FakeEmbeddingClient(dimensions=64)
    a, b, c = fake.embed_passages(["hoàn tiền khách hàng", "hoàn tiền khách hàng", "bảo hành pin"])
    assert a == b and len(a) == 64
    assert sum(x * x for x in a) == pytest.approx(1.0)

    def dot(u, v):
        return sum(x * y for x, y in zip(u, v))

    assert dot(a, b) > dot(a, c)


def test_results_come_back_in_input_order_and_batches_are_split():
    sent = []
    vectors = client(echo(sent)).embed_passages([str(i) for i in range(BATCH_SIZE + 1)])
    assert [v[0] for v in vectors[:BATCH_SIZE]] == [float(i) for i in range(BATCH_SIZE)]
    assert [len(r["input"]) for r in sent] == [BATCH_SIZE, 1]


def test_server_errors_are_retried_then_surface_as_unavailable():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(LLMUnavailableError) as e:
        client(handler).embed_queries(["x"])
    assert len(calls) == CONFIG.max_attempts and e.value.attempts == CONFIG.max_attempts


def test_a_transient_failure_is_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0, 1, 0]}]})

    assert client(handler).embed_queries(["x"]) == [[0, 1, 0]]


def test_a_rejected_request_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(413, text="too large")

    with pytest.raises(LLMRequestError):
        client(handler).embed_queries(["x"])
    assert len(calls) == 1


def test_auth_failure_is_its_own_error():
    with pytest.raises(LLMAuthError):
        client(lambda r: httpx.Response(401)).embed_queries(["x"])


def test_wrong_dimensions_are_rejected():
    reply = httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 2]}]})
    with pytest.raises(LLMRequestError, match="dimensions"):
        client(lambda r: reply).embed_queries(["x"])


def test_config_from_env(monkeypatch):
    monkeypatch.delenv("EMBEDDING_URL", raising=False)
    assert EmbeddingConfig.from_env() is None
    monkeypatch.setenv("EMBEDDING_URL", "http://embedding:80/")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1024")
    config = EmbeddingConfig.from_env()
    assert (config.url, config.dimensions) == ("http://embedding:80", 1024)


def test_config_treats_empty_values_as_unset(monkeypatch):
    # .env.example lists EMBEDDING_MODEL= and EMBEDDING_DIMENSIONS= empty
    monkeypatch.setenv("EMBEDDING_URL", "http://embedding:80")
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", " ")
    config = EmbeddingConfig.from_env()
    assert (config.model, config.dimensions) == ("intfloat/multilingual-e5-small", 384)
