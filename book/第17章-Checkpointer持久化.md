# 第 17 章 · Checkpointer 持久化：重启服务后对话为什么还在

> **这一章要回答的核心问题**：多轮对话的历史存在哪里？为什么刷新页面、重启服务后 Agent 还记得前面聊了什么？`thread_id` 是什么、从哪来、怎么隔离？SQLite 和 PostgreSQL 两种后端怎么选？

---

## 17.1 引子：一个让 ChatBot 露馅的瞬间

你和用户聊到第五轮：

```
用户：显微镜实验室在哪？
Agent：在实验楼 A 座 301。
用户：里面有什么设备？
Agent：有扫描电镜、离心机……
用户：离心机明天下午有空吗？
Agent：（需要先知道是"哪个实验室"的离心机）
```

第三轮的"离心机"依赖第二轮的上下文。如果你的实现是"前端每轮把完整历史回传给后端"，那没问题。但如果后端是无状态的呢？Agent 会一脸茫然："请问您指的是哪个实验室的离心机？"

**用户会觉得这个助手很蠢。** 而这就是没有状态持久化的直接后果。

再看一个更致命的场景——第 16 章的审批流程：

```
1. 用户："帮我预约明天下午的显微镜实验室"
2. Agent 决定调 create_lab_reservation → interrupt 暂停
3. 后端返回 approval_required + thread_id
4. 前端弹确认框
5. 用户点"确认" → 前端调 /ai/chat/resume
6. 后端从断点继续，执行预约
```

**第 6 步凭什么知道要执行什么？** 它必须"记得"第 2 步时模型生成的那个 `tool_call`（包含 lab_id、date、start_time、end_time）。如果状态丢了，后端根本不知道要预约什么。

**这就是 Checkpointer 存在的根本理由**：它不只是"记住聊天记录"，更是**中断恢复机制的物理基础**。没有持久化，就没有真正的 Human-in-the-Loop。

---

## 17.2 Checkpointer 到底存了什么

### 17.2.1 一次 ainvoke 背后发生了什么

当你调用：

```python
result = await agent.ainvoke(inputs, {"configurable": {"thread_id": "t-1"}})
```

LangGraph 的执行流程是：

```
1. 从 checkpointer 读取 thread_id="t-1" 的最新 checkpoint
   ├─ 有 → 加载为初始 state
   └─ 无 → 用你传的 inputs 作为初始 state

2. 执行超步 1（agent 节点）
   → 节点返回增量 → Reducer 合并 → 得到新 state
   → ★ 写 checkpoint（版本 n+1）

3. 执行超步 2（approval 节点）
   → ★ 写 checkpoint（版本 n+2）

4. ... 直到 END 或 interrupt 或 recursion_limit

5. 返回最终 state
```

**关键在第 2、3 步后面的"写 checkpoint"**——这是自动的，你不需要写任何代码。

### 17.2.2 checkpoint 的数据结构

LangGraph 的 checkpoint 大致长这样（SQLite 后端实际表结构会略有差异，但语义相同）：

```python
{
    "thread_id": "t-1",
    "checkpoint_ns": "",              # 命名空间（子图用）
    "checkpoint_id": "1ef8a...",      # 本次快照的唯一 ID
    "parent_checkpoint_id": "1ef7b...",  # 父快照 → 形成版本链
    "checkpoint": {
        "v": 1,
        "ts": "2026-10-17T12:00:00Z",
        "id": "1ef8a...",
        "channel_values": {           # ★ 真正存的状态
            "messages": [ ... 序列化的消息列表 ... ],
            "approval": {"approved": True},
        },
        "channel_versions": {         # 每个字段的版本号，用于增量更新
            "messages": 5,
            "approval": 2,
        },
        "pending_sends": [],
    },
    "metadata": {
        "source": "loop",             # 来源：input / loop / update
        "step": 3,                    # 第几个超步
        "writes": {"agent": {"messages": [...]}},  # 本步写了什么
    },
}
```

三个值得注意的设计：

**① 版本链（parent_checkpoint_id）**

每个 checkpoint 指向它的父快照，形成一条链。这让 LangGraph 能做**时间旅行（time travel）**——你可以回到任意历史版本重新执行。

