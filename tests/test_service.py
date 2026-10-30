"""Tests for the router, the chat service, the agents' loops, the auditor and the audit store. Everything the LLM would
do is replaced by a fake, so these make no API calls."""
from types import SimpleNamespace as NS

import pytest
from openai import OpenAIError

from app.agents.agents import GIVE_UP, AuditorAgent, DynamicAgent, RouterAgent, StaticAgent, load_api_tools
from app.http.services import APOLOGY, ChatService, UnknownConversation
from app.mock_api.mock_api import mock_request
from app.repository.db import AuditStore
from app.tools.convo_manager import ConversationManager
from app.tools.tools import ToolDispatcher


class FakeRouter:
    def __init__(self, plan):
        self.plan = plan

    def route(self, message, history):
        return self.plan


class FakeAgent:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def answer(self, query, history):
        self.calls.append(query)
        if self.error:
            raise self.error
        return self.result


class FakeLLM:
    """call_tool returns the given answer; chat_with_tools returns the given messages one after another."""

    def __init__(self, answer=None, messages=(), answers=()):
        self.answer, self.messages, self.answers, self.seen = answer, list(messages), list(answers), []

    def call_tool(self, messages, tool):
        self.seen.append(messages)
        return self.answers.pop(0) if self.answers else self.answer

    def chat_with_tools(self, messages, tools):
        self.seen.append(messages)
        return self.messages.pop(0) if len(self.messages) > 1 else self.messages[0]


def plan(action="answer", queries=(), reply=""):
    return {"action": action, "queries": list(queries), "reply": reply}


def make_service(the_plan, agents):
    return ChatService(FakeRouter(the_plan), agents, ConversationManager())


VENDORS = {"answer": "We have 8 vendors.", "sources": ["GET /vendors"], "tool_calls": [
    {"tool": "list_vendors", "arguments": '{"name": "x"}', "endpoint": "GET /vendors", "ok": True, "result": "{}"}]}
DOCS = {"answer": "Go to Vendors, then Add vendor.", "sources": ["Part 2 > How to add a vendor"]}


# ---------------------------------------------------------------- ChatService

def test_a_turn_returns_the_reply_sources_tool_calls_and_timings():
    agent = FakeAgent(VENDORS)
    service = make_service(plan(queries=[{"agent": "dynamic", "query": "How many vendors are there?"}]), {"dynamic": agent})
    convo = service.begin()
    out = service.send(convo, "How many vendors do we have?")

    assert agent.calls == ["How many vendors are there?"]  # the agent gets the router's rewritten query
    assert (out["route"], out["status"], out["sources"]) == ("dynamic", "active", ["GET /vendors"])
    assert "We have 8 vendors." in out["reply"] and "Sources:" in out["reply"]
    assert out["tool_calls"][0]["arguments"] == {"name": "x"}  # the JSON text is turned into an object for the client
    assert set(out["timings_ms"]) == {"router", "agents", "total"}


def test_a_mixed_question_goes_to_both_agents_and_the_answers_are_combined():
    static, dynamic = FakeAgent(DOCS), FakeAgent(VENDORS)
    queries = [{"agent": "static", "query": "How do I add a vendor?"}, {"agent": "dynamic", "query": "How many vendors?"}]
    service = make_service(plan(queries=queries), {"static": static, "dynamic": dynamic})
    out = service.send(service.begin(), "How do I add a vendor, and how many do we have?")

    assert (static.calls, dynamic.calls) == (["How do I add a vendor?"], ["How many vendors?"])
    assert out["route"] == "static+dynamic"
    assert "Add vendor" in out["reply"] and "8 vendors" in out["reply"]
    assert out["sources"] == ["Part 2 > How to add a vendor", "GET /vendors"]


