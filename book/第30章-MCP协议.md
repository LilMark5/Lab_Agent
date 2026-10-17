# 第 30 章 · MCP 协议：工具的"USB 接口"

> **这一章要回答的核心问题**：MCP 是什么？它和 Function Calling 有什么区别？为什么写库工具不能放进 MCP？跨进程的工具怎么保证不丢鉴权？

---

## 30.1 引子：每个 Agent 都在重复造轮子

假设你有三个 AI 应用：

1. 实验室预约 Agent（本项目）
2. Claude Desktop（你想让它也能查实验室）
3. 一个内部的运维机器人

它们都需要"查实验室列表"这个能力。

**没有 MCP 时**，你要写三遍：

```
Agent 1: @tool def list_open_labs(...)   # Python / LangChain 格式
Claude:  { "name": "list_open_labs", ... }  # Claude 的 tool 格式
运维机器人: 又一个格式...
```

每个 AI 平台的工具定义格式、调用协议、传输方式都不一样。**N 个应用 × M 个工具 = N×M 次适配工作。**

**MCP 要做的事，就是给"AI 应用"和"工具"之间定一个标准接口**：

```
N 个应用 × M 个工具  →  N + M 次实现
```

这就是 MCP 被称作"AI 应用的 USB-C"的原因。

---

## 30.2 MCP 是什么

**MCP（Model Context Protocol）** 是 Anthropic 在 2024 年 11 月开源的一个协议，定义 AI 应用如何连接外部工具和数据源。

### 30.2.1 三个角色

| 角色 | 是什么 | 本项目 |
|---|---|---|
| **Host** | AI 应用本体（发起方） | LangGraph Agent |
| **Client** | Host 里的连接器 | `MultiServerMCPClient` |
| **Server** | 提供工具/数据的一方 | `app/mcp_server.py` |

### 30.2.2 三类能力

MCP Server 可以提供三类东西：

| 能力 | 说明 | 本项目 |
|---|---|---|
| **Tools** | 可调用的函数 | ✅ `search_lab_docs`、`list_open_labs`、`list_lab_equipments` |
| **Resources** | 可读的数据（文件、数据库记录） | ❌ 未实现 |
| **Prompts** | 预定义的提示词模板 | ❌ 未实现 |

本项目只用了 **Tools**。

### 30.2.3 和 Function Calling 的关系（重要）

**这是面试必问，也是最容易混淆的点。**

| 维度 | Function Calling | MCP |
|---|---|---|
| **层次** | 模型 ↔ 应用 | 应用 ↔ 工具 |
| **解决的问题** | 让模型表达"我想调工具"的意图 | 让应用能发现并调用外部工具 |
| **位置** | 模型 API 的一部分 | 应用架构的一部分 |
| **是否必须** | 有 Agent 就有 | 可选 |

**它们不是竞争关系，是上下游关系**：

```
模型 --[Function Calling]--> Agent 应用 --[MCP]--> MCP Server --> 真实资源
      "我想调 search_lab_docs"        "去调用它"        "执行并返回"
```

> **一句话区分**：**Function Calling 是模型说"我要用工具"的语言；MCP 是应用去找工具、调工具的语言。**

**推论**：**不用 MCP 也能做 Agent**（本项目在 MCP 不可用时就是回退本地工具）；**用了 MCP 也不代表模型直接调 MCP**（中间必须经过应用转换成本地的工具对象，再 `bind_tools` 给模型）。

看本项目的代码正是如此（`agent_tools.py:187-198`）：

```python
mcp_tools = await _load_mcp_tools()      # 通过 MCP 拿到工具对象
if mcp_tools:
    return [*mcp_tools, create_lab_reservation, get_today]   # 混在一起
...
llm = ChatOpenAI(...).bind_tools(tools)  # ★ 模型看到的还是"本地工具"
```

**模型完全不知道 MCP 的存在** —— 它只看到一堆普通的 tool schema。

---

## 30.3 项目实现：MCP Server

`backend/app/mcp_server.py`（103 行）。

### 30.3.1 三个工具

