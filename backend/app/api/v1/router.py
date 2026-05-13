from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, chat, crawl_admin, journal_match, manuscripts, sessions, tools, upload, venues

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(sessions.router)
api_router.include_router(chat.router)
api_router.include_router(tools.router)
api_router.include_router(upload.router)
api_router.include_router(manuscripts.router)
api_router.include_router(journal_match.router)
api_router.include_router(venues.router)
api_router.include_router(crawl_admin.router)
