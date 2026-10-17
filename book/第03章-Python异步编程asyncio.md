# 第 03 章 · Python 异步编程 asyncio

## 开篇：为什么 Agent 代码全是 async

打开任何一个 Agent 项目的源码，你会看到：

```python
async def agent_node(state):
    response = await llm.ainvoke(...)

async def tool_node(state):
    result = await asyncio.wait_for(asyncio.to_thread(tool.invoke, args), timeout=30)

async def stream_agent(...):
    async for event in agent.astream_events(...):
        yield event
```

`async` / `await` 无处不在。很多人的反应是「跟着写就完了」——然后某天写出了这样的 bug：

> 服务上线后，同时来 10 个用户，第 1 个用户在等模型返回，后面 9 个全部卡死。
> 排查一天，发现是某个工具函数里用了 `requests.get()` 或者同步的数据库查询。

**异步不是语法糖，是一种不同的执行模型。** 不懂它，你会写出「看起来是异步、实际是同步」的代码，性能比纯同步还差（因为多了调度开销）。

这一章的目标：让你能回答三个问题：

1. **为什么** Agent 必须用异步？
2. **怎么写**才是真的异步？
3. **怎么识别**假的异步代码？

---

## 一、先建立直觉：咖啡店模型

理解异步最快的方式是类比。

### 模型 A：同步（一个服务员，死等）

```
服务员接了 1 号桌的点单 → 送到厨房 → 站在厨房门口等 → 菜好了 → 端给 1 号桌 → 接 2 号桌...
```

**问题**：服务员 90% 的时间在等厨房。10 桌客人，前 9 桌都在挨饿。

这就是**同步阻塞**：一个线程处理一个请求，遇到 IO（网络、磁盘、数据库）就干等。

### 模型 B：多线程（多个服务员）

```
10 个服务员，每人盯一桌。
```

**问题**：服务员很贵（线程开销大，一个线程默认占 8MB 栈空间）。1000 桌客人需要 1000 个服务员，内存爆了。而且服务员之间要协调（锁），容易打架。

### 模型 C：异步（一个服务员 + 叫号器）

```
服务员接 1 号桌点单 → 送到厨房 → 拿个叫号器 → 立刻去接 2 号桌
厨房好了 → 叫号器响 → 服务员回来端菜
```

**这就是异步**：一个线程，遇到 IO 不等待，而是**注册一个回调然后去做别的事**，IO 完成后再回来处理。

| | 同步 | 多线程 | 异步 |
|---|---|---|---|
| 并发数 | 1 | 受内存限制（几百~几千） | 几万 |
| IO 等待时 | 干等 | 其他线程能跑 | 切去干别的 |
| 开销 | 低 | 高（8MB/线程） | 极低（协程几 KB） |
| 编程难度 | 低 | 中（锁、竞态） | 中高（要全程 async） |
| 适合 | CPU 密集 | 一般 IO | 高并发 IO |

### 为什么 Agent 特别适合异步？

因为 **Agent 的绝大部分时间花在 IO 上**：

| 环节 | 耗时量级 | 是什么 IO |
|---|---|---|
| 调用大模型 | 1-30 秒 | 网络 |
| 工具查询数据库 | 1-100 ms | 网络/磁盘 |
| MCP 工具调用 | 10-500 ms | 进程间通信 |
| Embedding 计算 | 10-100 ms | CPU（但通常已异步化） |
| 向量检索 | 10-200 ms | 网络/磁盘 |

**一个 Agent 请求可能 95% 的时间在等网络**。同步写法的话，你的服务 QPS 就是 `1 / 平均响应时间` = 约 0.1。异步的话能达到几十甚至上百。

> 💡 **一句话记住**：异步解决的是「等待时的浪费」，不是「算得更快」。CPU 密集任务用异步没用（要用多进程）。

---

## 二、asyncio 的四个核心概念

### 2.1 协程（Coroutine）：可以被挂起的函数

```python
async def fetch_data():
    print("开始请求")
    await asyncio.sleep(1)     # ← 这里会让出控制权
    print("请求完成")
    return {"data": 123}

# 直接调用不会执行！只是创建了一个协程对象
coro = fetch_data()
print(type(coro))   # <class 'coroutine'>

# 必须用 await 或交给事件循环才会执行
result = asyncio.run(fetch_data())
```

