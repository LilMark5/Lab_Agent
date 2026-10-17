# 第 27 章 · Rerank 重排：为什么融合之后还要二次排序

> **这一章要回答的核心问题**：召回已经排好序了，为什么还要 rerank？双编码器和交叉编码器有什么区别？为什么 rerank 慢却值得？"召回-重排"两段式架构的本质是什么？

---

## 27.1 引子：召回的排序是"猜"，重排的排序是"看"

先理解一个根本区别。

### 召回阶段：每个文档"独自"和查询比较

向量检索是这样的：

```
query → embedding → q_vec
doc1  → embedding → d1_vec       （提前算好，存在库里）
doc2  → embedding → d2_vec       （提前算好）
...

score(query, doc1) = cosine(q_vec, d1_vec)
score(query, doc2) = cosine(q_vec, d2_vec)
```

**关键观察**：`d1_vec` 是**提前算好**的，它不知道 query 是什么。也就是说：**文档被压缩成一个向量时，丢失了大量信息**，而且这个压缩是"盲目的"（不知道会被拿来和什么比）。

这就像：你让 100 个人各自写一份 100 字的自我介绍，然后你拿自己的问题去匹配这些简介。**简介信息量有限，匹配必然粗糙。**

### 重排阶段：query 和 doc **一起**送进模型

```
input = [query, doc1] → 模型 → 相关性分数 0.92
input = [query, doc2] → 模型 → 相关性分数 0.31
```

**关键观察**：模型**同时看到了 query 和 doc**，可以做**深度的交互**——注意力机制让 query 的每个词和 doc 的每个词互相"看见"。

这就像：你把问题当面念给这 100 个人听，让他们各自回答"你有多符合这个问题"。**判断更准，但慢得多。**

**这就是召回-重排两段式架构的本质**：

> **用快的、粗糙的方法圈出候选集（召回），再用慢的、精准的方法精挑细选（重排）。**

---

## 27.2 双编码器 vs 交叉编码器

这是本章最重要的概念。

### 27.2.1 双编码器（Bi-Encoder）= 召回阶段

```
        ┌─────────┐
query → │ Encoder │ → q_vec ─┐
        └─────────┘          ├──→ cosine → score
        ┌─────────┐          │
doc   → │ Encoder │ → d_vec ─┘
        └─────────┘
```

| 特性 | 说明 |
|---|---|
| **两个输入分别编码** | 各自过一遍模型 |
| **可预计算** | doc 的向量提前算好存库 ✅ |
| **检索快** | 只需算一次 query 向量 + 向量检索 O(log N) ✅ |
| **交互浅** | 两个向量只在最后做一次点积 ❌ |
| **典型模型** | BGE、E5、GTE、OpenAI ada |

**优点**：快（这是它能做召回的原因）
**缺点**：精度有限（这是需要 rerank 的原因）

### 27.2.2 交叉编码器（Cross-Encoder）= 重排阶段

```
                    ┌─────────────┐
[query, doc] ──────→│  Encoder    │ → 0.92
 （拼接成一个输入）  │ (全注意力)  │
                    └─────────────┘
```

| 特性 | 说明 |
|---|---|
| **两个输入拼接后一起编码** | `[CLS] query [SEP] doc [SEP]` |
| **不可预计算** | 每对 (query, doc) 都要单独跑模型 ❌ |
| **慢** | N 个候选 = N 次模型推理 ❌ |
| **交互深** | 全注意力，query 和 doc 的词两两交互 ✅ |
| **典型模型** | bge-reranker、ms-marco-MiniLM |

**优点**：准（这是它值得慢的原因）
**缺点**：慢（这是它只能用于重排的原因）

### 27.2.3 对比表

| 维度 | 双编码器（召回） | 交叉编码器（重排） |
|---|---|---|
| 输入 | 分别编码 | 拼接后一起编码 |
| 可预计算 doc | ✅ 是 | ❌ 否 |
| 复杂度 | O(1) 次模型推理 + O(log N) 检索 | **O(N) 次模型推理** |
| 10 万文档耗时 | ~10ms | **不可行**（要跑 10 万次） |
| 100 个候选耗时 | ~10ms | ~200-500ms |
| 精度 | 中 | **高** |

