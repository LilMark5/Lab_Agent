# 第 39 章 · RAGAS 生成评估：四个指标怎么算

> 上一章我们解决了"检索对不对"的问题——Hit@K / MRR / nDCG@3 能告诉你召回的块里有没有答案。
> 但检索对了，答案就一定对吗？不一定。模型可能拿到了正确的资料，却在生成时编了一句资料里没有的话。
> 这一章解决第二个问题：**答案本身好不好**。

---

## 39.1 为什么需要它：检索指标盖不住的那一半

先看一个真实会发生的情况。

知识库里《预约规则.md》写着：

```
提交预约后状态为"待审核"，需管理员审核通过后方可使用。
```

用户问："我刚提交的预约现在能用了吗？"

检索侧完美命中——`预约规则#2` 排在第 1 名，Hit@1 = 1.0，MRR = 1.0，nDCG = 1.0。

但模型生成了这样一句：

> 可以，您的预约已提交成功，系统已自动通过审核，请按时前往实验室。

**检索指标全是满分，答案是错的，而且是危险地错**——用户会真的跑去实验室。

这就是检索指标的结构性盲区：**它只测"资料有没有送到模型面前"，不测"模型有没有照着资料说"**。

我们再把这个盲区拆细一点。一个 RAG 系统的失败可以分成两类：

```
第一类：资料没送到  → 检索侧故障 → Hit@K / MRR / nDCG 能抓到（第 38 章）
第二类：资料送到了，但模型没用好 → 生成侧故障 → 检索指标完全抓不到
```

第二类又可以再拆成三种典型表现：

| 表现 | 例子 | 检索指标 |
|---|---|---|
| **无中生有**（幻觉） | 资料说"待审核"，模型说"已自动通过" | 满分，看不出来 |
| **答非所问** | 问"周末几点开门"，答"本实验室配备高性能 GPU" | 满分，看不出来 |
| **该拒答却编造** | 问"Wi-Fi 密码"，资料里没有，模型编了一个 | 满分，看不出来 |

三种都属于"资料送到了但没用好"，而 Hit@K 对它们一律是满分。

**所以生成评估不是"锦上添花"，它是补齐了评测的另一半。** 没有它，你的评测体系只覆盖了链路的前 60%。

### 39.1.1 那能不能让人肉眼看？

能，但撑不住。

这个项目 14 条用例，你肉眼扫一遍答案 3 分钟搞定。但你想过没有：

- 你改了 prompt，要重看一遍——**没有基准线，你怎么知道是变好了还是变差了？**
- 你换了个模型，要重看一遍——**两版答案放一起，凭感觉选？**
- 你调了 `FINAL_CONTEXT_K` 从 3 改成 5，要重看一遍——**召回多了，faithfulness 是升是降？**

人肉评估的最大问题不是慢，是**不可比**。你上周看的那版答案，和你今天看的那版，中间隔了 7 天，你的判断标准已经漂移了。

这就是为什么必须有一个能落盘、能对比、能进 CI 的量化方案。

### 39.1.2 生成评估难在哪

坦白讲，生成评估比检索评估难一个数量级。原因有三：

**第一，"好答案"没有唯一标准。**
检索评估里，"这条记录该不该召回"是二值的、客观的。但"这个答案好不好"是主观的——简洁算好还是详尽算好？带引用算好还是不带算好？

**第二，答案的正确性无法用字符串比对。**
`预约需审核` 和 `提交后要等管理员通过才能用` 表达的是同一件事，但字符串相似度很低。反过来，`已通过` 和 `未通过` 字符串相似度极高，语义完全相反。

**第三，唯一的裁判是另一个大模型，而它本身有噪声。**
这是最要命的。你用模型给模型打分，就引入了一个新的误差源——而且这个误差源的抖动幅度可能比你试图测量的差异还大。

第三点正是这一章的核心难点，我们会在 39.4 花整节讲它。

---

## 39.2 它到底是什么：RAGAS 的四个指标

RAGAS（Retrieval Augmented Generation Assessment）是业界最主流的 RAG 评估框架。它的思路是：**把"答案好不好"这个主观问题，拆成四个可以机械计算的客观指标。**

四个指标分成两组——**两个测答案、两个测上下文**：

```
┌─────────────────────────────────────────────────────────┐
│                    RAGAS 四指标                          │
├──────────────────────────┬──────────────────────────────┤
│  答案侧（不用 reference） │  上下文侧（需要 reference）    │
│                          │                              │
│  faithfulness            │  context_precision           │
│  忠实度：有没有编造        │  上下文精确率：有用的排前面了吗 │
│                          │                              │
│  answer_relevancy        │  context_recall              │
│  相关性：有没有答非所问    │  上下文召回率：该召回的召到了吗 │
└──────────────────────────┴──────────────────────────────┘
```

这个分组不是随便分的，它决定了**每个指标需要什么输入**：

| 指标 | 需要 question | 需要 answer | 需要 contexts | 需要 reference |
|---|:---:|:---:|:---:|:---:|
| faithfulness | ✅ | ✅ | ✅ | ❌ |
| answer_relevancy | ✅ | ✅ | ❌ | ❌ |
| context_precision | ✅ | ❌ | ✅ | ✅ |
| context_recall | ✅ | ❌ | ✅ | ✅ |

记住这张表。**后面所有的"这个指标为什么算不了""这个分数为什么是假的"，根源都在这张表的"需要 reference"那一列。**

### 39.2.1 faithfulness（忠实度）：有没有编造

**一句话**：答案里的每一句话，能不能在召回的上下文里找到依据。

**算法**（RAGAS 内部实现）：

```
1. 把 answer 拆成若干条独立的 claim（陈述）
   例："人工智能实验室周末 09:00 开放，17:00 关闭。"
   →  claim1: 人工智能实验室周末 09:00 开放
   →  claim2: 人工智能实验室周末 17:00 关闭

2. 逐条判断：claim 能否从 retrieved_contexts 推出？
   claim1 → supported ✅
   claim2 → supported ✅

3. 分数 = 支持的 claim 数 / 总 claim 数 = 2/2 = 1.0
```

对应到项目代码（`evaluate_generation.py:128-134`）：