```python
# 查看某线程的全部历史快照
history = list(graph.get_state_history({"configurable": {"thread_id": "t-1"}}))
for snap in history:
    print(snap.config["configurable"]["checkpoint_id"], snap.values["messages"][-1].content)
```

**② channel_versions（增量更新）**

记录每个字段的版本号。这样 LangGraph 能判断"哪些字段变了"，只更新需要的部分。

**③ metadata.writes**

记录这一步是哪个节点写的、写了什么。这是可观测性的基础——你能精确知道每一步发生了什么。

### 17.2.3 存的是"完整 state"，不是"增量"

这一点很重要：**每个 checkpoint 都存了完整的 `channel_values`**（不是 diff）。

这意味着：

- ✅ 恢复时是 O(1)，不需要重放历史
- ❌ 存储会膨胀——对话越长，每个 checkpoint 越大，而且是**每个超步都存一份**

假设一轮对话 10 个超步、最终 state 50KB，那就是 **500KB**。1000 个会话就是 500MB。

> ⚠️ **坑 1（真实且重要）**：这是 checkpointer 最容易踩的坑——**存储膨胀**。
> 本项目的 `_trim_messages`（第 19 章）主要目的是控制 token，但它**同时也缓解了存储膨胀**。不过要注意：裁剪只影响**送入模型的消息**，不影响 state 里存的消息。要彻底解决，需要在写入 state 时就限制（比如只保留最近 20 条），或者定期清理旧 checkpoint。
> 这是可以写进简历的一个优化点。

---

## 17.3 thread_id：会话身份的锚点

### 17.3.1 它是什么

`thread_id` 是 checkpointer 用来**区分不同会话**的唯一标识。同一个 `thread_id` 的多次 `ainvoke` 共享同一条状态链。

```python
{"configurable": {"thread_id": thread_id}}
```

你可以把它理解为**数据库里的主键**——checkpointer 表的主键就是 `(thread_id, checkpoint_ns, checkpoint_id)`。

### 17.3.2 它从哪来？（本项目完整链路）

**后端兜底生成**（`api/ai.py:21-32`）：

```python
def _new_thread_id() -> str:
    return uuid.uuid4().hex

@router.post("/chat")
async def chat(data: ChatRequest, ...):
    thread_id = data.thread_id or _new_thread_id()
```

如果前端没传，后端用 `uuid4().hex` 生成一个 32 位十六进制串。

**前端生成并维护**（`AIChat.vue:79-84`）：

```javascript
// 一个页面会话一个 thread_id，后端 checkpointer 用它隔离和恢复多轮状态。
const threadId = ref(
  (typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Date.now().toString(36) + Math.random().toString(36).slice(2))
)
```

前端优先用 `crypto.randomUUID()`（现代浏览器原生 API），老浏览器降级到时间戳 + 随机数。

**为什么前端生成而不是后端生成？**

因为**前端需要在多轮对话中复用同一个 thread_id**，而前端是无状态的（刷新页面就没了）。所以：

1. 页面加载时生成一个，存进 `ref`
2. 每轮请求带上它
3. 后端用它读写 checkpoint

如果用户刷新页面，`threadId` 会重新生成 → **新会话**。这是当前设计的行为（"一个页面会话一个 thread_id"），符合直觉。

> 📝 **可改进点**：如果想让刷新后还能接着聊，需要把 thread_id 存进 `localStorage` 或后端用户表。后者更好（支持多设备同步），但需要新增一张会话表。这是一个很好的简历优化项。

### 17.3.3 thread_id 与用户隔离

**本项目的一个安全隐患**：`thread_id` 由前端提供，而后端**没有校验这个 thread_id 是否属于当前用户**。

也就是说，理论上用户 A 可以拿着用户 B 的 thread_id 发请求，读到 B 的对话历史（如果他猜到了 UUID——实际上很难猜，但不能依赖"难猜"做安全）。

**正确的做法是**：把用户身份编码进 thread_id，或者存一张会话表做归属校验。

