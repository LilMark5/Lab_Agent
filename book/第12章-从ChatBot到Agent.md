# 第 12 章 · 从 ChatBot 到 Agent

## 开篇：一个被问烂但答不好的问题

**「Agent 和 ChatBot 有什么区别？」**

这是每场 Agent 面试的开场题。常见的答案有：

| 常见答案 | 问题 |
|---|---|
| 「Agent 能调工具」 | 那加了天气查询的 ChatGPT 算 Agent 吗？ |
| 「Agent 能多轮对话」 | ChatGPT 也能多轮 |
| 「Agent 更智能」 | 废话 |
| 「Agent 有记忆」 | 记忆是组件，不是本质区别 |

**这些答案都不够。**

真正区别在三个字：**自主性**（Autonomy）。

---

## 一、本质区别：控制流在哪

### 1.1 ChatBot：控制流在代码里

```python
def chatbot(user_input):
    intent = classify(user_input)      # 代码判断意图

    if intent == "weather":
        city = extract_city(user_input)
        return call_weather_api(city)  # 代码决定调什么
    elif intent == "time":
        return get_current_time()
    else:
        return llm.chat(user_input)    # 兜底给模型
```

**特征**：执行路径是**代码写死的**。`if/else` 的每一个分支，都是程序员预先想到的。

```
用户输入 → [代码判断] → 分支A / 分支B / 分支C → 输出
                ↑
          程序员写死
```

### 1.2 Agent：控制流在模型里

```python
async def agent(user_input):
    messages = [SystemMessage(...), HumanMessage(user_input)]
    while True:
        response = await llm.ainvoke(messages)      # 模型决定下一步

        if not response.tool_calls:
            return response.content               # 模型说「可以回答了」

        for tc in response.tool_calls:
            result = await execute_tool(tc)        # 执行模型选的工具
            messages.append(ToolMessage(result))

        messages.append(response)                  # 循环，让模型再看结果
```

**特征**：执行路径是**模型在运行时决定的**。程序员不知道它会调几次工具、调哪些。

```
用户输入 → [模型决策] → 工具A → [模型再看] → 工具B → [模型说够了] → 输出
              ↑___________________________________________|
                        循环，次数未知
```

### 1.3 一句话总结

> **ChatBot：代码决定流程，模型负责生成文字。**
> **Agent：模型决定流程，代码负责执行和兜底。**

> 💡 **面试话术**：「本质区别是控制流的位置。ChatBot 的执行路径是代码写死的——if/else 的每个分支都是我预先想到的，模型只负责生成文字。Agent 的执行路径是模型在运行时决定的——我不知道它会调几次工具、调哪些工具、什么时候停。
>
> 这个区别带来一系列工程后果：一是没法用传统单测覆盖所有分支，必须注入假模型让路径确定才能断言；二是失败变成常态且不可预测，模型可能选错工具、编错参数、陷入循环，这些都要在运行时兜住；三是成本变成一等公民，因为调用次数未知。
>
> 所以我的理解是：**Agent 开发的难点不是『让模型调工具』，而是『在模型不可靠的前提下，把系统做得可靠』。**」

---

## 二、Agent 的四个构成要件

不是「能调工具」就叫 Agent。一个真正的 Agent 需要：

```
┌─────────────────────────────────────────────┐
│                  Agent                       │
│                                              │
│  ① 模型（大脑）                               │
│     负责：理解、规划、决策                     │
│                                              │
│  ② 工具（手脚）                               │
│     负责：执行、查询、改变世界                 │
│                                              │
│  ③ 循环（引擎）                               │
│     负责：观察结果 → 再决策 → 直到完成         │
│                                              │
│  ④ 状态（记忆）                               │
│     负责：跨轮次保持上下文                     │
│                                              │
└─────────────────────────────────────────────┘
```

**缺一个都不完整**：

| 缺了 | 变成什么 |
|---|---|
| 缺工具 | 就是 ChatBot（只能聊天） |
| 缺循环 | 只能调一次工具，复杂任务做不了 |
| 缺状态 | 每轮都是新的，无法多轮协作 |
| 缺模型 | 就是普通程序 |

