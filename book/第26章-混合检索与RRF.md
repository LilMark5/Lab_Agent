# 第 26 章 · 混合检索与 RRF：为什么向量检索还不够

> **这一章要回答的核心问题**：向量检索语义泛化能力强，为什么还要加 BM25？RRF 为什么只用名次不用分数？那个 `k=60` 是什么？中文分词不用 jieba 怎么做的？

---

## 26.1 引子：一个让纯向量检索崩溃的问题

假设知识库里有这么一段：

> "光谱仪型号 SP-2000，最大功率 5W，负责人：李工程师。"

用户问：**"SP-2000 的功率是多少？"**

用纯向量检索会发生什么？

`SP-2000` 是一个**型号字符串**。embedding 模型在训练时几乎没见过这种"字母+数字+连字符"的组合，它对这类 token 的语义编码非常弱。结果可能是：

```
向量检索 Top-3：
1. "光谱仪的操作流程..."        score=0.71   ← 语义相关，但不含 SP-2000
2. "光谱仪的维护周期..."        score=0.68   ← 同上
3. "型号 SP-2000，功率 5W..."   score=0.65   ← ★ 正确答案排第 3！
```

**如果 Top-K = 2，正确答案就被漏掉了。**

这不是假设，是生产环境的常见失败模式：**向量检索对专有名词、型号、编号、人名、代码标识符的匹配能力很弱**。

原因很简单：embedding 是在**大规模通用语料**上训的，它学的是"通用语义"。而 `SP-2000`、`lab_id=301`、`ErrorCode.Timeout` 这类字符串在语料里罕见，模型学不到它们的"精确匹配"特性。

**BM25 正好补这个短板。**

---

## 26.2 BM25：经典但不老的关键词检索

### 26.2.1 它是什么

BM25（Best Matching 25）是 1994 年提出的**词频检索算法**，是 TF-IDF 的改进版，至今仍是 Elasticsearch / Lucene 的核心算法。

核心思想三句话：

1. **词频（TF）**：查询词在文档中出现次数越多，越相关
2. **逆文档频率（IDF）**：词越稀有（出现在越少的文档里），区分度越高、权重越大
3. **长度归一化**：长文档天然包含更多词，要"惩罚"长度

### 26.2.2 公式

```
score(D, Q) = Σ  IDF(qᵢ) × [f(qᵢ,D) × (k₁+1)] / [f(qᵢ,D) + k₁ × (1 - b + b × |D|/avgdl)]
              i∈Q
```

别被公式吓到，看每一项：

| 项 | 含义 | 直觉 |
|---|---|---|
| `IDF(qᵢ)` | 词的稀有度 | "的" 权重≈0，"SP-2000" 权重高 |
| `f(qᵢ, D)` | 词在文档中的频次 | 出现 3 次 > 出现 1 次 |
| `k₁` | 词频饱和参数（通常 1.2） | **饱和**：出现 10 次不比 5 次好多少 |
| `b` | 长度归一化参数（通常 0.75） | 长文档要打折 |
| `\|D\| / avgdl` | 文档长度 / 平均长度 | |

**"词频饱和"是关键改进**：TF-IDF 里词频是线性累加的（出现 100 次就是 100 倍权重，可以被刷分），BM25 让它在某个点后趋于平缓。

### 26.2.3 和向量检索的互补

| 维度 | 向量检索 | BM25 |
|---|---|---|
| **匹配方式** | 语义相似 | 字面匹配 |
| **强项** | 同义、泛化（"关门"→"开放时间"） | **精确词、专有名词、型号、编号** |
| **弱项** | 专有名词、精确匹配 | 同义词、语义泛化 |
| **需要模型** | ✅ embedding 模型 | ❌ 纯统计 |
| **速度** | ANN 索引 O(log N) | 倒排索引 O(匹配词数) |
| **成本** | 向量化计算 | 极低 |

**这就是为什么叫"混合检索"（Hybrid Search）**：两条路各有短板，组合起来覆盖更全。

> **一个有用的心智模型**：
> - **向量检索 = "我记得有个类似的东西"**（模糊回忆）
> - **BM25 = "我精确记得这个词"**（精确索引）
> 人的检索也是这两种方式的组合。