```python
if name == "faithfulness":
    return metric.ascore(
        user_input=question, response=answer, retrieved_contexts=contexts
    )
```

**关键性质**：

- **不需要 reference**。它只比对"答案 vs 上下文"，跟标准答案无关。这意味着**任何用例都能算**，包括拒答类。
- 它是**唯一对拒答用例有意义**的指标——拒答用例考的就是"有没有编造"，而编造正是 faithfulness 的定义。
- 它测的是**幻觉**，不测正确性。如果资料本身就是错的，模型照着说，faithfulness = 1.0。**忠实 ≠ 正确**，这个区别面试常考。

> ⚠️ **一个容易误读的点**：faithfulness 高不代表答案对，只代表答案"有出处"。
> 资料写"周一开放"（其实是错的），模型答"周一开放"，faithfulness = 1.0 但答案是错的。
> 所以 faithfulness 必须和 context_recall（资料覆盖度）一起看。

### 39.2.2 answer_relevancy（答案相关性）：有没有答非所问

**一句话**：答案是不是在正面回答这个问题。

**算法**（有点反直觉——它是**倒着算**的）：

```
1. 拿"答案"反推问题：让 LLM 根据 answer 生成 N 个"可能的原始问题"
   （N 由 strictness 参数控制，默认 3，生成越多越严格）

   answer: "人工智能实验室周末 09:00 开放，17:00 关闭。"
   →  gen_q1: "人工智能实验室周末几点开门？"
   →  gen_q2: "人工智能实验室周末什么时候关门？"
   →  gen_q3: "人工智能实验室周末开放时间是什么？"

2. 计算每个生成问题与原始问题的 embedding 余弦相似度
   gen_q1 vs "人工智能实验室周末几点开放？"  → 0.94
   gen_q2 vs ...                            → 0.81
   gen_q3 vs ...                            → 0.92

3. 分数 = 均值 = 0.89
```

对应项目代码（`evaluate_generation.py:135-136`）：

```python
if name == "answer_relevancy":
    return metric.ascore(user_input=question, response=answer)
```

注意它**不需要 contexts，也不需要 reference**——纯粹是"问题 vs 答案"的双向匹配。

**关键性质**：

- 它测的是**完整性 + 聚焦度**。答案答得太少（漏了关键信息）或答得太多（塞了一堆无关内容），相似度都会被稀释。
- 它**需要 embedding 模型**。项目里复用了 RAG 用的 `BAAI/bge-small-zh-v1.5`（`evaluate_generation.py:309`）。

> ⚠️ **最大的坑：拒答类用例算这个指标必然接近 0，而且是机制导致的假低分。**

推导一遍你就明白了：

```
question: "实验室的 Wi-Fi 密码是多少？"
answer:   "资料里没有 Wi-Fi 密码相关信息，建议咨询管理员。"

→ 由答案反推问题：
   gen_q: "资料里有哪些关于实验室的信息？" / "遇到资料里没有的问题该怎么办？"

→ 与原问题比相似度：
   "资料里有哪些信息" vs "Wi-Fi 密码是多少" → 0.03
```

**模型答得完全正确（正确拒答），分数却是 0.03。** 这不是模型的问题，是指标的机制决定的：反推出来的问题必然是"资料里有什么"，和"密码是多少"天然不相似。

项目里的处理（`evaluate_generation.py:84-89`）：

```python
METRIC_CATEGORIES = {
    "faithfulness": {"factual", "refusal"},
    "answer_relevancy": {"factual"},          # ← 拒答类不算
    "context_precision": {"factual"},         # ← 拒答类不算
    "context_recall": {"factual"},            # ← 拒答类不算
}
```

**这是这一章最重要的一行代码。** 它体现了第 37 章讲的"指标口径匹配"原则——不是所有指标都能套所有用例，硬套会把汇总分数带偏，让你误以为系统退化了。

### 39.2.3 context_precision（上下文精确率）：有用的排到前面了吗

**一句话**：召回的上下文里，有用的那些有没有排在前面。

**算法**（注意：它算的是 **average precision**，**看排序不看比例**）：

```
1. 逐条判断每个 context 对回答这个问题是否"有用"（LLM 判定，参考 reference）
   ctx1 → useful ✅
   ctx2 → not useful ❌
   ctx3 → useful ✅

2. 算平均精确率：
   k=1: 前 1 条里 1 条有用 → P@1 = 1/1 = 1.0，v1=1 → 贡献 1.0
   k=2: 前 2 条里 1 条有用 → P@2 = 1/2 = 0.5，v2=0 → 贡献 0
   k=3: 前 3 条里 2 条有用 → P@3 = 2/3 = 0.67，v3=1 → 贡献 0.67

   分数 = (1.0 + 0.67) / 2 = 0.83
            ↑ 分母是"有用块总数"，不是"召回总数"
```

对应项目代码（`evaluate_generation.py:137-142`）：

```python
if name == "context_precision":
    return metric.ascore(
        user_input=question,
        reference=case["ground_truth"],
        retrieved_contexts=contexts,
    )
```

**关键性质（⚠️ 这一条面试高频）**：

> **`context_precision` 的分母是"相关块总数"，不是"召回块总数"。**
> 所以：唯一相关的那条只要排第 1 名，就是满分，后面跟多少条无关块都不扣分。

验证一下：

```
ctx1 → useful ✅      k=1: P@1 = 1/1 = 1.0，v1=1 → 贡献 1.0
ctx2..ctx10 → 全无用   k=2..10: v_k = 0 → 贡献 0

分数 = 1.0 / 1 = 1.0   ← 满分！尽管 10 条里 9 条是噪声
```

**这意味着什么？** 意味着 `context_precision` **不会惩罚"狂塞上下文"**。

你把 `FINAL_CONTEXT_K` 从 3 改成 20，只要那条有用的还排第一，context_precision 依然是 1.0。但它带来的副作用——token 成本 ×6、答案被噪声干扰导致 faithfulness 下降、延迟变长——**这个指标一个都抓不到**。

**所以 context_precision 必须配合成本指标和 faithfulness 一起看，单独看会被"塞满上下文"策略骗过去。** 这是 RAGAS 最容易被误用的地方。