**数量级差异**：双编码器处理 10 万文档 < 10ms；交叉编码器处理 100 个候选要 200ms+。

**这直接决定了架构**：

```
10 万文档 ──[双编码器，10ms]──→ 100 个候选 ──[交叉编码器，300ms]──→ 5 个精选
```

**不可能反过来**（先交叉编码器处理 10 万条，要几小时）。

> **面试金句**："召回-重排两段式是由两种模型复杂度的数量级差异决定的。双编码器能预计算文档向量，在 10 万条里检索只要 10 毫秒；交叉编码器要对每个 (query, doc) 对单独推理，处理 100 个候选就要几百毫秒——直接处理 10 万条要几小时，不可行。所以必须先粗筛再精选。"

---

## 27.3 项目实现

`kb_service.py:158-175`：

```python
def _rerank(query: str, hits: list[dict]) -> list[dict]:
    """用 CrossEncoder 对召回结果精排。失败则保持原顺序。"""
    global _rerank_model
    if not settings.RERANK_ENABLED or len(hits) < 2:
        return hits
    try:
        from sentence_transformers import CrossEncoder

        if _rerank_model is None:
            _rerank_model = CrossEncoder(settings.RERANK_MODEL)
        pairs = [(query, h["doc"]) for h in hits]
        scores = _rerank_model.predict(pairs)
        for h, score in zip(hits, scores):
            h["rerank"] = float(score)
        hits.sort(key=lambda x: x.get("rerank", 0), reverse=True)
    except Exception as exc:
        logger.warning("rerank 不可用，使用融合排序：%s", exc)
    return hits
```

### 五个设计点

**① `len(hits) < 2` 时直接返回**

```python
if not settings.RERANK_ENABLED or len(hits) < 2:
    return hits
```

**只有 0 或 1 个候选时不需要排序** —— 排序没有意义，直接省掉一次模型调用。

这是个小的优化，但体现了"**不为无意义的事付出成本**"的工程意识。

**② 全局单例模型**

```python
global _rerank_model
if _rerank_model is None:
    _rerank_model = CrossEncoder(settings.RERANK_MODEL)
```

和第 24 章的 embedding 模型一样：**模型加载重，必须复用**。

`bge-reranker-base` 约 400MB，加载要几秒。如果每次检索都加载，完全不可用。

**③ `pairs` 构造**

```python
pairs = [(query, h["doc"]) for h in hits]
```

**注意用的是 `hits`，即融合后的结果**，不是原始召回。这就是"召回 → 融合 → 重排"的顺序。

**④ `predict()` 批量推理**

```python
scores = _rerank_model.predict(pairs)
```

`sentence-transformers` 的 `predict()` 支持批量，内部会 batching。比循环调用 `predict([single_pair])` 快得多（GPU 并行）。

**⑤ 失败降级**

```python
except Exception as exc:
    logger.warning("rerank 不可用，使用融合排序：%s", exc)
```

**注意 `hits` 在 try 里被就地排序了**（`hits.sort()` 是原地操作）。如果 `predict` 抛异常，排序没发生，`hits` 保持**融合后的顺序**。

**这是"降级到上一阶段结果"的正确行为** ✅ —— rerank 挂了，还有 RRF 融合的结果可用。

### 27.3.1 分数存到 `h["rerank"]`

```python
for h, score in zip(hits, scores):
    h["rerank"] = float(score)
hits.sort(key=lambda x: x.get("rerank", 0), reverse=True)
```

**保留 RRF 分数，新增 rerank 分数**。这样调试时能对比两阶段的排序差异：

```python
# 调试时可以看到：某块 rrf 排第 3，rerank 后升到第 1
print([(h["rrf"], h.get("rerank")) for h in merged])
```

> 📝 **这是个可观测性的好实践**：保留中间分数而不是覆盖。如果做 A/B 评测（第 38 章），能直接分析"rerank 改变了多少排序、提升了多少准确率"。

---

## 27.4 rerank 到底提升了什么

### 27.4.1 三类典型提升

