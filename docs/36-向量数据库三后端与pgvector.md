# 36 · 向量数据库三后端与 pgvector

> **速成定位**：面试官问「你为什么选 pgvector / 怎么选向量库 / HNSW 是什么」，这一篇给你完整答案。
> **一句话**：把向量库操作抽象成统一接口（`is_ready/count/add_chunks/delete_chunks/search`），ChromaDB / Milvus / pgvector 三种实现可配置切换。

---

## 目录

1. [向量数据库解决什么问题](#1-向量数据库解决什么问题)
2. [三后端选型对比](#2-三后端选型对比)
3. [面向接口编程：统一抽象层](#3-面向接口编程)
4. [pgvector 深度剖析](#4-pgvector-深度剖析)
5. [HNSW 索引原理](#5-hnsw-索引原理)
6. [为什么选 pgvector 做生产后端](#6-为什么选-pgvector-做生产后端)
7. [最小可运行骨架](#7-最小可运行骨架)
8. [项目里对应哪块代码](#8-项目里对应哪块代码)
9. [面试高频问答](#9-面试高频问答)
10. [速记卡](#10-速记卡)

---

## 1. 向量数据库解决什么问题

### 从暴力搜索说起

有 100 万条 512 维向量，要找和查询向量最相似的 10 条：

- **暴力扫描**：算 100 万次余弦相似度 → 太慢（每次查询几百毫秒到秒级）。
- **ANN 索引**（近似最近邻）：牺牲一点点精度，换来百倍加速。

向量数据库 = **向量存储 + ANN 索引 + 元数据过滤 + 持久化**。

### 和传统数据库的区别

| | 传统 DB | 向量 DB |
| --- | --- | --- |
| 查询方式 | 精确匹配（=、>、LIKE） | **相似度排序**（top-k 近邻） |
| 索引 | B+Tree | **HNSW / IVF / PQ** |
| 语义 | 结构化 | 语义相似 |

---

## 2. 三后端选型对比

| | **ChromaDB** | **Milvus** | **pgvector** |
| --- | --- | --- | --- |
| 形态 | 嵌入式（本地文件）/ 服务 | 独立服务（Lite 文件模式 / 集群） | **PostgreSQL 扩展** |
| 部署成本 | ⭐ 零（pip 装完就用） | 高（Docker / 集群） | 中（已有 PG 只需装扩展） |
| 数据规模 | 中小（十万级） | 大（亿级） | 中（百万级够用） |
| 事务 | 无 | 无 | ✅ **和 PG 共享事务** |
| 混合查询 | 一般 | 好 | ✅ **SQL JOIN / WHERE 随便写** |
| 本项目状态 | ✅ 实跑 | ⚠️ 代码在，Windows 实机跑不了 | ✅ **实跑（默认后端）** |

> **诚实说明**（简历口径）：本项目 `VECTOR_BACKEND=pgvector` 已实跑全链路验证；ChromaDB 实跑过；**Milvus 代码完整但 Windows 环境未实机验证**，简历上写「了解」。

---

## 3. 面向接口编程

`vector_store.py:1-12` 定义了统一契约：

```python
"""
三者的共同接口：
    is_ready() -> bool
    count()    -> int
    add_chunks(chunks)            # 新增/更新块（按 id 幂等）
    delete_chunks(document_id)    # 删除某文档的全部块
    search(query, top_k, document_id=None) -> list[dict]
"""
```

三个实现类（`ChromaVectorStore` / `MilvusVectorStore` / `PgVectorStore`）都实现这套接口。上层 `kb_service` **只依赖接口，不依赖具体实现**。

### 工厂函数（`vector_store.py:451-490`）

```python
def get_vector_store():
    preferred = settings.VECTOR_BACKEND.lower()

    if preferred == "pgvector":
        store = PgVectorStore()
        store._ensure()
        _store = store
        return store

    if preferred == "milvus":
        try:
            store = MilvusVectorStore(); store._ensure()
            return store
        except Exception as exc:
            logger.warning("Milvus 初始化失败，回退 ChromaDB（Windows 不支持 Milvus Lite...）")

    try:
        store = ChromaVectorStore(); store._ensure()
        return store
    except Exception:
        logger.warning("ChromaDB 不可用，RAG 功能降级为空实现")
        return None
```

**三层降级**：pgvector → Milvus → ChromaDB → None（RAG 降级为空实现，服务仍可用）。

> **面试话术**：「向量库选型我没写死，抽象成统一接口后靠配置切换。任何一个后端初始化失败都会自动降级，最坏情况是 RAG 返回空，但**服务本身不会启动失败**。」

### 文档归属设计

每个块通过 `meta.document_id` 归属文档：内置知识库用 `"static"`，上传文档用其注册 ID。

这带来三个能力：
1. 删除某文档 → `delete_chunks(document_id)` 一次清掉它的所有块；
2. 只搜内置知识库 → `search(..., document_id="static")`；
3. 只搜某上传文档 → 传该文档 ID。

**这就是 Agent 侧「是否检索上传文档」开关的实现基础**（`agent_tools.py:77`）。

---

## 4. pgvector 深度剖析

### 4.1 建表与索引（`vector_store.py:291-325`）

```python
with self._engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 检测现有维度，变了就重建表
    existing_dim = conn.execute(text(
        "SELECT a.atttypmod FROM pg_attribute a "
        "JOIN pg_class c ON a.attrelid = c.oid "
        "WHERE c.relname = :t AND a.attname = 'embedding'"
    ), {"t": table}).scalar()
    if existing_dim and int(existing_dim) != dim:
        conn.execute(text(f"DROP TABLE {table}"))

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id VARCHAR(255) PRIMARY KEY,
            text TEXT NOT NULL,
            source VARCHAR(512) NOT NULL,
            chunk_index INTEGER NOT NULL,
            document_id VARCHAR(64),
            embedding vector({dim}) NOT NULL
        )
    """))
    conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_embedding "
        f"ON {table} USING hnsw (embedding vector_cosine_ops)"
    ))
```

**四个要点**：

1. **`vector(dim)` 类型**：维度必须显式指定，所以维度要动态获取（换模型自动适配）。
2. **维度变化自动重建**：用 `pg_attribute.atttypmod` 读出当前维度，和 embedding 模型的实际维度比对，不同就 `DROP TABLE` 重建。**避免换模型后报「维度不匹配」**。
3. **`ALTER TABLE ADD COLUMN IF NOT EXISTS document_id`**：给旧表平滑加列，兼容已存在的表。
4. **HNSW 索引 + `vector_cosine_ops`**：因为嵌入时做了归一化，余弦距离算子和索引类型要匹配。

### 4.2 写入用 upsert（`vector_store.py:340-364`）

```sql
INSERT INTO kb_chunks (...) VALUES (...)
ON CONFLICT (id) DO UPDATE SET
    text = EXCLUDED.text, ..., embedding = EXCLUDED.embedding
```

**为什么必须是 upsert**：知识库重建时块 id 不变（`文件名#序号`），重复写入必须更新而不是报错或产生重复。

### 4.3 检索 SQL（`vector_store.py:408-444`）

```sql
SELECT id, text, source, chunk_index, document_id,
       1 - (embedding <=> CAST(:vec AS vector)) AS score
FROM kb_chunks
WHERE document_id = :doc          -- 可选范围过滤
ORDER BY embedding <=> CAST(:vec AS vector)
LIMIT :k
```

| 算子 | 含义 |
| --- | --- |
| `<=>` | **余弦距离**（0=完全相同，2=完全相反） |
| `<->` | 欧氏距离 |
| `<#>` | 内积（负内积） |

`1 - 距离 = 相似度`，所以相似度越大越靠前。

**⚠️ 参数绑定**：`WHERE document_id = :doc` 用参数化；但表名 `{self.TABLE}` 是字符串拼接——这是内部常量 `'kb_chunks'`，不可注入，不过面试会被追问（见第 9 题）。

---

## 5. HNSW 索引原理

**HNSW = Hierarchical Navigable Small World**（分层可导航小世界图）。

### 直觉理解

想象一个多层地图导航系统：

```text
第 2 层（最稀疏）：  A ———————————— B          少数节点，长距离跳转
                      \            /
第 1 层（中等）：     A —— C —— D —— B          中距离
                      |   |   |   |
第 0 层（最密）：     A-C-E-D-F-G-H-B           所有节点，精确局部搜索
```

**查询过程**：
1. 从最高层的某个入口点出发，**贪心**走向离查询更近的邻居；
2. 到该层的局部最优点后，**下到下一层**继续；
3. 到最底层（包含所有节点）做精细搜索，返回 top-k。

**为什么快**：高层用少量跳转快速逼近目标区域（类似跳表），底层才做精细比较。复杂度从 O(N) 降到近似 **O(log N)**。

### 关键参数（面试会问）

| 参数 | 含义 | 权衡 |
| --- | --- | --- |
| `m` | 每个节点连接多少个邻居 | 越大图越密，**召回率高**、内存大、构建慢 |
| `ef_construction` | 构建时的候选队列大小 | 越大**索引质量越高**、构建越慢 |
| `ef_search` | 查询时的候选队列大小 | 越大**召回率越高**、查询越慢 |

本项目用默认参数（未显式指定），属于合理简化。

### HNSW vs IVF

| | HNSW | IVF（倒排文件） |
| --- | --- | --- |
| 原理 | 分层图 | 聚类分桶，只搜最近几个桶 |
| 查询速度 | 快 | 快 |
| 构建成本 | 较高 | 较低 |
| 内存 | 较大 | 较小 |
| 召回率 | 高 | 依赖 `nprobe` |

pgvector 两者都支持，本项目选 HNSW。

---

## 6. 为什么选 pgvector 做生产后端

**四个理由（面试按这个顺序讲）**：

1. **少一个组件**。业务数据已经在 PostgreSQL 里，再引入一个专门的向量库意味着多一套部署、监控、备份、扩容。pgvector 只是一个扩展。
2. **事务一致性**。向量表和业务表在同一个事务里，不会出现「业务记录删了但向量还在」的不一致。专用向量库做不到这点。
3. **混合查询能力强**。可以用 SQL 直接做元数据过滤、JOIN、聚合——比如「只搜某文档的块 + 按时间排序」，一个 WHERE 就搞定。
4. **规模够用**。百万级向量在本项目场景下完全够，HNSW 索引下查询仍是毫秒级。

**什么时候该换专用向量库**：数据量到千万/亿级、需要分布式分片、需要 GPU 加速——那时再上 Milvus。

> **面试话术**：「我用 pgvector 不是因为它最强，而是因为**在百万级规模下它最省心**。向量库抽象层已经做好了，真到需要 Milvus 的规模，改一个配置就行——这也是我为什么要做统一接口。」

---

## 7. 最小可运行骨架

**方案 A（零依赖）**：纯 Python 实现「存向量 + 暴力检索 + 元数据过滤」，把接口抽象跑通。

```python
"""最小骨架：向量库统一接口 + 两个实现 + 工厂切换 + 元数据过滤。
纯标准库，用字符重合度模拟余弦相似度。"""

import math
from abc import ABC, abstractmethod


# ============ 1. 统一接口（本项目 vector_store.py 的契约）============
class VectorStore(ABC):
    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def add_chunks(self, chunks): ...

    @abstractmethod
    def delete_chunks(self, document_id): ...

    @abstractmethod
    def search(self, query, top_k=5, document_id=None): ...


# ============ 2. 一个「假嵌入」：字符重合度模拟余弦相似度 ============
def embed(text: str):
    """真实项目这里换成 SentenceTransformer.encode(normalize_embeddings=True)"""
    vec = {}
    for i, ch in enumerate(text.lower()):
        if ch.isalnum():
            vec[ch] = vec.get(ch, 0) + 1
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1
    return {k: v / norm for k, v in vec.items()}        # 归一化 → 余弦=点积


def cosine(a, b):
    return sum(a.get(k, 0) * v for k, v in b.items())


# ============ 3. 实现 A：内存版（相当于 ChromaDB 的嵌入式形态）============
class MemoryStore(VectorStore):
    def __init__(self):
        self.rows = {}

    def count(self):
        return len(self.rows)

    def add_chunks(self, chunks):
        for c in chunks:
            # 按 id upsert：id 相同则覆盖，保证重建知识库不产生重复
            self.rows[c["id"]] = {
                "doc": c["doc"], "meta": c["meta"], "vec": embed(c["doc"])
            }

    def delete_chunks(self, document_id):
        self.rows = {k: v for k, v in self.rows.items()
                     if v["meta"].get("document_id") != document_id}

    def search(self, query, top_k=5, document_id=None):
        q = embed(query)
        cands = self.rows.values()
        if document_id:
            # 元数据过滤：这就是「只搜内置知识库」的实现方式
            cands = [r for r in cands if r["meta"].get("document_id") == document_id]
        scored = sorted(cands, key=lambda r: cosine(q, r["vec"]), reverse=True)
        return [{"id": k, "doc": r["doc"], "meta": r["meta"],
                 "score": cosine(q, r["vec"])}
                for k, r in ((k, r) for k, r in self.rows.items()
                             if r in scored)][:top_k]


# ============ 4. 工厂：按配置切换（三层降级思想的简化版）============
def get_vector_store(backend: str = "memory"):
    if backend == "memory":
        return MemoryStore()
    raise ValueError(f"未知后端: {backend}")


if __name__ == "__main__":
    store = get_vector_store("memory")
    store.add_chunks([
        {"id": "static#0", "doc": "实验室开放时间 8:00-22:00",
         "meta": {"source": "规则.md", "chunk_index": 0, "document_id": "static"}},
        {"id": "static#1", "doc": "进入实验室必须穿实验服",
         "meta": {"source": "规则.md", "chunk_index": 1, "document_id": "static"}},
        {"id": "doc-1#0", "doc": "光谱仪 LD-2000 需提前一天预约",
         "meta": {"source": "设备手册.pdf", "chunk_index": 0, "document_id": "doc-1"}},
    ])
    print("总数:", store.count())

    print("\n全库检索「开放时间」:")
    for h in store.search("开放时间", top_k=2):
        print(f"  {h['id']} score={h['score']:.3f} {h['doc']}")

    print("\n只搜内置知识库（document_id=static）:")
    for h in store.search("预约", top_k=3, document_id="static"):
        print(f"  {h['id']} {h['doc']}")   # 不会出现 doc-1 的内容

    print("\n删除上传文档 doc-1 后总数:", end=" ")
    store.delete_chunks("doc-1")
    print(store.count())
```

**方案 B（真实 pgvector，可选跑）**：

```sql
-- 在 PostgreSQL 里执行
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE kb_chunks (
    id VARCHAR(255) PRIMARY KEY,
    text TEXT NOT NULL,
    source VARCHAR(512) NOT NULL,
    chunk_index INTEGER NOT NULL,
    document_id VARCHAR(64),
    embedding vector(512) NOT NULL
);

-- HNSW 索引（余弦距离算子）
CREATE INDEX idx_kb_chunks_embedding
    ON kb_chunks USING hnsw (embedding vector_cosine_ops);

-- 查询：注意 <=> 是余弦距离，1-距离 = 相似度
SELECT id, text, 1 - (embedding <=> '[...]'::vector) AS score
FROM kb_chunks
WHERE document_id = 'static'
ORDER BY embedding <=> '[...]'::vector
LIMIT 3;
```

---

## 8. 项目里对应哪块代码

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| 接口契约 | `vector_store.py:1-12` | docstring 声明 5 个方法 |
| 嵌入 | `vector_store.py:31-42` | `SentenceTransformer` + 归一化 + 实例复用 |
| 动态维度 | `vector_store.py:45-50` | `get_embedding_dim()` |
| ChromaDB 实现 | `vector_store.py:53-135` | 集合名 `lab_kb_chunks_v2`，`upsert` |
| Milvus 实现 | `vector_store.py:138-262` | Lite 文件模式 |
| **pgvector 实现** | `vector_store.py:265-444` | 建表/维度重建/HNSW/upsert/检索 |
| 维度检测 | `vector_store.py:293-302` | `pg_attribute.atttypmod` |
| HNSW 建索引 | `vector_store.py:320-325` | `USING hnsw (embedding vector_cosine_ops)` |
| upsert | `vector_store.py:340-364` | `ON CONFLICT (id) DO UPDATE` |
| 检索 SQL | `vector_store.py:408-444` | `<=>` 余弦距离 + 参数绑定 |
| **工厂 + 降级** | `vector_store.py:451-490` | pgvector → Milvus → Chroma → None |
| 预热 | `vector_store.py:493-501` | `warmup()` |
| 配置 | `config.py:83-93` | `VECTOR_BACKEND`、`MILVUS_LOCAL_URI`、混合检索/rerank 开关 |
| 文档归属 | `kb_chunking.py:124 / 142` | `document_id="static"` 或上传文档 ID |

**当前实际配置**（`backend/.env`）：

```text
DATABASE_URL=postgresql+psycopg2://...@127.0.0.1:5432/lab_agent
VECTOR_BACKEND=pgvector
```

---

## 9. 面试高频问答

**Q1：为什么选 pgvector 不用 Milvus？**
> 在百万级规模下 pgvector 最省心：① 少一个组件，不用单独部署监控备份；② 和业务表共享事务，不会出现「业务删了向量还在」的不一致；③ 元数据过滤、JOIN 可以直接写 SQL；④ 性能够用。Milvus 要到千万/亿级、需要分布式分片时才必要。**而且我把向量库抽象成了统一接口，真到那个规模改配置即可。**

**Q2：HNSW 是什么原理？**
> 分层可导航小世界图。构建时把节点分层，上层稀疏、下层密集；查询时从最高层的入口点贪心走向更近的邻居，到局部最优后下到下一层，最后在包含全部节点的最底层做精细搜索。相当于「跳表 + 图搜索」，复杂度从 O(N) 降到近似 O(log N)。参数上，`m` 控制邻居数（越大召回越高、内存越大），`ef_search` 控制查询候选队列（越大越准越慢）。

**Q3：pgvector 的距离算子有哪些？**
> `<=>` 余弦距离、`<->` 欧氏距离、`<#>` 内积。我用余弦距离，因为嵌入时做了 `normalize_embeddings=True` 归一化，此时余弦相似度等于向量点积，索引算子用 `vector_cosine_ops` 与之匹配。SQL 里 `1 - (embedding <=> vec)` 就是相似度。

**Q4：换 embedding 模型会出问题吗？**
> 不会。维度是**动态获取**的（跑一次 `encode` 看长度），建表时用实际维度。而且 `PgVectorStore._ensure()` 会读 `pg_attribute.atttypmod` 拿到已有表的维度，和新维度比对，**不一致就 DROP TABLE 重建**。这样换模型不会报维度不匹配。

**Q5：为什么写入要用 upsert？**
> 知识库重建时块的 id 是 `文件名#序号`，保持不变。如果用普通 INSERT 会主键冲突，用「先删后插」会有一瞬间检索为空。upsert（`ON CONFLICT (id) DO UPDATE`）既幂等又不会中断服务。

**Q6：怎么做「只搜内置知识库」？**
> 每个块带 `meta.document_id`，内置知识库统一是 `"static"`。检索时传 `document_id` 参数，pgvector 侧是 `WHERE document_id = :doc` 参数化过滤，Chroma 侧是 `where={"document_id": ...}`。

**Q7（追问）：你的 SQL 里有字符串拼接，不怕注入吗？**
> 具体是表名 `{self.TABLE}`。它是模块内常量 `'kb_chunks'`，不来自用户输入，当前不可注入。但你说得对，**风格和同一函数里的参数化写法不统一**，容易被误解。改进方向是加一层表名白名单校验——这点我在代码审查里已经记下来了。

**Q8：向量库初始化失败会怎样？**
> 三层降级：pgvector 失败 → Milvus → ChromaDB → 返回 None，此时 RAG 检索返回空但**服务照常启动**。启动时 `warmup()` 还加了 30 秒超时，防止模型下载卡住服务启动。

**Q9（诚实题）：Milvus 你真的跑过吗？**
> 代码写完了，但 Milvus Lite 在 Windows 上不支持，我的环境没实机验证过。所以简历上我写的是「ChromaDB / pgvector 实跑，Milvus 了解」——没跑过的我不会写成熟练。要用 Milvus 得通过 Docker 起服务。

**Q10：向量检索和关键词检索的结果怎么合并？**
> 见 35 篇：两路各召回 top_k，用 RRF 按名次融合（因为向量分数和 BM25 分数量纲不同不可直接相加），再用 CrossEncoder 精排。

---

## 10. 速记卡

```text
向量库 = 向量存储 + ANN索引 + 元数据过滤 + 持久化
暴力 O(N) → ANN 近似 O(log N)

三后端：
  ChromaDB  嵌入式/零部署/中小规模   ✅实跑
  Milvus    独立服务/亿级/需Docker   ⚠️代码在,Windows未实机
  pgvector  PG扩展/共享事务/百万级   ✅实跑(默认)

统一接口（面向接口编程）：
  is_ready / count / add_chunks / delete_chunks / search
  工厂 get_vector_store() 三层降级：pgvector→milvus→chroma→None

pgvector:
  CREATE EXTENSION vector;  embedding vector(512)
  <=>余弦  <->欧氏  <#>内积      1-距离=相似度
  归一化后余弦=点积，索引用 vector_cosine_ops
  维度动态获取；atttypmod 检测变化→DROP 重建
  INSERT ... ON CONFLICT(id) DO UPDATE  ← upsert 幂等

HNSW：分层图，上层稀疏跳转 + 底层精细搜索（跳表思想）
  m=邻居数 / ef_construction=构建候选 / ef_search=查询候选
  比 IVF：召回高、内存大、构建慢

document_id：static=内置，上传文档=其ID
  → 删除文档 / 只搜内置 / 只搜某文档 全靠它

诚实口径：Milvus 未实机验证，写"了解"不写"熟练"
```
