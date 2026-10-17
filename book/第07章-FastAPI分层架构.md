# 第 07 章 · FastAPI 分层架构

## 开篇：从「能跑」到「能维护」的距离

写一个能跑的 FastAPI 接口，只需要 10 行：

```python
from fastapi import FastAPI
app = FastAPI()

@app.get("/labs")
def list_labs():
    return [{"id": 1, "name": "A301"}]
```

但当你的项目有 31 个接口、5 张表、一个 Agent、一条 RAG 管线时，这种写法会导致：

```python
@app.post("/reservation")
def create_reservation(data: dict, db=Depends(get_db), user=Depends(get_current_user)):
    # 校验
    if not data.get("lab_id"):
        raise HTTPException(400, "缺少 lab_id")
    # 查库
    lab = db.query(Lab).get(data["lab_id"])
    if not lab:
        raise HTTPException(404, "实验室不存在")
    # 冲突检测
    conflict = db.query(Reservation).filter(...).first()
    if conflict:
        raise HTTPException(409, "时段冲突")
    # 插入
    r = Reservation(...)
    db.add(r)
    db.commit()          # 忘了 rollback！
    # 还要记日志、发通知...
    return {"id": r.id}
```

**问题清单**：

| 问题 | 后果 |
|---|---|
| 业务逻辑在路由里 | 无法复用、无法单测（要起 HTTP 服务） |
| 异常抛出格式不统一 | 前端要处理 N 种错误结构 |
| 事务没有 rollback | 异常时留下脏数据 |
| `data: dict` 无校验 | 类型错误在运行时才炸 |
| 权限判断散落各处 | 容易漏判 |
| 200 行的路由函数 | 没人敢改 |

**分层架构就是为了解决这些**。这一章讲这个项目是怎么分的，以及每一层为什么要这么切。

---

## 一、整体分层

```
┌──────────────────────────────────────────────────────────┐
│  API 层  app/api/*.py                                     │
│  职责：协议转换（HTTP ↔ Python）、依赖注入、路由注册       │
│  禁止：业务逻辑、直接写 SQL                                │
└──────────────────────┬───────────────────────────────────┘
                       │ 调用
┌──────────────────────▼───────────────────────────────────┐
│  Service 层  app/services/*.py                            │
│  职责：业务逻辑、事务边界、调用 ORM、编排 Agent/RAG        │
│  禁止：HTTP 概念（Request/Response）                      │
└──────────────────────┬───────────────────────────────────┘
                       │ 调用
┌──────────────────────▼───────────────────────────────────┐
│  Model 层  app/models/*.py                                │
│  职责：数据表定义、关系                                    │
│  禁止：业务逻辑                                            │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│  数据库                                                    │
└──────────────────────────────────────────────────────────┘

横向支撑（贯穿各层）：
├─ schemas/      Pydantic 请求响应模型（校验与文档）
├─ dependencies/ 依赖注入（auth、rate_limit）
├─ common/       统一响应、统一异常
├─ utils/        工具函数（jwt、password）
└─ config.py     集中配置
```

### 为什么这么分？三层判据

**判据 1：能不能脱离 HTTP 运行？**

Service 层不应该 import 任何 `fastapi` 的东西。这样它才能被：
- HTTP 接口调用
- 定时任务调用
- CLI 脚本调用
- **单元测试直接调用**（不用起服务器）

> 💡 **面试话术**：「我判断分层的标准是：Service 层能不能脱离 HTTP 运行。我项目里 Service 函数签名是 `(db, current_user, data) -> Model`，全是普通 Python 对象，不依赖 Request/Response。这样做的好处是单测可以直接调 service 函数，不用起 HTTP 服务器，测试快很多；而且将来要加定时任务、CLI、或者换成 gRPC，业务逻辑完全不用改。」

**判据 2：改动频率**

越底层的东西改动越少。Model（表结构）几乎不改，Service 偶尔改，API 层跟着业务改。

**判据 3：依赖方向单向**

```
API → Service → Model
```

**不允许反向依赖**（Service 不能 import API），也不允许跨层（API 不能直接写 SQL）。

---

## 二、API 层：只做三件事

### 2.1 一个标准的路由函数

```python
# backend/app/api/reservation.py
@router.post("", response_model=ApiResponse[ReservationOut])
def create(
    data: ReservationCreate,                              # ① Pydantic 校验
    db: Session = Depends(get_db),                        # ② 依赖注入
    current_user: User = Depends(get_current_user),       # ② 鉴权
):
    reservation = reservation_service.create_reservation(db, current_user, data)
    return ok(reservation)
```

**数一下：4 行。** 所有业务逻辑都在 `reservation_service.create_reservation` 里。

**这四行分别做了什么**：

| 行 | 作用 | 失败时 |
|---|---|---|
| `data: ReservationCreate` | Pydantic 自动校验字段类型、必填 | 自动返回 422 + 详细错误字段 |
| `db = Depends(get_db)` | 拿数据库会话 | - |
| `current_user = Depends(get_current_user)` | 解 JWT、查用户 | 自动返回 401 |
| `return ok(reservation)` | 统一响应包装 | - |

**注意：这里没有 try/except** —— 因为异常由全局异常处理器统一处理（见第四节）。

### 2.2 路由注册

