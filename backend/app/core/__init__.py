"""
Core infrastructure modules for AIRA Backend.

This module provides:
- Config: Application settings via pydantic-settings
- Crypto: AES-256-GCM encryption/decryption
- Database: SQLAlchemy session and engine setup
- Security: JWT authentication and password hashing
- Authorization: RBAC/ABAC access control
- Encrypted Types: SQLAlchemy custom types for at-rest encryption
"""

from app.core.authorization import AccessGateway, Permission, ROLE_PERMISSIONS
from app.core.config import Settings, get_settings, settings
from app.core.crypto import CryptoManager, crypto_manager
from app.core.database import Base, SessionLocal, engine, get_db
from app.core.encrypted_types import EncryptedJSON, EncryptedText
from app.core.security import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    "settings",
    # Database
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    # Crypto
    "CryptoManager",
    "crypto_manager",
    "EncryptedJSON",
    "EncryptedText",
    # Security
    "authenticate_user",
    "create_access_token",
    "decode_access_token",
    "get_current_user",
    "get_password_hash",
    "verify_password",
    # Authorization
    "AccessGateway",
    "Permission",
    "ROLE_PERMISSIONS",
]