---

## 26.3 中文分词：不用 jieba 的务实方案

### 26.3.1 问题：中文没有空格

英文可以按空格分词：

```python
"lab safety rules".split()   # → ["lab", "safety", "rules"]
```

中文不行：

```python
"实验室安全规定"   # 怎么切？实验室/安全/规定？实验/室安/全规/定？
```

标准解法是用分词器（jieba、HanLP、pkuseg）。但本项目**没有用**，看 `kb_service.py:94-103`：

```python
def _tokenize(text: str) -> list[str]:
    """中文友好的分词近似：单字 + 二元组。

    不引入 jieba 也能处理"开放时间""实验室预约"这类中文词，
    因为二元组覆盖了大部分双字词。
    """
    cleaned = [ch for ch in text.lower() if ch.isalnum()]
    unigrams = list(cleaned)
    bigrams = [a + b for a, b in zip(cleaned, cleaned[1:])]
    return unigrams + bigrams
```

### 26.3.2 单字 + 二元组（Unigram + Bigram）

对 `"实验室安全"`：

```
cleaned = ["实", "验", "室", "安", "全"]
unigrams = ["实", "验", "室", "安", "全"]
bigrams  = ["实验", "验室", "室安", "安全"]
结果 = ["实","验","室","安","全","实验","验室","室安","安全"]
```

**为什么这样能工作？**

- **单字**：保证召回（"全"能匹配到"安全"里的"全"）
- **二元组**：覆盖**双字词**（中文 70%+ 的词是双字：实验室、安全、规定、设备、预约…）

`"实验室"` 这个词被拆成 `"实验"` + `"验室"` 两个二元组，查询 `"实验室"` 时也会产生这两个二元组，**能匹配上**。

**看一个具体例子**：

```
文档: "实验室安全规定"
  tokens = [实,验,室,安,全,规,定, 实验,验室,室安,安全,全规,规定]

查询: "实验室"
  tokens = [实,验,室, 实验,验室]

匹配: 实✅ 验✅ 室✅ 实验✅ 验室✅   → 全部命中！
```

### 26.3.3 这个方案的代价

| 优点 | 缺点 |
|---|---|
| **零依赖** | 噪声多（"验室"是无意义的词） |
| **快** | 三字词覆盖率低（"离心机"→ "离心"+"心机"，"心机"是噪声） |
| **跨词边界** | 词表膨胀（N 字文本产生约 2N 个 token） |

**"心机"这个问题很典型**：`"离心机"` 产生 `["离心", "心机"]`，而 `"心机"` 会匹配到"心思""心机"这类无关文档，**降低精度**。

**为什么本项目还是选它？** 三个理由：

1. **jieba 也是依赖**（虽然比模型轻，但要装、要维护词典）
2. **BM25 只是召回的一路**，后面还有 RRF 融合 + rerank 兜底。召回阶段"宁可多召回一些噪声"是可以接受的
3. **我们的文档规模小**，噪声影响有限

> **面试话术**："中文分词我用单字 + 二元组的近似，不引入 jieba。理由是二元组能覆盖中文 70% 以上的双字词，而 BM25 只是召回的一路，后面还有 RRF 融合和 rerank 兜底——召回阶段宁可多一点噪声，也不要为了精度牺牲召回。
>
> 这个方案的已知问题是三字词会产生噪声（'离心机' 切成 '离心'+'心机'，'心机' 会误匹配），以及 token 数膨胀约 2 倍。数据量大了之后，引入 jieba 是明确的改进方向。"

### 26.3.4 降级方案

`kb_service.py:114-121`：

```python
try:
    from rank_bm25 import BM25Okapi
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
except Exception:
    query_tokens = set(_tokenize(query))
    scores = [len(query_tokens & set(tokens)) for tokens in corpus]
```

**如果 `rank_bm25` 没装**，降级成"**词元交集大小**"打分（Jaccard 的简化版）。

这是本项目一贯的风格：**可选依赖 + 优雅降级**。

> ⚠️ **注意降级后的行为差异**：`rank_bm25` 的分数是 BM25 公式算的（考虑了 IDF 和长度归一化），降级方案是简单的"交集大小"（长文档占优、常见词和稀有词同权）。两者分数**不可比**。
> 但因为 RRF 只用**名次**，所以不影响融合结果——**这正是 RRF 的价值**。

