import asyncio
import json

import pytest

from app.core.agent.loop import QUEUED
from app.core.context import RequestContext
from app.core.contract import Trace, check, report
from app.core.llm.messages import AssistantMessage, ToolCall, ToolResultMessage
from app.tools import build_tools

CSKH = RequestContext("u1", ("cskh",))


def tool_trace(*calls: tuple[str, str, str, bool]) -> Trace:
    """calls: (tool name, call id, result content, is_error)."""
    messages = []
    for name, call_id, content, is_error in calls:
        messages.append(AssistantMessage(tool_calls=(ToolCall(id=call_id, name=name, arguments="{}"),)))
        messages.append(ToolResultMessage(tool_call_id=call_id, content=content, is_error=is_error))
    return Trace.from_messages(messages)


def fact(key, value, call_id, path):
    return {"key": key, "kind": "fact", "value": value, "ref": {"call_id": call_id, "path": path}, "derived_from": [], "reasoning": None}


def conclusion(key, value, derived_from, reasoning):
    return {"key": key, "kind": "conclusion", "value": value, "ref": None, "derived_from": derived_from, "reasoning": reasoning}


def result(*claims, status="done", open_questions=()):
    return {"status": status, "claims": list(claims), "open_questions": list(open_questions)}


ORDER = json.dumps({"paid_amount": 21990000, "delivered_date": "2026-10-17", "status": "delivered"})
TRACE = tool_trace(("lookup_order", "toolu_1", ORDER, False))


def codes(res, trace=TRACE, deliverables=None):
    return [v.code for v in check(res, trace, deliverables)]


def test_trace_names_calls_by_tool_name_and_order():
    trace = tool_trace(("lookup_order", "toolu_a", '{"x": 1}', False), ("lookup_order", "toolu_b", '{"x": 2}', False))
    assert trace.resolve("lookup_order", "x") == 1 and trace.resolve("lookup_order#2", "x") == 2


def test_trace_ignores_final_answer_calls():
    messages = [AssistantMessage(tool_calls=(ToolCall(id="f", name="final_answer", arguments="{}"),))]
    assert check(result(fact("k", 1, "final_answer", "x")), Trace.from_messages(messages))[0].code == "bad_ref"


def test_valid_fact_passes_and_numbers_must_match_exactly():
    assert codes(result(fact("paid", 21990000, "lookup_order", "paid_amount"))) == []
    assert codes(result(fact("paid", 22000000, "lookup_order", "paid_amount"))) == ["value_mismatch"]
    assert codes(result(fact("paid", "21990000", "lookup_order", "paid_amount"))) == ["value_mismatch"]


@pytest.mark.parametrize("call_id, path, message", [
    ("toolu_1", "paid_amount", "there is no source 'toolu_1'"),
    ("lookup_order", "nope", "no key 'nope' (its keys: paid_amount, delivered_date, status)"),
])
def test_unresolvable_ref_is_reported_with_what_exists(call_id, path, message):
    [violation] = check(result(fact("k", 1, call_id, path)), TRACE)
    assert violation.code == "bad_ref" and message in str(violation)


def test_fact_needs_a_ref_and_errors_cannot_back_a_fact():
    no_ref = {**fact("k", 1, "lookup_order", "x"), "ref": None}
    assert codes(result(no_ref)) == ["missing_ref"]
    failed = tool_trace(("lookup_order", "t", "Error (tool_error): order does not exist", True))
    assert codes(result(fact("k", 1, "lookup_order", "x")), failed) == ["bad_ref"]


def test_a_quote_may_be_an_excerpt_of_a_document_chunk():
    chunks = json.dumps({"QD-TEST-2026-01#1.1": {"title": "Đổi trả", "text": "Máy lỗi được đổi\ntrong  7 ngày kể từ ngày nhận."}})
    trace = tool_trace(("search_sop", "t", chunks, False))
    assert codes(result(fact("r", "đổi trong 7 ngày", "search_sop", "QD-TEST-2026-01#1.1")), trace) == []
    assert codes(result(fact("r", "đổi trong 30 ngày", "search_sop", "QD-TEST-2026-01#1.1")), trace) == ["value_mismatch"]
    assert codes(result(fact("r", " ", "search_sop", "QD-TEST-2026-01#1.1")), trace) == ["value_mismatch"]


def test_registered_sources_work_like_tool_calls():
    trace = Trace()
    trace.add("input", {"order_id": "DH1001"})
    trace.add("step:s1", {"stock": 14})
    res = result(fact("o", "DH1001", "input", "order_id"), fact("s", 14, "step:s1", "stock"))
    assert codes(res, trace) == []


