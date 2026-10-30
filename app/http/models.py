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


class AuditIssue(BaseModel):
    turn: int
    problem: str


class AuditSummary(BaseModel):
    """The auditor's verdict on one finished conversation, and the human reviewer's decision on it."""

    id: int
    created_at: str
    conversation_id: str
    ended_by: str  # "client", "ended" or "escalated"
    title: str  # the customer's first question
    score: int  # 1 to 5
    ended_well: bool
    outcome: str
    reasons: str
    issues: list[AuditIssue]
    suggestions: list[str]
    review: str  # "pending", "approved" or "rejected"
    review_note: str


class AuditDetail(AuditSummary):
    record: dict  # the full conversation: messages and traces


class ReviewRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = ""


class MessageResponse(BaseModel):
    reply: str  # what to show the customer; includes the Sources list
    # "active": keep chatting. "ended" or "escalated": the conversation was closed, the client should stop
    status: Literal["active", "ended", "escalated"] = "active"

    # what the agent did, so a client can show it
    route: str = ""  # "static", "dynamic", "static+dynamic", "unsupported", "escalate", "end" or "error"
    queries: list[RoutedQuery] = []
    sources: list[str] = []  # help-article sections or API calls the answer is based on
    tool_calls: list[ToolCall] = []