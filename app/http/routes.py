from fastapi import APIRouter, Depends, HTTPException, Request, Response
from app.http.models import (
    AuditDetail,
    AuditSummary,
    ConversationCreated,
    MessageRequest,
    MessageResponse,
    ReviewRequest,
)
from app.http.services import ChatService, UnknownConversation
from app.repository.db import AuditStore

router = APIRouter()


def get_service(request: Request) -> ChatService:
    return request.app.state.service


def get_audits(request: Request) -> AuditStore:
    return request.app.state.audits


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
    except UnknownConversation:
        raise HTTPException(status_code=404, detail="Unknown conversation")


@router.get("/audits", response_model=list[AuditSummary])
def list_audits(review: str | None = None, audits: AuditStore = Depends(get_audits)) -> list[dict]:
    """Audits of finished conversations, newest first. Use ?review=pending for the ones nobody has looked at."""
    return audits.list(review)


@router.get("/audits/{audit_id}", response_model=AuditDetail)
def get_audit(audit_id: int, audits: AuditStore = Depends(get_audits)) -> dict:
    audit = audits.get(audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Unknown audit")
    return audit


@router.post("/audits/{audit_id}/review", response_model=AuditSummary)
def review_audit(audit_id: int, body: ReviewRequest, audits: AuditStore = Depends(get_audits)) -> dict:
    """The human in the loop: approve or reject the auditor's suggestions. Nothing is changed automatically."""
    if not audits.set_review(audit_id, body.decision, body.note):
        raise HTTPException(status_code=404, detail="Unknown audit")
    return audits.get(audit_id)


@router.delete("/conversations/{convo_id}", status_code=204)
def close_conversation(convo_id: str, service: ChatService = Depends(get_service)) -> Response:
    """Called by the client when it shuts down. Does nothing if the agent already ended the conversation."""
    service.end(convo_id)
    return Response(status_code=204)