def test_unsupported_keeps_the_conversation_open_for_the_customers_choice():
    service = make_service(plan("unsupported", reply="I can't help with that. Escalate or end?"), {})
    convo = service.begin()
    out = service.send(convo, "What's our wallet balance?")

    assert (out["route"], out["status"]) == ("unsupported", "active")
    assert out["reply"] == "I can't help with that. Escalate or end?" and out["tool_calls"] == []
    assert len(service.convos.history(convo)) == 2  # still open, the turn was stored


@pytest.mark.parametrize("action, status", [("escalate", "escalated"), ("end", "ended")])
def test_escalate_and_end_close_the_conversation_and_hand_it_to_the_auditor(action, status):
    service = make_service(plan(action, reply="Bye."), {})
    audited = []
    service.audit = audited.append
    convo = service.begin()
    out = service.send(convo, "I want a human" if action == "escalate" else "thanks, bye")

    assert out["status"] == status
    with pytest.raises(KeyError):
        service.convos.history(convo)  # removed from memory
    assert audited[0]["ended_by"] == status and len(audited[0]["traces"]) == 1


def test_an_llm_failure_gets_an_apology_and_the_conversation_stays_open():
    agent = FakeAgent(error=OpenAIError("down"))
    service = make_service(plan(queries=[{"agent": "static", "query": "q"}]), {"static": agent})
    convo = service.begin()
    out = service.send(convo, "How do I add a vendor?")

    assert out["reply"] == APOLOGY and out["route"] == "error" and out["status"] == "active"
    assert service.convos.conversations[convo].traces[0]["error"] == "OpenAIError: down"


def test_a_bug_inside_a_turn_is_an_apology_not_an_unknown_conversation():
    # a KeyError from malformed model output used to surface as "404 unknown conversation"
    service = make_service(plan(queries=[{"agent": "static", "query": "q"}]), {"static": FakeAgent(error=KeyError("sources"))})
    convo = service.begin()
    out = service.send(convo, "How do I add a vendor?")

    assert out["reply"] == APOLOGY and out["route"] == "error"
    assert "KeyError" in service.convos.conversations[convo].traces[0]["error"]


def test_conversations_do_not_share_history():
    service = make_service(plan(queries=[{"agent": "static", "query": "q"}]), {"static": FakeAgent(DOCS)})
    a, b = service.begin(), service.begin()
    service.send(a, "How do I add a vendor?")

    assert a != b
    assert len(service.convos.history(a)) == 2 and service.convos.history(b) == []


def test_an_unknown_conversation_raises_and_ending_twice_is_fine():
    service = make_service(plan("end", reply="Bye."), {})
    with pytest.raises(UnknownConversation):
        service.send("nope", "hi")
    service.end("nope")  # nothing to end, no error


def test_the_auditor_only_runs_for_conversations_that_had_turns():
    calls = []
    service = ChatService(FakeRouter(plan()), {}, ConversationManager(),
                          auditor=NS(audit=lambda record: calls.append(record)), audits=NS())
    service.audit({"id": "x", "ended_by": "client", "traces": []})
    assert calls == []


def test_run_audit_saves_the_verdict_with_the_conversation():
    saved = []
    verdict = {"score": 4, "ended_well": True, "outcome": "resolved", "reasons": "fine", "issues": [], "suggestions": []}
    service = ChatService(FakeRouter(plan()), {}, ConversationManager(),
                          auditor=NS(audit=lambda record: verdict), audits=NS(save=lambda a, r: saved.append((a, r)) or 1))
    service.run_audit({"id": "c1", "ended_by": "client", "traces": [{}], "messages": []})
    assert saved[0][0] == verdict and saved[0][1]["id"] == "c1"


def test_a_failing_audit_never_raises():
    def broken(record):
        raise RuntimeError("auditor down")

    service = ChatService(FakeRouter(plan()), {}, ConversationManager(), auditor=NS(audit=broken), audits=NS())
    service.run_audit({"id": "c1", "ended_by": "client", "traces": [{}], "messages": []})  # logged, not raised


# ---------------------------------------------------------------- RouterAgent

