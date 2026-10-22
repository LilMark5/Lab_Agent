# 智能实验室预约系统 · AI Agent 毕业设计

一个从“传统 CRUD 业务”逐步升级到“AI Agent”的可运行全栈项目，适合作为
软件工程/AI 方向毕业设计，也适合作为 AI Agent 实习的简历项目。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue3 + Vite + Element Plus（可选 TypeScript） |
| 后端 | Python + FastAPI + SQLAlchemy |
| 数据库 | SQLite（默认）/ PostgreSQL + pgvector / MySQL |
| 缓存限流 | Redis |
| 向量库 | ChromaDB / Milvus / PostgreSQL + pgvector（HNSW） |
| AI | LangChain + LangGraph + RAG（递归切块 + 混合检索 + rerank + 父上下文）+ Tool Calling + MCP + ReAct + SSE |
| 部署 | Docker + Docker Compose + Nginx |

## 一、环境要求

| 软件 | 版本建议 | 说明 |
| --- | --- | --- |
| Python | 3.11 / 3.12 | AI 生态预编译包最全，3.14 部分依赖需源码编译 |
| Node.js | 18+ | 前端构建 |
| MySQL/PostgreSQL | 可选 | 默认 SQLite 零配置 |
| Docker | 可选 | 一键部署用 |

## 一之bis、⚡ 快速启动（TL;DR）

依赖已装好的机器，两个终端各一条命令：

```powershell
# 终端 1：后端（SQLite 零配置，不需要 PostgreSQL）
cd backend
$env:DATABASE_URL=""; $env:VECTOR_BACKEND="chroma"
.\.venv-clean\Scripts\python.exe -m uvicorn app.main:app --port 8000 --host 127.0.0.1

# 终端 2：前端
cd frontend
npm run dev
```

打开 <http://127.0.0.1:5175/>，用 `admin / 123456`（管理员）或 `student / 123456`（学生）登录。
也可以直接双击仓库根目录的 `start-dev.ps1`，它会开两个窗口把前后端一起拉起来。

> **⚠️ 最容易卡住的地方**：`backend/.env` 里默认写的是
> `DATABASE_URL=postgresql+psycopg2://...@127.0.0.1:5432/lab_agent` 和
> `VECTOR_BACKEND=pgvector`。**没装 PostgreSQL（也没 Docker）的机器直接启动会失败**，
> 报 `OperationalError: Connection refused`（5432 端口没人听）。
>
> 两条路选一条：
> 1. **不装 PG（推荐先用这个跑通）**：把 `DATABASE_URL=` 留空 → 自动用
>    `backend/lab_agent.db`（SQLite，启动时自动建表并灌演示数据），
>    同时 `VECTOR_BACKEND=chroma`。上面的 `$env:` 覆盖就是干这个的。
> 2. **要用 PG + pgvector**：先起 PostgreSQL，建库 `lab_agent`，装 pgvector 扩展，
>    再执行 `alembic upgrade head`，最后正常启动。
>
> 判据：日志出现 `Application startup complete` 就是连上了；
> 出现 `向量库预热超时` 不是错误，只是首个 RAG 请求会慢几秒。

启动后建议按这个顺序验收（都是实测跑通的）：

| 步骤 | 操作 | 预期 |
| --- | --- | --- |
| 1 | 打开 <http://127.0.0.1:8000/docs> | Swagger 文档，27 个接口 |
| 2 | 登录 `student / 123456` | 返回 token |
| 3 | AI 助手问「实验室开放时间是几点？」 | 命中《开放时间.md》并带来源表格 |
| 4 | AI 助手问「现在有哪些开放的实验室？」 | 调用 `list_open_labs` 查库返回 4 间 |
| 5 | 「帮我预约明天下午 14-16 点的人工智能实验室」→ 再回「确认」 | 弹出**操作确认框**（LangGraph interrupt）；点取消则**不写库** |
| 6 | 可选：`python -m app.mcp_server` | 8100 端口起 MCP，暴露 3 个只读工具 |

## 二、后端安装与运行

### 1. 进入后端目录并创建虚拟环境

> 如果你机器上已经有一个被污染的 `.venv`（里面是 Python 3.14 的包），
> 请改用干净的 `.venv-clean`。本仓库已为 Python 3.11 重建好了该环境。

