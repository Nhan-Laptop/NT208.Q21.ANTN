"""
Business logic services for AIRA Backend.

This module contains:
- ChatService: Chat session and message management
- FileService: File upload, storage (S3/local), and PDF extraction
- StorageService: Unified storage abstraction (S3/local) with encryption
- GroqLLMService: LLM integration with Groq (LLaMA 3.1)
- Bootstrap: System initialization and admin user setup
"""

from app.services.bootstrap import ensure_admin_user
from app.services.chat_service import ChatService, chat_service
from app.services.file_service import FileService, file_service
from app.services.llm_service import GroqLLMService, gemini_service
from app.services.storage_service import (
    StorageService,
    storage_service,
    StorageType,
    StorageStats,
    StorageObject,
    UploadResult,
)

# Backward-compatible aliases after Groq migration.
GeminiService = GroqLLMService
groq_llm_service = gemini_service

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
    "GroqLLMService",
    "groq_llm_service",
    "GeminiService",
    "gemini_service",
    "ensure_admin_user",
]