**最容易被忽略的是「状态」**。很多人写的「Agent」每次调用都是全新的对话，那它其实只是「带工具的问答」。

---

## 三、自主性的三个层次

Agent 不是一个非此即彼的概念，而是有**程度**的。

### 层次 0：无自主（ChatBot）

```
用户："帮我预约明天的A301"
系统：（固定流程）查实验室 → 查时段 → 创建 → 返回结果
```

路径固定，不会变通。

### 层次 1：工具自主（Tool-level）

```
用户："明天有能做细胞实验的实验室吗？"
Agent：（自己决定）
      → search_labs(keyword="细胞")      # 它决定先查实验室
      → list_equipments(lab_id=1)        # 它决定再查设备
      → "A301 有共聚焦显微镜，可以做"
```

**模型决定调哪些工具、什么顺序。但整体流程框架是预设的。**

### 层次 2：规划自主（Plan-level）

```
用户："我下周要做细胞实验，帮我安排一下"
Agent：（自己规划）
      1. 先查有哪些细胞实验室
      2. 查这些实验室的设备
      3. 查下周的空闲时段
      4. 综合推荐并预约
```

**模型自己分解任务、排出步骤。**

### 层次 3：完全自主（Open-ended）

```
用户："帮我准备下周的实验"
Agent：（自己探索）
      → 查日历 → 查实验要求 → 查库存 → 订试剂 → 预约实验室 → 通知同事
      → 遇到缺试剂 → 自己决定发采购申请
```

**没有预设的边界，模型自己决定做什么、什么时候停。**

> ⚠️ **重要判断**：**层次不是越高越好**。层次越高，越不可控、越贵、越难测。
>
> **本项目在层次 1-2 之间**：模型决定调哪些工具（层次1），偶尔会自己规划多步（层次2），但整体被 System Prompt 和工具集约束在「实验室预约」这个域内。

> 💡 **面试话术**：「自主性有程度之分：工具自主（模型决定调哪些工具）、规划自主（模型自己分解任务）、完全自主（没有预设边界）。我的项目在工具自主到规划自主之间——模型自己决定查什么，但被 System Prompt 和工具集约束在实验室预约这个域内。
>
> 我刻意没有做完全自主，因为层次越高越不可控。完全自主的 Agent 需要更强的模型、更完善的评测、更严格的权限控制，现阶段投入产出比不高。」

---

## 四、什么时候不该用 Agent（重要！）

**这是面试的加分点**——大部分候选人只会说「Agent 好」，你能说出「什么时候不该用」，说明你有工程判断力。

### 4.1 判断标准

> **如果任务路径可以被穷举成流程图，就不要用 Agent。**

### 4.2 反面例子（不该用 Agent）

| 场景 | 为什么不该用 |
|---|---|
| 用户上传发票 → 提取金额 → 入库 | 三步固定，写死更可靠更便宜 |
| 用户注册 → 校验 → 发邮件 → 建账号 | 固定流程 |
| 定时任务：每天统计预约数 → 生成报表 | 没有不确定性 |
| 表单填写引导 | 固定顺序的问题 |

**用 Agent 的代价**：

- 延迟高（每次决策都要调模型）
- 成本高
- 行为不可预测（可能走歪）
- 难测试

**写死流程的代价**：需要预先穷举所有分支。

**如果分支能穷举，写死一定更好。**

### 4.3 正面例子（该用 Agent）

| 场景 | 为什么该用 |
|---|---|
| 「帮我找个下周能做细胞实验的实验室」 | 要查什么取决于实验室实际情况，路径不可穷举 |
| 「实验室能带食物吗？」 | 要从知识库检索，问题形式发散 |
| 「我上周说的那个实验室还能预约吗」 | 需要上下文理解和指代消解 |
| 开放域的客服 | 用户意图发散 |

**共同特征**：
1. **用户意图发散**（不知道用户会怎么问）
2. **路径不可穷举**（下一步取决于上一步的结果）
3. **需要理解上下文**（指代、省略、隐含意图）

### 4.4 混合方案（实践中最好）

现实项目通常是**混合的**：