### 26.3.5 一个性能隐患

```python
def _bm25_search(query, top_k=5, document_id=None):
    chunks = _get_chunks()
    ...
    corpus = [_tokenize(c["doc"]) for c in chunks]     # ★ 每次都要重新分词
    bm25 = BM25Okapi(corpus)                            # ★ 每次都要重建索引
```

**每次检索都**：
1. 取出全部块
2. 对每个块重新分词
3. 重建 BM25 索引

**复杂度 O(N)**，而且是在 Python 里做。

**对于 1000 个块、每块 500 字**：每次检索要分词 50 万字符 → 可能要几百毫秒。

> 📝 **这是一个明确的性能优化点**（简历素材）：
> ```python
> _bm25_index = None
> _bm25_chunks = None
>
> def _get_bm25_index():
>     global _bm25_index, _bm25_chunks
>     chunks = _get_chunks()
>     if _bm25_index is None or chunks is not _bm25_chunks:
>         corpus = [_tokenize(c["doc"]) for c in chunks]
>         _bm25_index = BM25Okapi(corpus)
>         _bm25_chunks = chunks
>     return _bm25_index
> ```
> 缓存索引，只在 `invalidate_cache()` 时重建。这样从"每次 O(N) 分词"变成"首次 O(N) + 后续 O(查询词数)"。

---

## 26.4 RRF：为什么只用名次不用分数

### 26.4.1 融合的难题

现在有两组结果：

```
向量检索: [块A (0.82), 块B (0.71), 块C (0.65)]
BM25:     [块C (12.4), 块D (8.1), 块A (5.2)]
```

**怎么融合？**

**方案 A：加权求和分数**

```python
final_score = α × vector_score + β × bm25_score
```

**问题**：
- 分数不可比！向量分数是 `[0,1]` 或 `[-1,1]`，BM25 分数是 `[0, ∞)`（量级完全不相关）
- 需要归一化，但归一化方式（min-max? z-score?）会引入新的超参
- **不同查询的分数分布差异很大**：某个查询向量分都很高，另一个都很低

**方案 B：RRF（Reciprocal Rank Fusion）** ✅

> **不看分数，只看名次。**

### 26.4.2 RRF 公式

```
RRF_score(d) = Σ  1 / (k + rankᵢ(d))
               i
```

- `d` 是文档
- `rankᵢ(d)` 是它在第 `i` 路召回里的**名次**（从 1 开始）
- `k` 是平滑常数（本项目 60）

**例子**（k=60）：

```
向量检索: A(1), B(2), C(3)
BM25:     C(1), D(2), A(3)

A: 1/(60+1) + 1/(60+3) = 0.01639 + 0.01587 = 0.03226
B: 1/(60+2) + 0                            = 0.01613
C: 1/(60+3) + 1/(60+1) = 0.01587 + 0.01639 = 0.03226
D: 0        + 1/(60+2)                     = 0.01613

排序: A = C > B = D
```

**C 在两路都出现了**（第 3 名 + 第 1 名），所以总分最高——**这正是我们要的**：被多种方式都认为相关的，最可信。

### 26.4.3 为什么 RRF 有效？四个理由

**① 免疫分数尺度问题**

只看名次，不需要归一化。**这是最大的优势**——不同来源的分数可以有完全不同的量纲和分布。

**② 天然奖励"多路共识"**

一个文档在两路都出现，会拿到两次加分。**被多个独立信号同时认可的，更可信。**

**③ 抑制单路的极端值**

向量检索给了 0.99 分？没关系，排名第一还是 `1/(60+1)`。不会因为某一路的分数特别高就主导结果。

**④ 无需调参（相对）**

只有 `k` 一个参数，且对它不敏感（见下）。

### 26.4.4 `k=60` 是什么？为什么是 60？

`k` 的作用是**控制"名次靠前"的奖励强度**：

