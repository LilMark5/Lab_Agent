# 马凯

**求职意向**：AI Agent / 后端开发 实习生　|　**到岗时间**：可尽快　|　**城市**：[意向城市]

- 电话：[你的手机号]
- 邮箱：[你的邮箱]
- GitHub / 项目主页：[你的链接]

## 教育背景

**河北东方学院** · 软件工程 · 本科

2023.09 – 2027.06（预计）　|　主修课程：数据结构、操作系统、数据库原理、计算机网络、软件工程、Web 开发

## 专业技能

- **后端开发**：Python、FastAPI（分层架构 / 依赖注入 / lifespan 生命周期 / 异步流式接口）、Pydantic v2 校验、SQLAlchemy 2.x、Alembic 迁移、JWT + bcrypt 鉴权、统一响应与四级异常处理、文件上传
- **数据库**：PostgreSQL、SQLite、Redis（限流 / 检索结果缓存，可选依赖、未配置时优雅降级）；熟悉事务边界与失败回滚、索引、并发控制（SELECT FOR UPDATE + 时间区间重叠判定）、pgvector 向量检索与 HNSW 索引
- **AI 工程**：LangChain、LangGraph（ReAct 状态机 / checkpointer 会话持久化 / interrupt 人工审批 / 上下文窗口管理）、Function Calling、MCP（FastMCP 服务端 + 客户端接入）、Embedding、SSE 流式输出
- **RAG**：递归切块、向量召回 + BM25 关键词召回、RRF 融合、CrossEncoder 重排、父上下文扩展与引用溯源、查询改写；ChromaDB / pgvector 实跑，Milvus 了解
- **评估**：Hit@1/3、MRR、nDCG@3 检索指标；RAGAS 四指标生成评估，裁判模型与被测模型分离
- **前端**：Vue 3（Composition API）、Vue Router（角色路由守卫）、Element Plus、axios 拦截器、Markdown 渲染 + DOMPurify 防 XSS；Vite 构建（TypeScript 了解）
- **工程化**：Git、pytest（37 个单元 / 集成测试）、Docker（了解）、Linux 常用命令

## 项目经历

### 智能实验室预约系统 · AI Agent 全栈项目

独立开发　|　FastAPI + Vue3 + LangGraph + pgvector + MCP

- 从零实现 FastAPI + Vue3 的业务闭环（登录注册、实验室/设备管理、预约提交与管理员审核）：API / Service / Model / Schema 分层，JWT 鉴权、统一响应与全局异常，共 31 个接口；用 Alembic 管理数据库迁移，预约并发场景用 SELECT FOR UPDATE 防止重复预订，配套并发集成测试。
- 基于 LangGraph 构建 ReAct Agent：模型自主决定调用知识检索、实验室查询、预约落库等工具；用 checkpointer 将会话状态持久化（服务重启后可继续多轮对话），写库类操作通过 interrupt 中断等待用户确认、确认后用 Command(resume) 恢复执行；为审批闭环、多轮历史不重复等关键行为补了确定性集成测试。
- 补齐 Agent 线上稳定性三处工程细节：checkpointer 双后端抽象（SQLite 零配置 / PostgreSQL 多实例、会话与业务库同源）；按 token 预算裁剪对话历史（滑动窗口与摘要两种策略，并保护 tool_calls 与 ToolMessage 配对不被拆散）；工具调用加超时 + 有限重试，最终失败回填结构化错误给模型自纠，避免单次卡死拖垮整张图。
- 实现完整 RAG 管线：递归切块 → 向量召回 + BM25 关键词召回 → RRF 融合 → 交叉编码器精排 → 命中块扩展父上下文并带引用；向量库抽象为 ChromaDB / pgvector / Milvus 三后端统一接口，pgvector 侧采用 HNSW 索引并实跑全链路验证（embedding 维度变化自动重建）；检索前支持可开关的查询改写，把口语化问句规范化以提升召回，改写失败自动回退原句。
- 建立离线评估体系：检索侧评 Hit@1/3、MRR、nDCG@3，生成侧接入 RAGAS 四指标（faithfulness / answer_relevancy / context_precision / context_recall），自建 14 条标注用例（含「资料没有时不许编造」的拒答边界）；裁判模型与被测模型分离配置，避免模型自评引入系统性噪声；通过对照实验定位出检索指标饱和、判官模型噪声、context_precision 排序口径三个评测陷阱，形成评估文档。
- 将实验室查询能力封装为独立 MCP Server（FastMCP，streamable-http），Agent 经 langchain-mcp-adapters 接入，MCP 不可用时自动回退本地工具，实现工具与业务解耦。
- 用 SSE 实现流式输出：前端 fetch + ReadableStream 逐帧解析「思考 / 查库 / 等待审批」过程，配合 DOMPurify 渲染 Markdown 防 XSS；接入 Redis（可选依赖）做 AI 接口限流与检索结果缓存，按语料版本自动失效，未配置时优雅降级不影响本地开发。

### 其他项目（按需补充）

- [项目名称]　|　[技术栈]　|　[一句话说明你做了什么、解决了什么问题]

## 自我评价

- 对 AI Agent 方向有明确职业目标，能独立完成从需求、开发、测试到评估的完整闭环。
- 注重工程习惯：代码分层清晰、关键逻辑有注释、密钥不提交仓库、用 Git 管理版本。
- 学习以“能讲清原理 + 能跑通验证”为标准，不满足于会调 API。

## 其他

- 语言：英语 [CET-4/6 情况]
- 证书 / 竞赛 / 开源： [可选，按实际情况填写]