```powershell
cd backend
py -3.11 -m venv .venv-clean   # 首次创建；已存在则跳过
.venv-clean\Scripts\Activate.ps1
```

> macOS / Linux 激活命令是 `source .venv/bin/activate`。

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

依赖较多，首次安装建议使用国内镜像：

```powershell
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 3. 配置环境变量

```powershell
Copy-Item .env.example .env
```

打开 `.env`，重点填：

```text
# 数据库：留空用 SQLite；接 PostgreSQL 示例：
# DATABASE_URL=postgresql+psycopg2://postgres:123456@127.0.0.1:5432/lab_agent
DATABASE_URL=

# 大模型：OpenAI 兼容协议，DeepSeek/通义千问/Agnes 都能接
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 国内下载向量模型用镜像，否则第一次启动会卡在下载
HF_ENDPOINT=https://hf-mirror.com

# 向量库：auto / chroma / milvus / pgvector
# pgvector 需要 DATABASE_URL 指向启用 pgvector 扩展的 PostgreSQL
VECTOR_BACKEND=auto
# 注意：Milvus Lite 不支持 Windows；Windows 上要用 Milvus 需通过 Docker 起 Milvus 服务。
MILVUS_LOCAL_URI=./data/milvus.db

# Redis：可选，留空则自动降级不缓存不限流
REDIS_URL=
```

### 4. 启动后端

使用 PostgreSQL 时，首次启动前先执行数据库迁移：

```powershell
.\.venv-clean\Scripts\python.exe -m alembic upgrade head
```

SQLite（`DATABASE_URL` 留空）无需这步，启动时会自动建表。

```powershell
.\.venv-clean\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1
```

启动后：

- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/>

首次启动会自动写入演示数据（PostgreSQL 需先执行上面的迁移）：

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | admin | 123456 |
| 学生 | student | 123456 |

## 三、前端安装与运行

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 <http://localhost:5175>。Vite 已把 `/api`、`/uploads` 代理到
`http://127.0.0.1:8000`，所以前端不用写死后端地址。

生产构建：

```powershell
npm run build   # 产物在 dist/
npm run preview # 本地预览构建结果
```

## 四、AI 能力联调顺序（重要）

1. **先跑通对话**：`.env` 配好 `LLM_API_KEY`，重启后端，登录后打开「AI智能助手」。
2. **再验证 RAG**：问“实验室开放时间是几点”，应命中 `data/kb/开放时间.md`。
   第一次会下载向量模型，请设置 `HF_ENDPOINT=https://hf-mirror.com`。
3. **验证工具调用**：问“现在有哪些开放的实验室”，模型应调用 `list_open_labs` 查库。
4. **验证预约 Agent**：说“帮我预约明天下午的实验室”，Agent 会先复述预约信息，
   真正落库前前端会弹出「操作确认」对话框，点「确认」后才真实写入；点「取消」
   则本次操作被放弃。这个确认不是靠提示词，而是 LangGraph 的 interrupt 中断机制。
5. **验证 MCP**：先开 MCP 服务再走 Agent：

```powershell
python -m app.mcp_server        # 默认 http://127.0.0.1:8100/mcp
```

然后在 `.env` 保持 `MCP_ENABLED=true`、`MCP_URL=http://127.0.0.1:8100/mcp`，
Agent 会优先从 MCP 加载读工具。

## 五、Docker 一键部署（可选）

根目录执行：

```powershell
docker compose up --build
```

会启动四个服务：

| 服务 | 端口 | 作用 |
| --- | --- | --- |
| postgres(pgvector) | 5432 | 关系库 + 向量 |
| redis | 6379 | 缓存/限流 |
| backend | 8000 | FastAPI + Agent |
| frontend | 5175 | Nginx + Vue3 |

## 六、RAG 评估

评估分两侧：**检索侧**（召回得准不准）和**生成侧**（答得对不对）。题目统一放在
`backend/eval_dataset.py`，两侧共用同一批问题，分数才能互相印证。

### 1. 检索评估

```powershell
cd backend
python evaluate_rag.py
```