```python
# 方案 1：把用户 ID 编进 thread_id
thread_id = f"u{current_user.id}-{uuid4().hex}"

# 方案 2：查会话表校验归属（推荐，还能支持"历史会话列表"功能）
```
> ⚠️ **这是一个真实的待改进项**。面试时如果被问到"多用户下状态怎么隔离"，你可以先说现状（thread_id 由前端提供、UUID 随机性保证实际安全），再说改进方案（会话表 + 归属校验），并说明为什么当前没做（单用户/内网场景够用）。诚实 + 有方案，比假装完美得分高。

### 17.3.4 checkpoint_ns：子图的命名空间

如果你用了子图（subgraph），LangGraph 会自动用 `checkpoint_ns` 区分父子图的状态。本项目没用到，知道这个概念即可。

---

## 17.4 两种后端：SQLite vs PostgreSQL

### 17.4.1 本项目的实现（`agent_service.py:110-144`）

```python
async def get_checkpointer():
    """懒加载全局 checkpointer。
    - 配置了 CHECKPOINT_DATABASE_URL → AsyncPostgresSaver（会话状态与业务库同源）。
    - 否则 → AsyncSqliteSaver（本地文件，零配置）。
    """
    global _checkpointer, _checkpointer_cm
    if _checkpointer is not None:
        return _checkpointer

    if settings.CHECKPOINT_DATABASE_URL:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(
            settings.CHECKPOINT_DATABASE_URL
        )
        _checkpointer = await _checkpointer_cm.__aenter__()
        await _checkpointer.setup()
        logger.info("checkpointer 已就绪：PostgreSQL")
    else:
        path = Path(settings.CHECKPOINT_DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(path))
        _checkpointer = await _checkpointer_cm.__aenter__()
        logger.info("checkpointer 已就绪：SQLite（%s）", path)
    return _checkpointer
```

### 17.4.2 四个设计点

**① 全局单例 + 懒加载**

```python
global _checkpointer, _checkpointer_cm
if _checkpointer is not None:
    return _checkpointer
```

checkpointer 持有**连接池**，必须复用。如果每次请求都创建，很快会耗尽数据库连接。

**为什么是"懒加载"而不是启动时初始化？** 因为它是 `async` 的，而 FastAPI 的模块导入是同步的。放在 lifespan 里初始化也行，但懒加载更简单——第一次请求时初始化，后续复用。

**② 为什么存两个全局变量**

```python
_checkpointer_cm = AsyncPostgresSaver.from_conn_string(url)   # 上下文管理器
_checkpointer = await _checkpointer_cm.__aenter__()            # 真正的 saver
```

因为 `from_conn_string()` 返回的是一个**异步上下文管理器**，`__aenter__()` 返回的才是可用的 saver 对象。而关闭时需要调用 `__aexit__()`：

```python
async def close_checkpointer() -> None:
    """应用关闭时释放 checkpointer 连接。"""
    global _checkpointer, _checkpointer_cm
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
        _checkpointer_cm = None
        _checkpointer = None
```

这个函数在 FastAPI 的 `lifespan` shutdown 阶段调用，保证**优雅关闭**（不丢连接、不写坏数据）。

> ⚠️ **坑 2（真实）**：如果你只存 `_checkpointer` 而不存 `_checkpointer_cm`，关闭时无法正确释放连接。进程退出时可能留下僵尸连接，PG 侧会看到 `idle in transaction` 的连接越积越多。

**③ `await _checkpointer.setup()`**

```python
_checkpointer = await _checkpointer_cm.__aenter__()
await _checkpointer.setup()
```

`setup()` 负责**建表**（`checkpoints`、`checkpoint_blobs`、`checkpoint_writes` 等）。它是幂等的（已存在就跳过），所以每次启动调用也安全。

注意：**SQLite 后端不需要调用 setup()**（`AsyncSqliteSaver` 内部处理）。这也是代码里把 `setup()` 放在 PG 分支的原因。

**④ 为什么要支持 PG**

