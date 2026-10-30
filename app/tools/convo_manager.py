import uuid
from dataclasses import dataclass, field


@dataclass
class Conversation:
    id: str
    messages: list[dict] = field(default_factory=list)  # only {"role", "content"}: what the LLM sees as history
    traces: list[dict] = field(default_factory=list)  # one per turn: route, sources, tool calls... never sent to the client


class ConversationManager:
    """Keeps every conversation in memory, isolated by id. Decides what the client sees and what stays internal."""

    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}

    def begin(self) -> str:
        convo = Conversation(id=str(uuid.uuid4()))
        self.conversations[convo.id] = convo
        return convo.id

    def history(self, convo_id: str) -> list[dict]:
        return list(self._get(convo_id).messages)

    def add_turn(self, convo_id: str, query: str, route: str, result: dict) -> str:
        """Stores the turn and returns the text to show the client. result is {"answer", "sources", ...}."""
        convo = self._get(convo_id)
        convo.messages.append({"role": "user", "content": query})
        convo.messages.append({"role": "assistant", "content": result["answer"]})
        convo.traces.append({"query": query, "route": route, **result})
        return self._format_reply(result)

    def end(self, convo_id: str) -> dict:
        """Removes the conversation from memory and returns everything, to be handed to the auditor."""
        convo = self.conversations.pop(convo_id)
        return {"id": convo.id, "messages": convo.messages, "traces": convo.traces}

    def _get(self, convo_id: str) -> Conversation:
        if convo_id not in self.conversations:
            raise KeyError(f"unknown conversation {convo_id}")
        return self.conversations[convo_id]

    def _format_reply(self, result: dict) -> str:
        reply = result["answer"]
        if result.get("sources"):
            reply += "\n\nSources:\n" + "\n".join(f"- {s}" for s in result["sources"])
        return reply