```
用户输入
   ↓
[意图分类] ← 规则或小模型（快、便宜、确定）
   ↓
├─ 确定任务（查我的预约、取消预约）→ 固定流程代码
├─ 知识问答（规章制度）→ RAG 流程
└─ 开放任务（找实验室、安排实验）→ Agent
```

**本项目就是这个结构**：

```
用户："取消我的预约"
  → 其实可以走固定流程（但项目里也交给了 Agent）

用户："实验室能带食物吗？"
  → 走 RAG（search_lab_docs 工具）

用户："帮我找个能做细胞实验的实验室"
  → 走 Agent 多步规划
```

> 💡 **面试话术**：「我的判断标准是：**路径能被穷举成流程图就不用 Agent**。比如『上传发票 → 提取金额 → 入库』，这三步是确定的，写死比让模型规划更可靠也更便宜。
>
> Agent 适合的是『用户意图发散、路径不可穷举』的场景。比如『帮我找个下周能做细胞实验的实验室』——要查哪些东西取决于实验室的实际设备情况，没法预先穷举。
>
> 实践中我倾向于混合：先用规则或小模型做意图分类，确定的任务走固定流程，开放的任务才交给 Agent。这样成本和可靠性都能兼顾。
>
> 说实话我项目里有可以改进的地方：预约确认这个流程其实是固定的，我用 Agent 有一部分原因是为了演示 human-in-the-loop。如果纯从工程角度，那部分应该写死。」

---

## 五、Agent 的执行循环：ReAct

Agent 的循环有个名字：**ReAct**（Reasoning + Acting）。

### 5.1 三步循环

```
1. Reasoning（推理）：模型思考"我现在该做什么"
   → 输出：思考过程 + 决定要调的工具

2. Acting（行动）：执行工具
   → 输出：工具结果

3. Observing（观察）：把结果给模型看
   → 模型再推理，决定下一步
   → 回到 1
```

**用项目里的真实例子**：

```
用户输入："帮我预约明天下午2点的A301实验室"

── 第 1 圈 ──
Reasoning: "用户要预约 A301，但我不知道 A301 的 ID 是多少。
           我需要先查一下。"
Acting:    search_labs(keyword="A301")
Observing: [{"id": 1, "name": "A301 细胞生物学实验室", "capacity": 20}]

── 第 2 圈 ──
Reasoning: "A301 的 ID 是 1。现在可以创建预约了。
           但这是写库操作，需要用户确认。"
Acting:    create_reservation(lab_id=1, date="2025-01-18",
                              start_time="14:00:00", end_time="17:00:00")
           ⏸️ 被 interrupt 拦下，等用户确认

── 用户确认 ──

── 第 3 圈 ──
Observing: {"ok": true, "id": "R20250118001"}
Reasoning: "预约成功了，可以告诉用户了。"
输出:      "已为你预约 A301 细胞生物学实验室，1月18日 14:00-17:00，
           预约单号 R20250118001，状态待审核。"
```

### 5.2 ReAct 的核心洞察

> **让模型「看到」自己行动的结果，然后再决定下一步。**

这是 Agent 和普通「一次性调用工具」的关键区别。

**对比**：

```
❌ 一次性调用：
   模型 → 调工具 → 拿到结果 → 直接回答
   （工具结果是否正确，模型没有机会判断）

✅ ReAct 循环：
   模型 → 调工具 → 看结果 → "结果不对，换个参数再试" → 再调 → 回答
```

**第 4 章讲过：工具失败要回填错误让模型自纠。** 这个设计就是 ReAct 的直接应用——模型看到错误信息，可以自己换个思路。

---

## 六、Agent 的四个工程挑战

理解了 Agent 的本质，就能理解为什么它需要这么多工程设施。

### 挑战 1：循环怎么停下来？

模型可能永远觉得「还要再查一次」。

**解法**：
- `recursion_limit`（硬限制）
- System Prompt 约束「两次失败就告诉用户」
- 路由逻辑：`if not tool_calls: END`

### 挑战 2：状态怎么保存？

下一轮对话要知道上一轮说了什么。

**解法**：checkpointer（第 17 章）