**关键点**：`async def` 定义的函数，调用它**不会执行函数体**，只会创建一个协程对象。这是新手最大的困惑之一。

### 2.2 事件循环（Event Loop）：调度器

```python
asyncio.run(main())   # 创建事件循环 → 跑 main → 关闭循环
```

事件循环是那个「服务员」，它维护一个任务队列，某个任务 `await` 时切到下一个。

**在 FastAPI 里你不需要自己创建** —— Uvicorn 已经帮你建好了，你只管写 `async def`。

### 2.3 `await`：让出控制权的信号

```python
await some_coroutine()
```

`await` 的语义是：**「我要等这个东西，在等的时候，事件循环你可以去干别的」**。

**关键认知**：`await` 只在遇到**真正会让出的操作**时才有用。

```python
async def bad():
    time.sleep(5)        # ❌ 假异步！time.sleep 是阻塞的，不会让出
    return 1

async def good():
    await asyncio.sleep(5)   # ✅ 真异步，会让出
    return 1
```

### 2.4 Task：并发执行的载体

```python
# 串行：总共 3 秒
async def serial():
    await asyncio.sleep(1)
    await asyncio.sleep(1)
    await asyncio.sleep(1)

# 并发：总共 1 秒
async def parallel():
    await asyncio.gather(
        asyncio.sleep(1),
        asyncio.sleep(1),
        asyncio.sleep(1),
    )
```

**`gather` 是异步的核心武器**：把多个协程包装成 Task，一起调度。

---

## 三、最小可运行骨架：看懂串行与并发的差别

```python
"""
asyncio_demo.py —— 理解异步的核心：串行 vs 并发 vs 假异步
运行：python asyncio_demo.py
观察：三种写法耗时分别是 3s / 1s / 3s
"""
import asyncio
import time

# ── 1. 基础：串行 vs 并发 ────────────────────────────────

async def work(name: str, seconds: float) -> str:
    """模拟一次 IO 等待（比如调用大模型）。"""
    print(f"  [{time.strftime('%H:%M:%S')}] {name} 开始")
    await asyncio.sleep(seconds)          # 让出控制权
    print(f"  [{time.strftime('%H:%M:%S')}] {name} 完成")
    return f"{name}结果"

async def demo_serial():
    print("【串行】三个任务依次执行：")
    t0 = time.perf_counter()
    r1 = await work("A", 1)
    r2 = await work("B", 1)
    r3 = await work("C", 1)
    print(f"  耗时 {time.perf_counter()-t0:.2f}s，结果 {[r1,r2,r3]}\n")

async def demo_parallel():
    print("【并发】三个任务同时执行：")
    t0 = time.perf_counter()
    results = await asyncio.gather(work("A", 1), work("B", 1), work("C", 1))
    print(f"  耗时 {time.perf_counter()-t0:.2f}s，结果 {results}\n")

# ── 2. 假异步：最常见的坑 ────────────────────────────────

async def fake_async_work(name: str, seconds: float) -> str:
    """❌ 错误示范：在 async 函数里调用阻塞的 time.sleep。"""
    time.sleep(seconds)      # 阻塞整个事件循环！
    return f"{name}结果"

async def demo_fake_async():
    print("【假异步】用了 gather 但内部是阻塞的：")
    t0 = time.perf_counter()
    results = await asyncio.gather(
        fake_async_work("A", 1),
        fake_async_work("B", 1),
        fake_async_work("C", 1),
    )
    print(f"  耗时 {time.perf_counter()-t0:.2f}s  ← 注意！还是 3 秒")
    print("  原因：time.sleep 阻塞了事件循环，gather 根本没用\n")

# ── 3. 正确处理阻塞代码：to_thread ───────────────────────

def blocking_work(name: str, seconds: float) -> str:
    """一个无法改成 async 的第三方同步函数（比如 SQLAlchemy 同步 Session）。"""
    time.sleep(seconds)
    return f"{name}结果"

async def demo_to_thread():
    print("【to_thread】把阻塞函数丢到线程池：")
    t0 = time.perf_counter()
    results = await asyncio.gather(
        asyncio.to_thread(blocking_work, "A", 1),
        asyncio.to_thread(blocking_work, "B", 1),
        asyncio.to_thread(blocking_work, "C", 1),
    )
    print(f"  耗时 {time.perf_counter()-t0:.2f}s，结果 {results}")
    print("  这才是「同步库 + 异步框架」的正确用法\n")

# ── 4. 超时控制：wait_for ────────────────────────────────

async def demo_timeout():
    print("【wait_for】超时保护：")
    try:
        await asyncio.wait_for(work("慢任务", 10), timeout=2)
    except asyncio.TimeoutError:
        print("  ✅ 2 秒后超时，任务被取消\n")

    # wait_for 会真的取消任务吗？看这个
    task = asyncio.create_task(work("后台", 10))
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=1)
    except asyncio.TimeoutError:
        print("  shield 后超时了，但后台任务还在跑")

# ── 5. 流式：async generator ─────────────────────────────

async def token_stream(text: str):
    """模拟大模型逐 token 输出。"""
    for ch in text:
        await asyncio.sleep(0.05)     # 模拟生成延迟
        yield ch

async def demo_stream():
    print("【async generator】流式输出：")
    async for ch in token_stream("你好，我是助手"):
        print(ch, end="", flush=True)
    print("\n")

# ── 主函数 ───────────────────────────────────────────────

async def main():
    await demo_serial()
    await demo_parallel()
    await demo_fake_async()
    await demo_to_thread()
    await demo_timeout()
    await demo_stream()

if __name__ == "__main__":
    asyncio.run(main())
```

