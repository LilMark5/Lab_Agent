# 第 18 章 · Human-in-the-Loop：让 Agent 在关键处停下来等人

> **这一章要回答的核心问题**：`interrupt()` 这一行为什么能让函数"冻结"再"解冻"？它和 Python 的 `input()` 有什么本质区别？为什么它必须是"节点级"而不是"函数级"？前端是怎么知道该弹确认框的？

---

## 18.1 引子：AI 不能替你按下"提交"键

想象这样一个场景。用户说：

> "帮我把 301 实验室下周所有时段都预约了。"

模型很听话，开始调用 `create_lab_reservation`，一次、两次、三次……每调用一次就往数据库写一条记录。等用户反应过来，已经产生了 15 条待审核的预约单。

再想象一个更严重的：

> "把所有过期的预约记录删掉。"

如果 Agent 有一个 `delete_reservation` 工具，而它的"过期"判断逻辑有偏差，你的生产数据就没了。

**这就是 Agent 工程里最重要的安全命题**：

> **模型可以犯错，但错误不能是不可逆的。**

传统软件里，我们用"二次确认弹窗"解决不可逆操作。Agent 里也一样，但难点在于：**确认的时机是模型运行时决定的，你没法在代码里写死"第 3 步弹窗"**。

LangGraph 的 `interrupt()` 就是为此而生的。它让你可以**在任意节点内部**，用一行代码把整个图的执行冻结住，把控制权交回给调用方（你的 API 层 → 前端 → 用户），等用户决策后再从**同一行**继续。

这一章我们把这套机制从里到外拆开。

---

## 18.2 先理解"为什么难"：三种错误方案

在讲正确方案前，先看三种常见的错误实现。理解它们为什么不行，你才能真正 appreciate `interrupt()` 的设计。

### 方案 A：执行前用 if 判断（伪 HITL）

```python
async def tool_node(state):
    for tc in tool_calls:
        if tc["name"] == "create_lab_reservation":
            # 检查一下有没有用户确认标记
            if not state.get("user_confirmed"):
                return {"messages": [ToolMessage("请先让用户确认")]}
```

**为什么不行**：这不是"暂停等用户"，这是"告诉模型用户没确认"。模型会怎么做？它可能会：

- 再问一遍用户（用户已经烦了）
- 自作主张认为"用户刚才说了预约，算确认了"，然后**再次调用**，陷入死循环
- 直接放弃

**本质问题**：Agent 的执行没有真正停下，只是换了个理由继续跑。

### 方案 B：抛异常中断，下次重跑

```python
async def tool_node(state):
    if is_write(tc) and not confirmed:
        raise NeedApproval(tc)     # 抛异常

# API 层捕获，返回 approval_required
# 用户确认后，前端重新发完整请求，后端重跑整个图
```

**为什么不行**：重跑意味着：

1. **重复消耗**：前面已经做过的 LLM 调用、检索、工具调用全部重来一遍，token 翻倍
2. **状态不一致**：重跑时模型的输出可能不一样（尤其 temperature > 0），导致用户确认的内容和执行的内容对不上
3. **无法处理多步**：如果图已经走了 5 步，你怎么让重跑时跳过前 4 步？只能在 state 里塞一堆"已执行标记"，极其丑陋

### 方案 C：把确认做成"工具"

```python
@tool
def ask_user_confirmation(question: str) -> str:
    """向用户提问并等待回答。"""
    return input(question)     # ❌ 阻塞整个事件循环
```

**为什么不行**：

- `input()` 是**同步阻塞**的，在 async 环境里会卡死整个事件循环（第 3 章讲过）
- 即使改成 async，用户也不在终端前——他在浏览器里，你的服务进程根本联系不上他
- 请求早就 HTTP 响应结束了，进程里的函数调用栈已经销毁

**本质问题**：**进程的生命周期和用户的交互生命周期不匹配**。HTTP 请求是秒级的，用户思考是分钟级的。你不可能让一个 HTTP 请求挂在那里等 5 分钟。

### 正确方案的本质：把"等待"外化成"状态机"

LangGraph 的解法是把问题重构了：

> **不要让进程等待，让进程保存状态并退出；用户决策后，用新的请求加载状态并继续。**