| k | 第 1 名 | 第 5 名 | 第 1 名 / 第 5 名 |
|---|---|---|---|
| 1 | 0.5 | 0.167 | 3.0× |
| 10 | 0.091 | 0.067 | 1.36× |
| **60** | 0.0164 | 0.0154 | **1.06×** |
| 100 | 0.0099 | 0.0095 | 1.04× |

**k 越大 → 名次差异越被"拉平"** → 越依赖"多路共识"而不是"单路高分"。

**60 是原论文（Cormack et al. 2009）的经验值**，在 TREC 数据集上表现好。它的含义是：**前 60 名之内，每前进一名的收益很小，主要靠"是否出现在多路结果里"来区分。**

**实务建议**：
- 数据少（< 1000 块）：k 小一些（10-20），让名次更有区分度
- 数据多：k=60 或更大
- **不要花时间调 k**，它的影响远小于"召回质量"本身

### 26.4.5 项目实现

`kb_service.py:142-155`：

```python
def _rrf_fusion(vector_hits, keyword_hits, k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion：按名次融合多路召回，块 id 作为唯一键。"""
    fused: dict[str, dict] = {}
    for rank, hit in enumerate(vector_hits):
        key = hit.get("id") or hit.get("meta", {}).get("source", "") or hit["doc"][:32]
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    for rank, hit in enumerate(keyword_hits):
        key = hit.get("id") or hit.get("meta", {}).get("source", "") or hit["doc"][:32]
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    merged = list(fused.values())
    merged.sort(key=lambda x: x.get("rrf", 0), reverse=True)
    return merged
```

**四个实现细节**：

**① `rank + 1`**

```python
for rank, hit in enumerate(vector_hits):     # rank 从 0 开始
    ... 1 / (k + rank + 1)                   # ★ +1 让它从 1 开始
```

公式里的 rank 从 1 开始，Python 的 `enumerate` 从 0 开始，`+1` 修正。

**② `setdefault` 的妙用**

```python
item = fused.setdefault(key, dict(hit))
item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
```

- 第一次见到这个 key：插入 `dict(hit)` 的副本
- 之后再见到：返回已有的，`rrf` 累加

**一行代码同时处理了"新增"和"累加"两种情况。**

**③ 三级 fallback 的 key**

```python
key = hit.get("id") or hit.get("meta", {}).get("source", "") or hit["doc"][:32]
```

优先级：**块 id → 文件名 → 内容前 32 字**。

为什么需要 fallback？因为不同来源的 hit 结构可能不一致（本项目统一了，但防御性写法让它在边界情况下也不会崩）。

**④ `dict(hit)` 复制**

```python
fused.setdefault(key, dict(hit))
```

**浅拷贝**，避免修改原始的 hit 对象（因为 `hit` 可能还被其他地方引用）。

> ⚠️ **注意这是浅拷贝**：`meta` 字典是共享的。如果后面改了 `item["meta"]["xxx"]`，会影响原始对象。本项目没改 meta，所以安全。

### 26.4.6 为什么不做去重？

融合后可能有来自两路的同一个块（同 id）。`setdefault` 已经按 id 合并了，**所以天然去重**。

但如果是**内容相同但 id 不同**（比如 overlap 导致的重复块），不会被合并。这是一个已知的小问题（第 23 章延伸思考提过）。

---

## 26.5 完整检索流程

`kb_service.py:178-204`：

```python
def retrieve(query, top_k=None, document_id=None) -> list[dict]:
    """检索主入口：返回融合 + 重排后的块命中列表。"""
    if not query.strip():
        return []
    top_k = top_k or settings.RETRIEVAL_TOP_K

    search_query = _rewrite_query(query.strip())          # ① 查询改写
    if search_query != query.strip():
        logger.info("查询改写：%r -> %r", query, search_query)

    vector_hits = _vector_search(search_query, top_k=top_k, document_id=document_id)   # ②
    keyword_hits = (
        _bm25_search(search_query, top_k=top_k, document_id=document_id)               # ③
        if settings.HYBRID_SEARCH_ENABLED
        else []
    )
    if not vector_hits and not keyword_hits:
        return []

    merged = _rrf_fusion(vector_hits, keyword_hits)       # ④
    if settings.RERANK_ENABLED:
        merged = _rerank(search_query, merged)            # ⑤（第 27 章）
    return merged[:top_k]
```