**预期输出**：

```
【串行】三个任务依次执行：
  [10:00:00] A 开始
  [10:00:01] A 完成
  [10:00:01] B 开始
  [10:00:01] B 完成
  [10:00:01] C 开始
  [10:00:02] C 完成
  耗时 3.00s，结果 ['A结果', 'B结果', 'C结果']

【并发】三个任务同时执行：
  [10:00:02] A 开始
  [10:00:02] B 开始
  [10:00:02] C 开始
  [10:00:03] A 完成
  [10:00:03] B 完成
  [10:00:03] C 完成
  耗时 1.00s，结果 ['A结果', 'B结果', 'C结果']

【假异步】用了 gather 但内部是阻塞的：
  耗时 3.00s  ← 注意！还是 3 秒
  原因：time.sleep 阻塞了事件循环，gather 根本没用

【to_thread】把阻塞函数丢到线程池：
  耗时 1.00s，结果 ['A结果', 'B结果', 'C结果']
  这才是「同步库 + 异步框架」的正确用法
```

**这个 demo 的三个结论**（面试必背）：

1. `async def` 不等于异步。**内部调用必须是非阻塞的**。
2. 遇到改不了的同步库（SQLAlchemy、requests、boto3），用 `asyncio.to_thread`。
3. `gather` 才带来并发，`await` 本身只是等待。

---

## 四、FastAPI 里的同步 vs 异步路由

这是最容易写错的地方，也是面试高频。

### 4.1 FastAPI 怎么处理这两种路由

```python
@app.get("/sync")
def sync_route():        # ← 普通 def
    time.sleep(1)
    return {"ok": True}

@app.get("/async")
async def async_route(): # ← async def
    await asyncio.sleep(1)
    return {"ok": True}
```

| | `def` 路由 | `async def` 路由 |
|---|---|---|
| 执行位置 | **线程池** | **事件循环** |
| 阻塞时 | 阻塞一个线程（不影响其他请求） | **阻塞整个事件循环**（所有请求卡死） |
| 适合 | 内部有同步 IO | 内部全异步 |

**关键结论**：

> 如果你的路由函数内部**有同步阻塞调用**（比如 SQLAlchemy 同步 Session、requests），**就应该用 `def` 而不是 `async def`**。
>
> 用 `async def` 但内部是同步代码 = 灾难。

### 4.2 这个项目的真实情况

项目里 31 个接口中，**只有 5 个是 `async def`**。哪 5 个？正是 Agent 相关的：

| 接口 | 为什么必须 async |
|---|---|
| `POST /api/ai/chat/stream` | 要 `async for` 消费 `astream_events` |
| `POST /api/ai/chat` | 要 `await agent.ainvoke()` |
| `POST /api/ai/chat/resume` | 同上 |
| 另外 2 个 | 同样是异步链路 |

