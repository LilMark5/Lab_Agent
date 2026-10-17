# 第 05 章 · Token、上下文窗口与成本

## 开篇：一个真实的账单

假设你的实验室预约系统上线了，每天 1000 次对话。你拿到月底账单：

```
输入 token： 3000 万    ¥ 30
输出 token：  300 万    ¥ 36
────────────────────────────
合计：                  ¥ 66 / 月
```

看起来还行？现在把规模放大：

```
10 万次对话/天 × 30 天 = 300 万次/月
按上面的单价：¥ 66 × 3000 = ¥ 198,000 / 月
```

**每月 20 万。** 这时候老板会来找你谈。

更重要的是：**大部分成本是可以省的，而且省下来不牺牲效果**。这一章讲的就是怎么算这笔账、怎么省。

---

## 一、先搞清楚计费模型

### 1.1 输入和输出分开计价，且输出更贵

这是很多人不知道的第一件事。

| | 输入（prompt） | 输出（completion） |
|---|---|---|
| 典型价格比 | 1x | **3-5x** |
| 原因 | 可以批处理、KV cache 复用 | 必须逐 token 生成，无法并行 |
| 优化难度 | 相对容易（裁剪、缓存） | 难（要模型少说点） |

**典型价格**（2025 年，仅供参考，面试时说「各家不同，要看官网」）：

| 模型 | 输入（每百万 token） | 输出（每百万 token） |
|---|---|---|
| GPT-4o | $2.5 | $10 |
| GPT-4o-mini | $0.15 | $0.6 |
| DeepSeek-V3 | ¥2（缓存命中 ¥0.5） | ¥8 |
| DeepSeek-R1 | ¥4 | ¥16 |
| 通义千问 Plus | ¥0.8 | ¥2 |

**关键观察**：

1. **输出是输入的 4 倍价**。所以「让模型少说废话」比「让 prompt 短一点」更省钱。
2. **小模型和大模型差 10-20 倍**。模型分级是最大的成本杠杆。
3. **推理模型（R1）比普通模型贵 2-4 倍**。

### 1.2 缓存：输入 token 的隐藏折扣

很多服务商提供 **前缀缓存**（Prefix Caching / Context Caching）：

> 如果你的 prompt 前 N 个 token 和上次请求**完全一致**，这部分的计费打折（通常 0.1-0.25 倍）。

**这直接改变了一个设计决策**：

```
❌ 错误：把动态内容放在 prompt 前面
   [当前时间 2025-01-17 10:30:00] [System Prompt 2000 token] [用户问题]
   → 每次请求前缀都不同，缓存永远不命中

✅ 正确：把静态内容放前面，动态内容放后面
   [System Prompt 2000 token] [静态知识] [当前时间] [用户问题]
   → 前 2000 token 每次都一样，缓存命中，省 75%
```

> ⚠️ **注意**：这个优化在本项目里**没做**，因为 System Prompt 较短（几百 token），收益有限。但如果你的 System Prompt 有几千 token（比如 RAG 塞了很多文档），这个优化的收益非常大。

### 1.3 上下文窗口：硬上限

| 模型 | 上下文窗口 | 约等于 |
|---|---|---|
| GPT-3.5 | 16k | 1.2 万字 |
| GPT-4o | 128k | 9.6 万字 |
| DeepSeek-V3 | 64k / 128k | 5-10 万字 |
| Claude 3.5 | 200k | 15 万字 |

**超了会怎样？**

```
Error: This model's maximum context length is 65536 tokens.
However, you requested 71234 tokens.
```

**直接失败，不是降级**。所以必须有保护。（第 19 章）

**重要认知：长窗口 ≠ 应该用满**

三个理由：

1. **贵**：输入按 token 计费，塞 10 万 token 就是 10 万的钱
2. **慢**：Attention 是 O(n²)，而且首字延迟随上下文长度增加
3. **效果差**：Lost in the Middle，塞太多反而找不准

> 💡 **面试话术**：「长上下文窗口是个陷阱。技术上能塞 128k，不代表应该塞。我的做法是：窗口是『安全垫』不是『目标容量』——用裁剪把实际使用控制在 4000-8000 token，留出余量，同时省钱、提速、提高准确率。」

---