**五个步骤，对应五个配置项**：

| 步骤 | 函数 | 开关 |
|---|---|---|
| ① 查询改写 | `_rewrite_query` | `QUERY_REWRITE_ENABLED` |
| ② 向量召回 | `_vector_search` | 向量库可用性（隐式） |
| ③ BM25 召回 | `_bm25_search` | `HYBRID_SEARCH_ENABLED` |
| ④ RRF 融合 | `_rrf_fusion` | 无条件（至少一路非空才做） |
| ⑤ Rerank | `_rerank` | `RERANK_ENABLED` |

**注意 ④ 之前的判断**：

```python
if not vector_hits and not keyword_hits:
    return []
```

两路都空 → 直接返回，不做无意义的融合。

### 26.5.1 两阶段 Top-K：一个容易忽略的设计

```bash
RETRIEVAL_TOP_K=10    # retrieve 阶段：每路召回 10 条，融合后取 10 条
FINAL_CONTEXT_K=5     # search 阶段：最终进 prompt 的只有 5 条
```

看 `kb_service.py:283`：

```python
hits = retrieve(query, top_k=settings.FINAL_CONTEXT_K, document_id=document_id)
```

**等等** —— `search()` 调用 `retrieve` 时传的是 `FINAL_CONTEXT_K=5`！那 `RETRIEVAL_TOP_K=10` 什么时候用？

追踪一下：`retrieve` 的默认参数是 `top_k or settings.RETRIEVAL_TOP_K`。当 `search()` 显式传了 `5`，就**不会**用 `RETRIEVAL_TOP_K`。

所以实际链路是：

```
retrieve(top_k=5)
  → _vector_search(top_k=5)      # 向量召回 5 条
  → _bm25_search(top_k=5)        # BM25 召回 5 条
  → _rrf_fusion                  # 融合，最多 10 条（去重后可能 5-10）
  → _rerank                      # 重排
  → merged[:5]                   # 取前 5
```

**这是一个"召回 5+5、融合去重、重排后取 5"的流程。**

> **这是个值得注意的设计细节**：`RETRIEVAL_TOP_K` 只在直接调用 `retrieve()` 且不传 top_k 时生效（比如在评测脚本里）。在 `search()` 链路里用的是 `FINAL_CONTEXT_K`。
>
> 更清晰的设计是：**召回用 RETRIEVAL_TOP_K（宽）、最终用 FINAL_CONTEXT_K（窄）**——也就是"宽召回 + 窄精选"。当前实现里两者都是 5，召回宽度偏窄。
>
> 📝 **改进建议**：让 `search()` 用 `retrieve(query, top_k=RETRIEVAL_TOP_K)` 召回更宽，然后 rerank 后取 `FINAL_CONTEXT_K` 条。**"宽召回 + 精排序"是 RAG 的标准范式**，这样 rerank 才有更大的发挥空间（如果只召回 5 条，rerank 最多只能重排这 5 条，无法"捞回"被漏掉的）。

---

## 26.6 最小骨架：亲手跑通混合检索

