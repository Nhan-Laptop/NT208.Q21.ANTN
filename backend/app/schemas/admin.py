from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.user import UserRole


class AdminUserOut(BaseModel):
    """Admin view of user information."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str | None
    role: UserRole
    created_at: datetime


class AdminOverview(BaseModel):
    """Admin dashboard overview statistics."""
    users: int
    sessions: int
    messages: int
    files: int
    total_storage_bytes: int = 0
    total_storage_mb: float = 0.0