## 二、算一笔账：Agent 一次对话花多少

### 2.1 拆解一次典型对话

假设用户问：「帮我预约明天下午2点的A301实验室」，Agent 走 3 轮：

| 轮次 | 输入 token | 输出 token | 说明 |
|---|---|---|---|
| 第 1 轮 | | | |
| - System Prompt | 300 | | 固定 |
| - 用户问题 | 30 | | |
| - 工具 schema（6 个） | 400 | | **每轮都要带上！** |
| - 输出 | | 50 | tool_calls |
| 第 2 轮 | | | |
| - 累计历史 | 780 | | 含上轮 |
| - 工具结果 | 200 | | 实验室列表 |
| - 工具 schema | 400 | | 又带一次 |
| - 输出 | | 60 | tool_calls |
| 第 3 轮 | | | |
| - 累计历史 | 1440 | | |
| - 工具结果 | 100 | | 预约成功 |
| - 工具 schema | 400 | | 又带一次 |
| - 输出 | | 80 | 最终回答 |
| **合计** | **3650** | **190** | |

**关键发现**：

1. **工具 schema 每轮都要重发**（1200 token 总共 400×3）——这是纯浪费，但无法避免（API 设计如此）。
2. **历史是累加的**——第 3 轮的输入包含了前两轮的全部。
3. **输出其实很少**（190 token）——Agent 的输出主要是 tool_calls，很短。

### 2.2 成本计算

按 DeepSeek-V3 价格（输入 ¥2/百万，输出 ¥8/百万）：

```
输入：3650 token × ¥2/1,000,000 = ¥0.0073
输出： 190 token × ¥8/1,000,000 = ¥0.0015
────────────────────────────────
单次对话：¥0.0088  ≈ 0.9 分钱
```

**看起来很便宜？** 算一下规模：

| 日活对话 | 月成本 |
|---|---|
| 1,000 次/天 | ¥264 |
| 10,000 次/天 | ¥2,640 |
| 100,000 次/天 | ¥26,400 |

**如果是 RAG 场景，成本会高得多**：

```
每次检索塞 3 段文档 × 800 token = 2400 token
→ 单轮输入就从 780 涨到 3180
→ 单次对话成本翻 3-4 倍
```

### 2.3 成本的隐形大头：失败重试

**这是最容易被忽略的**：

- 模型调错工具 → 回填错误 → 再调一次 → 多一轮
- 工具超时 → 重试 → 多一次工具执行 + 多一轮模型调用
- 模型陷入循环 → 烧到 `recursion_limit` 才停

**一次「卡住」的对话可能花 10 倍的钱**。

> 💡 **面试话术**：「成本控制不只是『用便宜模型』，更重要的是减少无效调用。我做了三件事：工具加超时和有限重试，防止卡死；工具失败回填错误让模型自纠，避免重复同样的错误；设 recursion_limit 兜底，防止无限循环。这三条本质上都是在降低『失败对话的成本倍数』。」

---

## 三、成本优化的八个手段（按 ROI 排序）

### 手段 1：模型分级路由（ROI 最高）

**思路**：不是所有请求都需要最强的模型。

```
用户："你好"                        → 小模型（甚至不用模型）
用户："帮我预约实验室"               → 中模型 + 工具
用户："解释一下细胞培养的注意事项"    → 大模型 + RAG
用户："对比三种实验方案的优劣"       → 推理模型
```

**实现方式**：

```python
def route_model(query: str) -> str:
    """根据任务复杂度选择模型。"""
    if is_simple_greeting(query):
        return None                    # 不调模型，直接回
    if needs_tool(query):
        return "deepseek-chat"         # 中模型，快且便宜
    if needs_reasoning(query):
        return "deepseek-reasoner"     # 推理模型
    return "deepseek-chat"
```

**也可以用小模型做路由**：用一个极便宜的模型判断复杂度，再分发。路由本身花几分钱，但能省下几毛钱。

> ⚠️ **项目现状**：本项目**没有做**模型分级，所有请求用同一个 `LLM_MODEL`。这是可以改进的点。但项目做了**裁判模型分离**（`JUDGE_MODEL`）——评测时用更强的模型，主链路用便宜的模型。这其实是模型分级思想的一个应用。

