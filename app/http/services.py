from openai import OpenAIError

from app.agents.agents import RouterAgent, StaticAgent
from app.tools.convo_manager import ConversationManager
from app.tools.logger import get_logger

log = get_logger(__name__)

APOLOGY = "I'm sorry, I ran into a problem while working on that. Could you try asking again in a moment?"


class ChatService:
    """One chat turn: look up history, route the message, run the agent, store the turn, return the client text."""

    def __init__(self, router: RouterAgent, static_agent: StaticAgent, convos: ConversationManager):
        self.router = router
        self.agents = {"static": static_agent}
        self.convos = convos

    def begin(self) -> str:
        return self.convos.begin()

    def send(self, convo_id: str, message: str) -> tuple[str, str]:
        """Returns (reply for the client, status). Status is "active" unless the agent closed the conversation."""
        history = self.convos.history(convo_id)  # raises KeyError for an unknown conversation
        route = self.router.route(message, history)
        try:
            result = self.agents[route].answer(message, history)
        except (OpenAIError, ValueError) as error:  # the LLM already retried, so apologise and keep the conversation open
            log.error("agent failed in conversation %s: %s", convo_id, error)
            result = {"answer": APOLOGY, "sources": [], "error": str(error)}
        reply = self.convos.add_turn(convo_id, message, route, result)

        status = result.get("status", "active")  # agents will set "ended" or "escalated" when they close a conversation
        if status != "active":
            self.end(convo_id, ended_by=status)
        return reply, status

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
