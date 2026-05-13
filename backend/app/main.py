import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.crypto import crypto_manager
from app.core.database import SessionLocal, engine
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.models import ChatMessage, ChatSession, FileAttachment, User
from app.core.database import Base
from app.services.bootstrap import ensure_admin_user
from app.services.embeddings.specter2_service import specter2_service
from app.services.ingestion.index_service import academic_index_service
from app.services.storage_service import storage_service
from app.services.tools.citation_checker import citation_checker
from app.services.tools.grammar_checker import grammar_checker
from app.services.tools.retraction_scan import retraction_scanner
from crawler.scheduler import crawl_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.startup_schema_create_enabled:
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_admin_user(db)
        if settings.startup_source_bootstrap_enabled:
            crawl_scheduler.ensure_default_sources(db)
        if settings.startup_chroma_init_enabled:
            try:
                academic_index_service.ensure_collections()
            except Exception as exc:
                logger.warning("Academic index initialization skipped: %s", exc)
        try:
            if specter2_service.is_degraded:
                logger.warning(
                    "SPECTER2 embedding model is not available — using hash fallback. "
                    "Journal matching quality will be poor. Install model dependencies or set HF_TOKEN."
                )
        except Exception as exc:
            logger.warning("Embedding health check skipped: %s", exc)
    finally:
        db.close()
    yield
    # Shutdown: close persistent HTTP clients
    citation_checker.close()
    retraction_scanner.close()
    grammar_checker.close()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Safety net: catch any unhandled exception and return user-friendly 400.

    FastAPI's default HTTPException handler takes precedence for HTTPException
    (more specific), so this only catches truly unexpected exceptions.
    """
    logger.exception("Unhandled exception caught by global handler: %s", exc)
    return JSONResponse(
        status_code=400,
        content={
            "detail": (
                "Mình chưa xử lý được yêu cầu này. "
                "Bạn vui lòng kiểm tra lại nội dung hoặc thử lại sau."
            ),
        },
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods_list or ["*"],
    allow_headers=settings.cors_allow_headers_list or ["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.include_router(api_router, prefix=settings.api_v1_str)


@app.get("/health")
def health() -> dict[str, str | bool]:
    """Health check endpoint with system status."""
    payload: dict[str, str | bool | dict[str, str | float | int]] = {
        "status": "ok",
        "app": settings.app_name,
        "transport_encryption_enabled": settings.transport_encryption_enabled,
    }
    if settings.health_include_details:
        storage_stats = storage_service.get_stats()
        payload["storage"] = {
            "type": storage_stats.storage_type.value,
            "health": storage_stats.health_status,
            "objects": storage_stats.total_objects,
            "size_mb": round(storage_stats.total_size_bytes / (1024 * 1024), 2),
        }
        payload["master_key_source"] = crypto_manager.key_info.source
    return payload