| 维度 | SQLite | PostgreSQL |
|---|---|---|
| 部署形态 | 单进程 / 单容器 | 多实例 / 多容器 ✅ |
| 并发写 | 文件级写锁，串行 | MVCC，行级并发 ✅ |
| 容量 | 本地文件，受磁盘限制 | 独立服务，可扩容 ✅ |
| 备份 | 拷贝文件（有锁风险） | 标准 pg_dump ✅ |
| 运维 | 零配置 | 需要起服务 |

**核心理由是"多实例安全"**。生产环境你通常会跑多个 uvicorn worker 或多个容器（负载均衡）。SQLite 的文件锁在跨进程场景下会导致：

- 写入冲突（`database is locked`）
- 状态丢失（进程 A 写的文件，进程 B 的缓存里还是旧的）

PG 是共享存储，天然支持多实例。

### 17.4.3 双后端的工程价值（面试话术）

> "checkpointer 我做了双后端抽象：开发环境用 SQLite 零配置起步，生产环境配置 `CHECKPOINT_DATABASE_URL` 就切到 PostgreSQL。判断依据是这个环境变量有没有配。
>
> 之所以要支持 PG，是因为 SQLite 的文件锁在多 worker / 多容器部署下会冲突——生产环境 FastAPI 通常跑多个实例，状态会错乱。
>
> 实现上有两个细节：一是 checkpointer 是全局单例懒加载，因为它持有连接池，不能每次请求创建；二是它本质是异步上下文管理器，所以要同时保存管理器对象和应用关闭时的 `__aexit__` 释放，我在 FastAPI 的 lifespan shutdown 里做了优雅关闭。"

---

## 17.5 状态的读取、更新与时间旅行

### 17.5.1 查看当前状态

```python
state = await graph.aget_state({"configurable": {"thread_id": "t-1"}})
print(state.values)         # 当前 state
print(state.next)           # 下一步会执行哪些节点（重要！）
print(state.tasks)          # 待执行的任务详情
print(state.config)         # 配置
```

`state.next` 在调试 interrupt 时极其有用——它告诉你"图停在哪儿了"。

### 17.5.2 查看历史（时间旅行）

```python
async for snapshot in graph.aget_state_history({"configurable": {"thread_id": "t-1"}}):
    print(f"checkpoint: {snapshot.config['configurable']['checkpoint_id']}")
    print(f"step: {snapshot.metadata.get('step')}")
    print(f"next: {snapshot.next}")
    print(f"messages: {len(snapshot.values.get('messages', []))}")
```

**实用场景**：

1. **调试**：用户反馈"Agent 第 3 轮答错了"，你可以回溯到那一刻看它收到了什么。
2. **回放**：从某个历史 checkpoint 分叉执行（"如果当时这样，会怎样"）。
3. **审计**：合规场景需要留存完整的决策链路。

**从历史快照恢复并继续执行**：

```python
# 拿到某个历史快照
snapshots = [s async for s in graph.aget_state_history(cfg)]
target = snapshots[3]

# 从那个快照的配置继续执行
await graph.ainvoke(None, target.config)
```

### 17.5.3 手动更新状态

```python
await graph.aupdate_state(
    {"configurable": {"thread_id": "t-1"}},
    {"messages": [HumanMessage(content="补充一点：我要的是 301 实验室")]},
)
```

这在**纠正 Agent 误解**时很有用：用户说"不是这个实验室，是另一个"，你可以直接注入一条澄清消息，而不是重新走一遍。

---

## 17.6 最小骨架：亲手验证持久化

下面这个例子**可直接运行**（用假 LLM，不需要 API Key），亲眼验证"重启后状态还在"。

