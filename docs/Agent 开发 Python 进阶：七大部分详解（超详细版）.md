# Agent 开发 Python 进阶：七大部分详解（超详细版）

下面每一块都包含：

- **为什么学**
- **最小可运行骨架**（带注释）
- **运行结果**
- **详细解释**
- **Agent 开发中的实际用途**
- **常见坑**
- **练习**

------

# 第一部分：异步编程

## 1.1 为什么 Agent 开发必须用异步？

Agent 服务的特点是：**每个请求大部分时间都在等 I/O**。

- 等 LLM 返回：1~30 秒
- 等工具调用：几百毫秒到几秒
- 等向量检索：几十到几百毫秒
- 等数据库：几毫秒到几十毫秒

如果同步处理，一个用户对话时，服务器就卡在那里，其他用户全部排队。
异步让服务器在"等"的时候去处理别的请求。

## 1.2 同步 vs 异步对比

### 同步版本

python

```
import time

def call_llm(prompt: str) -> str:
    """模拟调用 LLM，耗时 2 秒"""
    time.sleep(2)
    return f"回答：{prompt}"

def main():
    start = time.time()
    # 串行调用 3 次
    r1 = call_llm("问题1")
    r2 = call_llm("问题2")
    r3 = call_llm("问题3")
    print(r1, r2, r3)
    print(f"总耗时：{time.time() - start:.2f} 秒")

main()
```



**运行结果：**

text

```
回答：问题1 回答：问题2 回答：问题3
总耗时：6.00 秒
```



三个问题串行等待，共 6 秒。

### 异步版本

python

```
import asyncio
import time

async def call_llm(prompt: str) -> str:
    """模拟异步调用 LLM，耗时 2 秒"""
    await asyncio.sleep(2)   # 非阻塞等待
    return f"回答：{prompt}"

async def main():
    start = time.time()
    # 并发调用 3 次
    results = await asyncio.gather(
        call_llm("问题1"),
        call_llm("问题2"),
        call_llm("问题3"),
    )
    print(results)
    print(f"总耗时：{time.time() - start:.2f} 秒")

asyncio.run(main())   # 顶层入口，运行协程
```



**运行结果：**

text

```
['回答：问题1', '回答：问题2', '回答：问题3']
总耗时：2.00 秒
```



三个问题并发等待，只要 2 秒。

### 关键差异

|          | 同步   | 异步       |
| :------- | :----- | :--------- |
| 总耗时   | 6 秒   | 2 秒       |
| 等待方式 | 阻塞   | 让出控制权 |
| 并发能力 | 单请求 | 多请求     |

## 1.3 async / await 的本质

python

```
import asyncio

async def fetch_data():
    print("1. 开始请求")
    await asyncio.sleep(1)   # 让出控制权，事件循环去跑别的
    print("2. 拿到数据")
    return "data"

async def other_task():
    print("A. 另一个任务开始")
    await asyncio.sleep(0.5)
    print("B. 另一个任务结束")

async def main():
    # 并发执行两个协程
    result = await asyncio.gather(
        fetch_data(),
        other_task(),
    )
    print("最终结果：", result)

asyncio.run(main())
```



**运行结果：**

text

```
1. 开始请求
A. 另一个任务开始
B. 另一个任务结束
2. 拿到数据
最终结果： ['data', None]
```



**解释：**

1. `fetch_data()` 开始，打印 "1. 开始请求"。
2. 遇到 `await asyncio.sleep(1)`，让出控制权。
3. 事件循环去跑 `other_task()`，打印 "A. 另一个任务开始"。
4. `other_task` 遇到 `await asyncio.sleep(0.5)`，让出控制权。
5. 0.5 秒后，`other_task` 先醒来，打印 "B. 另一个任务结束"。
6. 再等 0.5 秒，`fetch_data` 醒来，打印 "2. 拿到数据"。
7. `gather` 返回结果。

**核心理解：**

- `async def`：声明协程函数，调用它不立即执行，返回协程对象。
- `await`：让出控制权，事件循环去跑其他任务。
- 等待的是 I/O 时，事件循环可以复用这段时间。

## 1.4 如何运行协程？

python

```
import asyncio

async def hello():
    return "Hello"

# 方式1：asyncio.run（顶层入口）
result = asyncio.run(hello())
print(result)   # Hello

# 方式2：在另一个协程里 await
async def wrapper():
    r = await hello()
    print(r)

asyncio.run(wrapper())   # Hello

# 方式3：create_task 后台跑
async def main():
    task = asyncio.create_task(hello())
    result = await task
    print(result)

asyncio.run(main())   # Hello
```



**运行结果：**

text

```
Hello
Hello
Hello
```



## 1.5 asyncio.gather：并发跑多个任务

python

```
import asyncio
import time

async def fetch_user():
    await asyncio.sleep(1)
    return {"name": "张三"}

async def fetch_orders():
    await asyncio.sleep(2)
    return [{"id": 1}, {"id": 2}]

async def fetch_points():
    await asyncio.sleep(1.5)
    return 100

async def main():
    start = time.time()
    # 三个任务并发执行，总耗时 = 最慢的那个
    user, orders, points = await asyncio.gather(
        fetch_user(),
        fetch_orders(),
        fetch_points(),
    )
    print("user:", user)
    print("orders:", orders)
    print("points:", points)
    print(f"总耗时：{time.time() - start:.2f} 秒")

asyncio.run(main())
```