```python
# backend/app/api/router.py
from app.api import auth, user, files, kb, lab, equipment, reservation, ai

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(user.router, prefix="/user", tags=["用户"])
api_router.include_router(lab.router, prefix="/lab", tags=["实验室"])
api_router.include_router(equipment.router, prefix="/equipment", tags=["设备"])
api_router.include_router(reservation.router, prefix="/reservation", tags=["预约"])
api_router.include_router(kb.router, prefix="/kb", tags=["知识库"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(files.router, prefix="/files", tags=["文件"])
```

**为什么用统一的 router.py 汇总？**

1. `main.py` 只需要 `include_router(api_router, prefix="/api")` 一行
2. 新增模块只改这一个文件
3. `prefix` 和 `tags` 集中管理，Swagger 文档分组清晰

### 2.3 项目的 31 个接口分布

| 模块 | 接口数 | 前缀 |
|---|---|---|
| user | 7 | `/api/user` |
| lab | 5 | `/api/lab` |
| ai | 4 | `/api/ai` |
| equipment | 4 | `/api/equipment` |
| kb | 4 | `/api/kb` |
| reservation | 4 | `/api/reservation` |
| auth | 2 | `/api/auth` |
| files | 1 | `/api/files` |
| **合计** | **31** | |

> ⚠️ **诚实数据**：这 31 个接口里只有 **5 个是 `async def`**（都是 `/api/ai` 下的）。其余 26 个是普通 `def`。
>
> 原因见第 3 章：CRUD 接口内部用的是同步 SQLAlchemy Session，用 `def` 让 FastAPI 丢到线程池，反而比 `async def` 里调同步代码更安全。
>
> **简历上不要写「全异步」**——这是我实测过的数据，面试官一查就露馅。正确的说法是「IO 密集的 Agent 链路使用异步，同步 DB 操作的 CRUD 由线程池处理」。

---

## 三、Service 层：业务与事务边界

### 3.1 一个标准的 Service 函数

```python
# backend/app/services/reservation_service.py（简化）
def create_reservation(db: Session, current_user: User, data: ReservationCreate):
    # 1. 参数校验（业务级，Pydantic 管不了的）
    if data.start_time >= data.end_time:
        raise BusinessException(message="开始时间必须早于结束时间")

    # 2. 行锁：锁住实验室这一行，防止并发插入
    lab = db.query(Lab).filter(Lab.id == data.lab_id).with_for_update().first()
    if not lab:
        raise BusinessException(message="实验室不存在")

    # 3. 时段冲突检测（区间重叠）
    conflict = db.query(Reservation).filter(
        Reservation.lab_id == data.lab_id,
        Reservation.status.in_(["pending", "approved"]),
        Reservation.start_time < data.end_time,
        Reservation.end_time > data.start_time,
    ).first()
    if conflict:
        raise BusinessException(message="该时段已被预约")

    # 4. 插入
    reservation = Reservation(
        user_id=current_user.id,
        lab_id=data.lab_id,
        start_time=data.start_time,
        end_time=data.end_time,
        status="pending",
    )
    db.add(reservation)

    # 5. 事务边界：commit 必须包 try/except/rollback
    try:
        db.commit()
        db.refresh(reservation)
    except Exception:
        db.rollback()
        raise BusinessException(message="预约创建失败，请稍后重试")

    return reservation
```

**这段代码体现了 Service 层的五个职责**：

| 职责 | 位置 | 说明 |
|---|---|---|
| 业务校验 | 步骤 1 | Pydantic 做不了的（跨字段、依赖 DB 的） |
| 并发控制 | 步骤 2 | `with_for_update()`（第 11 章） |
| 规则判断 | 步骤 3 | 时段重叠（第 11 章） |
| 数据操作 | 步骤 4 | ORM |
| **事务边界** | 步骤 5 | **try/commit/except/rollback** |

### 3.2 事务边界的演进（真实缺陷修复）

**原始版本**：

```python
db.add(reservation)
db.commit()          # ❌ 没有 rollback
db.refresh(reservation)
return reservation
```

**问题**：如果 `commit()` 抛异常（约束冲突、连接断开），事务处于「未决」状态。虽然 FastAPI 的 `get_db` 最终会 `close()`，但**没显式 rollback**，可能留下脏状态。

**修复后**（第 11 章详解）：

```python
try:
    db.commit()
    db.refresh(reservation)
except Exception:
    db.rollback()        # ✅ 显式回滚
    raise BusinessException(...)
```

> ⚠️ **这是代码审查发现的 C1 缺陷**，共修了 4 处 commit。
>
> **面试话术**：「我项目里有四处 commit 没有 rollback 兜底。代码审查时发现后全部补上了 try/except/rollback。另外我还给 `get_db` 的 except 分支也加了 rollback——因为如果 service 层抛异常跑到依赖清理那里，事务也应该回滚，这是最后一道保险。」

### 3.3 Service 层禁止什么

```python
# ❌ 禁止：HTTP 概念
def create_reservation(request: Request): ...

# ❌ 禁止：返回 HTTP 响应
def create_reservation(...) -> JSONResponse: ...

# ❌ 禁止：直接抛 HTTPException
raise HTTPException(400, "参数错误")
# ✅ 应该：抛业务异常
raise BusinessException(message="参数错误")
```

**为什么要抛 `BusinessException` 而不是 `HTTPException`？**

因为 Service 层不应该知道 HTTP。`BusinessException` 是**业务概念**（「这个操作不合法」），由 API 层的异常处理器翻译成 HTTP 状态码。

这样 Service 层被调用时（比如定时任务里），异常语义仍然成立。

---

