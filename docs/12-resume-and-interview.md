# 12 · 简历怎么写才有含金量（AI Agent 实习）

## 1. 简历写作原则

实习生简历不要罗列技术名词，要写“**做了什么、解决了什么、用什么验证**”。
一个高含金量条目 = 技术 + 动作 + 量化结果。

```text
差：熟悉 FastAPI、LangChain、Milvus、MCP。
好：基于 FastAPI + LangGraph 构建智能实验室预约 Agent，支持 RAG 检索、
    Tool Calling 与人工确认，预约成功率达到 X%。
```

## 2. 可以直接用的简历条目

### 项目条目（放最上面）

**智能实验室预约系统 · AI Agent 全栈实践**

```text
独立完成 FastAPI + Vue3 的实验室预约系统，后端采用 API/Service/Model 分层，
实现 JWT 鉴权、统一响应、全局异常与预约冲突检测。

基于 LangGraph StateGraph 构建 ReAct 风格 Agent：模型自主决定调用
search_lab_docs / list_open_labs / create_lab_reservation 等工具，
多轮工具循环受 recursion_limit 约束，写库前强制用户确认。

RAG 采用向量召回 + BM25 关键词召回 + RRF 融合 + bge-reranker 重排，
向量库支持 ChromaDB 与 Milvus 双后端，并接入 Redis 缓存相似问题。

将实验室查询能力封装为独立 MCP Server，Agent 通过
langchain-mcp-adapters 接入，体现标准工具协议与业务解耦。

使用 SSE 流式输出让用户看到“思考/查库/提交预约”全过程，
并预留 Langfuse/RAGAS 接入点，用自研评估脚本统计检索 hit@k。
```

### 技术清单条目（可写但别写太长）

```text
后端：Python、FastAPI、SQLAlchemy、PostgreSQL、Redis、Docker
AI：LangChain、LangGraph、RAG、Function Calling、MCP、Embedding、Milvus
前端：Vue3、TypeScript(基础)、Vite、Element Plus
工程：Linux、异步编程、评估与可观测性
```

## 3. 每项技术对应的“面试一句话”

| 技术 | 面试可能问 | 你的答法骨架 |
| --- | --- | --- |
| FastAPI | 为什么用它 | 原生异步、自动文档、依赖注入 |
| SQLAlchemy | ORM 好在哪 | 对象映射、防注入、可切库；用 join/index/事务 |
| PostgreSQL | 和 MySQL 比 | 类型更强、pgvector 做向量检索 |
| Redis | 用它干嘛 | AI 接口限流、相似问题缓存 |
| Milvus | 为什么不用 Chroma | 面向海量向量、支持标量过滤、可扩展 |
| RAG | 怎么保证检索准 | 混合检索 + RRF + rerank + 评估指标 |
| LangGraph | Agent 怎么编排 | State/Node/Edge，条件边控制工具循环 |
| MCP | 解决什么 | 让工具标准化，任何 Agent 都能接入 |
| ReAct | 是什么 | Thought/Action/Observation 循环 |
| 评估 | 怎么证明效果好 | RAGAS 的 faithfulness/recall + 任务成功率 |
| 可观测 | 生产要关注什么 | token、成本、延迟、工具调用链路 |

## 4. 二十天冲刺期的简历策略

1. 项目写一个，不要写五个。
2. 把“评估”和“可观测”写进去，这是你和其他实习生的分水岭。
3. 每个技术点准备一个“我做了什么 + 为什么这么选”的 30 秒回答。
4. 准备一个架构图：一次请求从前端到 Agent 到数据库/向量库的完整路径。

## 5. 模拟面试自查表

- 能画出 ReAct 的循环图吗？
- 能说清 RAG 的召回、融合、重排吗？
- 能解释 MCP 和普通函数工具的区别吗？
- 能说明为什么预约要用户确认、写库为什么要鉴权吗？
- 能讲清 token 成本和延迟怎么控制吗？
