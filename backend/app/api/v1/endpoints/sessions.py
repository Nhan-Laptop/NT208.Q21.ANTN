from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.chat_session import ChatSession
from app.models.user import User
from app.schemas.chat import MessageOut, SessionCreate, SessionOut, SessionUpdate
from app.services.chat_service import chat_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut, status_code=201)
def create_session(
    payload: SessionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.SESSION_WRITE))],
) -> SessionOut:
    return chat_service.create_session(db, current_user, payload.title, payload.mode)


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.SESSION_READ))],
    limit: int = Query(50, ge=1, le=200, description="Max sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[SessionOut]:
    return chat_service.list_sessions(db, current_user, limit=limit, offset=offset)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.SESSION_READ))],
) -> SessionOut:
    session_obj = AccessGateway.assert_session_access(db, current_user, session_id)
    return session_obj


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(
    session_id: str,
    payload: SessionUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.SESSION_WRITE))],
) -> SessionOut:
    session_obj = AccessGateway.assert_session_access(db, current_user, session_id)
    
    if payload.title is not None:
        session_obj.title = payload.title
    if payload.mode is not None:
        session_obj.mode = payload.mode
    
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)
    return session_obj


@router.delete("/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.SESSION_WRITE))],
) -> None:
    session_obj = AccessGateway.assert_session_access(db, current_user, session_id)
    db.delete(session_obj)
    db.commit()


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def list_messages(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.SESSION_READ))],
    limit: int = Query(200, ge=1, le=1000, description="Max messages to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[MessageOut]:
    return chat_service.list_messages(db, current_user, session_id, limit=limit, offset=offset)
