"""LangGraph Agent 升级后的单元测试。

这些测试不调用真实大模型，也不访问网络，只验证图结构、路由逻辑和中断负载。
"""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage

import app.services.agent_service as agent_service


def test_route_with_tool_calls():
    msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "create_lab_reservation", "args": {"lab_id": 1}, "id": "c1"}
        ],
    )
    assert agent_service._route_after_agent({"messages": [msg]}) == "approval"


def test_route_without_tool_calls():
    msg = AIMessage(content="你好")
    assert agent_service._route_after_agent({"messages": [msg]}) == "end"


def test_interrupt_payload_extracts_value():
    class FakeInterrupt:
        value = {"tool": "create_lab_reservation", "args": {"lab_id": 1}}

    payload = agent_service._interrupt_payload([FakeInterrupt()])
    assert payload["tool"] == "create_lab_reservation"


def test_schemas_accept_thread_id():
    from app.schemas.ai import ApprovalResumeRequest, ChatRequest

    req = ChatRequest(messages=[{"role": "user", "content": "你好"}], thread_id="abc")
    assert req.thread_id == "abc"

    resume = ApprovalResumeRequest(thread_id="abc", approved=True)
    assert resume.approved is True


def test_build_agent_compiles(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_service.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(agent_service.settings, "MCP_ENABLED", False)
    monkeypatch.setattr(
        agent_service.settings, "CHECKPOINT_DB_PATH", str(tmp_path / "ckpt.db")
    )
    agent_service._checkpointer = None
    agent_service._checkpointer_cm = None

    user = SimpleNamespace(id=1, role="student")

    async def run():
        graph = await agent_service.build_agent(None, user)
        assert graph is not None
        await agent_service.close_checkpointer()

    asyncio.run(run())
