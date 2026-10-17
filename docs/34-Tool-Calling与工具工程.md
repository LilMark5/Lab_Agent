# 34 · Tool Calling 与工具工程（含 MCP）

> **速成定位**：Agent 岗 90% 会问「工具怎么设计」「工具失败了怎么办」「MCP 是什么」。这一篇把这三件事一次讲透。
> **一句话**：工具 = 带类型注解和 docstring 的普通函数，框架自动把它翻译成模型能看懂的 JSON Schema；生产级还要补**超时、重试、鉴权边界**。

---

## 目录

1. [Function Calling 的完整链路](#1-function-calling-的完整链路)
2. [工具的三个组成部分](#2-工具的三个组成部分)
3. [模型怎么知道调哪个工具](#3-模型怎么知道调哪个工具)
4. [本项目的 5 个工具](#4-本项目的-5-个工具)
5. [闭包注入：工具怎么拿到 db 和用户](#5-闭包注入)
6. [工具健壮性：超时 + 重试 + 失败回填](#6-工具健壮性)
7. [MCP：工具与业务解耦](#7-mcp工具与业务解耦)
8. [最小可运行骨架](#8-最小可运行骨架)
9. [项目里对应哪块代码](#9-项目里对应哪块代码)
10. [面试高频问答](#10-面试高频问答)
11. [速记卡](#11-速记卡)

---

## 1. Function Calling 的完整链路

**关键认知**：模型**从不直接执行**任何函数。它只是输出一段「我想调用什么」的 JSON。

```text
① 你把工具定义（JSON Schema）随请求发给模型
② 模型返回：{"tool_calls": [{"name": "search_lab_docs", "args": {"query": "开放时间"}}]}
③ 【你的代码】在本地执行这个函数
④ 把执行结果作为 ToolMessage 追加回消息列表
⑤ 再次调用模型，模型基于结果生成最终回答
```

**第 ③ 步发生在你的进程里**，这是 Agent 安全边界的核心：模型只能「提议」，执行权在你手上。所以你可以在第 ③ 步做任何事情——鉴权、限流、审批、超时、重试。

> 面试一句话：「模型输出的是**意图**（调用哪个工具、什么参数），真正的**执行**永远在我的服务端，这也是为什么我能对写库操作加人工审批。」

---

## 2. 工具的三个组成部分

```python
@langchain_tool
def list_open_labs(keywords: str = "") -> str:
    """查询开放的实验室列表。"""      # ← ③ docstring = 工具描述
    ...                                # ← ① 类型注解生成参数 Schema
                                       # ← ② 函数体是真实业务逻辑
```

| 组成 | 作用 | 为什么重要 |
| --- | --- | --- |
| **类型注解** | `keywords: str = ""` → JSON Schema | 模型靠它知道传什么类型 |
| **docstring** | 「查询开放的实验室列表。」 | **模型靠这句话决定要不要调这个工具** |
| **函数体** | 真实查库逻辑 | 执行发生在服务端 |

> **面试金句**：「写工具时，**docstring 就是给模型看的 prompt**。写得含糊，模型就不会在正确的时机调用它。我给每个工具的描述都写明了适用场景和排除范围。」

本项目的实证：`agent_tools.py:89-93` 会根据 `include_uploaded` 开关**动态改 docstring**：

```python
_search_lab_docs.__doc__ = (
    "根据用户的提问检索知识库，包含系统内置文档和用户上传的文档。"
    if include_uploaded
    else "根据用户的提问检索系统内置知识库，不包含用户上传的文档。"
)
```

这样模型就知道当前能不能搜到上传文档——**用 docstring 传递运行时状态**，很巧妙。

---

## 3. 模型怎么知道调哪个工具

`bind_tools`：

```python
llm = ChatOpenAI(...).bind_tools(tools)
```

它把每个工具的**名称 + 描述 + 参数 Schema** 塞进请求的 `tools` 字段（OpenAI 兼容协议）。模型看到这些定义后，判断是否需要调用。

**`tool_choice`** 可控制行为（本项目未显式设置，用默认 `auto`）：模型自己决定调不调、调几个。

---

## 4. 本项目的 5 个工具

`backend/app/services/agent_tools.py`

| 工具 | 类型 | 作用 | 数据来源 |
| --- | --- | --- | --- |
| `search_lab_docs` | 读 | 检索知识库（规则/安全/开放时间） | RAG（`kb_service.search`） |
| `list_open_labs` | 读 | 查开放实验室列表 | `lab_service` |
| `list_lab_equipments` | 读 | 查某实验室的设备 | `equipment_service` |
| `create_lab_reservation` | **写** | 真实预约落库 | `reservation_service` |
| `get_today` | 读 | 获取当前日期 | `datetime.now()` |

### 工具设计的几个讲究

**① 返回值统一是字符串 JSON**

```python
return json.dumps({"total": page.total, "labs": rows}, ensure_ascii=False)
```

好处：模型容易解析；`ensure_ascii=False` 让中文不被转义成 `\uXXXX`，**省 token 且模型更易理解**。

**② 只返回必要字段**

```python
rows = [{"id": ..., "name": ..., "location": ..., "capacity": ...,
         "open_time": ..., "close_time": ...} for item in page.list]
```

不是 `model_dump()` 整表外泄。注释里也写明了「只返回回答需要的字段，避免整表外泄」——这既是**省 token**也是**安全**考虑。

**③ 异常不抛出，转成结构化错误**

```python
except Exception as exc:
    return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
```

工具抛异常会导致整个图崩掉。转成 `{"ok": false, "error": ...}` 回填给模型，模型能据此**自行纠错或换一种方式回答**——这叫「失败即上下文」。

**④ 分页限制**

`page_size=10`，避免一次返回过多内容占用上下文。

**⑤ `get_today` 存在的理由**

SYSTEM_PROMPT 里专门写了：

> 当用户提到今天、明天、后天等日期问题时，请先调用 `get_today` 获取日期，不要直接返回「我需要确定明天的具体日期」。

这是**解决模型不知道当前日期**的经典手法：给一个工具而不是让模型猜。

---

## 5. 闭包注入

工具函数签名里**没有** `db` 和 `current_user`，但函数体里用到了——靠闭包：

```python
async def build_tools(db: Session, current_user: User, include_uploaded: bool = True):
    @langchain_tool
    def create_lab_reservation(lab_id: int, date: str, ...):
        reservation_service.create_reservation(db, current_user, data)   # ← 闭包变量
```

**为什么这么做**：

1. **工具签名干净**：Schema 里只有模型该填的参数（`lab_id/date/...`），不会出现 `db` 这种模型无法提供的参数。
2. **天然带权限**：`current_user` 来自 JWT 解析结果，工具落库时 `user_id=current_user.id`，**用户没法伪造身份预约**。
3. **每请求重建**：`build_agent` 每次请求调一次 `build_tools`，保证 db 会话和用户是当前请求的。

> **面试点**：「工具的鉴权不是靠模型自觉传 user_id，而是**闭包捕获**服务端解析出的用户对象，模型想伪造也做不到。」

---

## 6. 工具健壮性

### 6.1 为什么要超时和重试

工具内部是**同步阻塞**的 DB 查询。直接在 async 节点里调用会阻塞整个事件循环；慢查询或外部调用卡住会拖垮整张图。

### 6.2 本项目的实现（`agent_service.py`）

```python
async def _invoke_tool_with_retry(tool, args: dict) -> str:
    last_error: Exception | None = None
    for attempt in range(settings.TOOL_MAX_RETRIES + 1):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(tool.invoke, args),      # 同步工具丢线程池
                timeout=settings.TOOL_TIMEOUT_SECONDS,     # 超时保护
            )
            return result.content if hasattr(result, "content") else str(result)
        except Exception as exc:
            last_error = exc
            if attempt < settings.TOOL_MAX_RETRIES:
                await asyncio.sleep(0.2 * (attempt + 1))   # 简单退避
    return json.dumps({"ok": False, "error": str(last_error)}, ensure_ascii=False)
```

**三个技术点逐个讲**：

1. **`asyncio.to_thread(tool.invoke, args)`**：工具是同步函数（SQLAlchemy 同步 Session），丢到线程池执行，**不阻塞事件循环**。
2. **`asyncio.wait_for(..., timeout=30)`**：超时强制中断，防止慢查询拖死整张图。
3. **有限重试 + 退避**：`TOOL_MAX_RETRIES=1`（即最多 2 次尝试），只针对**临时性故障**（网络抖动）。**绝不能无限重试**——写库工具重试可能造成重复写入。

**最终失败的处理**：回填 `{"ok": false, "error": "..."}` 给模型，让它自己决定怎么回复用户。

### 6.3 写库工具的幂等性

> **面试必答**：「写库工具重试会不会造成重复预约？」
> 不会。两个保障：① 重试次数有限（1 次）；② 更根本的是 `create_reservation` 内部的时段冲突检测覆盖 `status in [0,1]` 且配 `with_for_update` 行锁，**重复提交会命中冲突被拒绝**，天然幂等。

本项目还踩过一个坑：曾尝试加「同用户同参数查重」的应用层幂等，结果破坏了并发测试「两线程抢同一时段应返回 busy」的互斥语义，最后**回退**了，确认冲突检测已足够。（这个取舍讲出来很加分。）

---

## 7. MCP：工具与业务解耦

### 7.1 MCP 是什么

**Model Context Protocol**：把工具从「某个 Agent 的内部函数」变成「独立服务暴露的标准协议」。任何支持 MCP 的客户端（Claude、Cursor、自研 Agent）都能接入。

```text
传统：工具函数写死在 agent_tools.py 里 → 只有本项目能用
MCP ：工具跑在独立 Server 上 → Claude / 其它 Agent 都能调
```

### 7.2 本项目的分工（设计亮点）

`agent_tools.py:187-198`：

```python
mcp_tools = await _load_mcp_tools()
if mcp_tools:
    return [*mcp_tools, create_lab_reservation, get_today]     # 读工具来自 MCP
return [search_lab_docs, list_open_labs, list_lab_equipments,
        create_lab_reservation, get_today]                      # 回退本地
```

| 类型 | 位置 | 原因 |
| --- | --- | --- |
| **读工具**（检索/查实验室/查设备） | MCP Server | 无副作用，可以开放给外部客户端 |
| **写工具**（`create_lab_reservation`） | **本地，带鉴权** | 写操作必须拿得到 JWT 用户身份 |

> **面试金句**：「MCP 的边界我划在**读写**上：读工具走 MCP 对外开放，写工具留在本地带鉴权的服务里。MCP Server 是公开协议服务，**不直接接受写操作**——这是刻意的安全边界。」（`mcp_server.py:9-10` 注释里也这么写）

### 7.3 MCP Server 实现（`app/mcp_server.py`）

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="lab-agent-mcp", instructions="智能实验室预约系统 MCP 服务")

@mcp.tool()
def search_lab_docs(query: str) -> str:
    """检索知识库（内置文档与用户上传文档，含预约规则、开放时间、安全规范等）。"""
    return kb_service.search(query) or "没有检索到相关资料"
```

启动：`mcp.run(transport="streamable-http", host="127.0.0.1", port=8100)`

**三个细节**：
1. 每个工具**自己开短会话** `_db()` 用完 `finally: db.close()`（`mcp_server.py:24-25`）。
2. 只返回必要字段，避免整表外泄。
3. `list_*` 用 `.limit(20)` 限制返回量。

### 7.4 一个真实修复的 Bug（面试素材）

`_load_mcp_tools` 原本用 `asyncio.get_running_loop()` 探测是否在 async 上下文，**在 async 里就直接 `return None`**。而 `build_agent` 是 async → **流式场景下 MCP 工具永远加载不到**，静默回退本地工具。

修复：改成真正的 `async def` 直接 `await client.get_tools()`，并用 `asyncio.Lock` + 双重检查防止并发重复建连。

> 另外：`langchain-mcp-adapters 0.3.2` 的 `MultiServerMCPClient` **上下文管理器已被移除**（`__aenter__` 抛 `NotImplementedError`），连接是自管理的，所以不需要 `asyncio.run` 包装。这个版本坑讲出来证明你真踩过。

---

## 8. 最小可运行骨架

不需要真实模型和数据库，演示「定义工具 → 序列化成 Schema → 模拟模型返回 tool_call → 带超时重试执行 → 回填结果」。

```python
"""最小骨架：工具定义 + Schema 生成 + 超时重试执行 + 失败回填。"""

import asyncio
import json
from typing import Optional

from langchain_core.tools import tool


# ============ 1. 定义工具：注解=Schema，docstring=给模型看的描述 ============
@tool
def search_lab_docs(query: str) -> str:
    """检索实验室知识库，用于回答规则、安全规范、开放时间等问题。"""
    # 真实项目：查向量库 + BM25
    return json.dumps({"ok": True, "result": f"关于「{query}」的规定：开放时间 8:00-22:00"},
                      ensure_ascii=False)


@tool
def create_lab_reservation(lab_id: int, date: str,
                           start_time: str, end_time: str,
                           remark: Optional[str] = None) -> str:
    """创建预约单，预约实验室。必须在用户明确确认后才能调用。"""
    # 真实项目：reservation_service.create_reservation(db, current_user, ...)
    return json.dumps({"ok": True, "message": "预约已提交，请等待管理员审核"},
                      ensure_ascii=False)


# ============ 2. 看看模型实际收到的 Schema 长什么样 ============
if __name__ == "__main__":
    print("=== 工具 Schema（这就是发给模型的东西）===")
    print(json.dumps(create_lab_reservation.args_schema.model_json_schema(),
                     ensure_ascii=False, indent=2))

    # ============ 3. 带超时 + 重试的执行器（本项目 _invoke_tool_with_retry 的简化版）============
    TOOL_TIMEOUT = 1.0
    MAX_RETRIES = 1

    async def invoke_with_retry(fn, args: dict) -> str:
        """同步工具丢线程池 + 超时 + 有限重试 + 失败回填。"""
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(fn.invoke, args),   # 同步函数丢线程池，不阻塞事件循环
                    timeout=TOOL_TIMEOUT,
                )
                return result.content if hasattr(result, "content") else str(result)
            except Exception as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.2 * (attempt + 1))
        # 最终失败：回填结构化错误，让模型自己决定怎么说
        return json.dumps({"ok": False, "error": str(last_error)}, ensure_ascii=False)

    # ============ 4. 一个会失败的假工具，用来演示重试 ============
    @tool
    def flaky_query(x: str) -> str:
        """一个会失败的查询工具，用于演示重试。"""
        raise RuntimeError("db timeout")

    async def demo():
        print("\n=== 正常工具 ===")
        print(await invoke_with_retry(search_lab_docs, {"query": "开放时间"}))

        print("\n=== 失败工具（重试 1 次后回填错误）===")
        print(await invoke_with_retry(flaky_query, {"x": "1"}))

        print("\n=== 超时工具 ===")
        @tool
        def slow_query(x: str) -> str:
            """一个很慢的工具，用于演示超时。"""
            import time
            time.sleep(5)
            return "done"

        print(await invoke_with_retry(slow_query, {"x": "1"}))

    asyncio.run(demo())
```

**预期输出要点**：

```text
=== 工具 Schema ===
{"title": "create_lab_reservation", "description": "创建预约单...",
 "properties": {"lab_id": {"type": "integer"}, ...},
 "required": ["lab_id", "date", "start_time", "end_time"]}

=== 正常工具 ===
{"ok": true, "result": "关于「开放时间」的规定：开放时间 8:00-22:00"}
=== 失败工具 ===
{"ok": false, "error": "db timeout"}
=== 超时工具 ===
{"ok": false, "error": ""}          ← 1 秒超时被 wait_for 打断
```

---

## 9. 项目里对应哪块代码

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| 工具构建入口 | `agent_tools.py:68-198` | `build_tools(db, current_user, include_uploaded)` |
| 检索工具 | `agent_tools.py:79-94` | `search_lab_docs` + **动态 docstring** |
| 查实验室 | `agent_tools.py:96-117` | 只返回必要字段 |
| 查设备 | `agent_tools.py:119-143` | |
| **写库工具** | `agent_tools.py:145-180` | 调 `reservation_service.create_reservation` |
| 日期工具 | `agent_tools.py:182-185` | 解决模型不知道今天几号 |
| 写工具集合 | `agent_service.py:100` | `WRITE_TOOLS = {"create_lab_reservation"}` |
| **超时重试** | `agent_service.py:155-173` | `_invoke_tool_with_retry` |
| 工具节点 | `agent_service.py:216-242` | 审批判定 + 执行 + 回填 |
| **MCP 加载** | `agent_tools.py:32-65` | async + `asyncio.Lock` 双重检查 |
| **MCP Server** | `mcp_server.py:28-91` | FastMCP 3 个读工具 |
| MCP 启动 | `mcp_server.py:94-102` | `streamable-http` :8100 |
| 工具中文名 | `agent_service.py:91-97` | `TOOL_LABELS`（前端展示用） |
| 配置 | `config.py:114-117` | `TOOL_TIMEOUT_SECONDS=30`、`TOOL_MAX_RETRIES=1` |
| 配置 | `config.py:102-105` | `MCP_ENABLED` / `MCP_TRANSPORT` / `MCP_URL` |

---

## 10. 面试高频问答

**Q1：Function Calling 的执行发生在哪里？**
> 模型只输出「想调用什么工具、什么参数」的 JSON，**执行永远在我的服务端**。模型返回 `tool_calls` 后，我在 tool_node 里执行函数、拿到结果、封装成 ToolMessage 追加回消息列表，再让模型生成最终回答。正因为执行权在我手上，我才能对写库操作加人工审批、加鉴权、加超时。

**Q2：工具的 docstring 有什么用？**
> 它就是**给模型看的 prompt**。框架会把 docstring 作为 `description` 放进 JSON Schema，模型靠这句话判断什么时候该调这个工具。所以我每个工具的描述都写明了适用场景；甚至会根据运行时的开关动态改 docstring（比如是否包含用户上传文档）。

**Q3：工具参数怎么传给模型？**
> 用类型注解。`lab_id: int` 会生成 `{"type": "integer"}`，可选参数 `remark: str | None = None` 不会进 `required`。模型按 Schema 填参数，框架再反序列化回来。

**Q4：工具执行失败怎么办？**
> 三层：① 工具内部 `try/except` 转成 `{"ok": false, "error": ...}`，不抛异常（抛异常会崩掉整张图）；② 外层 `_invoke_tool_with_retry` 带 30 秒超时和有限重试；③ 最终失败回填结构化错误给模型，让它自己决定怎么回复用户。这叫「失败即上下文」——把错误也当成信息喂给模型。

**Q5：同步工具在 async 节点里怎么调用？**
> 用 `asyncio.to_thread(tool.invoke, args)` 丢到线程池，避免阻塞事件循环；外面再套 `asyncio.wait_for(..., timeout=30)` 防慢查询拖死整张图。

**Q6：写库工具重试会不会造成重复预约？**
> 不会。① 重试次数有限（默认 1 次）；② 根本保障是 `create_reservation` 内部的时段冲突检测覆盖 `status in [0,1]` 且配 `with_for_update` 行锁，重复提交会命中冲突被拒绝，天然幂等。我评估过加应用层查重，但它会破坏并发测试「两线程抢同一时段应返回 busy」的语义，所以没加。

**Q7：MCP 解决了什么问题？**
> 把工具从「某个 Agent 的内部函数」变成「独立服务暴露的标准协议」。同样的实验室查询工具，Claude、Cursor 或任何支持 MCP 的客户端都能直接用，不用重复实现。

**Q8：为什么写工具不放进 MCP？**
> MCP Server 是公开协议服务，拿不到调用方的 JWT 身份。写操作必须绑定真实用户（`user_id=current_user.id`），所以写工具留在本地带鉴权的服务里，用闭包捕获用户对象。我把读写边界作为 MCP 的划分线——这是刻意的安全设计。

**Q9：MCP 不可用会怎样？**
> 自动回退本地工具（`build_tools` 里 `if mcp_tools` 否则返回本地列表），功能不降级，只是失去跨客户端复用能力。

**Q10：怎么防止模型乱调工具？**
> 三层：① docstring 写清适用场景；② SYSTEM_PROMPT 里写死规则（比如「提交预约前必须复述信息并获得确认」「日期问题先调 get_today」）；③ **写库工具由 LangGraph 的 interrupt 强制中断等待人工确认**——前两层是软约束，第三层是硬约束。

---

## 11. 速记卡

```text
Function Calling：模型只输出意图(JSON)，执行永远在服务端
  → 所以能做鉴权/审批/超时/重试

工具三要素：
  类型注解 → JSON Schema（模型知道传什么）
  docstring → description（模型知道何时调）★写给模型看的 prompt
  函数体   → 真实业务（服务端执行）

本项目 5 工具：
  search_lab_docs / list_open_labs / list_lab_equipments（读）
  create_lab_reservation（写，需审批）
  get_today（解决模型不知道日期）
  返回统一 JSON 字符串；ensure_ascii=False 省 token；只返回必要字段

闭包注入：db / current_user 不进签名 → Schema 干净 + 天然带权限
         模型无法伪造身份（user_id 来自 JWT 解析）

健壮性三件套：
  asyncio.to_thread(同步工具丢线程池)
  + asyncio.wait_for(timeout=30)
  + 有限重试(1次)+退避，最终回填 {"ok":false,"error":...}
  幂等：写库由时段冲突检测+行锁天然覆盖

MCP：读工具走 MCP(对外开放) / 写工具留本地(带鉴权) ← 刻意的安全边界
  FastMCP + streamable-http :8100
  ⚠️ 0.3.2 的 __aenter__ 已移除，连接自管理
  ⚠️ 曾在 async 上下文误探测导致流式场景 MCP 静默失效（已修）
```
