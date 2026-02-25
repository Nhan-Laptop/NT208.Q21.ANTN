"""
Business logic services for AIRA Backend.

This module contains:
- ChatService: Chat session and message management
- FileService: File upload, storage (S3/local), and PDF extraction
- StorageService: Unified storage abstraction (S3/local) with encryption
- GeminiService: LLM integration with Google Gemini
- Bootstrap: System initialization and admin user setup
"""

from app.services.bootstrap import ensure_admin_user
from app.services.chat_service import ChatService, chat_service
from app.services.file_service import FileService, file_service
from app.services.llm_service import GeminiService, gemini_service
from app.services.storage_service import (
    StorageService,
    storage_service,
    StorageType,
    StorageStats,
    StorageObject,
    UploadResult,
)

__all__ = [
    "ChatService",
    "chat_service",
    "FileService",
    "file_service",
    "StorageService",
    "storage_service",
    "StorageType",
    "StorageStats",
    "StorageObject",
    "UploadResult",
    "GeminiService",
    "gemini_service",
    "ensure_admin_user",
]