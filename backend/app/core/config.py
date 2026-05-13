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

    database_url: str = Field(default="sqlite:///./aira.db", min_length=1)
    alembic_database_url: str | None = None
    chroma_db_path: str = Field(default="data/chroma_db", min_length=1)
    academic_seed_path: str = Field(default="data/academic_seed.json", min_length=1)
    academic_live_sources_path: str = Field(default="crawler/sources.json", min_length=1)
    academic_live_crawl_enabled: bool = True
    crawler_user_agent: str = "AIRA-ScholarlyCrawler/1.0 contact:admin@aira.local"
    crawler_rate_limit_seconds: float = 2.0
    crawler_timeout_seconds: float = 30.0
    crawler_max_retries: int = 3
    crawler_raw_storage_path: str = "data/raw_snapshots"
    clarivate_manual_import_dir: str = "data/imports/clarivate"
    clarivate_username: str | None = None
    clarivate_password: str | None = None
    use_browser_crawler: bool = False
    browser_headless: bool = True
    academic_browser_path: str | None = None
    academic_browser_library_path: str | None = None
    hf_cache_dir: str = Field(default=".cache/huggingface", min_length=1)
    specter2_model_name: str = Field(default="allenai/specter2", min_length=1)
    specter2_fallback_model_name: str = Field(default="allenai/specter2_base", min_length=1)
    specter2_max_chars: int = Field(default=12000, ge=1000)
    academic_embedding_hash_fallback: bool = False
    ai_detect_ml_enabled: bool = True
    ai_detect_model_name: str = Field(default="roberta-base-openai-detector", min_length=1)
    ai_detect_allow_download: bool = True
    ai_detect_ensemble_weight_ml: float = Field(default=0.7, ge=0.0, le=1.0)
    ai_detect_ensemble_weight_rules: float = Field(default=0.3, ge=0.0, le=1.0)
    ai_detect_use_specter2: bool = False
    academic_enable_startup_schema_create: bool | None = None
    academic_enable_startup_source_bootstrap: bool | None = None
    academic_enable_startup_chroma_init: bool | None = None

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
    groq_api_key: str | None = None
    # Model names are provider-managed and may change.
    gemini_model: str = "gemini-flash-latest"
    groq_model: str = "llama-3.1-8b-instant"

    @model_validator(mode="after")
    def _normalize_optional_keys(self) -> "Settings":
        """Treat empty strings as None for optional API keys."""
        if isinstance(self.google_api_key, str) and not self.google_api_key.strip():
            object.__setattr__(self, "google_api_key", None)
        if isinstance(self.groq_api_key, str) and not self.groq_api_key.strip():
            object.__setattr__(self, "groq_api_key", None)
        if isinstance(self.hf_token, str) and not self.hf_token.strip():
            object.__setattr__(self, "hf_token", None)
        if isinstance(self.alembic_database_url, str) and not self.alembic_database_url.strip():
            object.__setattr__(self, "alembic_database_url", None)
        return self

    # Hugging Face token for authenticated model downloads (optional)
    hf_token: str | None = None
    chat_context_window: int = 8
    system_prompt: str = (
        "Bạn là AIRA — trợ lý nghiên cứu học thuật chuyên nghiệp. "
        "Luôn gọi công cụ (function call) khi cần dữ liệu học thuật thực tế. "
        "Không bao giờ bịa DOI, trích dẫn, hay số liệu. "
        "Trả lời ngắn gọn, chính xác, mang tính học thuật."
    )

    aws_region: str = "ap-southeast-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_bucket_name: str | None = None

    # Local storage settings
    storage_backend: str = "auto"
    local_storage_path: str = "local_storage"
    local_storage_cleanup_days: int = 90

    max_upload_size_mb: int = Field(default=20, gt=0)
    allowed_mime_types: str = Field(
        default="application/pdf,image/png,image/jpeg,image/gif,text/plain,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        min_length=1,
    )

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

    @model_validator(mode="after")
    def _validate_academic_runtime_safety(self) -> "Settings":
        env = (self.app_env or "development").strip().lower()
        object.__setattr__(self, "app_env", env)
        if env == "production" and self.database_url.startswith("sqlite"):
            raise ValueError("CRITICAL: DATABASE_URL must not use SQLite in production.")
        if env in {"staging", "production"} and self.academic_embedding_hash_fallback:
            raise ValueError(
                "CRITICAL: ACADEMIC_EMBEDDING_HASH_FALLBACK must be false in staging/production."
            )
        if env in {"staging", "production"} and self.academic_enable_startup_schema_create:
            raise ValueError(
                "CRITICAL: ACADEMIC_ENABLE_STARTUP_SCHEMA_CREATE must not be true in staging/production."
            )
        storage_backend = (self.storage_backend or "auto").strip().lower()
        if storage_backend not in {"auto", "local", "s3"}:
            raise ValueError("STORAGE_BACKEND must be one of: auto, local, s3.")
        object.__setattr__(self, "storage_backend", storage_backend)
        if not self.allowed_mime_types_list:
            raise ValueError("ALLOWED_MIME_TYPES must contain at least one MIME type.")
        return self

    @property
    def master_key_path(self) -> Path:
        return Path(self.master_key_file)

    @property
    def startup_schema_create_enabled(self) -> bool:
        if self.academic_enable_startup_schema_create is not None:
            return self.academic_enable_startup_schema_create
        return self.app_env == "development"

    @property
    def startup_source_bootstrap_enabled(self) -> bool:
        if self.academic_enable_startup_source_bootstrap is not None:
            return self.academic_enable_startup_source_bootstrap
        return self.app_env == "development"

    @property
    def startup_chroma_init_enabled(self) -> bool:
        if self.academic_enable_startup_chroma_init is not None:
            return self.academic_enable_startup_chroma_init
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