### 手段 2：裁剪上下文（ROI 极高）

见第 19 章。核心是：**不要把所有历史都塞进去**。

```
全量历史：第 10 轮的输入 = 前 9 轮全部 ≈ 8000 token
裁剪后：  只保留最近 3 轮 + 早期摘要 ≈ 2500 token
省 70%
```

### 手段 3：缩短工具 schema

工具 schema 每轮都要发，是纯固定成本。

```
优化前：6 个工具，每个 70 token = 420 token/轮
优化后：合并成 3 个工具，每个 90 token = 270 token/轮
省 35%
```

**怎么缩短？**

- 合并功能相近的工具
- docstring 精炼（但要保留关键信息，见第 34 章的权衡）
- 只注入当前场景需要的工具

> ⚠️ **权衡**：docstring 写短了省钱，但模型调用准确率会下降。**不要为了省 token 牺牲工具描述的关键信息**——一次错误的工具调用要重来一轮，比省下的 token 贵得多。

### 手段 4：限制输出长度

```
System Prompt 加："回答控制在 100 字以内，分点说明"
```

输出是输入的 4 倍价，这个优化很划算。

**但要小心**：限制太死会影响质量，而且推理模型要留思考预算。

### 手段 5：语义缓存

**思路**：相似的问题直接返回缓存答案。

```python
# 伪代码
embedding = embed(query)
similar = vector_search(embedding, threshold=0.95)
if similar:
    return cached_answer
```

**风险**：

- 缓存了错误的答案，会一直错下去
- 时效性数据（「明天有哪些空实验室」）不能缓存太久
- 缓存命中率不高的话，反而增加延迟（多一次 embedding + 检索）

**适合缓存的**：规章制度问答（稳定、高频）
**不适合缓存的**：实时查询、涉及用户个人数据的

> ⚠️ **项目现状**：项目里 `REDIS_URL` 是空的，缓存**没启用**。代码里检索有缓存逻辑，但未生效。

### 手段 6：批量处理

如果你有大量离线任务（比如批量评测、批量文档处理），用服务商的 Batch API，通常便宜 50%。

**限制**：通常不保证实时（24 小时内返回）。

### 手段 7：前缀缓存（前面讲过）

把静态内容（System Prompt、工具定义）放在 prompt 最前面，动态内容放后面。

**收益**：静态部分计费降到 0.1-0.25 倍。

### 手段 8：监控与告警

**没有监控的成本优化是盲目的**。至少要能回答：

- 单个对话的平均成本？
- P95 成本是多少（异常对话有多贵）？
- 哪个用户/哪个功能最烧钱？
- token 消耗的趋势？

**实现方式**：

```python
@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
    model: str
    thread_id: str
    user_id: int

# 每次调用后记录
usage = response.response_metadata.get("token_usage")
logger.info("llm_usage", extra={**usage, "thread_id": tid, "user_id": uid})
```

---

## 四、最小可运行骨架：成本计算器