而其他 26 个接口（用户、实验室、预约的 CRUD）内部用的是**同步 SQLAlchemy Session**，所以用 `def`，由 FastAPI 丢到线程池执行。

> ⚠️ **诚实口径**：这也就是为什么简历上不能写「全异步」。真实情况是「**IO 密集的 Agent 链路用 async，同步 DB 操作的 CRUD 用 sync 交给线程池**」——这个说法反而更专业，因为它体现了你知道取舍。

### 4.3 一个真实的错误示范

```python
# ❌ 错误：async 路由里调用同步 DB
@router.get("/labs")
async def list_labs(db: Session = Depends(get_db)):
    rows = db.query(Lab).all()      # 同步阻塞！阻塞事件循环
    return rows
```

**后果**：这个接口被并发调用时，所有其他请求（包括 Agent 流式）全部卡住。

**两种正确写法**：

```python
# ✅ 写法一：改成 def，让 FastAPI 用线程池（简单）
@router.get("/labs")
def list_labs(db: Session = Depends(get_db)):
    rows = db.query(Lab).all()
    return rows

# ✅ 写法二：保持 async，用 to_thread 包住阻塞调用
@router.get("/labs")
async def list_labs(db: Session = Depends(get_db)):
    rows = await asyncio.to_thread(lambda: db.query(Lab).all())
    return rows
```

**选哪个？** 写法一更简单，推荐。写法二只在「这个路由里既有异步又有同步」时才用。

---

## 五、Agent 场景的四个异步模式

### 模式 1：`to_thread` 跑同步工具（项目里在用）

**代码位置**：`agent_service.py` 的 `_invoke_tool_with_retry`

```python
result = await asyncio.wait_for(
    asyncio.to_thread(tool.invoke, args),   # 同步工具丢线程池
    timeout=settings.TOOL_TIMEOUT_SECONDS,  # 30 秒超时
)
```

**为什么工具是同步的？**

因为工具内部用的是同步 SQLAlchemy Session（项目的 ORM 是同步的）。要改成异步得整个数据访问层换 `AsyncSession`，改动太大。

**`to_thread` + `wait_for` 的组合解决了两件事**：

- `to_thread`：不阻塞事件循环 ✅
- `wait_for`：防止工具卡死导致请求永远挂着 ✅

> 💡 **面试话术**：「我的工具是同步的（用同步 SQLAlchemy），但 Agent 链路是异步的。我的做法是用 `asyncio.to_thread` 把工具执行丢到线程池，再用 `asyncio.wait_for` 加超时。这样既不阻塞事件循环，又能防止单个慢工具拖死整个请求。将来如果要更高性能，可以把数据层换成 `AsyncSession`，但现在的瓶颈在模型调用（几秒），不在这几十毫秒的数据库查询，所以优化的优先级不高。」
>
> 这段话体现了：**你知道问题在哪、知道怎么解、也知道现在不用解的优先级判断**。

### 模式 2：`async for` 消费流式

```python
async for event in agent.astream_events(inputs, version="v2", config=...):
    yield {"type": "token", "content": text}
```

**异步生成器**（`async generator`）是流式的核心。FastAPI 的 `StreamingResponse` 接受一个异步生成器，边生成边推给客户端。

### 模式 3：`asyncio.Lock` 防竞态（MCP 工具加载）

**代码位置**：`agent_tools.py` 的 `_load_mcp_tools`

```python
_mcp_lock = asyncio.Lock()
_mcp_cache = None

async def _load_mcp_tools():
    global _mcp_cache
    async with _mcp_lock:          # ← 只让一个协程加载
        if _mcp_cache is None:
            _mcp_cache = await _really_load()   # 慢操作，只做一次
    return _mcp_cache
```

**为什么需要锁？**

如果不用锁，100 个并发请求会同时触发 100 次 MCP 工具加载（每次都是跨进程通信，很慢），而且可能产生重复注册。

**为什么用 `asyncio.Lock` 而不是 `threading.Lock`？**

因为 `threading.Lock` 在协程里用会**阻塞整个事件循环**（它不会让出控制权）。`asyncio.Lock` 的 `acquire` 是可 await 的，拿不到锁会让出。

