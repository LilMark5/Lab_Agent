# 07 · 深入浅出 RAG：检索增强生成

## 1. 大模型的两个问题

1. **知识截止**：模型训练后不知道新知识。
2. **幻觉**：不知道时容易编造。

RAG 的解法是：先查资料，再把资料和问题一起交给模型。

```text
用户问题
  -> 检索相关知识
  -> 把知识塞进 Prompt
  -> 模型根据资料回答
```

“Retrieval-Augmented Generation” = 检索 + 增强 + 生成。

## 2. 为什么需要向量检索？

如果知识很少，可以直接全塞进 Prompt。但知识多、上下文有限，就需要“找最相关的”。

传统关键词匹配的问题：

- 用户问“几点开门”，文档写“开放时间”，关键词不同就查不到。
- 同义词、口语化表达无法匹配。

向量检索把文字映射到高维空间，语义相近的句子向量距离近。

```text
“几点开门”  -> 向量 A
“开放时间”  -> 向量 B
A 和 B 距离近，因此能检索到。
```

## 3. RAG 的核心流程

### 3.1 离线索引（写入）

```text
读文件 -> 切块(chunking) -> 向量化(embedding) -> 存向量库
```

本项目知识库较小，每篇 Markdown 直接作为一个文档块：

```python
col.add(ids=ids, documents=docs, metadatas=metas)
```

### 3.2 在线检索（查询）

```text
用户问题 -> 向量化 -> 相似度检索 -> 取 top-k
```

```python
res = col.query(query_texts=[query], n_results=limit)
```

### 3.3 生成

把检索结果拼进 system prompt：

```python
system_prompt += "\n\n以下是检索到的实验室资料：\n" + knowledge
```

模型被要求“依据资料回答，不要编造”。

## 4. 向量数据库 ChromaDB

本项目用 ChromaDB：

```python
client = chromadb.PersistentClient(path=str(CHROMA_DIR))
col = client.get_or_create_collection(name="lab_kb", embedding_function=...)
```

关键概念：

- Collection：一个向量集合。00
- Document：原文。
- Metadata：元数据，如来源文件名。
- Embedding Function：把文本转成向量。

## 5. Embedding 模型

本项目用 `BAAI/bge-small-zh-v1.5`，中文效果好，适合学习。
生产环境要考虑：

- 多语言支持。
- 向量维度与存储成本。
- 领域语料的微调。

Embedding 模型只负责“把文本变向量”，生成回答还是 LLM。两个模型分工不同。

## 6. 检索质量：为什么结果可能不准？

常见问题：

- 切块太粗或太细。
- 只按相似度取 top-k，忽略排序。
- 文档重复、过时。
- 查询本身太短，缺少上下文。

本项目用分数过滤和 top-2：

```python
score = 1 / (1 + dist)
if score < 0.5:
    continue
```

这只是简单版本。企业级会做混合检索、重排序、查询改写。

## 7. 从 Naive RAG 到 Advanced RAG

| 阶段 | 做法 |
| --- | --- |
| Naive RAG | 切块 -> 向量检索 -> 拼 Prompt |
| Advanced RAG | 查询改写、混合检索、重排序 |
| Modular RAG | 可插拔的检索/生成/记忆模块 |

你还可能听到 GraphRAG、HyDE、Multi-query RAG。核心不变：
**提升“找到正确资料”的能力，并控制“错误资料”带来的污染。**

## 8. 为什么知识库改了要重建？

ChromaDB 集合建好后再改 Markdown，向量不会自动更新。
本项目做法是删除 `data/chroma` 后重启，集合会重新导入。

生产上应该做增量更新、版本管理，而不是删库重建。

## 9. 检查清单

- RAG 解决大模型的什么问题？
- embedding 模型和 LLM 的分工是什么？
- 向量检索相比关键词检索有什么优势？
- 检索结果不准通常有哪些原因？