```python
"""
minimal_checkpoint.py —— 验证 checkpointer 持久化
运行：pip install langgraph langchain-core aiosqlite && python minimal_checkpoint.py
分两次运行：第二次注释掉 `import shutil; shutil.rmtree(...)` 那行
"""
import asyncio
import os
import shutil
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

DB_PATH = "./_ckpt_demo.sqlite"


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    turn: int


turn_counter = {"n": 0}


async def chat_node(state: State) -> dict:
    """假 LLM：记住用户说过的话，并在第二轮引用第一轮的内容。"""
    turn_counter["n"] += 1
    user_msgs = [m.content for m in state["messages"] if isinstance(m, HumanMessage)]
    reply = f"（第{turn_counter['n']}轮）我记着你说的：{' | '.join(user_msgs)}"
    return {"messages": [AIMessage(content=reply)], "turn": turn_counter["n"]}


def build(cp):
    g = StateGraph(State)
    g.add_node("chat", chat_node)
    g.add_edge(START, "chat")
    g.add_edge("chat", END)
    return g.compile(checkpointer=cp)


async def main():
    # fresh=True 时清空数据库，模拟"全新开始"
    fresh = os.environ.get("FRESH", "1") == "1"
    if fresh and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as cp:
        await cp.setup()
        graph = build(cp)
        cfg = {"configurable": {"thread_id": "demo-thread"}}

        # 模拟"第一轮对话"
        r1 = await graph.ainvoke({"messages": [HumanMessage("我叫马凯")]}, cfg)
        print(f"[轮次1] {r1['messages'][-1].content}")

    # ★ 这里完全退出上下文管理器 = 模拟"服务重启"
    print("  --- 连接已关闭（模拟服务重启）---")

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as cp:
        await cp.setup()
        graph = build(cp)
        cfg = {"configurable": {"thread_id": "demo-thread"}}

        # 第二轮：只传新消息，历史应该自动恢复
        r2 = await graph.ainvoke({"messages": [HumanMessage("我在学 LangGraph")]}, cfg)
        print(f"[轮次2] {r2['messages'][-1].content}")

        # 验证：state 里应该有 4 条消息（2 用户 + 2 AI）
        st = await graph.aget_state(cfg)
        print(f"\n[验证] state 中共有 {len(st.values['messages'])} 条消息：")
        for i, m in enumerate(st.values["messages"]):
            print(f"  [{i}] {type(m).__name__}: {m.content}")

        # 验证：换一个 thread_id 应该是全新的
        r3 = await graph.ainvoke(
            {"messages": [HumanMessage("新会话")]},
            {"configurable": {"thread_id": "another-thread"}},
        )
        print(f"\n[验证] 另一个 thread_id：{r3['messages'][-1].content}")

        # 验证：时间旅行
        print("\n[验证] 状态历史：")
        async for snap in graph.aget_state_history(cfg):
            step = snap.metadata.get("step", "?")
            n = len(snap.values.get("messages", []))
            print(f"  step={step}, messages={n}, next={snap.next}")


if __name__ == "__main__":
    asyncio.run(main())
```

**预期输出**：

```
[轮次1] （第1轮）我记着你说的：我叫马凯
  --- 连接已关闭（模拟服务重启）---
[轮次2] （第2轮）我记着你说的：我叫马凯 | 我在学 LangGraph

[验证] state 中共有 4 条消息：
  [0] HumanMessage: 我叫马凯
  [1] AIMessage: （第1轮）我记着你说的：我叫马凯
  [2] HumanMessage: 我在学 LangGraph
  [3] AIMessage: （第2轮）我记着你说的：我叫马凯 | 我在学 LangGraph

[验证] 另一个 thread_id：（第3轮）我记着你说的：新会话

[验证] 状态历史：
  step=1, messages=4, next=()
  step=0, messages=3, next=('chat',)
  step=-1, messages=2, next=()
  step=-2, messages=0, next=('chat',)
```

**四件事被验证了**：

1. ✅ **重启后历史还在**（轮次 2 能引用轮次 1 的内容）
2. ✅ **只需传新消息**（历史自动由 Reducer 追加）
3. ✅ **thread_id 隔离**（another-thread 是全新会话）
4. ✅ **历史快照链**（时间旅行可用）

---

## 17.7 项目代码定位汇总

| 功能 | 位置 | 说明 |
|---|---|---|
| 双后端选择 | `agent_service.py:110-135` | 按 `CHECKPOINT_DATABASE_URL` 判断 |
| 优雅关闭 | `agent_service.py:138-144` | `__aexit__` 释放连接 |
| config 构造 | `agent_service.py:332-333` | `thread_id` + `recursion_limit` |
| 只取新消息 | `agent_service.py:345-353` | `_build_input_messages` |
| 中断检测 | `agent_service.py:384-386` | 读 `__interrupt__` |
| thread_id 兜底 | `api/ai.py:21-32` | `uuid4().hex` |
| 前端生成 | `AIChat.vue:79-84` | `crypto.randomUUID()` |
| 配置项 | `config.py` | `CHECKPOINT_DATABASE_URL`、`CHECKPOINT_DB_PATH` |