> ⚠️ **真实缺陷**：这个锁是后来补的。原版本没有锁，并发时会重复加载 MCP 工具。这是代码审查发现的 C3 缺陷之一。（第 30 章详解）

### 模式 4：`create_task` 做后台任务

```python
@app.post("/upload")
async def upload(file: UploadFile, bg: BackgroundTasks):
    bg.add_task(process_document_async, file.filename)   # 返回后继续跑
    return {"message": "已接收，正在处理"}
```

适合「文档入库」这类耗时操作：先告诉用户「收到了」，后台慢慢切块、embedding、入库。

---

## 六、异步的五个经典陷阱

### 陷阱 1：在 async 函数里用 `requests`

```python
# ❌ requests 是同步的
async def call_api():
    return requests.get("https://api.example.com").json()

# ✅ 用 httpx 的 AsyncClient，或 to_thread
async def call_api():
    async with httpx.AsyncClient() as client:
        return (await client.get("https://api.example.com")).json()
```

**怎么自查**：在 async 函数里搜索 `requests.`、 `time.sleep(`、 `db.query(`、文件读写。

### 陷阱 2：忘记 `await`

```python
async def main():
    work()          # ❌ 什么都没发生，还警告 "coroutine was never awaited"
    asyncio.create_task(work())   # ✅ 至少会执行（但不等结果）
    await work()    # ✅
```

**这是最隐蔽的 bug**：代码不报错，但功能没执行。

### 陷阱 3：事件循环嵌套

```python
# ❌ 在已经跑着事件循环的地方再调 asyncio.run
async def handler():
    asyncio.run(something())   # RuntimeError: asyncio.run() cannot be called from a running event loop
```

**典型场景**：在 Jupyter Notebook 或 FastAPI 路由里调 `asyncio.run`。

**怎么解**：直接 `await`，或者用 `nest_asyncio`（不推荐，是 hack）。

### 陷阱 4：Task 被垃圾回收

```python
async def main():
    asyncio.create_task(background_work())   # ⚠️ 如果 main 很快结束，task 可能被取消
    return

# ✅ 保存引用
async def main():
    task = asyncio.create_task(background_work())
    ...
    await task   # 或者至少保存引用防止被 GC
```

### 陷阱 5：CPU 密集任务阻塞事件循环

```python
async def embed_texts(texts):
    # ❌ 计算 embedding 是 CPU 密集，会卡住事件循环
    return model.encode(texts)

# ✅ 丢到进程池（注意是进程不是线程，因为 GIL）
async def embed_texts(texts):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        ProcessPoolExecutor(), model.encode, texts
    )
```

**关键**：CPU 密集要用**进程池**，`to_thread` 没用（GIL 限制）。

---

## 七、项目代码定位

### 7.1 异步工具调用：`agent_service.py`

```python
async def _invoke_tool_with_retry(tool, args: dict) -> str:
    """带超时与重试的工具调用。"""
    last_error = None
    for attempt in range(settings.TOOL_MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(tool.invoke, args),        # ← 模式1
                timeout=settings.TOOL_TIMEOUT_SECONDS,
            )
            return result.content if hasattr(result, "content") else str(result)
        except Exception as exc:
            last_error = exc
            if attempt < settings.TOOL_MAX_RETRIES:
                await asyncio.sleep(0.2 * (attempt + 1))     # 指数退避
    return json.dumps({"ok": False, "error": str(last_error)}, ensure_ascii=False)
```

| 行 | 异步手法 | 作用 |
|---|---|---|
| `asyncio.to_thread` | 同步转异步 | 不阻塞事件循环 |
| `asyncio.wait_for` | 超时 | 防工具卡死 |
| `await asyncio.sleep` | 异步等待 | 退避时不阻塞 |

> ⚠️ **注意**：`0.2 * (attempt + 1)` 这个退避其实很短（0.2 秒、0.4 秒）。对网络抖动够用，但对「服务重启」这种场景不够。生产上应该用更长退避 + 抖动（jitter）避免惊群。（第 20 章详解）

### 7.2 MCP 异步加载：`agent_tools.py`