脚本对比“纯向量 / 混合检索 / 混合+rerank”三种策略的 Hit@1、Hit@3、MRR、nDCG@3，
并打印每条问题命中的源文档。知识库文档会先经过递归切块（默认 200 字、40 字重叠），
检索与 BM25 都在块粒度上执行，命中后按 source + chunk_index 扩展父上下文并带引用。

> 当前内置知识库只有 4 篇文档，三种策略都是满分——这是语料太小导致的饱和，
> 不代表检索策略没有差异。要看真实差距得先扩充评测语料。

### 2. 生成质量评估（RAGAS）

检索指标满分不代表答案能用：模型可能读错数字，也可能在没有依据时直接编。
生成侧用 RAGAS 补上 faithfulness / answer_relevancy / context_precision / context_recall。

```powershell
cd backend
pip install -r requirements-eval.txt      # 只需装一次
.\.venv-clean\Scripts\python.exe evaluate_generation.py
```

跑一次约 5 分钟（14 条用例），明细落到 `backend/eval_reports/generation.json`。
`--limit 3` 可只跑前几条做冒烟，`--concurrency` 可调并发。

> **依赖提醒**：ragas 0.4.3 依赖 `langchain-community` 的
> `chat_models.vertexai` 模块，而该模块在 `langchain-community` 0.4.x 已被移除，
> 所以 `requirements-eval.txt` 把版本钉在 `0.3.31`。原因与排查过程见
> [docs/21-rag-evaluation.md](docs/21-rag-evaluation.md#71-ragas-043-与-langchain-community-04x-不兼容必踩)。

指标含义、实测分数、口径陷阱（`context_precision` 看排序不看比例、
`answer_relevancy` 对拒答类恒为 0、分数存在 run-to-run 波动）
以及「怎么确认分数可信」的裁判自检方法，都写在
[docs/21 RAG 生成质量评估](docs/21-rag-evaluation.md)。

## 知识库文档管理（动态 RAG）

- `POST /api/kb/documents`：上传 Markdown/TXT/PDF/DOCX，自动解析、切块、向量化入库，
  内容按 SHA-256 去重，重复上传直接复用已有文档。
- `GET /api/kb/documents`：文档列表与状态（ready/failed）。
- `GET /api/kb/documents/{id}/search?query=`：在指定文档内检索并带引用。
- `DELETE /api/kb/documents/{id}`：删除文档并同步清理其全部向量。

上传的文档会进入混合检索（向量召回 + BM25 关键词召回 + rerank），
AI 助手回答时会按文件名注明来源，例如「根据《量子计算平台说明.md》」。
AI 助手页面提供「检索上传文档」开关，关闭后对话只在系统内置知识库范围内检索，
请求体对应字段为 `include_uploaded`。

## 七、常见问题排查

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 启动卡在下载模型 | HuggingFace 被墙 | `.env` 设 `HF_ENDPOINT=https://hf-mirror.com` |
| 登录 401 | token 过期/被改 | 重新登录，检查 `Authorization: Bearer` |
| 前端刷新 404 | Vue history 模式 | Nginx 需 `try_files ... /index.html` |
| AI 返回“未安装 LangGraph” | 依赖没装全 | `pip install -r requirements.txt` |
| SSE 一次性刷出 | 代理缓冲 | 检查 nginx `proxy_buffering off` |
| 端口被占用 | 8000/5175 已用 | 换端口，前端改 vite 代理 target |
| 前端报 `EACCES: permission denied 127.0.0.1:517x` | 端口被 Radmin VPN 等软件以 Bound 状态预占（Vite 不会自动换端口） | 换一个空闲端口改 `vite.config.js` 的 `server.port`，或关掉该软件 |

## 会话记忆与人工审批（LangGraph 升级）

- 后端通过 `langgraph-checkpoint-sqlite` 把会话状态持久化到
  `backend/data/checkpoints.db`，前端每个页面会话持有一个 `thread_id`，
  服务重启后同一会话仍可继续多轮对话。
- 写库类工具（`create_lab_reservation`）会先进入 approval 节点并触发
  LangGraph `interrupt`，等待用户确认后再执行；恢复接口为：
  - `POST /api/ai/chat` / `POST /api/ai/chat/resume`（非流式）
  - `POST /api/ai/chat/stream` / `POST /api/ai/chat/stream/resume`（SSE 流式）

