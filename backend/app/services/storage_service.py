"""
Storage Service - Unified Storage Abstraction Layer.

Provides a common interface for both S3 and local storage with:
- Pre-signed URLs for direct browser uploads
- Multi-part upload support for large files
- File listing and management
- Storage statistics and health checks
- Lifecycle management (cleanup, expiration)
"""

import hashlib
import mimetypes
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import BinaryIO

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - optional dependency guard
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]

    class ClientError(Exception):
        pass

from app.core.config import settings
from app.core.crypto import crypto_manager

import logging

logger = logging.getLogger(__name__)


class StorageType(str, Enum):
    """Storage backend type."""
    S3 = "s3"
    LOCAL = "local"


@dataclass(slots=True)
class StorageObject:
    """Metadata for a stored object."""
    key: str
    size_bytes: int
    content_type: str
    last_modified: datetime
    etag: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    is_encrypted: bool = False


@dataclass(slots=True)
class UploadResult:
    """Result from an upload operation."""
    key: str
    url: str
    size_bytes: int
    etag: str | None = None
    encrypted: bool = False
    checksum: str | None = None


@dataclass(slots=True)
class PreSignedUrl:
    """Pre-signed URL for direct upload/download."""
    url: str
    method: str  # PUT or GET
    expires_at: datetime
    fields: dict[str, str] = field(default_factory=dict)  # For POST policy


@dataclass(slots=True)
class StorageStats:
    """Storage statistics."""
    total_objects: int
    total_size_bytes: int
    storage_type: StorageType
    bucket_name: str | None = None
    local_path: str | None = None
    health_status: str = "healthy"


class BaseStorage(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def upload(
        self,
        data: bytes | BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        encrypt: bool = True,
    ) -> UploadResult:
        """Upload data to storage."""
        pass

    @abstractmethod
    def download(self, key: str, decrypt: bool = True) -> bytes:
        """Download data from storage."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an object from storage."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if an object exists."""
        pass

    @abstractmethod
    def get_metadata(self, key: str) -> StorageObject | None:
        """Get object metadata."""
        pass

    @abstractmethod
    def list_objects(
        self,
        prefix: str = "",
        max_results: int = 1000,
    ) -> list[StorageObject]:
        """List objects with optional prefix filter."""
        pass

    @abstractmethod
    def get_url(self, key: str) -> str:
        """Get public/access URL for an object."""
        pass

    @abstractmethod
    def get_stats(self) -> StorageStats:
        """Get storage statistics."""
        pass

    def generate_key(self, user_id: str, session_id: str, filename: str) -> str:
        """Generate a unique storage key."""
        unique_id = uuid.uuid4().hex[:8]
        safe_filename = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)
        return f"{user_id}/{session_id}/{unique_id}-{safe_filename}"

    def calculate_checksum(self, data: bytes) -> str:
        """Calculate MD5 checksum of data."""
        return hashlib.md5(data).hexdigest()


