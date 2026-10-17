# 第 14 章 · ReAct 范式：思考—行动—观察的循环

> **这一章要回答的核心问题**：模型只能"说话"，它是怎么变成能"做事"的 Agent 的？中间那套 "想一想 → 做一下 → 看看结果 → 再想想" 的循环，到底是谁在驱动？

---

## 14.1 引子：一个让所有 ChatBot 露馅的问题

先做一个思想实验。你有一个接了 DeepSeek 的聊天机器人，你问它：

> "帮我查一下明天下午 2 点显微镜实验室有没有空，有的话帮我预约两小时。"

纯 ChatBot 会怎么回答？它会非常礼貌地告诉你：

> "好的！我已经为您记录了预约需求……不过我是一个AI助手，无法直接访问您的实验室预约系统。您可以登录系统手动操作，或联系管理员。"

这段话我们称之为**"礼貌的无能"**。它暴露了 ChatBot 的三个结构性缺陷：

1. **它不能"看"**：不知道明天下午 2 点显微镜实验室到底有没有空——这是数据库里的实时数据，不在它的训练语料里。
2. **它不能"做"**：即便知道有空，它也只能在文本里"说"自己预约了，数据库里一行记录都不会多。
3. **它不会"规划"**：这个请求其实包含两个步骤（先查、后订），而且第二步依赖第一步的结果（有空才订）。它需要的是一个**条件分支**，而不是一段话。

Agent 要解决的就是这三件事。而 ReAct 范式，是目前最主流、最经得起追问的解决框架。

> **ReAct** = **Rea**soning（推理）+ **Act**ing（行动）。论文出自 2022 年 Google Research 的《ReAct: Synergizing Reasoning and Acting in Language Models》。

一句话概括 ReAct：

> **让模型在"自言自语地推理"和"调用外部工具"之间交替进行，用真实的观察结果不断修正自己的推理。**

---

## 14.2 ReAct 到底在解决什么问题

### 14.2.1 两条极端路线，都有病

在 ReAct 被提出之前，让模型完成复杂任务有两条路，但都有明显的病。

**路线 A：纯推理（Chain-of-Thought，CoT）**

就是让模型"一步步想"，也就是你熟悉的"让我们一步步思考"。

```
问题：明天下午2点显微镜实验室有空吗？有空就订2小时。
思考：我需要先查实验室的空闲情况……
思考：如果没空，就不预约……
思考：如果有空，就预约……
答案：（ hallucination 开始 ）
```

问题在于：**整条推理链都在模型脑子里完成，没有任何一步去碰真实世界**。模型不知道排班表，它就只能"编"。这就是**幻觉（hallucination）**的根源之一——不是模型故意撒谎，是它在没有任何事实约束的情况下做推理，推理链越严谨，编出来的东西越像真的。

更糟的是**错误累积**：第一步编了个"有空"，后面所有推理都建立在这个错误前提上，越推越离谱，而模型自己察觉不到。

**路线 B：纯行动（Act-only）**

反过来，干脆不让模型想，直接让它输出动作序列：

```
Action 1: query_lab_availability(lab="显微镜", date="2026-10-18", time="14:00")
Action 2: create_reservation(lab="显微镜", date="2026-10-18", start="14:00", end="16:00")
```

这条路的病是：**没有"看结果再说"的能力**。Action 1 返回"没空"，Action 2 还是照样执行了。整个流程是**盲目**的，没有任何基于观察的调整。而且一旦某步失败，整条链就崩了，没有恢复机制。

### 14.2.2 ReAct 的解法：把两者织在一起

ReAct 的核心洞察非常朴素：**推理和行动不是二选一，而是要交替**。

- 推理帮模型**决定下一步做什么**（规划）
- 行动帮模型**拿到真实信息**（接地 / grounding）
- 观察结果**修正下一步的推理**（闭环）

于是流程变成：

```
Thought 1: 我需要先查明天下午2点显微镜实验室的空闲情况
Action 1: query_lab_availability(lab="显微镜实验室", date="2026-10-18", time="14:00")
Observation 1: {"available": true, "remaining_hours": 5}

Thought 2: 有空，而且剩余5小时 > 需要的2小时，可以预约
Action 2: create_reservation(lab="显微镜实验室", date="2026-10-18", start="14:00", end="16:00")
Observation 2: {"ok": true, "reservation_id": 42}

Thought 3: 预约成功，可以回复用户了
Answer: 已为您预约显微镜实验室 10月18日 14:00-16:00，预约编号 42。
```

请注意这个模式的三个关键特征，面试时讲出来会非常加分：

| 特征 | 含义 | 为什么重要 |
|---|---|---|
| **交错（interleaved）** | 推理和行动交替出现，不是先想完再做 | 每一步行动都能被真实结果修正 |
| **接地（grounded）** | 每个结论都有 Observation 支撑 | 直接对抗幻觉 |
| **可恢复（recoverable）** | Observation 里包含错误时，下一轮 Thought 可以换策略 | 工具失败不会让整条链崩掉 |