```python
@mcp.tool()
def search_lab_docs(query: str) -> str:
    """检索知识库（内置文档与用户上传文档，含预约规则、开放时间、安全规范等）。"""
    result = kb_service.search(query)
    return result or "没有检索到相关资料"


@mcp.tool()
def list_open_labs(keywords: str = "") -> str:
    """查询开放中的实验室列表。"""
    db = _db()
    try:
        query = db.query(Lab).filter(Lab.status == 1)
        if keywords.strip():
            like = f"%{keywords.strip()}%"
            query = query.filter((Lab.name.ilike(like)) | (Lab.location.ilike(like)))
        rows = [{...} for lab in query.limit(20).all()]
        return json.dumps({"total": len(rows), "labs": rows}, ensure_ascii=False)
    finally:
        db.close()
```

**和本地工具（`agent_tools.py`）的对比**：

| 维度 | 本地工具 | MCP 工具 |
|---|---|---|
| db 来源 | **闭包注入**（请求级 Session） | **自己开**（`_db()` → `SessionLocal()`） |
| 用户身份 | **闭包注入** `current_user` | **完全没有** |
| 写操作 | ✅ 支持（有鉴权） | ❌ 只暴露读 |

### 30.3.2 为什么每个工具自己开 Session

```python
def _db() -> Session:
    return SessionLocal()  # 每个工具自己开一个短会话，用完关闭
```

MCP Server 是**独立进程**（`python -m app.mcp_server`），没有 FastAPI 的依赖注入，也没有"请求上下文"。所以它只能自己管理数据库会话。

**并且用完必须关闭**：

```python
try:
    ...
finally:
    db.close()
```

`finally` 保证异常时也会关闭（第 9 章讲过依赖注入的 finally）。

### 30.3.3 ★ 安全边界：为什么只暴露读工具

文件头注释写得非常清楚（`mcp_server.py:8-10`）：

```python
"""
这里只暴露"读"工具；写库（预约）仍留在有鉴权的 LangGraph Agent 里，
这是刻意的安全边界：公开协议服务不直接接受写操作。
"""
```

**这是本章最重要的设计判断，面试必讲。**

**原因**：MCP Server 是**无鉴权**的。它没有：
- JWT 校验
- 用户身份
- 权限检查

如果暴露 `create_lab_reservation`，意味着**任何能访问这个端口的人都能预约任何实验室**——而且是以**任意用户身份**（因为没有身份校验）。

所以：

| 工具类型 | 位置 | 理由 |
|---|---|---|
| **读**（检索、查询） | MCP | 无鉴权要求，可跨应用复用 |
| **写**（预约） | 本地 | **必须知道是谁在操作** |

> **面试金句**："我们有一个刻意的安全边界：**MCP Server 只暴露读工具，写库工具留在本地 Agent 里**。因为 MCP 是跨进程的公开协议服务，它拿不到请求级的数据库会话和用户身份——如果在 MCP 里暴露'创建预约'，等于任何人都能以任意身份操作。所以'需要知道是谁在做'的操作必须留在有鉴权的本地。"

### 30.3.4 传输方式

```python
mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
```

MCP 支持三种传输：

| 传输 | 说明 | 适用 |
|---|---|---|
| **stdio** | 通过标准输入输出（子进程） | 本地工具（Claude Desktop 常用） |
| **SSE** | HTTP + Server-Sent Events | 远程（旧版） |
| **streamable-http** | HTTP（新标准） | 远程（推荐） |

本项目用 `streamable-http`，绑 `127.0.0.1`（**只监听本地**，不对外暴露）。

配置项：

```bash
MCP_ENABLED=true
MCP_URL=http://127.0.0.1:8100/mcp
MCP_TRANSPORT=streamable-http
```

---

## 30.4 客户端：怎么加载 MCP 工具

`agent_tools.py:32-65`（第 20 章讲过锁的部分，这里看协议部分）：

```python
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient({
    "lab": {
        "url": settings.MCP_URL,
        "transport": settings.MCP_TRANSPORT,
    }
})
tools = await client.get_tools()
```

**`langchain-mcp-adapters` 做的事**：

1. 连接 MCP Server
2. 调用 `list_tools` 拿到工具定义（JSON Schema）
3. **把每个 MCP 工具包装成 LangChain 的 `StructuredTool`**
4. 返回工具列表