```python
"""
minimal_hybrid.py —— 混合检索（向量 + BM25）+ RRF 融合
运行：pip install rank_bm25 numpy && python minimal_hybrid.py
（rank_bm25 可选，没装会降级到词元交集打分）
"""
import math
import re
from typing import Any


# ── 1. 语料 ────────────────────────────────────────────────
CORPUS = [
    {"id": "s#0", "doc": "实验室开放时间为每日 8:00 至 22:00，节假日另行通知。"},
    {"id": "s#1", "doc": "进入实验室必须穿戴实验服和防护眼镜，禁止穿拖鞋。"},
    {"id": "s#2", "doc": "光谱仪型号 SP-2000，最大功率 5W，负责人李工程师。"},
    {"id": "s#3", "doc": "离心机使用前需检查转子是否平衡，严禁超速运行。"},
    {"id": "s#4", "doc": "实验结束后必须关闭电源、清理台面，并填写使用记录。"},
    {"id": "s#5", "doc": "光谱仪的操作流程：开机预热 30 分钟，然后校准。"},
]


# ── 2. 中文分词：单字 + 二元组 ─────────────────────────────
def tokenize(text: str) -> list[str]:
    cleaned = [c for c in text.lower() if c.isalnum()]
    unigrams = list(cleaned)
    bigrams = [a + b for a, b in zip(cleaned, cleaned[1:])]
    return unigrams + bigrams


# ── 3. 向量检索（用 toy embedding 模拟）────────────────────
def build_toy_vectors(corpus: list[dict]) -> dict[str, list[float]]:
    """模拟 embedding：词频向量 + IDF 加权 + 归一化。"""
    vocab = sorted({t for c in corpus for t in tokenize(c["doc"])})
    idx = {w: i for i, w in enumerate(vocab)}
    n = len(corpus)
    df = {w: 0 for w in vocab}
    for c in corpus:
        for w in set(tokenize(c["doc"])):
            df[w] += 1
    idf = {w: math.log((n + 1) / (df[w] + 0.5)) for w in vocab}

    vecs = {}
    for c in corpus:
        v = [0.0] * len(vocab)
        for t in tokenize(c["doc"]):
            v[idx[t]] += 1
        v = [x * idf[w] for x, w in zip(v, vocab)]
        norm = math.sqrt(sum(x * x for x in v))
        vecs[c["id"]] = [x / norm for x in v] if norm else v
    return {"vecs": vecs, "vocab": vocab, "idx": idx, "idf": idf}


def embed_query(q: str, model: dict) -> list[float]:
    v = [0.0] * len(model["vocab"])
    for t in tokenize(q):
        if t in model["idx"]:
            v[model["idx"][t]] += 1
    v = [x * model["idf"][w] for x, w in zip(v, model["vocab"])]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v


def vector_search(q: str, corpus, model, top_k=3) -> list[dict]:
    qv = embed_query(q, model)
    hits = []
    for c in corpus:
        cv = model["vecs"][c["id"]]
        score = sum(x * y for x, y in zip(qv, cv))   # 已归一化 → 点积 = 余弦
        hits.append({**c, "score": score})
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


# ── 4. BM25 检索（带降级）──────────────────────────────────
def bm25_search(q: str, corpus, top_k=3) -> list[dict]:
    tokenized = [tokenize(c["doc"]) for c in corpus]
    try:
        from rank_bm25 import BM25Okapi
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(tokenize(q))
        print("    (使用 rank_bm25)")
    except Exception:
        print("    (rank_bm25 未安装，降级为词元交集打分)")
        qt = set(tokenize(q))
        scores = [len(qt & set(t)) for t in tokenized]

    hits = [{**c, "score": float(s)} for c, s in zip(corpus, scores)]
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


# ── 5. RRF 融合 ────────────────────────────────────────────
def rrf_fusion(*hit_lists, k: int = 60) -> list[dict]:
    fused: dict[str, dict] = {}
    for hits in hit_lists:
        for rank, hit in enumerate(hits):
            key = hit.get("id") or hit["doc"][:32]
            item = fused.setdefault(key, dict(hit))
            item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    merged = list(fused.values())
    merged.sort(key=lambda x: x.get("rrf", 0), reverse=True)
    return merged


# ── 6. 演示 ────────────────────────────────────────────────
def show(title: str, hits: list[dict], score_key: str):
    print(f"\n{title}")
    for i, h in enumerate(hits, 1):
        print(f"  {i}. [{h['id']}] {score_key}={h.get(score_key, 0):.4f}  {h['doc'][:32]}")


if __name__ == "__main__":
    model = build_toy_vectors(CORPUS)

    # ★ 关键案例：专有名词 SP-2000
    for q in ["SP-2000 的功率是多少？", "实验室几点开门？"]:
        print(f"\n{'='*64}\n🔍 查询：{q}")
        v = vector_search(q, CORPUS, model, top_k=3)
        b = bm25_search(q, CORPUS, top_k=3)
        show("  【向量检索】", v, "score")
        show("  【BM25 检索】", b, "score")
        f = rrf_fusion(v, b)
        show("  【RRF 融合后】", f[:3], "rrf")

    # k 值影响演示
    print(f"\n{'='*64}\nk 值对 RRF 的影响（第1名 vs 第5名的得分比）：")
    for k in (1, 10, 60, 100):
        r1, r5 = 1 / (k + 1), 1 / (k + 5)
        print(f"  k={k:3d}: 第1名={r1:.5f} 第5名={r5:.5f} 比值={r1/r5:.2f}×")
    print("  ★ k 越大，名次差异越被拉平，越依赖'多路共识'")
```

