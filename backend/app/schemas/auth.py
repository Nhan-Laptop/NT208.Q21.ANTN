from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str | None
    role: UserRole
    created_at: datetime


class AIDetectionRulePreferencesUpdate(BaseModel):
    phrases: list[str] = Field(default_factory=list)


class AIDetectionRulePreferencesOut(BaseModel):
    phrases: list[str] = Field(default_factory=list)
    phrase_count: int = 0
    rule_source: Literal["default_app_rules", "user_custom_rules"] = "default_app_rules"
    updated_at: datetime | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PromoteUserRequest(BaseModel):
    user_id: str
    role: UserRole
