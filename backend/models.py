"""
数据模型 · Pydantic
================
所有请求/响应模型集中定义于此。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FileAttachment(BaseModel):
    name: str
    type: str  # "text/plain", "image/jpeg", etc.
    data: str  # text content or base64 data


class ChatRequest(BaseModel):
    input: str
    anchor: Optional[str] = None
    history: Optional[list[dict]] = None
    session_id: Optional[str] = None
    files: Optional[list[FileAttachment]] = None


class SessionRestoreRequest(BaseModel):
    session_id: str
    history: list[dict]


class RememberRequest(BaseModel):
    history: Optional[list[dict]] = None


class SaveChatRequest(BaseModel):
    history: Optional[list[dict]] = None


class MoodRequest(BaseModel):
    mood: str
    emoji: str
    label: str


class MemoryReviewRequest(BaseModel):
    action: str  # "approve" | "reject" | "approve_all"
    id: Optional[str] = None
    edited_content: Optional[str] = None


class MemoryDeleteRequest(BaseModel):
    id: str


class MemoryBatchDeleteRequest(BaseModel):
    ids: list[str]


class MemoryFavoriteRequest(BaseModel):
    id: str
    favorite: bool


class MemoryEditRequest(BaseModel):
    id: str
    category: Optional[str] = None
    content: Optional[str] = None


class ModelSwitchRequest(BaseModel):
    model: str


class SettingsData(BaseModel):
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""
    model: Optional[str] = ""
    qwen_api_key: Optional[str] = ""
    qwen_base_url: Optional[str] = ""
    qwen_vl_model: Optional[str] = ""
    weather_location: Optional[str] = ""
    thinking_mode: Optional[bool] = None


class AvatarRequest(BaseModel):
    data: str  # "data:image/png;base64,..."


class ProactiveSaveRequest(BaseModel):
    session_id: str
    message: str


class SearchRequest(BaseModel):
    query: str
    scope: str = "all"  # all | memory | chats | sessions


class TimelineAction(BaseModel):
    id: str


class TimelineContentRequest(BaseModel):
    id: str


class TodayNoteRequest(BaseModel):
    history: Optional[list[dict]] = None


class BookDiscussRequest(BaseModel):
    book_id: str
    chapter_index: int
    message: str
    history: Optional[list[dict]] = None


class AUCreateRequest(BaseModel):
    name: str
    background: str = ""
    persona_override: str = ""
    tone_shift: str = ""
