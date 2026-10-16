"""AI 对话 Schema。"""

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    thread_id: str | None = None
    include_uploaded: bool = True


class ApprovalResumeRequest(BaseModel):
    thread_id: str
    approved: bool
    include_uploaded: bool = True