**运行结果：**

text

```
user: {'name': '张三'}
orders: [{'id': 1}, {'id': 2}]
points: 100
总耗时：2.00 秒
```



三个任务并发，总耗时等于最慢的 2 秒，而不是 1+2+1.5=4.5 秒。

### 带异常处理的 gather

python

```
import asyncio

async def ok_task():
    await asyncio.sleep(0.5)
    return "成功"

async def fail_task():
    await asyncio.sleep(0.3)
    raise ValueError("出错了")

async def main():
    # return_exceptions=True：出错不中断，把异常当结果返回
    results = await asyncio.gather(
        ok_task(),
        fail_task(),
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            print("捕获异常：", r)
        else:
            print("正常结果：", r)

asyncio.run(main())
```



**运行结果：**

text

```
捕获异常： 出错了
正常结果： 成功
```



## 1.6 asyncio.create_task：后台任务

python

```
import asyncio
import time

async def log_usage(user_id: str):
    """后台任务：记录用量，不阻塞主流程"""
    await asyncio.sleep(1)
    print(f"[后台] 记录 {user_id} 的用量")

async def handle_request():
    start = time.time()
    # 不等待，后台跑
    asyncio.create_task(log_usage("user1"))
    print(f"[主流程] 立即返回，耗时 {time.time() - start:.2f} 秒")
    return {"status": "ok"}

async def main():
    result = await handle_request()
    print("响应：", result)
    # 等待一会儿，让后台任务跑完（实际项目中不需要）
    await asyncio.sleep(1.5)

asyncio.run(main())
```



**运行结果：**

text

```
[主流程] 立即返回，耗时 0.00 秒
响应： {'status': 'ok'}
[后台] 记录 user1 的用量
```



**关键点：**

- `create_task` 立即返回，任务在后台跑。
- `gather` 会等所有任务完成。
- Agent 中用于：异步写日志、异步计费、异步上报。

## 1.7 异步迭代：async for

python

```
import asyncio

async def stream_tokens():
    """模拟 LLM 逐字输出"""
    tokens = ["你", "好", "，", "世", "界"]
    for token in tokens:
        await asyncio.sleep(0.3)   # 模拟生成延迟
        yield token   # 产出单个 token

async def main():
    async for token in stream_tokens():
        print(token, end="", flush=True)
    print()   # 换行

asyncio.run(main())
```



**运行结果：**

text

```
你好，世界
```



（每个字间隔 0.3 秒依次出现）

## 1.8 异步上下文管理器：async with

python

```
import asyncio

class AsyncDB:
    """模拟异步数据库连接"""
    async def __aenter__(self):
        print("1. 打开连接")
        await asyncio.sleep(0.2)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("3. 关闭连接")
        await asyncio.sleep(0.2)

    async def query(self):
        print("2. 执行查询")
        await asyncio.sleep(0.3)
        return [{"id": 1}]

async def main():
    async with AsyncDB() as db:
        result = await db.query()
        print("结果：", result)

asyncio.run(main())
```



**运行结果：**

text

```
1. 打开连接
2. 执行查询
结果： [{'id': 1}]
3. 关闭连接
```



## 1.9 什么时候用 async def，什么时候用 def？

| 场景                                      | 写法                  | 原因                       |
| :---------------------------------------- | :-------------------- | :------------------------- |
| 调用异步库（httpx、asyncpg、AsyncOpenAI） | `async def` + `await` | 异步库需要 await           |
| 调用同步库（requests、psycopg2）          | `def`                 | FastAPI 扔线程池，避免阻塞 |
| CPU 密集（图像处理、大量计算）            | `def` 或进程池        | 异步不会让 CPU 变快        |
| 纯逻辑、很快                              | 两者都行              | 无差别                     |

**黄金规则：**

> `async def` 里绝不能用同步阻塞代码。

## 1.10 常见坑

### 坑 1：async 里用同步库

python

```
import asyncio
import time
import requests

async def bad():
    time.sleep(1)          # ❌ 阻塞事件循环
    requests.get("...")    # ❌ 阻塞事件循环

async def good():
    await asyncio.sleep(1)   # ✅
    import httpx
    async with httpx.AsyncClient() as client:
        await client.get("...")   # ✅
```



### 坑 2：忘记 await

python

```
async def f():
    asyncio.sleep(1)   # ❌ 没有 await，协程不会执行
```



运行时会警告：

text

```
RuntimeWarning: coroutine 'sleep' was never awaited
```



### 坑 3：在同步函数里 await

python

```
def f():
    await something()   # ❌ SyntaxError
```



### 坑 4：以为异步会自动多线程

python

