from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.audit import log_audit_event
from app.core.database import get_db
from app.core.security import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
)
from app.models.user import User
from app.schemas.auth import PromoteUserRequest, Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(user_in: UserCreate, db: Annotated[Session, Depends(get_db)], request: Request) -> UserOut:
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit_event(
        event="auth.register",
        actor_id=user.id,
        actor_role=user.role.value,
        outcome="success",
        resource_type="user",
        resource_id=user.id,
        details={"ip": request.client.host if request.client else None, "email": user.email},
    )
    return user


@router.post("/login", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
) -> Token:
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        log_audit_event(
            event="auth.login",
            actor_id=None,
            actor_role=None,
            outcome="failed",
            resource_type="user",
            details={"ip": request.client.host if request.client else None, "username": form_data.username},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=60 * 24)
    token = create_access_token(subject=user.id, expires_delta=access_token_expires)
    log_audit_event(
        event="auth.login",
        actor_id=user.id,
        actor_role=user.role.value,
        outcome="success",
        resource_type="user",
        resource_id=user.id,
        details={"ip": request.client.host if request.client else None},
    )
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return current_user


@router.post("/admin/promote", response_model=UserOut)
def promote_user(
    payload: PromoteUserRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[
        User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))
    ],
) -> UserOut:
    _ = current_user
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        log_audit_event(
            event="admin.promote_user",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="failed",
            resource_type="user",
            resource_id=payload.user_id,
            details={"reason": "user_not_found", "target_role": payload.role.value},
        )
        raise HTTPException(status_code=404, detail="User not found")
    old_role = user.role.value
    user.role = payload.role
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit_event(
        event="admin.promote_user",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        outcome="success",
        resource_type="user",
        resource_id=user.id,
        details={"old_role": old_role, "new_role": user.role.value},
    )
    return user