**包装后的工具和本地 `@tool` 定义的工具完全同构** —— 都有 `.name`、`.description`、`.invoke()`。所以可以直接混在一起 `bind_tools`（第 20 章 `agent_tools.py:187-198`）。

**这就是适配器的价值**：让不同来源的工具在应用层统一。

---

## 30.5 MCP 的工程代价

引入 MCP 不是免费的：

| 代价 | 说明 | 本项目 |
|---|---|---|
| **多一个进程** | 要单独启动、监控 | `python -m app.mcp_server` |
| **网络往返** | 每次工具调用多一次 HTTP | 本地回环，约 1-5ms |
| **失败点** | MCP 挂了怎么办 | 回退本地工具 ✅ |
| **无鉴权** | 只能放读工具 | 已处理 ✅ |
| **版本兼容** | 库 API 变动频繁 | 锁定版本 ✅ |

**本项目的降级设计**（第 20 章详述）：

```python
mcp_tools = await _load_mcp_tools()
if mcp_tools:
    return [*mcp_tools, create_lab_reservation, get_today]

return [search_lab_docs, list_open_labs, list_lab_equipments, create_lab_reservation, get_today]
```

**MCP 不可用 → 用本地实现的同名工具**。用户无感知。

**这是"可选依赖"的最佳实践**：增强功能挂了，核心功能不受影响。

> ⚠️ **注意一个细节**：MCP 版本的 `search_lab_docs` 和本地版本的**行为略有不同**——本地版支持 `document_id` 过滤（对应 `include_uploaded`），MCP 版（`mcp_server.py:35-38`）固定搜全库：
> ```python
> result = kb_service.search(query)      # 没传 document_id
> ```
> 所以**当 MCP 可用时，"是否包含上传文档"这个开关会失效**。
>
> 这是一个真实的功能不一致。**面试时主动指出**："MCP 版本的检索工具没有接 `include_uploaded` 参数，所以 MCP 启用时这个开关不生效。这是 MCP 工具接口设计时的简化——因为 MCP 是跨进程的通用协议，不应该绑定我们应用特有的参数。更好的做法是在 MCP 工具里加一个可选的 `scope` 参数。"

---

## 30.6 最小骨架：手写一个 MCP 风格的服务与客户端

