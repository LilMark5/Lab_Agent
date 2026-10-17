# 第 34 章 · 多 Agent 编排：什么时候该拆，怎么拆

> **这一章要回答的核心问题**：单 Agent 不够用吗？什么时候该拆多个？Supervisor、Swarm、Handoff 有什么区别？拆分的代价是什么？

---

## 34.1 引子：一个"什么都会但什么都不精"的 Agent

先看一个真实的退化过程。你的 Agent 一开始只有 3 个工具，表现很好。后来需求增加：

1. 知识库检索
2. 实验室查询
3. 设备查询
4. 创建预约
5. 取消预约
6. 查询我的预约
7. 管理员审核预约
8. 查询开放时间
9. 换算日期
10. 发送通知
11. 生成实验报告
12. ...

**到 15 个工具时，问题出现了**：

| 症状 | 原因 |
|---|---|
| 工具选错 | 候选太多，模型分不清 `query_my_reservation` 和 `list_open_labs` |
| 工具描述冲突 | 为了让模型区分，描述越写越长，挤占上下文 |
| 指令遵守下降 | System Prompt 越写越长，模型顾不过来 |
| 多步任务失败 | 步骤多了，规划能力跟不上 |

**这叫"工具膨胀"（Tool Proliferation）**，是单 Agent 最常见的退化路径。

**经验数字**：**单个 Agent 的工具数控制在 10 个以内**（本项目 5 个，很健康）。

---

## 34.2 什么时候该拆：四个信号

| 信号 | 说明 | 本项目 |
|---|---|---|
| **① 工具数 > 10** | 模型选择困难 | ❌ 只有 5 个，不需要拆 |
| **② 职责明显不同** | 检索 vs 写库 vs 审核 | ⚠️ 有不同职责但耦合紧 |
| **③ 需要不同的 System Prompt** | 检索要"严谨引用"，聊天要"轻松友好" | ❌ 统一 prompt 够用 |
| **④ 需要不同的模型** | 简单任务用小模型省成本 | ❌ 统一模型 |

**本项目的结论：当前不需要拆。** 这是一个重要的工程判断——**不是所有系统都要多 Agent**。

> **面试金句**（很有价值）："我们评估后没有做多 Agent 拆分，因为工具只有 5 个、职责耦合紧密（预约流程需要连续的上下文）、统一 prompt 够用。**多 Agent 是有代价的**——状态传递、调试复杂度、延迟都会增加。过早拆分是过度设计。
>
> 我的拆分标准是四个信号：工具数超过 10 个、职责明显不同且需要不同 prompt、需要不同模型、或者单 Agent 的准确率明显下降。如果后续要加'实验报告生成''设备报修'这类独立流程，我会按业务域拆成预约 Agent 和运维 Agent。"

**这个"我评估过但决定不拆"的回答，比"我用了多 Agent"更能体现工程判断力。**

---

## 34.3 三种主流编排模式

虽然本项目没拆，但你必须知道这几种模式（面试常考）。

### 34.3.1 Supervisor（主管-工人）

```
                 ┌─────────────┐
    用户请求  →   │  Supervisor │
                 │  (路由决策)  │
                 └──────┬──────┘
            ┌───────────┼───────────┐
            ▼           ▼           ▼
      ┌─────────┐ ┌─────────┐ ┌─────────┐
      │检索Agent│ │预约Agent│ │运维Agent│
      └────┬────┘ └────┬────┘ └────┬────┘
           └───────────┼───────────┘
                       ▼
                  汇总 → 用户
```

**流程**：Supervisor 分析请求，决定派给哪个工人，工人干完汇报，Supervisor 决定是否继续或结束。

**优点**：结构清晰、可控、容易加新工人
**缺点**：Supervisor 成为瓶颈（每次决策一次 LLM 调用）、工人之间不能直接通信

**LangGraph 实现**：