```
请求 1: 执行到 interrupt → 保存 state → HTTP 响应（带 approval_required）
        ↓ （进程结束，用户看弹窗，思考 30 秒）
请求 2: 加载 state → 从 interrupt 继续 → 执行 → HTTP 响应（结果）
```

这样：
- ✅ 进程不需要等待，HTTP 请求正常结束
- ✅ 状态完整保存，不会重复执行
- ✅ 用户想等多久等多久

**这就是"持久化（第 17 章）是 HITL 的物理基础"的含义。**

---

## 18.3 `interrupt()` 是怎么实现的

### 18.3.1 表面用法

`agent_service.py:272-287`：

```python
async def approval_node(state: AgentState) -> dict:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    write_calls = [tc for tc in tool_calls if tc.get("name") in WRITE_TOOLS]
    if not write_calls:
        return {"approval": None}

    payload = {"tool": write_calls[0].get("name"), "args": write_calls[0].get("args") or {}}
    decision = interrupt(payload)          # ★ 冻结
    if not isinstance(decision, dict):
        decision = {"approved": bool(decision)}
    return {"approval": decision}          # ★ 解冻后从这里继续
```

### 18.3.2 底层机制：异常 + 状态保存 + 重放

`interrupt()` 的实现原理（简化版）可以理解为：

```python
def interrupt(value):
    # 1. 把 payload 挂到一个特殊的地方
    # 2. 抛出 GraphInterrupt 异常
    raise GraphInterrupt(value)
```

然后 LangGraph 的执行器捕获它：

```python
try:
    result = node_func(state)          # 执行 approval_node
except GraphInterrupt as gi:
    # 保存当前 state（连同"我在哪个节点、第几次调用"的信息）
    checkpointer.put(config, checkpoint, metadata, new_versions)
    # 把中断信息放进 result
    return {"__interrupt__": [Interrupt(value=gi.value, ...)]}
```

**恢复时**：

```python
# 用户调用 ainvoke(Command(resume={"approved": True}), config)
# 1. 从 checkpointer 加载 state
# 2. 找到"上次在哪个节点被中断"（通过 checkpoint 的元数据）
# 3. 重新执行那个节点
# 4. 这次 interrupt() 不再抛异常，而是直接返回 resume 的值
# 5. 节点正常返回，图继续往下走
```

关键点：**第 4 步怎么实现的？**

LangGraph 在重新执行节点时，会在上下文里标记"这次是 resume 模式，且有一个待消费的 resume 值"。`interrupt()` 检测到这个标记，就**直接返回那个值**而不是抛异常。

如果同一个节点里有多个 `interrupt()`，它们会按**调用顺序**依次消费 resume 值（LangGraph 内部维护一个索引）。这就是"静态中断"（static interrupt）的行为约定：

> ⚠️ **坑 1（真实且致命）**：**resume 后，节点是从头重新执行的，不是从 `interrupt()` 那一行继续。**
> 这意味着 `interrupt()` **之前**的代码会被**再跑一遍**。

看个例子：

```python
async def approval_node(state):
    print("A")                     # ← resume 时会再打印一次
    payload = build_payload(state) # ← resume 时会再算一次
    decision = interrupt(payload)  # ← 第一次抛异常，第二次返回值
    print("B")
    return {"approval": decision}
```

执行日志：
```
第一次: A → (interrupt, 抛异常)
第二次: A → (返回值) → B       # A 被执行了两次！
```

**为什么这样设计？** 因为 Python 没有原生的协程序列化能力，无法把"函数执行到某一行"这个状态存下来。所以 LangGraph 选择了**重放（replay）**：从头执行节点，但在 `interrupt()` 处返回缓存的值。

**这个特性带来两条铁律**：

1. **`interrupt()` 之前的代码必须是幂等的**（不能有副作用：不能发短信、不能扣款、不能写库）
2. **`interrupt()` 之前的代码不要太重**（会被执行两次，浪费时间）

本项目的 `approval_node` 完全符合：前面只是读 state、筛列表、构造 dict，全是纯操作。✅

> **面试高分点**：能说出"interrupt 是通过异常 + 状态保存 + 节点重放实现的，所以 interrupt 之前的代码必须幂等"——这一句话就能证明你真的读过源码，而不是只会调 API。

### 18.3.3 为什么必须在"节点内"调用

`interrupt()` 只能在 LangGraph 的节点函数里调用。如果你在节点的子函数里调用：