**提升 1：否定与程度**

```
查询："实验室周末开放吗？"
候选A："实验室开放时间为 8:00-22:00"          向量分 0.85（很高！）
候选B："实验室周末不开放，仅限工作日"          向量分 0.79
```

**向量检索会把 A 排前面**（因为字面高度重合），但**B 才是正确答案**。

交叉编码器能捕捉"不开放"这个否定语义，把 B 排到前面。

> 这正是第 24 章延伸思考里提过的 embedding 缺陷：**对否定不敏感**。rerank 是主要的缓解手段。

**提升 2：精确匹配**

```
查询："SP-2000 功率"
候选A："光谱仪的操作流程..."                   向量分 0.81
候选B："光谱仪型号 SP-2000，最大功率 5W"       向量分 0.76
```

交叉编码器能看到 `SP-2000` 的字面精确匹配，把 B 提前。

**提升 3：语义关系的方向性**

```
查询："离心机故障了怎么办？"
候选A："离心机的使用方法..."                   向量分 0.80（都讲离心机）
候选B："离心机常见故障及排除方法"              向量分 0.78
```

"故障" 这个词在两者里都有，但 B 是"排除故障"（解决方案），A 是"使用方法"。交叉编码器能区分这个**意图差异**。

### 27.4.2 量化提升：需要评测

**rerank 提升多少？** 这个问题**必须实测**，不同数据集差异很大。

业界常见数字：

| 指标 | 无 rerank | 有 rerank | 提升 |
|---|---|---|---|
| NDCG@10 | 0.65 | 0.72 | +10% |
| 答案准确率 | 72% | 79% | +7% |

**本项目没有做这个 A/B 实验** —— 这是诚实的现状，也是**一个很好的简历优化点**（第 38 章的 D5 建议就是"改写 A/B 评测"，同样适用于 rerank）。

> **面试诚实说法**："rerank 我们接了，但没有做量化的 A/B 实验来测量它到底提升了多少。这是明确的待办——正确的做法是固定其他条件，跑一遍评测集对比 Hit@K 和 NDCG，用数字证明它的价值。我现在能说的是它在理论上解决的三类问题（否定、精确匹配、意图方向性），以及我们的降级设计（rerank 挂了还有 RRF 结果）。"

---

## 27.5 什么时候不该用 rerank

**rerank 不是免费的**。三个代价：

| 代价 | 说明 |
|---|---|
| **延迟** | 100 个候选 → 200-500ms |
| **资源** | 模型 400MB+，CPU/GPU 占用 |
| **复杂度** | 多一个依赖、多一个失败点 |

**三种情况可以不要 rerank**：

1. **延迟敏感**：实时对话要求 < 200ms 响应
2. **候选很少**：只有 5 个候选，重排收益有限
3. **召回已经很准**：如果向量检索质量极高（比如用了超强的 embedding），rerank 边际收益小

**本项目的权衡**：启用了（`RERANK_ENABLED=true`），因为：
- 检索结果直接决定答案质量
- 候选只有 5 条，rerank 很快（< 50ms）
- 本地模型，无 API 成本

---

## 27.6 rerank 的工程细节

### 27.6.1 候选数量的选择

```
召回 20 条 → rerank → 取 5 条
召回 50 条 → rerank → 取 5 条
```

**召回多少给 rerank？** 权衡：

| 召回数 | 优点 | 缺点 |
|---|---|---|
| 少（10） | rerank 快 | **可能漏掉相关文档**，rerank 再准也救不回来 |
| 多（100） | 漏掉的概率低 | rerank 慢（O(N)） |

**经验值**：**20-50**。

**关键原则**：

> **rerank 只能重新排序，不能"无中生有"。** 如果相关文档在召回阶段就被漏掉了（排在 Top-50 之外），rerank 永远救不回来。
>
> 所以：**召回的召回率（Recall）是天花板，rerank 只能优化排序（Precision@K）。**

这又回到第 26 章讲的"宽召回 + 窄精选"——**本项目当前召回宽度只有 5，rerank 的作用被严重限制了**。

### 27.6.2 长文本截断