第三点尤其重要，也最容易被忽略。ReAct 的真正威力不在于"能调工具"，而在于**工具返回错误时模型能自纠**。比如：

```
Action 1: create_reservation(lab="显微镜实验室", date="2026-10-18", start="14:00", end="16:00")
Observation 1: {"ok": false, "error": "该时段与已有预约重叠"}

Thought 2: 14:00-16:00 被占了，换 16:00-18:00 试试
Action 2: create_reservation(lab="显微镜实验室", date="2026-10-18", start="16:00", end="18:00")
Observation 2: {"ok": true, "reservation_id": 43}
```

**这不需要你写任何重试代码**——是模型读了 Observation 自己决定的。这就是 Agent 和"工作流自动化（Workflow）"的本质区别：工作流的分支是你写死的，Agent 的分支是模型现场生成的。

> ⚠️ **面试高分点**：当面试官问"Agent 和传统工作流/RPA 有什么区别"，标准答案就是这句：
> **工作流的控制流由开发者在编译期写死；Agent 的控制流由模型在运行时生成。**
> 代价是：工作流确定性强、可预测；Agent 灵活但有不确定性，所以需要 guardrail（护栏）。

---

## 14.3 最小骨架：手写一个不依赖任何框架的 ReAct 循环

现在我们来真正实现它。**不用 LangChain，不用 LangGraph**，只用 Python + 一个假的"模型"和几个假的"工具"。这样你能看清循环的本质。

这个骨架是可以**直接运行**的（不需要 API Key），我把它设计成用规则模拟模型行为，跑完你会看到完整的 Thought/Action/Observation 轨迹。

### 14.3.1 完整代码

```python
"""
minimal_react.py —— 不依赖任何框架的 ReAct 循环最小实现
运行：python minimal_react.py
无需 API Key，用规则模拟"模型"的输出。
"""
import json
import re
from dataclasses import dataclass, field


# ────────────────────────────────────────────────────────────
# 1. 工具注册表：Agent 能"做事"的全部能力
# ────────────────────────────────────────────────────────────

@dataclass
class Tool:
    """一个工具 = 名字 + 说明 + 可调用函数。"""
    name: str
    description: str
    func: callable


def query_lab_availability(lab: str, date: str, time: str) -> str:
    """查询某个实验室在某天的某个时刻是否空闲。"""
    # 真实项目里这里会查数据库；这里用硬编码模拟"已经有人订了14点"
    if time.startswith("14"):
        return json.dumps({"available": False, "reason": "该时段已被预约"}, ensure_ascii=False)
    return json.dumps({"available": True, "remaining_hours": 5}, ensure_ascii=False)


def create_reservation(lab: str, date: str, start: str, end: str) -> str:
    """创建一条预约记录。"""
    if start.startswith("14"):
        # 模拟数据库层面的时段冲突
        return json.dumps({"ok": False, "error": "时段冲突"}, ensure_ascii=False)
    return json.dumps({"ok": True, "reservation_id": 43}, ensure_ascii=False)


TOOLS: dict[str, Tool] = {
    "query_lab_availability": Tool(
        name="query_lab_availability",
        description="查询实验室空闲情况。参数: lab(名称), date(日期), time(时刻)",
        func=query_lab_availability,
    ),
    "create_reservation": Tool(
        name="create_reservation",
        description="创建预约。参数: lab(名称), date(日期), start(开始), end(结束)",
        func=create_reservation,
    ),
}


# ────────────────────────────────────────────────────────────
# 2. 假模型：用规则模拟 LLM 输出 Thought / Action
#    （真实场景这里是一次 HTTP 调用大模型）
# ────────────────────────────────────────────────────────────

def fake_llm(prompt: str) -> str:
    """根据 prompt 里的历史，决定是继续行动还是给出最终答案。"""
    # 已经创建成功 → 收尾
    if '"reservation_id"' in prompt:
        return "Thought: 预约已成功创建，可以答复用户了。\nAnswer: 已为您预约 10月18日 16:00-18:00（14点被占用，已自动顺延）。"

    # 已经查过空闲但被占 → 换时段直接尝试预约
    if '"available": false' in prompt:
        return (
            "Thought: 14:00 已被占用，改约 16:00-18:00。\n"
            "Action: create_reservation(lab=显微镜实验室, date=2026-10-18, start=16:00, end=18:00)"
        )

    # 还没查过 → 先查
    return (
        "Thought: 我需要先确认明天下午2点是否空闲，再决定是否预约。\n"
        "Action: query_lab_availability(lab=显微镜实验室, date=2026-10-18, time=14:00)"
    )


# ────────────────────────────────────────────────────────────
# 3. 解析模型输出：从文本里抠出 Action
# ────────────────────────────────────────────────────────────

ACTION_RE = re.compile(r"Action:\s*(\w+)\((.*?)\)", re.S)
ANSWER_RE = re.compile(r"Answer:\s*(.*)", re.S)


def parse_action(text: str) -> tuple[str, dict] | None:
    """把 `Action: name(a=1, b=2)` 解析成 (工具名, 参数字典)。"""
    m = ACTION_RE.search(text)
    if not m:
        return None
    name = m.group(1)
    args = {}
    for pair in m.group(2).split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            args[k.strip()] = v.strip().strip('"\'')
    return name, args


# ────────────────────────────────────────────────────────────
# 4. ReAct 主循环：Thought → Action → Observation → ...
# ────────────────────────────────────────────────────────────

@dataclass
class ReactState:
    """整个循环的状态：其实就是一串文本轨迹。"""
    question: str
    trajectory: list[str] = field(default_factory=list)

    @property
    def prompt(self) -> str:
        """把问题和历史轨迹拼成给模型的 prompt。"""
        return (
            "你是一个实验室预约助手，可用工具：\n"
            + "\n".join(f"- {t.name}: {t.description}" for t in TOOLS.values())
            + "\n\n请严格按格式输出：\n"
              "Thought: <你的推理>\nAction: <工具名>(<参数>)\n"
              "或当你有答案时：\nThought: <你的推理>\nAnswer: <最终答复>\n\n"
            + f"问题：{self.question}\n\n"
            + "\n".join(self.trajectory)
        )


def run_react(question: str, max_steps: int = 6) -> str:
    state = ReactState(question=question)

    for step in range(1, max_steps + 1):
        print(f"\n{'='*60}\n[Step {step}] 调用模型...")
        raw = fake_llm(state.prompt)
        print(raw)

        # ① 先看是不是最终答案 → 循环出口
        ans = ANSWER_RE.search(raw)
        if ans:
            print(f"\n{'='*60}\n✅ 循环结束，共 {step} 步")
            return ans.group(1).strip()

        # ② 解析 Action
        parsed = parse_action(raw)
        if not parsed:
            # 模型输出格式错了：把错误信息当作 Observation 喂回去，让它自纠
            state.trajectory.append(f"{raw}\nObservation: 格式错误，请按 `Action: 工具名(参数=值)` 输出")
            continue

        name, args = parsed
        tool = TOOLS.get(name)

        # ③ 执行工具，拿到 Observation
        if tool is None:
            obs = f"未找到工具 {name}，可用工具：{list(TOOLS)}"
        else:
            try:
                obs = tool.func(**args)
            except TypeError as e:
                # 参数不匹配也当成观察结果，让模型自己修正
                obs = f"参数错误：{e}"
        print(f"Observation: {obs}")

        # ④ 把这一轮写进轨迹，下一轮模型就能"看到"
        state.trajectory.append(f"{raw}\nObservation: {obs}")

    return "⚠️ 达到最大步数仍未得出结论"


if __name__ == "__main__":
    print(run_react("明天下午2点显微镜实验室有空吗？有空就帮我订2小时"))
```

