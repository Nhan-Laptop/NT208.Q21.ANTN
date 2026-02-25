import io
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import fitz
from fastapi import HTTPException, UploadFile
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.file_attachment import FileAttachment
from app.models.user import User
from app.services.storage_service import storage_service, StorageStats, StorageObject


@dataclass
class UserStorageStats:
    """Storage statistics for a user."""
    total_files: int
    total_size_bytes: int
    encrypted_files: int
    by_mime_type: dict[str, int]


class FileService:
    """Service for handling file operations with unified storage backend."""

    def __init__(self) -> None:
        self._storage = storage_service

    def extract_pdf_text(self, payload: bytes) -> str:
        """Extract text from PDF file."""
        try:
            text_parts: list[str] = []
            with fitz.open(stream=io.BytesIO(payload), filetype="pdf") as doc:
                for page in doc:
                    text_parts.append(page.get_text("text"))
            return "\n".join(text_parts).strip()
        except Exception:
            return ""

    def validate_mime_type(self, mime_type: str) -> bool:
        """Check if mime type is allowed."""
        allowed = settings.allowed_mime_types_list
        return mime_type in allowed or not allowed

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        base = Path(filename).name
        base = base.replace("\x00", "")
        sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", base)
        sanitized = sanitized.strip("._") or "upload.bin"
        return sanitized[:200]

    @staticmethod
    def _is_pdf_payload(payload: bytes) -> bool:
        return payload.startswith(b"%PDF-")

    def get_attachment(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        file_id: str | None = None,
    ) -> FileAttachment:
        """Get a file attachment with access control."""
        query = db.query(FileAttachment).filter(FileAttachment.session_id == session_id)
        if file_id:
            query = query.filter(FileAttachment.id == file_id)
        attachment = query.order_by(desc(FileAttachment.created_at)).first()
        if not attachment:
            raise HTTPException(status_code=404, detail="File attachment not found")
        if not current_user.is_admin and attachment.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="You cannot access this file")
        return attachment

    def get_attachment_by_id(
        self,
        db: Session,
        current_user: User,
        file_id: str,
    ) -> FileAttachment:
        """Get a file attachment by ID with access control."""
        attachment = db.query(FileAttachment).filter(FileAttachment.id == file_id).first()
        if not attachment:
            raise HTTPException(status_code=404, detail="File attachment not found")
        if not current_user.is_admin and attachment.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="You cannot access this file")
        return attachment

    async def save_upload(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        upload_file: UploadFile,
        message_id: str | None = None,
    ) -> FileAttachment:
        """Upload and save a file."""
        payload = await upload_file.read()
        size_mb = len(payload) / (1024 * 1024)
        
        # Validate file size
        if size_mb > settings.max_upload_size_mb:
            raise HTTPException(
                status_code=413, 
                detail=f"File exceeds {settings.max_upload_size_mb} MB limit"
            )
        
        # Validate mime type
        mime_type = upload_file.content_type or "application/octet-stream"
        if not self.validate_mime_type(mime_type):
            raise HTTPException(
                status_code=415,
                detail=f"File type '{mime_type}' is not allowed"
            )

        # Generate storage key
        filename = self.sanitize_filename(upload_file.filename or "upload.bin")
        if mime_type.lower() in {"application/pdf", "application/x-pdf"} and not self._is_pdf_payload(payload):
            raise HTTPException(status_code=415, detail="Invalid PDF file signature")
        key = self._storage.generate_key(current_user.id, session_id, filename)
        
        # Upload with encryption
        result = self._storage.upload(
            data=payload,
            key=key,
            content_type=mime_type,
            metadata={
                "user_id": current_user.id,
                "session_id": session_id,
                "original_filename": filename,
            },
            encrypt=True,
        )

        # Extract text for PDFs
        extracted_text = None
        if mime_type.lower() in {"application/pdf", "application/x-pdf"}:
            extracted_text = self.extract_pdf_text(payload)

        # Create database record
        attachment = FileAttachment(
            session_id=session_id,
            message_id=message_id,
            user_id=current_user.id,
            file_name=filename,
            mime_type=mime_type,
            size_bytes=len(payload),
            storage_key=result.key,
            storage_url=result.url,
            storage_encrypted=result.encrypted,
            storage_encryption_alg="AES-256-GCM" if result.encrypted else None,
            extracted_text=extracted_text,
        )
        db.add(attachment)
        db.commit()
        db.refresh(attachment)
        return attachment

    def download_file(self, attachment: FileAttachment) -> bytes:
        """Download and decrypt a file from storage."""
        try:
            return self._storage.download(
                key=attachment.storage_key,
                decrypt=attachment.storage_encrypted,
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found in storage")
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to retrieve file")

    def delete_file(
        self,
        db: Session,
        current_user: User,
        file_id: str,
    ) -> bool:
        """Delete a file from storage and database."""
        attachment = self.get_attachment_by_id(db, current_user, file_id)
        
        # Delete from storage
        self._storage.delete(attachment.storage_key)
        
        # Delete from database
        db.delete(attachment)
        db.commit()
        return True

    def list_user_files(
        self,
        db: Session,
        current_user: User,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FileAttachment]:
        """List files for a user."""
        query = db.query(FileAttachment)
        
        if not current_user.is_admin:
            query = query.filter(FileAttachment.user_id == current_user.id)
        
        if session_id:
            query = query.filter(FileAttachment.session_id == session_id)
        
        return (
            query
            .order_by(desc(FileAttachment.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_user_files(
        self,
        db: Session,
        current_user: User,
        session_id: str | None = None,
    ) -> int:
        """Count total files for pagination."""
        query = db.query(func.count(FileAttachment.id))
        if not current_user.is_admin:
            query = query.filter(FileAttachment.user_id == current_user.id)
        if session_id:
            query = query.filter(FileAttachment.session_id == session_id)
        return query.scalar() or 0

    def get_user_storage_stats(
        self,
        db: Session,
        current_user: User,
    ) -> UserStorageStats:
        """Get storage statistics for a user using SQL aggregation (no full load)."""
        base = db.query(FileAttachment)
        if not current_user.is_admin:
            base = base.filter(FileAttachment.user_id == current_user.id)

        total_files = base.with_entities(func.count(FileAttachment.id)).scalar() or 0
        total_size = base.with_entities(func.coalesce(func.sum(FileAttachment.size_bytes), 0)).scalar() or 0
        encrypted_count = (
            base.filter(FileAttachment.storage_encrypted == True)
            .with_entities(func.count(FileAttachment.id))
            .scalar()
            or 0
        )

        # Mime type breakdown — small result set, fine as GROUP BY
        mime_rows = (
            base.with_entities(FileAttachment.mime_type, func.count(FileAttachment.id))
            .group_by(FileAttachment.mime_type)
            .all()
        )
        by_mime_type = {mime: cnt for mime, cnt in mime_rows}

        return UserStorageStats(
            total_files=total_files,
            total_size_bytes=total_size,
            encrypted_files=encrypted_count,
            by_mime_type=by_mime_type,
        )

    def get_storage_stats(self) -> StorageStats:
        """Get overall storage statistics."""
        return self._storage.get_stats()

    def get_presigned_upload_url(
        self,
        user_id: str,
        session_id: str,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> dict | None:
        """Get pre-signed URL for direct upload (S3 only)."""
        if not self.validate_mime_type(content_type):
            raise HTTPException(status_code=415, detail=f"File type '{content_type}' is not allowed")
        safe_filename = self.sanitize_filename(filename)
        key = self._storage.generate_key(user_id, session_id, safe_filename)
        url_info = self._storage.generate_presigned_upload_url(key, content_type)
        
        if url_info:
            return {
                "upload_url": url_info.url,
                "method": url_info.method,
                "expires_at": url_info.expires_at.isoformat(),
                "storage_key": key,
            }
        return None

    def get_presigned_download_url(
        self,
        attachment: FileAttachment,
    ) -> dict | None:
        """Get pre-signed URL for direct download (S3 only)."""
        if attachment.storage_encrypted:
            # Can't use presigned URL for encrypted files
            return None
        
        url_info = self._storage.generate_presigned_download_url(
            attachment.storage_key,
            filename=attachment.file_name,
        )
        
        if url_info:
            return {
                "download_url": url_info.url,
                "expires_at": url_info.expires_at.isoformat(),
            }
        return None


file_service = FileService()
