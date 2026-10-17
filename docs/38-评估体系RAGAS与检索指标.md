# 38 · 评估体系：RAGAS 四指标 + 检索指标 + 裁判分离

> **速成定位**：**这是你最强的差异化**。绝大多数候选人只会说「我做了 RAG」，你能说「我建了评估体系并发现了三个评测陷阱」。
> **一句话**：检索侧评 Hit@1/3、MRR、nDCG@3；生成侧用 RAGAS 四指标，**裁判模型与被测模型分离**；自建 14 条标注用例含拒答边界。

---

## 目录

1. [为什么必须有评估](#1-为什么必须有评估)
2. [检索侧指标：Hit@K / MRR / nDCG](#2-检索侧指标)
3. [生成侧：RAGAS 四指标](#3-生成侧ragas-四指标)
4. [裁判分离：为什么要换更强的模型打分](#4-裁判分离)
5. [数据集设计：14 条用例](#5-数据集设计)
6. [三个评测陷阱（最强面试素材）](#6-三个评测陷阱)
7. [一键评测与 CI 集成](#7-一键评测与-ci-集成)
8. [最小可运行骨架](#8-最小可运行骨架)
9. [项目里对应哪块代码](#9-项目里对应哪块代码)
10. [面试高频问答](#10-面试高频问答)
11. [速记卡](#11-速记卡)

---

## 1. 为什么必须有评估

**没有评估的 RAG 是这样的**：

> 改了切块大小 → 「感觉好了？」→ 不知道 → 上线 → 用户投诉

**有评估的 RAG**：

> 改了切块大小 → 跑 `python run_eval.py` → Hit@3 从 0.85 掉到 0.72 → 回滚

**面试一句话**：
> 「RAG 的每一步（切块大小、top_k、是否混合检索、是否 rerank）都是**可调参数**，没有量化指标就只能靠感觉调，等于没调。」

---

## 2. 检索侧指标

本项目的检索评估在 `backend/evaluate_rag.py`，评测维度是「文档级命中」（不看块，看来源文件对不对）。

### 2.1 Hit@K（命中率）

> 前 K 个结果里**有没有**正确答案。

```python
hit1 += int(expected in sources[:1])     # 第一个就对
hit3 += int(expected in sources[:3])     # 前三个里有
```

- **最直观**：用户只看前几条。
- **缺点**：只看「有没有」，不看排第几。

### 2.2 MRR（平均倒数名次）

> 正确答案排第几？**名次越靠前得分越高**。

```python
def _mrr(expected: str, sources: list[str]) -> float:
    for i, s in enumerate(sources):
        if s == expected:
            return 1.0 / (i + 1)      # 第1名=1.0，第2名=0.5，第3名=0.33
    return 0.0
```

**MRR 比 Hit@K 更敏感**：Hit@3 只看「前 3 里有没有」，MRR 能区分「排第 1」和「排第 3」。

### 2.3 nDCG@K（归一化折损累计增益）

> 多个相关结果时，既看**相关性等级**也看**位置**。

核心思想：**排在后面的相关结果要「打折」**（折损），位置越靠后价值越低；再除以理想排序的得分做归一化。

```python
def _ndcg_at_k(expected: str, sources: list[str], k: int) -> float:
    # 本项目是单正确答案，简化为：命中则增益 1/log2(i+2)，再归一化
```

**面试解释 nDCG 的直觉**：
> 「用户看搜索结果是**从上往下**看的，第 10 条结果即使相关，用户也基本不会看到。所以相关结果的增益要按位置对数折损；归一化是为了不同查询之间可比。」

### 2.4 三个指标怎么配合

| 指标 | 回答的问题 |
| --- | --- |
| Hit@1 | 最理想情况下能不能一次命中 |
| Hit@3 | 给用户 3 次机会能不能命中 |
| MRR | 正确结果平均排多前 |
| nDCG | 整体排序质量（多相关结果时） |

---

## 3. 生成侧：RAGAS 四指标

RAGAS 是专门评估 RAG 生成质量的框架，四个指标覆盖两个维度：

```text
生成质量 ── faithfulness       答案是否忠于上下文（抗幻觉）
         └─ answer_relevancy   答案是否切题
检索质量 ── context_precision  有用的上下文是否排在前面
         └─ context_recall     标准答案的信息是否被召回覆盖
```

### 3.1 faithfulness（忠实度）★ 最重要

**问**：答案里的每一句话，都能在召回的上下文里找到依据吗？

**怎么算**（RAGAS 的实现）：用 LLM 把答案拆成若干**陈述**（claims），再逐条判断该陈述能否从上下文推出，最后 `可推出数 / 总陈述数`。

**为什么最重要**：它直接度量**幻觉**。RAG 的核心承诺就是「不编造」，faithfulness 是这个承诺的量化。

### 3.2 answer_relevancy（答案相关性）

**问**：答案有没有正面回答用户的问题？

**算法很反直觉**（面试加分点）：RAGAS 是**由答案反推问题**——让 LLM 根据生成的答案想出若干「可能会被问出这个答案的问题」，再算这些问题与原始问题的**嵌入相似度**。

> 这意味着：答案越泛化（「这个我不确定，可能有多种因素」），反推的问题就越分散，相似度越低，得分越低。**所以它惩罚「说了等于没说」的答案。**

### 3.3 context_precision（上下文精确率）

**问**：真正有用的上下文有没有排到前面？

**⚠️ 口径陷阱**（见第 6 节）：它算的是 **average precision**，不只是「有没有」，而是「有用的排在第几位」——把有用内容从第 3 位挪到第 1 位，即使召回集合没变，分数也会涨。

### 3.4 context_recall（上下文召回率）

**问**：标准答案里的信息，有多少被召回覆盖了？

**需要 reference**（人工标注的标准答案），所以只对**有确定答案的事实类问题**有意义。

---

## 4. 裁判分离

### 4.1 问题：让模型给自己阅卷

如果被测模型和打分模型是同一个：

- 它倾向于认为「自己生成的答案」是合理的 → **系统性偏高**；
- 同一段答案重复打分结果会抖动 → **噪声大**。

### 4.2 本项目的解法

`config.py:64-70`：

```python
JUDGE_MODEL: str | None = None        # 留空则回退被测模型
JUDGE_API_KEY: str | None = None
JUDGE_BASE_URL: str | None = None
```

`evaluate_generation.py` 里裁判 client **独立构造**，报告里标注裁判模型，并在「同源」时打印警告。

**原则**：裁判模型应比被测模型**更强、更稳定**（如被测用 `deepseek-v4-flash`，裁判用 `deepseek-reasoner`）。

> **面试话术**：「评估的可靠性取决于裁判比被测更强更稳定。让考生自己阅卷会引入系统性噪声——我实测过，同一段答案重复打分都会抖动。所以裁判模型独立配置，报告里会显式标注用的是哪个模型，如果和被测同源会打印警告。」

---

## 5. 数据集设计

`backend/eval_dataset.py`，**14 条标注用例**。

### 5.1 分类设计

| 类别 | 说明 | 适用指标 |
| --- | --- | --- |
| `factual` | 有确定答案的事实类问题 | 四个指标全评 |
| `refusal` | **资料里没有**的问题，期望拒答 | 只评 `faithfulness` |

这个分类写在 `evaluate_generation.py:85-88`：

```python
{
    "faithfulness": {"factual", "refusal"},
    "answer_relevancy": {"factual"},
    "context_precision": {"factual"},
    "context_recall": {"factual"},
}
```

**为什么拒答类只评 faithfulness**：`context_precision` / `context_recall` 需要「标准答案」，拒答类没有；`answer_relevancy` 的算法是反推问题，对拒答也不适用。而 **faithfulness 只依赖「答案 vs 上下文」**，任何类别都能评——而且拒答类恰恰最能检验「有没有编造」。

### 5.2 拒答边界用例（设计亮点）

用例形如：「资料里没有的问题」→ 期望答案：「没有检索到相关资料」。

> **这是整个评估体系最有价值的一条**：大多数 RAG Demo 都不会测「该不该说不知道」，而这恰恰是幻觉最容易暴露的地方。

### 5.3 上下文固定的原因

`evaluate_generation.py:26` 注释：

> RAGAS 的 faithfulness / context_precision 都要求**上下文固定可复现**。

如果每次评估都重新检索，上下文会变，两次评估结果就不可比。所以流程是：先检索一次拿到 contexts，**固定住**再生成答案、再打分。

---

## 6. 三个评测陷阱

**这是你最强的面试素材**——不是「我用了 RAGAS」，而是「我用 RAGAS 时发现了三个陷阱」。

### 陷阱 1：检索指标饱和

**现象**：混合检索、rerank 全开时，Hit@3 已经接近 1.0，再加优化也看不出差异。

**含义**：说明**当前语料太小/太简单**，指标已经失去区分度。此时应该扩充数据集（更多、更难的 query），而不是继续在饱和指标上刷分。

> **面试话术**：「我实测发现检索指标饱和了——Hit@3 长期接近满分，这时再加优化也测不出差别。说明瓶颈不在检索算法而在**评测集本身的难度**。所以我把简历上原来『hit@2 验证混合检索提升』的说法删掉了，因为它已经不成立。」

### 陷阱 2：裁判模型噪声

**现象**：同一条用例、同一段答案，重复跑两次分数不一样。

**原因**：LLM 打分本身是概率性的，尤其被测模型较弱时抖动更明显。

**应对**：
1. 用**更强更稳定**的裁判模型；
2. 关注**均值和有效样本数**，而不是单条用例的分数；
3. 接受一定噪声，不要过度解读 0.02 的波动。

### 陷阱 3：context_precision 的排序口径

**现象**：召回集合没变，只是把有用内容从第 3 位放到第 1 位，`context_precision` 就涨了。

**原因**：它算的是 **average precision**，包含**位置权重**，不是简单的「有用/总数」。

**为什么这很重要**：如果你以为它是「精确率」，会误判优化方向——它会奖励**排序**改进，这是好事，但你得知道自己在测什么。

---

## 7. 一键评测与 CI 集成

`backend/run_eval.py`：

```bash
python run_eval.py                    # 检索 + 生成全跑
python run_eval.py --skip-retrieval   # 只跑生成
python run_eval.py --limit 5          # 只跑前 5 条（快速验证）
python run_eval.py --diff             # 与上次报告对比涨跌
```

**返回码设计**（`run_eval.py:13`）：

> 返回码：0 全部成功；非 0 有环节失败。**CI 里可直接用 exit code 判断。**

这是工程化意识的体现——评估不是「跑一下看看」，而是可以接进 CI 做回归门禁。

`--diff` 会输出每个指标的涨跌，用来判断「这次改动是变好还是变坏」。

---

## 8. 最小可运行骨架

不需要 RAGAS 和真实模型，纯标准库实现检索三指标 + 一个「裁判打分」的模拟（用规则模拟 LLM 裁判，展示 faithfulness 的计算思路）。

```python
"""最小骨架：检索指标(Hit@K/MRR/nDCG) + 生成指标(faithfulness 思路) + 拒答边界用例。
纯标准库，用来理解「评估到底在算什么」。"""

import math

# ============ 1. 迷你评测集：包含【拒答边界】用例 ============
# expected=None 表示「资料里没有，应该拒答」
DATASET = [
    {"q": "实验室几点开门", "expected": "规则.md", "type": "factual"},
    {"q": "进入实验室要穿什么", "expected": "规则.md", "type": "factual"},
    {"q": "光谱仪怎么预约", "expected": "设备手册.pdf", "type": "factual"},
    {"q": "预约后谁来审核", "expected": "规则.md", "type": "factual"},
    {"q": "图书馆几点关门", "expected": None, "type": "refusal"},   # ★ 拒答边界
]

# 模拟检索结果（每条 query 返回的来源文件排序）
MOCK_RESULTS = {
    "实验室几点开门":     ["规则.md", "设备手册.pdf", "其他.md"],
    "进入实验室要穿什么": ["设备手册.pdf", "规则.md", "其他.md"],   # 排第 2
    "光谱仪怎么预约":     ["设备手册.pdf", "规则.md", "其他.md"],
    "预约后谁来审核":     ["其他.md", "其他2.md", "规则.md"],       # 排第 3
    "图书馆几点关门":     ["其他.md", "设备手册.pdf"],              # 不该命中任何"正确"答案
}


# ============ 2. 检索指标 ============
def hit_at_k(expected, sources, k):
    """前 k 个里有没有正确答案。"""
    return int(expected in sources[:k])


def mrr(expected, sources):
    """正确答案排第几 → 1/名次；没命中 0。"""
    for i, s in enumerate(sources):
        if s == expected:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(expected, sources, k):
    """折损累计增益：位置越靠后增益越低，再归一化。"""
    dcg = 0.0
    for i, s in enumerate(sources[:k]):
        if s == expected:
            dcg += 1.0 / math.log2(i + 2)      # i=0 → 1.0；i=1 → 0.63；i=2 → 0.5
    idcg = 1.0                                  # 理想情况：正确答案排第 1
    return dcg / idcg


# ============ 3. 生成指标：faithfulness 的计算思路 ============
def split_claims(answer: str):
    """把答案拆成若干陈述（真实实现里这一步由 LLM 做）。"""
    return [s.strip() for s in answer.replace("。", "。|").split("|") if s.strip()]


def faithfulness(answer: str, contexts: list[str]) -> float:
    """答案里每句话能否在上下文中找到依据 → 可推出数 / 总陈述数。"""
    claims = split_claims(answer)
    if not claims:
        return 0.0
    supported = 0
    for c in claims:
        # 简化：用「关键词是否出现在上下文」模拟 LLM 的蕴含判断
        keywords = [w for w in c if w.isalnum()]
        hit = any(all(k in ctx for k in keywords[:3]) for ctx in contexts) if keywords else False
        supported += int(hit)
    return supported / len(claims)


# ============ 4. 跑评测 ============
def evaluate_retrieval():
    print("=" * 60)
    print("检索评估（文档级命中）")
    print("=" * 60)
    h1 = h3 = 0
    mrr_sum = ndcg_sum = 0.0
    n = 0

    for case in DATASET:
        if case["type"] != "factual":
            continue                    # 拒答类不参与检索指标（没有"正确答案"）
        expected = case["expected"]
        sources = MOCK_RESULTS[case["q"]]
        h1 += hit_at_k(expected, sources, 1)
        h3 += hit_at_k(expected, sources, 3)
        mrr_sum += mrr(expected, sources)
        ndcg_sum += ndcg_at_k(expected, sources, 3)
        n += 1
        print(f"  {case['q']:<16} → {sources[:3]}  "
              f"Hit@1={hit_at_k(expected, sources, 1)} MRR={mrr(expected, sources):.2f}")

    print(f"\n  Hit@1 = {h1/n:.3f}   Hit@3 = {h3/n:.3f}   "
          f"MRR = {mrr_sum/n:.3f}   nDCG@3 = {ndcg_sum/n:.3f}")


def evaluate_generation():
    print("\n" + "=" * 60)
    print("生成评估（faithfulness，含拒答边界）")
    print("=" * 60)

    # 事实类：答案有依据
    ctx = ["实验室开放时间 8:00-22:00"]
    good = "实验室开放时间是 8:00 至 22:00。"
    print(f"  事实类  「{good}」 → faithfulness={faithfulness(good, ctx):.2f}")

    # 幻觉：答案编造了上下文里没有的信息
    bad = "实验室开放时间是 9:00 至 18:00，周末开放。"
    print(f"  幻觉类  「{bad}」 → faithfulness={faithfulness(bad, ctx):.2f}")

    # 拒答边界：资料里没有，正确行为是拒答
    refusal = "没有检索到相关资料。"
    print(f"  拒答类  「{refusal}」 → faithfulness={faithfulness(refusal, ['无相关资料']):.2f}"
          "  ★拒答且未编造，应得高分")


if __name__ == "__main__":
    evaluate_retrieval()
    evaluate_generation()
```

**预期输出要点**：

```text
Hit@1 = 0.500   Hit@3 = 1.000   MRR = 0.611   nDCG@3 = 0.708
```

观察这个结果的三层含义（面试可直接讲）：

1. **Hit@3 = 1.0 但 Hit@1 只有 0.5** → 说明召回没问题，但**排序有优化空间**（这正是 rerank 存在的理由）。
2. **MRR = 0.61** → 平均排在 1.6 名左右。
3. **Hit@3 已经饱和（1.0）** → 这就是「指标饱和」陷阱：此时再加优化也测不出差别，需要扩充评测集。

---

## 9. 项目里对应哪块代码

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| 评测数据集 | `eval_dataset.py` | 14 条用例，含 `factual` / `refusal` 两类 |
| 检索评估 | `evaluate_rag.py:35-76` | `_mrr` / `_ndcg_at_k` / Hit@1 / Hit@3 |
| 文档级命中 | `evaluate_rag.py:24-33` | `_sources` 从 meta 取 source |
| **生成评估** | `evaluate_generation.py` | RAGAS 四指标 |
| 指标适用范围 | `evaluate_generation.py:85-88` | 拒答类只评 faithfulness |
| 上下文固定 | `evaluate_generation.py:92-105` | `_retrieve_contexts` 先固定 |
| 回答生成 | `evaluate_generation.py:106-126` | `max_tokens` 配置 |
| 指标调用 | `evaluate_generation.py:128-150` | `_metric_call` 按指标组装 |
| 单用例打分 | `evaluate_generation.py:152-175` | `_score_case` |
| **裁判配置** | `config.py:64-70` | `JUDGE_MODEL` / `JUDGE_API_KEY` / `JUDGE_BASE_URL` |
| 裁判说明 | `evaluate_generation.py:17-18` | 留空回退被测模型 |
| **一键入口** | `run_eval.py:28-112` | 检索 + 生成 + `--limit` / `--skip-*` / `--diff` |
| CI 返回码 | `run_eval.py:13` | 0=全通过，非 0=有失败 |
| 报告对比 | `run_eval.py:57-88` | 与上次报告比涨跌 |
| 报告落盘 | `backend/eval_reports/` | `generation.json` |
| 依赖 | `requirements-eval.txt` | ragas、langchain-community(钉 0.3.31) |

**⚠️ 一个真实的版本坑**：`ragas` 会 import `langchain_community.chat_models.vertexai`，而该模块在 langchain-community 0.4.x 被移除。所以 `requirements-eval.txt` 里**钉住了 0.3.31**。这种踩坑细节讲出来很有说服力。

---

## 10. 面试高频问答

**Q1：你怎么评估你的 RAG 效果？**
> 分两侧。检索侧评 Hit@1、Hit@3、MRR、nDCG@3，文档级命中。生成侧接 RAGAS 四指标：faithfulness 看答案是否忠于上下文（抗幻觉）、answer_relevancy 看是否切题、context_precision 看有用上下文是否排前面、context_recall 看标准答案信息是否被覆盖。自建 14 条标注用例，其中**专门有拒答边界用例**验证「资料里没有时不编造」。

**Q2：faithfulness 是怎么算的？**
> RAGAS 用 LLM 把答案拆成若干条陈述（claims），逐条判断这条陈述能否从召回的上下文推出，最后 `可推出数 / 总陈述数`。它直接度量幻觉，是 RAG 最核心的指标。

**Q3：answer_relevancy 的算法有什么特别的？**
> 它是**由答案反推问题**：让 LLM 根据答案想出可能会被问出这个答案的问题，再和原始问题算嵌入相似度。所以答案越泛化、越「说了等于没说」，反推的问题越分散，得分越低。它惩罚的是空洞答案。

**Q4：为什么要做裁判模型分离？**
> 让被测模型给自己打分会系统性偏高，而且重复打分会抖动。评估的可靠性取决于裁判比被测更强更稳定。所以我用 `JUDGE_MODEL` 独立配置裁判，报告里会标注用的是哪个模型，如果和被测同源会打印警告。

**Q5：拒答用例为什么只评 faithfulness？**
> 因为 context_precision / context_recall 需要标准答案（reference），拒答类没有；answer_relevancy 是反推问题，对拒答也不适用。而 faithfulness 只依赖「答案 vs 上下文」，任何类别都能评——而且拒答类恰恰最能检验有没有编造。

**Q6：你发现了哪些评测陷阱？（★ 最强素材）**
> 三个：① **检索指标饱和**——Hit@3 长期接近 1.0，再加优化测不出差别，说明瓶颈在评测集难度而不是算法；② **裁判噪声**——同一条用例重复跑分数会抖，所以要关注均值和有效样本，不要解读 0.02 的波动；③ **context_precision 是排序口径**——它算 average precision 含位置权重，召回集合没变、只是把有用内容往前挪，分数也会涨，不知道这点会误判优化方向。

**Q7：评估怎么接进 CI？**
> `run_eval.py` 有明确的返回码设计：0 表示全部通过，非 0 表示有环节失败，可以直接用 exit code 做门禁。还有 `--limit` 快速验证、`--diff` 对比上次报告的指标涨跌。

**Q8：为什么评估时上下文要固定？**
> 因为 faithfulness 和 context_precision 都要求上下文可复现。如果每次评估都重新检索，上下文一变，两次结果就不可比了。所以流程是先检索一次拿到 contexts 固定住，再生成答案、再打分。

**Q9：你的评测集够吗？**
> 14 条偏少，这是当前的局限。现在的指标在这么小的集上容易饱和，所以下一步要扩充到 50~100 条并加入更难的问题（多跳、歧义、同义改写）。诚实讲，目前它适合做**回归检测**（改动前后对比），还不足以做绝对质量判断。

**Q10：Hit@3 饱和了怎么办？**
> 说明评测集失去区分度。两个方向：① 扩充数据集，加入更难的 query；② 换更敏感的指标（比如从 Hit@3 换成 MRR 或 nDCG@1）。我当时就是发现饱和后，把简历上「hit@2 验证混合检索提升」这个说法删掉了，因为它已经不成立。

---

## 11. 速记卡

```text
没有评估 = 只能靠感觉调参

检索指标：
  Hit@K   前 K 有没有（直观，但不看排序）
  MRR     正确结果排第几 → 1/名次（比 Hit@K 敏感）
  nDCG@K  折损累计增益：位置越靠后增益越低(1/log2(i+2))，再归一化

RAGAS 四指标：
  faithfulness        答案每句话能否在上下文找到依据 ★抗幻觉
                      算法：拆 claims → 逐条判蕴含 → 可推出/总数
  answer_relevancy    ★由答案反推问题，再和原问题比相似度
                      → 惩罚空洞/泛化答案
  context_precision   有用上下文是否排前面（average precision，含位置权重）
  context_recall      标准答案信息被召回覆盖多少（需 reference）

裁判分离：JUDGE_MODEL 独立配置，比被测更强更稳定
         同源会在报告里打印警告

数据集 14 条：factual(四指标) / refusal(只评 faithfulness)
  ★拒答边界用例 = 检验"该不该说不知道"，最有价值
  上下文固定 → 保证两次评估可比

三陷阱（最强素材）：
  ① 检索指标饱和(Hit@3≈1.0) → 瓶颈在评测集难度
  ② 裁判噪声(重复打分会抖) → 看均值和样本数
  ③ context_precision 是排序口径(含位置权重) → 别当精确率用

工程化：run_eval.py 一键跑 + exit code 供 CI + --diff 对比涨跌
坑：ragas 需 langchain-community==0.3.31（0.4.x 移除了 vertexai 模块）
局限：14 条偏少，够做回归检测，不够做绝对质量判断
```
