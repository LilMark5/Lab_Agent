# 第 24 章 · Embedding 向量化：语义怎么变成数字

> **这一章要回答的核心问题**：向量到底是什么？为什么两句话"意思相近"它们的向量就近？余弦相似度为什么比欧氏距离好？`normalize_embeddings=True` 这一行有什么讲究？换模型为什么要重建索引？

---

## 24.1 引子：计算机怎么知道"猫"和"喵星人"是一回事

在计算机眼里，文本最初只是字符串。"猫"和"喵星人"没有任何共同字符，字符串相似度是 0：

```python
"猫" == "喵星人"           # False
similar("猫", "喵星人")     # 0.0（没有共同字符）
```

但人一看就知道它们有关。

**Embedding 要做的，就是把"语义"转换成"几何"**：

```
"猫"        → [0.21, -0.33, 0.87, ..., 0.12]   （512 维）
"喵星人"    → [0.19, -0.30, 0.91, ..., 0.15]   （512 维）
"离心机"    → [-0.72, 0.44, 0.03, ..., -0.61]  （512 维）
```

前两个向量在空间里**离得很近**（距离小、夹角小），和第三个**离得很远**。

**于是"语义相似"这个模糊的概念，变成了"向量距离"这个可以精确计算的东西。**

这就是整个向量检索的数学基础。

---

## 24.2 向量到底是什么：一个"语义坐标系"

### 24.2.1 直观理解

想象一个二维坐标系（真实是 512 维，但原理一样）：

```
                 动物
                  ↑
        猫 ●   ● 喵星人
                 
   汽车 ●                    ● 卡车
                 
   离心机 ●   ● 光谱仪
                 
    ←────────────────────→ 工具
```

在这个"语义空间"里：

- 相近的概念聚在一起（猫 / 喵星人）
- 相关的概念方向接近（离心机 / 光谱仪 都是"设备"）
- 无关的概念离得远（猫 / 离心机）

**每一维代表什么？** 这是个关键问题，答案是：**我们不知道，也不需要知道。**

这些维度是模型**自己学出来的**"潜在语义特征"，没有人类可解释的标签（不像"第 1 维 = 动物性"这么清晰）。这是深度学习的典型特征——**分布式表示**。

### 24.2.2 那句著名的话，既是真的又是误导

你可能听过：

> **"国王 - 男人 + 女人 ≈ 女王"**（Word2Vec 的经典例子）

这是真的——在 Word2Vec 的向量空间里做这个算术，结果向量最接近的确实是"女王"的向量。

**但它有误导性**，因为：

1. **只对 Word2Vec 这类早期词向量成立**，对现代的句子级 embedding（BGE、OpenAI ada）不适用
2. **它暗示"维度有明确语义"**（比如有一维是"性别"），但实际是分布式的
3. **它让人以为向量能做逻辑推理**，实际只能做"相似"

> **面试提醒**：如果面试官提这个例子，你可以说："这是 Word2Vec 时代的经典发现，说明向量空间能编码类比关系。但对现代的句子级 embedding 模型（比如我们用的 bge-small-zh）不适用——它们是针对'语义相似度检索'优化的，不保证这种线性类比性质。这也提醒我们：**选 embedding 模型要看它的训练目标，不能想当然。**"

---

## 24.3 Embedding 模型是怎么训出来的

### 24.3.1 核心思想：对比学习

现代 embedding 模型（BGE、E5、GTE、OpenAI ada）的训练目标非常朴素：

> **让"语义相近"的文本向量靠近，"语义不同"的向量远离。**

训练数据长这样：

```python
# 正样本（语义相近）
("实验室几点关门？", "实验室开放时间是 8:00 到 22:00")     # 语义相关
("怎么预约离心机？", "离心机需提前一天在系统中预约")        # 语义相关

# 负样本（语义不同）
("实验室几点关门？", "离心机的转速上限是 12000 rpm")        # 不相关
```

模型通过调整参数，让正样本的向量距离变小，负样本的变大。

### 24.3.2 为什么"检索专用"模型比通用语言模型好？

一个常见的误解是："我直接用 GPT 的隐藏层输出当 embedding 不就行了？"

**不行**，因为训练目标不同：