## 四、统一响应与统一异常

### 4.1 响应结构

所有接口返回同一个结构：

```json
{
  "code": 200,
  "message": "success",
  "data": { ... }
}
```

```python
# backend/app/common/response.py
def ok(data=None, message="success", code=200):
    return {"code": code, "message": message, "data": data}
```

**为什么统一？**

| 好处 | 说明 |
|---|---|
| 前端统一处理 | 一个拦截器搞定：判断 `code === 200` |
| 错误信息一致 | 前端弹 `message` 即可 |
| 便于扩展 | 可以加 `trace_id`、`timestamp` |
| Swagger 清晰 | `response_model=ApiResponse[XOut]` 有完整文档 |

**前端对应的拦截器**：

```js
// frontend/src/utils/request.js
request.interceptors.response.use(
  response => {
    const res = response.data
    if (res.code === 200) return res.data      // 直接返回 data，业务代码不用解包
    ElMessage.error(res.message)               // 统一错误提示
    return Promise.reject(new Error(res.message))
  },
  error => {
    // HTTP 层错误（401/403/500）
    if (error.response?.status === 401) {
      removeToken(); router.push('/login')
    }
    return Promise.reject(error)
  }
)
```

### 4.2 四级异常处理

```python
# backend/app/common/exceptions.py
class BusinessException(Exception):
    """业务异常：可预期的业务错误（参数不合法、资源不存在、权限不足）。"""
    def __init__(self, message="操作失败", code=400):
        self.message = message
        self.code = code
        super().__init__(message)

class ApprovalRequired(Exception):
    """特殊业务异常：需要用户确认（Agent 写库审批）。"""
    def __init__(self, thread_id, payload):
        self.thread_id = thread_id
        self.payload = payload
```

```python
# backend/app/main.py
app.add_exception_handler(BusinessException, business_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
```

**四级分别是**：

| 级别 | 触发 | HTTP 码 | 处理方式 |
|---|---|---|---|
| 1. 业务异常 | `raise BusinessException(...)` | 400（可指定） | 返回 `message` 给前端 |
| 2. 校验异常 | Pydantic 自动 | 422 | 格式化成「字段：错误」 |
| 3. HTTP 异常 | `raise HTTPException` / 路由未匹配 | 401/404/... | 转换结构 |
| 4. 兜底异常 | 任何未捕获的 | 500 | **记录堆栈，返回通用文案** |

**为什么第四级必须存在？**

因为不处理的话，未捕获异常会导致：

1. 前端收到一个 HTML 的 500 页面（不是 JSON），解析失败
2. 敏感信息（堆栈、SQL、路径）可能泄露到响应里
3. 无法记录日志

```python
async def unhandled_exception_handler(request, exc):
    logger.exception("未处理异常：%s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "data": None},
    )
```

**关键**：`logger.exception` 记录了完整堆栈（内部可查），但**返回给用户的是通用文案**（不泄露细节）。

> ⚠️ **面试考点**：「为什么不能把异常详情返回给前端？」
> 答：三个原因——泄露实现细节（给攻击者线索）、可能包含敏感数据（SQL、路径、token）、用户体验差（用户看不懂堆栈）。正确做法是内部记日志 + 外部返回通用文案 + 带一个 trace_id 方便排查。

### 4.3 422 错误的格式化

FastAPI 默认的 422 错误长这样：

```json
{
  "detail": [
    {"loc": ["body", "lab_id"], "msg": "field required", "type": "value_error.missing"},
    {"loc": ["body", "start_time"], "msg": "invalid datetime format", "type": "value_error.datetime"}
  ]
}
```

前端处理起来很麻烦。项目做了格式化：

```python
async def validation_exception_handler(request, exc):
    errors = exc.errors()
    # 提取最后一个 loc 元素作为字段名
    messages = []
    for e in errors:
        field = e["loc"][-1] if e["loc"] else "参数"
        messages.append(f"{field}: {e['msg']}")
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "；".join(messages), "data": None},
    )
```

输出：

```json
{"code": 422, "message": "lab_id: field required；start_time: invalid datetime format", "data": null}
```

前端直接 `ElMessage.error(res.message)` 就能显示。

---

## 五、依赖注入：三种形态

FastAPI 的 `Depends` 是这套架构的粘合剂。项目里用了三种形态。

### 形态 1：函数依赖（最常用）

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
    finally:
        db.close()

# 使用
def list_labs(db: Session = Depends(get_db)): ...
```

### 形态 2：类依赖（带参数）

```python
class RoleChecker:
    def __init__(self, required_role: str):
        self.required_role = required_role

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != self.required_role:
            raise BusinessException(code=403, message="权限不足")
        return current_user

admin_only = RoleChecker("admin")

# 使用
@router.post("/documents")
def upload(current_user: User = Depends(admin_only)): ...
```

**这是怎么工作的？**

`Depends(admin_only)` 里的 `admin_only` 是一个**实例**。FastAPI 发现它是可调用对象（定义了 `__call__`），就调用它，并把 `__call__` 的参数也当作依赖去解析。

**好处**：`admin_only` 可以被复用，不用写重复的判断逻辑。

### 形态 3：嵌套依赖

```python
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),   # ← 依赖
    db: Session = Depends(get_db),                                     # ← 依赖
) -> User:
    ...
