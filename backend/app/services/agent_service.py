"""LangGraph 版单智能体（生产级升级）。

相比初版的三处关键升级：
1. 自定义 AgentState：messages + approval，为后续多智能体扩展留好位置。
2. checkpointer 持久化：会话状态落盘（SQLite 或 PostgreSQL），服务重启后仍可
   继续多轮对话，用 thread_id 做会话隔离。
3. human-in-the-loop：写库类工具通过 LangGraph interrupt 真正中断等待用户确认，
   而不是靠 system prompt 让模型“自觉”询问。

注意：LangGraph 1.2 的 interrupt 语义是——invoke/astream 返回的 state 里带
`__interrupt__` 键（不再抛 GraphInterrupt），恢复时用 Command(resume=...) 传入决策。
异步流式必须使用 AsyncSqliteSaver / AsyncPostgresSaver（同步版不支持 astream_events）。
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Any, TypedDict

from sqlalchemy.orm import Session

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.user import User
from app.schemas.ai import ChatRequest
from app.services import agent_tools

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    """Agent 的共享状态。

    - messages：对话消息，add_messages 保证同名 key 是追加而不是覆盖。
    - approval：最近一次人工审批的决策，approval 节点写入、tools 节点读取。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    approval: dict | None


class ApprovalRequired(Exception):
    """写库类工具需要用户确认时抛给 API 层的信号。"""

    def __init__(self, thread_id: str, payload: dict):
        self.thread_id = thread_id
        self.payload = payload
        super().__init__("需要用户确认后再执行")


SYSTEM_PROMPT = """你是智能实验室预约系统的 Agent，回答要简洁。
你可以：
1. 使用 search_lab_docs 查询实验室的规则、安全、开放时间等问题
2. 使用 list_open_labs / list_lab_equipments 查询真实的实验室和设备
3. 在用户确认预约后，使用 create_lab_reservation 进行真实的预约落库
4. 使用 get_today 进行日期的换算

## 必须遵守
当用户提到今天、明天、后天等日期问题时，请先调用 get_today 获取日期，
不要直接返回“我需要确定明天的具体日期”。

提交预约前必须向用户复述：实验室ID与名称（或设备ID和名称）、日期、开始时间、结束时间，
并得到用户确认后再调用 create_lab_reservation。系统会在真正落库前再次弹出确认，
这是最后一道保护，用户没有明确确认时不要硬调工具。

预约成功后状态是待审核，必须管理员确认后实验室（或设备）才能使用。
不要编造数据库里没有的实验室或设备信息。
询问开放时间或实验室规则时，优先调用 search_lab_docs。

## 引用要求
search_lab_docs 返回的资料会带 [文件名#块号] 这样的来源标记。知识库同时包含系统内置文档
和用户上传的文档，回答时要注明依据的文件名，例如「根据《量子实验室说明.md》」，
不要只给结论而不说明出处。
"""

# 工具英文名 -> 页面上展示的中文过程文案。
TOOL_LABELS = {
    "search_lab_docs": "检索实验室知识库",
    "list_open_labs": "查询开放实验室",
    "list_lab_equipments": "查询实验室设备",
    "create_lab_reservation": "提交预约",
    "get_today": "获取今天日期",
}

# 需要人工审批的写库类工具。
WRITE_TOOLS = {"create_lab_reservation"}


# checkpointer 单例：进程内复用同一个连接，启动时建立、关闭时释放。
# 后端可选：配置 CHECKPOINT_DATABASE_URL 用 PostgreSQL（生产推荐，多实例安全），
# 否则回退 SQLite（零配置本地开发）。
_checkpointer = None
_checkpointer_cm = None