```python
def supervisor(state) -> str:
    response = llm.invoke(f"路由这个请求到哪个 agent？选项：{agents}\n{state['messages'][-1]}")
    return response.content    # "retrieval" / "booking" / "FINISH"

graph.add_conditional_edges("supervisor", supervisor, {
    "retrieval": "retrieval_agent",
    "booking": "booking_agent",
    "FINISH": END,
})
```

### 34.3.2 Swarm（群体 / Handoff）

```
   Agent A ←────→ Agent B ←────→ Agent C
      │              │              │
      └────────── 任意传递 ──────────┘
```

**核心**：**没有中心协调者**，Agent 之间直接交接（handoff）。每个 Agent 可以决定"这个问题我不该管，转给 X"。

**优点**：灵活、无单点瓶颈
**缺点**：**难以预测控制流**（可能出现 A→B→A→B 循环）、调试困难

**LangGraph 实现**（用 `Command(goto=...)`）：

```python
def booking_agent(state) -> Command:
    # 如果发现这是报修问题，直接转给运维 Agent
    if is_repair_request(state):
        return Command(goto="ops_agent", update={"messages": [...]})
    ...
```

**注意**：第 18 章讲过 `Command` 支持 `goto`，正是为这个场景准备的。

### 34.3.3 流水线（Pipeline / Sequential）

```
Agent A → Agent B → Agent C → 输出
（检索）   （分析）   （生成）
```

**优点**：确定性强、易调试
**缺点**：不灵活（无法根据中间结果跳步）

**适合**：步骤固定的任务（比如"检索 → 提取要点 → 生成报告"）

### 34.3.4 对比

| 模式 | 控制流 | 优点 | 缺点 | 适用 |
|---|---|---|---|---|
| **Supervisor** | 中心化 | 清晰、可控、易扩展 | 瓶颈、工人不互通 | 领域明确、任务可分类 |
| **Swarm** | 去中心 | 灵活、无瓶颈 | **难预测、难调试** | 开放域、需要协作 |
| **Pipeline** | 线性 | 确定、易调试 | 不灵活 | 步骤固定 |

**主流建议**：**优先 Supervisor**，因为可控性最重要。Swarm 只在确实需要时（研究性质、开放对话）用。

---

## 34.4 多 Agent 的代价（重要）

**这一节是本章最有价值的部分** —— 大多数人只讲多 Agent 的好处，而你能讲代价，就体现深度。

### 代价 1：延迟累加

每个 Agent 都是一次（或多次）LLM 调用：

```
单 Agent:  用户 → LLM → 工具 → LLM → 回答          (2 次 LLM)
Supervisor: 用户 → Supervisor → 工人A → 回 Supervisor → 回答  (3+ 次 LLM)
```

**每多一层，多一次完整的 LLM 往返**（几百毫秒到几秒）。

### 代价 2：状态传递复杂

工人 A 的发现怎么传给工人 B？三种方式：

| 方式 | 做法 | 问题 |
|---|---|---|
| **共享 State** | 所有 Agent 读写同一个 state | 简单，但**上下文越来越长** |
| **消息传递** | A 把结论作为消息发给 B | 信息损失（A 的推理过程丢了） |
| **各自独立 State** | 每个 Agent 有自己的 state | 最干净，但需要显式传递 |

**这是多 Agent 最核心的难点**：**上下文在传递中会损失**。

### 代价 3：调试困难

单 Agent 出问题时，看一条消息链就懂。多 Agent 出问题时：

- 是 Supervisor 路由错了？
- 是工人 A 理解错了？
- 是工人 A 传给 B 的信息丢了？
- 是 B 执行错了？

**需要完整的 tracing**（第 40 章的可观测性）。

### 代价 4：成本

更多 LLM 调用 = 更多 token。多 Agent 系统的成本通常是单 Agent 的 **2-5 倍**。

### 代价 5：一致性

多个 Agent 用相同或不同的 prompt，可能对同一事实给出不同答案。**需要额外的"一致性检查"。**