### 14.3.2 跑起来你会看到什么

```
============================================================
[Step 1] 调用模型...
Thought: 我需要先确认明天下午2点是否空闲，再决定是否预约。
Action: query_lab_availability(lab=显微镜实验室, date=2026-10-18, time=14:00)
Observation: {"available": false, "reason": "该时段已被预约"}

============================================================
[Step 2] 调用模型...
Thought: 14:00 已被占用，改约 16:00-18:00。
Action: create_reservation(lab=显微镜实验室, date=2026-10-18, start=16:00, end=18:00)
Observation: {"ok": true, "reservation_id": 43}

============================================================
[Step 3] 调用模型...
Thought: 预约已成功创建，可以答复用户了。
Answer: 已为您预约 10月18日 16:00-18:00（14点被占用，已自动顺延）。

============================================================
✅ 循环结束，共 3 步
```

### 14.3.3 从这个骨架里，你要记住的五件事

这五件事，就是 ReAct 工程化的全部要点。后面用 LangGraph 只是把它们"框架化"了，**本质一模一样**：

1. **状态就是"轨迹"**：`trajectory` 是一个不断追加的字符串列表。真实项目里它是 `messages` 列表（LangChain 的 `BaseMessage`）。所谓"记忆"，就是这个列表。
2. **循环出口只有一个**：模型输出 `Answer`（真实项目里是"不再产生 tool_calls"）。**必须是模型决定结束，不能是你写死几步**。
3. **必须有 `max_steps` 兜底**：否则模型一旦陷入"反复失败重试"的死循环，你的 token 就烧没了。本项目里对应 `recursion_limit=10`。
4. **错误也要作为 Observation 回喂**：工具不存在、参数不对、业务失败，都不要抛异常中断循环，而是变成文本让模型看到并自纠。这是 ReAct 鲁棒性的关键。
5. **Prompt 每轮都重建**：因为轨迹在变。这也解释了为什么 ReAct 的 token 消耗是**平方级**增长的——第 N 轮要带上前 N-1 轮的全部内容。