```python
async def approval_node(state):
    decision = await ask_user(state)    # ask_user 内部调 interrupt
    return {"approval": decision}

async def ask_user(state):
    return interrupt({"tool": "..."})   # ❌ 不推荐
```

技术上能工作（因为异常会向上传播），但**强烈不推荐**，原因：

1. **可读性差**：读代码的人看不出这里会中断
2. **重放语义变复杂**：如果 `ask_user` 里有多个分支，重放时的行为难以预测
3. **调试困难**：堆栈里看不到节点边界

**最佳实践**：`interrupt()` 直接写在节点函数体里，且一个节点最好只有一个（或者至少顺序固定）。

### 18.3.4 `Command(resume=...)`：恢复的钥匙

`agent_service.py:400-402`：

```python
result = await agent.ainvoke(
    Command(resume={"approved": approved}), _make_config(thread_id)
)
```

`Command` 是 LangGraph 提供的特殊输入类型，除了 `resume` 还支持：

```python
Command(resume=...)        # 恢复中断，并把值传给 interrupt()
Command(update={...})      # 更新 state 后继续
Command(goto="node_name")  # 跳转到指定节点（跳过常规路由）
```

**三者可以组合**：

```python
# 用户不仅批准，还修改了参数
Command(
    resume={"approved": True},
    update={"messages": [HumanMessage("改成 16:00-18:00")]},
)
```

> 📝 **这是一个很实用的产品能力**：让用户在确认框里**修改参数**（比如改时段），而不只是"批准/拒绝"。本项目目前只做了批准/拒绝，但 `Command` 已经支持参数修改，扩展成本很低。

---

## 18.4 完整链路：从 interrupt 到前端弹窗

现在把整条链路串起来。这是一道经典的"讲讲你们的人工审批怎么实现的"面试题。

```
① 用户："帮我预约明天下午的显微镜实验室"
        │
        ▼
② POST /ai/chat/stream  { messages: [...], thread_id: "abc-123" }
        │
        ▼
③ agent_service.stream_agent → _stream_events
        │
        ▼
④ 图执行：agent 节点 → 模型返回 tool_calls=[create_lab_reservation]
        │
        ▼
⑤ 路由 → approval 节点 → 命中 WRITE_TOOLS → interrupt(payload)
        │
        ├─ 抛 GraphInterrupt → 保存 state → ainvoke 返回
        ├─ astream_events 产出 on_chain_stream 事件，data.chunk.__interrupt__
        ▼
⑥ _stream_events 检测到中断（`agent_service.py:449-459`）
        yield {"type": "approval_required", "thread_id": ..., "payload": {...}}
        return
        │
        ▼
⑦ SSE 帧：data: {"type":"approval_required","payload":{"tool":"create_lab_reservation","args":{...}}}
        │
        ▼
⑧ 前端 AIChat.vue 收到事件 → 渲染确认卡片（显示实验室、日期、时段）
        │
        ▼
⑨ 用户点"确认"
        │
        ▼
⑩ POST /ai/chat/stream/resume  { thread_id: "abc-123", approved: true }
        │
        ▼
⑪ resume_stream_agent → agent.ainvoke(Command(resume={"approved": true}), config)
        │
        ▼
⑫ 加载 checkpoint → 重放 approval_node → interrupt 返回 {"approved": true}
        │
        ▼
⑬ tool_node 执行 create_lab_reservation → 真实落库
        │
        ▼
⑭ 回到 agent 节点 → 模型生成"预约已提交" → SSE token 流 → 前端打字机
```

### 18.4.1 关键代码：流式下的中断检测

`agent_service.py:449-459`：

```python
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
```

**为什么流式模式下的中断检测和非流式不一样？**

- 非流式：`ainvoke` 返回的 result 里有 `__interrupt__`
- 流式：`astream_events` 产出的是事件流，中断表现为一个 `on_chain_stream` 事件，`name == "LangGraph"`，payload 藏在 `data.chunk.__interrupt__` 里

这个差异是 LangGraph 版本的坑。注释里写了"LangGraph 1.2 以 on_chain_stream 携带"——**说明这个行为在不同版本间变过**。

> ⚠️ **坑 2（真实）**：LangGraph 版本升级时，中断事件的表现形式会变。这是我们要**锁定版本**的又一个理由。升级 LangGraph 后，务必回归测试审批流程。

### 18.4.2 `_interrupt_payload`：防御式取值

