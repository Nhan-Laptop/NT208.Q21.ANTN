from typing import Annotated

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.file_attachment import FileAttachment
from app.models.user import User
from app.schemas.admin import AdminOverview, AdminUserOut
from app.schemas.upload import (
    FileAttachmentOut,
    FileListResponse,
    StorageStatsResponse,
)
from app.services.file_service import file_service
from app.services.storage_service import storage_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverview)
def overview(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> AdminOverview:
    """Get admin dashboard overview statistics."""
    _ = current_user
    users = db.query(func.count(User.id)).scalar() or 0
    sessions = db.query(func.count(ChatSession.id)).scalar() or 0
    messages = db.query(func.count(ChatMessage.id)).scalar() or 0
    files = db.query(func.count(FileAttachment.id)).scalar() or 0
    
    # Calculate total storage used
    total_storage = db.query(func.sum(FileAttachment.size_bytes)).scalar() or 0
    
    return AdminOverview(
        users=users,
        sessions=sessions,
        messages=messages,
        files=files,
        total_storage_bytes=total_storage,
        total_storage_mb=round(total_storage / (1024 * 1024), 2),
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
    limit: int = Query(50, ge=1, le=500, description="Maximum users to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[AdminUserOut]:
    """List all users (admin only) with pagination."""
    _ = current_user
    return db.query(User).order_by(User.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/files", response_model=FileListResponse)
def list_all_files(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
    user_id: str | None = Query(None, description="Filter by user ID"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> FileListResponse:
    """List all files in the system (admin only)."""
    query = db.query(FileAttachment)
    
    if user_id:
        query = query.filter(FileAttachment.user_id == user_id)
    if session_id:
        query = query.filter(FileAttachment.session_id == session_id)
    
    total = query.count()
    files = query.order_by(desc(FileAttachment.created_at)).offset(offset).limit(limit).all()
    
    return FileListResponse(
        files=[FileAttachmentOut.model_validate(f) for f in files],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/storage", response_model=StorageStatsResponse)
def get_storage_info(
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> StorageStatsResponse:
    """Get storage backend information and statistics (admin only)."""
    stats = file_service.get_storage_stats()
    log_audit_event(
        event="admin.storage_info",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        outcome="success",
        resource_type="storage",
        details={"storage_type": stats.storage_type.value, "health_status": stats.health_status},
    )
    return StorageStatsResponse(
        storage_type=stats.storage_type.value,
        total_objects=stats.total_objects,
        total_size_bytes=stats.total_size_bytes,
        total_size_mb=round(stats.total_size_bytes / (1024 * 1024), 2),
        bucket_name=stats.bucket_name,
        local_path=stats.local_path,
        health_status=stats.health_status,
    )


@router.delete("/files/{file_id}")
def admin_delete_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> dict:
    """Delete any file from storage (admin only)."""
    attachment = db.query(FileAttachment).filter(FileAttachment.id == file_id).first()
    if not attachment:
        log_audit_event(
            event="admin.delete_file",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="failed",
            resource_type="file",
            resource_id=file_id,
            details={"reason": "not_found"},
        )
        raise HTTPException(status_code=404, detail="File not found")
    
    # Delete from storage
    try:
        storage_service.delete(attachment.storage_key)
    except Exception:
        # Log but continue - file might already be deleted from storage
        pass
    
    # Delete from database
    db.delete(attachment)
    db.commit()
    log_audit_event(
        event="admin.delete_file",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        outcome="success",
        resource_type="file",
        resource_id=file_id,
        details={"file_name": attachment.file_name, "user_id": attachment.user_id},
    )
    
    return {
        "success": True,
        "file_id": file_id,
        "message": "File deleted successfully",
    }


@router.get("/storage/health")
def check_storage_health(
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> dict:
    """Check storage backend health (admin only)."""
    try:
        stats = storage_service.get_stats()
        log_audit_event(
            event="admin.storage_health",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="success",
            resource_type="storage",
            details={"storage_type": stats.storage_type.value, "health": stats.health_status},
        )
        return {
            "status": stats.health_status,
            "storage_type": stats.storage_type.value,
            "accessible": True,
            "details": {
                "total_objects": stats.total_objects,
                "total_size_mb": round(stats.total_size_bytes / (1024 * 1024), 2),
            }
        }
    except Exception as e:
        log_audit_event(
            event="admin.storage_health",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="failed",
            resource_type="storage",
            details={"error": str(e)},
        )
        return {
            "status": "error",
            "storage_type": storage_service.storage_type.value,
            "accessible": False,
            "error": str(e),
        }
