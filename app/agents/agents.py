from pathlib import Path

import yaml

from app.rag.retriever import Retriever
from app.tools.llm import LLM

AGENTS = Path(__file__).parent


def load_tool(name: str) -> dict:
    """Reads agents/tools/<name>.yaml and returns it as an OpenAI function definition."""
    definition = yaml.safe_load((AGENTS / "tools" / f"{name}.yaml").read_text(encoding="utf-8"))
    return {"type": "function", "function": definition}


class RouterAgent:
    """Decides which agent handles a message. For now everything goes to the static agent."""

    def route(self, message: str, history: list[dict]) -> str:
        return "static"


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