`agent_service.py:336-342`：

```python
def _interrupt_payload(interrupts: list) -> dict:
    """从 state 里的 __interrupt__ 列表取第一个中断的负载。"""
    if not interrupts:
        return {}
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}
```

三层防御：

1. `__interrupt__` 可能为空 → 返回 `{}`
2. 元素可能是对象也可能是裸值 → `getattr(first, "value", first)`
3. 值可能不是 dict → 包成 `{"value": ...}`

**为什么要这么小心？** 因为 `Interrupt` 对象的形态在不同 LangGraph 版本里不一致（有时是 `Interrupt` dataclass，有时是 dict）。防御式取值让代码对版本变化更健壮。

### 18.4.3 服务层到 API 层的信号转换

`agent_service.py:384-386`：

```python
interrupts = result.get("__interrupt__")
if interrupts:
    raise ApprovalRequired(thread_id=thread_id, payload=_interrupt_payload(interrupts))
```

`ApprovalRequired` 是自定义异常（`agent_service.py:56-62`）：

```python
class ApprovalRequired(Exception):
    """写库类工具需要用户确认时抛给 API 层的信号。"""

    def __init__(self, thread_id: str, payload: dict):
        self.thread_id = thread_id
        self.payload = payload
        super().__init__("需要用户确认后再执行")
```

**为什么用异常而不是返回值？**

因为 `run_agent` 的返回类型是 `str`（AI 的回复文本）。要额外携带"需要审批"这个信号 + payload，两个选择：

| 方案 | 优点 | 缺点 |
|---|---|---|
| 返回 `tuple[str, dict\|None]` 或 dataclass | 类型明确 | 所有调用点都要解包，签名变复杂 |
| **抛异常** | 签名不变，正常路径干净 | 异常不应作控制流（有争议） |

选异常的实用性理由：**"需要审批"是一个打断正常流程的事件**，语义上就是"异常"。而且 FastAPI 里可以用 `try/except` 干净地转成不同的响应结构。

API 层（`api/ai.py:35-42`）：

```python
except agent_service.ApprovalRequired as exc:
    return Response.success(
        data={
            "type": "approval_required",
            "thread_id": exc.thread_id,
            "payload": exc.payload,
        }
    )
```

**注意这里返回的是 HTTP 200**，不是 4xx。因为对前端来说这不是错误，是一个正常的状态："需要你确认"。用 `type` 字段区分响应类型，而不是用 HTTP 状态码。这是一个合理的设计选择。

### 18.4.4 前端的确认与恢复

`AIChat.vue:173-175`：

```javascript
await resumeStream(evt.thread_id, true, assistant)   // 确认
await resumeStream(evt.thread_id, false, assistant)  // 拒绝
```

两个按钮，传 `approved` 布尔值。

**拒绝时会发生什么？** `tool_node` 里：

```python
if name in WRITE_TOOLS and (not approval or not approval.get("approved")):
    content = "用户取消了本次操作，未执行。"
```

返回这条 ToolMessage，模型收到后会告诉用户"已取消"。**用户能取消，这才是真正的"人在环路"**——而不是只能点"确定"的假弹窗。

---

## 18.5 最小骨架：亲手跑通 interrupt 全流程

第 16 章的 `minimal_guard.py` 已经演示过 interrupt。这里再给一个**更聚焦**的例子，专门验证"重放语义"和"幂等性"。