async def get_checkpointer():
    """懒加载全局 checkpointer。

    - 配置了 CHECKPOINT_DATABASE_URL → AsyncPostgresSaver（会话状态与业务库同源）。
    - 否则 → AsyncSqliteSaver（本地文件，零配置）。
    """
    global _checkpointer, _checkpointer_cm
    if _checkpointer is not None:
        return _checkpointer

    if settings.CHECKPOINT_DATABASE_URL:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(
            settings.CHECKPOINT_DATABASE_URL
        )
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()
        logger.info("checkpointer 已就绪：PostgreSQL")
    else:
        path = Path(settings.CHECKPOINT_DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(path))
        _checkpointer = await _checkpointer_cm.__aenter__()
        logger.info("checkpointer 已就绪：SQLite（%s）", path)
    return _checkpointer


async def close_checkpointer() -> None:
    """应用关闭时释放 checkpointer 连接。"""
    global _checkpointer, _checkpointer_cm
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer_cm = None
        _checkpointer = None


def _route_after_agent(state: AgentState) -> str:
    """模型返回 tool_calls 则先进审批节点，否则结束本轮。"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return "end"


async def _invoke_tool_with_retry(tool, args: dict) -> str:
    """执行工具：线程池里跑（避免阻塞事件循环），带超时与有限重试。

    - 超时兜底：DB 慢查询或外部调用卡住时，不让它拖垮整张图。
    - 重试：只针对临时性故障重试有限次，最终失败再回填错误 JSON 给模型自纠。
    """
    last_error: Exception | None = None
    for attempt in range(settings.TOOL_MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(tool.invoke, args),
                timeout=settings.TOOL_TIMEOUT_SECONDS,
            )
            return result.content if hasattr(result, "content") else str(result)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < settings.TOOL_MAX_RETRIES:
                await asyncio.sleep(0.2 * (attempt + 1))
    return json.dumps({"ok": False, "error": str(last_error)}, ensure_ascii=False)


def _estimate_tokens(message: AnyMessage) -> int:
    """轻量 token 估算：字符数 / 4 向上取整。

    不引入 tiktoken（依赖重、且对中文分词不准），用「字符/4」做保守近似：
    英文 1 token ≈ 4 字符，中文 1 token ≈ 1~1.5 字符，因此对中文这是
    偏高的估计（更早触发裁剪），宁多剪不越界。工具调用参数也会计入，
    避免大段检索结果被漏算。
    """
    content = getattr(message, "content", "") or ""
    text = content if isinstance(content, str) else str(content)
    extra = 0
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        extra += len(json.dumps(tool_calls, ensure_ascii=False, default=str))
    return (len(text) + extra + 3) // 4


def _trim_messages(messages: list[AnyMessage], budget_tokens: int) -> list[AnyMessage]:
    """把消息裁剪进 token 预算，保证 model 不因超长而报错。

    策略（TRIM_STRATEGY）：
    - sliding_window（默认）：从最老的消息开始丢弃，保留最新的；
    - summary：丢弃的早期消息用一条 HumanMessage 摘要占位（内容描述
      「已省略 N 条更早的对话」），保留更久远的语义线索。

    边界处理：
    - 单条消息本身超过预算时不硬裁，直接返回（避免截断出残缺的 tool_calls）。
    - 优先保护「AI 带 tool_calls + 其后紧邻的 ToolMessage」配对，避免把
      工具调用和它的结果拆散，导致模型拿到没有结果的 tool_call 报错。
    """
    if not messages or budget_tokens <= 0:
        return list(messages)

    total = sum(_estimate_tokens(m) for m in messages)
    if total <= budget_tokens:
        return list(messages)

    # 找出「AI 带 tool_calls」的位置，其后的 ToolMessage 与它绑定，裁剪时成组处理。
    protected = set()
    for i, m in enumerate(messages):
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                protected.add(j)
                j += 1
    # 最新的那条（可能是 ToolMessage）也始终保留，它是本轮要回应的依据。
    if messages:
        protected.add(len(messages) - 1)

    keep = list(messages)
    strategy = settings.TRIM_STRATEGY
    # 从最老（索引 0）向新裁剪；受保护的 ToolMessage 与它前面的 AI 一起保留。
    dropped = 0
    i = 0
    while i < len(keep) and sum(_estimate_tokens(m) for m in keep) > budget_tokens:
        if i in protected:
            i += 1
            continue
        del keep[i]
        dropped += 1
        # 删除后索引整体前移，受保护索引需同步左移。
        protected = {p - 1 if p > i else p for p in protected}

    if strategy == "summary" and dropped > 0:
        summary = HumanMessage(
            content=f"[系统提示] 更早的 {dropped} 条对话因上下文长度已省略，"
            "请仅基于下方仍然保留的内容回答。"
        )
        keep = [summary, *keep]

    return keep


async def build_agent(db: Session, current_user: User, include_uploaded: bool = True):
    """构建并编译带 checkpointer 的 LangGraph Agent。"""
    if not settings.LLM_API_KEY:
        raise BusinessException(message="未配置大模型 API Key")

    tools = await agent_tools.build_tools(db, current_user, include_uploaded=include_uploaded)
    tools_by_name = {tool.name: tool for tool in tools}
    llm = ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0,
        streaming=True,
    ).bind_tools(tools)

    async def agent_node(state: AgentState) -> dict:
        """agent 节点：调用大模型，返回新的 AI 消息。"""
        # system prompt 每次调用时注入，不放进 state，避免被 checkpointer 反复持久化。
        # 上下文窗口保护：送入模型前先按 token 预算裁剪历史，防止长对话撑爆 context。
        history = _trim_messages(state["messages"], settings.MAX_CONTEXT_TOKENS)
        response = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
        return {"messages": [response]}

    async def approval_node(state: AgentState) -> dict:
        """审批节点：命中写库工具时 interrupt 暂停，等用户确认。"""
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        write_calls = [tc for tc in tool_calls if tc.get("name") in WRITE_TOOLS]
        if not write_calls:
            return {"approval": None}

        payload = {
            "tool": write_calls[0].get("name"),
            "args": write_calls[0].get("args") or {},
        }
        decision = interrupt(payload)
        if not isinstance(decision, dict):
            decision = {"approved": bool(decision)}
        return {"approval": decision}

    async def tool_node(state: AgentState) -> dict:
        """工具节点：执行模型请求的工具，写库工具遵守审批结果。"""
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        approval = state.get("approval")
        messages: list[ToolMessage] = []

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args") or {}
            tool = tools_by_name.get(name)

            if name in WRITE_TOOLS and (not approval or not approval.get("approved")):
                content = "用户取消了本次操作，未执行。"
            elif tool is None:
                content = f"未找到工具：{name}"
            else:
                content = await _invoke_tool_with_retry(tool, args)

            messages.append(
                ToolMessage(
                    content=content,
                    tool_call_id=tc.get("id"),
                    name=name,
                )
            )
        return {"messages": messages}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("approval", approval_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", _route_after_agent, {"approval": "approval", "end": END}
    )
    graph.add_edge("approval", "tools")
    graph.add_edge("tools", "agent")

    checkpointer = await get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


def _make_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}


def _interrupt_payload(interrupts: list) -> dict:
    """从 state 里的 __interrupt__ 列表取第一个中断的负载。"""
    if not interrupts:
        return {}
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


def _build_input_messages(data: ChatRequest) -> list:
    """只取本轮新增的用户消息；历史由 checkpointer 负责，前端不再回传。"""
    messages = []
    for message in data.messages or []:
        if message.role == "user" and message.content.strip():
            messages.append(HumanMessage(content=message.content.strip()))
    if not messages:
        raise BusinessException(message="请输入您要对话的内容")
    return messages


def _last_ai_text(messages: list) -> str:
    """从 Agent 结果里取最后一条有内容的 AI 消息。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            content = message.content
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            if str(content or "").strip():
                return str(content).strip()
    raise BusinessException(message="大模型没有任何返回内容")


