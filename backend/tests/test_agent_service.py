"""LangGraph Agent 升级后的单元测试。

这些测试不调用真实大模型，也不访问网络，只验证图结构、路由逻辑和中断负载。
"""

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
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


def test_multiturn_does_not_duplicate_history(tmp_path, monkeypatch):
    """checkpointer 已保存历史时，前端只发新消息，不能出现历史重复。"""
    captured = {"calls": []}

    class FakeBound:
        async def ainvoke(self, messages):
            captured["calls"].append(list(messages))
            return AIMessage(content="ok")

    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def bind_tools(self, tools):
            return FakeBound()

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
        config = agent_service._make_config("multiturn-test")
        await graph.ainvoke({"messages": [HumanMessage(content="第一句")]}, config)
        await graph.ainvoke({"messages": [HumanMessage(content="第二句")]}, config)

        second_call = captured["calls"][1]
        texts = [m.content for m in second_call]
        assert texts.count("第一句") == 1
        assert texts.count("第二句") == 1
        assert sum(isinstance(m, SystemMessage) for m in second_call) == 1
        await agent_service.close_checkpointer()

    asyncio.run(run())


def test_checkpointer_sqlite_fallback_when_no_pg(tmp_path, monkeypatch):
    """未配置 CHECKPOINT_DATABASE_URL 时回退 SQLite，且不触发 PG 导入。"""
    monkeypatch.setattr(agent_service.settings, "CHECKPOINT_DATABASE_URL", None)
    monkeypatch.setattr(
        agent_service.settings, "CHECKPOINT_DB_PATH", str(tmp_path / "ckpt.db")
    )
    agent_service._checkpointer = None
    agent_service._checkpointer_cm = None

    async def run():
        ckpt = await agent_service.get_checkpointer()
        assert ckpt is not None
        # SQLite 回退分支：checkpointer 实例是 AsyncSqliteSaver，而非 Postgres。
        assert ckpt.__class__.__name__ == "AsyncSqliteSaver"
        await agent_service.close_checkpointer()

    asyncio.run(run())


def test_invoke_tool_with_retry_succeeds(monkeypatch):
    """工具一次成功：直接返回结果内容。"""
    calls = {"n": 0}

    class FakeResult:
        content = "查询到 3 个实验室"

    class FakeTool:
        def invoke(self, args):
            calls["n"] += 1
            return FakeResult()

    async def run():
        out = await agent_service._invoke_tool_with_retry(FakeTool(), {})
        assert out == "查询到 3 个实验室"

    asyncio.run(run())
    assert calls["n"] == 1


def test_invoke_tool_with_retry_retries_then_fails(monkeypatch):
    """工具连续失败：按 TOOL_MAX_RETRIES 重试后，回填错误 JSON 给模型自纠。"""
    monkeypatch.setattr(agent_service.settings, "TOOL_MAX_RETRIES", 2)
    calls = {"n": 0}

    class FakeTool:
        def invoke(self, args):
            calls["n"] += 1
            raise RuntimeError("db timeout")

    async def run():
        out = await agent_service._invoke_tool_with_retry(FakeTool(), {})
        assert '"ok": false' in out
        assert "db timeout" in out

    asyncio.run(run())
    # 初次 + 2 次重试 = 3 次调用。
    assert calls["n"] == 3


def test_invoke_tool_with_retry_recovers_on_second_try(monkeypatch):
    """工具第一次失败、第二次成功：应重试后返回成功结果。"""
    monkeypatch.setattr(agent_service.settings, "TOOL_MAX_RETRIES", 1)
    calls = {"n": 0}

    class FakeTool:
        def invoke(self, args):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return SimpleNamespace(content="恢复成功")

    async def run():
        out = await agent_service._invoke_tool_with_retry(FakeTool(), {})
        assert out == "恢复成功"

    asyncio.run(run())
    assert calls["n"] == 2


def test_estimate_tokens_counts_chinese_and_tool_calls():
    """中文按字符/4 估算，工具调用参数也计入预算。"""
    msg = HumanMessage(content="你好" * 100)  # 200 个中文字符
    assert agent_service._estimate_tokens(msg) == 50

    ai = AIMessage(
        content="",
        tool_calls=[{"name": "search_lab_docs", "args": {"q": "安全规范"}, "id": "t1"}],
    )
    assert agent_service._estimate_tokens(ai) > 0


def test_trim_messages_returns_as_is_under_budget():
    """未超预算时原样返回，不丢任何消息。"""
    messages = [HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮你")]
    result = agent_service._trim_messages(messages, budget_tokens=1000)
    assert result == messages


def test_trim_messages_drops_oldest_on_overflow():
    """超预算时丢弃最早的消息，保留最新的一条。"""
    long = HumanMessage(content="长" * 4000)  # 约 1000 token
    messages = [
        HumanMessage(content="最早的问题"),
        AIMessage(content="最早的答复"),
        long,  # 最新，最应保留
    ]
    result = agent_service._trim_messages(messages, budget_tokens=1000)
    # 最新那条长消息必须保留
    assert result[-1] == long
    assert "最早的问题" not in [m.content for m in result]


def test_trim_messages_protects_tool_call_pairing():
    """AI 的 tool_calls 与其 ToolMessage 结果成组保留，不被拆散。"""
    ai_with_call = AIMessage(
        content="",
        tool_calls=[{"name": "search_lab_docs", "args": {"q": "规则"}, "id": "c1"}],
    )
    tool_result = ToolMessage(content="检索结果", tool_call_id="c1", name="search_lab_docs")
    # 前面塞一条超长的旧消息，迫使裁剪。
    old = HumanMessage(content="旧" * 4000)
    messages = [old, ai_with_call, tool_result]
    result = agent_service._trim_messages(messages, budget_tokens=50)
    # 工具调用与结果必须同时存在
    assert any(isinstance(m, AIMessage) and m.tool_calls for m in result)
    assert any(isinstance(m, ToolMessage) for m in result)
    assert ai_with_call in result
    assert tool_result in result


def test_trim_messages_summary_strategy_adds_placeholder(monkeypatch):
    """summary 策略：裁剪后在最前面插入一条摘要占位消息。"""
    monkeypatch.setattr(agent_service.settings, "TRIM_STRATEGY", "summary")
    messages = [
        HumanMessage(content="旧" * 4000),
        AIMessage(content="旧答复"),
        HumanMessage(content="新问题"),
    ]
    result = agent_service._trim_messages(messages, budget_tokens=50)
    assert isinstance(result[0], HumanMessage)
    assert "省略" in result[0].content
    assert result[-1].content == "新问题"