```python
"""
cost_calculator.py —— Agent 成本计算与优化对比
运行：python cost_calculator.py
演示：算清一次对话的成本，对比八种优化手段的收益
"""

# ── 1. 模型价格表（示意，实际以官网为准）────────────────

MODELS = {
    "deepseek-chat":      {"in": 2.0,  "out": 8.0,  "window": 65536},
    "deepseek-reasoner":  {"in": 4.0,  "out": 16.0, "window": 65536},
    "gpt-4o-mini":        {"in": 1.1,  "out": 4.4,  "window": 128000},
    "gpt-4o":             {"in": 17.5, "out": 70.0, "window": 128000},
    "qwen-plus":          {"in": 0.8,  "out": 2.0,  "window": 131072},
}
# 单位：元 / 每百万 token

def calc_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = MODELS[model]
    return (prompt_tokens * p["in"] + completion_tokens * p["out"]) / 1_000_000

# ── 2. 模拟一次 Agent 对话的 token 累积 ──────────────────

def simulate_conversation(
    turns: int = 3,
    system_prompt: int = 300,
    tools_schema: int = 400,
    retrieved_docs: int = 0,
    trim: bool = False,
    keep_turns: int = 3,
) -> tuple:
    """返回 (总输入 token, 总输出 token, 每轮明细)"""
    total_in = total_out = 0
    history = 0
    details = []

    for t in range(1, turns + 1):
        user_msg = 30
        tool_result = 200 if t > 1 else 0

        if trim and t > keep_turns:
            # 裁剪：只保留最近 keep_turns 轮
            history = system_prompt + keep_turns * 300
        else:
            history += user_msg + tool_result

        prompt = system_prompt + tools_schema + history + retrieved_docs
        completion = 50 if t < turns else 80

        total_in += prompt
        total_out += completion
        history += completion
        details.append((t, prompt, completion))

    return total_in, total_out, details

# ── 3. 场景对比 ──────────────────────────────────────────

def scenario_basic():
    print("【场景 1】普通 Agent 对话（3 轮，无 RAG，无裁剪）")
    tin, tout, details = simulate_conversation(turns=3)
    cost = calc_cost("deepseek-chat", tin, tout)
    print(f"  轮次明细 (轮, 输入, 输出): {details}")
    print(f"  合计: 输入 {tin} / 输出 {tout} → ¥{cost:.5f}\n")
    return cost

def scenario_rag():
    print("【场景 2】带 RAG（每轮塞 2400 token 文档）")
    tin, tout, details = simulate_conversation(turns=3, retrieved_docs=2400)
    cost = calc_cost("deepseek-chat", tin, tout)
    print(f"  合计: 输入 {tin} / 输出 {tout} → ¥{cost:.5f}")
    print(f"  ⚠️ 比无 RAG 贵 {cost/scenario_basic_cache:.1f} 倍\n" if scenario_basic_cache else "")
    return cost

def scenario_long():
    print("【场景 3】长对话 20 轮，无裁剪")
    tin, tout, details = simulate_conversation(turns=20, retrieved_docs=2400)
    cost = calc_cost("deepseek-chat", tin, tout)
    print(f"  合计: 输入 {tin} / 输出 {tout} → ¥{cost:.5f}")
    print(f"  前 3 轮输入: {details[0][1]}，第 20 轮输入: {details[-1][1]}")
    print(f"  ⚠️ 输入呈二次增长（历史累加）\n")
    return cost, tin

def scenario_long_trimmed():
    print("【场景 4】长对话 20 轮，开启裁剪（保留 3 轮）")
    tin, tout, details = simulate_conversation(
        turns=20, retrieved_docs=2400, trim=True, keep_turns=3
    )
    cost = calc_cost("deepseek-chat", tin, tot) if False else calc_cost("deepseek-chat", tin, tout)
    print(f"  合计: 输入 {tin} / 输出 {tout} → ¥{cost:.5f}")
    print(f"  ✅ 裁剪后输入稳定在 {details[-1][1]} 左右\n")
    return cost

def scenario_model_routing():
    print("【场景 5】模型分级：简单问题用便宜模型")
    # 假设 1000 次对话中：300 次简单、500 次工具、200 次复杂
    simple = calc_cost("qwen-plus", 350, 100) * 300
    tool   = calc_cost("deepseek-chat", 1200, 150) * 500
    complex_ = calc_cost("deepseek-reasoner", 3000, 800) * 200
    total = simple + tool + complex_
    print(f"  简单(300次): ¥{simple:.3f}")
    print(f"  工具(500次): ¥{tool:.3f}")
    print(f"  复杂(200次): ¥{complex_:.3f}")
    print(f"  合计: ¥{total:.3f}")

    # 对比：全部用 deepseek-chat
    all_one = calc_cost("deepseek-chat", 1500, 400) * 1000
    print(f"  对比全用中模型: ¥{all_one:.3f}")
    print(f"  {'✅ 省' if total < all_one else '⚠️ 反而贵'} {abs(1-total/all_one)*100:.1f}%\n")

def scenario_retry_waste():
    print("【场景 6】失败重试的隐形成本")
    base = calc_cost("deepseek-chat", 1200, 150)
    print(f"  正常一次对话: ¥{base:.6f}")
    for extra in [1, 3, 10]:
        print(f"  多走 {extra} 轮无效循环: ¥{base*(1+extra):.6f}  ({1+extra}x)")
    print("\n  ⚠️ 一次卡住的对话可能花 10 倍的钱")
    print("  ✅ 对策：工具超时(30s) + 有限重试(1次) + recursion_limit(10)")
    print("         工具失败回填错误让模型自纠，而不是重复同样错误\n")

def scenario_scale():
    print("【场景 7】规模化后的月成本")
    per_conv = calc_cost("deepseek-chat", 3650, 190)
    print(f"  单次对话: ¥{per_conv:.6f}")
    for daily in [1000, 10000, 100000]:
        monthly = per_conv * daily * 30
        print(f"  {daily:>7} 次/天 → ¥{monthly:>10,.0f} / 月")
    print()

def scenario_optimization_summary():
    print("【场景 8】八种优化手段的收益对比（示意）")
    base = 100.0
    opts = [
        ("模型分级路由",      -45),
        ("上下文裁剪",        -35),
        ("缩短工具 schema",   -8),
        ("限制输出长度",      -12),
        ("前缀缓存",          -20),
        ("语义缓存",          -25),
        ("批量处理(离线)",    -50),
        ("减少无效重试",      -30),
    ]
    print(f"  {'手段':<20}{'成本降幅':>10}   说明")
    print("  " + "-" * 62)
    notes = {
        "模型分级路由": "最大杠杆，简单任务用小模型",
        "上下文裁剪": "长对话必做",
        "缩短工具 schema": "小心别牺牲描述质量",
        "限制输出长度": "输出是输入 4 倍价，很划算",
        "前缀缓存": "静态内容放前面",
        "语义缓存": "只适合稳定的知识问答",
        "批量处理(离线)": "评测/批量任务，非实时",
        "减少无效重试": "降低'失败对话'的倍数",
    }
    for name, delta in opts:
        print(f"  {name:<20}{delta:>9}%   {notes[name]}")
    print("\n  ⚠️ 注意：这些手段不能简单相加（有重叠）")
    print("  ✅ 实际组合（路由+裁剪+限制输出+减少重试）通常能省 60-70%")

# ── 主函数 ───────────────────────────────────────────────

scenario_basic_cache = None

if __name__ == "__main__":
    print("=" * 66)
    print("Agent 成本计算器")
    print("=" * 66 + "\n")
    scenario_basic_cache = scenario_basic()
    scenario_rag()
    scenario_long()
    scenario_long_trimmed()
    scenario_model_routing()
    scenario_retry_waste()
    scenario_scale()
    scenario_optimization_summary()
```