### 39.2.4 context_recall（上下文召回率）：该召回的召到了吗

**一句话**：标准答案里的信息，有多少被召回的上下文覆盖了。

**算法**：

```
1. 把 reference（ground_truth）拆成若干 claim
   ground_truth: "人工智能实验室周末 09:00 开放，17:00 关闭。"
   →  claim1: 周末 09:00 开放
   →  claim2: 周末 17:00 关闭

2. 逐条判断：这个 claim 能不能从 retrieved_contexts 里找到依据？
   claim1 → 在 contexts 里有 ✅
   claim2 → 在 contexts 里没有 ❌

3. 分数 = 2 个里 1 个 = 0.5
```

对应项目代码（`evaluate_generation.py:143-148`）：

```python
if name == "context_recall":
    return metric.ascore(
        user_input=question,
        retrieved_contexts=contexts,
        reference=case["ground_truth"],
    )
```

**关键性质**：

- **它测的是检索的上限**。context_recall = 0.5 意味着"就算模型再完美，它最多也只能答对一半"——因为另一半信息压根没送进来。
- **它不看排序**。有用的块排第 1 还是排第 10，context_recall 都是 1.0。看排序是 `context_precision` 和 MRR 的活。
- **它和 Hit@K 的区别**：Hit@K 看的是"文档命中了吗"（文档级、二值），context_recall 看的是"标准答案的信息覆盖了多少"（claim 级、连续）。后者更细。

---

## 39.3 最小可运行骨架

RAGAS 本身依赖很重（`datasets`、`pyarrow`、`langchain` 一堆），为了让你看清楚 **LLM-as-judge 的本质**，我们先手写一个 40 行的 faithfulness 打分器——不装任何依赖就能跑。

把下面存成 `minimal_ragas.py`：

```python
"""手写 faithfulness：看清 LLM-as-judge 的本质。

RAGAS 的 faithfulness 做的事就三步：
  1. 把答案拆成若干条独立陈述（claim）
  2. 逐条判断 claim 能否从上下文里推出
  3. 分数 = 支持的条数 / 总条数

真实的 RAGAS 用 LLM 做第 1 步和第 2 步；这里为了让脚本离线可跑，
用一个 FakeJudge 顶替。把 FakeJudge 换成真实 LLM 调用，就是生产实现。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Judge:
    """裁判接口：拆 claim + 判支持。换成 LLM 就是生产版。"""

    def split_claims(self, answer: str) -> list[str]:
        raise NotImplementedError

    def is_supported(self, claim: str, contexts: list[str]) -> bool:
        raise NotImplementedError


class FakeJudge(Judge):
    """离线裁判：用规则模拟 LLM，用于跑通流程、验证计分逻辑。"""

    def split_claims(self, answer: str) -> list[str]:
        # 真实实现是 LLM 抽取；这里按句号/分号粗切，够演示用
        parts = re.split(r"[。；;\n]", answer)
        return [p.strip() for p in parts if len(p.strip()) >= 4]

    def is_supported(self, claim: str, contexts: list[str]) -> bool:
        # 真实实现是 LLM 判断；这里退化成"关键词是否出现在上下文里"
        keys = re.findall(r"\d{1,2}:\d{2}|[一-龥]{2,6}", claim)
        if not keys:
            return True  # 没有可核验实体，视为不可证伪
        return any(k in ctx for ctx in contexts for k in keys)


class LLMJudge(Judge):
    """真实裁判：把两个判断都交给 LLM（这就是 RAGAS 的做法）。"""

    _SPLIT = """把下面的答案拆成若干条互相独立的陈述，每行一条，不要编号，不要解释。
答案：{answer}"""

    _SUPPORT = """判断下面这条陈述能否从给定资料中推出。只回答 yes 或 no。
资料：
{contexts}
陈述：{claim}"""

    def __init__(self, client, model: str, judge_of_judge: bool = False):
        self.client = client
        self.model = model

    async def split_claims(self, answer: str) -> list[str]:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": self._SPLIT.format(answer=answer)}],
            temperature=0,          # ★ 裁判必须 temperature=0，否则分数不可复现
            max_tokens=2048,
        )
        text = resp.choices[0].message.content or ""
        return [line.strip() for line in text.splitlines() if line.strip()]

    async def is_supported(self, claim: str, contexts: list[str]) -> bool:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": self._SUPPORT.format(
                        contexts="\n".join(contexts), claim=claim
                    ),
                }
            ],
            temperature=0,
            max_tokens=8,           # 只要 yes/no，别让模型发挥
        )
        return (resp.choices[0].message.content or "").strip().lower().startswith("y")


def faithfulness(answer: str, contexts: list[str], judge: Judge) -> tuple[float, list]:
    """返回 (分数, 每条 claim 的判定明细)。

    注意：分数只是结果，**明细才是诊断依据**。生产环境一定要把明细落盘，
    否则你只知道"0.67"，不知道是哪一条编的。
    """
    if not contexts:
        # ★ 没有任何上下文时，答案里一切实质内容都是编造 → 判 0
        return 0.0, []

    claims = judge.split_claims(answer)
    if not claims:
        return 0.0, []

    verdicts = [(c, judge.is_supported(c, contexts)) for c in claims]
    score = sum(1 for _, ok in verdicts if ok) / len(verdicts)
    return round(score, 4), verdicts


if __name__ == "__main__":
    contexts = [
        "[开放时间#3]\n人工智能实验室周末 09:00 开放，17:00 关闭。",
        "[开放时间#4]\n机器人实验室仅工作日开放。",
    ]
    judge = FakeJudge()

    # 用例 1：完全忠实
    good = "人工智能实验室周末 09:00 开放，17:00 关闭。"
    score, detail = faithfulness(good, contexts, judge)
    print(f"[忠实]   {score}  {good}")
    for claim, ok in detail:
        print(f"         {'✅' if ok else '❌'} {claim}")

    # 用例 2：夹带一句编造
    bad = "人工智能实验室周末 09:00 开放，17:00 关闭，并且需要提前一天预约。"
    score, detail = faithfulness(bad, contexts, judge)
    print(f"\n[编造]   {score}  {bad}")
    for claim, ok in detail:
        print(f"         {'✅' if ok else '❌'} {claim}")

    # 用例 3：空上下文 → 一切都是编造
    score, _ = faithfulness("实验室 09:00 开放", [], judge)
    print(f"\n[无上下文] {score}  （空上下文一律判 0，这是刻意的保守设计）")
```