```

`get_current_user` 自己也有依赖。FastAPI 会**递归解析**。

**依赖图**：

```
create_reservation 路由
├─ Depends(get_db) → SessionLocal()
├─ Depends(get_current_user)
│   ├─ Security(security) → 从 Header 提取 Bearer token
│   └─ Depends(get_db) → ★ 复用同一个 Session（有缓存！）
```

> 💡 **重要**：FastAPI 对同一个请求中的相同依赖有**缓存**。所以 `get_db` 只会执行一次，路由和 `get_current_user` 拿到的是**同一个 Session**。这保证了事务一致性。

### 5.1 依赖缓存的坑

```python
# 默认有缓存
def get_db(): ...

# 关闭缓存
def get_db(): ...
def route(a = Depends(get_db, use_cache=False), b = Depends(get_db)):
    # a 和 b 是不同的 Session！
```

**什么时候要关闭缓存？** 极少。通常你希望同一个请求共用一个 DB 会话。

---

## 六、配置管理：pydantic-settings

```python
# backend/app/config.py
class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "智能实验室预约系统"
    DEBUG: bool = False

    # 大模型
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = "deepseek-chat"
    JUDGE_MODEL: str = ""          # 裁判模型（与被测分离）

    # 数据库
    DATABASE_URL: str = "sqlite:///./lab.db"
    CHECKPOINT_DATABASE_URL: str = ""

    # 向量库
    VECTOR_BACKEND: str = "chroma"     # chroma / pgvector / milvus
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"

    # 检索
    HYBRID_SEARCH_ENABLED: bool = True
    RERANK_ENABLED: bool = True
    QUERY_REWRITE_ENABLED: bool = True

    # Agent 健壮性
    TOOL_TIMEOUT_SECONDS: float = 30.0
    TOOL_MAX_RETRIES: int = 1
    MAX_CONTEXT_TOKENS: int = 4000
    TRIM_STRATEGY: str = "sliding_window"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

### 为什么用 pydantic-settings 而不是 os.getenv？

| | `os.getenv` | `pydantic-settings` |
|---|---|---|
| 类型转换 | 手动 `int(...)` | 按注解自动 |
| 集中声明 | 散落各处 | 一个类看全 |
| IDE 补全 | 无 | 有 |
| 校验 | 无 | 可以加约束 |
| 默认值 | 要手写 `or "xxx"` | 直接写 |

**校验示例**：

```python
from pydantic import Field

class Settings(BaseSettings):
    TOOL_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=300)
    VECTOR_BACKEND: str = Field(default="chroma", pattern="^(chroma|pgvector|milvus)$")
```

这样配置写错了**启动时就报错**，不用等到运行时。

### 单例 vs 每次实例化

```python
settings = Settings()   # 模块级单例
```

**好处**：所有模块 `from app.config import settings` 拿到同一个对象。

**测试时怎么覆盖？**

```python
# 方式一：monkeypatch
def test_something(monkeypatch):
    monkeypatch.setattr(settings, "TOOL_TIMEOUT_SECONDS", 0.1)

# 方式二：环境变量 + 重新实例化（需要重新 import）
```

> ⚠️ **单例的坑**：单例让测试变难。如果测试很多，考虑用依赖注入 `settings` 而不是全局导入。但对本项目的规模，单例够用。

---

## 七、生命周期：lifespan

```python
# backend/app/main.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 启动 ──
    logger.info("服务启动中...")
    init_db()                    # 建表
    await warmup_embedding()     # 预热 embedding 模型
    logger.info("服务启动完成")

    yield                        # ← 服务运行中

    # ── 关闭 ──
    logger.info("服务关闭中...")
    await close_vector_store()
    logger.info("服务已关闭")

app = FastAPI(title="智能实验室预约系统", lifespan=lifespan)
```

### 为什么用 lifespan 而不是模块顶层代码？

| 对比项 | 模块顶层 | lifespan |
|---|---|---|
| 执行时机 | import 时 | 服务启动/关闭时 |
| 能 await | ❌ 不能 | ✅ 能 |
| 测试可控 | ❌ import 就跑 | ✅ 可控制 |
| 资源释放 | 没地方写 | 和申请配对写 |
| 多 worker | 每个 worker 都跑一次 | 每个 worker 各跑一次（一样） |

**最关键的理由是测试可控性**：

```python
# 测试时如果初始化在模块顶层
import app.main    # ← 这一行就会连数据库、加载模型！测试还没开始就失败了

# 用 lifespan 的话
from app.main import app
with TestClient(app) as client:    # ← 进入上下文才初始化
    ...
```

### 项目里 lifespan 做了什么

| 动作 | 为什么 |
|---|---|
| `init_db()` | 开发环境下自动建表（生产应该用 Alembic） |
| `await warmup_embedding()` | **避免第一个用户承担冷启动延迟** |
| `await close_vector_store()` | 释放连接，优雅关闭 |

**预热 embedding 的重要性**（第 1 章讲过）：

`sentence-transformers` 首次调用要加载约 130MB 的模型权重，可能要 10 秒。不预热的话，第一个提问的用户要等 10 秒才看到回答。

> 💡 **面试话术**：「我在 lifespan 里预热了 embedding 模型。原因是 sentence-transformers 首次加载要加载一百多兆的权重，冷启动第一次检索可能要十几秒。预热之后用户第一次提问就是快的。这是 Agent 应用很常见的优化——模型加载、向量库连接这类重资源的初始化都应该在服务启动时完成，而不是让第一个用户买单。」

---

## 八、最小可运行骨架：完整分层 Demo