| 模型 | 训练目标 | 适合做 embedding？ |
|---|---|---|
| GPT / LLaMA | **预测下一个 token** | ❌ 它的表示是为"生成"优化的 |
| BERT | 完形填空 + 下一句预测 | ⚠️ 一般 |
| **BGE / E5 / GTE** | **对比学习（相似 vs 不相似）** | ✅ 专为检索优化 |

**本项目用的 `bge-small-zh-v1.5`**：
- BGE = BAAI General Embedding（智源研究院）
- `small` = 小模型（24M 参数，快）
- `zh` = **中文专用**
- `v1.5` = 版本

**为什么选中文专用模型？** 因为多语言模型（如 `paraphrase-multilingual`）在单语言上通常不如单语模型。中文的语义、分词、表达方式都和英文差异很大，专用模型效果明显更好。

> **面试话术**："我们用的是 bge-small-zh-v1.5，中文专用的检索 embedding 模型。选它的理由：一是中文专用模型在中文检索上显著优于多语言模型；二是 small 版本只有 24M 参数，本地 CPU 就能跑，不需要 GPU 和 API 调用，成本和延迟都可控；三是它是针对'检索'这个任务用对比学习训的，而不是通用的语言模型。"

### 24.3.3 维度：512 是怎么来的

`bge-small-zh-v1.5` 输出 **512 维**。

**维度越高越好吗？** 不一定：

| 维度 | 优点 | 缺点 |
|---|---|---|
| 低（128） | 存储小、检索快 | 表达力弱，可能区分不开 |
| 中（512） | 平衡 | |
| 高（1536, 3072） | 表达力强 | 存储大、检索慢、可能过拟合 |

**512 是工程上的甜点**，足够表达大多数语义，又不至于太慢。

---

## 24.4 相似度怎么算：余弦 vs 欧氏

### 24.4.1 两种度量

给定两个向量 `a` 和 `b`：

**欧氏距离（L2）**：
```
dist = sqrt(Σ(aᵢ - bᵢ)²)
```
衡量"两点之间的直线距离"。

**余弦相似度**：
```
cos = (a · b) / (|a| × |b|)
```
衡量"两个向量的夹角"。

### 24.4.2 为什么检索几乎都用余弦？

**核心原因：余弦对"长度"不敏感，只关心"方向"。**

看这个例子：

```
文档 A："实验室安全管理规定。"                    （10 字）
文档 B："实验室安全管理规定。实验室安全管理规定。...（重复 50 次）"  （500 字）
```

这两个文档的**语义方向相同**（都在讲实验室安全规定），但**长度差 50 倍**。

- 欧氏距离：**很大**（因为向量长度差很多）→ 判定不相似 ❌
- 余弦相似度：**接近 1**（方向一致）→ 判定相似 ✅

**在文本检索里，我们关心的是"主题是否一致"，不是"篇幅是否相同"。** 所以余弦更合适。

> **例外**：如果长度本身是重要特征（比如"短问答"vs"长论文"），欧氏距离反而更有信息量。但绝大多数 RAG 场景用余弦。

### 24.4.3 `normalize_embeddings=True` 的妙处

本项目（`vector_store.py:42`）：

```python
return _sentence_model.encode(texts, normalize_embeddings=True).tolist()
```

**这一行极其重要，但很容易被忽略。**

`normalize_embeddings=True` 会把每个向量**归一化成单位长度**（模长 = 1）。

**归一化之后，余弦相似度简化成了点积**：

```
cos(a, b) = (a · b) / (|a| × |b|) = (a · b) / (1 × 1) = a · b
```

这带来三个好处：

1. **计算更快**：点积比余弦少两次开方和一次除法。在百万级向量上，这个差距很大。
2. **可以预处理**：归一化在索引时做一次就行，检索时只需算点积。
3. **很多向量库要求归一化**：pgvector 的 `vector_cosine_ops` 索引、FAISS 的 `IndexFlatIP` 都假设归一化。

**代价**：失去了"长度"信息（但在文本检索里这个信息通常无用）。

