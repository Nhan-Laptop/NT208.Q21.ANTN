from collections.abc import Callable
from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.file_attachment import FileAttachment
from app.models.user import User, UserRole


class Permission(str, Enum):
    SESSION_READ = "session:read"
    SESSION_WRITE = "session:write"
    MESSAGE_WRITE = "message:write"
    TOOL_EXECUTE = "tool:execute"
    FILE_UPLOAD = "file:upload"
    ADMIN_MANAGE = "admin:manage"


ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.ADMIN: {
        Permission.SESSION_READ,
        Permission.SESSION_WRITE,
        Permission.MESSAGE_WRITE,
        Permission.TOOL_EXECUTE,
        Permission.FILE_UPLOAD,
        Permission.ADMIN_MANAGE,
    },
    UserRole.RESEARCHER: {
        Permission.SESSION_READ,
        Permission.SESSION_WRITE,
        Permission.MESSAGE_WRITE,
        Permission.TOOL_EXECUTE,
        Permission.FILE_UPLOAD,
    },
}


class AccessGateway:
    """Gateway for RBAC + ABAC authorization checks."""

    @staticmethod
    def require_permissions(*required: Permission) -> Callable[..., User]:
        def _dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
            role_permissions = ROLE_PERMISSIONS.get(current_user.role, set())
            missing = [perm for perm in required if perm not in role_permissions]
            if missing:
                raise HTTPException(status_code=403, detail=f"Missing permissions: {', '.join(missing)}")
            return current_user

        return _dependency

    @staticmethod
    def assert_session_access(db: Session, current_user: User, session_id: str) -> ChatSession:
        session_obj = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")
        if current_user.is_admin:
            return session_obj
        if session_obj.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="You cannot access this session")
        return session_obj

    @staticmethod
    def assert_message_access(db: Session, current_user: User, message_id: str) -> ChatMessage:
        message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        if current_user.is_admin:
            return message
        session_obj = db.query(ChatSession).filter(ChatSession.id == message.session_id).first()
        if not session_obj or session_obj.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="You cannot access this message")
        return message

    @staticmethod
    def assert_file_access(db: Session, current_user: User, file_id: str) -> FileAttachment:
        file_obj = db.query(FileAttachment).filter(FileAttachment.id == file_id).first()
        if not file_obj:
            raise HTTPException(status_code=404, detail="File not found")
        if current_user.is_admin:
            return file_obj
        if file_obj.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="You cannot access this file")
        return file_obj
