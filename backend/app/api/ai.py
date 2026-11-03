"""AI 对话接口：普通返回 + SSE 流式 + 人工审批恢复。"""

import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import ai_rate_limiter
from app.models.user import User
from app.schemas.ai import ApprovalResumeRequest, ChatMessage, ChatRequest
from app.services import agent_service

router = APIRouter(prefix="/ai", tags=["AI相关的API"])


def _new_thread_id() -> str:
    return uuid.uuid4().hex


@router.post("/chat")
async def chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(ai_rate_limiter),
    db: Session = Depends(get_db),
):
    thread_id = data.thread_id or _new_thread_id()
    try:
        content = await agent_service.run_agent(db, current_user, data, thread_id)
    except agent_service.ApprovalRequired as exc:
        return Response.success(
            data={
                "type": "approval_required",
                "thread_id": exc.thread_id,
                "payload": exc.payload,
            }
        )
    return Response.success(
        data={"type": "message", "thread_id": thread_id,
              "message": ChatMessage(role="assistant", content=content)}
    )


@router.post("/chat/resume")
async def chat_resume(
    data: ApprovalResumeRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(ai_rate_limiter),
    db: Session = Depends(get_db),
):
    try:
        content = await agent_service.resume_agent(
            db, current_user, data.thread_id, data.approved, data.include_uploaded
        )
    except agent_service.ApprovalRequired as exc:
        return Response.success(
            data={
                "type": "approval_required",
                "thread_id": exc.thread_id,
                "payload": exc.payload,
            }
        )
    return Response.success(
        data={
            "type": "message",
            "thread_id": data.thread_id,
            "message": ChatMessage(role="assistant", content=content),
        }
    )


def _sse_line(payload: dict) -> str:
    """拼一条 SSE 帧：data: {json}\n\n"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(ai_rate_limiter),
    db: Session = Depends(get_db),
):
    thread_id = data.thread_id or _new_thread_id()

    async def event_gen():
        async for event in agent_service.stream_agent(
            db, current_user, data, thread_id
        ):
            yield _sse_line(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/stream/resume")
async def chat_stream_resume(
    data: ApprovalResumeRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(ai_rate_limiter),
    db: Session = Depends(get_db),
):
    async def event_gen():
        async for event in agent_service.resume_stream_agent(
            db,
            current_user,
            data.thread_id,
            data.approved,
            data.include_uploaded,
        ):
            yield _sse_line(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