> ⚠️ **坑 1（真实且高频）**：ReAct 的 token 消耗是 O(n²)。
> 假设每轮增量 500 token，跑 6 轮，总消耗不是 3000，而是 500+1000+1500+2000+2500+3000 = **10500**。
> 这就是为什么第 19 章"上下文工程"必须存在——长对话不裁剪，钱和 context window 一起爆。

---

## 14.4 从"文本协议"到"结构化协议"：ReAct 的工业化

### 14.4.1 文本解析为什么不可靠

上面的骨架有个致命的工程问题：**我们用正则去解析模型的自然语言输出**。

```python
ACTION_RE = re.compile(r"Action:\s*(\w+)\((.*?)\)", re.S)
```

这在真实场景会怎么死？

- 模型输出 `Action：query_lab_availability(...)`（中文冒号）→ 匹配失败
- 模型参数里带了逗号：`Action: search(query="预约, 取消")` → 参数被错误切分
- 模型自作主张加了 markdown 代码块包裹 → 正则抓不到
- 模型输出了 3 个 Action，你只解析了第 1 个

**用自然语言做协议，等于把系统的可靠性押在模型的格式稳定性上。**这在 demo 里能跑，在生产里是定时炸弹。

### 14.4.2 Function Calling：把协议结构化

工业界的解法是 **Function Calling**（第 13 章已详述）：不再让模型"输出文本让你解析"，而是让模型**直接输出结构化的 JSON**，由 API 层保证格式。

模型不再输出：

```
Action: query_lab_availability(lab=显微镜实验室, date=2026-10-18, time=14:00)
```

而是输出一个结构化的 `tool_calls` 字段：

```json
{
  "tool_calls": [{
    "id": "call_abc123",
    "name": "query_lab_availability",
    "args": {"lab": "显微镜实验室", "date": "2026-10-18", "time": "14:00"}
  }]
}
```

**于是 ReAct 的三个要素在现代 Agent 里有了新的对应关系：**

| ReAct 原始概念 | 文本协议时代 | Function Calling 时代（本项目） |
|---|---|---|
| Thought | `Thought: xxx` 文本 | 模型内部的推理 token（DeepSeek-R1 等会显式返回 `reasoning_content`） |
| Action | `Action: name(args)` 文本 | `AIMessage.tool_calls` 结构化字段 |
| Observation | `Observation: xxx` 文本 | `ToolMessage(content=...)` 消息对象 |
| 轨迹 | 拼接的字符串 | `messages` 消息列表 |
| 循环出口 | 出现 `Answer:` | `tool_calls` 为空 |

**关键认知**：Function Calling 出现后，"Thought" 这一环在很多实现里**不再显式输出**了。模型内部完成推理，直接吐出 tool_calls。所以你现在看本项目的 `agent_service.py`，**找不到任何 "Thought:" 字样**——这不是没实现 ReAct，而是 ReAct 已经"内化"了。

> ⚠️ **面试高频追问**："你的 Agent 用了 ReAct 吗？代码里怎么没看到 Thought？"
> **标准回答**：我们用的是 Function Calling 形态的 ReAct。Thought 环节由模型内部的推理过程承担（DeepSeek-R1 这类推理模型会返回 `reasoning_content` 字段可以观察到），Action 对应 `AIMessage.tool_calls`，Observation 对应 `ToolMessage`，循环由 LangGraph 的 `agent → tools → agent` 边驱动。相比文本协议版，结构化版不需要正则解析，可靠性高很多。

### 14.4.3 用 LangChain 消息重写同一个循环

如果不引入 LangGraph，只用手写循环 + Function Calling，代码长这样（这是理解本项目代码的重要跳板）：

```python
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="deepseek-chat", temperature=0).bind_tools(tools)
tools_by_name = {t.name: t for t in tools}

messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_question)]

for step in range(6):                      # ③ max_steps 兜底
    ai = await llm.ainvoke(messages)       # ① 模型决定：调工具还是回答
    messages.append(ai)

    if not ai.tool_calls:                  # ② 没有 tool_calls → 循环出口
        return ai.content

    for tc in ai.tool_calls:               # ④ 执行工具，结果作为 Observation
        tool = tools_by_name.get(tc["name"])
        if tool is None:
            obs = f"未找到工具：{tc['name']}"        # 错误也回喂，让模型自纠
        else:
            obs = await tool.ainvoke(tc["args"])
        messages.append(ToolMessage(content=obs, tool_call_id=tc["id"]))
```

**请把这段代码和你项目里的 `agent_service.py` 对照着看**——结构完全一样，只是循环的控制权从 Python 的 `for` 交给了 LangGraph 的图。

---

## 14.5 项目代码定位：ReAct 循环在本项目里的样子

现在回到真实代码。本项目的 ReAct 循环藏在 `backend/app/services/agent_service.py`，由 `build_agent` 函数构建。

### 14.5.1 全图一览（`agent_service.py:317-329`）

