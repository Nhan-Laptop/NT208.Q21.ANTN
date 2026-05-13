from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.user import User
from app.schemas.academic import (
    ManuscriptParseRequest,
    ManuscriptParseResponse,
    ManuscriptUploadResponse,
)
from app.services.chat_service import chat_service
from app.services.file_service import file_service
from app.services.journal_match.service import journal_match_service

router = APIRouter(prefix="/manuscripts", tags=["manuscripts"])


@router.post("/upload", response_model=ManuscriptUploadResponse, status_code=201)
async def upload_manuscript(
    session_id: Annotated[str, Form()],
    title: Annotated[str | None, Form()] = None,
    upload: UploadFile = File(...),
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD, Permission.TOOL_EXECUTE))] = None,
) -> ManuscriptUploadResponse:
    AccessGateway.assert_session_access(db, current_user, session_id)
    attachment = await file_service.save_upload(
        db=db,
        current_user=current_user,
        session_id=session_id,
        upload_file=upload,
    )
    linked_message = chat_service.log_file_upload(db, current_user, session_id, attachment)
    attachment.message_id = linked_message.id
    db.add(attachment)
    db.commit()
    db.refresh(attachment)

    manuscript, assessment = journal_match_service.create_manuscript_from_file(
        db,
        current_user=current_user,
        session_id=session_id,
        file_id=attachment.id,
        title=title,
    )
    return ManuscriptUploadResponse(file_id=attachment.id, manuscript=manuscript, assessment=assessment)


@router.post("/parse", response_model=ManuscriptParseResponse, status_code=201)
def parse_manuscript(
    payload: ManuscriptParseRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> ManuscriptParseResponse:
    if payload.file_id and payload.session_id:
        AccessGateway.assert_session_access(db, current_user, payload.session_id)
        manuscript, assessment = journal_match_service.create_manuscript_from_file(
            db,
            current_user=current_user,
            session_id=payload.session_id,
            file_id=payload.file_id,
            title=payload.title,
        )
    elif payload.text:
        manuscript, assessment = journal_match_service.create_manuscript(
            db,
            current_user=current_user,
            text=payload.text,
            session_id=payload.session_id,
            title=payload.title,
            source_type="parse_only",
        )
    else:
        raise HTTPException(status_code=400, detail="Provide file_id + session_id or text.")
    return ManuscriptParseResponse(manuscript=manuscript, assessment=assessment)