def route(answer, message="the customer's words", history=()):
    llm = FakeLLM(answer)
    return RouterAgent(llm).route(message, list(history)), llm


def test_router_falls_back_to_the_docs_when_it_returns_nothing_usable():
    result, _ = route({"action": "answer", "queries": [{"agent": "nope", "query": "x"}, {"agent": "static", "query": " "}], "reply": ""})
    assert result["queries"] == [{"agent": "static", "query": "the customer's words"}]


def test_router_sends_at_most_two_queries():
    queries = [{"agent": "static", "query": f"q{i}"} for i in range(4)]
    result, _ = route({"action": "answer", "queries": queries, "reply": ""})
    assert len(result["queries"]) == 2


def test_router_rejects_an_unknown_action_after_asking_twice():
    llm = FakeLLM({"action": "shrug", "queries": [], "reply": ""})
    with pytest.raises(ValueError):
        RouterAgent(llm).route("hi", [])
    assert len(llm.seen) == 2


def test_router_asks_again_when_the_first_answer_is_not_an_action():
    llm = FakeLLM(answers=[{"action": "shrug"}, {"action": "end", "queries": [], "reply": "Bye"}])
    assert RouterAgent(llm).route("thanks", [])["action"] == "end"


@pytest.mark.parametrize("agent", ["static", "dynamic"])
def test_router_treats_an_agent_name_in_the_action_field_as_an_answer(agent):
    # this happened for real: {"action": "static", ...}
    result, llm = route({"action": agent, "queries": [], "reply": ""}, message="How do I add a vendor?")
    assert result["action"] == "answer" and result["queries"] == [{"agent": agent, "query": "How do I add a vendor?"}]
    assert len(llm.seen) == 1  # no second attempt was needed


@pytest.mark.parametrize("action", ["unsupported", "escalate", "end"])
def test_router_fills_in_a_reply_and_drops_queries_for_non_answers(action):
    result, _ = route({"action": action, "queries": [{"agent": "static", "query": "x"}]})  # no reply field at all
    assert result["queries"] == [] and result["reply"]


def test_router_sees_the_history_and_the_new_message():
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    _, llm = route({"action": "end", "queries": [], "reply": "Bye"}, message="now", history=history)
    sent = llm.seen[0]
    assert [m["content"] for m in sent[1:]] == ["earlier", "reply", "now"]


# ---------------------------------------------------------------- StaticAgent and DynamicAgent

def test_static_agent_reports_only_the_sections_the_model_says_it_used():
    sections = [{"title": f"Section {n}", "section": f"text {n}"} for n in (1, 2, 3)]
    llm = FakeLLM({"answer": "A", "sources": [2, 9, 2]})  # 9 does not exist, 2 is repeated
    agent = StaticAgent(llm, NS(retrieve=lambda query: sections))
    result = agent.answer("q", [])

    assert result["sources"] == ["Section 2"]
    assert "### [1] Section 1" in llm.seen[0][0]["content"]  # numbered sections are in the prompt


def test_static_agent_copes_with_a_model_that_leaves_out_the_sources():
    sections = [{"title": "Section 1", "section": "text"}]
    agent = StaticAgent(FakeLLM({"answer": "A"}), NS(retrieve=lambda query: sections))
    assert agent.answer("q", [])["sources"] == []
    agent = StaticAgent(FakeLLM({"answer": "A", "sources": ["1", None, 1]}), NS(retrieve=lambda query: sections))
    assert agent.answer("q", [])["sources"] == ["Section 1"]  # only real section numbers count


def test_static_agent_fails_cleanly_when_the_model_gives_no_answer():
    agent = StaticAgent(FakeLLM({"sources": [1]}), NS(retrieve=lambda query: []))
    with pytest.raises(ValueError):
        agent.answer("q", [])


def tool_call(name, arguments, call_id="1"):
    return NS(content=None, tool_calls=[NS(id=call_id, function=NS(name=name, arguments=arguments))])