```python
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)      # 模型节点：产生 Thought + Action
graph.add_node("approval", approval_node)  # 审批节点：写库前拦一道（本项目特有）
graph.add_node("tools", tool_node)       # 工具节点：产生 Observation
graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent", _route_after_agent, {"approval": "approval", "end": END}
)
graph.add_edge("approval", "tools")
graph.add_edge("tools", "agent")         # ★ 回到 agent，形成循环
```

画成图：

```
         ┌──────────────────────────────────┐
         │                                  │
         ▼                                  │
    ┌─────────┐  有 tool_calls   ┌──────────┴──┐
    │  agent  │ ───────────────▶ │  approval   │
    │ (LLM)   │                  │ (interrupt) │
    └────┬────┘                  └──────┬──────┘
         │                              │
         │ 无 tool_calls                ▼
         │                        ┌───────────┐
         │                        │   tools   │
         │                        │(Observation)│
         │                        └─────┬─────┘
         ▼                              │
       END ◀────────────────────────────┘
              （tools 执行完回到 agent）
```

对照 ReAct 三要素：

| ReAct 要素 | 项目里的位置 | 代码 |
|---|---|---|
| **Thought** | `agent_node` 内部，模型隐式完成 | `agent_service.py:264-270` |
| **Action** | `agent_node` 返回的 `AIMessage.tool_calls` | 同上 |
| **Observation** | `tool_node` 返回的 `ToolMessage` | `agent_service.py:289-315` |
| **循环** | `graph.add_edge("tools", "agent")` | `agent_service.py:326` |
| **出口** | `_route_after_agent` 判断无 tool_calls → END | `agent_service.py:147-152` |
| **步数兜底** | `_make_config` 的 `recursion_limit: 10` | `agent_service.py:332-333` |

### 14.5.2 模型节点：`agent_node`（`agent_service.py:264-270`）

```python
async def agent_node(state: AgentState) -> dict:
    """agent 节点：调用大模型，返回新的 AI 消息。"""
    # system prompt 每次调用时注入，不放进 state，避免被 checkpointer 反复持久化。
    # 上下文窗口保护：送入模型前先按 token 预算裁剪历史，防止长对话撑爆 context。
    history = _trim_messages(state["messages"], settings.MAX_CONTEXT_TOKENS)
    response = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
    return {"messages": [response]}
```

三个细节值得单独讲，面试能讲到这层的人不多：

**① System Prompt 在节点内注入，不进 state**

```python
await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
```

为什么不放进 `state["messages"]`？因为 state 会被 checkpointer **每一次节点执行后就持久化一次**（第 17 章会详述）。如果把 SystemMessage 放进 state，它会被反复写入数据库，白白浪费存储和 IO，而且如果哪天你改了 prompt，历史会话里残留的旧 prompt 会造成行为不一致。**在节点里注入，prompt 永远是当前版本的那一份。**

**② 送入模型前先裁剪历史**

```python
history = _trim_messages(state["messages"], settings.MAX_CONTEXT_TOKENS)
```

这一行就是 ReAct "token 平方级增长"问题的解药。详见第 19 章。

**③ 返回的是增量，不是全量**

```python
return {"messages": [response]}
```

返回的是一个**只含新消息的列表**。LangGraph 会根据 state 的 reducer（`add_messages`）把它**追加**到已有 messages 后面，而不是覆盖。这是 LangGraph 状态管理的核心约定，第 15 章细讲。

### 14.5.3 路由函数：`_route_after_agent`（`agent_service.py:147-152`）

```python
def _route_after_agent(state: AgentState) -> str:
    """模型返回 tool_calls 则先进审批节点，否则结束本轮。"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "approval"
    return "end"
```

这就是 ReAct 的**循环出口判定**，一行代码，但它是整个 Agent 的"终止条件"。

注意这里用的是 `getattr(last, "tool_calls", None)` 而不是 `last.tool_calls`。为什么？因为 `state["messages"]` 里可能存在不是 `AIMessage` 的消息（比如 `SystemMessage`、某些边界情况下的 `ToolMessage`），直接访问属性会 `AttributeError`。`getattr` 带默认值是防御性写法，成本几乎为零但能避免一整类崩溃。

### 14.5.4 工具节点：`tool_node`（`agent_service.py:289-315`）

```python
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
            ToolMessage(content=content, tool_call_id=tc.get("id"), name=name)
        )
    return {"messages": messages}
```

请特别注意这个节点的**错误处理哲学**——它完美体现了 14.3.3 里的第 4 条：

> **任何失败都不抛异常，而是变成一条 Observation 消息回喂给模型。**

三种失败全部"降级"成文本：

| 失败类型 | 处理 | 模型的后续行为 |
|---|---|---|
| 用户取消（`approval` 未通过） | `content = "用户取消了本次操作，未执行。"` | 模型会向用户说明已取消，并可能询问是否换个时段 |
| 工具不存在 | `content = f"未找到工具：{name}"` | 模型会意识到自己调错了名字，换个名字重试 |
| 工具执行报错/超时 | `_invoke_tool_with_retry` 返回 `{"ok": false, "error": ...}` | 模型读错误自纠（如换时段、换参数） |