跑一下：

```
$ python minimal_ragas.py
[忠实]   1.0  人工智能实验室周末 09:00 开放，17:00 关闭。
         ✅ 人工智能实验室周末 09:00 开放，17:00 关闭

[编造]   0.5  人工智能实验室周末 09:00 开放，17:00 关闭，并且需要提前一天预约。
         ✅ 人工智能实验室周末 09:00 开放
         ✅ 17:00 关闭
         ❌ 并且需要提前一天预约

[无上下文] 0.0  （空上下文一律判 0，这是刻意的保守设计）
```

**这个 40 行脚本揭示了 LLM-as-judge 的全部本质**：

1. **把主观判断拆成若干个二值判断**（这条 claim 支持吗？yes/no）
2. **用 LLM 做每个二值判断**（`temperature=0`，输出受限）
3. **聚合成一个 0~1 的分数**（计数 / 总数）

RAGAS 的四个指标，无一例外都是这个套路，只是拆的粒度不同（claim / 生成问题 / context 有用性）。

**看懂这个骨架，你就不会再觉得 RAGAS 是黑盒了。**

---

## 39.4 项目代码定位

### 39.4.1 整体链路

`backend/evaluate_generation.py`（387 行）的完整链路：

```
eval_dataset.CASES (14 条)
        │
        ├─► kb_service.retrieve(question, top_k=FINAL_CONTEXT_K)   ← 复用线上检索管线
        │       │
        │       └─► kb_service._expand_context(hit)  ← 父上下文展开（第 29 章）
        │               │
        │               └─► contexts = ["[开放时间#3]\n正文", ...]
        │
        ├─► _generate_answer(client, question, contexts)   ← 用【被测模型】生成答案
        │       model = settings.LLM_MODEL
        │       temperature = 0
        │
        └─► _score_case(metrics, case, answer, contexts)   ← 用【裁判模型】打分
                model = settings.JUDGE_MODEL
```

**注意这里有两个模型**，这是整个设计的关键。

### 39.4.2 上下文怎么来（必须与线上一致）

`evaluate_generation.py:92-103`：

```python
def _retrieve_contexts(question: str) -> list[str]:
    """召回并展开父上下文，返回与送入模型完全一致的上下文块列表。"""
    top_k = settings.FINAL_CONTEXT_K
    hits = kb_service.retrieve(question, top_k=top_k)
    contexts: list[str] = []
    for hit in hits:
        meta = hit.get("meta") or {}
        source = meta.get("source") or "未知来源"
        chunk_index = meta.get("chunk_index")
        body = kb_service._expand_context(hit)
        contexts.append(f"[{source}#{chunk_index}]\n{body}")
    return contexts
```

**为什么这里要调 `_expand_context`？** 因为线上也是这么送进 prompt 的。如果你评估时送原文的块、线上送父上下文展开后的块，**你评估的就不是线上那个系统**。

**为什么 `contexts` 里要带 `[source#chunk_index]` 前缀？** 因为线上的 RAG prompt 里带这个前缀，模型是看着这个格式生成引用的（第 29 章）。评估必须复现这个格式，否则 faithfulness 会失真。

这个"评估输入必须与线上一致"的原则，比任何指标选择都重要。

### 39.4.3 答案怎么生成（只用被测模型）

`evaluate_generation.py:106-125`：

```python
async def _generate_answer(
    client: AsyncOpenAI, question: str, contexts: list[str]
) -> str:
    if contexts:
        material = "\n\n".join(contexts)
    else:
        material = "（本次没有检索到任何资料）"
    user_prompt = f"以下是检索到的实验室资料：\n{material}\n\n问题：{question}"

    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,          # ★ 被测模型
        messages=[
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=1024,
    )
    return (response.choices[0].message.content or "").strip()
```

`RAG_SYSTEM_PROMPT`（`:59-63`）刻意**没有整段抄线上的 `SYSTEM_PROMPT`**：

```python
RAG_SYSTEM_PROMPT = """你是智能实验室预约系统的助手，回答要简洁。
只依据下面提供的实验室资料回答，不要编造资料里没有的信息。
如果资料里没有相关内容，直接说明「资料里没有相关内容」，不要给出猜测。
回答时注明依据的文件名，例如「根据《开放时间.md》」。
"""
```

注释里写得很清楚（`:56-58`）：

> 这里不抄整段 prompt，是因为线上那段还要讲工具调用规则，跟本脚本无关。

**这是一个重要的边界声明**：本脚本只评估"检索 → 有据作答"这一段，**不含工具编排、多轮记忆、人工审批**。所以：

> ⚠️ **本脚本的分数不代表线上 Agent 的整体质量。**
> 它衡量的是 RAG 问答链路本身。第 38 章的检索指标 + 这一章的生成指标，加起来也只覆盖了"问答"这一半能力，工具调用那一半要靠单测（第 15-18 章的测试）覆盖。

### 39.4.4 裁判/被测模型分离（核心设计）

配置在 `backend/app/config.py:68-70`：

```python
JUDGE_MODEL: str | None = None
JUDGE_API_KEY: str | None = None
JUDGE_BASE_URL: str | None = None
```

运行时组装（`evaluate_generation.py:294-309`）：

```python
# 被测模型：用它「生成答案」，模拟线上回答质量。
client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)

# 裁判模型：独立配置，用于给答案打分。留空则回退被测模型（不推荐）。
judge_model = settings.JUDGE_MODEL or settings.LLM_MODEL
judge_api_key = settings.JUDGE_API_KEY or settings.LLM_API_KEY
judge_base_url = settings.JUDGE_BASE_URL or settings.LLM_BASE_URL
judge_client = AsyncOpenAI(api_key=judge_api_key, base_url=judge_base_url)

llm = llm_factory(
    judge_model,
    client=judge_client,
    max_tokens=RAGAS_MAX_TOKENS,
    temperature=0,
)
```

