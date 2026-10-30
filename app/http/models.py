from typing import Literal

from pydantic import BaseModel, Field


class ConversationCreated(BaseModel):
    conversation_id: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)


class RoutedQuery(BaseModel):
    agent: str  # "static" (help articles) or "dynamic" (account data)
    query: str  # the question as the router rewrote it


class ToolCall(BaseModel):
    tool: str
    arguments: dict
    endpoint: str | None  # the API call that was made, for example "GET /vendors"; None if the call was rejected
    ok: bool


class MessageResponse(BaseModel):
    reply: str  # what to show the customer; includes the Sources list
    # "active": keep chatting. "ended" or "escalated": the conversation was closed, the client should stop
    status: Literal["active", "ended", "escalated"] = "active"

    # what the agent did, so a client can show it
    route: str = ""  # "static", "dynamic", "static+dynamic", "unsupported", "escalate", "end" or "error"
    queries: list[RoutedQuery] = []
    sources: list[str] = []  # help-article sections or API calls the answer is based on
    tool_calls: list[ToolCall] = []