如果这里改成 `raise`，会发生什么？异常会穿透整张图，`run_agent` 捕获后返回"大模型调用失败，请稍后重试"——**用户啥也不知道，只能重来一遍**。而把它变成 Observation，模型有机会自己救回来。这就是"Agent 的韧性"。

**另外一个极易忽略但必须做对的细节**：

```python
ToolMessage(content=content, tool_call_id=tc.get("id"), name=name)
```

`tool_call_id` **必须**和 `AIMessage.tool_calls` 里的 `id` 严格对应。这是 OpenAI 消息协议的硬性约束：一个 `tool_call` 必须有一条同 id 的 `tool_message` 来回应。缺失或错位，API 会直接报 400。

这也是第 19 章"上下文裁剪"里那段"保护 tool_calls 与 ToolMessage 配对"逻辑存在的原因——**裁剪历史时如果只删了 ToolMessage 没删对应的 AI 消息，下次调用模型就会因为协议不完整而报错**。这是一个非常隐蔽、只有真正做过长对话的人才会踩的坑。

### 14.5.5 步数兜底：`recursion_limit`（`agent_service.py:332-333`）

```python
def _make_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 10}
```

这是 LangGraph 自带的保险丝：`recursion_limit=10` 表示图最多执行 10 个"超步（superstep）"，超了就抛 `GraphRecursionError`。

为什么是 10 而不是 6？因为本项目多了审批节点，一次"思考-行动-观察"要消耗 3 个节点（agent → approval → tools），10 步大约能容纳 3 轮工具调用。这个值需要在"够用"和"防跑飞"之间权衡：

- 太小：复杂任务（先查实验室 → 再查设备 → 再预约）会被拦腰截断
- 太大：模型陷入死循环时烧掉大量 token

> ⚠️ **坑 2（真实）**：`recursion_limit` 在 LangGraph 里是**按超步计数**，不是按"轮次"。
> 一个 `agent → approval → tools → agent` 的循环 = 4 个超步。所以 `recursion_limit=10` 只够约 2-3 轮完整工具循环，不是 10 轮。这个换算面试时经常算错。

---

## 14.6 ReAct 的五个真实弱点（面试必问 ".ReAct 有什么问题"）

只会讲 ReAct 的好，面试官会觉得你只背了论文。主动说出它的弱点，才是真的做过。

### 弱点 1：错误会传播且难以回溯

模型第一步调错了工具，第二步基于错误的 Observation 继续推理，第三步又基于第二步……等到第五步发现结论离谱时，**前面四步已经没法撤销了**——尤其是写库操作已经落库的情况下。

**本项目的对策**：把写库工具（如 `create_reservation`）在**执行前**用 `interrupt` 拦下来（第 18 章）。这等于在"不可逆动作"前加了一道人工闸门，是 ReAct 工程化最重要的补丁之一。

### 弱点 2：循环不收敛

模型可能陷入"调工具 → 报错 → 换个参数再调 → 再报错"的循环，直到撞上 `recursion_limit`。表现为用户等了 30 秒，最后收到一句"达到最大步数"。

**对策**：
- `recursion_limit` 硬兜底（本项目已做）
- 工具超时 + 有限重试（第 20 章，本项目已做）
- 在 System Prompt 里写"同一工具连续失败 2 次后，请直接告知用户并说明原因"

### 弱点 3：token 成本随轮次平方增长

见 14.3.3。这是 ReAct 的经济性问题，长任务成本失控。

**对策**：上下文裁剪（第 19 章，本项目已做）、摘要压缩、中间结果不进历史。

### 弱点 4：串行执行，慢

ReAct 循环是**严格串行**的：必须等 Observation 回来才能产生下一个 Thought。如果模型一次要调 3 个独立工具（查 3 个实验室的空闲情况），纯 ReAct 会一个一个查。

**对策**：现代模型支持 **parallel tool calling**（一次返回多个 tool_calls）。本项目的 `tool_node` 用 `for tc in tool_calls` 遍历，天然支持并行返回；但执行是串行的（`await` 在循环里）。如果要真并行，可以改成 `asyncio.gather`。当前选择串行是因为工具都涉及数据库操作，**串行更安全、更容易控制事务**（第 11 章讲过并发事务的坑）。

> 面试可以这样答："parallel tool calling 我们支持接收，但执行上选择了串行，因为工具主要是数据库读写，并行会带来事务竞争和连接池压力；对纯读的工具可以考虑 gather 并行。"

### 弱点 5：没有"全局规划"，容易走一步看一步

ReAct 是**贪心**的：每一步只看眼前，没有完整计划。对于"帮我安排一周的实验计划"这种需要全局统筹的任务，ReAct 会表现得很笨。

**对策**：这就是 Plan-and-Execute、ReWOO、LLM Compiler 等进阶范式存在的理由，也是第 34 章"多 Agent 编排"要解决的问题。

