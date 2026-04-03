from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.chat_message import MessageRole, MessageType
from app.models.chat_session import SessionMode


class SessionCreate(BaseModel):
    title: str = Field(default="Trò chuyện mới", max_length=255)
    mode: SessionMode = SessionMode.GENERAL_QA


class SessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    mode: SessionMode | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    mode: SessionMode
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: MessageRole
    message_type: MessageType
    content: str | None
    tool_results: dict[str, Any] | list[Any] | None
    created_at: datetime


class ChatCompletionRequest(BaseModel):
    session_id: str
    user_message: str = Field(min_length=1)
    mode: SessionMode | None = None
    encrypted: bool = False


class SessionChatRequest(BaseModel):
    user_message: str = Field(min_length=1)
    mode: SessionMode | None = None


class ChatCompletionResponse(BaseModel):
    session_id: str
    session: SessionOut
    user_message: MessageOut
    assistant_message: MessageOut


class EncryptedPayload(BaseModel):
    payload: str


class EncryptedChatCompletionResponse(BaseModel):
    payload: str