```
import asyncio
import time

async def cpu_heavy():
    # 这是在事件循环里跑，会卡住所有任务
    total = 0
    for i in range(10**7):
        total += i
    return total

async def main():
    start = time.time()
    await asyncio.gather(cpu_heavy(), cpu_heavy())
    print(f"耗时 {time.time() - start:.2f} 秒")   # 和串行一样

asyncio.run(main())
```



CPU 密集任务应该用 `def`，让 FastAPI 扔线程池，或用进程池。

## 1.11 练习

1. 写一个异步函数模拟调用 LLM，2 秒返回。
2. 并发调用 3 个，用 `gather`，看总耗时。
3. 写一个异步生成器，逐字输出一句话。
4. 用 FastAPI 写一个 `async def` 接口，返回这个生成器。
5. 用 `create_task` 实现"立即返回 + 后台写日志"。

------

# 第二部分：类型注解 + Pydantic

## 2.1 为什么重要？

FastAPI、LangGraph、Pydantic 都靠类型注解工作。没有类型注解：

- FastAPI 不知道参数类型、从哪读
- Pydantic 无法校验
- LangGraph 无法推断状态结构
- IDE 无法补全

## 2.2 基础类型注解

python

```
def greet(name: str, age: int) -> str:
    """类型注解：name 是 str，age 是 int，返回 str"""
    return f"{name} 今年 {age} 岁"

print(greet("张三", 30))
```



**运行结果：**

text

```
张三 今年 30 岁
```



类型注解**不会强制校验**，只是提示。下面代码也能跑：

python

```
print(greet(123, "abc"))   # 123 今年 abc 岁
```



但在 FastAPI / Pydantic 里，类型注解会**真正校验**。

## 2.3 容器类型

python

```
# Python 3.9+ 可以直接用内置类型
names: list[str] = ["a", "b"]
scores: dict[str, int] = {"math": 90}
pair: tuple[int, str] = (1, "a")
unique: set[int] = {1, 2, 3}

# 嵌套
matrix: list[list[int]] = [[1, 2], [3, 4]]
users: list[dict[str, str]] = [{"name": "张三"}]

print(names, scores, pair, unique, matrix)
```



**运行结果：**

text

```
['a', 'b'] {'math': 90} (1, 'a') {1, 2, 3} [[1, 2], [3, 4]]
```



## 2.4 Optional 和 Union

python

```
from typing import Optional

# 老写法
def find_user(user_id: int) -> Optional[str]:
    if user_id == 1:
        return "张三"
    return None

# 新写法（Python 3.10+，推荐）
def find_user2(user_id: int) -> str | None:
    if user_id == 1:
        return "张三"
    return None

# Union：多类型
def parse(value: int | str) -> str:
    return str(value)

print(find_user(1))     # 张三
print(find_user(2))     # None
print(parse(123))       # 123
print(parse("abc"))     # abc
```



**运行结果：**

text

```
张三
None
123
abc
```



`Optional[str]` 等价于 `str | None`。

## 2.5 Literal：限定取值

python

```
from typing import Literal

def set_mode(mode: Literal["fast", "slow", "balanced"]) -> str:
    return f"模式：{mode}"

print(set_mode("fast"))       # 模式：fast
# print(set_mode("ultra"))    # 类型检查器会报错，但运行时不会
```



**运行结果：**

text

```
模式：fast
```



在 Pydantic 里会**运行时校验**：

python

```
from pydantic import BaseModel
from typing import Literal

class Config(BaseModel):
    mode: Literal["fast", "slow"]

try:
    Config(mode="ultra")
except Exception as e:
    print("校验失败：", e)
```



**运行结果：**

text

```
校验失败： 1 validation error for Config
mode
  Input should be 'fast' or 'slow' ...
```



## 2.6 Annotated：给类型加元数据

python

```
from typing import Annotated

# 简单用法：附加说明
def get_items(q: Annotated[str, "查询关键词"]) -> list[str]:
    return [q]

print(get_items("test"))   # ['test']

# FastAPI 用法
from fastapi import FastAPI, Query

app = FastAPI()

@app.get("/items")
async def read_items(
    q: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
):
    return {"q": q}
```



**LangGraph 的核心用法：**

python

```
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class State(TypedDict):
    # Annotated[list, add_messages]：
    # 类型是 list，add_messages 是 reducer
    # 告诉 LangGraph 新消息"追加"到列表，而不是覆盖
    messages: Annotated[list, add_messages]
```



## 2.7 Pydantic BaseModel

### 基础定义

python

```
from pydantic import BaseModel, Field

class ToolArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=200, description="查询关键词")
    top_k: int = Field(5, ge=1, le=20, description="返回结果数量")
    include_metadata: bool = False

# 正常使用
args = ToolArgs(query="Python 异步", top_k=3)
print(args.query)
print(args.top_k)
print(args.include_metadata)
print(args.model_dump())
```



**运行结果：**

text

```
Python 异步
3
False
{'query': 'Python 异步', 'top_k': 3, 'include_metadata': False}
```



### 校验失败

python

```
from pydantic import ValidationError

try:
    ToolArgs(query="", top_k=100)
except ValidationError as e:
    print(e)
```



**运行结果：**

text

