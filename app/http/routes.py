from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.http.models import ConversationCreated, MessageRequest, MessageResponse
from app.http.services import ChatService

router = APIRouter()


def get_service(request: Request) -> ChatService:
    return request.app.state.service


@router.get("/health")
def health(request: Request) -> dict:
    if not request.app.state.store.is_ready():
        raise HTTPException(status_code=503, detail="Vector database is not ready")
    return {"status": "ok"}


@router.post("/conversations", response_model=ConversationCreated)
def begin_conversation(service: ChatService = Depends(get_service)) -> ConversationCreated:
    return ConversationCreated(conversation_id=service.begin())


@router.post("/conversations/{convo_id}/messages", response_model=MessageResponse)
def send_message(convo_id: str, body: MessageRequest, service: ChatService = Depends(get_service)) -> MessageResponse:
    try:
        return MessageResponse(**service.send(convo_id, body.message))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown conversation")


@router.delete("/conversations/{convo_id}", status_code=204)
def close_conversation(convo_id: str, service: ChatService = Depends(get_service)) -> Response:
    """Called by the client when it shuts down. Does nothing if the agent already ended the conversation."""
    service.end(convo_id)
    return Response(status_code=204)
