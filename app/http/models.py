from typing import Literal

from pydantic import BaseModel, Field


class ConversationCreated(BaseModel):
    conversation_id: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)


class MessageResponse(BaseModel):
    reply: str
    # "active": keep chatting. "ended" or "escalated": the agent closed the conversation, the client should stop
    status: Literal["active", "ended", "escalated"] = "active"