### 挑战 3：危险操作怎么控制？

模型决定要删数据，拦不拦？

**解法**：interrupt + 人工确认（第 18 章）

### 挑战 4：上下文爆炸怎么办？

多轮 + 工具结果，token 快速增长。

**解法**：裁剪（第 19 章）

**这四章（16-19）就是围绕这四个挑战展开的。**

---

## 七、最小可运行骨架：手写 ReAct 循环

不用任何框架，50 行实现 ReAct 的核心，理解它到底在做什么。

```python
"""
react_from_scratch.py —— 手写 ReAct 循环
运行：python react_from_scratch.py（无需 API Key，用模拟模型）
演示：Reasoning → Acting → Observing 循环，以及循环如何停止
"""

import json
from typing import Callable

# ══════════════════════════════════════════════════════════
# 1. 工具集（模拟）
# ══════════════════════════════════════════════════════════

LABS_DB = [
    {"id": 1, "name": "A301 细胞生物学实验室", "capacity": 20, "equipments": ["共聚焦显微镜", "离心机"]},
    {"id": 2, "name": "B205 材料分析实验室", "capacity": 15, "equipments": ["电子显微镜", "XRD"]},
]
RESERVATIONS = []

def search_labs(keyword: str = "") -> str:
    """根据关键词搜索实验室。"""
    matched = [l for l in LABS_DB if keyword in l["name"] or not keyword]
    return json.dumps(matched, ensure_ascii=False)

def list_equipments(lab_id: int) -> str:
    """查询某实验室的设备列表。"""
    lab = next((l for l in LABS_DB if l["id"] == lab_id), None)
    if not lab:
        return json.dumps({"ok": False, "error": "实验室不存在"}, ensure_ascii=False)
    return json.dumps({"ok": True, "equipments": lab["equipments"]}, ensure_ascii=False)

def create_reservation(lab_id: int, date: str, start_time: str, end_time: str) -> str:
    """创建预约（写操作）。"""
    RESERVATIONS.append({"lab_id": lab_id, "date": date,
                         "start_time": start_time, "end_time": end_time})
    return json.dumps({"ok": True, "id": f"R{len(RESERVATIONS):03d}"}, ensure_ascii=False)

TOOLS: dict[str, Callable] = {
    "search_labs": search_labs,
    "list_equipments": list_equipments,
    "create_reservation": create_reservation,
}

# ══════════════════════════════════════════════════════════
# 2. 模拟模型（关键：看它怎么"决策"）
# ══════════════════════════════════════════════════════════

class FakeLLM:
    """模拟模型的决策过程。真实模型是根据上下文生成，
    这里用一个简单的状态机模拟，让你看清循环结构。"""

    def __init__(self, script=None):
        self.round = 0
        self.script = script or []

    def think(self, messages: list) -> dict:
        """返回 {"thought": 思考内容, "tool_calls": [...]} 或 {"answer": ...}"""
        # 看最后一条消息（工具结果）来决定下一步
        last_tool_result = None
        for m in reversed(messages):
            if m["role"] == "tool":
                last_tool_result = m["content"]
                break

        self.round += 1

        # 第 1 轮：还没查过，先查实验室
        if self.round == 1:
            return {
                "thought": "用户要预约 A301，但我不知道它的 ID。先搜索。",
                "tool_calls": [{"name": "search_labs", "args": {"keyword": "A301"}}],
            }

        # 第 2 轮：拿到实验室列表了，可以创建预约
        if self.round == 2:
            labs = json.loads(last_tool_result)
            lab_id = labs[0]["id"]
            return {
                "thought": f"找到了，A301 的 ID 是 {lab_id}。现在创建预约。",
                "tool_calls": [{
                    "name": "create_reservation",
                    "args": {"lab_id": lab_id, "date": "2025-01-18",
                             "start_time": "14:00:00", "end_time": "17:00:00"},
                }],
            }

        # 第 3 轮：预约成功，可以回答了
        return {
            "thought": "预约成功了，告诉用户结果。",
            "answer": "已为你预约 A301 细胞生物学实验室，1月18日 14:00-17:00。"
        }

# ══════════════════════════════════════════════════════════
# 3. ReAct 循环（核心！）
# ══════════════════════════════════════════════════════════

def run_react(user_input: str, llm: FakeLLM, max_rounds: int = 10,
              verbose: bool = True) -> str:
    """ReAct 主循环。"""
    messages = [{"role": "user", "content": user_input}]

    for round_no in range(1, max_rounds + 1):
        if verbose:
            print(f"\n{'─'*60}")
            print(f"第 {round_no} 圈")
            print(f"{'─'*60}")

        # ── 1. Reasoning：模型思考 ──
        response = llm.think(messages)
        thought = response.get("thought", "")
        if verbose:
            print(f"💭 Reasoning: {thought}")

        # ── 判断是否结束 ──
        if "answer" in response:
            if verbose:
                print(f"✅ 模型决定结束循环")
            return response["answer"]

        # ── 2. Acting：执行工具 ──
        tool_calls = response.get("tool_calls", [])
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": tool_calls})

        for tc in tool_calls:
            name, args = tc["name"], tc["args"]
            if verbose:
                print(f"🔧 Acting:    {name}({args})")

            tool = TOOLS.get(name)
            if tool is None:
                result = json.dumps({"ok": False, "error": f"未找到工具：{name}"},
                                    ensure_ascii=False)
            else:
                try:
                    result = tool(**args)
                except Exception as e:
                    # ★ 关键：失败不中断，回填错误让模型自纠
                    result = json.dumps({"ok": False, "error": str(e)},
                                        ensure_ascii=False)

            if verbose:
                preview = result[:100] + ("..." if len(result) > 100 else "")
                print(f"👁 Observing: {preview}")

            # ── 3. Observing：把结果加入消息 ──
            messages.append({"role": "tool", "content": result})

    # 超过 max_rounds
    return "（达到最大轮次限制，强制结束）"

# ══════════════════════════════════════════════════════════
# 4. 演示
# ══════════════════════════════════════════════════════════

def demo_normal():
    print("=" * 60)
    print("【演示 1】正常流程")
    print("=" * 60)
    llm = FakeLLM()
    answer = run_react("帮我预约明天下午2点的A301实验室", llm)
    print(f"\n📤 最终回答: {answer}")
    print(f"\n📊 统计: 共 {llm.round} 圈，创建了 {len(RESERVATIONS)} 条预约")

def demo_tool_error():
    print("\n" + "=" * 60)
    print("【演示 2】工具调用失败 → 模型自纠")
    print("=" * 60)

    class BuggyLLM(FakeLLM):
        """故意传错参数，演示错误回填后的自纠。"""
        def think(self, messages):
            self.round += 1
            if self.round == 1:
                return {
                    "thought": "查设备，但故意传个不存在的 lab_id。",
                    "tool_calls": [{"name": "list_equipments", "args": {"lab_id": 999}}],
                }
            if self.round == 2:
                # 看到错误了，改成正确的 ID
                return {
                    "thought": "上次的 ID 不存在，换成 1 再试。",
                    "tool_calls": [{"name": "list_equipments", "args": {"lab_id": 1}}],
                }
            return {"thought": "拿到了。", "answer": "A301 的设备有：共聚焦显微镜、离心机"}

    run_react("A301 有哪些设备？", BuggyLLM())

def demo_infinite_loop():
    print("\n" + "=" * 60)
    print("【演示 3】模型陷入循环 → recursion_limit 兜底")
    print("=" * 60)

    class LoopingLLM(FakeLLM):
        """永远觉得还要再查一次。"""
        def think(self, messages):
            self.round += 1
            return {
                "thought": "再查一次看看...",
                "tool_calls": [{"name": "search_labs", "args": {"keyword": ""}}],
            }

    answer = run_react("有哪些实验室？", LoopingLLM(), max_rounds=5, verbose=False)
    print(f"  max_rounds=5，模型每轮都要再查")
    print(f"  最终结果: {answer}")
    print(f"  ✅ 循环被硬限制拦住了（真实项目里这里是 recursion_limit）")
    print(f"  ⚠️ 如果不设限制：无限调用 = 无限烧钱")

def demo_comparison():
    print("\n" + "=" * 60)
    print("【对比】ChatBot vs Agent")
    print("=" * 60)
    print("""
    ChatBot（控制流在代码）：

      用户输入 → if 意图=="查实验室": → 查 → 返回
                 elif 意图=="预约":   → 预约 → 返回
                 else:                → 模型兜底
                   ↑ 每个分支程序员写死

    Agent（控制流在模型）：

      用户输入 → 模型决策 → 工具 → 观察 → 模型决策 → ... → 模型说够了 → 返回
                   ↑___________________________________|
                        循环次数由模型决定

    后果对比：
    ┌────────────┬──────────────────┬────────────────────┐
    │            │ ChatBot          │ Agent              │
    ├────────────┼──────────────────┼────────────────────┤
    │ 路径可预测  │ ✅ 完全可预测     │ ❌ 运行时才确定      │
    │ 测试        │ ✅ 分支覆盖       │ ⚠️ 需注入假模型      │
    │ 失败模式    │ 明确的错误        │ 选错工具/编错参数/循环│
    │ 成本        │ 固定             │ 未知（可能很高）     │
    │ 灵活性      │ ❌ 穷举不了       │ ✅ 意图发散也能处理   │
    └────────────┴──────────────────┴────────────────────┘
    """)

if __name__ == "__main__":
    demo_normal()
    demo_tool_error()
    demo_infinite_loop()
    demo_comparison()
```