```
2 validation errors for ToolArgs
query
  String should have at least 1 character [type=string_too_short, ...]
top_k
  Input should be less than or equal to 20 [type=less_than_equal, ...]
```



### 嵌套模型

python

```
from pydantic import BaseModel

class Message(BaseModel):
    role: str
    content: str

class Conversation(BaseModel):
    session_id: str
    messages: list[Message]

conv = Conversation(
    session_id="s1",
    messages=[
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！"},
    ],
)

print(conv.session_id)
print(conv.messages[0].role)
print(conv.messages[0].content)
print(conv.model_dump())
```



**运行结果：**

text

```
s1
user
你好
{'session_id': 's1', 'messages': [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '你好！'}]}
```



### 常用 Field 参数

| 参数                        | 作用       | 示例                             |
| :-------------------------- | :--------- | :------------------------------- |
| `...`                       | 必填       | `name: str = Field(...)`         |
| `default`                   | 默认值     | `top_k: int = Field(5)`          |
| `min_length` / `max_length` | 字符串长度 | `Field(..., min_length=1)`       |
| `ge` / `gt` / `le` / `lt`   | 数值范围   | `Field(5, ge=1, le=20)`          |
| `pattern`                   | 正则       | `Field(..., pattern=r"^\d+$")`   |
| `description`               | 文档描述   | `Field(..., description="查询")` |

### 自定义校验器（v2）

python

```
from pydantic import BaseModel, field_validator, model_validator

class User(BaseModel):
    name: str
    age: int

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name 不能为空")
        return v.strip()

    @model_validator(mode="after")
    def check_age(self):
        if self.age < 0:
            raise ValueError("age 不能为负")
        return self

print(User(name=" 张三 ", age=30))
```



**运行结果：**

text

```
name='张三' age=30
```



试试非法输入：

python

```
try:
    User(name="   ", age=30)
except Exception as e:
    print(e)
```



**运行结果：**

text

```
1 validation error for User
name
  Value error, name 不能为空 ...
```



## 2.8 TypedDict：LangGraph 状态专用

python

```
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    next_action: str
    tool_result: dict | None

# 使用
state: AgentState = {
    "messages": [],
    "next_action": "search",
    "tool_result": None,
}
print(state)
```



**运行结果：**

text

```
{'messages': [], 'next_action': 'search', 'tool_result': None}
```



TypedDict 和 BaseModel 的区别：

|              | TypedDict | BaseModel     |
| :----------- | :-------- | :------------ |
| 运行时有校验 | ❌         | ✅             |
| 性能         | 快        | 略慢          |
| 用途         | 内部状态  | API 请求/响应 |
| 支持默认值   | 有限      | ✅             |

LangGraph 状态用 TypedDict，因为不需要运行时校验，只要类型提示。

## 2.9 练习

1. 用 Pydantic 定义 `AgentRequest`，包含 `query`、`session_id`、`tools` 列表。
2. 给 `query` 加 `min_length=1`，试着传空字符串看报错。
3. 用 `TypedDict` + `Annotated` 定义 LangGraph 状态。
4. 用 `model_validator` 实现"start 必须小于 end"。

------

# 第三部分：生成器与迭代器

## 3.1 什么是生成器？

普通函数用 `return` 一次性返回。
生成器用 `yield`，**一次产出一个值**，可以产出多次。

python

```
def count_up(n: int):
    """生成器：依次产出 0 到 n-1"""
    for i in range(n):
        yield i

# 使用
for x in count_up(3):
    print(x)
```



**运行结果：**

text

```
0
1
2
```



## 3.2 yield 和 return 的区别

python

```
def f_return():
    return 1
    return 2   # 永远不执行

def f_yield():
    yield 1
    yield 2
    yield 3

print("return 版本：", f_return())
print("yield 版本：", list(f_yield()))
```



**运行结果：**

text

```
return 版本： 1
yield 版本： [1, 2, 3]
```



执行 `f_yield()` 不会立即运行，返回一个生成器对象。每次 `next()` 或 `for` 循环，才执行到下一个 `yield`。

python

```
gen = f_yield()
print(next(gen))   # 1
print(next(gen))   # 2
print(next(gen))   # 3
# print(next(gen))   # StopIteration
```



## 3.3 生成器价值：惰性求值 + 内存高效

python

```
import sys

# 列表：一次性生成 100 万个数字，占满内存
def make_list(n):
    return [i * i for i in range(n)]

# 生成器：一次只产生一个
def make_gen(n):
    for i in range(n):
        yield i * i

lst = make_list(1_000_000)
gen = make_gen(1_000_000)

print("列表内存：", sys.getsizeof(lst), "字节")
print("生成器内存：", sys.getsizeof(gen), "字节")
```



**运行结果：**

text

```
列表内存： 8448728 字节
生成器内存： 104 字节
```



生成器内存几乎可以忽略。

## 3.4 异步生成器：Agent 流式输出的核心

python