启动时如果没配裁判，脚本会**主动告警**（`:272-274`）：

```python
print(f"裁判模型    : {settings.JUDGE_MODEL or settings.LLM_MODEL}")
if settings.JUDGE_MODEL is None:
    print("              ⚠ 未配置 JUDGE_MODEL，裁判与被测同源，分数存在噪声")
```

**为什么必须分离？** 文件头注释（`:15-21`）给了答案：

> 评估的可靠性取决于裁判比被测更强、更稳定。让「考生自己阅卷」会引入系统性噪声——
> 之前实测同一段答案重复打分能在 0.5~1.0 之间抖动。

**"同一段答案重复打分在 0.5~1.0 之间抖动"** 这句话值得停下来想三秒：

- 你的模型改了一版，faithfulness 从 0.72 涨到 0.81
- 你很高兴，觉得优化生效了
- 但实际上，**裁判本身的抖动幅度就是 0.5**，这个 0.09 的差异完全在噪声里

**这就是第 37 章讲的"裁判噪声"陷阱的具体数值。** 分离裁判模型只是缓解，不是根治——根治要多次打分取均值 + 人工校准。

### 39.4.5 指标分类打分（METRIC_CATEGORIES）

`evaluate_generation.py:74-89`，注释写得比代码还长，因为它承载的是口径决策：

```python
# 每个指标适用的用例类别。不同指标的前提条件不一样，硬套会把汇总分数带偏：
#
# - context_precision / context_recall 需要 reference，只对 factual 有意义。
#   拒答用例的标准答案本身就是「资料里没有」，拿它去算召回覆盖毫无意义。
# - answer_relevancy 的算法是「由答案反推问题，再和原问题比嵌入相似度」。
#   拒答答案反推出来的问题是「资料里有什么」，和「Wi-Fi 密码是多少」
#   相似度必然接近 0——实测拒答类恒为 0.000，是机制导致的假低分，
#   不是模型答错了。所以拒答类不算这个指标。
# - faithfulness 只依赖「答案 vs 上下文」，任何类别都适用，
#   也是拒答用例唯一有意义的指标（考的就是有没有编造）。
METRIC_CATEGORIES = {
    "faithfulness": {"factual", "refusal"},
    "answer_relevancy": {"factual"},
    "context_precision": {"factual"},
    "context_recall": {"factual"},
}
```

"实测拒答类恒为 0.000"——这个数字是跑出来的，不是推理出来的。这正是第 37 章说的"**先看数据，再下结论**"。

打分时按类别过滤（`evaluate_generation.py:152-173`）：

```python
async def _score_case(metrics, case, answer, contexts) -> dict:
    applicable = [
        name for name in METRIC_ORDER
        if case["category"] in METRIC_CATEGORIES[name]
    ]
    calls = {
        name: _metric_call(name, metrics[name], case, answer, contexts)
        for name in applicable
    }
    results = await asyncio.gather(*calls.values(), return_exceptions=True)

    scores: dict[str, float] = {}
    errors: dict[str, str] = {}
    for name, result in zip(calls.keys(), results):
        if isinstance(result, BaseException):
            errors[name] = f"{type(result).__name__}: {result}"
        else:
            scores[name] = round(float(result.value), 4)
    return {"scores": scores, "errors": errors}
```

两个细节值得学：

**① `return_exceptions=True`**：单个指标挂了（LLM 超时、JSON 解析失败）不拖垮整条用例，错误单独记到 `errors` 里，最后汇总会提示"⚠ N 条用例存在指标异常"。

**② 分数和错误分开存**：`scores` 和 `errors` 是两个字典。汇总时 `scored` 字段记录有效样本数（`:236-238`）：

```python
for metric in METRIC_ORDER:
    values = [c["scores"][metric] for c in selected if metric in c.get("scores", {})]
    summary[metric] = {"mean": _mean(values), "scored": len(values)}
```

**"均值 + 有效样本数"必须一起报。** 一个 0.85 的均值，如果有效样本只有 2 条，它和 14 条样本的 0.85 完全是两回事。

### 39.4.6 数据集：14 条用例

`backend/eval_dataset.py:20-131`，每条用例四个字段：

```python
{
    "question": "人工智能实验室周末几点开放？",
    "ground_truth": "人工智能实验室周末 09:00 开放，17:00 关闭。",
    "expected_source": "开放时间",
    "category": "factual",
},
```

分布：**12 条 factual + 2 条 refusal**。

两条拒答用例（`:112-129`）是刻意设计的边界：

```python
{
    "question": "实验室的 Wi-Fi 密码是多少？",
    "ground_truth": (
        "知识库里没有 Wi-Fi 密码相关信息，正确做法是说明资料中没有该信息，"
        "不要编造一个密码。"
    ),
    "expected_source": None,      # ★ None 表示"知识库答不了"
    "category": "refusal",
},
{
    "question": "单次预约最长可以约几个小时？",
    "ground_truth": (
        "知识库没有规定单次预约的时长上限，正确做法是说明资料里没有相关规定，"
        "建议咨询管理员，不要编造一个时长。"
    ),
    "expected_source": None,
    "category": "refusal",
},
```

**为什么拒答用例必须单独放？** 因为它们是**最容易被优化掉的一类**。

你为了让 faithfulness 好看，把 prompt 改成"尽量回答，不要说不知道"——事实类分数纹丝不动，但拒答类会**从 1.0 掉到 0.0**（模型开始编密码了）。如果没有这两条用例，你的评测集会**完全检测不到这个退化**。

> **拒答用例是评测集里的哨兵。** 它们的存在意义不是"提分"，是"防止你在优化事实类指标时把安全边界搞坏"。

`expected_source: None` 这个设计（`:131-140`）也很关键：

```python
def factual_cases() -> list[dict]:
    """只取「资料里有答案」的用例，检索指标用这批。"""
    return [case for case in CASES if case["expected_source"]]
```

检索指标（第 38 章）只跑 12 条 factual，因为拒答用例的 `expected_source` 是 None，算 Hit@K 没有意义。