```python
"""
minimal_mcp.py —— 模拟 MCP 的核心机制：服务发现 + 跨进程调用 + 降级
运行：python minimal_mcp.py  （纯 Python，无需依赖）
重点理解：tools/list 协议、JSON-RPC 风格、适配器包装
"""
import json
from typing import Any, Callable


# ══════════════════════════════════════════════════════════
# 服务端：模拟 MCP Server（真实项目是独立进程 + HTTP）
# ══════════════════════════════════════════════════════════
class McpServer:
    """提供工具的 Server。★ 只暴露读工具（安全边界）。"""

    def __init__(self, name: str):
        self.name = name
        self._tools: dict[str, dict] = {}

    def tool(self, fn: Callable):
        """装饰器：注册工具，从签名和 docstring 生成 schema（和 @tool 一样）。"""
        import inspect
        sig = inspect.signature(fn)
        props, required = {}, []
        for pname, p in sig.parameters.items():
            props[pname] = {"type": "string"}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        self._tools[fn.__name__] = {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip(),
            "inputSchema": {"type": "object", "properties": props, "required": required},
            "_fn": fn,
        }
        return fn

    def list_tools(self) -> list[dict]:
        """★ MCP 协议方法：客户端用它发现有哪些工具。"""
        return [
            {"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]}
            for t in self._tools.values()
        ]

    def call_tool(self, name: str, args: dict) -> str:
        """★ MCP 协议方法：执行工具。"""
        tool = self._tools.get(name)
        if not tool:
            return json.dumps({"error": f"未找到工具：{name}"}, ensure_ascii=False)
        try:
            return tool["_fn"](**args)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)


# ── 定义服务端的工具（只读！）──────────────────────────────
server = McpServer("lab-agent-mcp")


@server.tool()
def search_lab_docs(query: str) -> str:
    """检索知识库（内置文档与用户上传文档，含预约规则、开放时间、安全规范等）。"""
    return f"[检索结果] 关于「{query}」：实验室开放时间 8:00-22:00"


@server.tool()
def list_open_labs(keywords: str = "") -> str:
    """查询开放中的实验室列表。"""
    labs = [{"id": 1, "name": "量子实验室"}, {"id": 2, "name": "显微镜实验室"}]
    if keywords:
        labs = [l for l in labs if keywords in l["name"]]
    return json.dumps({"total": len(labs), "labs": labs}, ensure_ascii=False)


# ★ 注意：没有 create_reservation —— 写工具不进 MCP


# ══════════════════════════════════════════════════════════
# 客户端适配器：把 MCP 工具包装成本地工具对象
# ══════════════════════════════════════════════════════════
class AdaptedTool:
    """包装后的工具：和本地 @tool 定义的工具同构（有 name/description/invoke）。"""

    def __init__(self, schema: dict, server: McpServer):
        self.name = schema["name"]
        self.description = schema["description"]
        self.args_schema = schema["inputSchema"]
        self._server = server

    def invoke(self, args: dict) -> Any:
        """★ 本地调用 → 转成 MCP 协议调用（真实场景是一次 HTTP 往返）。"""
        return self._server.call_tool(self.name, args)


class McpClient:
    def __init__(self, url: str):
        self.url = url

    def get_tools(self) -> list[AdaptedTool]:
        # 真实场景：HTTP 请求 list_tools
        return [AdaptedTool(s, server) for s in server.list_tools()]


# ══════════════════════════════════════════════════════════
# 本地工具（MCP 不可用时的降级实现）
# ══════════════════════════════════════════════════════════
class LocalTool:
    def __init__(self, name: str, description: str, fn: Callable):
        self.name = name
        self.description = description
        self._fn = fn

    def invoke(self, args: dict) -> Any:
        return self._fn(**args)


def local_search_lab_docs(query: str, document_id: str | None = None) -> str:
    """本地版检索（支持 document_id 过滤）。"""
    scope = "全库" if document_id is None else f"仅{document_id}"
    return f"[本地检索·{scope}] 关于「{query}」：开放时间 8:00-22:00"


def create_lab_reservation(lab_id: int, date: str) -> str:
    """★ 写工具：只在本地，因为它需要用户身份。"""
    return json.dumps({"ok": True, "msg": "预约已提交（已鉴权）"}, ensure_ascii=False)


# ══════════════════════════════════════════════════════════
# 组装：MCP 优先，本地兜底（本项目 agent_tools.build_tools 的逻辑）
# ══════════════════════════════════════════════════════════
def build_tools(mcp_available: bool = True) -> list:
    write_tools = [
        LocalTool("create_lab_reservation", "创建预约（需鉴权）", create_lab_reservation),
    ]
    if mcp_available:
        try:
            mcp_tools = McpClient("http://127.0.0.1:8100/mcp").get_tools()
            return [*mcp_tools, *write_tools]      # ★ 读走 MCP，写留本地
        except Exception as exc:
            print(f"  ⚠ MCP 不可用，降级本地：{exc}")

    local_read = [
        LocalTool("search_lab_docs", "检索知识库", local_search_lab_docs),
        LocalTool("list_open_labs", "查询实验室", lambda keywords="": "本地实验室列表"),
    ]
    return [*local_read, *write_tools]


if __name__ == "__main__":
    print("=" * 62)
    print("【MCP Server 的 tools/list 响应】（模型最终看到的 schema）")
    for t in server.list_tools():
        print(f"  - {t['name']}: {t['description'][:30]}")
        print(f"    schema: {json.dumps(t['inputSchema'], ensure_ascii=False)}")

    print("\n" + "=" * 62)
    print("【MCP 可用时】")
    tools = build_tools(mcp_available=True)
    for t in tools:
        print(f"  - {t.name:24} ({type(t).__name__})")
    print("  ★ 读工具来自 MCP，写工具来自本地")

    print("\n【MCP 不可用时（降级）】")
    tools = build_tools(mcp_available=False)
    for t in tools:
        print(f"  - {t.name:24} ({type(t).__name__})")
    print("  ★ 全部本地，用户无感知")

    print("\n" + "=" * 62)
    print("【调用演示：本地接口 → MCP 协议 → 远程执行】")
    tools = build_tools(mcp_available=True)
    search = next(t for t in tools if t.name == "search_lab_docs")
    print(f"  调用 {search.name}({{'query': '开放时间'}})")
    print(f"  结果：{search.invoke({'query': '开放时间'})}")

    print("\n" + "=" * 62)
    print("【★ 安全边界验证】")
    print(f"  MCP 暴露的工具：{[t['name'] for t in server.list_tools()]}")
    print(f"  写工具 create_lab_reservation 是否在 MCP 里？"
          f" {'create_lab_reservation' in [t['name'] for t in server.list_tools()]}")
    print("  ✅ 不在。因为 MCP 无鉴权，写操作必须留在本地")
```