```
import asyncio

async def stream_llm(prompt: str):
    """模拟 LLM 逐字输出"""
    tokens = ["你", "好", "，", "世", "界"]
    for token in tokens:
        await asyncio.sleep(0.2)
        yield token

async def main():
    async for token in stream_llm("hi"):
        print(token, end="", flush=True)
    print()

asyncio.run(main())
```



**运行结果：**

text

```
你好，世界
```



（每字间隔 0.2 秒依次出现）

## 3.5 FastAPI 中实现 SSE 流式输出

python

```
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio
import json

app = FastAPI()

async def event_generator(prompt: str):
    """SSE 事件生成器"""
    tokens = ["你", "好", "，", "世", "界"]
    for token in tokens:
        await asyncio.sleep(0.3)
        data = json.dumps({"token": token}, ensure_ascii=False)
        # SSE 格式：data: xxx\n\n
        yield f"data: {data}\n\n"
    # 结束标记
    yield "data: [DONE]\n\n"

@app.get("/stream")
async def stream(prompt: str):
    return StreamingResponse(
        event_generator(prompt),
        media_type="text/event-stream",
    )
```



**运行方式：**

bash

```
uvicorn main:app --reload
```



**测试：**

bash

```
curl -N http://127.0.0.1:8000/stream?prompt=hi
```



**运行结果：**

text

```
data: {"token": "你"}

data: {"token": "好"}

data: {"token": "，"}

data: {"token": "世"}

data: {"token": "界"}

data: [DONE]
```



## 3.6 LangGraph 的流式

python

```
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages]

def node_a(state: State):
    return {"messages": [{"role": "assistant", "content": "回答A"}]}

graph = StateGraph(State)
graph.add_node("a", node_a)
graph.add_edge(START, "a")
graph.add_edge("a", END)
app_graph = graph.compile()

async def main():
    async for event in app_graph.astream(
        {"messages": [{"role": "user", "content": "你好"}]},
        stream_mode="updates",
    ):
        print(event)
```



**运行结果：**

text

```
{'a': {'messages': [{'role': 'assistant', 'content': '回答A'}]}}
```



## 3.7 生成器表达式

python

```
# 列表推导：立即生成全部
squares_list = [x * x for x in range(5)]
print("列表：", squares_list)

# 生成器表达式：惰性
squares_gen = (x * x for x in range(5))
print("生成器：", squares_gen)
print("转列表：", list(squares_gen))

# 配合函数
total = sum(x * x for x in range(5))
print("平方和：", total)
```



**运行结果：**

text

```
列表： [0, 1, 4, 9, 16]
生成器： <generator object <genexpr> at 0x...>
转列表： [0, 1, 4, 9, 16]
平方和： 30
```



## 3.8 常见坑

### 坑 1：生成器只能消费一次

python

```
def gen():
    yield 1
    yield 2

g = gen()
print(list(g))   # [1, 2]
print(list(g))   # []  空了！
```



### 坑 2：在生成器里混用 return 和 yield

python

```
def f():
    yield 1
    return   # 提前结束
    yield 2   # 永远不执行

print(list(f()))   # [1]
```



### 坑 3：忘记 async 用 async for

python

```
async def gen():
    yield 1

# for x in gen():        # ❌ TypeError
async for x in gen():     # ✅
    print(x)
```



## 3.9 练习

1. 写一个生成器，产出斐波那契数列前 20 项。
2. 写一个异步生成器，逐字输出一句话。
3. 用 FastAPI `StreamingResponse` 把它变成 SSE 接口。
4. 用 `curl -N` 测试流式输出。

------

# 第四部分：上下文管理器

## 4.1 with 是什么？

自动管理资源：进入时获取，退出时释放。

python

```
# 写文件
with open("example.txt", "w", encoding="utf-8") as f:
    f.write("Hello, Python!")

# 读文件
with open("example.txt", "r", encoding="utf-8") as f:
    content = f.read()
    print(content)
```



**运行结果：**

text

```
Hello, Python!
```



离开 `with` 块，文件自动关闭，即使中途报错。

## 4.2 with 的原理

python

```
class MyResource:
    def __enter__(self):
        print("1. 获取资源")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print("3. 释放资源")
        # 返回 False 表示不吞异常
        return False

    def do_something(self):
        print("2. 使用资源")

with MyResource() as r:
    r.do_something()
```



**运行结果：**

text

```
1. 获取资源
2. 使用资源
3. 释放资源
```



即使中途报错：

python

```
with MyResource() as r:
    raise ValueError("出错了")
```



**运行结果：**

text

```
1. 获取资源
3. 释放资源
Traceback (most recent call last):
  ...
ValueError: 出错了
```



`__exit__` 依然执行。

## 4.3 async with

python

```
import asyncio

class AsyncResource:
    async def __aenter__(self):
        print("1. 异步获取资源")
        await asyncio.sleep(0.2)
        return self

    async def __aexit__(self, *args):
        print("3. 异步释放资源")
        await asyncio.sleep(0.2)

    async def do_something(self):
        print("2. 使用资源")
        await asyncio.sleep(0.3)

async def main():
    async with AsyncResource() as r:
        await r.do_something()

asyncio.run(main())
```



**运行结果：**

text

