import json
import time
from typing import Callable

from openai import OpenAI, OpenAIError

from app.tools.logger import get_logger

log = get_logger(__name__)


class LLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        retries: int = 3,
        reasoning_first: str = "minimal",
        reasoning_retry: str = "medium",
    ):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.retries = retries
        self.reasoning_first = reasoning_first
        self.reasoning_retry = reasoning_retry

    def chat(self, messages: list[dict]) -> str:
        """Returns the reply text."""
        return self._run(messages, self._read_text)

    def call_tool(self, messages: list[dict], tool: dict) -> dict:
        """Forces the model to call `tool` (an OpenAI function definition) and returns the parsed arguments."""
        choice = {"type": "function", "function": {"name": tool["function"]["name"]}}
        return self._run(messages, self._read_tool_arguments, tools=[tool], tool_choice=choice)

    def _run(self, messages: list[dict], read: Callable, **options):
        """First attempt has reasoning off (fast). If it fails or returns something unusable, retry with reasoning on."""
        for attempt in range(1, self.retries + 1):
            reasoning = self.reasoning_first if attempt == 1 else self.reasoning_retry
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages, reasoning_effort=reasoning, **options
                )
                return read(response.choices[0].message)
            except (OpenAIError, ValueError) as error:  # ValueError covers empty replies and bad tool arguments
                log.warning("llm call failed (attempt %d/%d, reasoning=%s): %s", attempt, self.retries, reasoning, error)
                if attempt == self.retries:
                    raise
                time.sleep(attempt)

    def _read_text(self, message) -> str:
        if not message.content:
            raise ValueError("empty reply")
        return message.content

    def _read_tool_arguments(self, message) -> dict:
        if not message.tool_calls:
            raise ValueError("model did not call the tool")
        return json.loads(message.tool_calls[0].function.arguments)  # JSONDecodeError is a ValueError