def test_a_queued_call_backs_facts_with_the_arguments_staff_will_approve():
    """#142: the step cited the queued send_email and code found no key 'to' in the queued notice."""
    email = {"to": "khach@example.com", "subject": "Hoàn tiền DH1001", "order_id": "DH1001"}
    messages = [AssistantMessage(tool_calls=(ToolCall(id="s1", name="send_email", arguments=json.dumps(email)),)),
                ToolResultMessage(tool_call_id="s1", content=QUEUED)]
    trace = Trace.from_messages(messages)
    assert codes(result(fact("to", "khach@example.com", "send_email", "to"),
                        fact("order", "DH1001", "send_email", "order_id")), trace) == []
    assert codes(result(fact("to", "khac@example.com", "send_email", "to")), trace) == ["value_mismatch"]
    # b10-bare: the model guessed 'result' five times; the error now names the keys it can cite
    [violation] = check(result(fact("status", "queued", "send_email", "result")), trace)
    assert "its keys: to, subject, order_id" in str(violation)
    # A call the tool refused to queue is an error, so it backs nothing
    refused = [messages[0], ToolResultMessage(tool_call_id="s1", content="Error (invalid_arguments): to", is_error=True)]
    assert codes(result(fact("to", "khach@example.com", "send_email", "to")), Trace.from_messages(refused)) == ["bad_ref"]


def test_conclusion_rules():
    base = fact("delivered", "2026-10-17", "lookup_order", "delivered_date")
    good = conclusion("deadline", "hết 2026-10-24", ["delivered"], "Giao 2026-10-17 cộng 7 ngày thì đến 2026-10-24.")
    assert codes(result(base, good)) == ["invented_number"]  # 7 is in no basis claim
    window = fact("window", "trong 7 ngày", "search_sop", "QD-TEST-2026-01#1.1")
    trace = tool_trace(("lookup_order", "a", ORDER, False),
                       ("search_sop", "b", json.dumps({"QD-TEST-2026-01#1.1": {"title": "t", "text": "đổi trong 7 ngày"}}), False))
    assert codes(result(base, window, {**good, "derived_from": ["delivered", "window"]}), trace) == []
    assert codes(result(base, {**good, "derived_from": []}), trace) == ["missing_basis", "invented_number"]
    assert "bad_basis" in codes(result(base, {**good, "derived_from": ["ghost"]}), trace)
    # A number the task gave (today's date) is not invented
    today = conclusion("days", "đã 9 ngày", ["delivered"], "Giao 2026-10-17, hôm nay 2026-10-26 nên đã 9 ngày.")
    assert codes(result(base, today)) == ["invented_number"]  # 26 is in no basis claim
    assert check(result(base, today), TRACE, given="<today>2026-10-26</today>") == []
    assert "missing_reasoning" in codes(result(base, {**good, "reasoning": " "}), trace)
    assert "conclusion_has_ref" in codes(result(base, {**good, "ref": {"call_id": "x", "path": "y"}}), trace)


def test_thousand_separators_do_not_count_as_new_numbers():
    paid = fact("paid", 21990000, "lookup_order", "paid_amount")
    ok = conclusion("c", "đã trả đủ", ["paid"], "Khách đã trả 21.990.000 đồng.")
    assert codes(result(paid, ok)) == []


def test_findings_must_cite_existing_claims_and_cover_their_numbers():
    window = fact("window", "đổi trong 7 ngày", "search_sop", "QD-TEST-2026-01#1.1")
    trace = tool_trace(("search_sop", "t", json.dumps({"QD-TEST-2026-01#1.1": {"title": "t", "text": "đổi trong 7 ngày"}}), False))

    def with_findings(*findings):
        return {**result(window), "findings": list(findings)}

    ok = {"text": "Máy lỗi được đổi trong 7 ngày", "claims": ["window"]}
    assert codes(with_findings(ok), trace) == []
    assert codes(with_findings({"text": "Máy lỗi được đổi", "claims": ["ghost"]}), trace) == ["bad_finding_basis"]
    assert codes(with_findings({"text": "Được đổi trong 30 ngày", "claims": ["window"]}), trace) == ["invented_number"]
    [violation] = check(with_findings({"text": "Được đổi trong 30 ngày", "claims": ["window"]}), trace)
    assert "30" in str(violation) and "Được đổi trong 30 ngày" in str(violation)


def test_a_finding_may_name_digits_from_any_claim_or_the_task():
    """Eval traces: most rejections were ids and names ("DH261028014970", "iPhone 16 128GB", "Quận 1")."""
    order = json.dumps({"status": "shipping", "product_name": "iPhone 16 128GB", "store": "CN Quận 1"})
    trace = tool_trace(("lookup_order", "t", order, False))
    claims = result(fact("status", "shipping", "lookup_order", "status"),
                    fact("product", "iPhone 16 128GB", "lookup_order", "product_name"),
                    fact("store", "CN Quận 1", "lookup_order", "store"))
    text = {"text": "Đơn DH261028014970 (iPhone 16 128GB, CN Quận 1) đang giao", "claims": ["status"]}
    res = {**claims, "findings": [text]}
    assert codes(res, trace) == ["invented_number"]  # the order id is in no claim
    assert check(res, trace, given="Tra đơn DH261028014970") == []
    # A number from nowhere is still caught
    made_up = {"text": "Đơn DH261028014970 giao trong 3 ngày", "claims": ["status"]}
    assert codes({**claims, "findings": [made_up]}, trace) == ["invented_number"]


