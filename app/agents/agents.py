from pathlib import Path
from typing import TYPE_CHECKING

from app.rag.retriever import Retriever

if TYPE_CHECKING:
    from app.tools.llm import LLM

PROMPTS = Path(__file__).parent / "prompts"


class RouterAgent:
    """Decides which agent handles a message. For now everything goes to the static agent."""

    def route(self, message: str, history: list[dict]) -> str:
        return "static"


class StaticAgent:
    """Answers documentation questions: retrieve sections, put them in the prompt, ask the LLM."""

    def __init__(self, llm: "LLM", retriever: Retriever):
        self.llm = llm
        self.retriever = retriever
        self.prompt = (PROMPTS / "static.md").read_text(encoding="utf-8")

    def answer(self, query: str, history: list[dict]) -> dict:
        """Returns {"answer": str, "sources": [section titles]}. history is a list of {"role", "content"}."""
        sections = self.retriever.retrieve(query)
        context = "\n\n".join(f"### {s['title']}\n{s['section']}" for s in sections)

        messages = [{"role": "system", "content": self.prompt.replace("{context}", context)}]
        messages += history
        messages.append({"role": "user", "content": query})

        return {"answer": self.llm.chat(messages), "sources": [s["title"] for s in sections]}
