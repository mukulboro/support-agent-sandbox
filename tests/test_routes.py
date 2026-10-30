"""The HTTP layer, with the chat service replaced by a stub, so no LLM or Qdrant is involved."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.http.routes import router
from app.http.services import UnknownConversation


class StubService:
    def begin(self):
        return "abc"

    def send(self, convo_id, message):
        if convo_id == "gone":
            raise UnknownConversation(convo_id)
        if convo_id == "bug":
            raise KeyError("a real bug, not an unknown conversation")
        return {"reply": "hi", "status": "active", "route": "static", "queries": [], "sources": [], "tool_calls": [],
                "timings_ms": {"router": 1, "agents": 2, "total": 3}}

    def end(self, convo_id):
        pass


def client():
    app = FastAPI()
    app.include_router(router)
    app.state.service = StubService()
    return TestClient(app, raise_server_exceptions=False)


def test_a_message_gets_the_reply_and_the_timings():
    body = client().post("/conversations/abc/messages", json={"message": "hello"}).json()
    assert body["reply"] == "hi" and body["timings_ms"] == {"router": 1, "agents": 2, "total": 3}


def test_only_an_unknown_conversation_is_a_404():
    assert client().post("/conversations/gone/messages", json={"message": "hello"}).status_code == 404
    assert client().post("/conversations/bug/messages", json={"message": "hello"}).status_code == 500  # a bug stays visible


def test_an_empty_message_is_rejected():
    assert client().post("/conversations/abc/messages", json={"message": ""}).status_code == 422


def test_deleting_is_always_204():
    assert client().delete("/conversations/whatever").status_code == 204