**预期输出（关键部分）**：

```
【MCP 可用时】
  - search_lab_docs        (AdaptedTool)   ← 来自 MCP
  - list_open_labs         (AdaptedTool)   ← 来自 MCP
  - create_lab_reservation (LocalTool)     ← 本地
  ★ 读工具来自 MCP，写工具来自本地

【★ 安全边界验证】
  MCP 暴露的工具：['search_lab_docs', 'list_open_labs']
  写工具 create_lab_reservation 是否在 MCP 里？ False
  ✅ 不在。因为 MCP 无鉴权，写操作必须留在本地
```

---

## 30.7 面试问答

### Q1：MCP 是什么？和 Function Calling 有什么区别？

**答**：MCP 是 Anthropic 开源的一个协议，定义 AI 应用如何连接外部工具和数据源，目标是让"N 个应用 × M 个工具"从 N×M 次适配变成 N+M 次实现。

**和 Function Calling 是上下游关系，不是竞争关系**：
- **Function Calling 解决"模型 ↔ 应用"**：让模型表达"我想调工具"的意图
- **MCP 解决"应用 ↔ 工具"**：让应用发现并调用外部工具

链路是：模型用 Function Calling 说"我要调 search_lab_docs" → 应用通过 MCP 去调用 → MCP Server 执行并返回。

关键推论：**不用 MCP 也能做 Agent**（本项目 MCP 不可用时就用本地工具）；**用了 MCP 也不代表模型直接调 MCP**——中间必须经过适配器把 MCP 工具转换成本地工具对象，再 `bind_tools` 给模型。模型完全不知道 MCP 的存在。

### Q2：为什么只把读工具放进 MCP？

**答**：因为 **MCP Server 是无鉴权的**。

它是跨进程的公开协议服务，拿不到请求级的数据库会话和用户身份。如果在 MCP 里暴露"创建预约"，等于**任何能访问这个端口的人都能以任意身份预约任何实验室**。

所以我们的安全边界是：**需要知道"是谁在做"的操作必须留在有鉴权的本地 Agent 里**（通过闭包拿到真实的 `current_user`），只有无鉴权要求的读工具才放进 MCP。

### Q3：MCP 挂了怎么办？

**答**：降级到本地工具。

`build_tools` 里先尝试加载 MCP 工具，失败或返回空就用本地实现的同名工具（`search_lab_docs`、`list_open_labs`、`list_lab_equipments`）。用户完全无感知。

而且用 `_mcp_cache["tried"]` 标记"已经试过了"——失败后**永久降级**，不每次请求都去连一个已知不可用的服务。

**这里我要主动指出一个不一致**：MCP 版的 `search_lab_docs` 没有接 `include_uploaded` 参数（固定搜全库），而本地版支持 `document_id` 过滤。所以 MCP 启用时，"是否包含上传文档"这个开关不生效。这是接口设计时的简化——更好的做法是在 MCP 工具里加一个可选的 `scope` 参数。

### Q4：MCP 的传输方式有哪些？你们用的什么？

**答**：三种。**stdio**（子进程，通过标准输入输出，Claude Desktop 常用）、**SSE**（HTTP + Server-Sent Events，旧的远程方案）、**streamable-http**（新的远程标准）。