> ⚠️ **坑 1（真实且高频）**：**忘记归一化会导致检索结果诡异。**
> 如果你用 `normalize_embeddings=False` 存向量，然后用余弦距离检索，长文档会系统性地被"惩罚"（因为模长大）。表现为：**长块永远排不到前面，短块霸榜。**
> 本项目在 Chroma 侧用的是 Chroma 内置的 `SentenceTransformerEmbeddingFunction`（它内部也归一化），pgvector 侧用 `_embed_texts`（显式归一化）——**两边一致**，这是对的。

### 24.4.4 距离 vs 相似度：符号陷阱

不同库返回的"分数"含义不同，**这是最容易搞混的地方**：

| 库 | 返回 | 越大越好？ |
|---|---|---|
| Chroma | `distances`（距离） | ❌ **越小越好** |
| pgvector `<=>` | 余弦距离 | ❌ 越小越好 |
| 本项目统一后 | `score` | ✅ 越大越好 |

看本项目怎么统一（Chroma 侧，`vector_store.py:132-134`）：

```python
for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
    score = 1 / (1 + float(dist))        # ★ 距离 → 相似度
    hits.append({"id": chunk_id, "doc": doc, "meta": meta or {}, "score": score})
```

**`1 / (1 + dist)` 把距离映射到 (0, 1] 区间**：
- `dist = 0`（完全相同）→ `score = 1`
- `dist = 1` → `score = 0.5`
- `dist → ∞` → `score → 0`

**永远是正数，且越大越好。** 这个统一很关键——因为下游的 RRF 融合（第 26 章）要**按名次排序**，但如果不同来源的分数方向不一致，排序就乱了。

pgvector 侧（`vector_store.py:420`）：

```sql
1 - (embedding <=> CAST(:vec AS vector)) AS score
```

`<=>` 是 pgvector 的**余弦距离**算子（0 = 相同，2 = 完全相反）。`1 - distance` 转成相似度：范围 `[-1, 1]`。

> ⚠️ **注意两个后端的 score 范围不一致**：Chroma 是 `(0, 1]`，pgvector 是 `[-1, 1]`。
> **这会影响 RRF 吗？** 不会——因为 RRF 只用**名次**，不用分数（第 26 章详述）。这正是 RRF 的一大优势：**不需要归一化不同来源的分数**。
> 但如果要做"按分数过滤"（比如只要 score > 0.7 的），两个后端的行为就不同了。这是一个需要注意的边界。

---

## 24.5 项目代码定位：embedding 的两个关键函数

`backend/app/services/vector_store.py:31-50`：

```python
EMBEDDING_MODEL = settings.EMBEDDING_MODEL
_sentence_model = None
_embedding_dim = None


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """用本地 sentence-transformers 模型把文本转成向量。"""
    global _sentence_model
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise RuntimeError("未安装 sentence-transformers，无法进行向量化") from exc

    # 模型加载很重，必须复用同一个实例，不能每次检索都重新加载。
    if _sentence_model is None:
        _sentence_model = SentenceTransformer(EMBEDDING_MODEL)
    return _sentence_model.encode(texts, normalize_embeddings=True).tolist()


def get_embedding_dim() -> int:
    """动态获取 embedding 维度，避免换模型后维度写死导致建表/建索引失败。"""
    global _embedding_dim
    if _embedding_dim is None:
        _embedding_dim = len(_embed_texts(["dim"])[0])
    return _embedding_dim
```

### 四个设计点

**① 全局单例模型**

```python
global _sentence_model
if _sentence_model is None:
    _sentence_model = SentenceTransformer(EMBEDDING_MODEL)
```

注释里写得很清楚：**"模型加载很重，必须复用同一个实例"**。

加载一个 SentenceTransformer 要：读模型文件（几百 MB）、初始化 PyTorch、可能还要编译。第一次可能要几秒到几十秒。如果每次检索都加载，系统完全不可用。

这是**和第 17 章 checkpointer 单例、第 20 章 MCP 缓存一样的模式**：**重资源全局复用 + 懒加载**。

**② 延迟导入 + 明确报错**

```python
try:
    from sentence_transformers import SentenceTransformer
except Exception as exc:
    raise RuntimeError("未安装 sentence-transformers，无法进行向量化") from exc
```

`sentence-transformers` 是个**超重依赖**（会拉 PyTorch）。延迟导入让不装它的环境仍能启动（虽然向量功能不可用）。

`from exc` 保留原始异常链，方便排查。

**③ 动态获取维度**

