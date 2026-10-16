"""LangGraph Agent 升级后的单元测试。

这些测试不调用真实大模型，也不访问网络，只验证图结构、路由逻辑和中断负载。
"""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

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


def test_interrupt_approval_flow(tmp_path, monkeypatch):
    """用假 LLM 验证 interrupt 审批的完整闭环，不依赖真实模型和网络。"""
    calls = {"n": 0}

    class FakeBound:
        def __init__(self, tools):
            self.tools = tools

        async def ainvoke(self, messages):
            calls["n"] += 1
            if calls["n"] == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "create_lab_reservation",
                            "args": {"lab_id": 1, "date": "2026-10-17",
                                     "start_time": "14:00", "end_time": "15:00"},
                            "id": "c1",
                        }
                    ],
                )
            return AIMessage(content="预约已提交")

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def bind_tools(self, tools):
            return FakeBound(tools)

    monkeypatch.setattr(agent_service, "ChatOpenAI", FakeLLM)
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

        first = await graph.ainvoke(
            {"messages": [HumanMessage(content="帮我预约明天下午的实验室")]},
            agent_service._make_config("approval-test"),
        )
        interrupts = first.get("__interrupt__")
        assert interrupts, "首次调用应当触发 interrupt 等待审批"
        assert agent_service._interrupt_payload(interrupts)["tool"] == "create_lab_reservation"

        resumed = await graph.ainvoke(
            Command(resume={"approved": True}),
            agent_service._make_config("approval-test"),
        )
        assert "预约已提交" in agent_service._last_ai_text(resumed.get("messages") or [])
        await agent_service.close_checkpointer()

    asyncio.run(run())