```
1. 异步获取资源
2. 使用资源
3. 异步释放资源
```



## 4.4 FastAPI 数据库会话：经典用法

python

```
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from fastapi import FastAPI, Depends
from sqlalchemy import text

engine = create_async_engine("sqlite+aiosqlite:///:memory:")
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    """依赖：每个请求一个 session，用完自动关闭"""
    async with AsyncSessionLocal() as session:
        yield session   # 注意是 yield，不是 return

app = FastAPI()

@app.get("/items")
async def read_items(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"result": result.scalar()}
```



**关键点：**

- `yield session`：FastAPI 会在请求结束后继续执行 `yield` 之后的代码（关闭 session）。
- `async with` 保证异常也会关闭。

## 4.5 asynccontextmanager：写自己的异步上下文

python

```
import asyncio
from contextlib import asynccontextmanager

class FakeLLMClient:
    async def close(self):
        print("关闭 LLM 客户端")
        await asyncio.sleep(0.1)

    async def ask(self, prompt):
        await asyncio.sleep(0.2)
        return f"回答：{prompt}"

@asynccontextmanager
async def get_llm_client():
    """异步上下文：自动管理 LLM 客户端生命周期"""
    client = FakeLLMClient()
    print("创建 LLM 客户端")
    try:
        yield client
    finally:
        await client.close()

async def main():
    async with get_llm_client() as client:
        result = await client.ask("你好")
        print(result)

asyncio.run(main())
```



**运行结果：**

text

```
创建 LLM 客户端
回答：你好
关闭 LLM 客户端
```



## 4.6 FastAPI lifespan：应用级别

python

```
from contextlib import asynccontextmanager
from fastapi import FastAPI

class FakeCheckpointer:
    async def setup(self):
        print("初始化 checkpointer")

    async def close(self):
        print("关闭 checkpointer")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    print("应用启动")
    app.state.checkpointer = FakeCheckpointer()
    await app.state.checkpointer.setup()
    yield
    # 关闭时执行
    print("应用关闭")
    await app.state.checkpointer.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def index():
    return {"status": "ok"}
```



**运行方式：**

bash

```
uvicorn main:app
```



**运行结果：**

text

```
应用启动
初始化 checkpointer
INFO:     Uvicorn running on http://127.0.0.1:8000
...
# 按 Ctrl+C 停止
应用关闭
关闭 checkpointer
```



## 4.7 为什么用上下文管理器？

- **资源不泄漏**：文件、连接、会话保证释放。
- **异常安全**：即使报错，`__exit__` 也执行。
- **代码清晰**：资源生命周期一目了然。

## 4.8 常见坑

### 坑 1：yield 写在 try 外面

python

```
# ❌ 如果 yield 前出错，finally 不会执行
@asynccontextmanager
async def bad():
    yield
    await cleanup()

# ✅
@asynccontextmanager
async def good():
    try:
        yield
    finally:
        await cleanup()
```



### 坑 2：忘了 async with

python

```
async with AsyncSessionLocal() as session:   # ✅
with AsyncSessionLocal() as session:          # ❌
```



## 4.9 练习

1. 写一个上下文管理器，进入和退出时打印日志。
2. 写一个 `asynccontextmanager`，管理一个模拟的 LLM 客户端。
3. 在 FastAPI 里用 `lifespan` 初始化一个共享资源。

------

# 第五部分：装饰器

## 5.1 装饰器是什么？

装饰器是**接受一个函数，返回一个新函数**的函数。

python

```
import time

def log_time(func):
    """装饰器：记录函数耗时"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"{func.__name__} 耗时 {time.time() - start:.2f}s")
        return result
    return wrapper

@log_time
def slow():
    time.sleep(1)
    return "done"

print(slow())
```



**运行结果：**

text

```
slow 耗时 1.00s
done
```



`@log_time` 等价于 `slow = log_time(slow)`。

## 5.2 带参数的装饰器

python

```
import time

def retry(times: int):
    """带参数的装饰器：重试 times 次"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == times - 1:
                        raise
                    print(f"重试 {i+1}/{times}：{e}")
        return wrapper
    return decorator

count = 0

@retry(times=3)
def call_api():
    global count
    count += 1
    if count < 3:
        raise ValueError("模拟失败")
    return "成功"

print(call_api())
```



**运行结果：**

text

```
重试 1/3：模拟失败
重试 2/3：模拟失败
成功
```



## 5.3 functools.wraps：保留原函数元数据

python

```
from functools import wraps

def log_time(func):
    @wraps(func)   # 保留原函数名、文档字符串
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@log_time
def my_func():
    """这是我的文档"""
    pass

print(my_func.__name__)   # 不加 @wraps 会变成 wrapper
print(my_func.__doc__)    # 不加 @wraps 会变成 None
```



**运行结果：**

text

```
my_func
这是我的文档
```



## 5.4 FastAPI / LangGraph 里的装饰器

python

```
# FastAPI 路由
from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
async def read_items():
    return []

# LangChain 工具
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """根据关键词搜索。"""
    return f"搜索结果：{query}"
```



你只需要**看懂**装饰器在做什么，不要求自己写复杂装饰器。