### 配置项说明

```bash
# .env
# 不配置 → 用 SQLite（默认，零配置本地开发）
CHECKPOINT_DB_PATH=./data/checkpoints.sqlite

# 配置 → 用 PostgreSQL（生产推荐，多实例安全）
CHECKPOINT_DATABASE_URL=postgresql://user:pass@localhost:5432/lab_agent
```

---

## 17.8 存储膨胀：必须面对的问题

前面提到"每个超步存一份完整 state"会导致存储膨胀。我们来量化一下。

### 17.8.1 算一笔账

假设：
- 一轮对话平均 4 个超步
- 最终 state 约 20KB（含检索返回的知识库内容）
- 平均每个会话 10 轮对话

**单个会话的存储** ≈ 4 超步 × 10 轮 × 平均 10KB = **400KB**

**1000 个会话** = 400MB
**10000 个会话** = 4GB

而且这是**只增不减**的——旧 checkpoint 永远不会被自动删除。

### 17.8.2 四种应对策略

| 策略 | 做法 | 代价 |
|---|---|---|
| **限制历史长度** | 写入 state 时就只保留最近 N 条消息 | 丢失早期上下文 |
| **中间结果不进 state** | 大的工具结果（如检索内容）不追加到 messages，改用临时存储 | 模型看不到（需另行注入） |
| **定期清理** | 定时任务删除 N 天前的 checkpoint | 需要额外运维 |
| **只保留最新** | 配置 checkpointer 只存最新快照（丢弃版本链） | 失去时间旅行能力 |

**本项目目前没有做这些优化**，这是诚实的现状。如果要做，我推荐**组合方案**：

1. 会话结束时（或超时未活跃）清理该 thread 的全部历史 checkpoint，只保留最新
2. 对超过 30 天的 thread 整体删除
3. 检索工具的返回内容做长度截断（比如单块最多 1500 字）

> 📝 这是一个很好的简历优化点，而且能引出"你怎么估算 Agent 系统的存储成本"这类高阶问题。

---

## 17.9 面试问答

### Q1：多轮对话的历史存在哪里？

**答**：存在 checkpointer 里。LangGraph 在每个超步执行后自动把 State 序列化写入后端，关联 `thread_id`。下次用同一个 `thread_id` 调用时，框架自动加载最新 checkpoint 作为初始状态。

我们做了双后端：开发环境用 SQLite（零配置），生产环境配 `CHECKPOINT_DATABASE_URL` 切 PostgreSQL。选 PG 的核心原因是 SQLite 的文件锁在多 worker 部署下会冲突。

### Q2：为什么后端只取最后一条用户消息，不让前端传完整历史？

**答**：三个理由。

一是**单一数据源**：历史只有一个地方存（checkpoint 库），不会出现前端传的和后端存的不一致。

二是**省带宽**：长对话时前端不用每轮回传几十 KB。

三是**防篡改**：用户不能通过篡改前端传的历史来伪造上下文（比如伪造"管理员已批准"）。

代码上对应 `_build_input_messages`，它只从 `data.messages` 里筛出 role=user 的新消息。

### Q3：checkpointer 存的是增量还是全量？有什么问题？

**答**：存的是**全量 state**，不是 diff。好处是恢复 O(1)，不用重放历史；问题是**存储膨胀**——每个超步存一份，长对话的存储是线性累积的。

我算过一笔账：一轮对话 4 个超步、平均 state 10-20KB、10 轮对话，单个会话就接近 400KB，一万个会话是 4GB。而且只增不减。

应对方案有几种：限制写入 state 的消息条数、大工具结果不进 state、定期清理旧 checkpoint、只保留最新快照。我们目前还没做，但这是明确的优化方向。

### Q4：为什么 checkpointer 要做成全局单例？

**答**：因为它持有数据库连接池。如果每个请求都创建，会迅速耗尽连接，而且频繁建连销毁的性能开销很大。

