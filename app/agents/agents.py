import json
from pathlib import Path

import yaml

from app.rag.retriever import Retriever
from app.tools.llm import LLM
from app.tools.tools import ToolDispatcher

AGENTS = Path(__file__).parent

GIVE_UP = "I'm sorry, I couldn't finish looking that up. Could you narrow the question down a little?"

AGENT_NAMES = ("static", "dynamic")
MAX_QUERIES = 2  # one per agent is the most a single message needs
DEFAULT_REPLIES = {
    "unsupported": "I'm sorry, I can't help with that here. Would you like me to escalate this to a human, or end the conversation?",
    "escalate": "I'm passing this to a human colleague who will follow up with you.",
    "end": "Glad I could help. Goodbye!",
}


def load_tool(name: str) -> dict:
    """Reads agents/tools/<name>.yaml and returns it as an OpenAI function definition."""
    definition = yaml.safe_load((AGENTS / "tools" / f"{name}.yaml").read_text(encoding="utf-8"))
    return {"type": "function", "function": definition}


def load_api_tools() -> list[dict]:
    """Reads the dynamic agent's tool definitions from agents/tools/api_tools.yaml."""
    return yaml.safe_load((AGENTS / "tools" / "api_tools.yaml").read_text(encoding="utf-8"))


class RouterAgent:
    """Reads the latest message and the history and decides what happens: answer (which agents, which queries),
    unsupported (we cannot do this), escalate or end."""

    def __init__(self, llm: LLM):
        self.llm = llm
        self.prompt = (AGENTS / "prompts" / "router.md").read_text(encoding="utf-8")
        self.tool = load_tool("route_message")

    def route(self, message: str, history: list[dict]) -> dict:
        """Returns {"action": "answer" | "unsupported" | "escalate" | "end", "queries": [{"agent", "query"}], "reply": str}."""
        messages = [{"role": "system", "content": self.prompt}] + history + [{"role": "user", "content": message}]
        plan = self.llm.call_tool(messages, self.tool)

        action = plan.get("action")
        if action not in ("answer", "unsupported", "escalate", "end"):
            raise ValueError(f"router returned an unknown action: {action!r}")

        # the model does not always fill every field, so read the optional ones defensively
        queries = [q for q in plan.get("queries") or [] if q.get("agent") in AGENT_NAMES and q.get("query", "").strip()]
        queries = queries[:MAX_QUERIES]
        if action == "answer" and not queries:
            queries = [{"agent": "static", "query": message}]  # nothing usable came back: fall back to the help articles
        reply = (plan.get("reply") or "").strip() or DEFAULT_REPLIES.get(action, "")
        return {"action": action, "queries": queries if action == "answer" else [], "reply": reply}


class StaticAgent:
    """Answers documentation questions: retrieve sections, put them in the prompt, let the LLM answer via a tool call."""

    def __init__(self, llm: LLM, retriever: Retriever):
        self.llm = llm
        self.retriever = retriever
        self.prompt = (AGENTS / "prompts" / "static.md").read_text(encoding="utf-8")
        self.tool = load_tool("answer_question")

    def answer(self, query: str, history: list[dict]) -> dict:
        """Returns {"answer": str, "sources": [titles of the sections the LLM says it used]}."""
        sections = self.retriever.retrieve(query)
        context = "\n\n".join(f"### [{n}] {s['title']}\n{s['section']}" for n, s in enumerate(sections, start=1))

        messages = [{"role": "system", "content": self.prompt.replace("{context}", context)}]
        messages += history
        messages.append({"role": "user", "content": query})

        result = self.llm.call_tool(messages, self.tool)
        used = [n for n in result["sources"] if 1 <= n <= len(sections)]  # ignore numbers the LLM made up
        return {"answer": result["answer"], "sources": [sections[n - 1]["title"] for n in dict.fromkeys(used)]}


class DynamicAgent:
    """Answers questions about the customer's own data: the LLM asks for API tools, we run them, until it can answer."""

    def __init__(self, llm: LLM, dispatcher: ToolDispatcher, today: str, max_rounds: int = 6):
        self.llm = llm
        self.dispatcher = dispatcher
        self.max_rounds = max_rounds
        self.prompt = (AGENTS / "prompts" / "dynamic.md").read_text(encoding="utf-8").replace("{today}", today)

    def answer(self, query: str, history: list[dict]) -> dict:
        """Returns {"answer", "sources": [API calls that succeeded], "tool_calls": [every call made, for the trace]}."""
        messages = [{"role": "system", "content": self.prompt}] + history + [{"role": "user", "content": query}]
        tool_calls = []

        for _ in range(self.max_rounds):
            message = self.llm.chat_with_tools(messages, self.dispatcher.schemas())
            if not message.tool_calls:
                return self.result(message.content, tool_calls)

            messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in message.tool_calls
                ],
            })
            for call in message.tool_calls:
                outcome = self.dispatcher.run(call.function.name, call.function.arguments)
                tool_calls.append({
                    "tool": call.function.name,
                    "arguments": call.function.arguments,
                    "endpoint": outcome["endpoint"],
                    "ok": outcome["ok"],
                })
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(outcome["output"])})

        return self.result(GIVE_UP, tool_calls, error=f"no answer after {self.max_rounds} tool rounds")

    def result(self, answer: str, tool_calls: list[dict], error: str | None = None) -> dict:
        sources = [c["endpoint"] for c in tool_calls if c["ok"]]
        result = {"answer": answer, "sources": list(dict.fromkeys(sources)), "tool_calls": tool_calls}
        if error:
            result["error"] = error
        return result
