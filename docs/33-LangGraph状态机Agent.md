# 33 · LangGraph Agent 状态机（checkpointer / interrupt / 上下文裁剪）

> **速成定位**：整份简历含金量最高的一块。面试官问「你和只会调 API 的人有什么区别」，答案就在这里。
> **一句话**：不是一次性 `llm.invoke` 拿答案，而是把「模型 → 工具 → 模型」建模成一张**有状态、可持久化、可中断**的图（StateGraph）。

---

## 目录

1. [为什么需要 Agent 框架](#1-为什么需要-agent-框架)
2. [StateGraph 五要素](#2-stategraph-五要素)
3. [AgentState 与 add_messages](#3-agentstate-与-add_messages)
4. [本项目的图结构（三节点）](#4-本项目的图结构)
5. [checkpointer：会话持久化与双后端](#5-checkpointer会话持久化)
6. [interrupt：真正的 Human-in-the-Loop](#6-interrupt真正的-human-in-the-loop)
7. [上下文窗口保护](#7-上下文窗口保护)
8. [流式事件 astream_events](#8-流式事件)
9. [最小可运行骨架](#9-最小可运行骨架)
10. [项目里对应哪块代码](#10-项目里对应哪块代码)
11. [面试高频问答](#11-面试高频问答)
12. [速记卡](#12-速记卡)

---

## 1. 为什么需要 Agent 框架

### 朴素写法的问题

```python
resp = await llm.ainvoke([...])           # 模型说要调工具
tool_result = search(query)                # 手动执行
resp2 = await llm.ainvoke([... resp, tool_result])   # 再问一次
```

手写循环能跑，但会遇到五个绕不开的问题：

| 问题 | LangGraph 的答案 |
| --- | --- |
| 多轮循环怎么组织？ | **StateGraph**：节点 + 边 + 条件路由 |
| 历史怎么累加？ | **State + reducer**（`add_messages`） |
| 服务重启后还能接着聊吗？ | **checkpointer** 持久化 |
| 危险操作怎么等人工确认？ | **interrupt + Command(resume)** |
| 怎么边跑边输出？ | **astream_events** |

**核心认知（面试一句话概括）**：
> LangGraph 把 Agent 从「一串函数调用」升级为「一台**可持久化、可中断、可观测的状态机**」。

---

## 2. StateGraph 五要素

```text
State  ─── 在节点之间流转的共享数据（本项目：messages + approval）
Node   ─── 一个处理步骤，接收 state 返回 state 的增量
Edge   ─── 节点之间的连线
Conditional Edge ─── 根据 state 决定走哪条边（路由）
Checkpointer ─── 每一步之后把 state 落盘
```

编译后得到一个可执行对象：`graph.compile(checkpointer=...)`。

---

## 3. AgentState 与 add_messages

`agent_service.py:45-53`：

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    approval: dict | None
```

**`Annotated[..., add_messages]` 是精髓**。它声明了「这个字段的**合并规则**」：

- 没有 reducer 时：`return {"messages": [new]}` 会**覆盖**原来的列表。
- 有了 `add_messages`：新消息会**追加**到历史后面（同 id 的消息则是更新）。

这就是「多轮对话自动累积历史」的实现原理，你不需要手动 `history.append()`。

> **面试点**：`add_messages` 是 LangGraph 预置的 reducer，本质上是一个函数 `(旧state, 新state) -> 合并后的state`。理解这一点就理解了 LangGraph 的状态管理。

`approval` 字段是普通 `dict | None`：**没有** reducer，所以每次写入都是覆盖——正好符合语义（只关心最近一次审批决策）。

---

## 4. 本项目的图结构

```
    START
      │
      ▼
   ┌───────┐
   │ agent │  ← 调 LLM，system prompt 每次注入
   └───┬───┘
       │ _route_after_agent
   ┌───┴──────────────┐
   │                  │
有 tool_calls        无 tool_calls
   │                  │
   ▼                  ▼
┌──────────┐        END
│ approval │  ← 写库工具才 interrupt
└────┬─────┘
     ▼
 ┌───────┐
 │ tools │  ← 执行工具
 └───┬───┘
     └────→ 回到 agent（让模型看到工具结果再回答）
```

`agent_service.py:244-256`：

```python
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("approval", approval_node)
graph.add_node("tools", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", _route_after_agent,
                            {"approval": "approval", "end": END})
graph.add_edge("approval", "tools")
graph.add_edge("tools", "agent")
```

### 节点 1：`agent_node`（`agent_service.py:191-197`）

```python
async def agent_node(state: AgentState) -> dict:
    history = _trim_messages(state["messages"], settings.MAX_CONTEXT_TOKENS)
    response = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
    return {"messages": [response]}
```

**两个设计点**：
1. **system prompt 每次注入而不是放进 state** —— 注释写明原因：避免被 checkpointer 反复持久化，也方便随时改 prompt 而老会话立刻生效。
2. **调用前先裁剪历史** —— 见第 7 节。

### 节点 2：`approval_node`（`agent_service.py:199-214`）

```python
tool_calls = getattr(last, "tool_calls", None) or []
write_calls = [tc for tc in tool_calls if tc.get("name") in WRITE_TOOLS]
if not write_calls:
    return {"approval": None}          # 只读工具：直接放行

payload = {"tool": ..., "args": ...}
decision = interrupt(payload)           # ← 图在这里【暂停】
return {"approval": decision}
```

`WRITE_TOOLS = {"create_lab_reservation"}`：只有**写库**工具需要审批，查询类工具不打断用户体验。

### 节点 3：`tool_node`（`agent_service.py:216-242`）

```python
if name in WRITE_TOOLS and (not approval or not approval.get("approved")):
    content = "用户取消了本次操作，未执行。"       # 用户点了「取消」
elif tool is None:
    content = f"未找到工具：{name}"
else:
    content = await _invoke_tool_with_retry(tool, args)   # 带超时重试
```

**关键**：审批被拒时**不是什么都不做**，而是回填一条明确的 ToolMessage 告诉模型「用户取消了」，模型才能据此回复用户，而不是卡住或瞎编。

### 条件路由（`agent_service.py:147-152`）

```python
def _route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return "end"
```

---

## 5. checkpointer：会话持久化

### 5.1 它解决什么

没有 checkpointer 时，`state` 只在内存里，服务重启就丢。有了它：

- 每个 **thread_id** 是一条独立会话线，多路会话互不干扰。
- 图每执行完一个节点就自动存一次快照。
- 用同一个 thread_id 再次 invoke，会自动把历史加载回来继续。

### 5.2 本项目的双后端（`agent_service.py:110-135`）

```python
async def get_checkpointer():
    if settings.CHECKPOINT_DATABASE_URL:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.CHECKPOINT_DATABASE_URL)
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()          # 建表
    else:
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(path))
        _checkpointer = await _checkpointer_cm.__aenter__()
    return _checkpointer
```

| 后端 | 场景 | 说明 |
| --- | --- | --- |
| **AsyncPostgresSaver** | 生产 | 多实例共享、会话状态与业务库同源 |
| **AsyncSqliteSaver** | 本地零配置 | 单文件，开箱即用 |

### 5.3 三个必须知道的坑（面试金句）

**坑 1：必须用异步版。**
> 注释第一行就写了：异步流式必须使用 `AsyncSqliteSaver` / `AsyncPostgresSaver`，**同步版不支持 `astream_events`**。

**坑 2：`from_conn_string` 返回的是异步上下文管理器，不是实例。**
```python
cm = AsyncPostgresSaver.from_conn_string(url)
saver = await cm.__aenter__()      # 必须手动进入
await saver.setup()                # 还要建表
```
退出时 `await cm.__aexit__(None, None, None)`（项目在 `close_checkpointer()` 里做）。

**坑 3：checkpointer 是进程级单例。**
模块级 `_checkpointer` 全局变量 + 懒加载，应用关闭时由 `main.py:50` 的 `close_checkpointer()` 释放。

### 5.4 thread_id 从哪来

- 后端：`api/ai.py:32` `thread_id = data.thread_id or _new_thread_id()`（UUID4）。
- 前端：`AIChat.vue` 里一个页面会话生成一个 `crypto.randomUUID()`，多轮对话复用。

> **注意**：历史由 checkpointer 负责，**前端不再回传全部历史**，只发本轮新消息（`_build_input_messages`）。项目有专门的测试 `test_multiturn_does_not_duplicate_history` 验证不会出现历史重复。

---

## 6. interrupt：真正的 Human-in-the-Loop

### 6.1 假 HITL vs 真 HITL

**假 HITL**（很多 Demo 这么干）：
```python
SYSTEM_PROMPT = "提交预约前必须先询问用户确认"
```
问题：模型是概率性的，可能不遵守；也没法真正「暂停」等用户。

**真 HITL**（本项目）：
```python
decision = interrupt(payload)     # 图真正暂停，state 已落盘
# ... 几分钟后用户点了确认 ...
graph.ainvoke(Command(resume={"approved": True}), config)
```

### 6.2 LangGraph 1.2 的 interrupt 语义（版本坑）

> **面试加分点**：「不同版本 interrupt 的语义不一样，我踩过。」

- 旧版本：抛 `GraphInterrupt` 异常。
- **本项目版本（1.2）**：不抛异常，而是**返回的 state 里带 `__interrupt__` 键**。

所以要这样判断（`agent_service.py:311-313`）：

```python
result = await agent.ainvoke(inputs, config)
interrupts = result.get("__interrupt__")
if interrupts:
    raise ApprovalRequired(thread_id=thread_id, payload=_interrupt_payload(interrupts))
```

恢复时用 `Command(resume=...)` 作为输入：

```python
result = await agent.ainvoke(Command(resume={"approved": approved}), config)
```

### 6.3 完整闭环

```text
① 用户："帮我预约明天下午的实验室"
② agent_node → 模型返回 tool_calls=[create_lab_reservation]
③ approval_node → interrupt(payload) → 图暂停
④ API 层检测到 __interrupt__ → 抛 ApprovalRequired → 返回 {type:"approval_required"}
⑤ 前端弹出确认框，展示实验室/日期/时段
⑥ 用户点确认 → POST /api/ai/chat/stream/resume {thread_id, approved:true}
⑦ approval_node 从断点继续，拿到 decision={"approved":True}
⑧ tool_node 执行真实落库
⑨ 回到 agent_node → 模型生成"预约已提交，请等待管理员审核"
```

**为什么能「从断点继续」**：因为 checkpointer 已经把断点前的 state（包括那条带 tool_calls 的 AI 消息）落盘了，恢复时用同一个 thread_id 就能精确回到那个位置。

> 这就是 **checkpointer 和 interrupt 必须配套使用**的原因：没有持久化，就没有「稍后恢复」。

### 6.4 非流式与流式两条路

| 路径 | 非流式 | 流式 |
| --- | --- | --- |
| 首轮 | `run_agent` → `ainvoke` | `stream_agent` → `astream_events` |
| 恢复 | `resume_agent` → `ainvoke(Command(resume))` | `resume_stream_agent` → `astream_events(Command(resume))` |
| 中断检测 | `result["__interrupt__"]` | 监听 `on_chain_stream` 事件里的 `chunk["__interrupt__"]` |

---

## 7. 上下文窗口保护

### 7.1 问题

`agent_node` 把 `state["messages"]` 全量塞给 LLM。多轮对话 + 每次检索都返回大段父上下文，token 会一路涨，最终**超出模型 context window 报错**。

### 7.2 本项目方案（`agent_service.py:155-215`）

**token 估算**（字符/4）：

```python
def _estimate_tokens(message: AnyMessage) -> int:
    content = getattr(message, "content", "") or ""
    text = content if isinstance(content, str) else str(content)
    extra = 0
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        extra += len(json.dumps(tool_calls, ensure_ascii=False, default=str))
    return (len(text) + extra + 3) // 4
```

**为什么不引入 tiktoken**：依赖重，且对中文分词不准。字符/4 对英文准确，对中文是**保守偏高**估计（1 中文字符 ≈ 1~1.5 token，按 4 算会高估 → 更早触发裁剪 → 更安全）。

**裁剪**（`_trim_messages`）：

```python
MAX_CONTEXT_TOKENS: int = 4000      # 预算
TRIM_STRATEGY: str = "sliding_window"   # 或 "summary"
```

- `sliding_window`：从最老开始丢，保留最新。
- `summary`：丢掉的早期对话压成一条占位消息 `[系统提示] 更早的 N 条对话因上下文长度已省略…`。

**最关键的一个边界处理**（面试必讲）：

```python
# 保护「AI 带 tool_calls」与其后紧邻 ToolMessage 的配对
for i, m in enumerate(messages):
    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
        j = i + 1
        while j < len(messages) and isinstance(messages[j], ToolMessage):
            protected.add(j); j += 1
```

> 为什么必须保护配对？如果只留下「AI 说要调工具」而丢掉「工具返回结果」，模型会收到一条**没有结果的 tool_call**，很多模型会直接报错。这是裁剪时最容易踩的坑。

---

## 8. 流式事件

`agent_service.py:367-418` 用 `astream_events(version="v2")` 把图内部事件转成前端可消费的消息：

| 事件 | 前端展示 |
| --- | --- |
| `on_chain_stream` + `name=="LangGraph"` 且含 `__interrupt__` | 弹审批确认框 |
| `on_tool_start` | 「正在检索实验室知识库…」 |
| `on_tool_end` | 「检索实验室知识库完成」+ 结果预览 |
| `on_chat_model_stream` | 逐字输出 token |

**一个细节**：`on_chat_model_stream` 里过滤了 `metadata.langgraph_node`，只保留 `agent` 节点的输出，避免把摘要/改写等其它模型的输出混进对话流。

---

## 9. 最小可运行骨架

不需要真实大模型和网络，用假 LLM 即可跑通**编译图 → 工具调用 → interrupt → 恢复**全流程。`pip install langgraph langchain-core`。

```python
"""最小骨架：StateGraph + checkpointer + interrupt(HITL) 完整闭环。
不需要真实大模型：用一个假 LLM 模拟「先要调工具，再回答」。"""

import asyncio
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from typing import Annotated, TypedDict


# ============ 1. State：messages 用 add_messages 追加 ============
class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]     # reducer：追加而非覆盖
    approval: dict | None                        # 无 reducer：覆盖语义


# ============ 2. 假 LLM：第一轮返回 tool_call，第二轮返回文本 ============
class FakeLLM:
    def __init__(self):
        self.n = 0

    async def ainvoke(self, messages):
        self.n += 1
        if self.n == 1:
            # 模拟模型决定调用「写库工具」
            return AIMessage(content="", tool_calls=[
                {"name": "create_reservation", "args": {"lab_id": 1}, "id": "c1"}
            ])
        return AIMessage(content="预约已提交，请等待管理员审核")


llm = FakeLLM()
WRITE_TOOLS = {"create_reservation"}


# ============ 3. 节点 ============
async def agent_node(state: AgentState) -> dict:
    print("  [agent] 调用模型")
    # system prompt 每次注入，不进 state，避免被持久化
    resp = await llm.ainvoke([SystemMessage(content="你是助手"), *state["messages"]])
    return {"messages": [resp]}


async def approval_node(state: AgentState) -> dict:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    write_calls = [tc for tc in tool_calls if tc.get("name") in WRITE_TOOLS]
    if not write_calls:
        return {"approval": None}                 # 只读工具不打断

    print("  [approval] ⏸ 中断等待用户确认")
    decision = interrupt({"tool": write_calls[0]["name"], "args": write_calls[0]["args"]})
    print(f"  [approval] ▶ 收到决策: {decision}")
    return {"approval": decision}


async def tool_node(state: AgentState) -> dict:
    last = state["messages"][-1]
    approval = state.get("approval")
    out = []
    for tc in (getattr(last, "tool_calls", None) or []):
        if tc["name"] in WRITE_TOOLS and not (approval or {}).get("approved"):
            content = "用户取消了本次操作，未执行。"
        else:
            content = '{"ok": true, "message": "预约已提交"}'
        out.append(ToolMessage(content=content, tool_call_id=tc["id"], name=tc["name"]))
    return {"messages": out}


def route(state: AgentState) -> str:
    if getattr(state["messages"][-1], "tool_calls", None):
        return "approval"
    return "end"


# ============ 4. 组装图 ============
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("approval", approval_node)
graph.add_node("tools", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", route, {"approval": "approval", "end": END})
graph.add_edge("approval", "tools")
graph.add_edge("tools", "agent")


async def main():
    # ============ 5. checkpointer：异步版 + 手动进入上下文 ============
    cm = AsyncSqliteSaver.from_conn_string("./mini_ckpt.db")
    ckpt = await cm.__aenter__()
    app = graph.compile(checkpointer=ckpt)

    thread_id = uuid.uuid4().hex
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}

    # ---- 第一轮：会在 approval 节点中断 ----
    print("第一轮：")
    result = await app.ainvoke(
        {"messages": [HumanMessage(content="帮我预约明天下午的实验室")]}, config
    )
    interrupts = result.get("__interrupt__")
    if interrupts:
        print(f"  ✅ 检测到中断，payload={interrupts[0].value}")

    # ---- 第二轮：用户点了「确认」，用 Command(resume) 恢复 ----
    print("第二轮（用户确认）：")
    result = await app.ainvoke(Command(resume={"approved": True}), config)
    print(f"  ✅ 最终回复: {result['messages'][-1].content}")

    await cm.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
```

**预期输出**：

```text
第一轮：
  [agent] 调用模型
  [approval] ⏸ 中断等待用户确认
  ✅ 检测到中断，payload={'tool': 'create_reservation', 'args': {'lab_id': 1}}
第二轮（用户确认）：
  [approval] ▶ 收到决策: {'approved': True}
  ✅ 最终回复: 预约已提交，请等待管理员审核
```

注意第二轮**没有再次打印 `[agent] 调用模型` 之前的中断**——它从 `approval` 节点**断点处继续**，这正是 checkpointer 的价值。

---

## 10. 项目里对应哪块代码

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| **AgentState** | `agent_service.py:45-53` | `messages`(add_messages) + `approval` |
| **图组装** | `agent_service.py:244-256` | 3 节点 + 条件边 + `checkpointer` |
| **条件路由** | `agent_service.py:147-152` | 有 tool_calls → approval，否则 END |
| **agent 节点** | `agent_service.py:191-197` | 裁剪 + system prompt 注入 |
| **approval 节点** | `agent_service.py:199-214` | 只拦 `WRITE_TOOLS` |
| **tool 节点** | `agent_service.py:216-242` | 审批拒绝 → 回填「用户取消」 |
| **checkpointer 双后端** | `agent_service.py:110-135` | PG / SQLite 异步版 |
| **关闭释放** | `agent_service.py:138-144` | `__aexit__` |
| **token 估算** | `agent_service.py:155-173` | `_estimate_tokens` 字符/4 |
| **历史裁剪** | `agent_service.py:176-215` | `_trim_messages`，保护 tool_calls 配对 |
| **超时重试** | `agent_service.py:155-173`（上一版）/ 现 176 前 | `_invoke_tool_with_retry` |
| **非流式执行** | `agent_service.py:298-314` | `run_agent` + `__interrupt__` 检测 |
| **恢复执行** | `agent_service.py:317-338` | `Command(resume=...)` |
| **流式事件** | `agent_service.py:367-418` | `astream_events` v2 |
| **审批异常** | `agent_service.py:56-62` | `ApprovalRequired(thread_id, payload)` |
| **API 四个入口** | `api/ai.py:25/49/82/108` | chat / resume / stream / stream-resume |
| **配置** | `config.py:105-112 / 118-130` | `CHECKPOINT_DATABASE_URL`、`MAX_CONTEXT_TOKENS`、`TRIM_STRATEGY` |

**测试用例**（`backend/tests/test_agent_service.py`，共 16 个）：

| 测试 | 验证 |
| --- | --- |
| `test_route_with_tool_calls` | 路由逻辑 |
| `test_interrupt_approval_flow` | 假 LLM 跑通 interrupt 闭环 |
| `test_multiturn_does_not_duplicate_history` | 多轮不重复历史 |
| `test_checkpointer_sqlite_fallback_when_no_pg` | 无 PG 时回退 SQLite |
| `test_trim_messages_protects_tool_call_pairing` | 裁剪不拆散工具配对 |
| `test_invoke_tool_with_retry_recovers_on_second_try` | 重试恢复 |

---

## 11. 面试高频问答

**Q1：为什么用 LangGraph 而不是自己写循环？**
> 自己写循环能跑通 Demo，但五件事做不好：多轮历史累积、服务重启后恢复、危险操作等待人工确认、流式输出每一步、超长对话的上下文管理。LangGraph 把这些都变成了框架能力——State + reducer 管历史，checkpointer 管持久化，interrupt 管人工介入，astream_events 管可观测性。

**Q2：`add_messages` 是干什么的？**
> 它是一个 reducer，定义了 state 中 messages 字段的合并规则：新消息**追加**到历史（同 id 则更新）。没有它，节点返回 `{"messages": [new]}` 会直接覆盖掉历史。理解了 reducer 就理解了 LangGraph 的状态管理。

**Q3：怎么做到服务重启后还能继续多轮对话？**
> checkpointer 在每执行完一个节点后把 state 快照落盘（本项目 PostgreSQL 或 SQLite），用 thread_id 做会话隔离。下次用同一个 thread_id invoke，会自动加载历史。所以前端**只发本轮新消息**，历史不回传——我有专门的测试验证不会出现历史重复。

**Q4：人工审批是怎么实现的？靠 prompt 让模型自觉吗？**
> 不是。用的是 LangGraph 原生 `interrupt()`：命中写库工具时图真正暂停，state 已落盘；用户确认后用 `Command(resume={"approved": True})` 从断点恢复。**区别在于这是框架级的中断，模型即使想硬来也绕不过去。** 而且只有 `create_lab_reservation` 这类写库工具会触发，查询工具不打断体验。

**Q5（进阶）：不同版本 interrupt 语义不同，你踩过坑吗？**
> 踩过。旧版本是抛 `GraphInterrupt` 异常，本项目用的 1.2 不抛异常，而是在返回的 state 里带 `__interrupt__` 键。所以我用 `result.get("__interrupt__")` 判断中断，恢复时传 `Command(resume=...)`。

**Q6：checkpointer 为什么必须用异步版？**
> 因为项目要 `astream_events` 流式输出，同步版 checkpointer 不支持。另外 `from_conn_string` 返回的是异步上下文管理器而不是实例，必须 `await cm.__aenter__()` 拿到实例，PG 还要再 `setup()` 建表，关闭时 `__aexit__`。

**Q7：长对话怎么防止撑爆上下文？**
> 两层：① token 预算（字符/4 轻量估算，不引入 tiktoken，对中文保守高估），送入模型前按预算裁剪；② 两种策略，滑动窗口直接丢最早的，summary 把丢弃部分压成一条占位摘要。裁剪时有个关键边界——**必须保护「AI 的 tool_calls」和它对应的 ToolMessage 配对**，否则模型会收到没有结果的 tool_call 而报错。

**Q8：用户点了「取消」会发生什么？**
> tool_node 不会真的什么都不做，而是回填一条明确的 ToolMessage「用户取消了本次操作，未执行。」给模型。这样模型才知道发生了什么，才能据此回复用户，而不是卡住或编造结果。

**Q9：thread_id 怎么生成和传递？**
> 后端 `api/ai.py` 在没有传入时用 `uuid4().hex` 生成；前端每个页面会话生成一个 `crypto.randomUUID()` 并复用。它同时是 checkpointer 的会话键和审批恢复的定位键。

**Q10：你的 Agent 怎么保证不无限循环？**
> 配置里设了 `recursion_limit: 10`（`_make_config`），图在 agent → tools → agent 之间循环超过 10 步会强制终止。

---

## 12. 速记卡

```text
LangGraph = 有状态、可持久化、可中断的 Agent 状态机

五要素：State / Node / Edge / ConditionalEdge / Checkpointer

State:
  messages → Annotated[list, add_messages]  (追加;同id更新)
  approval → dict|None                      (覆盖)
  reducer = 合并规则，理解它就理解状态管理

图：START → agent →(有tool_calls?)→ approval → tools → agent → END
                  └─(无)→ END
    system prompt 每次注入，不进 state（不被持久化）

checkpointer:
  AsyncSqliteSaver(零配置) / AsyncPostgresSaver(多实例)
  ⚠️ 必须异步版(同步不支持 astream_events)
  ⚠️ from_conn_string 返回 cm，要 await __aenter__()；PG 还要 setup()
  thread_id 隔离会话；前端只发新消息，历史由它加载

HITL:
  interrupt(payload) → 图暂停(真暂停,非prompt)
  1.2 版本：结果里 __interrupt__ 键（不是抛异常）
  恢复：ainvoke(Command(resume={"approved": True}), config)
  拒绝 → 回填「用户取消了」给模型

上下文保护:
  _estimate_tokens 字符/4（中文保守高估，不用 tiktoken）
  _trim_messages  sliding_window / summary
  ⚠️ 保护 tool_calls + ToolMessage 配对

流式：astream_events(v2) → status/tool_start/tool_end/token/approval_required
防死循环：recursion_limit=10
```