> **面试金句**："多 Agent 的代价有五个：延迟累加（每多一层多一次 LLM 往返）、**状态传递中的上下文损失**（这是最核心的难点）、调试困难（要完整 tracing 才能定位）、成本翻倍（2-5 倍）、以及多 Agent 之间的一致性。
>
> 所以我的判断是：**能用单 Agent 解决就不要拆**。拆分的前提是单 Agent 已经明显力不从心（工具超过 10 个、准确率下降），而不是为了架构好看。"

---

## 34.5 本项目的"准多 Agent"设计

虽然没有拆成多个 Agent，但本项目有一些**为多 Agent 预留的设计**：

### 34.5.1 AgentState 留了扩展位

`agent_service.py:45-53`：

```python
class AgentState(TypedDict, total=False):
    """Agent 的共享状态。

    - messages：对话消息，add_messages 保证同名 key 是追加而不是覆盖。
    - approval：最近一次人工审批的决策，approval 节点写入、tools 节点读取。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    approval: dict | None
```

文档注释第一行写着（`:4`）：**"自定义 AgentState：messages + approval，为后续多智能体扩展留好位置。"**

**怎么扩展？** 比如拆成两个 Agent 后，需要记录"当前由哪个 Agent 处理"：

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    approval: dict | None
    current_agent: str | None        # ★ 新增：Supervisor 写入，工人读取
    handoff_reason: str | None       # ★ 新增：交接原因（便于调试）
```

### 34.5.2 工具按业务域分组

当前的 5 个工具其实可以分成两组：

| 组 | 工具 | 性质 |
|---|---|---|
| **知识/查询** | `search_lab_docs`、`list_open_labs`、`list_lab_equipments`、`get_today` | 读 |
| **预约** | `create_lab_reservation` | 写 |

**这正好是 Supervisor 拆分的天然边界**。如果将来要拆，就是这个分法。

### 34.5.3 MCP 就是"外部 Agent/服务"

第 30 章的 MCP 可以理解为一种**跨进程的多 Agent 协作**：MCP Server 提供能力，主 Agent 调用它。

**它比多 Agent 更松耦合**（不需要共享 state，通过协议通信）。

---

## 34.6 最小骨架：一个最小的 Supervisor

```python
"""
minimal_supervisor.py —— 最小 Supervisor 多 Agent 编排
运行：pip install langgraph langchain-core && python minimal_supervisor.py
用规则模拟 LLM 路由，重点理解：路由决策、工人返回、循环终止
"""
import asyncio
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    next_agent: str | None


# ── 工人 Agent（用规则模拟，真实场景是各自的 LLM + 工具）────
async def retrieval_agent(state: State) -> dict:
    """检索 Agent：回答知识类问题。"""
    q = state["messages"][0].content
    return {"messages": [AIMessage(content=f"[检索Agent] 关于「{q}」：开放时间 8:00-22:00")]}


async def booking_agent(state: State) -> dict:
    """预约 Agent：处理预约类请求。"""
    return {"messages": [AIMessage(content="[预约Agent] 已提交预约，等待管理员审核")]}


async def ops_agent(state: State) -> dict:
    """运维 Agent：处理报修类请求。"""
    return {"messages": [AIMessage(content="[运维Agent] 已登记报修工单")]}


AGENTS = {"retrieval": retrieval_agent, "booking": booking_agent, "ops": ops_agent}


# ── Supervisor：路由决策 ────────────────────────────────────
async def supervisor(state: State) -> dict:
    """模拟 LLM 路由：根据关键词决定派给谁。"""
    last = state["messages"][-1].content

    # 已经由工人处理过 → 结束
    if any(f"[{name}Agent]" in m.content for m in state["messages"]
           for name in ["检索", "预约", "运维"] if isinstance(m, AIMessage)):
        return {"next_agent": "FINISH"}

    if "预约" in last or "订" in last:
        return {"next_agent": "booking"}
    if "报修" in last or "坏了" in last:
        return {"next_agent": "ops"}
    return {"next_agent": "retrieval"}