实现上用 `global` 变量 + 懒加载：第一次调用时初始化，之后直接复用。它是异步上下文管理器，所以要同时保存管理器对象（`_checkpointer_cm`）和 saver 对象（`_checkpointer`），关闭时调用 `__aexit__` 释放。我在 FastAPI 的 lifespan shutdown 里做了优雅关闭。

### Q5：thread_id 怎么生成？多用户怎么隔离？

**答**：前端生成（`crypto.randomUUID()`，老浏览器降级到时间戳+随机数），每轮请求带上；后端兜底（没传就用 `uuid4().hex` 生成）。

诚实地说，当前实现**没有做归属校验**——thread_id 由前端提供，后端不验证它是否属于当前用户。实际安全靠 UUID 的随机性（猜不出来），但这不算真正的隔离。

要严格做有两种方案：一是把用户 ID 编进 thread_id（`f"u{user_id}-{uuid}"`），二是建一张会话表记录归属并在请求时校验。第二种更好，还能顺便支持"历史会话列表"功能。当前没做是因为单用户/内网场景够用。

### Q6：interrupt 之后，状态是怎么保存的？

**答**：`interrupt()` 抛出一个特殊的 `GraphInterrupt` 异常，LangGraph 捕获它后：把当前 state 写入 checkpointer（这就是它能恢复的原因），然后 `ainvoke` 正常返回，result 里带 `__interrupt__` 字段。

恢复时用 `Command(resume=用户决策)` 调用，框架加载 checkpoint，从 `interrupt()` 那一行**继续执行**，返回值就是 resume 的内容。

所以持久化是中断恢复的物理基础——没有 checkpointer 就没有真正的 Human-in-the-Loop。

---

## 17.10 速记卡

> **Checkpointer = 每个超步后自动存 state，按 thread_id 隔离，是持久化 + 中断恢复的物理基础。**

**存什么**：完整 state（不是 diff），含 `channel_values` / `channel_versions` / `metadata`

**什么时候存**：每个超步结束后（自动，无需代码）

**怎么隔离**：`{"configurable": {"thread_id": ...}}`

**三种后端**：`AsyncSqliteSaver`（开发）/ `AsyncPostgresSaver`（生产）/ `InMemorySaver`（测试）

**为什么 PG**：SQLite 文件锁在多 worker 部署下冲突

**全局单例**：持有连接池，懒加载 + lifespan 优雅关闭（`__aexit__`）

**时间旅行**：
```python
async for snap in graph.aget_state_history(cfg): ...
await graph.aupdate_state(cfg, {"messages": [...]})   # 手动改状态
```

**存储膨胀**：全量存 × 每超步 → 线性膨胀，需定期清理

**代码位置**：
- 双后端：`agent_service.py:110-135`
- 关闭：`agent_service.py:138-144`
- config：`agent_service.py:332-333`
- 只取新消息：`agent_service.py:345-353`
- thread_id 兜底：`api/ai.py:21-32`

---

## 17.11 延伸思考

1. **如果要在"历史会话列表"功能里展示每个会话的标题，你会怎么存？**
   提示：checkpoint 里只有 messages。要么单独建一张 `conversations` 表（thread_id, user_id, title, created_at），要么从第一条用户消息截取。**顺便解决了归属校验问题**。

2. **用户开了两个标签页，A 页面聊了几轮，B 页面显示落后了。怎么解决？**
   提示：本质是"前端显示"和"后端状态"不同步。可以让前端按 thread_id 从后端拉历史（新增 `/ai/history` 接口），或者用 WebSocket 推送。

3. **checkpoint 里存了检索返回的知识库原文。如果那份文档被删除了，历史会话里还引用着它——这是问题吗？**
   提示：看需求。如果是审计场景，保留原文反而是对的（快照语义）；如果希望同步更新，就不该存原文而该存引用 ID，展示时再查。这是"快照 vs 引用"的经典取舍。

---

**下一章**：第 18 章 · Human-in-the-Loop——深入 `interrupt()` 的实现原理，看"暂停-等待-恢复"这个魔法是怎么实现的。
