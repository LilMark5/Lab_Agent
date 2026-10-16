# 15 · Milvus 与混合检索、rerank

## 1. 为什么需要专业向量库？

ChromaDB 适合学习和原型；数据量大了以后需要：

- 亿级向量的索引与检索。
- 标量过滤（例如只查 `status=1` 的文档）。
- 稳定性和水平扩展。

Milvus 就是为此设计的。本项目用 Milvus Lite（嵌入式文件模式），
代码和真正 Milvus 一致，只是零运维。

## 2. 向量库在项目里的抽象

[vector_store.py](../../backend/app/services/vector_store.py) 定义了两个实现：

```text
ChromaVectorStore   -> ChromaDB
MilvusVectorStore   -> Milvus Lite
```

切换只改 `.env` 的 `VECTOR_BACKEND`，业务代码无感。这就是面向接口编程。

## 3. 混合检索为什么比纯向量强

- 纯向量：语义好，但专有名词、精确编号可能漏。
- BM25：关键词精确匹配强，但不会理解同义词。
- 混合：两种都召回，再用 RRF 融合排序。

```text
向量召回 top-k  ┐
                ├──> RRF 融合 -> 精排(rerank) -> 给大模型
BM25 召回 top-k ┘
```

## 4. RRF 是什么？

Reciprocal Rank Fusion：不看分数绝对值，只看名次。

```text
RRF 分数 = Σ 1 / (k + rank)
```

名次靠前的文档在多个召回里都被认可，最终排名就高。简单、稳定、无需调参。

## 5. rerank 是干嘛的？

向量检索是“双塔模型”，快但粗；rerank 用交叉编码器把“问题 + 文档”成对打分，
慢但准。所以流程是：**先召回一批，再用 rerank 精排前几名。**

## 6. 面试答法

“我先用向量召回语义相关的候选，再用 BM25 补关键词命中，RRF 融合两路排序，
最后用 bge-reranker 精排。这样兼顾语义和精确匹配，检索质量明显比单一召回高。”

## 7. 代码位置

- 向量库抽象：[vector_store.py](../../backend/app/services/vector_store.py)
- 混合检索与重排：[kb_service.py](../../backend/app/services/kb_service.py)
- 评估脚本：[evaluate_rag.py](../../backend/evaluate_rag.py)