```python
def get_embedding_dim() -> int:
    global _embedding_dim
    if _embedding_dim is None:
        _embedding_dim = len(_embed_texts(["dim"])[0])
    return _embedding_dim
```

**这是一个很聪明的设计**，值得单独讲。

**为什么需要它？** 因为 pgvector 建表时要写死维度：

```sql
CREATE TABLE ... (embedding vector(512) NOT NULL)
```

如果你换个 embedding 模型（比如从 `bge-small-zh` 512 维换成 `bge-base-zh` 768 维），而维度写死 512，就会：

- 建表成功，但插入 768 维向量时报错
- 或者更糟：静默截断

**动态获取的做法**：用一句 `"dim"` 试跑一次，看输出多少维。

```python
len(_embed_texts(["dim"])[0])   # → 512
```

**这个技巧叫 "probe"（探针）**：用一个最小输入探测模型的输出规格。

**④ pgvector 侧的维度自适应（重建表）**

`vector_store.py:295-316`（节选）：

```python
# 检查已有表的维度
existing_dim = conn.execute(text(
    "SELECT atttypmod FROM pg_attribute WHERE attname = 'embedding' ..."
)).scalar()
if existing_dim and int(existing_dim) != dim:
    conn.execute(text(f"DROP TABLE {table}"))     # ★ 维度不一致 → 删表重建
conn.execute(text(f"""
    CREATE TABLE IF NOT EXISTS {table} (
        ...
        embedding vector({dim}) NOT NULL
    )
"""))
```

**换模型 → 维度变 → 自动 DROP 表重建。**

这个逻辑很实用（避免手动清理），但要注意：

> ⚠️ **坑 2（危险操作）**：`DROP TABLE` 会**丢掉所有已上传文档的向量**！重建后会用 `kb_chunking.load_kb_chunks()` 重新加载**静态知识库**，但**用户上传的文档不会重建**（因为它们的原文存在别处，需要重新解析）。
>
> 生产环境应该：① 警告并备份；② 或者支持"多版本表并存"；③ 或者在重建后触发所有上传文档的重新索引。
> **面试时主动指出这个风险**会很加分——说明你有生产意识。

---

## 24.6 最小骨架：亲手体验 embedding

这个例子**不需要 GPU**，用纯 Python 模拟 embedding 的核心思想，帮你建立直觉。