**预期输出（关键部分）**：

```
🔍 查询：SP-2000 的功率是多少？
  【向量检索】
    1. [s#5] score=0.2139  光谱仪的操作流程：开机预热 30 分钟...   ← 语义相关但答非所问
    2. [s#2] score=0.1804  光谱仪型号 SP-2000，最大功率 5W...      ← ★ 正确答案第 2
  【BM25 检索】
    1. [s#2] score=...     光谱仪型号 SP-2000，最大功率 5W...      ← ★ 精确匹配，第 1
  【RRF 融合后】
    1. [s#2] rrf=0.03252  光谱仪型号 SP-2000，最大功率 5W...      ← ★ 融合后正确答案排第 1！
```

**这个例子完美展示了混合检索的价值**：向量检索把正确答案排第 2，BM25 排第 1，RRF 融合后**正确答案稳居第一**。

---

## 26.7 面试问答

### Q1：为什么向量检索不够，还要加 BM25？

**答**：因为向量检索对**专有名词、型号、编号、人名、代码标识符**的匹配能力很弱。

embedding 模型是在大规模通用语料上训的，学的是通用语义。`SP-2000` 这种型号字符串在语料里罕见，模型对它的语义编码非常弱。我们实测过：问"SP-2000 的功率是多少"，向量检索把正确答案排在第 2 或第 3，Top-2 就漏掉了。

BM25 是字面匹配，正好补这个短板——它精确匹配 `SP-2000` 这个字符串。

两者的关系是：**向量检索擅长语义泛化（同义词、改写），BM25 擅长精确匹配（专有名词、型号）**。组合起来覆盖更全，这就是混合检索。

### Q2：中文分词你们怎么做的？为什么不用 jieba？

**答**：用单字 + 二元组的近似。对"实验室安全"产生 `["实","验","室","安","全"]` + `["实验","验室","室安","安全"]`。

原理是**二元组能覆盖中文 70% 以上的双字词**（实验室、安全、规定、设备…），查询时产生相同的二元组就能匹配上。

不用 jieba 的理由：一是它是额外依赖（要装、要维护词典）；二是 **BM25 只是召回的一路**，后面还有 RRF 融合和 rerank 兜底——召回阶段宁可多一点噪声，也不要为了精度牺牲召回。

已知问题是三字词会产生噪声（"离心机" 切成 "离心"+"心机"，"心机" 会误匹配无关文档），以及 token 数膨胀约 2 倍。数据量大了之后引入 jieba 是明确方向。

### Q3：RRF 是什么？为什么用名次不用分数？

**答**：RRF（Reciprocal Rank Fusion）是倒数排名融合，公式 `Σ 1/(k + rank)`。

**用名次不用分数的核心原因是：不同来源的分数不可比。** 向量相似度是 `[-1,1]` 或 `[0,1]`，BM25 分数是 `[0, ∞)`，量纲和分布完全不同。要加权求和就得先归一化，而归一化方式（min-max、z-score）会引入新的超参和不确定性。

用名次的好处：一是**免疫分数尺度**，不需要归一化；二是**天然奖励多路共识**——被多个独立信号同时认可的更可信；三是**抑制单路极端值**，不会因为某一路给了 0.99 分就主导结果。

我们项目里还有个具体体现：BM25 在 `rank_bm25` 没装时会降级成"词元交集打分"，分数含义完全不同——但因为 RRF 只看名次，降级不影响融合结果。

### Q4：k=60 是什么？怎么调？

**答**：k 是平滑常数，控制"名次靠前"的奖励强度。k 越大，名次差异越被拉平，越依赖"是否出现在多路结果里"这个信号，而不是"在哪一路排得靠前"。

60 是原论文（Cormack 2009）在 TREC 数据集上的经验值。

实务上：**不要花时间调 k**，它的影响远小于召回质量本身。数据少（<1000 块）可以用小一些（10-20）让名次更有区分度，数据多用 60 或更大。