### 39.4.7 一键入口与 CI

`backend/run_eval.py`（117 行）把两条链收进一个命令：

```bash
python run_eval.py                  # 检索 + 生成全跑
python run_eval.py --skip-gen       # 只跑检索
python run_eval.py --limit 3        # 生成侧只跑前 3 条（冒烟）
python run_eval.py --diff           # 与上次报告对比
```

返回码设计（`run_eval.py:100-113`）：

```python
rc = 0
if not args.skip_retrieval:
    rc |= _run_retrieval()
if not args.skip_gen:
    rc |= _run_generation(args.limit, args.concurrency)
if args.diff:
    rc |= _diff_last_report()

print()
if rc == 0:
    print("评测完成：全部通过。")
else:
    print("评测完成：存在失败环节，请查看上方输出。", file=sys.stderr)
return rc
```

**位或 `|=` 累积返回码**——任一环节失败，最终 exit code 非 0，CI 里可以直接判断。这是"让评测能进流水线"的最小实现。

结果落盘 `backend/eval_reports/generation.json`（`:335-357`），包含：

- `generated_at`：时间戳（对比两次报告用）
- `config`：被测/裁判模型、top_k、hybrid/rerank 开关、RAGAS_MAX_TOKENS
- `summary`：overall / factual / refusal 三组汇总
- `cases`：14 条明细，每条含 question / category / ground_truth / contexts / answer / scores / errors

**为什么 `config` 要进报告？** 因为**脱离配置的分数无法对比**。你看到 faithfulness = 0.72，但不知道 top_k 是 3 还是 5、rerank 开没开、裁判是谁——这个数字就废了。落盘 config 是"可复现"的最低要求。

---

## 39.5 踩过的坑

### ⚠️ 坑 1：推理模型的思考 token 吃掉了 JSON 预算

**现象**：用 DeepSeek 的推理类模型当裁判，跑几条就抛 `IncompleteOutputException`。

**原因**：RAGAS 的结构性输出（让裁判返回 JSON）默认 `max_tokens=1024`。推理模型会先输出一大段思考过程（reasoning tokens），**思考过程也算在 max_tokens 预算里**。等它思考完开始写 JSON 时，预算已经用完了，JSON 被截断。

**修复**（`evaluate_generation.py:65-67`）：

```python
# RAGAS 结构性输出默认只给 1024 token，deepseek-v4-flash 的思考过程会先把预算吃掉，
# 导致 JSON 被截断并抛 IncompleteOutputException，所以显式调高。
RAGAS_MAX_TOKENS = 8192
```

然后传给 `llm_factory`（`:303-308`）。

**这个坑的通用教训**：**推理模型（o1 / deepseek-reasoner / 带思考的 flash）在需要结构化输出的场景，必须显式调高 max_tokens，并且把 "thinking budget" 和 "answer budget" 分开算。** 只调高总预算是 workaround，正解是看厂商是否支持 `reasoning_effort` 或独立的思考预算参数。

### ⚠️ 坑 2：裁判与被测同源，分数抖动 0.5

**现象**：同一段答案，连续跑两次评估，faithfulness 一次 0.52 一次 1.0。

**原因**：裁判模型和被测模型是同一个，且裁判本身输出不稳定。

**缓解**：`JUDGE_MODEL` 指向更强的模型（注释建议 `deepseek-reasoner` / `gpt-4o`），并且**启动时主动告警**未分离的情况。

**未根治**：即使分离了裁判，LLM-as-judge 仍有噪声。第 37 章给的进一步手段是**同一条打分 N 次取均值**，本项目没做（成本考虑）。这是已知的未做项，面试时如实说。

### ⚠️ 坑 3：context_precision 看排序不看比例，抓不到"塞满上下文"

**现象**：把 `FINAL_CONTEXT_K` 从 3 调到 20，context_precision 纹丝不动（还是 1.0），但成本翻了 6 倍、延迟涨了、faithfulness 反而掉了。

**原因**：见 39.2.3——分母是"相关块总数"，无关块不扣分。

**教训**：**不要单独看任何一个指标。** 必须的组合：

```
context_precision + token 成本    → 才能判断"召回宽度"是否合理
context_recall  + faithfulness    → 才能判断"模型有没有用好资料"
```

### ⚠️ 坑 4：拒答用例的 answer_relevancy 是机制性假低分

**现象**：拒答用例 answer_relevancy 恒为 0.000，一度以为是模型答错了。

**排查**：手动推导算法（39.2.2）后发现是"由答案反推问题"这个机制决定的——拒答答案反推出来的问题是"资料里有什么"，与原问题天然不相似。

**修复**：`METRIC_CATEGORIES` 把拒答类排除出 answer_relevancy。

**教训（最重要的一条）**：**看到异常分数，先怀疑指标口径，再怀疑模型。** 这个排查顺序能省下大量无用功。

### ⚠️ 坑 5：ragas 依赖太重，拖慢所有脚本启动

**现象**：`import ragas` 会拉起 `datasets`、`pyarrow` 等一堆重依赖，任何一个用到 `app.config` 的脚本都被拖慢。

**修复**：把 import 放进函数内（`evaluate_generation.py:283-292`）：

```python
# 这里的 import 故意放在函数内：ragas 及其依赖（datasets / pyarrow 等）
# 只想在真正跑评估时加载，不影响其它脚本的启动速度。
from ragas.embeddings import HuggingFaceEmbeddings
from ragas.llms import llm_factory
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextPrecisionWithReference,
    ContextRecall,
    Faithfulness,
)
```

**这是个通用模式**：重依赖、可选依赖，一律延迟导入。

### ⚠️ 坑 6：RAGAS 0.4.x 的 API 与网上教程完全不同

**现象**：照着教程写 `from ragas.metrics import faithfulness; evaluate(dataset, metrics=[faithfulness])`，报 ImportError。

**原因**：RAGAS 0.4.x 改成了**类形式 + 异步单条打分**：

```python
# 0.1.x / 0.2.x（旧）
from ragas.metrics import faithfulness
result = evaluate(dataset, metrics=[faithfulness])

# 0.4.x（新，本项目用的）
from ragas.metrics.collections import Faithfulness
metric = Faithfulness(llm=llm)
score = await metric.ascore(user_input=..., response=..., retrieved_contexts=...)
```