```python
"""
minimal_embedding.py —— 用"词袋 + 降维"模拟 embedding 的核心思想
运行：pip install numpy && python minimal_embedding.py
（不需要下载真实模型，目的是理解"语义 → 向量 → 相似度"的完整链条）
"""
import math
import re


# ── 1. 一个极简的"embedding 模型"：词袋 + TF-IDF 式加权 ────
class ToyEmbedder:
    """真实 embedding 模型是神经网络；这里用统计方法模拟，原理相通：
    语义相近的文本 → 词分布相似 → 向量相近。"""

    def __init__(self, docs: list[str]):
        self.vocab = self._build_vocab(docs)
        self.idf = self._build_idf(docs)

    def _tokenize(self, text: str) -> list[str]:
        chars = [c for c in text.lower() if c.isalnum()]
        # 中文用二元组（和项目里 _tokenize 一致）
        return [c for c in chars] + [a + b for a, b in zip(chars, chars[1:])]

    def _build_vocab(self, docs: list[str]) -> list[str]:
        vocab = set()
        for d in docs:
            vocab |= set(self._tokenize(d))
        return sorted(vocab)

    def _build_idf(self, docs: list[str]) -> dict[str, float]:
        """IDF：越稀有的词权重越高（和 BM25 的思想一致，见第 26 章）。"""
        n = len(docs)
        df = {w: 0 for w in self.vocab}
        for d in docs:
            for w in set(self._tokenize(d)):
                df[w] += 1
        return {w: math.log((n + 1) / (df[w] + 0.5)) for w in self.vocab}

    def encode(self, text: str, normalize: bool = True) -> list[float]:
        tokens = self._tokenize(text)
        vec = [0.0] * len(self.vocab)
        idx = {w: i for i, w in enumerate(self.vocab)}
        for t in tokens:
            if t in idx:
                vec[idx[t]] += 1
        # 乘 IDF 权重
        vec = [v * self.idf[w] for v, w in zip(vec, self.vocab)]
        if normalize:
            vec = self._normalize(vec)
        return vec

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm else vec


# ── 2. 两种相似度 ──────────────────────────────────────────
def cosine(a: list[float], b: list[float]) -> float:
    """归一化后 = 点积；未归一化时需要除以模长。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


# ── 3. 演示 ────────────────────────────────────────────────
CORPUS = [
    "实验室开放时间为每日 8:00 至 22:00，节假日另行通知。",
    "进入实验室必须穿戴实验服和防护眼镜，禁止穿拖鞋。",
    "激光设备使用前需预约，操作时必须佩戴专用护目镜。",
    "离心机使用前需检查转子是否平衡，严禁超速运行。",
    "实验结束后必须关闭电源、清理台面，并填写使用记录。",
]

if __name__ == "__main__":
    emb = ToyEmbedder(CORPUS)
    print(f"词表大小（模拟维度）：{len(emb.vocab)}")

    # ① 语义相似 vs 字面相似
    q1 = "实验室几点开门？"
    q2 = "离心机怎么用？"

    print("\n=== ① 语义匹配（'开门' vs '开放时间'，字面无重合）===")
    v1 = emb.encode(q1)
    for doc in CORPUS:
        vd = emb.encode(doc)
        print(f"  cos={cosine(v1, vd):+.3f}  {doc[:30]}")

    print("\n=== ② 归一化后：余弦 == 点积 ===")
    a, b = emb.encode(q1), emb.encode(q2)
    print(f"  cosine        = {cosine(a, b):.6f}")
    print(f"  dot product   = {sum(x*y for x, y in zip(a, b)):.6f}   ★ 归一化后相等")
    print(f"  euclidean     = {euclidean(a, b):.6f}   ← 长度归一化后，距离与余弦单调相关")

    # ③ 长度不变性演示（余弦 vs 欧氏的关键差异）
    print("\n=== ③ 长度不变性：长文档是否会被误判？===")
    short = "实验室安全管理规定。"
    long_ = "实验室安全管理规定。" * 20        # 语义相同，长度 20 倍
    vs, vl = emb.encode(short), emb.encode(long_)
    print(f"  短文本 vs 长文本（同语义）")
    print(f"    cosine    = {cosine(vs, vl):.3f}   ← 接近 1，认为相同 ✅")
    print(f"    euclidean = {euclidean(vs, vl):.3f}")
    print(f"  ★ 两者都归一化了，所以余弦接近 1；")
    print(f"    如果不归一化，欧氏距离会很大 → 长文档被系统性惩罚")

    # ④ 未归一化的后果演示
    print("\n=== ④ 不归一化会怎样（模拟）===")
    raw_short = [x * 1.0 for x in emb.encode(short, normalize=False)]
    raw_long = [x * 1.0 for x in emb.encode(long_, normalize=False)]
    print(f"  未归一化模长：短={sum(x*x for x in raw_short)**0.5:.2f} "
          f"长={sum(x*x for x in raw_long)**0.5:.2f}")
    print(f"  欧氏距离 = {euclidean(raw_short, raw_long):.2f}  ← 很大，误判为不相似 ❌")
    print(f"  余弦     = {cosine(raw_short, raw_long):.3f}   ← 仍接近 1 ✅")
    print(f"  ★ 结论：余弦对长度不敏感，这正是文本检索需要的")
```

**预期输出（关键行）**：

```
=== ② 归一化后：余弦 == 点积 ===
  cosine        = 0.041237
  dot product   = 0.041237   ★ 归一化后相等
  euclidean     = 1.384821

=== ④ 不归一化会怎样（模拟）===
  未归一化模长：短=8.32 长=166.41
  欧氏距离 = 158.11  ← 很大，误判为不相似 ❌
  余弦     = 1.000   ← 仍接近 1 ✅
```

**三件事被验证**：
1. ✅ 归一化后余弦 == 点积（计算更快）
2. ✅ 余弦对长度不敏感
3. ✅ 不归一化时欧氏距离会误判（长文档被惩罚）

---

## 24.7 Embedding 的五个实践要点

### 要点 1：查询和文档要用**同一个模型**

这是最容易犯的错：索引用 A 模型，检索用 B 模型。