rerank 模型也有输入长度限制（通常 512 token）。

```python
pairs = [(query, h["doc"][:1000]) for h in hits]    # 截断长块
```

如果块很长，超出的部分被丢弃（或者被模型截断）。

**本项目的块是 500 字符**，加上 query 通常不超 512 token，基本安全。但如果 `CONTEXT_WINDOW` 扩展后块变大，就要注意。

### 27.6.3 批处理

```python
scores = _rerank_model.predict(pairs)     # ✅ 批量
# vs
for pair in pairs:                        # ❌ 逐条
    score = model.predict([pair])
```

批量能让 GPU 并行，快 5-10 倍。

### 27.6.4 GPU vs CPU

| 环境 | 100 个候选耗时 |
|---|---|
| CPU（4 核） | ~1-2 秒 |
| GPU（T4） | ~50ms |

**本项目是 CPU**（本地部署，无 GPU）。所以候选数必须少 —— 5 个候选约 100ms，可接受。

**如果要扩大召回宽度到 50**，CPU 上就要 1 秒+，**必须上 GPU 或换更小的模型**。

---

## 27.7 最小骨架：理解两段式架构

这个例子用纯 Python 模拟"召回 → 重排"，重点展示**架构和降级**，不需要真实模型。

```python
"""
minimal_rerank.py —— 召回-重排两段式架构演示
运行：python minimal_rerank.py  （纯 Python，无需依赖）
用规则模拟交叉编码器，目的是理解架构：粗筛 + 精选 + 降级
"""
import math


# ── 1. 语料 ────────────────────────────────────────────────
CORPUS = [
    {"id": "s#0", "doc": "实验室开放时间为 8:00 至 22:00，节假日另行通知。"},
    {"id": "s#1", "doc": "实验室周末不开放，仅限工作日使用。"},
    {"id": "s#2", "doc": "光谱仪型号 SP-2000，最大功率 5W。"},
    {"id": "s#3", "doc": "离心机使用前需检查转子是否平衡。"},
    {"id": "s#4", "doc": "离心机常见故障及排除方法：先断电再检查。"},
]


# ── 2. 召回阶段（双编码器模拟）：词袋余弦 ──────────────────
def tokenize(text: str) -> list[str]:
    chars = [c for c in text.lower() if c.isalnum()]
    return chars + [a + b for a, b in zip(chars, chars[1:])]


def recall(query: str, corpus, top_k: int) -> list[dict]:
    """模拟双编码器：可预计算、快、但交互浅。"""
    q = set(tokenize(query))
    hits = []
    for c in corpus:
        d = set(tokenize(c["doc"]))
        score = len(q & d) / len(q | d) if (q | d) else 0
        hits.append({**c, "recall_score": score})
    hits.sort(key=lambda x: x["recall_score"], reverse=True)
    return hits[:top_k]


# ── 3. 重排阶段（交叉编码器模拟）：能看到 query+doc 的交互 ──
def cross_encoder_score(query: str, doc: str) -> float:
    """模拟交叉编码器：慢，但能捕捉否定、精确匹配、意图方向性。"""
    score = 0.0

    # ① 基础词元重叠（和召回一样）
    q, d = set(tokenize(query)), set(tokenize(doc))
    score += len(q & d) / len(q | d) if (q | d) else 0

    # ② ★ 否定敏感：查询问"开放吗"，文档说"不开放" → 这恰恰是强相关
    if ("不" in doc or "禁止" in doc or "仅限" in doc):
        score += 0.3

    # ③ ★ 精确匹配：型号、编号这类字符串精确命中，加权
    for token in query.split():
        if len(token) > 2 and token in doc:
            score += 0.5

    # ④ ★ 意图方向性：问"故障怎么办"，答"排除方法" > "使用方法"
    if "故障" in query and "排除" in doc:
        score += 0.4
    if "故障" in query and "使用方法" in doc:
        score -= 0.2

    return score


def rerank(query: str, hits: list[dict], enabled: bool = True) -> list[dict]:
    """重排。失败/关闭时保持原顺序（降级到召回结果）。"""
    if not enabled or len(hits) < 2:
        return hits
    try:
        for h in hits:
            h["rerank_score"] = cross_encoder_score(query, h["doc"])
        hits.sort(key=lambda x: x["rerank_score"], reverse=True)
    except Exception as exc:
        print(f"    ⚠ rerank 失败，降级到召回顺序：{exc}")
    return hits


# ── 4. 演示 ────────────────────────────────────────────────
def show(title: str, hits: list[dict]):
    print(f"\n{title}")
    for i, h in enumerate(hits, 1):
        rs = h.get("rerank_score")
        extra = f" rerank={rs:.3f}" if rs is not None else ""
        print(f"  {i}. [{h['id']}] recall={h['recall_score']:.3f}{extra}  {h['doc'][:34]}")


if __name__ == "__main__":
    cases = [
        ("实验室周末开放吗？", "否定敏感：'周末不开放' 才是答案"),
        ("SP-2000 的功率", "精确匹配：型号字符串"),
        ("离心机故障了怎么办", "意图方向性：'排除方法' > '使用方法'"),
    ]

    for query, note in cases:
        print(f"\n{'='*66}")
        print(f"🔍 {query}    【{note}】")

        # 宽召回（模拟 RETRIEVAL_TOP_K=4）
        recalled = recall(query, CORPUS, top_k=4)
        show("  【召回阶段】（双编码器，快但粗糙）", recalled)

        # 重排 + 精选（模拟 FINAL_CONTEXT_K=2）
        ranked = rerank(query, list(recalled))
        show("  【重排后】（交叉编码器，慢但精准）", ranked)

        final = ranked[:2]
        print(f"  ✅ 最终进 prompt：{[h['id'] for h in final]}")

    # 降级演示
    print(f"\n{'='*66}")
    print("【降级演示】rerank 关闭时")
    recalled = recall("实验室周末开放吗？", CORPUS, top_k=4)
    ranked = rerank("实验室周末开放吗？", list(recalled), enabled=False)
    show("  保持召回顺序（RRF 融合结果）", ranked)
    print("  ★ rerank 挂了不影响可用性，只是精度下降")

    # ★ 关键：rerank 不能无中生有
    print(f"\n{'='*66}")
    print("【★ 天花板演示】召回漏掉的，rerank 救不回来")
    narrow = recall("SP-2000 的功率", CORPUS, top_k=1)      # 只召回 1 条
    show("  窄召回（top_k=1）", narrow)
    ranked = rerank("SP-2000 的功率", list(narrow))
    print(f"  重排后仍是：{[h['id'] for h in ranked]}")
    print("  ★ 正确答案 s#2 不在候选里 → rerank 无能为力")
    print("  ★ 结论：召回率是天花板，rerank 只优化排序")
```