```python
_mcp_lock = asyncio.Lock()      # 模块级锁

async def _load_mcp_tools() -> list:
    global _mcp_cache
    if not settings.MCP_ENABLED:
        return []
    async with _mcp_lock:                    # ← 防止并发重复加载
        if _mcp_cache is not None:
            return _mcp_cache
        try:
            client = MultiServerMCPClient({...})
            tools = await client.get_tools()   # ← 跨进程通信，慢
            _mcp_cache = tools
        except Exception:
            logger.exception("MCP 工具加载失败")
            _mcp_cache = []
    return _mcp_cache
```

**双重检查锁定模式**（double-checked locking）：

```python
if _mcp_cache is not None:      # 第一次检查（快路径，无锁）
    return _mcp_cache
async with _mcp_lock:
    if _mcp_cache is not None:  # 第二次检查（拿到锁后再确认）
        return _mcp_cache
    _mcp_cache = await load()   # 真正加载
```

**为什么要检查两次？**

第一次避免每次都抢锁（性能）。第二次是因为：可能多个线程同时通过第一次检查，然后排队等锁，第一个加载完释放锁后，第二个如果不重新检查就会重复加载。

### 7.3 流式生成器：`agent_service.py:440`

```python
async def _stream_events(agent, inputs, thread_id):
    yield {"type": "status", "message": "正在思考…"}      # ← async generator
    try:
        async for event in agent.astream_events(...):      # ← 异步迭代
            ...
            yield {"type": "token", "content": text}
        yield {"type": "done"}
    except BusinessException as exc:
        yield {"type": "error", "message": exc.message}    # ← 错误也走流
    except Exception:
        logger.exception("Agent 流式执行失败")
        yield {"type": "error", "message": "大模型调用失败，请稍后重试"}
```

**关键设计：错误也通过流返回，而不是让连接断开。**

`StreamingResponse` 已经开始推数据了，响应头已经发出，这时候抛异常客户端会收到一个截断的流。正确做法是把错误作为事件推给前端。

### 7.4 路由层的 async 用法：`api/ai.py`

```python
@router.post("/chat/stream")
async def chat_stream(...):
    return StreamingResponse(
        _event_generator(db, current_user, data, thread_id),   # async generator
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
```

---

## 八、怎么判断一段异步代码是不是真的异步

给你一个自查清单，面试前扫一遍自己的项目：

| 检查项 | 危险信号 | 怎么改 |
|---|---|---|
| `requests` / `urllib` | 在 `async def` 里 | 换 `httpx.AsyncClient` |
| `time.sleep` | 在 `async def` 里 | 换 `await asyncio.sleep` |
| `db.query()` / `session.execute()` | 同步 Session 在 `async def` 里 | 换 `AsyncSession` 或 `to_thread` |
| `open()` / 文件读写 | 在 `async def` 里 | 用 `aiofiles` 或 `to_thread` |
| `model.encode()` 等计算 | 在 `async def` 里 | `run_in_executor(ProcessPoolExecutor())` |
| `threading.Lock` | 在协程里 | 换 `asyncio.Lock` |
| 没有 `await` 的协程调用 | 任何地方 | 补 `await` |

**一个实操技巧**：在开发时开 asyncio 的 debug 模式，慢回调会告警：

```python
import asyncio, logging
logging.basicConfig(level=logging.DEBUG)
asyncio.run(main(), debug=True)
```

或者用第三方库 `asyncio-debug` / `blockbuster` 自动检测阻塞调用。

---

## 本章速记卡

1. **异步解决的是「等待时的浪费」**，不是算得更快。CPU 密集要用多进程。
2. **`async def` ≠ 异步**。内部调用必须非阻塞，否则比同步更糟。
3. **`gather` 带来并发**，`await` 只是等待。
4. **同步库 + 异步框架 → `asyncio.to_thread`**。
5. **FastAPI 的 `def` 路由走线程池，`async def` 走事件循环**。内部有同步 IO 就用 `def`。
6. **`wait_for` 加超时**，`to_thread` 防阻塞，两者常组合使用。
7. **协程里用 `asyncio.Lock`**，不能用 `threading.Lock`。
8. **CPU 密集用进程池**，`to_thread` 受 GIL 限制没用。
9. **流式用 async generator**，错误也要作为事件推给前端。
10. **本项目**：31 个接口只有 5 个 async——Agent 链路 async，CRUD 用 def 走线程池。