我们用 `streamable-http`，绑在 `127.0.0.1:8100`——**只监听本地**，不对外暴露（配合"只放读工具"的安全策略）。

### Q5：那个 MCP 加载的 bug 是什么？

**答**：原实现用 `asyncio.get_running_loop()` 探测"当前是否在 async 上下文"，如果在就返回 None（因为同步函数没法 await）。

问题是 `build_tools` 是在 async 的 `build_agent` 里调用的，**永远**能拿到 running loop，所以 MCP 工具**永远加载不到**；而非流式路径可能不在 async 上下文反而能加载——造成流式和非流式行为不一致。

修复是把整条链改成 async（`build_tools` 和 `_load_mcp_tools` 都改 `async def`），直接 `await`。

教训：**不要用运行时探测判断"能不能 await"**。能不能 await 是写代码时就确定的（你是不是在 async 函数里）。正确做法是把整条调用链改成 async。

### Q6：MCP 的工程代价是什么？值得吗？

**答**：代价有五个：多一个进程要运维、每次调用多一次网络往返、多一个失败点、无鉴权（所以只能放读工具）、库版本 API 变动频繁（要锁版本）。

值不值得看场景。对我们这个项目，**MCP 的价值更多是架构展示和跨应用复用能力**——同一个 MCP Server 可以被 Claude Desktop、其他 Agent 接入，不用重写。但单就本项目而言，本地工具完全够用，MCP 是"锦上添花"。

诚实的说法：如果只是为了本项目，引入 MCP 的收益有限；它的价值在于**工具的一次实现、多处复用**。

---

## 30.8 速记卡

> **MCP = AI 应用的 USB-C。Function Calling 管"模型说要用"，MCP 管"应用去找/调工具"。**

**三角色**：Host（应用）/ Client（连接器）/ Server（工具提供方）

**三能力**：Tools ✅ / Resources ❌ / Prompts ❌（本项目只用 Tools）

**★ 与 Function Calling 的关系**：**上下游，不是竞争**
```
模型 --[Function Calling]--> 应用 --[MCP]--> Server --> 资源
```

**★ 安全边界**：**MCP 无鉴权 → 只放读工具**；写操作留本地（闭包拿 `current_user`）

**传输**：stdio / SSE / **streamable-http**（本项目，绑 127.0.0.1）

**适配器**：`MultiServerMCPClient.get_tools()` → 包装成 LangChain `StructuredTool` → 和本地工具同构 → 混在一起 `bind_tools`

**降级**：MCP 不可用 → 本地同名工具（用户无感知）+ `tried` 标记永久降级

**⚠️ 不一致**：MCP 版检索没有 `include_uploaded` 参数 → 开关失效

**代码位置**：
- Server：`app/mcp_server.py`（103 行）
- Client：`agent_tools.py:32-65`
- 组装：`agent_tools.py:187-198`

---

## 30.9 延伸思考

1. **如果 MCP Server 要支持鉴权，你会怎么设计？**
   提示：MCP 协议本身没有定义鉴权，需要自己加。方案：① 在 HTTP header 里带 token（但 MCP 客户端要支持传 header）；② 用 OAuth（MCP 规范里有草案）；③ **不在 MCP 层做，而是在 MCP Server 前面加一层网关**做鉴权和审计。第三种最实用。

2. **MCP 工具返回大段文本时，跨进程传输的开销值得关注吗？**
   提示：本地回环（127.0.0.1）传输 10KB 几乎无感（< 1ms）。但如果 MCP Server 在远程，且工具返回 100KB（大段检索结果），就要考虑——这也是"上下文工程"（第 19 章）要考虑的：工具返回应该截断。

3. **如果同一份工具既有 MCP 版又有本地版，怎么保证行为一致？**
   提示：**用同一份实现**——让 MCP Server 和本地工具都调用同一个 service 函数（本项目的 `kb_service.search` 就是这么做的 ✅）。差异只在"能否拿到请求级参数"。更彻底的方案是：让 MCP 工具成为唯一实现，本地也通过 MCP 调用（但会引入网络依赖，且拿不到鉴权）。

---

**下一章**：第 31 章 · SSE 流式——打字机效果怎么实现？半包、断包、`[DONE]` 怎么处理？