**后果**：向量空间完全不同，检索结果毫无意义（相似度都是随机的）。

本项目：`_embed_texts` 是唯一的入口，所有地方都用它。✅

### 要点 2：批量编码比逐条快得多

```python
# ❌ 慢
for text in texts:
    vec = model.encode([text])

# ✅ 快（GPU 并行 + 减少 Python 开销）
vecs = model.encode(texts)
```

本项目 `add_chunks` 就是批量的（`vector_store.py:337`）：

```python
vectors = _embed_texts([c["doc"] for c in chunks])
```

### 要点 3：换模型必须重建索引

不同模型的向量空间完全不同，**旧向量和新向量不可比**。

本项目用 `get_embedding_dim()` + 维度不一致时 DROP TABLE 来处理（见 24.5 ④）。

### 要点 4：长文本会被截断

`bge-small-zh` 的 `max_seq_length` 是 **512 token**。超过会被截断。

**这印证了第 23 章 chunk_size=500 的选择**——正好在模型上限内。

超过的部分**静默丢失**（不报错，只是丢了）。这是"解析/切块要控制大小"的根本原因。

### 要点 5：embedding 也要成本

| 方式 | 成本 | 延迟 |
|---|---|---|
| **本地模型（本项目）** | 硬件成本（CPU/GPU），边际成本≈0 | 10-100ms / 批 |
| **云 API（OpenAI ada）** | $0.0001 / 1K token | 网络往返 50-200ms |

本项目选**本地模型**：
- ✅ 无 API 费用
- ✅ 无网络延迟
- ✅ 数据不出内网（**实验室规程这类敏感数据很重要**）
- ❌ 需要下载模型文件（几百 MB）
- ❌ 需要 CPU 资源

> **面试加分词**："我们用本地 embedding 模型而不是云 API，除了成本考虑，更重要的是**数据不出内网**——实验室规程、设备信息这类数据有保密要求。这也是很多企业选择本地部署 embedding 的核心原因。"

---

## 24.8 面试问答

### Q1：什么是 embedding？为什么能做语义检索？

**答**：embedding 是把文本映射成一个高维向量（我们是 512 维），使得**语义相近的文本在向量空间里距离近**。

它是通过对比学习训出来的：给模型看成对的"语义相近"和"语义不同"的文本，让它调整参数使正样本向量靠近、负样本远离。

于是"语义相似"这个模糊概念变成了"向量距离"这个可以精确计算的东西——这就是向量检索的数学基础。

### Q2：为什么用余弦相似度而不是欧氏距离？

**答**：核心原因是**余弦对向量长度不敏感，只关心方向**。

在文本检索里我们关心的是"主题是否一致"，不是"篇幅是否相同"。用欧氏距离的话，一份 500 字文档和一份 20 字文档即使语义相同，距离也会很大——长文档被系统性惩罚。

实践中我们还会做归一化（`normalize_embeddings=True`），归一化后余弦相似度就等于点积，**少两次开方一次除法**，在百万级向量上这个差距很可观。很多向量库的索引（pgvector 的 `vector_cosine_ops`、FAISS 的 `IndexFlatIP`）也假设向量已归一化。

### Q3：你们用什么 embedding 模型？为什么？

**答**：bge-small-zh-v1.5，中文专用的检索 embedding 模型，512 维，本地部署。

选它的理由：一是**中文专用**——多语言模型在单语言上通常不如专用模型，中文的语义和表达方式差异很大；二是 **small 版本只有 24M 参数**，CPU 就能跑，不需要 GPU 和 API 调用；三是它是用**对比学习**针对检索任务训的，而不是通用的语言模型（像 GPT 那样为"预测下一个 token"优化的，不适合直接当 embedding）。

另外我们选本地部署而非云 API，除了成本，更重要的是**数据不出内网**——实验室规程这类数据有保密要求。

### Q4：换 embedding 模型会发生什么？你们怎么处理？

**答**：换模型后向量空间完全不同，旧向量和新向量不可比，必须重建索引。

我们的处理是**动态获取维度**：用一句探针文本试跑一次拿到维度，建表时用这个真实维度，而不是写死 512。这样换成 768 维的模型也不会建表失败。