## 5.5 常见坑

- 忘记 `@wraps`，函数名和文档丢失。
- 忘记 `*args, **kwargs`，原函数参数传不进去。
- 装饰器顺序：`@a` 在上，先应用 `@b` 再应用 `@a`。

## 5.6 练习

1. 写一个装饰器，记录函数被调用的次数。
2. 写一个带参数的重试装饰器，用于模拟 LLM 调用失败重试。
3. 给装饰器加 `@wraps`，验证函数名保留。

------

# 第六部分：异常处理

## 6.1 基本语法

python

```
try:
    num = int("abc")
except ValueError:
    print("转换失败")

print("程序继续运行")
```



**运行结果：**

text

```
转换失败
程序继续运行
```



## 6.2 完整结构

python

```
try:
    num = int("123")
except ValueError:
    print("出错")
else:
    print("成功，结果是", num)
finally:
    print("总是执行")
```



**运行结果：**

text

```
成功，结果是 123
总是执行
```



- `try`：尝试
- `except`：出错时
- `else`：没出错时
- `finally`：无论怎样都执行

## 6.3 捕获多种异常

python

```
try:
    d = {"a": 1}
    print(d["b"])
except KeyError as e:
    print("键错误：", e)
except (ValueError, IndexError) as e:
    print("值或索引错误：", e)
except Exception as e:
    print("其他错误：", e)
```



**运行结果：**

text

```
键错误： 'b'
```



## 6.4 主动抛出：raise

python

```
def divide(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("除数不能为 0")
    return a / b

try:
    divide(10, 0)
except ValueError as e:
    print("捕获：", e)
```



**运行结果：**

text

```
捕获： 除数不能为 0
```



## 6.5 自定义异常

python

```
class LLMTimeoutError(Exception):
    """自定义异常：LLM 超时"""
    pass

def call_llm(timeout: bool):
    if timeout:
        raise LLMTimeoutError("LLM 超时了")
    return "回答"

try:
    call_llm(timeout=True)
except LLMTimeoutError as e:
    print("捕获自定义异常：", e)
```



**运行结果：**

text

```
捕获自定义异常： LLM 超时了
```



## 6.6 FastAPI 中的 HTTPException

python

```
from fastapi import FastAPI, HTTPException

app = FastAPI()

items = {1: {"name": "Apple"}}

@app.get("/items/{item_id}")
def read_item(item_id: int):
    item = items.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item
```



**测试：**

bash

```
curl http://127.0.0.1:8000/items/1
curl http://127.0.0.1:8000/items/2
```



**运行结果：**

text

```
{"name":"Apple"}
{"detail":"Item not found"}   # 404
```



## 6.7 Agent 开发中的异常场景

python

```
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FakeLLM:
    def __init__(self):
        self.count = 0

    async def ask(self, prompt):
        self.count += 1
        if self.count < 3:
            raise TimeoutError("模拟超时")
        return f"回答：{prompt}"

async def call_llm_with_retry(client, prompt, retries=3):
    """带重试的 LLM 调用"""
    for i in range(retries):
        try:
            return await client.ask(prompt)
        except TimeoutError as e:
            if i == retries - 1:
                logger.error(f"最终失败：{e}")
                raise
            wait = 2 ** i   # 指数退避：1, 2, 4 秒
            logger.warning(f"第 {i+1} 次失败，{wait} 秒后重试")
            await asyncio.sleep(wait)

async def main():
    client = FakeLLM()
    try:
        result = await call_llm_with_retry(client, "你好")
        print("最终结果：", result)
    except Exception as e:
        print("全部失败：", e)

asyncio.run(main())
```



**运行结果：**

text

```
WARNING:root:第 1 次失败，1 秒后重试
WARNING:root:第 2 次失败，2 秒后重试
最终结果： 回答：你好
```



## 6.8 常见坑

### 坑 1：裸 except

python

```
try:
    ...
except:   # ❌ 连 Ctrl+C 都吞
    pass
```



### 坑 2：吞掉异常

python

```
try:
    ...
except Exception:
    pass   # ❌ 出问题你永远不知道
```



### 坑 3：finally 里 return

python

```
def f():
    try:
        return 1
    finally:
        return 2   # ❌ 返回 2，覆盖 1

print(f())   # 2
```



## 6.9 练习

1. 写一个函数，把字符串转 int，失败时返回 None。
2. 用 try/except/finally 实现安全的文件读取。
3. 写一个带重试的 LLM 调用函数，指数退避。
4. 在 FastAPI 里用 `HTTPException` 实现 404。

------

# 第七部分：字典/列表高级操作

## 7.1 字典基础操作

python

```
data = {"name": "张三", "age": 30}

print(data.get("name"))            # 张三
print(data.get("gender", "未知"))   # 未知
data.setdefault("score", 0)
print(data)                        # {'name': '张三', 'age': 30, 'score': 0}
data.update({"age": 31, "city": "北京"})
print(data)
```



**运行结果：**

text

```
张三
未知
{'name': '张三', 'age': 30, 'score': 0}
{'name': '张三', 'age': 31, 'score': 0, 'city': '北京'}
```



