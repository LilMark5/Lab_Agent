# 30 · FastAPI 分层架构与依赖注入

> **速成定位**：这是整个后端的骨架。面试官问「你的项目怎么组织的」「为什么用 FastAPI」「请求进来经过哪些步骤」，全靠这一篇。
> **一句话**：FastAPI = Starlette（异步 Web 内核）+ Pydantic（数据校验），本项目用它做了 `API → 依赖注入 → Service → Model` 四层分离。

---

## 目录

1. [为什么是 FastAPI](#1-为什么是-fastapi)
2. [分层架构：为什么不能把代码全写在路由里](#2-分层架构)
3. [依赖注入 Depends：本项目最核心的设计](#3-依赖注入-depends)
4. [统一响应与四级异常](#4-统一响应与四级异常)
5. [lifespan 生命周期](#5-lifespan-生命周期)
6. [同步与异步路由：一个高频追问](#6-同步与异步路由)
7. [最小可运行骨架（带详细注释）](#7-最小可运行骨架)
8. [项目里对应哪块代码](#8-项目里对应哪块代码)
9. [面试高频问答](#9-面试高频问答)
10. [速记卡](#10-速记卡)

---

## 1. 为什么是 FastAPI

FastAPI 不是自己实现了 Web 服务器，它是「站在两个巨人肩膀上」：

| 组成 | 作用 | 面试价值 |
| --- | --- | --- |
| **Starlette** | 异步 Web 内核：路由分发、中间件、WebSocket、StreamingResponse | 解释「为什么支持高并发、为什么能流式输出」 |
| **Pydantic v2** | 用类型注解做数据校验与序列化（底层是 Rust 写的 pydantic-core） | 解释「参数校验为什么不用手写 if」 |
| **ASGI** | 异步服务器网关接口，uvicorn 是它的实现 | 对比 WSGI（Flask/Django）：ASGI 支持长连接和流式 |

```text
浏览器 → uvicorn(ASGI) → Starlette(中间件/路由) → 你的路由函数 → 依赖注入 → Service → DB
```

### 和 Flask / Django 怎么比（面试常问）

- **Flask**：WSGI，同步为主，生态老但异步弱。
- **Django**：大而全，自带 ORM/Admin，但重，不适合做纯 API 服务。
- **FastAPI**：天生异步、**自动生成 OpenAPI 文档**（`/docs`）、**类型即校验**、性能好。做 AI 后端几乎是标配，因为 LangChain / LangGraph 全生态都是 async 优先。

> 本项目实测版本：FastAPI 0.143.0、Pydantic 2.14.1。

---

## 2. 分层架构

### 2.1 为什么不能把代码全写在路由里

反例（很多初学者项目长这样）：

```python
@app.post("/reservation")
def create(data: dict, token: str = Depends(oauth)):
    user = db.query(User).filter(...).first()   # 查库
    if data["date"] < today:                    # 校验
        return {"msg": "日期错误"}
    if db.query(Reservation).filter(...).first():  # 冲突判断
        return {"msg": "已预约"}
    db.add(Reservation(...))                    # 落库
    db.commit()
    return {"msg": "ok"}
```

问题：

1. **路由函数又管 HTTP 又管业务**，改业务要动 HTTP 代码。
2. **无法复用**：AI Agent 的 `create_lab_reservation` 工具也想创建预约，只能复制一遍。
3. **无法单测**：测试必须起 HTTP 服务，慢。

### 2.2 本项目的分层

```text
backend/app/
├── api/          ← 只做：接参数、调依赖鉴权、调 service、包统一响应
├── schemas/      ← Pydantic 模型：请求体的形状与校验
├── services/     ← 业务规则：不认识 HTTP，只认识参数
├── models/       ← SQLAlchemy ORM：表结构
├── dependencies/ ← 可复用的依赖：鉴权、限流
├── common/       ← 统一响应 Response、业务异常 BusinessException
└── config.py     ← 配置集中管理
```

**依赖方向严格单向**：`api → services → models`，反向 import 是不允许的。

这样带来的直接好处（面试要讲）：
> 「我把预约逻辑放在 `reservation_service.create_reservation`，HTTP 接口和 AI Agent 的 `create_lab_reservation` 工具**调用的是同一个函数**，所以规则不会出现两套实现。」

项目实证：`backend/app/api/reservation.py`（HTTP 入口）和 `backend/app/services/agent_tools.py`（AI 工具）都调用 `reservation_service.create_reservation`。

---

## 3. 依赖注入 Depends

### 3.1 它解决了什么

路由里这三件事每个接口都要做：解析 token → 查用户 → 开数据库会话。

不注入就得每个函数写一遍；注入之后只写一行：

```python
@router.post("/chat")
async def chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),   # 鉴权
    db: Session = Depends(get_db),                     # 会话
): ...
```

### 3.2 三种依赖形态（都要会）

**(a) 普通函数依赖** —— 返回值直接注入：

```python
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    ...
```

注意它自己也有 `Depends`——**依赖可以嵌套**，FastAPI 会先解析子依赖。项目里 `get_current_admin` 依赖 `get_current_user`，`get_current_user` 又依赖 `get_db` 和 `oauth2_scheme`，形成一条链。

**(b) `yield` 依赖** —— 需要清理动作（关连接、关会话）：

```python
def get_db():
    db = SessionLocal()
    try:
        yield db          # 路由执行期间
    finally:
        db.close()        # 响应返回后才执行
```

FastAPI 把 `yield` 的依赖当成**上下文管理器**处理：`yield` 之前的代码在路由前执行，之后的代码在响应生成后执行。这就是为什么项目里 `get_db` 用 `yield` 而不是 `return`。

**(c) 依赖还能做「副作用」** —— 本项目有个巧妙用法：

```python
_: None = Depends(ai_rate_limiter)   # 不关心返回值，只想要它「执行限流」
```

`ai_rate_limiter` 返回值是 `None`，用它纯粹是为了**在路由执行前跑一次限流检查**。见 `backend/app/api/ai.py:29`。

### 3.3 依赖缓存（面试加分）

默认情况下 FastAPI 对**同一次请求内**的依赖做缓存（`use_cache=True`）：同一个 `get_current_user` 被多个依赖用到，只执行一次。想要每次都跑，用 `Depends(f, use_cache=False)`。

---

## 4. 统一响应与四级异常

### 4.1 统一响应：为什么业务错误也返回 HTTP 200

```python
class Response(BaseModel):
    code: int
    message: str
    data: Any = None
```

前端 axios 只判断一个字段：

```js
if (res.code === 200) return res      // 成功
if (res.code === 401) logout()        // 登录失效
else ElMessage.error(res.message)     // 其它错误弹提示
```

**面试要点**：业务错误（如「该时段已预约」）是**可预期的业务分支**，不是服务器故障，所以用 HTTP 200 + `code=500` 表达，前端处理逻辑只有一条。而真正的协议级错误（401 未授权、422 参数校验失败）仍然用 HTTP 状态码，因为那是 HTTP 语义。

### 4.2 四级异常处理

`backend/app/main.py:72-75` 注册顺序**必须**从具体到宽泛：

| 处理器 | 捕获 | HTTP 状态 | 场景 |
| --- | --- | --- | --- |
| `business_exception_handler` | `BusinessException` | **200**（body 里 code 表达） | 「账号已存在」「该时段已预约」 |
| `http_exception_handler` | `HTTPException` | 原状态码（401/403/429） | 未登录、限流 |
| `validation_exception_handler` | `RequestValidationError` | 422 | Pydantic 校验失败 |
| `global_exception_handler` | `Exception` | 500 | **兜底**，防止堆栈泄漏给前端 |

> **面试必答**：「为什么必须有兜底 handler？」—— 否则未捕获异常会返回 500 + 堆栈，既难看又泄漏实现细节。

---

## 5. lifespan 生命周期

`@asynccontextmanager` + `yield` 把「启动」和「关闭」写在一起：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动时 ----
    if not settings.DATABASE_URL:
        Base.metadata.create_all(bind=engine)   # SQLite 零配置建表
    seed_if_empty()                              # 初始化管理员账号
    await asyncio.wait_for(asyncio.to_thread(kb_service.warmup), timeout=30)  # 预热向量库
    task = asyncio.create_task(reservation_service.run_expire_scan())         # 后台任务
    yield
    # ---- 关闭时 ----
    task.cancel()
    await agent_service.close_checkpointer()
```

三个值得讲的工程细节：

1. **`asyncio.wait_for(..., timeout=30)`**：向量模型首次加载要下载权重，网络差时会卡住。加超时保证**服务不被模型下载拖死**，超时只是首个 RAG 请求慢一点。
2. **`asyncio.to_thread(kb_service.warmup)`**：`warmup` 是同步阻塞函数（加载模型、读文件），直接调用会阻塞事件循环。丢到线程池里跑，避免整个服务卡住。
3. **后台任务 `asyncio.create_task`**：过期待审核预约每 60 秒扫描一次自动取消，关闭时 `task.cancel()` 优雅退出。

---

## 6. 同步与异步路由

这是本项目的一个**诚实考点**，面试很可能被追问：

```python
def get_labs(...): ...          # 同步路由
async def chat(...): ...        # 异步路由
```

- **同步 `def` 路由**：FastAPI 会把它丢进**线程池**执行，不阻塞事件循环，但占用线程。
- **异步 `async def` 路由**：在事件循环里执行，**一旦里面有阻塞调用就会卡死整个循环**。

**本项目实测：31 个接口中只有 5 个是 `async def`**（AI 对话相关的 4 个 + 部分），其余是同步 `def`。原因是：业务接口内部用的是**同步 SQLAlchemy**（`Session` 不是 `AsyncSession`），写成 `async def` 反而会让同步 DB 调用阻塞事件循环。而 AI 接口必须 `async`，因为要 `await` 大模型调用和 `astream_events` 流式。

> **面试话术**：「同步 DB 就用同步路由，交给 FastAPI 的线程池；只有真正需要 await 的 AI 流式接口才用 async def。我没有为了『显得异步』把所有接口都写成 async——**async 里放阻塞调用比同步更糟**。」

---

## 7. 最小可运行骨架

把下面的内容存成 `mini_app.py`，`pip install fastapi uvicorn pydantic` 后 `uvicorn mini_app:app --reload` 即可运行，访问 `http://127.0.0.1:8000/docs` 看自动生成的文档。

```python
"""最小可运行骨架：完整演示 分层 / 依赖注入 / 统一响应 / 异常 / 生命周期。"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ============ 1. Schema 层：请求体的形状与校验 ============
class ItemIn(BaseModel):
    """Pydantic 模型：类型注解即校验规则。"""
    name: str
    price: float


class Response(BaseModel):
    """统一响应结构：code / message / data。"""
    code: int
    message: str
    data: Any = None

    @classmethod
    def success(cls, data=None):
        return cls(code=200, message="ok", data=data)

    @classmethod
    def error(cls, code: int, message: str):
        return cls(code=code, message=message)


# ============ 2. 业务异常 ============
class BizError(Exception):
    """可预期的业务错误，走 HTTP 200 + code 表达。"""
    def __init__(self, message: str, code: int = 500):
        self.message = message
        self.code = code


# ============ 3. Model / 存储层：真实项目换成 SQLAlchemy ============
DB = {"items": {}, "seq": 0}


# ============ 4. Service 层：只管业务规则，不认识 HTTP ============
def create_item(name: str, price: float) -> dict:
    """业务规则集中在这里，HTTP 接口和 AI 工具都能复用。"""
    if not name.strip():
        raise BizError("名称不能为空")
    if price <= 0:
        raise BizError("价格必须大于 0")
    DB["seq"] += 1
    item = {"id": DB["seq"], "name": name, "price": price}
    DB["items"][item["id"]] = item
    return item


def get_item(item_id: int) -> dict:
    item = DB["items"].get(item_id)
    if not item:
        raise BizError("记录不存在")
    return item


# ============ 5. 依赖：鉴权 + 会话（yield 版带清理） ============
def get_db():
    """yield 依赖：yield 前在路由前执行，yield 后在响应后执行。"""
    db = DB                      # 真实项目：db = SessionLocal()
    try:
        yield db                 # 路由执行期间拿到的就是它
    finally:
        pass                     # 真实项目：db.close()


def get_current_user(token: str = "demo") -> dict:
    """模拟鉴权依赖：真实项目解析 JWT 并查库。"""
    if token != "demo":
        raise BizError("未登录", code=401)
    return {"id": 1, "name": "alice"}


def rate_limiter():
    """副作用型依赖：不关心返回值，只想在路由前执行检查。"""
    # 真实项目：Redis INCR + EXPIRE，超限抛 429
    return None


# ============ 6. 生命周期：启动预热 / 关闭释放 ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("启动：建表 / 预热模型 / 起后台任务")
    yield
    print("关闭：取消后台任务 / 释放连接")


# ============ 7. 组装应用 ============
app = FastAPI(title="mini", lifespan=lifespan)


@app.exception_handler(BizError)
async def biz_handler(request: Request, exc: BizError):
    """业务异常：HTTP 仍是 200，错误语义放在 body 的 code 里。"""
    return JSONResponse(status_code=200, content=Response.error(exc.code, exc.message).model_dump())


@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    """兜底：绝不把堆栈暴露给前端。"""
    return JSONResponse(status_code=500, content=Response.error(500, "服务器内部错误").model_dump())


# ============ 8. API 层：只做接参数 + 调依赖 + 调 service + 包响应 ============
@app.post("/items")
def create(data: ItemIn, user=Depends(get_current_user), _=Depends(rate_limiter)):
    # 注意：路由里没有任何业务规则，规则全在 service。
    return Response.success(create_item(data.name, data.price)).model_dump()


@app.get("/items/{item_id}")
def read(item_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(get_item(item_id)).model_dump()
```

跑起来之后自己试三件事（这三件事就是面试素材）：

1. `POST /items` 传 `{"name":"a","price":-1}` → 返回 `{"code":500,"message":"价格必须大于 0"}`，**HTTP 状态是 200**。
2. `POST /items` 传 `{"name":"a"}`（缺 price）→ 返回 422，Pydantic 自动校验。
3. `GET /items/999` → 返回 `code=500, message="记录不存在"`。

---

## 8. 项目里对应哪块代码

### 8.1 应用入口与生命周期

**文件**：`backend/app/main.py`

| 位置 | 作用 |
| --- | --- |
| `main.py:29-50` | `lifespan`：建表 / 种子数据 / 向量库预热（带 30s 超时）/ 起过期扫描后台任务 / 关闭时释放 checkpointer |
| `main.py:61-69` | CORS 中间件（`allow_credentials=False` 的原因写在注释里） |
| `main.py:72-75` | 四级异常 handler 注册（顺序从具体到兜底） |
| `main.py:78` | `app.include_router(api)` 挂载总路由 |
| `main.py:81` | `app.mount("/uploads", StaticFiles(...))` 静态文件 |

### 8.2 路由聚合

**文件**：`backend/app/api/router.py`

```python
api = APIRouter(prefix="/api")     # 统一前缀
api.include_router(auth.router)
api.include_router(user.router)
...                                 # 8 个子路由
```

**项目接口分布（实测 31 个）**：`user` 7 / `lab` 5 / `ai` 4 / `equipment` 4 / `kb` 4 / `reservation` 4 / `auth` 2 / `files` 1。

### 8.3 依赖注入的三种形态

| 形态 | 位置 | 代码 |
| --- | --- | --- |
| 嵌套依赖（鉴权链） | `dependencies/auth.py:50-56` | `get_current_admin` ← `get_current_user` ← `get_db` + `oauth2_scheme` |
| `yield` 依赖（会话清理） | `database.py:37-51` | `get_db`，`finally: db.close()` |
| 副作用依赖（限流） | `api/ai.py:29` | `_: None = Depends(ai_rate_limiter)` |

### 8.4 统一响应

**文件**：`backend/app/common/response.py`

```python
class Response(BaseModel):
    code: int
    message: str
    data: Any = None
```

有个**真实踩坑**写在 `response.py:31-34` 的注释里，面试讲出来很加分：

```python
class PageResponse(BaseModel):
    # 字段名叫 list，如果注解写 list[Any]，会把内置 list 遮蔽成 FieldInfo，
    # 导致 Pydantic 求值失败。所以显式用 typing.List。
    list: List[Any] = Field(default_factory=list)
```

### 8.5 业务异常

**文件**：`backend/app/common/exceptions.py`

```python
class BusinessException(Exception):
    def __init__(self, message: str, code: int = 500): ...
```

用法遍布各 service，例如 `reservation_service.py:33`：`raise BusinessException(message="预约日期不能小于当前的日期")`。

### 8.6 分层调用实例（背下来）

```text
POST /api/reservation
  → api/reservation.py      路由：接参数 + Depends 鉴权
  → reservation_service.create_reservation()   业务规则 + 并发控制
  → models/reservation.py   ORM 落库
  → common/response.py      包成 {code,message,data}
```

AI 侧复用同一个 service：

```text
Agent 决定调用工具
  → services/agent_tools.py: create_lab_reservation()
  → reservation_service.create_reservation()   ← 同一个函数！
```

---

## 9. 面试高频问答

**Q1：为什么选 FastAPI 不用 Flask/Django？**
> 三个理由：① 原生 async，AI 调用的流式输出（`StreamingResponse`）和 LangGraph 的 `astream_events` 都需要真正的异步；② Pydantic 类型即校验，31 个接口省掉大量手写 if；③ 自动生成 OpenAPI 文档，前后端联调成本低。

**Q2：`Depends` 的原理是什么？**
> FastAPI 在启动时解析路由函数的签名，看到默认值是 `Depends(xxx)` 就记录依赖树；请求进来时按拓扑顺序先执行依赖（默认同一次请求内缓存结果），把返回值按参数名注入路由函数。`yield` 型依赖被当作异步上下文管理器，`yield` 后的代码在响应生成后执行。

**Q3：为什么业务错误返回 HTTP 200？**
> 业务分支（「该时段已预约」）是预期内的结果，不是服务器故障。统一 200 + body 里的 code，前端 axios 拦截器只需要一套判断逻辑。协议级错误（401/422/429）仍然走 HTTP 状态码，因为那是 HTTP 语义本身。

**Q4：拦截器/中间件和依赖注入有什么区别？**
> 中间件是全局的、按注册顺序对所有请求生效（如 CORS）；依赖注入是**按路由声明**的、粒度更细、可以拿到校验后的类型化对象。鉴权用依赖而不是中间件，是因为「哪些接口需要登录、哪些需要 admin」是逐接口配置的。

**Q5（陷阱题）：既然 FastAPI 是异步框架，为什么你大部分接口写成同步 `def`？**
> 因为我的 ORM 用的是同步 `Session`，在 `async def` 里调同步 DB 会阻塞事件循环，比同步路由更糟。同步路由会被 FastAPI 丢进线程池，不阻塞循环。只有真正需要 `await` 的 AI 流式接口（4 个）才用 `async def`。**是不是 async 要看里面有没有真异步调用，不是看框架。**

**Q6：启动预热为什么加超时？**
> embedding 模型首次运行要下载权重（几十 MB），网络差时会卡很久。用 `asyncio.wait_for(..., timeout=30)` 包住，保证服务一定能起来，最坏情况是首个 RAG 请求慢一点，而不是整个服务启动失败。

---

## 10. 速记卡

```text
FastAPI = Starlette(异步内核) + Pydantic(类型即校验) + ASGI(uvicorn)

分层：api(HTTP) → dependencies(鉴权/限流) → services(业务) → models(ORM)
      ↳ 反向 import 禁止；service 被 HTTP 和 AI 工具共用

依赖三形态：
  普通  → 返回值注入
  yield → 路由后清理（get_db 关会话）
  嵌套  → admin ← user ← db/oauth2

响应：{code, message, data}；业务错 HTTP 200 + code≠200
异常四级：Business(200) → HTTP(401/422/429) → Validation(422) → 兜底(500)

lifespan：启动建表/预热(30s超时,to_thread)/后台任务 → yield → 关闭 cancel+释放

sync vs async：同步 DB 用 def(线程池)，真 await 才用 async def
项目实测：31 接口 / 5 个 async def / 8 个子路由
```
