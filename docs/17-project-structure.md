# 17 · 项目结构详解

这份文档把每个目录、每个关键文件“是干什么的、为什么放这里”讲清楚。
面试时被问“你项目怎么组织的”，直接按这张图答。

## 1. 顶层目录

```text
lab_agent_std/
├── backend/              # 后端：FastAPI + AI Agent
├── frontend/             # 前端：Vue3
├── docs/                 # 学习文档（01-18）
├── resume/               # 简历
├── docker-compose.yml    # 一键编排 postgres/redis/backend/frontend
├── .gitignore            # 忽略 .env、.venv、node_modules、*.db
└── README.md             # 安装运行教程
```

## 2. 后端目录（重点）

```text
backend/
├── app/
│   ├── main.py               # 入口：生命周期、CORS、异常注册、路由挂载
│   ├── config.py             # 全局配置，读 .env
│   ├── database.py           # 引擎、Session、Base
│   ├── init_data.py          # 启动时写入演示数据
│   ├── mcp_server.py         # 独立运行的 MCP Server
│   ├── api/                  # 接口层：只做参数接收和调用 service
│   │   ├── router.py         # 汇总所有子路由到 /api
│   │   ├── auth.py           # 登录/注册
│   │   ├── user.py           # 用户信息/密码/用户管理
│   │   ├── files.py          # 文件上传
│   │   ├── lab.py            # 实验室管理 + 学生列表
│   │   ├── equipment.py      # 设备管理
│   │   ├── reservation.py    # 预约创建/列表/取消/审核
│   │   └── ai.py             # AI 对话 + SSE 流式
│   ├── services/             # 业务层：核心逻辑，AI 工具复用这里
│   │   ├── auth_service.py   # 登录注册逻辑
│   │   ├── user_service.py   # 用户 CRUD、改密
│   │   ├── lab_service.py    # 实验室 CRUD、分页
│   │   ├── equipment_service.py # 设备 CRUD、分页
│   │   ├── reservation_service.py # 预约核心校验、过期扫描
│   │   ├── kb_service.py     # 混合检索 + rerank + 缓存
│   │   ├── vector_store.py   # 向量库抽象（Chroma / Milvus）
│   │   ├── ai_service.py     # 早期手写 tool loop（教学对照）
│   │   ├── agent_tools.py    # LangGraph 工具 + MCP 加载
│   │   └── agent_service.py  # LangGraph 图 + 流式
│   ├── models/               # ORM：users/labs/equipments/reservations
│   ├── schemas/              # 接口入参出参（Pydantic）
│   ├── dependencies/         # get_current_user / get_current_admin / 限流
│   ├── common/               # 统一响应 + 异常处理
│   └── utils/                # JWT、密码
├── data/
│   ├── kb/                   # RAG 知识库 Markdown
│   ├── chroma/               # ChromaDB 持久化目录（运行时生成）
│   └── milvus.db             # Milvus Lite 文件（运行时生成）
├── uploads/                  # 上传的文件
├── requirements.txt
├── Dockerfile
├── .env.example
└── evaluate_rag.py           # RAG 评估脚本
```

## 3. 三层架构怎么串

```text
api/        接收参数、鉴权、调用 service
    ↓
services/   业务规则、事务、异常
    ↓
models/     ORM 对象 <-> 数据库表
```

`schemas/` 是接口契约，`models/` 是数据库对象，二者分离：
接口不暴露密码，数据库细节不泄漏到前端。

## 4. 前端目录

```text
frontend/
├── src/
│   ├── main.js             # 入口：注册 Element Plus 和图标
│   ├── App.vue             # 根组件，只放 router-view
│   ├── router/index.js     # 路由 + 登录守卫
│   ├── api/                # 每个模块的请求函数
│   ├── utils/              # request/auth/user
│   ├── components/         # ReserveDialog 等复用组件
│   └── views/              # 页面
├── vite.config.js          # @ 别名、/api 代理、SSE 防缓冲
├── nginx.conf              # 生产反代
├── Dockerfile
└── package.json
```

## 5. 一次“智能预约”的完整调用链

```text
浏览器(AIChat.vue)
  -> fetch /api/ai/chat/stream (SSE)
  -> Nginx/Vite 代理
  -> FastAPI api/ai.py
  -> ai_rate_limiter(Redis 限流)
  -> agent_service.stream_agent
  -> LangGraph 图：agent -> tools -> agent
  -> agent_tools 里的工具
       ├─ search_lab_docs -> kb_service -> vector_store(Chroma/Milvus)
       ├─ list_open_labs -> lab_service -> PostgreSQL/MySQL/SQLite
       └─ create_lab_reservation -> reservation_service -> 数据库
  -> SSE 逐字推回前端
```

## 6. 面试怎么讲

“我的项目后端分四层：api 只收参数，service 放业务规则，model 对应数据库，
schema 做接口契约。AI 工具不是新写一套逻辑，而是复用 service，所以普通接口
和 Agent 落库走的是一样的业务校验。向量库抽象成接口，Chroma 和 Milvus 可切换。
这样讲清楚分层，比罗列技术名词有说服力得多。”
