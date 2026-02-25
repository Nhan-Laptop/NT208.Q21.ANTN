"""
API v1 module.

Contains all v1 endpoint routers for:
- Authentication (register, login, me)
- Admin (overview, users)
- Sessions (CRUD operations)
- Chat (completions, encrypted)
- Tools (citation, journal, retraction, PDF, AI detection)
- Upload (file upload to S3/local)
"""

from app.api.v1.router import api_router

__all__ = ["api_router"]