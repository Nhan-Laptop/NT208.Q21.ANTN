import logging
import secrets
from functools import lru_cache
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger(__name__)

_INSECURE_JWT_DEFAULTS = {"replace-me-in-production", "changeme", "secret", ""}
_INSECURE_ADMIN_DEFAULTS = {"ChangeMe!123", "changeme", "password", "admin", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    app_name: str = "AIRA Backend"
    app_env: str = "development"
    api_v1_str: str = "/api/v1"
    debug: bool = False

    database_url: str = "sqlite:///./aira.db"

    jwt_secret_key: str = "replace-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60  # 1 hour (down from 24h)

    admin_email: str = "admin@aira.local"
    admin_password: str = "ChangeMe!123"

    @model_validator(mode="after")
    def _validate_security_defaults(self) -> "Settings":
        """Warn loudly (or block) when insecure defaults are detected."""
        if self.app_env != "development":
            if self.jwt_secret_key.lower() in _INSECURE_JWT_DEFAULTS:
                raise ValueError(
                    "CRITICAL: jwt_secret_key is using an insecure default. "
                    "Set JWT_SECRET_KEY in .env for non-development environments."
                )
            if self.admin_password in _INSECURE_ADMIN_DEFAULTS:
                raise ValueError(
                    "CRITICAL: admin_password is using an insecure default. "
                    "Set ADMIN_PASSWORD in .env for non-development environments."
                )
        else:
            if self.jwt_secret_key.lower() in _INSECURE_JWT_DEFAULTS:
                _logger.warning(
                    "\u26a0\ufe0f  jwt_secret_key is insecure — acceptable only in development mode."
                )
            if self.admin_password in _INSECURE_ADMIN_DEFAULTS:
                _logger.warning(
                    "\u26a0\ufe0f  admin_password is insecure — acceptable only in development mode."
                )
        return self

    # Master key for AES-256-GCM (base64 urlsafe, 32-byte raw key)
    admin_master_key_b64: str | None = None
    master_key_file: str = ".aira_master_key"

    google_api_key: str | None = None
    # Model names are provider-managed and may change. Use ListModels if 404 occurs.
    gemini_model: str = "gemini-flash-latest"
    chat_context_window: int = 8
    system_prompt: str = (
        "You are a professional academic research assistant. "
        "Respond concisely, formally, and with scientific integrity."
    )

    aws_region: str = "ap-southeast-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_bucket_name: str | None = None

    # Local storage settings
    local_storage_path: str = "local_storage"
    local_storage_cleanup_days: int = 90

    max_upload_size_mb: int = 20
    allowed_mime_types: str = "application/pdf,image/png,image/jpeg,image/gif,text/plain,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_allow_credentials: bool = False
    cors_allow_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_allow_headers: str = "Authorization,Content-Type,Accept"

    security_headers_enabled: bool = True
    csp_policy: str = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' https:;"

    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_auth_max: int = 10
    rate_limit_chat_max: int = 60
    rate_limit_tools_max: int = 40
    rate_limit_upload_max: int = 20
    rate_limit_default_max: int = 120

    audit_log_file: str = "audit.log"
    health_include_details: bool = False

    @property
    def allowed_mime_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_mime_types.split(",")]

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

    @property
    def cors_allow_methods_list(self) -> list[str]:
        return [item.strip().upper() for item in self.cors_allow_methods.split(",") if item.strip()]

    @property
    def cors_allow_headers_list(self) -> list[str]:
        return [item.strip() for item in self.cors_allow_headers.split(",") if item.strip()]

    transport_encryption_enabled: bool = True

    @property
    def master_key_path(self) -> Path:
        return Path(self.master_key_file)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