---

## 14.7 和另外三种 Agent 范式的对比

面试时如果只会 ReAct，会被认为"只了解入门"。你至少要知道它在全景图里的位置。

| 范式 | 核心思路 | 优点 | 缺点 | 适用场景 |
|---|---|---|---|---|
| **ReAct** | 思考-行动-观察交替 | 灵活、可自纠、实现简单 | 串行慢、token 平方增长、贪心 | 通用助手、需要多步查证的任务 |
| **Plan-and-Execute** | 先生成完整计划，再逐步执行 | 有全局观、可并行 | 计划一旦错，全盘皆错；计划本身消耗 token | 步骤明确、可拆解的复杂任务 |
| **ReWOO** | 一次性规划所有工具调用，批量执行后再推理 | 大幅减少 LLM 调用次数、省 token | 无法根据中间结果调整后续调用 | 工具调用独立、无需依赖结果的场景 |
| **Reflexion** | 执行后自我反思，把反思写进记忆重试 | 能从失败中学习 | 需要多轮，成本高 | 代码生成、需要迭代优化的任务 |

**本项目为什么选 ReAct？** 三个理由，面试时讲出来说明你是选型而不是跟风：

1. **任务以查询为主**：实验室预约场景 80% 的请求是"查空闲/查设备/查规定"，1-2 轮工具调用就够，ReAct 的循环深度需求很低。
2. **需要自纠**：时段冲突、实验室不存在这类错误很常见，ReAct 把错误回喂给模型自纠的能力非常契合。
3. **需要人工介入**：ReAct 的"行动"环节天然是一个可以插入 `interrupt` 的切面（本项目在 agent 和 tools 之间插了 approval 节点），其他范式没有这么干净的切入点。

---

## 14.8 动手实验：三件事让你真正理解 ReAct

### 实验 1：观察循环深度

跑 `minimal_react.py`，把 `max_steps` 改成 1，看会发生什么。

**预期**：直接返回"⚠️ 达到最大步数仍未得出结论"。因为第一轮只完成了查询，还没来得及执行预约。

**理解**：`max_steps` 不是"最多说几句话"，是"最多做几轮思考-行动"。它必须 ≥ 任务所需的工具调用轮数 + 1（最后一轮用于总结）。

### 实验 2：制造工具失败，观察自纠

把 `create_reservation` 改成永远返回 `{"ok": false, "error": "时段冲突"}`，把 `max_steps` 改成 8。

**预期**：模型会不断尝试（换时段、换实验室），直到耗尽步数。

**理解**：这就是"循环不收敛"。真实项目里要靠 `recursion_limit` + prompt 约束 + 人工审批来兜底。**同时要意识到：这 8 步的 token 已经烧掉了**，这就是为什么生产环境必须做成本监控（第 40、41 章）。

### 实验 3：破坏 tool_call_id 配对

在 `tool_node` 里把 `tool_call_id=tc.get("id")` 改成 `tool_call_id="wrong-id"`，然后发起一次需要调工具的请求。

**预期**：OpenAI 兼容接口返回 400 错误，类似：

```
BadRequestError: An assistant message with 'tool_calls' must be followed by
tool messages responding to each tool_call_id.
```

**理解**：这是消息协议的硬约束，也是第 19 章裁剪逻辑必须保护配对的原因。踩过这个坑，你对"为什么裁剪要成对删"就有体感了。

---

## 14.9 面试问答：这一章会被怎么问

### Q1：什么是 ReAct？和普通的 Function Calling 有什么区别？

**答**：ReAct 是一种 Agent 范式，让模型在"推理"和"行动"之间交替：先推理决定做什么，调用工具，拿到结果后再推理，直到能给出答案。

和单纯 Function Calling 的区别在于：**Function Calling 是一次性的能力**（模型能调工具），**ReAct 是一个循环结构**（模型能根据工具结果持续调整）。Function Calling 是 ReAct 的"行动"这个环节的实现手段，ReAct 是组织这些调用的框架。打个比方：Function Calling 是"手"，ReAct 是"手眼协调的闭环"。

### Q2：ReAct 循环在代码里怎么终止的？

**答**：两个终止条件：

1. **正常终止**：模型返回的 `AIMessage` 里 `tool_calls` 为空，说明它认为信息够了，可以直接回答。本项目里对应 `_route_after_agent` 返回 `"end"`。
2. **兜底终止**：`recursion_limit`（本项目设为 10）防止死循环。注意 LangGraph 里它按"超步"计数，一个完整的 agent→approval→tools 循环占 3 个超步，所以 10 大约够 3 轮。

### Q3：工具调用失败了你会怎么处理？

**答**：分三层：

- **工具层**：超时 + 有限重试（`_invoke_tool_with_retry`，30 秒超时、1 次重试）。
- **协议层**：最终失败不抛异常，而是返回 `{"ok": false, "error": "..."}` 作为 `ToolMessage` 的内容回喂给模型，让它读错误自纠（如换时段重试）。
- **全局层**：`recursion_limit` 兜底，超出后给用户明确提示。