## 7.2 字典推导

python

```
nums = {"a": 1, "b": 2, "c": 3}

squared = {k: v * v for k, v in nums.items()}
print(squared)

even = {k: v for k, v in nums.items() if v % 2 == 0}
print(even)

# 翻转
flipped = {v: k for k, v in nums.items()}
print(flipped)
```



**运行结果：**

text

```
{'a': 1, 'b': 4, 'c': 9}
{'b': 2}
{1: 'a', 2: 'b', 3: 'c'}
```



## 7.3 列表推导

python

```
nums = [1, 2, 3, 4]

squares = [x * x for x in nums]
evens = [x for x in nums if x % 2 == 0]
pairs = [(x, y) for x in [1, 2] for y in ["a", "b"]]

print(squares)   # [1, 4, 9, 16]
print(evens)     # [2, 4]
print(pairs)     # [(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')]
```



**运行结果：**

text

```
[1, 4, 9, 16]
[2, 4]
[(1, 'a'), (1, 'b'), (2, 'a'), (2, 'b')]
```



## 7.4 解包 * 和 **

python

```
# 字典解包：合并配置
default = {"model": "gpt-4", "temperature": 0.7}
override = {"temperature": 0.9}
config = {**default, **override}
print(config)

# 列表解包
a = [1, 2]
b = [3, 4]
c = [*a, *b]
print(c)

# 函数调用解包
def f(a, b, c):
    return a + b + c

args = [1, 2, 3]
print(f(*args))

kwargs = {"a": 1, "b": 2, "c": 3}
print(f(**kwargs))
```



**运行结果：**

text

```
{'model': 'gpt-4', 'temperature': 0.9}
[1, 2, 3, 4]
6
6
```



## 7.5 函数参数里的 *args / **kwargs

python

```
def wrapper(*args, **kwargs):
    print("位置参数：", args)
    print("关键字参数：", kwargs)
    return args, kwargs

wrapper(1, 2, 3, name="张三", age=30)
```



**运行结果：**

text

```
位置参数： (1, 2, 3)
关键字参数： {'name': '张三', 'age': 30}
```



## 7.6 常用内置函数

python

```
# zip：并行迭代
names = ["张三", "李四"]
ages = [30, 25]
for name, age in zip(names, ages):
    print(name, age)

# enumerate：带索引
for i, name in enumerate(names):
    print(i, name)

# any / all
print(any([False, True, False]))   # True
print(all([True, True, True]))     # True

# sorted 带 key
users = [{"name": "b", "age": 30}, {"name": "a", "age": 25}]
print(sorted(users, key=lambda u: u["age"]))
```



**运行结果：**

text

```
张三 30
李四 25
0 张三
1 李四
True
True
[{'name': 'a', 'age': 25}, {'name': 'b', 'age': 30}]
```



## 7.7 Agent 开发中的典型用法

python

```
# 合并配置
base_config = {"model": "gpt-4", "temperature": 0.7, "max_tokens": 1000}
user_config = {"temperature": 0.9}
runtime_config = {"session_id": "s1"}
final_config = {**base_config, **user_config, **runtime_config}
print(final_config)

# 提取工具名
tools = [{"name": "search", "desc": "搜索"}, {"name": "calc", "desc": "计算"}]
tool_names = [t["name"] for t in tools]
print(tool_names)

# 构建消息
messages = [
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": "你好"},
]
print(messages)

# 找工具
target = "search"
tool = next((t for t in tools if t["name"] == target), None)
print(tool)
```



**运行结果：**

text

```
{'model': 'gpt-4', 'temperature': 0.9, 'max_tokens': 1000, 'session_id': 's1'}
['search', 'calc']
[{'role': 'system', 'content': '你是助手'}, {'role': 'user', 'content': '你好'}]
{'name': 'search', 'desc': '搜索'}
```



## 7.8 练习

1. 用字典推导统计一段文字里每个单词出现的次数。
2. 用 `**` 合并三层配置。
3. 用 `zip` 把两个列表合并成字典。
4. 用 `next` + 生成器表达式，从列表里找第一个满足条件的元素。

------

# 学习节奏建议

| 周   | 主题                            | 目标                    |
| :--- | :------------------------------ | :---------------------- |
| 1    | async / await / gather          | 能写并发调用 LLM        |
| 2    | 类型注解 + Pydantic + TypedDict | 能定义 Agent 请求和状态 |
| 3    | 生成器 + 异步生成器 + SSE       | 能实现流式输出          |
| 4    | with / async with + 装饰器      | 能管理资源和看懂路由    |
| 5    | 异常处理 + 字典高级             | 能写出健壮的 Agent      |

**核心原则：**

- 每周必须写代码，不要只看。
- 每学完一块，就用到 FastAPI + LangGraph 小项目里。
- 遇到不懂，让 Codex 帮你解释和改写。
- 每个骨架代码都要亲自跑一遍，看运行结果是否一致。

需要我针对某一部分，做成一个完整的小项目练习吗？

This response is AI-generated, for reference only.