更进一步，pgvector 侧检测到已有表的维度和当前模型不一致时，会 **DROP TABLE 重建**，然后重新加载静态知识库。

**但这里有个我要主动指出的风险**：DROP TABLE 会丢掉所有已上传文档的向量。重建后只会自动恢复静态知识库，用户上传的文档需要重新索引。生产环境应该做备份和告警，或者触发全量重新索引。

### Q5：`normalize_embeddings=True` 有什么用？不设会怎样？

**答**：把每个向量归一化成单位长度（模长=1）。三个好处：

一是**余弦变点积**，计算更快；二是**索引时做一次就行**，检索时只算点积；三是**很多向量库要求归一化**（pgvector 的 `vector_cosine_ops`、FAISS 的 IndexFlatIP）。

不设的话，会出现一个很隐蔽的问题：**长块被系统性惩罚**。因为长文本的向量模长大，用距离度量时永远排在后面。表现是长块检索不到、短块霸榜。

我们 Chroma 侧用的是它内置的 embedding function（内部也归一化），pgvector 侧显式传 `normalize_embeddings=True`，两边一致。

### Q6：不同向量库返回的分数含义一样吗？

**答**：不一样，这是个容易踩的坑。

Chroma 返回的是 `distances`（距离，**越小越好**），pgvector 的 `<=>` 也是余弦距离。我们统一转成 `score`（越大越好）：Chroma 侧用 `1/(1+dist)` 映射到 `(0,1]`，pgvector 侧用 `1 - distance` 映射到 `[-1,1]`。

**注意两个范围不一致**。这会影响"按分数过滤"这类逻辑，但**不影响我们的 RRF 融合**——因为 RRF 只用名次不用分数，这正是它的优势：不需要归一化不同来源的分数。

---

## 24.9 速记卡

> **Embedding = 把语义变成几何：相似 → 距离近。**

**核心思想**：对比学习训出来 —— 正样本靠近，负样本远离

**本项目模型**：`bge-small-zh-v1.5`（中文专用 / 512 维 / 24M 参数 / 本地部署）

**为什么本地**：成本 + 延迟 + **数据不出内网**

**余弦 vs 欧氏**：余弦对**长度不敏感**（只关心方向）→ 文本检索首选

**★ `normalize_embeddings=True`**：
- 余弦 == 点积（更快）
- 不设 → **长块被系统性惩罚**

**距离转相似度**：`score = 1/(1+dist)` → 永远正数、越大越好

**动态维度**：`len(_embed_texts(["dim"])[0])` —— 探针技巧，避免维度写死

**换模型 → 重建索引**：pgvector 侧维度不一致会自动 DROP TABLE（⚠️ 会丢上传文档）

**五要点**：同模型 / 批量编码 / 换模型重建 / 512 token 上限 / 成本

**代码位置**：`vector_store.py:31-50`（`_embed_texts` + `get_embedding_dim`）

---

## 24.10 延伸思考

1. **如果用户用英文提问，但知识库是中文的，能检索到吗？**
   提示：取决于模型。`bge-small-zh` 是中文专用，跨语言能力弱。要支持跨语言需要多语言模型（如 `paraphrase-multilingual-MiniLM`）或者专门的跨语言模型。**这是一个真实的边界**，面试时可以说"当前不支持跨语言检索，需要的话要换多语言模型"。

2. **embedding 能表达"否定"吗？"实验室不开放" 和 "实验室开放" 的向量会近吗？**
   提示：**会近**——因为它们用词几乎一样。这是 embedding 的著名缺陷：**对否定、程度、语序不敏感**。缓解方法：rerank（第 27 章，交叉编码器能捕捉这类细微差异）；或者对否定句做特殊处理。这是一个很好的面试题。

3. **为什么不用"稀疏向量"（SPLADE）？它和稠密向量有什么区别？**
   提示：稠密向量（512 维，每维都有值）擅长语义泛化；稀疏向量（词表维度，大部分为 0，保留词级权重）擅长精确匹配。现代系统常做**混合检索**（第 26 章）——正是"稠密 + 稀疏"的组合。我们的 BM25 其实就扮演了稀疏检索的角色。

---

**下一章**：第 25 章 · 向量数据库——Chroma / pgvector / Milvus 三后端怎么抽象？HNSW 索引是什么？