class S3Storage(BaseStorage):
    """AWS S3 storage implementation."""

    def __init__(
        self,
        bucket_name: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ):
        if boto3 is None or Config is None:
            raise RuntimeError("boto3 is required for S3 storage.")
        self._bucket = bucket_name
        self._region = region
        
        # Configure S3 client with retries
        config = Config(
            region_name=region,
            retries={"max_attempts": 3, "mode": "adaptive"},
            signature_version="s3v4",
        )
        
        self._client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=config,
        )
        
        # Verify bucket access
        self._verify_bucket()

    def _verify_bucket(self) -> None:
        """Verify bucket exists and is accessible."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            logger.info(f"S3 bucket '{self._bucket}' verified successfully")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "404":
                logger.warning(f"S3 bucket '{self._bucket}' does not exist")
            elif error_code == "403":
                logger.warning(f"Access denied to S3 bucket '{self._bucket}'")
            else:
                logger.warning(f"S3 bucket verification failed: {e}")

    def upload(
        self,
        data: bytes | BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        encrypt: bool = True,
    ) -> UploadResult:
        """Upload data to S3."""
        # Read data if it's a file-like object
        if hasattr(data, "read"):
            data = data.read()
        
        original_size = len(data)
        checksum = self.calculate_checksum(data)
        
        # Encrypt if requested
        if encrypt:
            encrypted_data = crypto_manager.encrypt_bytes(data, aad=key.encode("utf-8"))
            upload_data = encrypted_data.encode("utf-8")
            key = f"{key}.enc"
            content_type = "application/octet-stream"
        else:
            upload_data = data
        
        # Prepare metadata
        s3_metadata = metadata or {}
        s3_metadata["original-size"] = str(original_size)
        s3_metadata["encrypted"] = str(encrypt).lower()
        s3_metadata["checksum-md5"] = checksum
        
        # Upload to S3
        try:
            response = self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=upload_data,
                ContentType=content_type,
                Metadata=s3_metadata,
                ServerSideEncryption="AES256",
            )
            
            return UploadResult(
                key=key,
                url=self.get_url(key),
                size_bytes=original_size,
                etag=response.get("ETag", "").strip('"'),
                encrypted=encrypt,
                checksum=checksum,
            )
        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    def upload_multipart(
        self,
        file_path: str | Path,
        key: str,
        content_type: str = "application/octet-stream",
        chunk_size: int = 50 * 1024 * 1024,  # 50MB chunks
    ) -> UploadResult:
        """Upload large file using multipart upload."""
        file_path = Path(file_path)
        file_size = file_path.stat().st_size
        
        # Initiate multipart upload
        response = self._client.create_multipart_upload(
            Bucket=self._bucket,
            Key=key,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        upload_id = response["UploadId"]
        
        parts = []
        part_number = 1
        
        try:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    part_response = self._client.upload_part(
                        Bucket=self._bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=chunk,
                    )
                    
                    parts.append({
                        "PartNumber": part_number,
                        "ETag": part_response["ETag"],
                    })
                    part_number += 1
            
            # Complete multipart upload
            self._client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            
            return UploadResult(
                key=key,
                url=self.get_url(key),
                size_bytes=file_size,
                encrypted=False,
            )
            
        except Exception as e:
            # Abort on failure
            self._client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
            )
            raise

    def download(self, key: str, decrypt: bool = True) -> bytes:
        """Download data from S3."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            data = response["Body"].read()
            
            # Check if encrypted
            metadata = response.get("Metadata", {})
            is_encrypted = metadata.get("encrypted", "").lower() == "true" or key.endswith(".enc")
            
            if decrypt and is_encrypted:
                original_key = key.rstrip(".enc") if key.endswith(".enc") else key
                return crypto_manager.decrypt_bytes(data.decode("utf-8"), aad=original_key.encode("utf-8"))
            
            return data
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"Object not found: {key}")
            raise

    def delete(self, key: str) -> bool:
        """Delete an object from S3."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def exists(self, key: str) -> bool:
        """Check if an object exists in S3."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def get_metadata(self, key: str) -> StorageObject | None:
        """Get object metadata from S3."""
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
            return StorageObject(
                key=key,
                size_bytes=response["ContentLength"],
                content_type=response.get("ContentType", "application/octet-stream"),
                last_modified=response["LastModified"],
                etag=response.get("ETag", "").strip('"'),
                metadata=response.get("Metadata", {}),
                is_encrypted=key.endswith(".enc"),
            )
        except ClientError:
            return None

    def list_objects(
        self,
        prefix: str = "",
        max_results: int = 1000,
    ) -> list[StorageObject]:
        """List objects in S3 bucket."""
        objects = []
        paginator = self._client.get_paginator("list_objects_v2")
        
        pages = paginator.paginate(
            Bucket=self._bucket,
            Prefix=prefix,
            PaginationConfig={"MaxItems": max_results},
        )
        
        for page in pages:
            for obj in page.get("Contents", []):
                objects.append(StorageObject(
                    key=obj["Key"],
                    size_bytes=obj["Size"],
                    content_type="application/octet-stream",  # HEAD request needed for actual type
                    last_modified=obj["LastModified"],
                    etag=obj.get("ETag", "").strip('"'),
                    is_encrypted=obj["Key"].endswith(".enc"),
                ))
        
        return objects

    def get_url(self, key: str) -> str:
        """Get S3 URL for an object."""
        return f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{key}"

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
    ) -> PreSignedUrl:
        """Generate pre-signed URL for direct upload."""
        try:
            url = self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
            return PreSignedUrl(
                url=url,
                method="PUT",
                expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
            )
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: str | None = None,
    ) -> PreSignedUrl:
        """Generate pre-signed URL for download."""
        params = {
            "Bucket": self._bucket,
            "Key": key,
        }
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
            return PreSignedUrl(
                url=url,
                method="GET",
                expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
            )
        except ClientError as e:
            logger.error(f"Failed to generate presigned download URL: {e}")
            raise

    def get_stats(self) -> StorageStats:
        """Get S3 bucket statistics."""
        objects = self.list_objects(max_results=10000)
        return StorageStats(
            total_objects=len(objects),
            total_size_bytes=sum(o.size_bytes for o in objects),
            storage_type=StorageType.S3,
            bucket_name=self._bucket,
            health_status="healthy",
        )


