import asyncio
import json
import smtplib

import pytest

from app.core.context import RequestContext
from app.core.tools import ToolError
from app.knowledge import load_chunks
from app.tools import build_tools, mailer

CSKH = RequestContext("u1", ("cskh",))
EXEC = RequestContext("u2", ("executive",))
IT = RequestContext("u3", ("it",))


def run(tool, **args):
    return asyncio.run(tool.run(json.dumps(args)))


def tools(ctx):
    return {tool.name: tool for tool in build_tools(("search_sop", "lookup_order", "lookup_product", "consult"), ctx)}


def test_only_implemented_allowlisted_tools_are_built():
    assert list(tools(CSKH)) == ["search_sop", "lookup_order", "lookup_product"]
    assert build_tools(("query_metrics",), CSKH) == []


def test_lookup_order_returns_flat_json_and_errors_with_hints():
    order = json.loads(run(tools(CSKH)["lookup_order"], order_id="DH1001").content)
    assert order["paid_amount"] == 21990000 and order["delivered_date"] == "2026-10-17"
    missing = run(tools(CSKH)["lookup_order"], order_id="DH9999")
    assert missing.is_error and missing.content.startswith("Error (tool_error)")
    bad = run(tools(CSKH)["lookup_order"], order_id="1001")
    assert bad.content.startswith("Error (invalid_arguments)")


def test_permission_denied_tells_the_model_not_to_look_elsewhere():
    denied = run(tools(IT)["lookup_order"], order_id="DH1001")
    assert denied.is_error and denied.content.startswith("Error (permission_denied)")
    assert "Do not try another tool" in denied.content


def test_search_sop_only_sees_documents_of_the_users_departments():
    query = "hạn mức phê duyệt tài chính từ 10.000.000 VNĐ"
    cskh = json.loads(run(tools(CSKH)["search_sop"], query=query, limit=5).content)
    assert cskh and not any(chunk_id.startswith("QC-BOD-2026-01#") for chunk_id in cskh)
    executive = json.loads(run(tools(EXEC)["search_sop"], query=query).content)
    assert next(iter(executive)) == "QC-BOD-2026-01#2.3"


def test_search_sop_returns_chunks_keyed_by_id():
    hits = json.loads(run(tools(CSKH)["search_sop"], query="đổi trả máy lỗi", limit=2).content)
    assert len(hits) == 2 and all(chunk_id.startswith("QD-CSKH-2026-03#") for chunk_id in hits)
    chunks = {c.chunk_id: c for c in load_chunks()}
    for chunk_id, hit in hits.items():
        assert hit == {"title": chunks[chunk_id].title, "text": chunks[chunk_id].text}
    assert len(json.loads(run(tools(CSKH)["search_sop"], query="đổi trả máy lỗi").content)) == 3
    none = run(tools(CSKH)["search_sop"], query="xyzxyz")
    assert not none.is_error and "No matching document" in none.content


def email(**changes):
    return {"order_id": "DH1002", "to": "binh.tran@example.com", "subject": "Về đơn DH1002",
            "body": "Kính gửi Anh/Chị Bình", **changes}


def send_email(ctx=CSKH):
    [tool] = build_tools(("send_email",), ctx)
    return tool


def approved(tool, key="s1:3:0", **args):
    return asyncio.run(tool.run(json.dumps(args), key))


@pytest.fixture
def sent(monkeypatch):
    out = []

    async def send(to, subject, body, key):
        out.append((to, key))

    monkeypatch.setattr(mailer, "send", send)
    return out


def test_send_email_is_high_risk_and_sends_only_once_approved(sent):
    tool = send_email()
    assert tool.high_risk
    assert run(tool, **email()).is_error and sent == []
    assert approved(tool, **email(to="Binh.Tran@example.com")).content == "Sent."
    assert sent == [("Binh.Tran@example.com", "s1:3:0")]


def test_send_email_goes_only_to_the_orders_customer(sent):
    wrong = approved(send_email(), **email(to="x@attacker.com"))
    assert wrong.is_error and "is not the email" in wrong.content
    denied = approved(send_email(IT), **email())
    assert denied.content.startswith("Error (permission_denied)")
    assert sent == []


def test_send_email_checks_the_address_where_lookup_order_reads_orders(sent, monkeypatch):
    import httpx
    from app.tools import orders
    monkeypatch.setenv("ORDERS_SERVICE_URL", "http://order-service:8080")
    monkeypatch.delenv("ORDERS_GRPC_ADDR", raising=False)
    order = {"order_id": "DH1002", "customer_email": "binh@shop.test"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=order))
    monkeypatch.setattr(orders, "_get_client", lambda base_url, _=None: httpx.AsyncClient(base_url=base_url, transport=transport))
    # The seed's address is not the one order-service has
    assert approved(send_email(), **email()).is_error
    assert approved(send_email(), **email(to="binh@shop.test")).content == "Sent."
    assert sent == [("binh@shop.test", "s1:3:0")]


def test_without_smtp_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    out = approved(send_email(), **email())
    assert out.is_error and "mail is not configured" in out.content


def test_one_action_always_carries_the_same_message_id_and_smtp_errors_are_tool_errors(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("MAIL_FROM", "cskh@shop.test")
    delivered = []
    monkeypatch.setattr(mailer, "_deliver", lambda host, msg: delivered.append(msg))
    for key in ("k1", "k1", "k2"):
        asyncio.run(mailer.send("an@x.test", "s", "b", key))
    ids = [m["Message-ID"] for m in delivered]
    assert ids[0] == ids[1] != ids[2]
    assert (delivered[0]["From"], delivered[0]["To"]) == ("cskh@shop.test", "an@x.test")

    def refused(host, msg):
        raise smtplib.SMTPRecipientsRefused({"an@x.test": (550, b"no such user")})

    monkeypatch.setattr(mailer, "_deliver", refused)
    with pytest.raises(ToolError, match="sending failed"):
        asyncio.run(mailer.send("an@x.test", "s", "b", "k3"))