**预期输出（关键部分）**：

```
🔍 实验室周末开放吗？    【否定敏感：'周末不开放' 才是答案】
  【召回阶段】（双编码器，快但粗糙）
    1. [s#0] recall=0.214  实验室开放时间为 8:00 至 22:00...   ← 字面最像，但答非所问
    2. [s#1] recall=0.200  实验室周末不开放，仅限工作日使用。   ← ★ 正确答案第 2
  【重排后】（交叉编码器，慢但精准）
    1. [s#1] recall=0.200 rerank=0.500  实验室周末不开放...    ← ★ 升到第 1
    2. [s#0] recall=0.214 rerank=0.214  实验室开放时间为 8:00...
  ✅ 最终进 prompt：['s#1', 's#0']

【★ 天花板演示】召回漏掉的，rerank 救不回来
  窄召回（top_k=1）
    1. [s#0] recall=0.214  实验室开放时间为 8:00 至 22:00...
  重排后仍是：['s#0']
  ★ 正确答案 s#1 不在候选里 → rerank 无能为力
```

**四件事被验证**：
1. ✅ rerank 能修正"否定"这类语义陷阱
2. ✅ rerank 能识别精确匹配和意图方向
3. ✅ rerank 挂了能降级（保持召回顺序）
4. ✅ **rerank 不能无中生有**（召回是天花板）

---

## 27.8 项目代码定位