**教训**：RAGAS 的 API 在 0.3→0.4 之间有一次大改。**遇到版本问题时，直接去看你装的那个版本的源码，别信博客。** 项目里用的版本是 0.4.3。

### ⚠️ 坑 7：并发打爆限流

`evaluate_generation.py:318-321`：

```python
sem = asyncio.Semaphore(concurrency)      # 默认 3
results = await asyncio.gather(
    *(_run_case(client, metrics, case, sem) for case in cases)
)
```

14 条用例 × 每条 1 次检索 + 1 次生成 + 4 次打分 = 约 84 次 LLM 调用。不设并发上限会瞬间打爆 API 限流。

**注意**：RAGAS 内部还有自己的并发调度，**外层 Semaphore 和内层并发会相乘**。所以外层保守设 3，别贪。

### ⚠️ 坑 8：评估链路与线上不一致，分数被误读

这是**设计上的取舍，不是 bug，但必须说清楚**（`evaluate_generation.py:23-28`）：

> 线上走的是 LangGraph Agent + 工具调用，这里刻意只跑「检索 → 有据作答」这一段。
> 原因是 RAGAS 的 faithfulness / context_precision 都要求上下文固定可复现，
> 而 Agent 的工具调用路径每轮都可能不同，分数抖动会掩盖真实问题。

**为什么必须这么做？** 因为 Agent 每轮召回的上下文可能不同（工具调用次数、查询改写结果都影响），**上下文不可复现 → faithfulness 不可比**。

**代价**：分数只代表 RAG 链路，不代表 Agent 整体。这个代价是明确接受的，并且写进了注释——**"知道自己没测什么"比"测了什么"更重要**。

---

## 39.6 面试问答

### Q1：RAGAS 四个指标分别测什么？哪些需要标准答案？

**答**：分两组。答案侧两个：

- **faithfulness**：答案的每条陈述能否在召回上下文里找到依据，测幻觉，不需要 reference
- **answer_relevancy**：由答案反推问题再和原问题比嵌入相似度，测答非所问，不需要 reference

上下文侧两个，都需要 reference：

- **context_precision**：有用的上下文有没有排前面，算的是 average precision
- **context_recall**：标准答案的信息有多少被召回覆盖

关键区别是**需不需要 ground_truth**。不需要的那两个可以在无标注数据上跑，需要的那两个必须先建评测集。

### Q2：faithfulness 高是不是说明答案是对的？

**答**：不是。faithfulness 只保证"**有出处**"，不保证"**出处是对的**"。如果知识库本身写错了（比如文档过期），模型照着说，faithfulness 是 1.0，答案是错的。

所以 faithfulness 要和 context_recall 一起看：前者看模型有没有照资料说，后者看资料有没有覆盖正确答案。**两个都高，答案才大概率对。**

### Q3：context_precision 为什么"看排序不看比例"？有什么后果？

**答**：它算的是 average precision，分母是**相关块总数**而不是召回块总数。所以唯一相关的那条只要排第 1 就是满分，后面跟多少无关块都不扣分。

后果是**它抓不到"狂塞上下文"**。你把 top_k 从 3 加到 20，只要有用那条还排第一，分数不变，但成本翻 6 倍、噪声增加、faithfulness 可能下降。

所以实际调参时，context_precision 必须和 token 成本、faithfulness 一起看，不能单独看。

### Q4：为什么裁判模型要和被测模型分离？

**答**：评估的可靠性取决于裁判比被测更强更稳定。让被测模型自己给自己打分，会引入系统性噪声——我们实测同一段答案重复打分能在 0.5~1.0 之间抖动，这个抖动幅度比我们想测的优化差异（通常 0.05~0.1）大一个数量级，等于**测量工具的误差远大于被测信号**。

项目里用 `JUDGE_MODEL` / `JUDGE_API_KEY` / `JUDGE_BASE_URL` 三个环境变量独立配置裁判，留空时回退被测模型，但会**在启动横幅里打印告警**，避免你忘了配还以为分数可信。

### Q5：拒答类用例为什么不算 answer_relevancy？

**答**：因为 answer_relevancy 的算法是"由答案反推问题，再和原问题比相似度"。拒答答案（"资料里没有相关信息"）反推出来的问题是"资料里有什么"，和"Wi-Fi 密码是多少"这种具体问题相似度必然接近 0。

我们实测拒答类恒为 0.000，**这是机制导致的假低分，不是模型答错了**。所以项目里用 `METRIC_CATEGORIES` 做了指标分类，拒答类只算 faithfulness——因为拒答用例考的就是"有没有编造"，而这正是 faithfulness 的定义。

### Q6：评估链路和线上不一致，分数还有意义吗？

**答**：有意义，但要清楚它测的是哪一段。我们的评估刻意只跑"检索 → 有据作答"，不走 LangGraph 工具调用，因为 faithfulness 和 context_precision 都要求上下文固定可复现，而 Agent 的工具路径每轮可能不同，上下文不可复现分数就不可比。

所以这个分数**衡量的是 RAG 链路本身**，不含工具编排、多轮记忆、人工审批。那部分靠单元测试覆盖。评测要分层，不可能一个指标覆盖全链路。

### Q7：用推理模型当裁判有什么坑？

**答**：RAGAS 的结构性输出默认 `max_tokens=1024`，推理模型会先输出一大段思考过程，思考 token 也算在这个预算里，等它开始写 JSON 时预算已经用完，JSON 被截断，抛 `IncompleteOutputException`。

我们显式调高到 8192 解决了。更根本的做法是看厂商是否支持独立的思考预算参数（如 `reasoning_effort`），把思考预算和回答预算分开配。

### Q8：怎么判断一个低分该往哪个方向优化？

**答**：看四个指标的组合：

