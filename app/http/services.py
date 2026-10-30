import json

from openai import OpenAIError

from app.agents.agents import RouterAgent
from app.tools.convo_manager import ConversationManager
from app.tools.logger import get_logger

log = get_logger(__name__)

APOLOGY = "I'm sorry, I ran into a problem while working on that. Could you try asking again in a moment?"

# what the conversation's status becomes after each router action; unsupported keeps it open for the customer's choice
STATUS_AFTER = {"answer": "active", "unsupported": "active", "escalate": "escalated", "end": "ended"}


class ChatService:
    """One chat turn: look up history, let the router decide, run the agents, store the turn, return the client text."""

    def __init__(self, router: RouterAgent, agents: dict, convos: ConversationManager):
        self.router = router
        self.agents = agents  # {"static": StaticAgent, "dynamic": DynamicAgent}
        self.convos = convos

    def begin(self) -> str:
        return self.convos.begin()

    def send(self, convo_id: str, message: str) -> dict:
        """Returns what the client gets: the reply and status, plus the route, queries, sources and tool calls.
        Status is "active" unless the conversation was ended or escalated."""
        history = self.convos.history(convo_id)  # raises KeyError for an unknown conversation

        plan = None
        try:
            plan = self.router.route(message, history)
            result = self.carry_out(plan, history)
        except (OpenAIError, ValueError) as error:  # the LLM already retried, so apologise and keep the conversation open
            log.error("turn failed in conversation %s: %s", convo_id, error)
            result = {"answer": APOLOGY, "sources": [], "error": str(error)}

        reply = self.convos.add_turn(convo_id, message, self.describe(plan), result)
        status = result.get("status", "active")
        if status != "active":
            self.end(convo_id, ended_by=status)
        return {
            "reply": reply,
            "status": status,
            "route": self.describe(plan),
            "queries": plan["queries"] if plan else [],
            "sources": result["sources"],
            "tool_calls": [self.readable(call) for call in result.get("tool_calls", [])],
        }

    def readable(self, call: dict) -> dict:
        """Tool arguments are stored as the JSON text the model wrote; the client gets them as an object."""
        try:
            arguments = json.loads(call["arguments"])
        except ValueError:
            arguments = None
        return {**call, "arguments": arguments if isinstance(arguments, dict) else {"raw": call["arguments"]}}

    def carry_out(self, plan: dict, history: list[dict]) -> dict:
        if plan["action"] != "answer":  # unsupported, escalate or end: the router already wrote the reply
            return {"answer": plan["reply"], "sources": [], "status": STATUS_AFTER[plan["action"]], "plan": plan}

        results = [self.agents[q["agent"]].answer(q["query"], history) for q in plan["queries"]]
        return {
            "answer": "\n\n".join(r["answer"] for r in results),
            "sources": list(dict.fromkeys(s for r in results for s in r["sources"])),
            "tool_calls": [call for r in results for call in r.get("tool_calls", [])],
            "plan": plan,
        }

    def describe(self, plan: dict | None) -> str:
        """The route label stored in the trace: 'static', 'dynamic', 'static+dynamic', 'unsupported', 'escalate', 'end' or 'error'."""
        if plan is None:
            return "error"
        if plan["action"] == "answer":
            return "+".join(q["agent"] for q in plan["queries"])
        return plan["action"]

    def end(self, convo_id: str, ended_by: str = "client") -> None:
        """Removes the conversation and audits it. Safe to call twice: ending an unknown conversation does nothing."""
        try:
            record = self.convos.end(convo_id)
        except KeyError:
            return
        record["ended_by"] = ended_by
        self.audit(record)

    def audit(self, record: dict) -> None:
        # the auditor agent will score the conversation here, including whether it ended on a good note
        log.info("conversation %s ended by %s after %d turns", record["id"], record["ended_by"], len(record["traces"]))