**跑一遍你会看到**：

1. RAG 让单次成本翻好几倍
2. 长对话的输入是**二次增长**（历史累加）
3. 裁剪后输入稳定下来
4. 模型分级是最大杠杆
5. 失败重试的倍数效应
6. 规模化后的月成本

---

## 五、上下文预算的规划方法

### 5.1 一个实用的分配公式

假设模型窗口是 64k，你怎么分配？

```
总预算 64k，但实际目标控制在 8-16k（留 4 倍余量）

├─ System Prompt        500 token   (固定)
├─ 工具 schema          400 token   (固定，每轮重复)
├─ 检索文档            2400 token   (3 段 × 800)
├─ 对话历史            最多 4000    (滑动窗口)
├─ 当前用户输入         200 token
└─ 留给模型输出         1000 token
─────────────────────────────────
合计                   8500 token
```

**项目里的实现**：`MAX_CONTEXT_TOKENS = 4000`（默认值）。

这个 4000 是**历史部分的预算**，不包括 System Prompt 和当前输入。计算方式：

```python
history = _trim_messages(state["messages"], settings.MAX_CONTEXT_TOKENS)
response = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), *history])
```

### 5.2 怎么定这个数字

**三步法**：

**第一步：测出 P95 的正常用量**

跑一批真实对话，统计 token 分布：

```python
# 伪代码
usages = [measure(conv) for conv in real_conversations]
p50 = percentile(usages, 50)
p95 = percentile(usages, 95)
p99 = percentile(usages, 99)
```

**第二步：预算设为 P95 的 1.2 倍**

这样 95% 的对话不会被裁剪，5% 的长对话会被裁剪但能正常工作。

**第三步：留出输出空间**

```
预算 = 模型窗口 × 0.7 - 预期输出长度
```

0.7 是为了留 30% 余量给：工具结果的意外膨胀、System Prompt 变长、模型输出超预期。

