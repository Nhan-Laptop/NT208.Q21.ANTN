from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FileUploadResponse(BaseModel):
    """Response after successful file upload."""
    id: str
    session_id: str
    message_id: str | None
    file_name: str
    mime_type: str
    size_bytes: int
    storage_url: str
    storage_encrypted: bool
    storage_encryption_alg: str | None
    created_at: datetime


class FileAttachmentOut(BaseModel):
    """File attachment output schema."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    message_id: str | None
    user_id: str
    file_name: str
    mime_type: str
    size_bytes: int
    storage_encrypted: bool
    storage_encryption_alg: str | None
    created_at: datetime


class FileListResponse(BaseModel):
    """Response for file listing endpoint."""
    files: list[FileAttachmentOut]
    total: int
    limit: int
    offset: int


class UserStorageStatsResponse(BaseModel):
    """User storage statistics."""
    total_files: int
    total_size_bytes: int
    total_size_mb: float
    encrypted_files: int
    by_mime_type: dict[str, int]


class StorageStatsResponse(BaseModel):
    """Overall storage statistics."""
    storage_type: str
    total_objects: int
    total_size_bytes: int
    total_size_mb: float
    bucket_name: str | None = None
    local_path: str | None = None
    health_status: str


class PreSignedUploadRequest(BaseModel):
    """Request for pre-signed upload URL."""
    session_id: str
    filename: str
    content_type: str = "application/octet-stream"


class PreSignedUploadResponse(BaseModel):
    """Pre-signed URL for direct upload."""
    upload_url: str
    method: str
    expires_at: str
    storage_key: str


class PreSignedDownloadResponse(BaseModel):
    """Pre-signed URL for direct download."""
    download_url: str
    expires_at: str


class FileDeleteResponse(BaseModel):
    """Response after file deletion."""
    success: bool
    file_id: str
    message: str