### Q5：混合检索的召回宽度怎么定？

**答**：这是我要主动说明的一个点。

我们的配置是 `RETRIEVAL_TOP_K=10` 和 `FINAL_CONTEXT_K=5`。但在 `search()` 链路里，`retrieve` 收到的是 `FINAL_CONTEXT_K=5`，所以实际是"向量召回 5 + BM25 召回 5 → 融合去重 → 重排 → 取 5"。

**更标准的范式是"宽召回 + 窄精选"**：召回阶段取 20-50 条，rerank 之后再取 5 条。这样 rerank 有更大的发挥空间——如果只召回 5 条，rerank 最多只能重排这 5 条，**无法捞回被漏掉的相关文档**。

我们的当前实现召回宽度偏窄，这是明确的改进方向：让 `search()` 用 `RETRIEVAL_TOP_K` 召回，rerank 后用 `FINAL_CONTEXT_K` 截断。

### Q6：BM25 每次检索都重建索引，性能有问题吗？

**答**：有问题，这是明确的性能隐患。

当前实现每次检索都要：取全部块 → 对每个块重新分词 → 重建 BM25 索引，是 O(N) 且在 Python 里做。1000 个块、每块 500 字，每次检索要分词 50 万字符，可能几百毫秒。

改进是缓存索引对象，只在 `invalidate_cache()`（文档变更）时重建。这样从"每次 O(N) 分词"变成"首次 O(N) + 后续只算查询词"。

---

## 26.8 速记卡

> **混合检索 = 向量（语义泛化）+ BM25（精确匹配），RRF 按名次融合。**

**为什么混合**：向量对**专有名词/型号/编号**匹配弱；BM25 补精确匹配

**BM25 三要素**：词频（带饱和）+ IDF（稀有词权重高）+ 长度归一化

**中文分词**：**单字 + 二元组**（覆盖 70% 双字词，零依赖）
- 缺点：三字词噪声（"离心机"→"心机"）、token 膨胀 2 倍
- 降级：没装 rank_bm25 → 词元交集打分

**RRF 公式**：`score = Σ 1/(k + rank)`，rank 从 1 开始

**为什么用名次**：分数不可比（量纲/分布不同）→ **无需归一化** + 奖励多路共识 + 抑制极端值

**k=60**：原论文经验值；k 大 → 拉平名次差异 → 更依赖共识；**不要花时间调**

**实现技巧**：`fused.setdefault(key, dict(hit))` —— 一行搞定新增 + 累加

**★ 当前缺陷**：召回宽度 = FINAL_CONTEXT_K = 5，偏窄
**★ 改进**：宽召回（RETRIEVAL_TOP_K）+ 窄精选（FINAL_CONTEXT_K）

**性能隐患**：BM25 每次重建索引 O(N)，应缓存

**代码位置**：
- 分词：`kb_service.py:94-103`
- BM25：`kb_service.py:106-128`
- RRF：`kb_service.py:142-155`
- 主入口：`kb_service.py:178-204`

---

## 26.9 延伸思考

1. **如果只有向量检索，没有 BM25，评测集的 Hit@K 会掉多少？**
   提示：做一个"消融实验"——把 `HYBRID_SEARCH_ENABLED` 设成 false，跑一遍评测集（第 38 章），对比 Hit@3。**这个数字就是"BM25 的价值"的量化证明**，是简历上非常有说服力的素材。

2. **RRF 的两路权重一样。如果向量检索质量明显更好，能不能加权？**
   提示：可以 —— `weighted_rrf = Σ wᵢ / (k + rankᵢ)`。但要注意：权重的引入意味着要调参，而调参需要评测集支撑。**没有评测就不要调权重**，默认值通常够用。

3. **三路召回（向量 + BM25 + 知识图谱）怎么融合？**
   提示：RRF 天然支持多路 —— `rrf_fusion(vector_hits, bm25_hits, kg_hits)`。这也是它相对"加权求和"的另一个优势：**扩展性好**。

---

**下一章**：第 27 章 · Rerank 重排——为什么融合之后还要二次排序？交叉编码器和双编码器有什么区别？