```python
"""
minimal_hitl.py —— 验证 interrupt 的重放语义与幂等要求
运行：pip install langgraph langchain-core aiosqlite && python minimal_hitl.py
"""
import asyncio
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    approval: dict | None


# 用全局计数器观察"重放"发生了几次
side_effect_counter = {"n": 0}


async def approval_node(state: State) -> dict:
    """演示：interrupt 之前的代码会被执行两次。"""
    # ❌ 危险区：这里如果有副作用（发短信/扣款/写库），会被执行两次！
    side_effect_counter["n"] += 1
    print(f"  [approval] ★ 进入节点第 {side_effect_counter['n']} 次（含重放）")

    # ✅ 安全区：纯计算，重复执行无害
    last = state["messages"][-1]
    calls = getattr(last, "tool_calls", None) or []
    payload = {"tool": calls[0]["name"], "args": calls[0]["args"]} if calls else {}

    print(f"  [approval] ⏸ 调用 interrupt，payload={payload}")
    decision = interrupt(payload)          # 第一次：抛异常；第二次：返回值
    print(f"  [approval] ▶ interrupt 返回：{decision}")

    return {"approval": decision}


async def after_node(state: State) -> dict:
    approval = state.get("approval") or {}
    result = "✅ 已执行预约" if approval.get("approved") else "❌ 用户取消，未执行"
    return {"messages": [AIMessage(content=result)]}


def build(cp):
    g = StateGraph(State)
    g.add_node("approval", approval_node)
    g.add_node("after", after_node)
    g.add_edge(START, "approval")
    g.add_edge("approval", "after")
    g.add_edge("after", END)
    return g.compile(checkpointer=cp)


async def main():
    async with AsyncSqliteSaver.from_conn_string("./_hitl_demo.sqlite") as cp:
        await cp.setup()
        graph = build(cp)
        cfg = {"configurable": {"thread_id": "hitl-demo"}}

        print("=== 步骤 1：首次调用（应触发 interrupt）===")
        r = await graph.ainvoke(
            {"messages": [AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "create_reservation",
                             "args": {"lab": "301", "time": "14:00"}}],
            )]},
            cfg,
        )
        print(f"  __interrupt__ = {r.get('__interrupt__')}")
        print(f"  approval 节点已执行 {side_effect_counter['n']} 次")

        print("\n=== 步骤 2：用户批准，resume ===")
        r = await graph.ainvoke(Command(resume={"approved": True}), cfg)
        print(f"  最终结果：{r['messages'][-1].content}")
        print(f"  approval 节点共执行 {side_effect_counter['n']} 次  ← 注意：重放导致 +1")

        # 验证：拒绝路径
        print("\n=== 步骤 3：新线程，用户拒绝 ===")
        r = await graph.ainvoke(
            {"messages": [AIMessage(
                content="",
                tool_calls=[{"id": "c2", "name": "create_reservation",
                             "args": {"lab": "302", "time": "15:00"}}],
            )]},
            {"configurable": {"thread_id": "hitl-deny"}},
        )
        print(f"  收到中断：{r.get('__interrupt__') is not None}")
        r = await graph.ainvoke(
            Command(resume={"approved": False}),
            {"configurable": {"thread_id": "hitl-deny"}},
        )
        print(f"  最终结果：{r['messages'][-1].content}")

        # 验证：Command 还能改参数
        print("\n=== 步骤 4：批准的同时修改参数 ===")
        r = await graph.ainvoke(
            {"messages": [AIMessage(
                content="",
                tool_calls=[{"id": "c3", "name": "create_reservation",
                             "args": {"lab": "303", "time": "16:00"}}],
            )]},
            {"configurable": {"thread_id": "hitl-modify"}},
        )
        r = await graph.ainvoke(
            Command(
                resume={"approved": True},
                update={"messages": [HumanMessage("用户改成了 18:00-20:00")]},
            ),
            {"configurable": {"thread_id": "hitl-modify"}},
        )
        print(f"  最终消息数：{len(r['messages'])}")
        for m in r["messages"]:
            print(f"    {type(m).__name__}: {m.content or '<tool_calls>'}")


if __name__ == "__main__":
    asyncio.run(main())
```

**预期输出（关键行）**：

```
=== 步骤 1：首次调用（应触发 interrupt）===
  [approval] ★ 进入节点第 1 次（含重放）
  [approval] ⏸ 调用 interrupt，payload={'tool': 'create_reservation', 'args': {...}}
  __interrupt__ = [Interrupt(value={...})]
  approval 节点已执行 1 次

=== 步骤 2：用户批准，resume ===
  [approval] ★ 进入节点第 2 次（含重放）        ← ★ 重放！
  [approval] ⏸ 调用 interrupt，payload={'tool': 'create_reservation', 'args': {...}}
  [approval] ▶ interrupt 返回：{'approved': True}
  最终结果：✅ 已执行预约
  approval 节点共执行 2 次  ← 注意：重放导致 +1
```

**结论被验证**：`approval_node` 的函数体**被执行了两次**。第二次时 `interrupt()` 直接返回值，不再抛异常。

---

## 18.6 设计权衡：什么时候该拦，什么时候不该拦

不是所有操作都需要人工确认。拦得太多，用户体验极差（"这个 Agent 什么都要问我"）；拦得太少，出事。