async def run_agent(
    db: Session, current_user: User, data: ChatRequest, thread_id: str
) -> str:
    """非流式执行 Agent。遇到写库工具会抛 ApprovalRequired。"""
    agent = await build_agent(db, current_user, data.include_uploaded)
    inputs = {"messages": _build_input_messages(data)}
    try:
        result = await agent.ainvoke(inputs, _make_config(thread_id))
    except BusinessException:
        raise
    except Exception:
        raise BusinessException(message="大模型调用失败，请稍后重试")

    interrupts = result.get("__interrupt__")
    if interrupts:
        raise ApprovalRequired(thread_id=thread_id, payload=_interrupt_payload(interrupts))
    return _last_ai_text(result.get("messages") or [])


async def resume_agent(
    db: Session,
    current_user: User,
    thread_id: str,
    approved: bool,
    include_uploaded: bool = True,
) -> str:
    """用用户决策恢复被中断的 Agent。"""
    agent = await build_agent(db, current_user, include_uploaded)
    try:
        result = await agent.ainvoke(
            Command(resume={"approved": approved}), _make_config(thread_id)
        )
    except BusinessException:
        raise
    except Exception:
        raise BusinessException(message="大模型调用失败，请稍后重试")

    interrupts = result.get("__interrupt__")
    if interrupts:
        raise ApprovalRequired(thread_id=thread_id, payload=_interrupt_payload(interrupts))
    return _last_ai_text(result.get("messages") or [])