这里的关键设计是**不抛异常，而是把错误变成 Observation**——因为异常会中断整个循环，而 Observation 给了模型自己救回来的机会。

### Q4：ReAct 有什么缺点？你怎么解决的？

**答**：五个主要缺点（对应 14.6）：错误传播、循环不收敛、token 平方增长、串行执行慢、贪心无全局规划。

我们针对性做了三件事：写库操作前用 `interrupt` 加人工审批闸门（防错误传播到不可逆动作）；`recursion_limit=10` + 工具超时重试（防不收敛 + 防卡死）；送入模型前按 token 预算裁剪历史（控成本）。串行慢的问题我们权衡后保留了串行，因为工具以数据库读写为主，并行会带来事务竞争。

至于无全局规划，我们评估后认为实验室预约场景 1-2 轮工具调用就够，暂时不需要 Plan-and-Execute；如果后续要做"安排一周实验计划"这种任务，会考虑引入。

### Q5：为什么不直接用 Plan-and-Execute 或 ReWOO？

**答**：选型要看任务特征。我们的场景有三个特点：一是工具调用轮次浅（多数 1-2 轮），Plan-and-Execute 的前置规划成本（一次额外 LLM 调用 + 更长 prompt）反而更贵；二是错误率高（时段冲突、实验室不存在很常见），需要"看到结果再调整"的能力，这正是 ReAct 的强项，而 ReWOO 一次性规划完就无法根据中间结果调整；三是需要在写库前插入人工审批，ReAct 的"行动"环节天然是一个干净的可中断切面。

### Q6：模型的 Thought 在哪？我怎么调试它？

**答**：Function Calling 形态下 Thought 是隐式完成的，模型内部推理，直接吐出 `tool_calls`。调试手段有三种：

1. 用推理模型（如 DeepSeek-R1），它会返回 `reasoning_content` 字段，能直接看到思考过程。
2. 在 prompt 里要求模型在输出 tool_calls 前先用一段文本说明意图（部分场景可用，但会略微降低工具调用的准确性）。
3. 接可观测性平台（LangSmith / Langfuse），把每轮的消息、token、耗时打点记录下来（第 40 章）。

---

## 14.10 速记卡

> **ReAct = Reasoning + Acting 交替循环**，2022 年 Google 提出，对抗 CoT 的幻觉问题和 Act-only 的盲目问题。

**一句话定义**：让模型在自言自语推理和调用外部工具之间交替，用真实观察结果不断修正推理。

**三要素**：
- Thought → 模型内部推理（Function Calling 形态下隐式）
- Action → `AIMessage.tool_calls`
- Observation → `ToolMessage`

**代码三行对应**：
```python
if not ai.tool_calls:  return ai.content      # 出口
for tc in ai.tool_calls: ...                  # 行动
messages.append(ToolMessage(...))             # 观察
```

**四条工程铁律**：
1. 错误变 Observation 回喂，不要抛异常（给了模型自纠机会）
2. `tool_call_id` 必须严格配对（协议硬约束，错了对不上 400）
3. 必须有 `max_steps` / `recursion_limit` 兜底（防死循环烧钱）
4. token 是平方级增长的，长任务必须裁剪历史

**五个弱点**：错误传播 / 不收敛 / token 平方增长 / 串行慢 / 贪心无规划

**本项目对应位置**：
- 图结构：`agent_service.py:317-329`
- 模型节点：`agent_service.py:264-270`
- 出口判定：`agent_service.py:147-152`
- 工具节点：`agent_service.py:289-315`
- 步数兜底：`agent_service.py:332-333`

---

## 14.11 延伸思考

留三个问题，想清楚它们，你对 Agent 的理解会超过大多数候选人：

1. **如果工具返回的结果本身是错的（比如数据库里的数据就是脏的），ReAct 能发现吗？**
   不能。ReAct 保证的是"结论有 Observation 支撑"，不保证 Observation 本身正确。这就是为什么引用溯源（第 29 章）很重要——让用户可以回溯到原文验证。

2. **`recursion_limit` 撞上之后，用户看到什么？你会怎么优化体验？**
   目前是异常提示。更好的做法是：撞限后把已有轨迹交给模型，让它"基于目前掌握的信息给出一个阶段性答复"，而不是直接失败。这是一个很实际的优化点，可以写进简历。

3. **ReAct 循环里的每一步都要调用一次 LLM，有没有办法省？**
   有。比如"确定性步骤"可以不用 LLM——如果模型要连查 3 个独立实验室的空闲情况，可以一次返回 3 个 tool_calls 批量执行（parallel tool calling），省掉 2 次 LLM 调用。再进一步就是 ReWOO 的思路。

---

**下一章**：第 15 章 · LangGraph 状态机——把这一章手写的循环，变成一个可持久化、可中断、可观测的图。