def route(state: State) -> str:
    nxt = state.get("next_agent") or "FINISH"
    return END if nxt == "FINISH" else nxt


# ── 建图 ────────────────────────────────────────────────────
def build():
    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    for name, fn in AGENTS.items():
        g.add_node(name, fn)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route,
                            {**{n: n for n in AGENTS}, "FINISH": END})
    # ★ 工人干完 → 回到 supervisor 汇报
    for name in AGENTS:
        g.add_edge(name, "supervisor")
    return g.compile()


async def main():
    graph = build()
    for q in ["实验室几点开门？", "帮我预约明天下午的显微镜实验室", "离心机坏了"]:
        print(f"\n{'='*56}\n👤 {q}")
        result = await graph.ainvoke({"messages": [HumanMessage(q)]})
        for m in result["messages"]:
            if isinstance(m, AIMessage) and m.content:
                print(f"🤖 {m.content}")


if __name__ == "__main__":
    asyncio.run(main())
```

**预期输出**：

```
👤 实验室几点开门？
🤖 [检索Agent] 关于「实验室几点开门？」：开放时间 8:00-22:00

👤 帮我预约明天下午的显微镜实验室
🤖 [预约Agent] 已提交预约，等待管理员审核

👤 离心机坏了
🤖 [运维Agent] 已登记报修工单
```

**三件事被演示**：
1. ✅ Supervisor 路由决策
2. ✅ 工人执行后回到 Supervisor
3. ✅ 终止条件（已处理过 → FINISH）

---

## 34.7 面试问答

### Q1：你们用了多 Agent 吗？为什么？

**答**：没有，我们评估后决定不拆。

理由是工具只有 5 个、职责耦合紧密（预约流程需要连续的上下文）、统一 prompt 够用。**多 Agent 是有代价的**：延迟累加、状态传递中的上下文损失、调试困难、成本翻倍。过早拆分是过度设计。

我的拆分标准是四个信号：工具数超过 10 个、职责明显不同且需要不同 prompt、需要不同模型、或者单 Agent 准确率明显下降。

**如果后续要拆**，会按业务域拆成预约 Agent 和运维 Agent——当前 5 个工具天然分成"知识/查询"和"预约/写库"两组。我们的 `AgentState` 也留了扩展位（注释里写了"为后续多智能体扩展留好位置"），加个 `current_agent` 字段就能支持 Supervisor。

### Q2：多 Agent 有哪些编排模式？

**答**：三种主流。

**Supervisor（主管-工人）**：中心化的协调者分析请求、派给工人、工人汇报、协调者决定继续或结束。优点是结构清晰可控易扩展，缺点是协调者成为瓶颈、工人之间不直接通信。**我优先推荐这个。**

**Swarm / Handoff**：没有中心，Agent 之间直接交接（LangGraph 用 `Command(goto=...)`）。优点是灵活无瓶颈，缺点是**控制流难以预测**（可能 A→B→A→B 循环）、调试困难。

**Pipeline**：线性流水线，步骤固定。优点确定性强易调试，缺点不灵活。适合"检索→提取→生成"这类固定流程。

### Q3：多 Agent 的代价是什么？

**答**：五个。

一是**延迟累加**——每多一层就多一次完整的 LLM 往返。

二是**状态传递中的上下文损失**——这是最核心的难点。工人 A 的推理过程不会自动传给 B，只传结论的话信息就丢了。三种传递方式（共享 State、消息传递、独立 State）各有取舍。

三是**调试困难**——出问题时不知道是路由错了、哪个工人错了、还是传递中丢了信息，需要完整的 tracing。

四是**成本**——通常 2-5 倍。

五是**一致性**——多个 Agent 可能对同一事实给出不同答案。

**所以我的判断：能用单 Agent 解决就不要拆。**

### Q4：单 Agent 什么时候会力不从心？

**答**：四个信号，最重要的是**工具膨胀**。

经验数字是**工具数控制在 10 个以内**——超过后模型的选择准确率明显下降，表现为选错工具、多步任务失败。而且为了区分相似工具，描述越写越长，挤占上下文。

其他信号：职责明显不同且需要不同的 System Prompt（检索要严谨引用、聊天要轻松）、需要不同模型（简单任务用小模型省成本）、或者实测准确率下降。

### Q5：如果让你拆这个项目，怎么拆？

**答**：按业务域拆，因为这是最自然的边界。

当前 5 个工具分成两组：知识/查询组（`search_lab_docs`、`list_open_labs`、`list_lab_equipments`、`get_today`）和预约组（`create_lab_reservation`）。

如果后续要加"实验报告生成""设备报修""管理员审核"，我会拆成：

- **预约 Agent**：查空闲、创建/取消预约（写库，带审批）
- **知识 Agent**：RAG 检索、规则问答
- **运维 Agent**：报修、设备状态

用 Supervisor 编排，共享 `messages` 但各自有独立的 System Prompt。写库相关的仍然保留 `interrupt` 人工审批。

**状态设计上**，`AgentState` 加两个字段：`current_agent`（谁在处理）和 `handoff_reason`（为什么交接，便于调试）。

### Q6：MCP 和多 Agent 是什么关系？

**答**：可以理解为**不同粒度的能力复用**。

多 Agent 是"应用内"的拆分——多个 Agent 共享 state、在同一个进程里协作。

MCP 是"跨进程/跨应用"的能力暴露——MCP Server 提供工具，任何支持 MCP 的客户端都能调用，**不共享 state**，通过协议通信。

我们项目里 MCP 承担的是"读工具标准化"的角色，比多 Agent 更松耦合。如果要做真正的跨系统协作（比如让运维系统的 Agent 也能查实验室），MCP 比多 Agent 更合适。

---

## 34.8 速记卡

> **能用单 Agent 解决就不要拆。拆分的前提是单 Agent 明显力不从心。**

**四个拆分信号**：工具 > 10 个 / 职责不同需不同 prompt / 需不同模型 / 准确率下降

**三模式**：
- **Supervisor**（中心路由，清晰可控，**优先推荐**）
- **Swarm/Handoff**（`Command(goto=...)`，灵活但难预测）
- **Pipeline**（线性，确定但不灵活）

**五代价**：延迟累加 / **上下文损失（核心难点）** / 调试困难 / 成本 2-5 倍 / 一致性

**本项目判断**：**不拆**（5 个工具、职责耦合、统一 prompt 够用）

**预留设计**：`AgentState` 注释"为后续多智能体扩展留好位置"；工具天然分两组

**Supervisor 图结构**：
```
START → supervisor →(条件边)→ worker → supervisor →(FINISH)→ END
```

**代码位置**：
- State：`agent_service.py:45-53`
- Command goto：第 18 章 `Command` 能力

---

## 34.9 延伸思考

1. **Supervisor 和工人共享 `messages`，会不会导致上下文爆炸？**
   提示：会。每个工人的中间过程都进 messages。解法：① 工人只把**结论**写回共享 state，中间过程放独立的 state 字段；② 用第 19 章的裁剪，但要小心不要把工人间的关键交接信息裁掉；③ 用"各自独立 State + 显式传递"，最干净但最麻烦。

2. **如果 Supervisor 路由错了（把预约请求派给了检索 Agent），怎么恢复？**
   提示：工人可以返回一个"我做不了"的信号，Supervisor 重新路由。要给路由次数设上限（避免死循环）。**这是 Supervisor 相对 Swarm 的优势**：有中心协调者兜底。

3. **多 Agent 的成本是 2-5 倍，有什么办法降？**
   提示：① Supervisor 用小模型（路由是简单任务）；② 简单的工人用小模型；③ **缓存路由结果**（相似请求直接复用）；④ 用 prompt caching 复用共享前缀（第 19 章）。

---

**下一章**：第 35 章 · 记忆系统——短期记忆与长期记忆，为什么"记住用户偏好"比"记住对话"更难？