def dynamic_agent(llm, rounds=6):
    return DynamicAgent(llm, ToolDispatcher(mock_request, load_api_tools()), "2026-09-28", rounds)


def test_dynamic_agent_runs_the_tool_then_answers_from_its_result():
    llm = FakeLLM(messages=[tool_call("list_vendors", '{"name": "Orrery"}'), NS(content="Orrery is in Dublin.", tool_calls=None)])
    result = dynamic_agent(llm).answer("Where is Orrery?", [])

    assert result["answer"] == "Orrery is in Dublin." and result["sources"] == ["GET /vendors"]
    assert result["tool_calls"][0]["ok"] and "Orrery" in result["tool_calls"][0]["result"]
    tool_message = llm.seen[1][-1]  # what the model got back on the second round
    assert tool_message["role"] == "tool" and '"count": 1' in tool_message["content"]


def test_dynamic_agent_gives_up_after_the_round_limit():
    result = dynamic_agent(FakeLLM(messages=[tool_call("list_vendors", "{}")]), rounds=3).answer("loop forever", [])
    assert result["answer"] == GIVE_UP and "3 tool rounds" in result["error"] and len(result["tool_calls"]) == 3


def test_dynamic_agent_hands_tool_errors_back_to_the_model_and_cites_no_source():
    llm = FakeLLM(messages=[tool_call("get_transaction", '{"transaction_id": "txn-nope"}'), NS(content="I don't have access to that.", tool_calls=None)])
    result = dynamic_agent(llm).answer("status of txn-nope", [])

    assert result["sources"] == [] and result["tool_calls"][0]["ok"] is False
    assert "404" in llm.seen[1][-1]["content"]


# ---------------------------------------------------------------- Auditor and audit store

RECORD = {
    "id": "c1", "ended_by": "client",
    "messages": [{"role": "user", "content": "How many vendors?"}, {"role": "assistant", "content": "8"}],
    "traces": [{"query": "How many vendors?", "route": "dynamic", "answer": "8", "sources": ["GET /vendors"],
                "tool_calls": [{"tool": "list_vendors", "arguments": "{}", "endpoint": "GET /vendors", "ok": True, "result": '{"count": 8}'}]}],
}


def test_the_auditor_is_shown_the_tool_calls_and_their_results():
    text = AuditorAgent(FakeLLM()).render(RECORD)
    assert "ended by: client" in text and "list_vendors" in text and '{"count": 8}' in text and "Agent reply: 8" in text


def test_the_auditor_clamps_the_score_and_rejects_an_incomplete_verdict():
    audit = AuditorAgent(FakeLLM({"score": 9, "ended_well": 1, "outcome": "resolved", "reasons": "ok"})).audit(RECORD)
    assert audit["score"] == 5 and audit["ended_well"] is True and audit["issues"] == []
    with pytest.raises(ValueError):
        AuditorAgent(FakeLLM({"ended_well": True, "reasons": "no score"})).audit(RECORD)


def test_audit_store_saves_lists_reviews_and_loads_the_full_record(tmp_path):
    store = AuditStore(tmp_path / "audits.db")
    verdict = {"score": 2, "ended_well": False, "outcome": "unresolved", "reasons": "missed it",
               "issues": [{"turn": 1, "problem": "no detail call"}], "suggestions": ["call the detail tool"]}
    first, second = store.save(verdict, RECORD), store.save({**verdict, "score": 5}, {**RECORD, "id": "c2"})

    assert [a["id"] for a in store.list()] == [second, first]  # newest first
    assert store.get(first)["record"]["id"] == "c1" and store.get(first)["title"] == "How many vendors?"
    assert "record" not in store.list()[0]  # the list view leaves out the full conversation

    assert store.set_review(first, "approved", "agree") and not store.set_review(999, "approved", "")
    assert [a["id"] for a in store.list("pending")] == [second]
    assert store.get(first)["review"] == "approved" and store.get(first)["issues"][0]["turn"] == 1
    assert store.get(999) is None
