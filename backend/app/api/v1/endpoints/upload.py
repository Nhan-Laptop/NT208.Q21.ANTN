import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.user import User
from app.schemas.upload import (
    FileAttachmentOut,
    FileDeleteResponse,
    FileListResponse,
    FileUploadResponse,
    PreSignedDownloadResponse,
    PreSignedUploadRequest,
    PreSignedUploadResponse,
    StorageStatsResponse,
    UserStorageStatsResponse,
)
from app.services.chat_service import chat_service
from app.services.file_service import file_service

router = APIRouter(prefix="/upload", tags=["upload"])
_logger = logging.getLogger(__name__)


@router.post("", response_model=FileUploadResponse)
async def upload_file(
    session_id: Annotated[str, Form()],
    message_id: Annotated[str | None, Form()] = None,
    upload: UploadFile = File(...),
    db: Annotated[Session, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))] = None,
) -> FileUploadResponse:
    """
    Upload a file to storage.
    
    - Files are automatically encrypted with AES-256-GCM
    - PDF files have text extracted for search/summarization
    - Files are linked to the specified session
    """
    AccessGateway.assert_session_access(db, current_user, session_id)
    attachment = await file_service.save_upload(
        db=db,
        current_user=current_user,
        session_id=session_id,
        upload_file=upload,
        message_id=message_id,
    )
    
    # Link to message if provided
    if message_id:
        message = AccessGateway.assert_message_access(db, current_user, message_id)
        tool_results = message.tool_results if isinstance(message.tool_results, dict) else {}
        attachments = tool_results.get("attachments", [])
        attachments.append({
            "attachment_id": attachment.id,
            "file_name": attachment.file_name,
            "mime_type": attachment.mime_type,
            "storage_url": attachment.storage_url,
        })
        tool_results["attachments"] = attachments
        message.tool_results = tool_results
        db.add(message)
        db.commit()
    else:
        # Create a system message for the file upload
        linked_message = chat_service.log_file_upload(db, current_user, session_id, attachment)
        attachment.message_id = linked_message.id
        db.add(attachment)
        db.commit()
        db.refresh(attachment)

    log_audit_event(
        event="file.upload",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        outcome="success",
        resource_type="file",
        resource_id=attachment.id,
        details={
            "session_id": session_id,
            "file_name": attachment.file_name,
            "size_bytes": attachment.size_bytes,
            "mime_type": attachment.mime_type,
        },
    )

    return FileUploadResponse(
        id=attachment.id,
        session_id=attachment.session_id,
        message_id=attachment.message_id,
        file_name=attachment.file_name,
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes,
        storage_url=attachment.storage_url,
        storage_encrypted=attachment.storage_encrypted,
        storage_encryption_alg=attachment.storage_encryption_alg,
        created_at=attachment.created_at,
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))],
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> FileListResponse:
    """
    List files for the current user.
    
    - Admins can see all files
    - Regular users can only see their own files
    - Optional filter by session_id
    """
    files = file_service.list_user_files(
        db=db,
        current_user=current_user,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )

    # Get accurate total count for pagination
    total = file_service.count_user_files(db, current_user, session_id=session_id)
    
    return FileListResponse(
        files=[FileAttachmentOut.model_validate(f) for f in files],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats/me", response_model=UserStorageStatsResponse)
async def get_my_storage_stats(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))],
) -> UserStorageStatsResponse:
    """Get storage statistics for the current user."""
    stats = file_service.get_user_storage_stats(db, current_user)
    return UserStorageStatsResponse(
        total_files=stats.total_files,
        total_size_bytes=stats.total_size_bytes,
        total_size_mb=round(stats.total_size_bytes / (1024 * 1024), 2),
        encrypted_files=stats.encrypted_files,
        by_mime_type=stats.by_mime_type,
    )


@router.get("/stats/storage", response_model=StorageStatsResponse)
async def get_storage_stats(
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> StorageStatsResponse:
    """Get overall storage statistics (admin only)."""
    stats = file_service.get_storage_stats()
    return StorageStatsResponse(
        storage_type=stats.storage_type.value,
        total_objects=stats.total_objects,
        total_size_bytes=stats.total_size_bytes,
        total_size_mb=round(stats.total_size_bytes / (1024 * 1024), 2),
        bucket_name=stats.bucket_name,
        local_path=stats.local_path,
        health_status=stats.health_status,
    )


@router.get("/{file_id}", response_class=Response)
async def download_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))],
) -> Response:
    """
    Download a file by ID.
    
    - Automatically decrypts if stored encrypted
    - Validates user has access to the file
    """
    attachment = AccessGateway.assert_file_access(db, current_user, file_id)
    
    try:
        file_bytes = file_service.download_file(attachment)
    except Exception as e:
        _logger.exception("File download failed for file_id=%s", file_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve file")
    
    return Response(
        content=file_bytes,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.file_name}"',
            "Content-Length": str(len(file_bytes)),
        },
    )


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))],
) -> FileDeleteResponse:
    """
    Delete a file from storage.
    
    - Removes file from storage backend (S3 or local)
    - Removes database record
    - User must own the file or be admin
    """
    try:
        file_service.delete_file(db, current_user, file_id)
        log_audit_event(
            event="file.delete",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="success",
            resource_type="file",
            resource_id=file_id,
            details={},
        )
        return FileDeleteResponse(
            success=True,
            file_id=file_id,
            message="File deleted successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@router.post("/presigned-upload", response_model=PreSignedUploadResponse)
async def get_presigned_upload_url(
    request: PreSignedUploadRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))],
) -> PreSignedUploadResponse:
    """
    Get a pre-signed URL for direct upload to S3.
    
    - Only available when S3 storage is configured
    - Returns 501 if using local storage
    - Client can upload directly to S3 using the returned URL
    """
    AccessGateway.assert_session_access(db, current_user, request.session_id)
    
    result = file_service.get_presigned_upload_url(
        user_id=current_user.id,
        session_id=request.session_id,
        filename=request.filename,
        content_type=request.content_type,
    )
    
    if not result:
        log_audit_event(
            event="file.presigned_upload",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="failed",
            resource_type="file",
            details={"reason": "not_supported"},
        )
        raise HTTPException(
            status_code=501,
            detail="Pre-signed URLs are only available with S3 storage"
        )

    log_audit_event(
        event="file.presigned_upload",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        outcome="success",
        resource_type="file",
        details={"session_id": request.session_id, "storage_key": result["storage_key"]},
    )
    
    return PreSignedUploadResponse(**result)


@router.get("/{file_id}/presigned-download", response_model=PreSignedDownloadResponse)
async def get_presigned_download_url(
    file_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.FILE_UPLOAD))],
) -> PreSignedDownloadResponse:
    """
    Get a pre-signed URL for direct download from S3.
    
    - Only available when S3 storage is configured
    - Not available for encrypted files (use regular download instead)
    """
    attachment = AccessGateway.assert_file_access(db, current_user, file_id)
    
    result = file_service.get_presigned_download_url(attachment)

    if not result:
        log_audit_event(
            event="file.presigned_download",
            actor_id=current_user.id,
            actor_role=current_user.role.value,
            outcome="failed",
            resource_type="file",
            resource_id=file_id,
            details={"reason": "not_supported"},
        )
        raise HTTPException(
            status_code=501,
            detail="Pre-signed downloads not available (encrypted files or local storage)"
        )

    log_audit_event(
        event="file.presigned_download",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        outcome="success",
        resource_type="file",
        resource_id=file_id,
        details={},
    )
    
    return PreSignedDownloadResponse(**result)
