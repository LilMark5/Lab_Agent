# 35 · RAG 检索管线全流程

> **速成定位**：RAG 岗必考。面试官让你「讲一遍检索流程」，你要能一口气说出七步并解释每一步为什么存在。
> **一句话**：切块 → 嵌入 → 向量召回 + BM25 召回 → RRF 融合 → CrossEncoder 重排 → 父上下文扩展 → 带引用返回。

---

## 目录

1. [RAG 解决什么问题](#1-rag-解决什么问题)
2. [总体流程图](#2-总体流程图)
3. [第一步：切块 Chunking](#3-第一步切块)
4. [第二步：嵌入 Embedding](#4-第二步嵌入)
5. [第三步：双路召回](#5-第三步双路召回)
6. [第四步：RRF 融合](#6-第四步rrf-融合)
7. [第五步：CrossEncoder 重排](#7-第五步crossencoder-重排)
8. [第六步：父上下文扩展](#8-第六步父上下文扩展)
9. [第七步：查询改写](#9-第七步查询改写)
10. [缓存与失效](#10-缓存与失效)
11. [最小可运行骨架](#11-最小可运行骨架)
12. [项目里对应哪块代码](#12-项目里对应哪块代码)
13. [面试高频问答](#13-面试高频问答)
14. [速记卡](#14-速记卡)

---

## 1. RAG 解决什么问题

**RAG = Retrieval-Augmented Generation**（检索增强生成）。

大模型有三个硬伤，RAG 逐一应对：

| 硬伤 | RAG 的解法 |
| --- | --- |
| 知识过时（训练截止日期） | 从你的知识库实时检索 |
| 不知道私有数据 | 检索企业内部文档 |
| **会编造（幻觉）** | 给模型依据，并要求「没检索到就说不知道」 |

本项目的实证：评测数据集里有**专门的拒答边界用例**——「资料没有时不许编造」，见 `backend/eval_dataset.py` 的 14 条标注用例。

---

## 2. 总体流程图

```text
离线（建索引）：文档 → 切块 → 嵌入 → 存入向量库
在线（检索）  ：
  用户提问
    → [可选] 查询改写（口语 → 规范检索词）
    → 向量召回 top_k ┐
    → BM25 召回 top_k ┴→ RRF 融合 → CrossEncoder 重排 → 取 top_k
    → 父上下文扩展（命中块前后各 N 块）
    → 拼成「[文件名#块号]\n内容」带引用文本
    → 塞进模型上下文
```

**七步，每一步都有存在理由**：

| 步骤 | 为什么需要 |
| --- | --- |
| 切块 | 文档太长塞不进上下文；小块检索更精准 |
| 嵌入 | 让「语义相近但用词不同」也能匹配 |
| BM25 | 补向量的短板：专有名词、精确词 |
| RRF | 两路排序分数不可比，只能按**名次**融合 |
| rerank | 双塔召回精度不够，用交叉编码器精排 |
| 父上下文 | 小块切碎了语义不完整，扩展回上下文 |
| 引用 | 可溯源，用户能核对，减少幻觉 |

---

## 3. 第一步：切块

### 3.1 为什么不能整篇塞进去

- 上下文窗口有限；
- 整篇作为一个向量，语义被稀释，检索不准；
- 成本：token 越多越贵。

### 3.2 递归字符切分（`kb_chunking.py`）

分隔符按「粗 → 细」排列：

```python
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
```

算法：

1. 找**第一个能命中**的分隔符切分；
2. 切出来的片段若仍超过 `chunk_size`，**换下一级分隔符递归再切**；
3. 把小片段合并成不超过 `chunk_size` 的块，合并时保留 `chunk_overlap`。

**为什么要 overlap**：如果一句话正好卡在块边界，切完两边都不完整。重叠一部分保证边界处的语义不丢。

配置（`config.py:76-78`）：

```python
CHUNK_SIZE: int = 200       # 按字符数，对中文友好
CHUNK_OVERLAP: int = 40
```

**为什么按字符不按 token**：注释写明「用 `len()` 计长度，按字符切，对中文更直接，不引入 `langchain-text-splitters` 依赖」。中文一个字信息量远大于英文一个字母，按字符切对中文更合理。

### 3.3 元数据是后续所有步骤的基础

`kb_chunking.py:116-127`：

```python
{
    "id": f"{path.stem}#{index}",          # 唯一键，用于去重和 RRF 融合
    "doc": chunk_text,                     # 块正文
    "meta": {
        "source": path.name,               # 文件名 → 用于引用标注 + 父上下文定位
        "chunk_index": index,              # 块序号 → 用于父上下文扩展
        "document_id": "static",           # 归属文档 → 用于删除/范围过滤
    },
}
```

- `document_id="static"` 表示内置知识库；上传文档用其注册 ID。
- **这个 `document_id` 是后面「只搜内置知识库 / 只搜上传文档」开关的实现基础**。

---

## 4. 第二步：嵌入

`vector_store.py:31-42`：

```python
def _embed_texts(texts: list[str]) -> list[list[float]]:
    global _sentence_model
    if _sentence_model is None:
        _sentence_model = SentenceTransformer(EMBEDDING_MODEL)
    return _sentence_model.encode(texts, normalize_embeddings=True).tolist()
```

- 模型：`BAAI/bge-small-zh-v1.5`（中文优化，512 维）。
- **模型实例必须复用**：加载很重，不能每次检索重新加载（注释写明了）。
- **`normalize_embeddings=True`**：归一化后，余弦相似度 = 向量点积，pgvector 的 `<=>` 算子直接可用。

维度动态获取（`get_embedding_dim()`）：

```python
_embedding_dim = len(_embed_texts(["dim"])[0])
```

**为什么动态**：写死 512 会在换模型后导致建表/建索引失败。动态获取后，pgvector 侧能检测维度变化并**自动重建表**（见第 12 节）。

---

## 5. 第三步：双路召回

### 5.1 为什么需要两路

| 路 | 擅长 | 不擅长 |
| --- | --- | --- |
| **向量召回** | 语义相近、同义改写（「怎么借实验室」vs「实验室借用流程」） | 精确型号、专有名词、罕见词 |
| **BM25** | 关键词精确匹配（「LD-2000 光谱仪」） | 语义泛化 |

**只做向量召回的典型失败**：用户问设备型号，向量把「光谱仪」泛化成一堆相关设备，精确型号反而没排上。**混合检索就是为了解决这个**。

### 5.2 BM25 是什么

基于词频-逆文档频率的**概率排序**函数：
- 词在本文档出现次数越多，得分越高（但有饱和，不会无限涨）；
- 词在越多文档出现（逆文档频率低），区分度越低，得分贡献越小。

### 5.3 中文分词的处理（项目巧思）

`kb_service.py:94-103`：

```python
def _tokenize(text: str) -> list[str]:
    """中文友好的分词近似：单字 + 二元组。"""
    cleaned = [ch for ch in text.lower() if ch.isalnum()]
    unigrams = list(cleaned)
    bigrams = [a + b for a, b in zip(cleaned, cleaned[1:])]
    return unigrams + bigrams
```

**为什么不引入 jieba**：增加依赖 + 词典维护。用**单字 + 二元组**（"开放时间" → `开,放,时,间,开放,放时,时间`），二元组覆盖了绝大多数中文双字词，效果够用且零依赖。

BM25 不可用时还有降级（`kb_service.py:119-121`）：退化为「查询词与文档词的交集大小」。

---

## 6. 第四步：RRF 融合

`kb_service.py:142-155`：

```python
def _rrf_fusion(vector_hits, keyword_hits, k: int = 60) -> list[dict]:
    fused: dict[str, dict] = {}
    for rank, hit in enumerate(vector_hits):
        key = hit.get("id") or ...
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    # keyword_hits 同样处理
    merged.sort(key=lambda x: x.get("rrf", 0), reverse=True)
    return merged
```

**公式**：`RRF_score = Σ 1 / (k + rank)`（k=60 是经验值，抑制头部权重）

### 为什么不能用分数直接相加

> **面试重点**：向量相似度是 0~1 的余弦值，BM25 分数可能是 0~20 的无界值，**两者量纲完全不同，不可比**。任何归一化都依赖数据分布假设。RRF 只用**名次**，天然免疫量纲问题——这是它成为工业界标配融合算法的原因。

**k 的作用**：k 越大，名次差异对分数的影响越小（第一名和第 100 名的差距被压缩）。60 是原始论文的经验值。

---

## 7. 第五步：CrossEncoder 重排

`kb_service.py:158-175`：

```python
pairs = [(query, h["doc"]) for h in hits]
scores = _rerank_model.predict(pairs)
hits.sort(key=lambda x: x.get("rerank", 0), reverse=True)
```

### 双塔 vs 交叉编码器（面试必考对比）

| | 双塔（Bi-Encoder） | 交叉编码器（CrossEncoder） |
| --- | --- | --- |
| 输入 | query 和 doc **分别**编码成向量 | query 和 doc **拼接后一起**过模型 |
| 速度 | **快**：doc 向量可离线算好，检索时只算 query | **慢**：每个 (query, doc) 对都要跑一次模型 |
| 精度 | 一般 | **高**：能建模词之间的交互 |
| 用途 | **召回**（从百万中捞百条） | **重排**（从百条中排前十） |

**这就是为什么必须两段式**：直接用 CrossEncoder 对全库打分是不可行的（百万次模型推理）；只用它对召回的 top_k 打分则成本可控。

本项目模型：`BAAI/bge-reranker-base`。

**降级**：rerank 不可用（模型没下载/报错）时保持 RRF 顺序，不影响可用性（`kb_service.py:173-174`）。

---

## 8. 第六步：父上下文扩展

### 8.1 小块 vs 大块的矛盾

- **小块检索准**（语义集中），但**信息不完整**（可能只有半句话）。
- **大块信息全**，但检索不准（语义稀释）。

### 8.2 解法：小块检索，大块返回

`kb_service.py:207-227`：

```python
def _expand_context(hit, window=None) -> str:
    source = hit["meta"].get("source")
    chunk_index = hit["meta"].get("chunk_index")
    document_id = hit["meta"].get("document_id")

    # 找出同源同文档的块（按 chunk_index 排序）
    same_source = [c for c in _get_chunks()
                   if c["meta"].get("source") == source
                   and c["meta"].get("document_id") == document_id]
    if not same_source:
        return hit.get("doc", "")     # 动态上传文档不在静态缓存里 → 返回块本身

    low = max(0, int(chunk_index) - window)
    high = min(len(same_source), int(chunk_index) + window + 1)
    return "\n".join(c["doc"] for c in same_source[low:high])
```

`CONTEXT_WINDOW=1`：命中块前后各扩 1 块。

**边界处理**（面试加分）：`if not same_source: return hit["doc"]` —— 动态上传的文档可能不在静态块缓存里，这时直接返回命中块本身，不能返回空。

### 8.3 引用标注

`kb_service.py:287-294`：

```python
parts.append(f"[{source}#{chunk_index}]\n{context}")
```

输出形如：

```text
[实验室安全规范.md#12]
第 12 块的内容……

[量子实验室说明.md#3]
第 3 块的内容……
```

**为什么必须带引用**：① 用户能核对来源，建立信任；② SYSTEM_PROMPT 里要求模型「注明依据的文件名」，从机制上抑制编造；③ 评测时可以用引用判断检索是否命中。

---

## 9. 第七步：查询改写

`kb_service.py:38-64`：

```python
def _rewrite_query(question: str) -> str:
    if not settings.QUERY_REWRITE_ENABLED:
        return question
    if not settings.LLM_API_KEY:
        return question
    try:
        resp = _rewrite_client.chat.completions.create(...)
        rewritten = (resp.choices[0].message.content or "").strip()
        return rewritten or question        # 改写为空则回退
    except Exception as exc:
        logger.warning("查询改写失败，回退原始问题：%s", exc)
        return question                    # 失败也回退
```

**解决什么**：用户问「那个能做实验的地方几点开门啊」，口语化、指代模糊。改写成「实验室开放时间」后召回更好。

**三重降级**（面试要讲）：
1. 开关关闭 → 原样返回（默认 `False`，因为要多一次 LLM 调用，有延迟成本）；
2. 没有 API Key → 原样返回；
3. 调用失败或返回空 → 原样返回。

> **诚实提示**：这个功能目前**默认关闭且没有 A/B 对比数据**。面试如果讲，就说「已实现并有降级，但改写效果的量化对比还在进行中」——不要吹成已验证的收益。

---

## 10. 缓存与失效

`kb_service.py:265-296`：

```python
cache_key = f"rag:v{_corpus_version}:{scope}:" + hashlib.md5(query.encode()).hexdigest()
cached = _cache_get(cache_key)
if cached:
    return cached
```

**缓存键的三段设计**：

| 段 | 作用 |
| --- | --- |
| `v{_corpus_version}` | **语料版本号**：文档增删时 `invalidate_cache()` 会 `+1`，旧缓存自动失效 |
| `{scope}` | 检索范围（all / static / 某文档 ID） |
| `md5(query)` | 查询内容 |

> **注意一个诚实点**：这是**查询哈希精确缓存**，不是「相似问题缓存」。同样的问法才命中，换个说法就不命中。（简历上曾误写成「相似问题缓存」，已更正。）

Redis 未配置时 `_redis_client()` 返回 None，缓存直接跳过，**功能不受影响**。

---

## 11. 最小可运行骨架

零依赖实现「切块 + BM25 + RRF + 父上下文」的核心逻辑，用**字符重合度**模拟向量分数，纯标准库即可运行。

```python
"""最小骨架：切块 → 双路召回 → RRF 融合 → 父上下文扩展 → 带引用输出。
纯标准库，不需要任何向量模型，用来理解 RAG 的数据流。"""

import math
import re
from collections import Counter

# ============ 准备语料 ============
DOC = """实验室开放时间为每天 8:00 至 22:00，节假日另行通知。
进入实验室必须穿戴实验服和防护眼镜，禁止穿拖鞋。
预约成功后状态为待审核，需要管理员审核通过后才能使用。
危险化学品的领用需要导师签字，并在台账上登记。
设备 LD-2000 光谱仪的预约需要提前一天提交申请。"""

SEPARATORS = ["\n", "。", "！", "？", "；", "，", " ", ""]
CHUNK_SIZE = 40
CHUNK_OVERLAP = 10


# ============ 1. 切块（简化版递归切分）============
def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按分隔符从粗到细切，再把小片合并成 <= size 的块。"""
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, cur = [], ""
    for p in parts:
        # 长句再按句号切
        for s in re.split(r"[。！？；]", p):
            s = s.strip()
            if not s:
                continue
            if len(cur) + len(s) > size and cur:
                chunks.append(cur)
                cur = cur[-overlap:] + s          # 保留 overlap 保证边界语义
            else:
                cur = (cur + "。" + s) if cur else s
    if cur:
        chunks.append(cur)
    return chunks


chunks = split_text(DOC)
print(f"切块结果（{len(chunks)} 块）：")
for i, c in enumerate(chunks):
    print(f"  #{i}: {c}")


# ============ 2. 中文分词：单字 + 二元组 ============
def tokenize(text: str):
    cleaned = [ch.lower() for ch in text if ch.isalnum()]
    return cleaned + [a + b for a, b in zip(cleaned, cleaned[1:])]


corpus_tokens = [tokenize(c) for c in chunks]


# ============ 3. 路 A：BM25 关键词召回 ============
def bm25_scores(query: str):
    """极简 BM25：这里用「词频 × 逆文档频率」近似，演示排序思想。"""
    q = tokenize(query)
    N = len(corpus_tokens)
    df = Counter()
    for tokens in corpus_tokens:
        for w in set(tokens):
            df[w] += 1
    out = []
    for tokens in corpus_tokens:
        tf = Counter(tokens)
        score = 0.0
        for w in q:
            if w in tf:
                idf = math.log((N - df[w] + 0.5) / (df[w] + 0.5) + 1)
                score += tf[w] * idf
        out.append(score)
    return out


# ============ 4. 路 B：向量召回（用字符重合度模拟余弦相似度）============
def vector_scores(query: str):
    q = set(tokenize(query))
    out = []
    for tokens in corpus_tokens:
        t = set(tokens)
        # 模拟余弦相似度：|交集| / sqrt(|q| * |d|)
        out.append(len(q & t) / math.sqrt(len(q) * len(t) + 1e-9))
    return out


# ============ 5. RRF 融合：只按名次，不看分数（量纲不可比）============
def rrf_fusion(*score_lists, k: int = 60, top_k: int = 3):
    fused = {}
    for scores in score_lists:
        # 按分数降序得到名次
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        for rank, idx in enumerate(ranked):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    return [i for i, _ in ordered[:top_k]]


# ============ 6. 父上下文扩展：命中块前后各扩 window 块 ============
def expand(idx: int, window: int = 1):
    low = max(0, idx - window)
    high = min(len(chunks), idx + window + 1)
    return "\n".join(chunks[low:high])


# ============ 7. 完整检索 ============
def retrieve(query: str, top_k: int = 3):
    v, b = vector_scores(query), bm25_scores(query)
    idxs = rrf_fusion(v, b, top_k=top_k)
    return [{"index": i, "source": "实验室规则.md", "text": expand(i)} for i in idxs]


if __name__ == "__main__":
    q = "LD-2000 光谱仪怎么预约"
    print(f"\n查询：{q}")
    print("\n=== 单看向量路（字符重合）===")
    print([round(s, 3) for s in vector_scores(q)])
    print("=== 单看 BM25 路 ===")
    print([round(s, 3) for s in bm25_scores(q)])
    print("\n=== RRF 融合后的结果（带引用 + 父上下文）===")
    for h in retrieve(q):
        print(f"\n[实验室规则.md#{h['index']}]\n{h['text']}")
```

**怎么观察混合检索的价值**：把 `q` 换成精确型号（如 `LD-2000`），你会看到 **BM25 路把正确的块排到第一**，而向量路可能因为语义泛化排错——这就是必须做双路的实证。

---

## 12. 项目里对应哪块代码

| 步骤 | 文件:行 | 关键内容 |
| --- | --- | --- |
| 切块 | `kb_chunking.py:15` | `SEPARATORS` 从 `\n\n` 到 `""` |
| 递归切分 | `kb_chunking.py:51-88` | `_split_recursive` |
| 合并带 overlap | `kb_chunking.py:26-48` | `_merge_splits` |
| 生成块元数据 | `kb_chunking.py:116-127` | `id / doc / meta(source, chunk_index, document_id)` |
| 上传文档切块 | `kb_chunking.py:131-146` | `chunk_document_text` |
| 嵌入 | `vector_store.py:31-42` | `SentenceTransformer` + `normalize_embeddings=True` |
| 动态维度 | `vector_store.py:45-50` | `get_embedding_dim()` |
| 语料缓存 | `kb_service.py:67-84` | `_get_chunks()`，向量库优先，失败回退静态文件 |
| 中文分词 | `kb_service.py:94-103` | 单字 + 二元组，不引 jieba |
| BM25 召回 | `kb_service.py:106-128` | 含降级：退化为词交集 |
| 向量召回 | `kb_service.py:131-139` | 失败返回空，不崩 |
| **RRF 融合** | `kb_service.py:142-155` | `1/(k+rank+1)`，k=60 |
| **rerank** | `kb_service.py:158-175` | `CrossEncoder`，失败保持原序 |
| **查询改写** | `kb_service.py:38-64` | 三重降级 |
| **检索主入口** | `kb_service.py:178-204` | 改写 → 双路 → 融合 → rerank → 截断 |
| **父上下文** | `kb_service.py:207-227` | 含「动态文档不在缓存」的边界 |
| **带引用输出** | `kb_service.py:265-296` | `[source#chunk_index]` + 缓存 |
| 缓存失效 | `kb_service.py:87-91` | `invalidate_cache()` → `_corpus_version += 1` |
| 启动预热 | `kb_service.py:304-306` / `main.py:38-44` | `warmup()`，30 秒超时 |
| 配置 | `config.py:72-97` | `CHUNK_SIZE/OVERLAP`、`RETRIEVAL_TOP_K=5`、`FINAL_CONTEXT_K=3`、`CONTEXT_WINDOW=1`、`HYBRID_SEARCH_ENABLED`、`RERANK_ENABLED`、`QUERY_REWRITE_ENABLED` |

**两条调用链**：

```text
HTTP：POST /api/kb/search → api/kb.py → kb_service.search()
AI  ：Agent 调 search_lab_docs → agent_tools.py:81 → kb_service.search()
```

---

## 13. 面试高频问答

**Q1：讲一遍你的 RAG 流程。**
> 七步：离线把文档递归切块（200 字符，40 重叠）并用 bge-small-zh 嵌入存向量库。在线时先可选做查询改写，然后向量和 BM25 双路各召回 top5，用 RRF（k=60）按名次融合，再用 bge-reranker 交叉编码器精排，取 top3，对每个命中块做父上下文扩展（前后各 1 块），最后拼成带 `[文件名#块号]` 引用的文本塞给模型。

**Q2：为什么用混合检索？只用向量不行吗？**
> 不行。向量擅长语义泛化，但对**精确型号、专有名词**效果差——用户问「LD-2000 光谱仪」，向量可能返回一堆泛化的设备介绍，精确型号反而没排上。BM25 正好补这个短板。反过来 BM25 处理不了同义改写，所以两路必须都有。

**Q3：RRF 为什么按名次而不是按分数融合？**
> 因为向量相似度是 0~1 的余弦值，BM25 是无界分数，**量纲完全不同，不可比**，任何归一化都要依赖数据分布假设。RRF 只用名次 `1/(k+rank)`，天然免疫量纲问题，这是它成为工业界标配的原因。k=60 是论文经验值，用来抑制头部权重。

**Q4：双塔和交叉编码器的区别？为什么不能只用交叉编码器？**
> 双塔把 query 和 doc 分别编码，doc 向量能离线算好，检索时只算 query，所以能从百万条里快速捞百条，但精度一般。交叉编码器把两者拼接后一起过模型，能建模词间交互，精度高，但**每个 (query, doc) 对都要跑一次模型**。所以必须两段式：双塔负责召回，交叉编码器只对召回的 top_k 精排。

**Q5：为什么要父上下文扩展？**
> 小块检索准但信息不完整，大块信息全但检索不准。解法是**小块检索、大块返回**：命中后用 `source + chunk_index` 找到同源文档的相邻块，前后各扩 1 块拼起来。这样既保证了检索精度，又给了模型完整的上下文。

**Q6：怎么处理中文分词？**
> 没用 jieba（多一个依赖、词典要维护），用**单字 + 二元组**近似。比如「开放时间」生成 `开,放,时,间,开放,放时,时间`，二元组覆盖了绝大多数中文双字词，效果够用且零依赖。

**Q7：chunk_size 怎么定的？**
> 200 字符、40 重叠，按字符切（对中文比按 token 更直接）。这个值偏小是为了提高检索精度，然后用父上下文扩展补偿信息完整性。真实调参应该做网格搜索，用检索指标（Hit@K/MRR）来选。

**Q8：怎么防止模型编造？**
> 三层：① 检索返回空时直接返回「没有检索到相关的资料」，不给模型发挥空间；② 输出强制带 `[文件名#块号]` 引用，SYSTEM_PROMPT 要求模型必须注明依据；③ 评测集里专门有**拒答边界用例**验证「资料里没有时不编造」。

**Q9：文档更新了怎么办？**
> `invalidate_cache()` 清空块缓存并把 `_corpus_version` 加 1。Redis 缓存键里带这个版本号，所以**新增/删除文档后旧缓存自动失效**，不用手动清 Redis。

**Q10：查询改写有什么风险？**
> 改写的语义漂移风险——改写错了反而召回更差，而且多一次 LLM 调用增加延迟。所以我做了三重降级：开关默认关闭、没有 Key 不启用、调用失败或返回空一律回退原问题。目前还没有做「改写 vs 不改写」的量化 A/B 对比，这是下一步要补的。

---

## 14. 速记卡

```text
RAG 七步：切块 → 嵌入 → 双路召回 → RRF → rerank → 父上下文 → 带引用

切块：递归字符切分，分隔符 \n\n → \n → 。！？；，→ 空格 → 单字
      200 字符 / 40 重叠 / 按字符(中文友好)
      meta = source + chunk_index + document_id ← 后续所有步骤的基础

嵌入：bge-small-zh-v1.5(512维) / normalize_embeddings=True(余弦=点积)
      模型实例必须复用；维度动态获取(换模型自动重建表)

双路：向量(语义同义) + BM25(精确词/型号)  ← 互补，缺一不可
      中文分词：单字 + 二元组，不引 jieba

RRF：1/(k+rank)，k=60
     ★按名次≠按分数：量纲不可比，归一化需分布假设

rerank：CrossEncoder(bge-reranker-base)
  双塔(分别编码/可离线/快/召回) vs 交叉(拼接/慢/准/精排)
  必须两段式：全库用交叉 = 百万次推理，不可行

父上下文：小块检索 + 大块返回；前后各扩 1 块
         边界：动态上传文档不在静态缓存 → 返回命中块本身

引用：[文件名#块号] → 可溯源 + 抑制幻觉 + 便于评测

查询改写：三重降级(开关/无Key/失败回退)
         ⚠️ 默认关闭，暂无 A/B 数据，别吹

缓存：key = rag:v{语料版本}:{范围}:md5(query)
      文档增删 → _corpus_version+1 → 旧缓存自动失效
      ⚠️ 是查询哈希精确缓存，不是"相似问题"缓存
```
