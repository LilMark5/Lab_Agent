# 马凯

**求职意向**：AI Agent / 后端开发 实习生　|　**到岗时间**：可尽快　|　**城市**：[意向城市]

- 电话：[你的手机号]
- 邮箱：[你的邮箱]
- GitHub / 项目主页：[你的链接]

## 教育背景

**河北东方学院** · 软件工程 · 本科

2023.09 – 2027.06（预计）　|　主修课程：数据结构、操作系统、数据库原理、计算机网络、软件工程、Web 开发

## 专业技能

- **后端**：Python、FastAPI、SQLAlchemy、JWT 鉴权、统一响应与全局异常、文件上传
- **数据库**：MySQL、PostgreSQL、Redis，熟悉事务、索引、分页查询
- **AI 工程**：LangChain、LangGraph、RAG、Function Calling、MCP、ReAct、Embedding、Milvus、SSE
- **检索**：向量检索 + BM25 + RRF 融合 + rerank 重排，会用命中率指标评估检索质量
- **前端**：Vue3、Vite、Element Plus、axios、TypeScript（基础）
- **工程化**：Docker、Docker Compose、Nginx、Git、Linux 常用命令

## 项目经历

### 智能实验室预约系统 · AI Agent 全栈项目

独立开发　|　FastAPI + Vue3 + LangGraph + Milvus + MCP

- 从零实现 FastAPI + Vue3 的实验室预约业务闭环：用户登录注册、实验室/设备管理、预约提交与管理员审核，后端采用 API / Service / Model / Schema 分层，实现 JWT 鉴权、统一响应与全局异常处理。
- 基于 LangGraph 构建 ReAct 风格 Agent，模型自主决定调用知识检索、实验室查询、预约落库等工具，多轮工具循环受 `recursion_limit` 约束，写库前强制用户确认，避免误操作。
- 实现 RAG 检索：向量召回 + BM25 关键词召回 + RRF 融合 + bge-reranker 精排，向量库抽象为 ChromaDB / Milvus 双后端，并用 Redis 缓存相似问题、对 AI 接口做限流。
- 将实验室查询能力封装为独立 MCP Server，Agent 通过 langchain-mcp-adapters 接入，实现工具与业务解耦。
- 使用 SSE 实现流式输出，前端实时展示“思考 / 查库 / 提交预约”过程；编写检索评估脚本统计 hit@2，验证混合检索相对纯向量检索的提升。
- 使用 Docker Compose 编排 PostgreSQL(pgvector) + Redis + 后端 + 前端，实现一键部署。

### 其他项目（按需补充）

- [项目名称]　|　[技术栈]　|　[一句话说明你做了什么、解决了什么问题]

## 自我评价

- 对 AI Agent 方向有明确职业目标，能独立完成从需求、开发、部署到评估的完整闭环。
- 注重工程习惯：代码分层清晰、关键逻辑有注释、密钥不提交仓库、用 Git 管理版本。
- 学习以“能讲清原理 + 能跑通验证”为标准，不满足于会调 API。

## 其他

- 语言：英语 [CET-4/6 情况]
- 证书 / 竞赛 / 开源： [可选，按实际情况填写]