### 18.6.1 判断标准

| 维度 | 需要拦截 | 不需要拦截 |
|---|---|---|
| **可逆性** | 不可逆（删数据、发通知、付款） | 可逆（查询、检索） |
| **副作用范围** | 影响他人/外部系统 | 只影响当前会话 |
| **成本** | 花钱（API、短信） | 免费 |
| **出错代价** | 高（数据损坏、投诉） | 低（答错了重新问） |
| **频率** | 低频 | 高频 |

本项目的选择（`agent_service.py:100`）：

```python
WRITE_TOOLS = {"create_lab_reservation"}
```

只拦写库工具。检索、查询、日期换算全部放行。

### 18.6.2 一个有意思的细节：预约本身是"待审核"状态

看工具定义（`agent_tools.py:164-176`）：

```python
reservation_service.create_reservation(db, current_user, data)
return json.dumps({
    "ok": True,
    "message": "预约已提交，请等待管理员审核",
    ...
})
```

**预约创建后是"待审核"状态，还需要管理员确认。** 也就是说本项目实际是**双层审批**：

1. **用户层**：`interrupt` 拦截，用户点确认才落库
2. **管理员层**：落库后状态是 `pending`，管理员在后台审核才生效

这大大降低了第一层的风险——即便用户误点了确认，管理员还能拦住。

**面试可以这样讲**："我们的预约是双层的：Agent 落库前有一次用户确认（技术层面的 interrupt），落库后还有管理员审核（业务层面的审批流）。这样即便 interrupt 被误放行，业务层还有一道闸门。"

### 18.6.3 System Prompt 里的配合

`agent_service.py` 的 SYSTEM_PROMPT：

```
提交预约前必须向用户复述：实验室ID与名称（或设备ID和名称）、日期、开始时间、结束时间，
并得到用户确认后再调用 create_lab_reservation。系统会在真正落库前再次弹出确认，
这是最后一道保护，用户没有明确确认时不要硬调工具。
```

这里做了两件事：

1. **要求模型先"复述"**：这是**软确认**（模型层面）——用户在看到复述后可以纠正。
2. **告知模型有硬确认**：减少模型因为"怕出错"而反复调用的行为。

**软确认 + 硬确认的组合**是很好的实践：软确认让用户有机会在对话中纠正（"不是 301，是 302"），硬确认保证不会有意外落库。

---

## 18.7 测试：怎么给 interrupt 写确定性测试

这是本项目做得很好的一点。看 `tests/test_agent_service.py:67-127`：

```python
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
                    tool_calls=[{
                        "name": "create_lab_reservation",
                        "args": {"lab_id": 1, "date": "2026-10-17",
                                 "start_time": "14:00", "end_time": "15:00"},
                        "id": "c1",
                    }],
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
    monkeypatch.setattr(agent_service.settings, "CHECKPOINT_DB_PATH", str(tmp_path / "ckpt.db"))
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
```

**五个值得学习的测试技巧**：

1. **假 LLM 替代真实模型**：用 `monkeypatch` 替换 `ChatOpenAI`，返回**确定性的** `AIMessage`。这样测试不依赖网络、不烧钱、可重复。
2. **用 `calls["n"]` 模拟"第一轮调工具、第二轮给答案"**：让假 LLM 有状态，能模拟多轮行为。
3. **`tmp_path` 隔离 checkpointer**：每个测试用自己的临时目录，不污染真实数据。
4. **重置全局单例**：`agent_service._checkpointer = None` —— 因为 checkpointer 是全局的，测试之间要重置，否则会串味。
5. **验证闭环**：不只测"触发了 interrupt"，还测"resume 后得到了正确结果"。

> **面试加分词**："我们给 Agent 的审批闭环、多轮历史不重复这些关键行为补了确定性集成测试——用假 LLM 替换真实模型，这样测试不依赖网络、不烧钱、可重复。这是 Agent 测试的核心方法论：把不确定性隔离在边界上。"

另一个测试 `test_multiturn_does_not_duplicate_history`（`:130-171`）验证的是："前端只发新消息时，模型收到的历史不能重复"——这正是防止 checkpointer 和前端传参重复的关键回归测试。

---

## 18.8 项目代码定位汇总