### 5.3 RAG 文档的 token 预算

这是最需要精细控制的部分。

```
每轮检索回来 3 段文档，每段多长合适？
```

| 文档长度 | 优点 | 缺点 |
|---|---|---|
| 200 token（太小） | 省 | 语义不完整，可能答不准 |
| 800 token（推荐） | 平衡 | - |
| 2000 token（太大） | 上下文完整 | 贵，且 Lost in the Middle |

**项目的做法**：切块时用递归切块，块大小 500 字符左右，重叠 50 字符；检索时命中块后**扩展到父上下文**（第 23、29 章详解）。

**为什么要父上下文？**

因为切块会把完整段落切碎。命中一个 200 token 的碎片，模型看到的可能是半句话。扩展回父块（比如 800 token 的完整段落），语义才完整。

**代价**：token 变多。所以项目里是**按需扩展**——只对最终进入 top3 的块扩展。

---

## 六、项目里的成本控制现状（诚实版）

### 6.1 已做的

| 措施 | 位置 | 效果 |
|---|---|---|
| 上下文裁剪 | `agent_service.py:_trim_messages` | 长对话不爆、省 token |
| 工具超时 | `TOOL_TIMEOUT_SECONDS=30` | 防卡死烧钱 |
| 有限重试 | `TOOL_MAX_RETRIES=1` | 防无限重试 |
| `recursion_limit=10` | `_make_config` | 防无限循环 |
| 裁判模型分离 | `JUDGE_MODEL` | 评测时才用贵模型 |
| `temperature=0` | `build_agent` | 减少无效重试 |

### 6.2 没做的（诚实列出，面试反而加分）

| 未做 | 原因 | 如果做会怎样 |
|---|---|---|
| 模型分级路由 | 请求量小，收益不明显 | 省 40%+ |
| 语义缓存 | Redis 未启用 | 高频问答省 25% |
| 前缀缓存优化 | System Prompt 较短 | 省 20% |
| token 用量监控 | 没做埋点 | 无法定位异常 |
| 批量 API | 评测是交互式的 | 评测省 50% |

> 💡 **面试话术**：「成本控制我做了几件事：上下文裁剪避免长对话 token 爆炸、工具超时和有限重试防止卡死、recursion_limit 防止无限循环、裁判模型和被测模型分离（评测才用贵的）。
>
> 但有几件事我没做，说实话一是请求量不大收益不明显，二是优先级：模型分级路由和语义缓存收益很大，但需要先把 token 监控做起来——没有监控的优化是盲目的。如果要继续做，我的顺序是：先埋点监控 → 再模型分级 → 再语义缓存。」

**这种「知道自己没做什么、知道为什么没做、知道如果要做先做什么」的回答，比「我全都做了」可信得多。**

---

## 本章速记卡

1. **输出 token 是输入的 3-5 倍价**，让模型少说话比缩短 prompt 更省钱。
2. **工具 schema 每轮都要重发**，是纯固定成本，合并工具能省。
3. **历史是累加的**，长对话输入呈二次增长 → 必须裁剪。
4. **失败重试是最隐蔽的成本大头**，一次卡住可能花 10 倍。
5. **长窗口是安全垫不是目标容量**，实际控制在 8-16k 更好（省、快、准）。
6. **前缀缓存**：静态内容放 prompt 前面，能打 0.1-0.25 折。
7. **模型分级是最大杠杆**，简单任务用小模型能省 40%+。
8. **没有监控的成本优化是盲目的**，先埋点再优化。
9. **RAG 每轮塞 2400 token**，是成本大头，要控制段数和长度。
10. **本项目**：做了裁剪/超时/重试/recursion_limit/裁判分离；没做模型分级/语义缓存/前缀缓存/监控。

---

## 面试问答：成本与上下文

### Q1：「一次对话大概花多少钱？你怎么优化的？」

**满分答法**：

