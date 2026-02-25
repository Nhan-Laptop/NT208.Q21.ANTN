from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.crypto import crypto_manager
from app.core.database import get_db
from app.models.chat_session import SessionMode
from app.models.user import User
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EncryptedChatCompletionResponse,
    EncryptedPayload,
    MessageOut,
    SessionChatRequest,
)
from app.services.chat_service import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/completions", response_model=ChatCompletionResponse)
def create_completion(
    payload: ChatCompletionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.MESSAGE_WRITE))],
) -> ChatCompletionResponse:
    user_msg, assistant_msg = chat_service.complete_chat(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        user_message=payload.user_message,
        mode_override=payload.mode,
    )
    return ChatCompletionResponse(
        session_id=payload.session_id,
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
    )


@router.post("/{session_id}", response_model=ChatCompletionResponse)
def create_completion_by_session(
    session_id: str,
    payload: SessionChatRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.MESSAGE_WRITE))],
) -> ChatCompletionResponse:
    user_msg, assistant_msg = chat_service.complete_chat(
        db=db,
        current_user=current_user,
        session_id=session_id,
        user_message=payload.user_message,
        mode_override=payload.mode,
    )
    return ChatCompletionResponse(
        session_id=session_id,
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
    )


@router.post("/completions/encrypted", response_model=EncryptedChatCompletionResponse)
def create_completion_encrypted(
    envelope: EncryptedPayload,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.MESSAGE_WRITE))],
) -> EncryptedChatCompletionResponse:
    try:
        body = crypto_manager.decrypt_json(envelope.payload, aad=current_user.id.encode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid encrypted payload") from exc

    session_id = body.get("session_id")
    user_message = body.get("user_message")
    mode_raw = body.get("mode")
    mode_override = SessionMode(mode_raw) if mode_raw else None
    if not session_id or not user_message:
        raise HTTPException(status_code=400, detail="session_id and user_message are required")

    user_msg, assistant_msg = chat_service.complete_chat(
        db=db,
        current_user=current_user,
        session_id=session_id,
        user_message=user_message,
        mode_override=mode_override,
    )

    response_body = {
        "session_id": session_id,
        "user_message": MessageOut.model_validate(user_msg).model_dump(mode="json"),
        "assistant_message": MessageOut.model_validate(assistant_msg).model_dump(mode="json"),
    }
    encrypted = crypto_manager.encrypt_json(response_body, aad=current_user.id.encode("utf-8"))
    return EncryptedChatCompletionResponse(payload=encrypted)