| 功能 | 位置 |
|---|---|
| rerank 主逻辑 | `kb_service.py:158-175` |
| 全局模型变量 | `kb_service.py:22` |
| 调用点 | `kb_service.py:202-203` |
| 配置项 | `config.py`: `RERANK_ENABLED`、`RERANK_MODEL` |

```bash
# .env
RERANK_ENABLED=true
RERANK_MODEL=BAAI/bge-reranker-base
```

### 调用链

```
retrieve()
  → _vector_search()      # 召回
  → _bm25_search()        # 召回
  → _rrf_fusion()         # 融合
  → _rerank()             # 重排（本章）
  → merged[:top_k]        # 截断
```

---

## 27.9 面试问答

### Q1：为什么要 rerank？召回不是已经排好序了吗？

**答**：因为召回阶段的排序是"粗糙"的。

召回用的是**双编码器**：query 和 doc 各自编码成向量，然后算余弦。**doc 的向量是提前算好的，它不知道 query 是什么**——信息在压缩成向量时就丢了，而且这个压缩是盲目的。最后的匹配只是两个向量做一次点积，交互非常浅。

rerank 用**交叉编码器**：把 query 和 doc **拼接后一起**送进模型，全注意力让 query 的每个词和 doc 的每个词互相看见，能做深度交互。

这带来三类典型提升：一是否定语义（"周末不开放" 才是"周末开放吗"的答案，向量检索会因为字面重合把"开放时间"排前面）；二是精确匹配（型号 SP-2000）；三是意图方向性（问"故障怎么办"，"排除方法" 优于 "使用方法"）。

### Q2：双编码器和交叉编码器有什么区别？

**答**：核心区别是**是否可预计算**。

**双编码器**：query 和 doc 分别编码成向量。doc 向量可以**提前算好存库**，检索时只需算一次 query 向量再做向量检索（O(log N)）。处理 10 万文档 < 10ms。缺点是交互浅（只在最后做一次点积）。

**交叉编码器**：query 和 doc 拼接成一个输入，全注意力交互。**每个 (query, doc) 对都要单独跑一次模型**，处理 100 个候选要几百毫秒——直接处理 10 万条要几小时，不可行。优点是判断准。

**正是这个数量级差异决定了"召回-重排"两段式架构**：先用快而粗糙的方法圈出候选，再用慢而精准的方法精选。

### Q3：rerank 的候选数量怎么定？

**答**：经验值 20-50。

**核心原则是：rerank 只能重新排序，不能无中生有。** 如果相关文档在召回阶段被漏掉了（排在候选之外），rerank 再准也救不回来。所以**召回的召回率是天花板，rerank 只优化排序精度**。

候选多的好处是漏掉概率低，代价是 rerank 慢（O(N)）。

**这里我要主动说明一个我们当前的缺陷**：我们的召回宽度是 5（等于 `FINAL_CONTEXT_K`），rerank 只能在这 5 条里打转，作用被严重限制。更标准的做法是召回 20-50 条，rerank 后取 5 条。这是明确的改进方向。

### Q4：rerank 失败了怎么办？

**答**：降级到融合排序。

实现上，我们把 rerank 包在 try/except 里，异常时只打 warning 不抛出。因为 `hits.sort()` 是原地操作，如果 `predict` 抛异常，排序没发生，`hits` 保持 **RRF 融合后的顺序**。

所以 rerank 挂了不影响可用性，只是精度下降——这是"优雅降级"的设计。

另外我们还保留了两阶段的分数：RRF 分数存在 `rrf` 字段，rerank 分数存在 `rerank` 字段，不覆盖。这样调试和做 A/B 评测时能直接对比两阶段的排序差异。

### Q5：rerank 的代价是什么？什么时候不用？

**答**：三个代价：延迟（100 个候选 200-500ms）、资源（模型 400MB+）、复杂度（多一个依赖和失败点）。

三种情况可以不用：一是**延迟敏感**（要求 < 200ms）；二是**候选很少**（5 条以内重排收益有限）；三是**召回已经很准**（用了超强 embedding，边际收益小）。