```python
"""
layered_demo.py —— 完整分层架构最小实现
运行：pip install fastapi uvicorn pydantic && python layered_demo.py
然后访问 http://localhost:8000/docs

演示：API / Service / Model 三层 + 依赖注入 + 统一响应 + 四级异常
"""
from contextlib import asynccontextmanager
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════
# Model 层（真实项目用 SQLAlchemy，这里用内存字典模拟）
# ══════════════════════════════════════════════════════════

class Lab:
    def __init__(self, id: int, name: str, capacity: int):
        self.id, self.name, self.capacity = id, name, capacity

class Reservation:
    def __init__(self, id: int, lab_id: int, user_id: int, hours: str, status: str):
        self.id, self.lab_id = id, lab_id
        self.user_id, self.hours, self.status = user_id, hours, status

class FakeDB:
    """模拟数据库（含事务语义）。"""
    def __init__(self):
        self.labs = {1: Lab(1, "A301 细胞实验室", 20), 2: Lab(2, "B205 材料实验室", 15)}
        self.reservations: dict = {}
        self._next_id = 1
        self._dirty = False

    def add(self, obj):
        self._dirty = True
        self._pending = obj

    def commit(self):
        """模拟提交。这里故意模拟一种失败：id 冲突。"""
        if self._dirty:
            obj = self._pending
            obj.id = self._next_id
            self.reservations[obj.id] = obj
            self._next_id += 1
            self._dirty = False

    def rollback(self):
        """模拟回滚。"""
        self._dirty = False
        self._pending = None

DB = FakeDB()

# ══════════════════════════════════════════════════════════
# common：统一响应与异常
# ══════════════════════════════════════════════════════════

class BusinessException(Exception):
    """业务异常：Service 层抛，API 层翻译成 HTTP。"""
    def __init__(self, message="操作失败", code=400):
        self.message, self.code = message, code
        super().__init__(message)

def ok(data=None, message="success", code=200):
    return {"code": code, "message": message, "data": data}

# ══════════════════════════════════════════════════════════
# schemas：Pydantic 请求模型
# ══════════════════════════════════════════════════════════

class ReservationCreate(BaseModel):
    lab_id: int = Field(..., description="实验室 ID")
    hours: str = Field(..., min_length=1, description="预约时段，如 '14:00-17:00'")

class ReservationOut(BaseModel):
    id: int
    lab_id: int
    hours: str
    status: str

# ══════════════════════════════════════════════════════════
# Service 层：业务逻辑 + 事务边界（不依赖 HTTP！）
# ══════════════════════════════════════════════════════════

def create_reservation(db: FakeDB, user_id: int, data: ReservationCreate) -> Reservation:
    """创建预约。注意：签名里没有任何 FastAPI 的东西。"""

    # 1. 业务校验（Pydantic 做不了的：跨字段、依赖 DB）
    if data.lab_id not in db.labs:
        raise BusinessException(message="实验室不存在", code=404)

    # 2. 业务规则：同一用户同一时段不能重复预约
    for r in db.reservations.values():
        if r.user_id == user_id and r.hours == data.hours and r.status != "cancelled":
            raise BusinessException(message="你已预约该时段", code=409)

    # 3. 创建对象
    reservation = Reservation(
        id=0, lab_id=data.lab_id, user_id=user_id,
        hours=data.hours, status="pending"
    )
    db.add(reservation)

    # 4. ★ 事务边界：commit 必须包 try/except/rollback
    try:
        db.commit()
    except Exception:
        db.rollback()      # ← 关键：没有这行会留下脏状态
        raise BusinessException(message="预约创建失败，请稍后重试")

    return reservation

def list_reservations(db: FakeDB, user_id: int, is_admin: bool) -> list:
    """查询预约。管理员看全部，普通用户只看自己的。"""
    rows = list(db.reservations.values())
    if not is_admin:
        rows = [r for r in rows if r.user_id == user_id]   # ← 权限过滤下沉
    return rows

# ══════════════════════════════════════════════════════════
# dependencies：依赖注入
# ══════════════════════════════════════════════════════════

def get_db() -> Generator[FakeDB, None, None]:
    """数据库会话依赖。yield 之后的代码在响应返回后执行。"""
    try:
        yield DB
    except Exception:
        DB.rollback()      # ← 兜底回滚
    # 真实项目这里会 db.close()

security = HTTPBearer()

class CurrentUser:
    def __init__(self, id: int, role: str):
        self.id, self.role = id, role

FAKE_USERS = {
    "token-student": CurrentUser(1, "student"),
    "token-admin":   CurrentUser(2, "admin"),
}

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> CurrentUser:
    """解 token → 拿用户。真实项目还会查库确认账号状态。"""
    user = FAKE_USERS.get(credentials.credentials)
    if not user:
        raise BusinessException(message="登录已失效", code=401)
    return user

class RoleChecker:
    """类依赖：带参数的权限检查。"""
    def __init__(self, required_role: str):
        self.required_role = required_role

    def __call__(self, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role != self.required_role:
            raise BusinessException(message="权限不足", code=403)
        return user

admin_only = RoleChecker("admin")

# ══════════════════════════════════════════════════════════
# 异常处理：四级
# ══════════════════════════════════════════════════════════

async def business_handler(request, exc: BusinessException):
    return JSONResponse(
        status_code=exc.code,
        content=ok(None, message=exc.message, code=exc.code),
    )

async def validation_handler(request, exc: RequestValidationError):
    messages = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=ok(None, message="；".join(messages), code=422),
    )

async def http_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ok(None, message=exc.detail, code=exc.status_code),
    )

async def unhandled_handler(request, exc: Exception):
    # 真实项目这里要 logger.exception(exc)
    print(f"!! 未处理异常: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content=ok(None, message="服务器内部错误", code=500),  # ← 不泄露细节
    )

# ══════════════════════════════════════════════════════════
# lifespan：生命周期
# ══════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(">> 启动：初始化资源（真实项目：建表、预热模型、连向量库）")
    yield
    print(">> 关闭：释放资源")

# ══════════════════════════════════════════════════════════
# API 层：只做协议转换
# ══════════════════════════════════════════════════════════

app = FastAPI(title="分层架构 Demo", lifespan=lifespan)

app.add_exception_handler(BusinessException, business_handler)
app.add_exception_handler(RequestValidationError, validation_handler)
app.add_exception_handler(HTTPException, http_handler)
app.add_exception_handler(Exception, unhandled_handler)

@app.post("/reservation", response_model=dict)
def create(
    data: ReservationCreate,                          # ① Pydantic 校验
    db: FakeDB = Depends(get_db),                     # ② 依赖注入
    user: CurrentUser = Depends(get_current_user),    # ③ 鉴权
):
    """创建预约。路由里只有 2 行，业务全在 service。"""
    reservation = create_reservation(db, user.id, data)   # ← 调用 service
    return ok(ReservationOut(
        id=reservation.id, lab_id=reservation.lab_id,
        hours=reservation.hours, status=reservation.status,
    ).model_dump())

@app.get("/reservation")
def list_mine(
    db: FakeDB = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """查询预约。权限过滤在 service 里做。"""
    rows = list_reservations(db, user.id, is_admin=(user.role == "admin"))
    return ok([
        ReservationOut(id=r.id, lab_id=r.lab_id, hours=r.hours, status=r.status).model_dump()
        for r in rows
    ])

@app.delete("/reservation/{rid}")
def cancel(
    rid: int,
    user: CurrentUser = Depends(admin_only),   # ← 类依赖：只有管理员能取消
):
    """取消预约（管理员专属）。演示类依赖的用法。"""
    return ok(None, message=f"管理员 {user.id} 取消了预约 {rid}")

@app.get("/boom")
def boom():
    """演示兜底异常处理。"""
    raise RuntimeError("数据库连接炸了（敏感信息不应暴露）")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

**启动后用这些命令验证**：

```bash
# 1. 正常创建（用 student token）
curl -X POST http://localhost:8000/reservation \
  -H "Authorization: Bearer token-student" \
  -H "Content-Type: application/json" \
  -d '{"lab_id":1,"hours":"14:00-17:00"}'