---

## 面试问答：异步编程

### Q1：「为什么 Agent 开发几乎都用异步？」

**满分答法**：

> 因为 Agent 的时间几乎全花在 IO 等待上。一次对话要调模型（几秒）、可能调多次工具（每次几十毫秒）、还要流式推送。同步写法的话，单个请求的响应时间就是所有 IO 的累加，服务的 QPS 直接被压到 0.1 这个量级。
>
> 异步的价值是：在等模型返回的时候，这个线程（其实是事件循环）可以去处理其他用户的请求。同样的机器，并发能力从个位数提升到几百。
>
> 具体到我的项目：Agent 的三个接口用了 `async def`，因为要 `await` 模型的异步调用和 `async for` 消费流式事件；而 26 个 CRUD 接口用的是同步 SQLAlchemy，我就用普通的 `def`，让 FastAPI 把它们丢到线程池——这样它们阻塞时不影响事件循环。

---

### Q2：「`async def` 和 `def` 在 FastAPI 里有什么区别？你怎么选？」

**满分答法**：

> FastAPI 对两者处理方式不同：`async def` 的路由直接在事件循环里执行；`def` 的路由会被丢到线程池执行。
>
> 所以选择标准很明确：**如果函数内部全是异步调用（await 模型、await 异步 DB），用 `async def`；如果内部有同步阻塞调用（同步 ORM、requests），用 `def`**。
>
> 最危险的组合是 `async def` 里面写同步代码——它会阻塞整个事件循环，所有请求全部卡死，而 `def` 里写同步代码最多占一个线程。
>
> 我项目里 31 个接口，只有 5 个是 `async def`，正是 Agent 那几个。这个数字我是实测过的，简历上我也不写「全异步」，因为不属实。

---

### Q3：「你的工具是同步的，Agent 是异步的，你怎么处理？」

**满分答法**：

> 用 `asyncio.to_thread` 把工具执行丢到线程池，再用 `asyncio.wait_for` 包一层加超时。
>
> 为什么要 to_thread：工具内部用的是同步 SQLAlchemy Session，直接在 async 函数里调用会阻塞事件循环，导致所有请求卡住。
>
> 为什么要 wait_for：工具可能因为慢查询、网络抖动卡住，没有超时的话这个请求会永远挂着，占着连接资源。我设的是 30 秒。
>
> 超时后不是抛异常中断，而是把错误 JSON 回填给模型，让模型知道「这个工具失败了」并尝试其他路径。这是 Agent 和传统后端的区别——失败要能被模型感知和自纠。

---

### Q4：「`asyncio.gather` 和 `await` 逐个调用有什么区别？什么时候用 gather？」

**满分答法**：

> `await` 逐个调用是串行的：等第一个完成才发起第二个。三个各耗时 1 秒的任务，总共 3 秒。
>
> `gather` 会把协程包装成 Task 并发调度：三个 1 秒的任务总共还是 1 秒。
>
> 什么时候用 gather：**多个独立的 IO 操作**。比如 Agent 一次要调 3 个互不依赖的工具，就应该 gather 并行。
>
> 什么时候不能：有依赖关系时。比如先查实验室 ID、再用 ID 查设备，第二步依赖第一步的结果，没法并行。
>
> 另外要注意 `gather` 的错误处理：默认 `return_exceptions=False`，一个任务抛异常会立刻中断（但其他任务不会被取消，可能造成泄漏）。我一般用 `return_exceptions=True`，然后逐个检查哪些失败了。
>
> 补充一点：我项目里 `tool_node` 现在是串行 for 循环，如果模型一次要调多个独立工具，改成 gather 能明显降低延迟。这是个可以优化的点，我没做是因为大部分场景模型一次只调一个工具。

---

### Q5：「异步代码怎么调试和测试？」

**满分答法**：