> 我算过一次典型的三轮工具调用对话：输入约 3650 token，输出约 190 token。按 DeepSeek 的价格，单次大概不到一分钱。
>
> 但如果是 RAG 场景，每轮要塞 2400 token 的检索文档，单次成本会翻好几倍。如果对话到 20 轮又不裁剪，输入是累加的，第 20 轮的输入可能是第 1 轮的十几倍。
>
> 我做了这些优化：
>
> 一是上下文裁剪，按 token 预算保留最近几轮，早期历史摘要压缩，这样输入不会随轮次无限增长。
>
> 二是工具加超时和有限重试，防止一个卡死的工具烧掉整轮调用。
>
> 三是设 recursion_limit 兜底，防止模型陷入循环。
>
> 四是裁判模型和被测模型分离——评测时才用贵的模型，主链路用便宜的。
>
> 没做的有模型分级路由和语义缓存，主要因为请求量不大收益不明显。如果做的话，我的顺序是先做 token 监控埋点，再分级，再缓存——没有监控的优化是盲目的。

---

### Q2：「上下文窗口怎么规划？你怎么定 token 预算？」

**满分答法**：

> 三步法。
>
> 第一步，跑一批真实对话统计 token 分布的 P50、P95、P99。
>
> 第二步，预算设为 P95 的 1.2 倍——这样 95% 的对话完全不裁剪，5% 的长对话会被裁剪但仍然能正常工作。
>
> 第三步，留出输出空间。公式大概是：预算 = 模型窗口 × 0.7 - 预期输出长度。留 30% 余量是为了应对工具结果意外膨胀、System Prompt 变长、模型输出超预期这些情况。
>
> 我项目里 MAX_CONTEXT_TOKENS 默认 4000，这是历史部分的预算，不含 System Prompt 和当前输入。
>
> 需要说明的是：**长窗口是安全垫，不是目标容量**。技术上能塞 128k，不代表应该塞。塞满有三个问题：贵、慢（Attention 是 O(n²)）、而且效果反而差（Lost in the Middle，塞太多反而找不准）。

---

### Q3：「怎么估算 token 数？用 tiktoken 吗？」

**满分答法**：

> 理想方案是用官方 tokenizer，精确。但我没用，有两个实际原因：
>
> 一是我们用的是 DeepSeek，它的 tokenizer 和 OpenAI 不完全一致，用 tiktoken 估算会有偏差；二是 tiktoken 要下载词表文件，国内网络环境下经常失败，会拖慢服务启动。
>
> 所以我用了字符数除以 4 的粗略估算。这个估算对中文是**偏高**的——中文一个字大约 1-2 个 token，除以 4 会多算。
>
> 我刻意选择了偏高估：宁可多剪一点，也不要超预算。因为超预算是整个请求失败（API 直接报 context_length_exceeded），而多剪一点只是丢失一些早期历史，用户体验的损失小得多。这是个明确的取舍。
>
> 另外我会把工具调用的参数也算进去——`tool_calls` 里的 args 也是 token，只算 content 会低估。

---

### Q4：「RAG 塞那么多文档，成本怎么控制？」

**满分答法**：

> 三个层面控制。
>
> **段数**：不塞十段，只留最相关的三段。一是省 token，二是对抗 Lost in the Middle——塞太多模型反而找不到关键那段。
>
> **段长**：切块时控制在 500 字符左右，检索命中后再扩展到父上下文（比如 800 token 的完整段落）。为什么不一开始就切大块？因为小块检索更精准，大块给模型看更完整——这是「检索单元」和「生成单元」分离的思路。
>
> **按需扩展**：只对最终进入 top3 的块做父上下文扩展，不是对所有召回的块都扩展。
>
> 另外如果能做的话，把检索结果做缓存——规章制度这类稳定知识，同一个问题问十次没必要检索十次。我项目里 Redis 没启用，所以这块没做。

---

### Q5：「如果发现某天成本暴涨，你怎么排查？」

**满分答法**（这题考运维思维）：

> 首先得有埋点——每次模型调用记录 prompt_tokens、completion_tokens、model、thread_id、user_id。没有这个数据就没法排查，所以我一直强调监控要先做。
>
> 有了数据，按这几个维度切：
>
> **按用户看**：是不是某个用户在刷？可能是脚本攻击或者异常使用。
>
> **按 thread 看**：是不是某个会话异常？可能是模型陷入了循环，一直调工具。
>
> **按时间看**：是不是某个时段集中？可能是批量任务或者重试风暴。
>
> **按输入输出比看**：如果输出占比异常高，可能是模型在生成超长回答；如果输入占比高，可能是上下文没裁剪好或者工具结果太大。
>
> 最常见的三个原因：一是模型陷入工具调用循环（靠 recursion_limit 和监控发现）；二是某个工具返回了巨大的结果（比如没加 limit 查了全表）；三是重试风暴（下游服务抖动导致大量重试）。
>
> 我项目里现在缺的就是这个埋点，所以如果要上生产，这是优先级最高的一项。

