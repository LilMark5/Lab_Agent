# 学习文档导航

这套文档的目标不是复述课程步骤，而是帮你建立一个 AI Agent 工程师的知识骨架。
每个模块都对应项目里真实存在的代码，建议边读边回到源码点开看。

> **推荐从这里开始**：[00 从零到面试全流程](00-从零到面试全流程.md) 是一份
> 从头到尾的操作 + 教学总纲，按 20 天打卡表走，再回下面各篇深读细节。

| 顺序 | 文档 | 对应项目模块 |
| --- | --- | --- |
| 00 | 从零到面试全流程（总纲） | 全部 |
| 01 | 项目总览与架构 | backend/app/main.py、frontend/src |
| 02 | Vue3 前端 | frontend/src/views、router、utils |
| 03 | FastAPI 企业级 | backend/app/api、common、dependencies |
| 04 | SQLAlchemy 与数据库 | backend/app/database.py、models、services |
| 05 | JWT 鉴权 | backend/app/utils/jwt.py、dependencies/auth.py |
| 06 | LangChain 企业级 | backend/app/services/ai_service.py |
| 07 | RAG 深入浅出 | backend/app/services/kb_service.py、data/kb |
| 08 | LangGraph 零基础 | backend/app/services/agent_service.py |
| 09 | Tool Calling | backend/app/services/agent_tools.py |
| 10 | SSE 流式输出 | backend/app/api/ai.py、frontend/src/views/AIChat.vue |
| 11 | AI Agent 工程师成长路线 | 综合与延伸 |
| 12 | 简历含金点与面试准备 | 简历条目、面试答法 |
| 13 | Git 从零到面试够用 | 版本控制、分支、回退、冲突 |
| 14 | MCP 从零入门 | backend/app/mcp_server.py |
| 15 | Milvus 与混合检索、rerank | vector_store.py、kb_service.py |
| 16 | Redis、PostgreSQL 与 Docker 部署 | rate_limit.py、docker-compose.yml |
| 17 | 项目结构详解 | 全目录、调用链 |
| 18 | 核心面试题库 | 面试准备 |
| 20 | 工程升级上下文（交接文档） | 本轮全部改造、环境与未决问题 |
| 21 | RAG 生成质量评估（RAGAS） | backend/evaluate_generation.py、eval_dataset.py |
| 22 | 项目总结（阶段性盘点） | 全局：架构、测试、评估、已知问题与路线 |
| 23 | 代码审查报告（Agent 岗标准） | 五维度审查：缺陷分级 + 面试应对 |

## 面试速成系列（30–38，强烈推荐）

这一套是**面试速成专用**，比上面 00–23 的课程式文档深一个量级。每篇统一结构：
**原理详解 → 最小可运行骨架（带注释）→ 项目里对应哪块代码（精确到文件与函数）→ 面试高频问答 → 速记卡**。

想快速过一遍面试，直接按顺序读 30 → 38 即可。

| 序号 | 文档 | 对应项目模块 | 面试命中率 |
| --- | --- | --- | --- |
| 30 | FastAPI 分层架构与依赖注入 | `app/api`、`common`、`dependencies`、`main.py` | ⭐⭐⭐⭐ |
| 31 | SQLAlchemy 2.x 与事务并发控制 | `database.py`、`reservation_service.py`、`models` | ⭐⭐⭐⭐⭐ |
| 32 | JWT 鉴权与 RBAC 角色守卫 | `utils/jwt.py`、`dependencies/auth.py`、`router/index.js` | ⭐⭐⭐⭐ |
| 33 | LangGraph 状态机 Agent | `services/agent_service.py` | ⭐⭐⭐⭐⭐ |
| 34 | Tool Calling 与工具工程（含 MCP） | `services/agent_tools.py`、`mcp_server.py` | ⭐⭐⭐⭐⭐ |
| 35 | RAG 检索管线全流程 | `services/kb_service.py`、`kb_chunking.py` | ⭐⭐⭐⭐⭐ |
| 36 | 向量数据库三后端与 pgvector | `services/vector_store.py` | ⭐⭐⭐⭐ |
| 37 | SSE 流式前后端打通 | `api/ai.py`、`api/ai.js`、`views/AIChat.vue` | ⭐⭐⭐⭐ |
| 38 | 评估体系：RAGAS 与检索指标 | `evaluate_*.py`、`eval_dataset.py`、`run_eval.py` | ⭐⭐⭐⭐⭐ |

> **优先级建议**：时间不够就先读 **31（并发）、33（LangGraph）、35（RAG）、38（评估）** 这四篇——
> 它们对应简历上含金量最高的四段。

---

## 模块文档（00–23）

这套文档的目标不是复述课程步骤，而是帮你建立一个 AI Agent 工程师的知识骨架。
每个模块都对应项目里真实存在的代码，建议边读边回到源码点开看。

1. **先跑起来再问原理。** 项目能启动，你才有调试和验证的对象。
2. **从数据流出发读代码。** 一次请求：浏览器 -> Vite 代理 -> FastAPI 路由 -> Service -> 数据库 -> 返回。
3. **把“调用关系”画出来。** AI 应用最怕只会背概念，不会说清“模型 -> 工具 -> 数据库”的来回。

推荐配合阅读：

- Vue 官方文档：https://cn.vuejs.org/
- FastAPI 官方文档：https://fastapi.tiangolo.com/zh/
- LangChain 文档：https://python.langchain.com/
- LangGraph 文档：https://langchain-ai.github.io/langgraph/

## 简历与运行

- 安装运行教程：[根目录 README](../README.md)
- 简历：[resume/马凯-AI-Agent实习生简历.md](../resume/马凯-AI-Agent实习生简历.md)
- 简历填写说明：[resume/填写说明.md](../resume/填写说明.md)