def test_the_verifier_takes_the_task_from_the_user_messages():
    from app.core.contract import verifier
    from app.core.llm.messages import UserMessage
    res = {**result(fact("status", "shipping", "lookup_order", "status")),
           "findings": [{"text": "Đơn DH261028014970 đang giao", "claims": ["status"]}]}
    history = [UserMessage(content="<task>Tra đơn DH261028014970</task>"),
               AssistantMessage(tool_calls=(ToolCall(id="t", name="lookup_order", arguments="{}"),)),
               ToolResultMessage(tool_call_id="t", content='{"status": "shipping"}')]
    assert verifier()(res, history) is None
    assert "261028014970" in verifier()(res, history[1:])


def test_a_text_result_has_no_keys():
    [violation] = check(result(fact("k", 1, "lookup_order", "x")), tool_trace(("lookup_order", "t", "plain text", False)))
    assert "returned plain text" in str(violation)


def test_cyclic_basis_is_reported():
    a = conclusion("a", "x", ["b"], "từ b")
    b = conclusion("b", "y", ["a"], "từ a")
    assert "cyclic_basis" in codes(result(a, b))


def test_duplicate_keys():
    one = fact("k", 21990000, "lookup_order", "paid_amount")
    assert codes(result(one, one)) == ["duplicate_key"]


def test_deliverables_and_status():
    paid = fact("paid", 21990000, "lookup_order", "paid_amount")
    wants = [{"key": "paid", "kind": "fact"}, {"key": "refund", "kind": "conclusion"}]
    assert codes(result(paid), deliverables=wants) == ["missing_deliverable"]
    wrong = fact("refund", 1, "lookup_order", "paid_amount")
    assert codes(result(paid, wrong), deliverables=wants) == ["value_mismatch", "wrong_kind"]
    null = {**paid, "key": "refund", "kind": "conclusion", "value": None, "ref": None}
    assert codes(result(paid, null), deliverables=wants) == ["status_mismatch"]
    assert codes(result(paid, null, status="partial"), deliverables=wants) == ["missing_open_questions"]
    assert codes(result(paid, null, status="partial", open_questions=["thiếu quy định"]), deliverables=wants) == []
    assert codes(result(status="blocked")) == ["missing_open_questions"]


def run(tool, **args):
    return asyncio.run(tool.run(json.dumps(args))).content


def test_real_customer_result_from_the_first_live_run_passes_with_tool_names():
    """The result Sonnet gave for DH1001, with call ids replaced by tool names as the contract now says,
    and the return rule moved from the old seed (7 days from delivery) to QD-CSKH-2026-03 (30 days from invoice)."""
    tools = {tool.name: tool for tool in build_tools(("search_sop", "lookup_order", "lookup_product"), CSKH)}
    trace = tool_trace(
        ("lookup_order", "t1", run(tools["lookup_order"], order_id="DH1001"), False),
        ("search_sop", "t2", run(tools["search_sop"], query="đổi trả hoàn tiền máy lỗi", limit=5), False),
        ("lookup_product", "t3", run(tools["lookup_product"], product_id="P001"), False),
    )
    quote = ("đổi ngay 01 máy mới 100% cùng model (cùng mã SKU) hoàn toàn miễn phí trong vòng 30 ngày đầu tiên "
             "kể từ ngày xuất hóa đơn nếu thiết bị phát sinh lỗi phần cứng từ Nhà sản xuất")
    res = result(
        fact("order_date", "2026-10-15", "lookup_order", "order_date"),
        fact("sop_return", quote, "search_sop", "QD-CSKH-2026-03#2.1"),
        fact("stock", 14, "lookup_product", "stock_total"),
        conclusion("return_window", "Hạn đổi máy đến hết 2026-11-14", ["order_date", "sop_return"],
                   "Ngày đặt hàng 2026-10-15 (hóa đơn xuất cùng ngày) cộng 30 ngày theo quy định đổi máy cho hạn 2026-11-14."),
        status="partial", open_questions=["Khách báo lỗi ngày nào?"],
    )
    assert check(res, trace) == []


def test_report_lists_every_violation_for_the_model():
    violations = check(result(fact("paid", 1, "lookup_order", "paid_amount"), fact("k", 1, "ghost", "x")), TRACE)
    text = report(violations)
    assert text.count("\n") == 1 and all(line.startswith("- claim '") for line in text.splitlines())
    assert "claim 'paid'" in text and "claim 'k'" in text
