from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.user import User
from app.schemas.academic import MatchRequestCreate, MatchRequestOut, MatchResultResponse
from app.services.journal_match.service import journal_match_service

router = APIRouter(prefix="/journal-match", tags=["journal-match"])


@router.post("/requests", response_model=MatchRequestOut, status_code=201)
def create_match_request(
    payload: MatchRequestCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> MatchRequestOut:
    if payload.session_id:
        AccessGateway.assert_session_access(db, current_user, payload.session_id)
    return journal_match_service.create_match_request(db, current_user=current_user, payload=payload)


@router.post("/run/{request_id}", response_model=MatchResultResponse)
def run_match_request(
    request_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> MatchResultResponse:
    journal_match_service.run_request(db, current_user=current_user, request_id=request_id)
    result = journal_match_service.get_result(db, current_user=current_user, request_id=request_id)
    return MatchResultResponse(**result)


@router.get("/results/{request_id}", response_model=MatchResultResponse)
def get_match_results(
    request_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> MatchResultResponse:
    result = journal_match_service.get_result(db, current_user=current_user, request_id=request_id)
    return MatchResultResponse(**result)