**跑一遍你会看到**：

1. **正常流程**：3 圈完成任务，每一圈的 Reasoning / Acting / Observing
2. **错误自纠**：第 1 圈参数错了，看到错误后第 2 圈改正
3. **无限循环**：被 `max_rounds` 拦住（这就是 `recursion_limit` 的原理）

---

## 八、项目代码定位：Agent 在哪

### 8.1 四个构成要件对应到项目

| 要件 | 项目位置 |
|---|---|
| ① 模型 | `agent_service.py:256` `ChatOpenAI(...)` |
| ② 工具 | `agent_tools.py` 全部 |
| ③ 循环 | `agent_service.py:317-326` 图的边（`tools → agent`） |
| ④ 状态 | `AgentState` + checkpointer |

### 8.2 AgentState

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    approval: dict | None
```

| 字段 | 作用 |
|---|---|
| `messages` | 对话历史（`add_messages` 保证追加而非覆盖） |
| `approval` | 人工审批的决策（approval 节点写、tools 节点读） |

**为什么要有 `approval` 字段？**

因为审批决策需要在**节点之间传递**：`approval` 节点拿到用户的决定，写进 state；`tools` 节点读出来决定要不要执行。

这是「节点间通信」的典型模式——不通过参数传递，而是通过共享状态。

### 8.3 循环的实现：那条回边

```python
graph.add_edge("tools", "agent")    # ← 这一行就是 ReAct 循环
```

**去掉这一行会怎样？** 工具执行一次就结束了，模型没有机会看到结果再决策。那就退化成「一次性工具调用」，不是 Agent。

---

## 本章速记卡

1. **本质区别是控制流位置**：ChatBot 写代码里，Agent 写模型里。
2. **四个构成要件**：模型（大脑）、工具（手脚）、循环（引擎）、状态（记忆）。缺一不完整。
3. **自主性三层次**：工具自主 / 规划自主 / 完全自主。**不是越高越好**。
4. **判断标准**：路径能穷举成流程图就不用 Agent。混合方案实践中最好。
5. **ReAct = Reasoning → Acting → Observing 循环**，核心是「让模型看到自己行动的结果」。
6. **循环的回边**（`tools → agent`）是 Agent 的关键，去掉就退化成一次性调用。
7. **四个工程挑战**：循环怎么停、状态怎么存、危险操作怎么控、上下文怎么管。
8. **`recursion_limit` 必须设**，不设会无限循环烧钱。
9. **工具失败回填错误**是 ReAct 的直接应用（让模型自纠）。
10. **本项目在工具自主到规划自主之间**，被 System Prompt 和工具集约束在预约域内。

---

## 面试问答：Agent 本质

### Q1：「Agent 和 ChatBot 有什么区别？」

**满分答法**：

> 本质区别是**控制流的位置**。
>
> ChatBot 的执行路径是代码写死的——if/else 的每个分支都是程序员预先想到的，模型只负责生成文字。
>
> Agent 的执行路径是模型在运行时决定的——我不知道它会调几次工具、调哪些、什么时候停。程序员写的是「循环 + 兜底」，不是具体路径。
>
> 这个区别带来三个工程后果：
>
> 一是**测试方式变了**。没法用传统单测覆盖所有分支，必须注入假模型让执行路径确定，才能断言「审批节点有没有触发」「工具重试了几次」。
>
> 二是**失败变成常态**。模型可能选错工具、编错参数、陷入循环，这些都要在运行时兜住——我的做法是工具失败不抛异常，而是把错误回填给模型让它自纠。
>
> 三是**成本变成一等公民**。调用次数未知，所以要设 recursion_limit、要做上下文裁剪、要考虑模型分级。
>
> 所以我的理解是：Agent 开发的难点不是「让模型调工具」，而是「在模型不可靠的前提下把系统做得可靠」。

---

### Q2：「什么时候不该用 Agent？」

**满分答法**（加分题）：

> 判断标准：**如果任务路径能被穷举成流程图，就不要用 Agent**。
>
> 比如「上传发票 → 提取金额 → 入库」，这三步是确定的，写死比让模型规划更可靠也更便宜。用 Agent 的代价是延迟高、成本高、行为不可预测、难测试，这些代价只有在路径不可穷举时才值得付。
>
> Agent 适合三个特征：用户意图发散（不知道会怎么问）、路径不可穷举（下一步取决于上一步结果）、需要理解上下文（指代、省略）。
>
> 实践中我倾向混合方案：先用规则或小模型做意图分类，确定的任务走固定流程，开放任务才交给 Agent。
>
> 说实话我项目里有可以改进的地方——预约确认这个流程其实是固定的，我用 Agent 有一部分原因是为了演示 human-in-the-loop，纯从工程角度那部分应该写死。

---

### Q3：「ReAct 是什么？」

**满分答法**：

> ReAct 是 Reasoning（推理）+ Acting（行动）的组合，实际还有一个 Observing（观察），形成一个循环：
>
> 模型先推理「我现在该做什么」，然后决定调什么工具；工具执行完，把结果作为观察返回给模型；模型看到结果后再推理，决定是继续调工具还是给出最终答案。
>
> 核心洞察是：**让模型看到自己行动的结果，然后再决定下一步**。这是 Agent 和「一次性工具调用」的关键区别——有了观察这一步，模型才有机会发现「结果不对，换个参数再试」。
>
> 这也是为什么工具失败要回填错误而不是抛异常——抛异常图就断了，回填错误模型才有机会自纠。
>
> 在 LangGraph 里，这个循环就是 `tools → agent` 那条回边。去掉它，就退化成一次性调用了。

---

### Q4：「你的 Agent 有多少自主性？为什么不做更高？」

**满分答法**：

> 自主性我分三个层次：工具自主（模型决定调哪些工具）、规划自主（模型自己分解任务步骤）、完全自主（没有预设边界）。
>
> 我的项目在工具自主到规划自主之间。模型自己决定查什么（比如先查实验室再查设备），偶尔会自己规划多步，但整体被 System Prompt 和工具集约束在实验室预约这个域内。
>
> 我刻意没有做完全自主，三个原因：
>
> 一是**可控性**。完全自主意味着模型可能做出我没预料的操作，而我只有 interrupt 这一道保险（还只覆盖写库）。
>
> 二是**成本**。开放的探索会大量增加模型调用次数，而且不确定性高，无法预估。
>
> 三是**评测难度**。完全自主的行为没有标准答案，我没法建有效的评测集。
>
> 现阶段投入产出比不高。如果将来要做，我会先建更完善的评测体系，再逐步放开。

---

### Q5：「Agent 的循环怎么停下来？」

**满分答法**：

> 正常情况是模型自己决定停——当它返回的 AIMessage 里没有 `tool_calls`，路由函数就走 END。
>
> 但模型可能不停，所以要三层防护：
>
> **第一层，路由逻辑**：`if not tool_calls: END`。这是正常出口。
>
> **第二层，recursion_limit**：我在 config 里设了 10，图最多走 10 步，超了 LangGraph 抛 `GraphRecursionError`。这个必须有——不设的话模型陷入「调工具→失败→再调同样工具」的循环会一直烧钱。
>
> **第三层，Prompt 软约束**：System Prompt 里写「如果两次尝试都失败，就直接告诉用户你做不到，不要无限重试」。
>
> 另外工具层面还有超时（30 秒）和有限重试（1 次），防止单个工具卡死拖垮整个循环。

---

### Q6：「如果模型一直不调工具，或者一直调错，你怎么排查？」

**满分答法**（这题考实战）：

> 我会先看日志。我在关键节点记录了每次模型返回的 tool_calls，能看到它到底"想"做什么。
>
> 排查顺序：
>
> **第一步，确认工具 schema 发出去了没有**。检查 `bind_tools` 有没有调、工具列表是不是空的。我有次遇到 MCP 加载失败导致工具列表为空，模型当然不会调。
>
> **第二步，看工具描述**。是不是没写清使用场景？我会检查 description 里有没有明确的触发条件。
>
> **第三步，看 System Prompt**。有没有「这类问题必须调工具」的约束？
>
> **第四步，看具体失败案例**。如果是「一直调错工具」，通常是两个工具描述太相似，模型分不清——这时要么合并它们，要么在描述里写清区别。如果是「一直编错参数」，是参数 description 没写清格式。
>
> **第五步，做对照实验**。改一版跑一次评测集，看工具调用率和准确率的变化。凭感觉改是没用的。
>
> 另外我会加监控：记录每个类别问题的工具调用率，如果突然下降能及时发现。

---

## 常见坑

### 坑 1：以为「能调工具」就是 Agent

没有循环、没有状态，那只是「带工具的问答」。

### 坑 2：不设 recursion_limit

无限循环烧钱。这是最贵的坑。

### 坑 3：工具失败抛异常

图断了，模型没机会自纠。

### 坑 4：状态不持久化

每轮都是新的，多轮协作失效。

### 坑 5：过度追求自主性

越自主越不可控、越贵、越难测。

### 坑 6：把固定流程也做成 Agent

成本高、可靠性差。

### 坑 7：忘了「观察」这一步

直接把工具结果返回给用户，模型没机会判断对错。

---

## 动手练习

### 练习 1（必做）

跑通第七节的 `react_from_scratch.py`，观察三个演示：

1. 正常流程走了几圈？
2. 错误自纠是怎么发生的？
3. 无限循环被什么拦住的？

然后**去掉 `max_rounds`**（改成很大的数）跑演示 3，看会发生什么。

### 练习 2

修改 `run_react`，加上「工具并行」：如果模型一次返回多个 tool_calls，同时执行而不是串行。

> 提示：真实的 Agent 里要注意工具有没有依赖关系。

### 练习 3

打开 `agent_service.py`，画出你的项目的图结构：

```
START → ? → ? → ?
```

标出哪些是条件边、条件是什么。对照第 15 章验证。

### 练习 4（进阶）

思考并写下答案：你的项目里，有哪些功能其实**不该用 Agent**？如果改成固定流程，会怎么设计？

---

## 下一章

**第 13 章 · Function Calling**

ReAct 循环的关键是「模型输出工具调用」。那么：**模型输出的到底是什么格式？API 是怎么把文本变成结构化的 `tool_calls` 的？**

第 4 章讲过「工具调用是生成出来的」，这一章讲工程细节：

- `tool_calls` 的完整结构和每个字段的作用
- 为什么 `tool_call_id` 必须配对
- `bind_tools` 到底做了什么
- 三种 `tool_choice` 模式的区别
- 并行工具调用（Parallel Tool Calling）
- 流式场景下的 tool_calls 增量（这是个真实的坑）

这些是「能让你的 Agent 真的跑起来」的细节。
