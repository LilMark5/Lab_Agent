# 03 · FastAPI 企业级进阶

## 1. FastAPI 为什么适合 AI 后端？

- 原生异步，适合调用大模型这种 I/O 密集场景。
- 自动生成 Swagger 文档，联调方便。
- 依赖注入体系清晰，鉴权、数据库会话都能复用。
- Pydantic 做数据校验，和 AI 工具的参数 Schema 天然契合。

## 2. 请求生命周期

FastAPI 收到请求后的处理顺序：

```text
中间件(Middleware)
  -> 路由匹配
  -> 依赖注入(Depends)
  -> 参数校验(Pydantic)
  -> 路由处理函数
  -> 响应
  -> 依赖清理(yield 的 finally)
```

本项目 `get_db` 用 `yield` 就是依赖清理：

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

每个请求独立拿一个 Session，结束一定关闭，避免连接泄漏。

## 3. 分层：API / Service / Model

如果所有代码写在路由函数里，项目一大就无法维护。

正确做法：

```text
API 层：接收参数、声明鉴权、调用 service
Service 层：事务、业务规则、异常
Model 层：数据库对象
Schema 层：接口数据契约
```

例如创建预约：

```python
@router.post("")
def create_reservation(
    data: ReservationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation_service.create_reservation(db, current_user, data)
    return Response.success(message="预约已提交，请等待审核")
```

路由很薄，真正判断“实验室是否开放、时段是否冲突”的代码在 service。
这样 LangGraph 的 `create_lab_reservation` 工具才能复用同一套业务逻辑。

## 4. 依赖注入：鉴权复用

`get_current_user` 从请求头解析 JWT，返回 User 对象：

```python
current_user: User = Depends(get_current_user)
```

管理员鉴权是在普通用户鉴权之上再包一层：

```python
def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise BusinessException(message="无权限访问", code=403)
    return current_user
```

这是“组合依赖”，是企业级 FastAPI 很常用的模式。

## 5. 统一响应

所有接口返回：

```json
{"code": 200, "message": "请求成功", "data": {}}
```

好处：

- 前端只写一个拦截器。
- 业务错误用 `code` 表达，HTTP 状态仍为 200，方便前端统一处理。
- 401 这种认证错误仍用 HTTP 401，浏览器和拦截器能区分。

## 6. 统一异常处理

异常分四层：

1. `BusinessException`：可预期业务错误，如“账号已存在”。
2. `HTTPException`：框架级错误，如 401。
3. `RequestValidationError`：Pydantic 参数错误。
4. `Exception`：兜底，防止堆栈外泄。

注册顺序很重要，兜底必须最后注册。

## 7. 异步与阻塞

FastAPI 的 async 接口适合调用数据库异步驱动、HTTP 客户端等。
但 SQLAlchemy 同步 Sessiinn。本项目 AI 接口为了简单使用同步写法，
FastAPI 会把它丢到线程池执行，不影响事件循环。

启动时预热向量模型使用了：

```python
await asyncio.to_thread(kb_service.warmup)
```

这是把耗时同步任务交给线程池，避免阻塞启动流程。
## 8. 企业级要补的知识

### 8.1 配置管理

本项目用 pydantic-settings 读 `.env`。生产环境会区分 dev/staging/prod，
密钥统一放环境变量或配置中心。

### 8.2 日志

学习 `logging` 的结构化日志，给每个请求加 trace_id，方便追踪 AI 链路。

### 8.3 数据库迁移

本项目用 `create_all` 建表，只适合学习。生产环境要用 Alembic 做迁移，
否则改表结构会非常痛苦。

### 8.4 测试

用 pytest + httpx 写接口测试。测试时用独立数据库，`Depends` 可以覆盖依赖。

### 8.5 部署

生产环境通常 `uvicorn` 前面加 Nginx，用 systemd 或 Docker 管理进程，
还要考虑限流、CORS 白名单、HTTPS。

## 9. 检查清单

- 为什么路由函数要尽量薄？
- `yield` 在 `get_db` 里起什么作用？
- 统一异常处理为什么要最后注册 `Exception`？
- 管理员鉴权如何复用普通用户鉴权？
