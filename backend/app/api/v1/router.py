from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, chat, sessions, tools, upload

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(sessions.router)
api_router.include_router(chat.router)
api_router.include_router(tools.router)
api_router.include_router(upload.router)