| 功能 | 位置 | 说明 |
|---|---|---|
| 写库白名单 | `agent_service.py:100` | `WRITE_TOOLS = {"create_lab_reservation"}` |
| 审批节点 | `agent_service.py:272-287` | 筛选 → `interrupt()` → 归一化 |
| 中断信号异常 | `agent_service.py:56-62` | `ApprovalRequired` |
| payload 提取 | `agent_service.py:336-342` | 三层防御式取值 |
| 非流式中断检测 | `agent_service.py:384-386` | 读 `result["__interrupt__"]` |
| 流式中断检测 | `agent_service.py:449-459` | `on_chain_stream` + `__interrupt__` |
| 恢复执行 | `agent_service.py:390-411` | `Command(resume=...)` |
| API 层转换 | `api/ai.py:35-42` | 转 `approval_required` 响应 |
| 恢复接口 | `api/ai.py:50-74` | `/ai/chat/resume` |
| 流式恢复 | `api/ai.py:108-133` | `/ai/chat/stream/resume` |
| 前端确认 | `AIChat.vue:173-175` | `resumeStream(thread_id, approved)` |
| 工具返回 | `agent_tools.py:164-176` | "预约已提交，请等待管理员审核" |
| 集成测试 | `tests/test_agent_service.py:67-127` | 假 LLM 验证闭环 |

---

## 18.9 面试问答

### Q1：什么是 Human-in-the-Loop？你的项目怎么实现的？

**答**：HITL 是指在 Agent 的关键决策点插入人工确认，防止不可逆的错误操作。

我们的实现是：在 `agent` 和 `tools` 节点之间插了一个 `approval` 节点。它检查模型这次要调的工具里有没有写库工具（白名单 `WRITE_TOOLS = {"create_lab_reservation"}`），有的话调用 `interrupt(payload)` 把整个图的执行冻结。LangGraph 会把当前 state 存进 checkpointer，然后 `ainvoke` 返回，result 里带 `__interrupt__` 字段。服务层把它转成 `ApprovalRequired` 异常抛给 API 层，API 层返回 `type: approval_required` 的响应，前端渲染确认卡片。用户点确认后调 `/ai/chat/stream/resume`，后端用 `Command(resume={"approved": true})` 恢复执行。

### Q2：`interrupt()` 的原理是什么？

**答**：它是"异常 + 状态保存 + 节点重放"三步实现的。

`interrupt()` 内部抛出一个 `GraphInterrupt` 异常，LangGraph 的执行器捕获它，把当前 state 写入 checkpointer，然后正常返回，result 里带 `__interrupt__`。

恢复时用 `Command(resume=...)` 调用，框架加载 checkpoint，**重新执行**被中断的那个节点——这次 `interrupt()` 检测到 resume 标记，直接返回值而不抛异常，节点继续往下走。

**这里有个关键的坑**：因为是"重放"而不是"从断点继续"，`interrupt()` 之前的代码会被**执行两次**。所以那些代码必须幂等——不能有发短信、扣款、写库这类副作用。我们的 `approval_node` 里前面只有读 state 和构造 dict，是纯操作。

### Q3：为什么不用 `input()` 或者在函数里等待？

**答**：因为**进程生命周期和用户交互生命周期不匹配**。HTTP 请求是秒级的，用户思考是分钟级的。你不可能让一个请求挂在那里等 5 分钟——不仅占用连接，还可能超时。

而且 async 环境里 `input()` 是同步阻塞的，会卡死整个事件循环。

正确做法是**把等待外化成状态机**：进程保存状态并退出，用户决策后用新的请求加载状态继续。这正是 checkpointer + interrupt 的组合。

### Q4：用户拒绝了会怎么样？

**答**：`tool_node` 里检查 `approval.get("approved")`，未通过就返回一条 ToolMessage："用户取消了本次操作，未执行。"

**这个措辞是故意的**——不带"失败"、"请重试"这类暗示，避免模型以为要重试然后再次触发审批，导致用户被反复弹窗。模型收到后会如实告诉用户"已取消"。

### Q5：你怎么测试审批流程？

**答**：用假 LLM 替换真实的 `ChatOpenAI`。具体来说用 `monkeypatch` 把 `ChatOpenAI` 换成一个 FakeLLM，它的 `bind_tools` 返回一个 FakeBound，`ainvoke` 用一个计数器控制行为：第一次返回带 `create_lab_reservation` 的 tool_calls，第二次返回"预约已提交"文本。