# 2. 重复预约 → 409 业务异常
curl -X POST http://localhost:8000/reservation \
  -H "Authorization: Bearer token-student" \
  -H "Content-Type: application/json" \
  -d '{"lab_id":1,"hours":"14:00-17:00"}'
# {"code":409,"message":"你已预约该时段","data":null}

# 3. 缺字段 → 422 校验异常（已格式化）
curl -X POST http://localhost:8000/reservation \
  -H "Authorization: Bearer token-student" \
  -H "Content-Type: application/json" \
  -d '{"lab_id":1}'
# {"code":422,"message":"hours: field required","data":null}

# 4. 无效 token → 401
curl -X POST http://localhost:8000/reservation \
  -H "Authorization: Bearer bad-token" \
  -H "Content-Type: application/json" \
  -d '{"lab_id":1,"hours":"14:00-17:00"}'

# 5. 非管理员调用管理员接口 → 403
curl -X DELETE http://localhost:8000/reservation/1 \
  -H "Authorization: Bearer token-student"

# 6. 未处理异常 → 500 且不泄露详情
curl http://localhost:8000/boom
# {"code":500,"message":"服务器内部错误","data":null}
# 终端里能看到完整堆栈（内部可查）
```

**这个 demo 验证了分层架构的全部要点**：

1. 路由只有 2 行
2. Service 不依赖 HTTP
3. 四级异常各有各的处理
4. 依赖注入三种形态
5. 事务有 rollback
6. 权限过滤下沉到 service

---

## 九、项目代码定位

| 文件 | 职责 | 关键位置 |
|---|---|---|
| `app/main.py` | 应用入口、lifespan、异常注册、CORS | 全文 |
| `app/api/router.py` | 路由汇总 | 9 个 `include_router` |
| `app/api/*.py` | 31 个接口 | 每个函数 3-5 行 |
| `app/services/*.py` | 业务逻辑 | 13 个 service |
| `app/models/*.py` | 5 张表 | user/lab/equipment/reservation/kb_document |
| `app/schemas/*.py` | Pydantic 模型 | 请求/响应 |
| `app/dependencies/auth.py` | `get_current_user`、角色检查 | - |
| `app/dependencies/rate_limit.py` | 限流 | Redis 可选 |
| `app/common/response.py` | `ok()` | - |
| `app/common/exceptions.py` | `BusinessException`、`ApprovalRequired` | - |
| `app/config.py` | `Settings` | 全文 |
| `app/database.py` | 引擎、`get_db` | - |

### 一个值得注意的设计：`ApprovalRequired`

```python
class ApprovalRequired(Exception):
    """写库类工具需要用户确认时抛给 API 层的信号。"""
    def __init__(self, thread_id: str, payload: dict):
        self.thread_id = thread_id
        self.payload = payload
```

这是一个**跨层信号**：Service 层（Agent）发现需要人工确认，抛这个异常；API 层捕获后转换成 HTTP 200 + `approval_required` 事件。

**为什么是 200 而不是 4xx？** 因为「需要确认」不是错误，是正常的流程中间态。

```python
# api/ai.py
try:
    answer = await agent_service.run_agent(db, current_user, data, thread_id)
    return ok({"type": "answer", "content": answer, "thread_id": thread_id})
except ApprovalRequired as exc:
    return ok({
        "type": "approval_required",
        "thread_id": exc.thread_id,
        "payload": exc.payload,
    })
```

---

## 本章速记卡

1. **三层**：API（协议转换）→ Service（业务+事务）→ Model（数据）。依赖单向。
2. **Service 层判据**：能不能脱离 HTTP 运行？不 import fastapi，才能被单测/定时任务/CLI 复用。
3. **路由只有 3-5 行**：校验、依赖注入、调 service、包装响应。
4. **统一响应** `{code, message, data}`，前端一个拦截器搞定。
5. **四级异常**：业务 / 校验(422) / HTTP / 兜底(500)。兜底必须记日志 + 返回通用文案（不泄露细节）。
6. **Service 抛 `BusinessException` 不抛 `HTTPException`**，保持与 HTTP 解耦。
7. **依赖注入三形态**：函数、类（带参数）、嵌套。同请求内依赖有缓存（DB 会话共用）。
8. **`get_db` 用 yield** 保证 close/rollback 一定执行。
9. **lifespan 优于模块顶层**：能 await、测试可控、资源配对释放。
10. **本项目**：31 接口只有 5 个 async（Agent 链路），26 个 CRUD 用 def 走线程池。

---

## 面试问答：分层与工程

### Q1：「你的项目怎么分层的？为什么这么分？」

**满分答法**：

> 三层：API 层、Service 层、Model 层，加上横向的 schemas、dependencies、common、config。
>
> API 层只做协议转换——Pydantic 校验入参、依赖注入拿身份和 DB 会话、调用 service、包装统一响应。每个路由函数基本只有三五行。
>
> Service 层放业务逻辑和事务边界，签名是 `(db, current_user, data)` 这种纯 Python 对象，**不 import 任何 FastAPI 的东西**。这是我的分层判据：Service 能不能脱离 HTTP 运行？能，就意味着它可以被单测直接调用（不用起服务器），也能被定时任务、CLI 复用。
>
> Model 层就是 SQLAlchemy 的表定义，不含业务逻辑。
>
> 横向有四个支撑：schemas 放 Pydantic 模型、dependencies 放依赖注入（鉴权、限流）、common 放统一响应和异常、config 做集中配置。

---

### Q2：「异常怎么处理？为什么不能把异常详情返回给前端？」

**满分答法**：

> 我做了四级异常处理，在 main.py 里注册：
>
> 第一级业务异常，Service 层抛 `BusinessException`，带 message 和 code，转成对应 HTTP 状态码和统一响应结构。
>
> 第二级校验异常，Pydantic 自动抛 422，我做了格式化——默认的 detail 是个数组，前端处理麻烦，我提取字段名和错误信息拼成「字段名: 错误」的字符串。
>
> 第三级 HTTP 异常，比如路由不匹配、HTTPException，转成统一结构。
>
> 第四级兜底，捕获所有未处理异常，**记录完整堆栈到日志，但返回通用文案「服务器内部错误」**。
>
> 为什么不能返回详情：一是泄露实现细节给攻击者线索；二是可能包含敏感数据（SQL 语句、文件路径、token）；三是用户也看不懂堆栈。正确做法是内部记日志、外部给通用文案、带一个 trace_id 方便用户报障时定位。

---

### Q3：「为什么 Service 层抛 BusinessException 而不是 HTTPException？」

**满分答法**：

> 因为 Service 层不应该知道 HTTP 的存在。
>
> `HTTPException` 是一个 HTTP 概念——它有 status_code。但「这个用户已预约该时段」是一个业务概念，它既可能出现在 HTTP 接口里，也可能出现在定时任务、CLI 脚本、甚至 Agent 工具调用里。
>
> 如果 Service 抛 HTTPException，那它在非 HTTP 场景下就语义错乱了。抛 BusinessException 的话，由最外层的异常处理器负责翻译成 HTTP 状态码——这个翻译只发生一次，在 API 边界上。
>
> 这也是分层架构的核心思想：**内层不依赖外层**。

---

### Q4：「依赖注入你怎么用的？」

**满分答法**：

> 三种形态。
>
> 一是函数依赖，最常用。`get_db` 用 yield 保证 finally 里一定 close，`get_current_user` 解 JWT 拿用户。
>
> 二是类依赖，用 `__call__` 实现带参数的依赖。比如 `RoleChecker("admin")` 生成一个管理员检查器，多个接口复用，不用写重复的判断。
>
> 三是嵌套依赖，`get_current_user` 自己依赖 `get_db` 和 `Security(security)`，FastAPI 会递归解析。
>
> 有个关键点：FastAPI 对同一个请求内的相同依赖**有缓存**。所以路由里的 `db` 和 `get_current_user` 里的 `db` 是同一个 Session，这保证了事务一致性。如果误用 `use_cache=False` 会拿到两个 Session，事务就断了。

---

### Q5：「为什么用 lifespan？」

**满分答法**：

> 三个理由。
>
> 一是能 await。模块顶层代码不能 await，但初始化经常是 IO 密集的——我要加载 embedding 模型、要连向量库。
>
> 二是测试可控。模块顶层代码在 import 时就执行，导致你 import 一下就会连数据库、加载模型，测试没法在干净状态下开始。用 lifespan 的话，只有进入 `TestClient` 上下文才初始化。
>
> 三是资源配对。申请和释放写在同一个函数里，yield 之前申请、之后释放，不会漏。写在顶层的话，关闭逻辑没地方放。
>
> 我在 lifespan 里做了三件事：建表、预热 embedding 模型、注册关闭时的资源释放。预热模型特别重要——sentence-transformers 首次加载要十几秒，不预热的话第一个用户就要等这么久。

---

### Q6：「你的项目是全异步的吗？」（陷阱题）

**满分答法**（诚实 + 体现判断力）：

> 不是，我也不建议这么写。实测 31 个接口里只有 5 个是 `async def`，都在 `/api/ai` 下。
>
> 判断标准很明确：**如果函数内部全是异步调用，用 async def；如果内部有同步阻塞调用（比如同步 SQLAlchemy Session），用普通 def**。
>
> 因为 FastAPI 对 `def` 路由会丢到线程池执行，阻塞只占一个线程；而 `async def` 路由直接在事件循环里跑，一旦内部有同步阻塞，**所有请求全部卡死**。最危险的组合就是 `async def` 里写同步代码。
>
> 我那 5 个 async 接口是 Agent 链路，需要 `await` 模型调用和 `async for` 消费流式事件，必须异步。其余 26 个 CRUD 接口用同步 ORM，所以用 `def` 走线程池更安全。
>
> 这个数字我是实测过的，简历上我也不会写「全异步」，因为不属实。

---

### Q7：「如果要支持更高并发，你会改什么？」（追问）

**满分答法**：

> 几个方向：
>
> 一是数据层换异步。现在是同步 SQLAlchemy + `to_thread`，线程池大小会成为瓶颈。换成 `AsyncSession` 能真正利用事件循环，但改动面大——所有 service 函数都要改成 async。
>
> 二是工具并行。Agent 的 `tool_node` 现在是串行 for 循环，如果模型一次要调多个独立工具，应该用 `asyncio.gather`。不过要注意有些工具有依赖关系，不能无脑并行。
>
> 三是连接池配置。PostgreSQL 的连接池大小、checkpointer 的连接池，都要根据实际并发调，别把连接耗尽。
>
> 四是限流。我现在用 Redis 做了滑动窗口限流，但 `REDIS_URL` 没配，等于没启用。生产上必须开，防止单个用户刷爆服务。
>
> 但说实话，现在最大的延迟来源是模型调用（几秒），不是数据库（几十毫秒）。所以优化的优先级应该是：先减少模型调用次数（缓存、减少无效重试），再考虑数据层异步化。

---

## 常见坑

### 坑 1：业务逻辑写在路由里

200 行的路由函数，无法复用、无法单测。

### 坑 2：Service 层 import fastapi

分层被破坏，Service 无法脱离 HTTP 运行。

### 坑 3：commit 没有 rollback

异常时留下脏事务。（本项目修过 4 处）

### 坑 4：兜底异常返回详情

泄露敏感信息。

### 坑 5：`async def` 里调同步 ORM

阻塞事件循环，所有请求卡死。

### 坑 6：依赖用 `use_cache=False` 导致多个 Session

事务断裂。

### 坑 7：初始化写在模块顶层

测试无法在干净状态下开始。

### 坑 8：422 错误不格式化

前端要处理复杂的嵌套结构。

### 坑 9：配置散落各处用 os.getenv

没有类型、没有补全、改了找不到。

### 坑 10：CORS 配 `*` 又要带 credentials

两者不能共存，浏览器会拒绝。

---

## 动手练习

### 练习 1（必做）

跑通第八节的 `layered_demo.py`，用 curl 验证 6 个场景：

1. 正常创建 → 200
2. 重复预约 → 409
3. 缺字段 → 422（注意看格式化的 message）
4. 无效 token → 401
5. 非管理员删预约 → 403
6. `/boom` → 500 且无详情泄露

### 练习 2

打开 `backend/app/api/` 下的任意接口文件，数一下每个路由函数的行数。

如果超过 15 行，思考：哪些逻辑应该移到 service？

### 练习 3

给项目加一个「取消预约」接口，要求：

- 只有本人或管理员能取消（权限判断在 service 里）
- 已审核通过的预约不能取消（业务规则）
- 用 `BusinessException` 抛错
- commit 包 try/except/rollback

### 练习 4（进阶）

验证依赖缓存：

```python
# 在 get_db 里打印 id(db)
# 在路由和 get_current_user 里各打印一次
# 看是不是同一个对象
```

然后加 `use_cache=False` 再试一次，观察差异。

---

## 下一章

**第 08 章 · Pydantic 数据契约**

路由函数签名里那个 `data: ReservationCreate` 是整套架构的第一道防线——它自动校验类型、必填、格式，还能生成 Swagger 文档。

但 Pydantic 的能力远不止「校验」。下一章讲：模型继承和复用、自定义验证器、Field 的各种约束、请求响应模型分离（为什么不能共用一个）、以及 Pydantic 在 Agent 场景的特殊用法（工具参数 schema 就是从 Pydantic 生成的）。