def _chunk_text(chunk: Any) -> str:
    """从模型流式 chunk 中提取纯文本。"""
    if chunk is None:
        return ""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content) if content is not None else ""


def _tool_output_preview(output: Any, limit: int = 200) -> str:
    """把工具结果收成短预览，避免整段 JSON 刷到前端。"""
    if isinstance(output, ToolMessage):
        output = output.content
    text = output if isinstance(output, str) else str(output)
    return text if len(text) <= limit else text[:limit] + "…"


async def _stream_events(agent, inputs: Any, thread_id: str):
    """统一处理 astream_events 的输出，转成前端可消费的事件。"""
    yield {"type": "status", "message": "正在思考…"}
    try:
        async for event in agent.astream_events(
            inputs, version="v2", config=_make_config(thread_id)
        ):
            kind = event.get("event")

            # 图层面抛出的中断：LangGraph 1.2 以 on_chain_stream 携带 __interrupt__。
            if kind == "on_chain_stream" and event.get("name") == "LangGraph":
                chunk = (event.get("data") or {}).get("chunk") or {}
                interrupts = chunk.get("__interrupt__")
                if interrupts:
                    yield {
                        "type": "approval_required",
                        "thread_id": thread_id,
                        "payload": _interrupt_payload(interrupts),
                    }
                    return

            if kind == "on_tool_start":
                name = event.get("name") or ""
                yield {
                    "type": "tool_start",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                }
            elif kind == "on_tool_end":
                name = event.get("name") or ""
                yield {
                    "type": "tool_end",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                    "preview": _tool_output_preview(
                        (event.get("data") or {}).get("output")
                    ),
                }
            elif kind == "on_chat_model_stream":
                meta = event.get("metadata") or {}
                if meta.get("langgraph_node") not in (None, "agent"):
                    continue
                text = _chunk_text((event.get("data") or {}).get("chunk"))
                if text:
                    yield {"type": "token", "content": text}

        yield {"type": "done"}
    except BusinessException as exc:
        yield {"type": "error", "message": exc.message}
    except Exception:
        logger.exception("Agent 流式执行失败")
        yield {"type": "error", "message": "大模型调用失败，请稍后重试"}


async def stream_agent(db: Session, current_user: User, data: ChatRequest, thread_id: str):
    """流式执行 Agent（首轮）。"""
    agent = await build_agent(db, current_user, data.include_uploaded)
    inputs = {"messages": _build_input_messages(data)}
    async for event in _stream_events(agent, inputs, thread_id):
        yield event


async def resume_stream_agent(
    db: Session,
    current_user: User,
    thread_id: str,
    approved: bool,
    include_uploaded: bool = True,
):
    """流式恢复被中断的 Agent。"""
    agent = await build_agent(db, current_user, include_uploaded)
    inputs = Command(resume={"approved": approved})
    async for event in _stream_events(agent, inputs, thread_id):
        yield event