然后测试完整闭环：`ainvoke` 第一次应该拿到 `__interrupt__`，且 payload 里的 tool 名正确；再用 `Command(resume={"approved": True})` 恢复，应该得到"预约已提交"。

配套的三个要点：用 `tmp_path` 隔离 checkpointer 数据；重置全局的 `_checkpointer` 单例（否则测试间会串味）；验证闭环而不只是验证触发。

这是 Agent 测试的核心方法论：**把不确定性隔离在边界上**——假 LLM 是确定的，剩下的图逻辑就可以确定性测试。

### Q6：除了预约，还有哪些场景需要 HITL？

**答**：按四个维度判断：不可逆（删数据、付款、发通知）、影响外部系统或他人、有金钱成本、出错代价高。

在本项目里，如果后续要加这些工具，都应该进 `WRITE_TOOLS`：删除预约、取消他人预约、发送通知给实验室管理员、批量导入数据。

反过来，检索、查询、日期换算这些只读操作不应该拦，否则用户体验会很差——每问一句都要点确认。

另外我们还有一层业务审批：预约创建后是"待审核"状态，需要管理员在后台确认才生效。所以即便 interrupt 被误放行，业务层还有一道闸门。

### Q7：`Command` 除了 resume 还能做什么？

**答**：还支持 `update`（更新 state）和 `goto`（跳转到指定节点），三者可组合。

比如用户不仅批准还想改时段：

```python
Command(
    resume={"approved": True},
    update={"messages": [HumanMessage("改成 16:00-18:00")]},
)
```

我们目前只用了 `resume`，但 `update` 的能力已经支持，扩展成"确认框里可修改参数"的成本很低。

---

## 18.10 速记卡

> **HITL = 在不可逆操作前冻结图，把控制权交回用户，决策后从冻结处继续。**

**为什么难**：进程生命周期（秒）≠ 用户思考时间（分钟），不能让请求挂起等待

**解法**：把等待外化成状态机 —— 保存 state 退出 → 用新请求加载继续

**三步原理**：
```
interrupt() → 抛 GraphInterrupt → 存 checkpoint → 返回 __interrupt__
Command(resume=v) → 加载 checkpoint → 重放节点 → interrupt 返回 v → 继续
```

**★ 铁律**：resume 是**重放节点**不是从断点继续 → `interrupt()` 前的代码会执行两次 → **必须幂等**

**Command 三能力**：`resume` / `update` / `goto`（可组合）

**拦什么**：不可逆、影响他人、有成本、出错代价高 → 白名单 `WRITE_TOOLS`

**拒绝的措辞**："用户取消了本次操作，未执行。"（不带重试暗示）

**双层审批**：interrupt 用户确认（技术）+ 落库后管理员审核（业务）

**测试方法论**：假 LLM 替换真实模型 → 把不确定性隔离在边界上

**代码位置**：
- 审批节点：`agent_service.py:272-287`
- 流式中断检测：`agent_service.py:449-459`
- 恢复：`agent_service.py:390-411`
- 测试：`tests/test_agent_service.py:67-127`

---

## 18.11 延伸思考

1. **如果用户在确认框里想改时段（而不是简单批准/拒绝），前后端要改哪些地方？**
   提示：`Command(resume=..., update={"messages": [...]})` 已经支持。前端确认卡片要加可编辑字段；后端要把修改内容作为一条 HumanMessage 注入。思考：模型看到这条消息后会怎么做？（很可能重新调用预约工具 → 触发第二次 interrupt）

2. **用户一直不点确认，30 分钟后才点。这期间 state 还在吗？会不会有问题？**
   提示：state 还在（checkpoint 不会过期）。但要注意：如果这期间数据库里的实验室被删除了，恢复执行时预约会失败——模型会看到错误并自纠，体验尚可。更严谨的做法是恢复前校验一次。

3. **同一个 thread 上，用户点了确认后网络断了，又点了一次确认，会发生什么？**
   提示：第二次 `Command(resume=...)` 时，图已经不在中断状态了。LangGraph 会怎么处理？（可能报"没有待恢复的中断"，或者把 resume 值当作新输入）这是一个需要实测的边界——**幂等的恢复接口**值得设计。

---

**下一章**：第 19 章 · 上下文工程——长对话怎么不撑爆 context window？看 token 预算与滑动窗口裁剪的实现。