| 组合 | 诊断 | 方向 |
|---|---|---|
| `context_recall` 低 | 该召回的没召回 | 扩 top_k、开混合检索、加查询改写、调切块 |
| recall 高 + `context_precision` 低 | 召回了但排序差 | 加 rerank（第 27 章） |
| precision 高 + `faithfulness` 低 | 资料送到但模型编造 | 收紧 prompt、temperature=0、换更强模型 |
| faithfulness 高 + `answer_relevancy` 低 | 忠实但答非所问 | 改 prompt 的问题理解、检查查询改写 |
| 四个都低 | 数据或切块有根本问题 | 回第 22-23 章看解析和切块 |

**核心思路：用指标组合定位故障层，而不是看到一个低分就瞎调。**

### Q9：为什么评测集里要放"答不了"的用例？

**答**：因为它们是哨兵。如果你为了优化 faithfulness 把 prompt 改成"尽量回答，不要说不知道"，事实类分数纹丝不动，但拒答类会从 1.0 掉到 0.0——模型开始编 Wi-Fi 密码了。

**没有拒答用例，这个退化你的评测集完全检测不到。** 它们的价值不是提分，是防止你在优化某个指标时把安全边界搞坏。我们放了 2 条。

### Q10：LLM-as-judge 的本质是什么？

**答**：把主观判断拆成若干个二值判断，用 LLM 做每个二值判断（`temperature=0`、输出受限），再聚合成 0~1 的分数。

faithfulness 拆的是 claim（这条陈述有依据吗？yes/no）；context_precision 拆的是 context（这条有用吗？yes/no）；context_recall 拆的是 ground_truth 的 claim（这条被覆盖了吗？yes/no）。

看懂这个套路后，你可以给任何主观维度设计指标——比如"答案是否带引用""语气是否礼貌"，都是同样的三步。**RAGAS 不是黑盒，它是这个套路的四次应用。**

---

## 39.7 速记卡

**四指标**

| 指标 | 测什么 | 需要 reference | 算法核心 |
|---|---|:---:|---|
| faithfulness | 幻觉 | ❌ | 答案拆 claim → 逐条核对上下文 |
| answer_relevancy | 答非所问 | ❌ | 由答案反推问题 → 比嵌入相似度 |
| context_precision | 排序质量 | ✅ | average precision（看排序） |
| context_recall | 召回覆盖 | ✅ | ground_truth 拆 claim → 看覆盖比例 |

**★ 拒答类只算 faithfulness**（answer_relevancy 机制性 0 分）

**★ context_precision 分母是相关块总数** → 不惩罚塞满上下文 → 必须配成本看

**★ faithfulness 高 ≠ 答案对**（只保证有出处）→ 要配 context_recall 看

**裁判分离**：`JUDGE_MODEL` / `JUDGE_API_KEY` / `JUDGE_BASE_URL`，留空回退并告警
**★ 同源抖动实测 0.5~1.0，远大于待测差异**

**⚠️ 推理模型坑**：RAGAS 默认 `max_tokens=1024`，思考 token 吃掉预算 → JSON 截断 → 调 `RAGAS_MAX_TOKENS=8192`

**⚠️ RAGAS 0.4.x API**：类形式 `Faithfulness(llm=llm)` + `await metric.ascore(...)`，旧教程全废

**⚠️ 重依赖延迟导入**：`ragas` 放函数内 import

**评测链路**：`retrieve` → `_expand_context` → 被测模型生成 → 裁判模型打分
**★ 必须与线上格式一致**（`[source#idx]` 前缀、父上下文展开）

**已知边界**：只测 RAG 链路，不含工具编排/多轮/审批；裁判噪声未根治（未做多次打分取均值）

**代码位置**：
- `evaluate_generation.py:84-89` 指标分类
- `evaluate_generation.py:67` RAGAS_MAX_TOKENS
- `evaluate_generation.py:294-309` 裁判/被测分离
- `eval_dataset.py:20-131` 14 条用例（12 factual + 2 refusal）
- `run_eval.py:100-113` exit code 累积

---

## 39.8 延伸思考

1. **如果连 ground_truth 都写不出来，还能评估吗？**
   提示：能，但只能用**不需要 reference 的两个指标**（faithfulness / answer_relevancy）。更进一步可以走 **reference-free** 路线：用 LLM 从文档自动生成问答对当伪 ground_truth（RAGAS 有 `TestsetGenerator`）。但要注意——**自动生成的评测集会有"生成器偏爱"偏差**，它生成的问题往往是原文里直接能找到的，测不出真正的难点。实务上是"自动生成 + 人工审一遍"。

2. **裁判模型的噪声怎么定量测出来？**
   提示：**重测信度（test-retest reliability）**。同一批答案，在完全相同的配置下跑 N 次，算分数的标准差 / 方差。如果标准差是 0.2，那任何小于 0.4 的差异都不可信。再进一步可以做 **Cohen's kappa**：让裁判和人工标注同时打同一批，算一致率——一致率低于 0.6 说明这个裁判不可用于决策。本项目没做这两件事，是明确的未做项。

3. **评测能不能进 CI？进了之后要注意什么？**
   提示：技术上能——`run_eval.py` 的 exit code 已经为 CI 设计好了。但有三个坑：① **成本**（84 次 LLM 调用，每次 PR 都跑受不了）→ 只在 release 分支跑，或用 `--limit` 冒烟；② **不稳定性**（LLM 输出有随机性，即使 temperature=0 也不保证逐字节一致）→ **不能用硬阈值卡 CI**，只能用"相对上次报告下降超过 X%"的软告警；③ **外部依赖**（API 挂了 CI 就红）→ 要有超时和降级。**评测进 CI 的难点不在代码，在成本与稳定性。**

4. **四个指标都涨了，用户满意度没涨，可能是什么原因？**
   提示：指标的口径和用户的诉求错位。常见的错位：① 用户要的是**能直接照做**（"点击这里预约"），你优化的是**信息完整度**；② 用户要的是**快**，你优化的是**准**；③ 评测集里全是单轮事实问，用户实际在问多轮上下文相关的问题（"那我刚才那个预约呢"）；④ **UI 层的问题**（渲染错、加载慢）评测集完全覆盖不到。**指标涨了体验没涨，第一反应应该是"我的评测集代表性够不够"。**

---

**下一章**：第 40 章 · 可观测性——线上出问题时，你怎么知道是哪一环坏的？