> 调试三个手段：
>
> 一是开 `asyncio.run(main(), debug=True)`，慢回调（超过 100ms 的同步阻塞）会打警告，能定位到「哪里阻塞了事件循环」。
>
> 二是看日志的时间戳。如果所有请求的日志都是严格串行、没有交错，说明异步没生效。
>
> 三是压测对比。用 locust 或者简单的并发脚本，看 QPS 是不是随并发数线性增长。如果并发 10 和并发 1 的总耗时一样，说明是串行。
>
> 测试方面，FastAPI 用 `httpx.AsyncClient` 配合 `TestClient` 测异步接口；纯函数用 `pytest-asyncio` 的 `@pytest.mark.asyncio`。
>
> 我项目里 Agent 的测试还有个特殊点：**注入假 LLM**。真模型响应慢且不确定，测试会又慢又不稳定。我写一个 FakeLLM 返回预设的 tool_calls，整个执行路径就确定了，测试能在毫秒级跑完并且可重复。

---

### Q6：「asyncio 的 GIL 问题你怎么理解？」

**满分答法**（这题考深度）：

> GIL 保证同一时刻只有一个线程执行 Python 字节码。所以**多线程不能并行执行 CPU 密集任务**——这是很多人对 `to_thread` 的误解。
>
> 但 `to_thread` 对我的场景仍然有效，因为我的工具是 **IO 密集**（数据库查询）。IO 操作时线程会释放 GIL（比如等待网络、磁盘），所以多线程在 IO 密集场景确实能并发。
>
> 真正的 CPU 密集任务，比如批量计算 embedding、rerank 模型推理，要用**进程池** `ProcessPoolExecutor`，因为每个进程有独立的 GIL。
>
> 在我的项目里，embedding 计算是用 sentence-transformers，它在内部已经做了批处理优化，而且我在服务启动时预热了模型。如果真遇到 CPU 瓶颈，应该把 embedding 拆成独立服务，而不是在主进程里跑。

---

## 常见坑

### 坑 1：`async def` 里调同步 ORM，服务并发能力归零

最隐蔽的异步 bug。自查方法：搜索 async 函数里的 `db.query`、`requests`、`time.sleep`。

### 坑 2：MCP 工具加载没加锁，并发时重复加载

`asyncio.Lock` + 双重检查锁定解决。

### 坑 3：忘记 `await`，代码静默失效

Python 只给一个 `RuntimeWarning`，很容易被日志淹没。建议把警告升级为错误。

### 坑 4：`wait_for` 取消了任务但资源没释放

超时后数据库连接、HTTP 连接可能没关。要确保工具有清理逻辑。

### 坑 5：`to_thread` 默认线程池太小

默认是 `min(32, cpu_count + 4)`。如果大量请求都在跑同步工具，会排队。可以调：

```python
loop.set_default_executor(ThreadPoolExecutor(max_workers=100))
```

### 坑 6：把 CPU 密集任务用 `to_thread`

没用，GIL 限制。要用进程池。

---

## 动手练习

### 练习 1（必做）

跑通第三节的 `asyncio_demo.py`，确认三种写法的耗时（3s / 1s / 3s / 1s）。

然后修改 `demo_parallel`，把 `gather` 改成逐个 `await`，看耗时变化。

### 练习 2

写一个小实验：创建 10 个并发任务，每个 `await asyncio.sleep(1)`。
- 用 `asyncio.gather` → 应该约 1 秒
- 用 for 循环逐个 `await` → 应该约 10 秒

验证你对并发的理解。

### 练习 3（进阶）

打开 `backend/app/api/` 下的任意三个接口文件，判断它们用 `def` 还是 `async def` 是否正确：

- 如果内部有 `db.query()`，应该是 `def`
- 如果内部有 `await`，必须是 `async def`

找出有没有「`async def` 但内部是同步 DB」的错误写法。

### 练习 4

给 `_invoke_tool_with_retry` 加一个测试：让工具抛异常，验证：

1. 重试了几次？
2. 最终返回的是什么格式？
3. 超时是否生效？（用一个 sleep 60 的工具测）

---

## 下一章

**第 04 章 · 大模型是怎么"思考"的**

你现在知道 Agent 代码为什么是异步的了。但还有一个更根本的问题：**模型到底是怎么决定「该调哪个工具」的？**

很多人把模型当黑盒，只知道「输入 prompt 输出回答」。但要做 Agent，你必须理解：模型看到的是什么格式、它是怎么「选择」的、为什么有时候不调工具、为什么参数会编错。

下一章不讲数学推导，讲**工程直觉**：从 token 到 attention 到 tool_calls 的生成过程。