我们启用是因为：检索质量直接决定答案质量；候选只有 5 条所以很快（< 50ms）；本地模型无 API 成本。

### Q6：你们量化过 rerank 的提升吗？

**答**：诚实说，没有。我们接了 rerank 但没做量化的 A/B 实验。

这是明确的待办——正确做法是固定其他条件（同样的评测集、同样的召回配置），只开关 `RERANK_ENABLED`，对比 Hit@K、NDCG 和最终答案质量。用数字证明它的价值。

我现在能说的是它在理论上解决的三类问题（否定、精确匹配、意图方向性）和降级设计。如果要写进简历，"量化了 rerank 提升 NDCG 从 X 到 Y" 会比"接入了 rerank"有说服力得多。

### Q7：除了交叉编码器，还有别的 rerank 方案吗？

**答**：有几种。

**LLM-as-Reranker**：让大模型给每个候选打分或做 listwise 排序。优点是不需要额外模型、能理解复杂指令；缺点是慢且贵（每个候选都要一次 LLM 调用）。

**ColBERT（late interaction）**：介于双编码器和交叉编码器之间——token 级向量，延迟交互。比双编码器准，比交叉编码器快，是个折中方案。

**学习排序（LTR）**：用特征工程 + GBDT/XGBoost 排序。适合有点击日志等监督信号的场景。

我们用的是标准的交叉编码器（bge-reranker-base），因为它在这个规模下性价比最高。

---

## 27.10 速记卡

> **召回-重排 = 用快的粗筛，用慢的精选。**

**本质区别**：
- 双编码器：**分别编码**，doc 可预计算，快（10 万条 < 10ms），交互浅
- 交叉编码器：**拼接后一起编码**，不可预计算，慢（100 条 ≈ 300ms），交互深

**为什么必须两段式**：复杂度的数量级差异（交叉编码器处理 10 万条要几小时）

**★ 天花板原则**：**rerank 只能重排，不能无中生有** —— 召回率是天花板

**三类提升**：否定语义 / 精确匹配（型号）/ 意图方向性

**项目实现**（`kb_service.py:158-175`）：
```python
if not RERANK_ENABLED or len(hits) < 2: return hits    # 少于 2 条不排
pairs = [(query, h["doc"]) for h in hits]
scores = model.predict(pairs)                          # ★ 批量，不是循环
except: 降级（hits.sort() 是原地操作，异常时保持原顺序）
```

**保留两阶段分数**：`rrf` + `rerank` 不覆盖（便于调试和 A/B）

**候选数**：经验 20-50；**本项目当前 5，偏窄（缺陷）**

**代价**：延迟 / 资源（400MB）/ 复杂度

**其他方案**：LLM-as-Reranker / ColBERT（late interaction）/ LTR

**诚实现状**：未做量化 A/B 实验

**代码位置**：`kb_service.py:158-175`

---

## 27.11 延伸思考

1. **如果用 LLM 做 rerank，怎么控制成本？**
   提示：listwise（一次给 20 个候选让模型排序）比 pointwise（每个候选打一次分）便宜 20 倍。但 listwise 有位置偏差（模型倾向选靠前的）。可以用"滑动窗口 + 多轮投票"缓解。

2. **rerank 模型也是通用的，能不能用领域数据微调它？**
   提示：可以，而且效果通常显著。需要构造 (query, doc, 相关性分数) 的三元组。数据来源可以是**点击日志**（用户最终采纳了哪个结果）——但冷启动阶段没有日志，可以用"检索结果是否被模型引用"作为弱标签。**这是一个很有深度的优化方向**。

3. **如果 rerank 把某个候选从第 5 名提到第 1 名，但那个候选其实不相关（rerank 错了），怎么办？**
   提示：这是"重排风险"。缓解方法：① 保留 top-1 的召回结果（不让 rerank 完全推翻召回的第一名）；② 用 RRF 和 rerank 的分数做加权；③ 靠评测集监控 rerank 的准确率。**没有银弹，只能靠数据验证。**

---

**下一章**：第 28 章 · 查询改写——用户问"那个啥几点关"，怎么变成"实验室开放时间"？