---

### Q6：「模型分级路由怎么做？」

**满分答法**：

> 核心思路是：不是所有请求都需要最强的模型。
>
> 最简单的是规则路由：打招呼、闲聊直接不调模型或者用极小的模型；需要调工具的用中等模型（快且便宜）；需要深度推理的用推理模型。
>
> 更灵活的是用小模型做router：发一个极便宜的模型判断「这个问题的复杂度」，再分发到对应模型。路由本身只花几分钱，但能省下几毛钱。
>
> 我的项目里没做分级，但做了一个类似思想的实践：**裁判模型和被测模型分离**。主链路用便宜的对话模型，评测判官用更强的模型。因为判断「答案是否忠于原文」这个任务需要仔细比对，值得多花 token，而主链路的工具调用不需要。
>
> 如果要做完整分级，我会先统计真实请求的复杂度分布，确定分几档、每档用什么模型，然后用评测集验证「降级到小模型后效果掉了多少」，在成本和效果之间找平衡点。不能只看成本——效果掉了 20% 省 50% 的钱，通常是亏的。

---

## 常见坑

### 坑 1：只看输入成本，忽略输出

输出是输入的 4 倍价。让模型啰嗦，账单会很惊喜。

### 坑 2：以为「长窗口 = 可以不用裁剪」

技术上能塞不等于应该塞。贵、慢、效果还差。

### 坑 3：把动态内容放在 prompt 前面

前缀缓存永远不命中。System Prompt、工具定义这些静态内容应该放最前。

### 坑 4：为了省 token 把工具描述写得太短

一次错误的工具调用要重来一轮，比省下的 token 贵得多。

### 坑 5：没设 recursion_limit

一晚上烧掉几百块。这是最贵的坑。

### 坑 6：没监控就谈优化

不知道钱花在哪，所有优化都是拍脑袋。

### 坑 7：推理模型设小 max_tokens

思考 token 吃光预算，答案被截断，还以为是模型问题。

### 坑 8：缓存了不该缓存的

实时数据（「明天有哪些空实验室」）缓存了会返回错误答案。

---

## 动手练习

### 练习 1（必做）

跑通第五节的 `cost_calculator.py`，记录这几个数字：

1. 单次 RAG 对话的成本
2. 20 轮长对话，裁剪和不裁剪的成本差
3. 你的场景（假设日活 X）的月成本

### 练习 2

给项目加一个 token 埋点：

```python
# 在 agent_node 里，模型调用后
usage = response.response_metadata.get("token_usage", {})
logger.info(
    "llm_usage",
    extra={
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "thread_id": thread_id,
        "user_id": current_user.id,
    }
)
```

跑几次对话，看看真实的 token 数和你估算的差多少。

### 练习 3

打开 `agent_service.py` 的 `_trim_messages`，把 `MAX_CONTEXT_TOKENS` 分别设成：

- 500（很激进）
- 4000（默认）
- 50000（几乎不裁剪）

问同一个多轮问题，观察回答质量的差异。

### 练习 4（进阶）

设计一个模型分级方案：

1. 列出你项目里的 5 类典型请求
2. 给每类指定模型和理由
3. 估算能省多少

---

## 下一章

**第 06 章 · Prompt 工程**

你现在知道 token 很贵了，那么**怎么用最少的 token 让模型做对事**？

Prompt 工程是 Agent 开发性价比最高的技能——不需要改代码，改几句话就能让模型行为完全不同。

但网上的 Prompt 教程大多是「魔法词」合集（"让我们一步步思考"、"你是 XX 专家"）。这一章不教魔法词，教**原则**：怎么写 System Prompt、怎么写工具描述、怎么写 few-shot、怎么迭代验证。

还有一个重要话题：**Prompt 也是代码，需要版本管理和测试**。