class LocalStorage(BaseStorage):
    """Local filesystem storage implementation."""

    def __init__(self, base_path: str | Path = "local_storage"):
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._metadata_dir = self._base_path / ".metadata"
        self._metadata_dir.mkdir(exist_ok=True)
        logger.info(f"Local storage initialized at: {self._base_path.absolute()}")

    def _get_file_path(self, key: str) -> Path:
        """Get full file path for a key."""
        # Replace / with _ to flatten structure, or use nested dirs
        safe_key = key.replace("/", "_")
        return self._base_path / safe_key

    def _get_metadata_path(self, key: str) -> Path:
        """Get metadata file path for a key."""
        safe_key = key.replace("/", "_")
        return self._metadata_dir / f"{safe_key}.json"

    def _save_metadata(self, key: str, metadata: dict) -> None:
        """Save object metadata."""
        import json
        meta_path = self._get_metadata_path(key)
        meta_path.write_text(json.dumps(metadata, default=str))

    def _load_metadata(self, key: str) -> dict | None:
        """Load object metadata."""
        import json
        meta_path = self._get_metadata_path(key)
        if meta_path.exists():
            return json.loads(meta_path.read_text())
        return None

    def upload(
        self,
        data: bytes | BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        encrypt: bool = True,
    ) -> UploadResult:
        """Upload data to local storage."""
        # Read data if it's a file-like object
        if hasattr(data, "read"):
            data = data.read()
        
        original_size = len(data)
        checksum = self.calculate_checksum(data)
        
        # Encrypt if requested
        if encrypt:
            encrypted_data = crypto_manager.encrypt_bytes(data, aad=key.encode("utf-8"))
            upload_data = encrypted_data.encode("utf-8")
            key = f"{key}.enc"
        else:
            upload_data = data
        
        # Write file
        file_path = self._get_file_path(key)
        file_path.write_bytes(upload_data)
        
        # Save metadata
        meta = {
            "key": key,
            "original_size": original_size,
            "stored_size": len(upload_data),
            "content_type": content_type,
            "encrypted": encrypt,
            "checksum": checksum,
            "created_at": datetime.utcnow().isoformat(),
            **(metadata or {}),
        }
        self._save_metadata(key, meta)
        
        return UploadResult(
            key=key,
            url=str(file_path.absolute()),
            size_bytes=original_size,
            encrypted=encrypt,
            checksum=checksum,
        )

    def download(self, key: str, decrypt: bool = True) -> bytes:
        """Download data from local storage."""
        file_path = self._get_file_path(key)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Object not found: {key}")
        
        data = file_path.read_bytes()
        
        # Check if encrypted
        meta = self._load_metadata(key)
        is_encrypted = (meta and meta.get("encrypted", False)) or key.endswith(".enc")
        
        if decrypt and is_encrypted:
            original_key = key.rstrip(".enc") if key.endswith(".enc") else key
            return crypto_manager.decrypt_bytes(data.decode("utf-8"), aad=original_key.encode("utf-8"))
        
        return data

    def delete(self, key: str) -> bool:
        """Delete an object from local storage."""
        file_path = self._get_file_path(key)
        meta_path = self._get_metadata_path(key)
        
        deleted = False
        if file_path.exists():
            file_path.unlink()
            deleted = True
        if meta_path.exists():
            meta_path.unlink()
        
        return deleted

    def exists(self, key: str) -> bool:
        """Check if an object exists in local storage."""
        return self._get_file_path(key).exists()

    def get_metadata(self, key: str) -> StorageObject | None:
        """Get object metadata."""
        file_path = self._get_file_path(key)
        if not file_path.exists():
            return None
        
        meta = self._load_metadata(key) or {}
        stat = file_path.stat()
        
        return StorageObject(
            key=key,
            size_bytes=meta.get("original_size", stat.st_size),
            content_type=meta.get("content_type", "application/octet-stream"),
            last_modified=datetime.fromtimestamp(stat.st_mtime),
            metadata=meta,
            is_encrypted=meta.get("encrypted", False) or key.endswith(".enc"),
        )

    def list_objects(
        self,
        prefix: str = "",
        max_results: int = 1000,
    ) -> list[StorageObject]:
        """List objects in local storage."""
        objects = []
        safe_prefix = prefix.replace("/", "_")
        
        for file_path in self._base_path.iterdir():
            if file_path.is_file() and not file_path.name.startswith("."):
                if file_path.name.startswith(safe_prefix):
                    meta = self._load_metadata(file_path.name) or {}
                    stat = file_path.stat()
                    
                    objects.append(StorageObject(
                        key=file_path.name,
                        size_bytes=meta.get("original_size", stat.st_size),
                        content_type=meta.get("content_type", "application/octet-stream"),
                        last_modified=datetime.fromtimestamp(stat.st_mtime),
                        is_encrypted=meta.get("encrypted", False),
                    ))
                    
                    if len(objects) >= max_results:
                        break
        
        return objects

    def get_url(self, key: str) -> str:
        """Get local file path as URL."""
        return str(self._get_file_path(key).absolute())

    def get_stats(self) -> StorageStats:
        """Get local storage statistics."""
        objects = self.list_objects(max_results=100000)
        
        # Check disk space
        disk_usage = shutil.disk_usage(self._base_path)
        health = "healthy"
        if disk_usage.free < 1024 * 1024 * 100:  # Less than 100MB free
            health = "warning_low_disk"
        
        return StorageStats(
            total_objects=len(objects),
            total_size_bytes=sum(o.size_bytes for o in objects),
            storage_type=StorageType.LOCAL,
            local_path=str(self._base_path.absolute()),
            health_status=health,
        )

    def cleanup_old_files(self, days: int = 30) -> int:
        """Delete files older than specified days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted_count = 0
        
        for file_path in self._base_path.iterdir():
            if file_path.is_file() and not file_path.name.startswith("."):
                stat = file_path.stat()
                if datetime.fromtimestamp(stat.st_mtime) < cutoff:
                    self.delete(file_path.name)
                    deleted_count += 1
        
        return deleted_count


class StorageService:
    """
    Unified storage service that automatically selects S3 or local backend.
    """

    def __init__(self):
        self._backend: BaseStorage
        backend_mode = settings.storage_backend

        # Local development can force filesystem storage even when S3
        # credentials are present in a private .env.
        if backend_mode == "local":
            self._backend = LocalStorage(getattr(settings, "local_storage_path", "local_storage"))
            self._storage_type = StorageType.LOCAL
            logger.info("Storage service initialized with local backend")
        elif (
            settings.aws_access_key_id
            and settings.aws_secret_access_key
            and settings.s3_bucket_name
        ):
            try:
                self._backend = S3Storage(
                    bucket_name=settings.s3_bucket_name,
                    region=settings.aws_region,
                    access_key_id=settings.aws_access_key_id,
                    secret_access_key=settings.aws_secret_access_key,
                )
                self._storage_type = StorageType.S3
                logger.info("Storage service initialized with S3 backend")
            except Exception as e:
                if backend_mode == "s3":
                    raise
                logger.warning(f"S3 initialization failed, falling back to local: {e}")
                self._backend = LocalStorage(settings.local_storage_path)
                self._storage_type = StorageType.LOCAL
        else:
            self._backend = LocalStorage(getattr(settings, "local_storage_path", "local_storage"))
            self._storage_type = StorageType.LOCAL
            logger.info("Storage service initialized with local backend")

    @property
    def storage_type(self) -> StorageType:
        """Get current storage backend type."""
        return self._storage_type

    @property
    def backend(self) -> BaseStorage:
        """Get the storage backend."""
        return self._backend

    def upload(
        self,
        data: bytes | BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
        encrypt: bool = True,
    ) -> UploadResult:
        """Upload data to storage."""
        return self._backend.upload(data, key, content_type, metadata, encrypt)

    def download(self, key: str, decrypt: bool = True) -> bytes:
        """Download data from storage."""
        return self._backend.download(key, decrypt)

    def delete(self, key: str) -> bool:
        """Delete an object."""
        return self._backend.delete(key)

    def exists(self, key: str) -> bool:
        """Check if object exists."""
        return self._backend.exists(key)

    def get_metadata(self, key: str) -> StorageObject | None:
        """Get object metadata."""
        return self._backend.get_metadata(key)

    def list_objects(self, prefix: str = "", max_results: int = 1000) -> list[StorageObject]:
        """List objects."""
        return self._backend.list_objects(prefix, max_results)

    def get_url(self, key: str) -> str:
        """Get URL for object."""
        return self._backend.get_url(key)

    def get_stats(self) -> StorageStats:
        """Get storage statistics."""
        return self._backend.get_stats()

    def generate_key(self, user_id: str, session_id: str, filename: str) -> str:
        """Generate a unique storage key."""
        return self._backend.generate_key(user_id, session_id, filename)

    def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
    ) -> PreSignedUrl | None:
        """Generate pre-signed URL for direct upload (S3 only)."""
        if isinstance(self._backend, S3Storage):
            return self._backend.generate_presigned_upload_url(key, content_type, expires_in)
        return None

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600,
        filename: str | None = None,
    ) -> PreSignedUrl | None:
        """Generate pre-signed URL for download (S3 only)."""
        if isinstance(self._backend, S3Storage):
            return self._backend.generate_presigned_download_url(key, expires_in, filename)
        return None


# Singleton instance
storage_service = StorageService()
