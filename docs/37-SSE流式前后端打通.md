# 37 · SSE 流式输出前后端打通

> **速成定位**：AI 应用的用户体验命门。面试官问「你的流式怎么做的」「半包怎么处理」「为什么不用 EventSource」，这一篇全答。
> **一句话**：后端用 `StreamingResponse` 按 `data: {json}\n\n` 逐帧推送结构化事件；前端用 `fetch + getReader` 手动解析，配合缓冲区处理半包。

---

## 目录

1. [为什么必须流式](#1-为什么必须流式)
2. [SSE 协议格式](#2-sse-协议格式)
3. [为什么不用 EventSource](#3-为什么不用-eventsource)
4. [后端：StreamingResponse](#4-后端streamingresponse)
5. [事件协议设计](#5-事件协议设计)
6. [前端：fetch + ReadableStream](#6-前端fetch--readablestream)
7. [半包问题的三种处理](#7-半包问题的三种处理)
8. [Markdown 渲染与 XSS 防护](#8-markdown-渲染与-xss-防护)
9. [最小可运行骨架](#9-最小可运行骨架)
10. [项目里对应哪块代码](#10-项目里对应哪块代码)
11. [面试高频问答](#11-面试高频问答)
12. [速记卡](#12-速记卡)

---

## 1. 为什么必须流式

大模型生成一段回答要 5~30 秒。如果非流式：

```text
用户点发送 → 白屏等待 15 秒 → 整段答案突然出现
```

用户体验是「卡死了」。流式：

```text
用户点发送 → 0.5 秒出第一个字 → 逐字滚动 → 15 秒完成
```

**对 Agent 更关键**：Agent 中间要调工具（检索、查库、等审批）。流式可以把**过程**也推给用户：

```text
正在思考… → 正在检索实验室知识库… → 检索完成 → 正在提交预约… → 需要您确认
```

没有流式，用户完全不知道 Agent 在干什么，尤其是在等人工审批时会以为卡死。

---

## 2. SSE 协议格式

**SSE = Server-Sent Events**，本质是「HTTP 长连接 + 纯文本流」。

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {"type":"token","content":"你"}

data: {"type":"token","content":"好"}

data: {"type":"done"}
```

三条规则：

1. 每条消息以 `data: ` 开头；
2. **消息之间用空行（`\n\n`）分隔**；
3. 流式结束可发 `data: [DONE]`（本项目自己也兼容这个约定）。

**本项目用 JSON 而不是纯文本**：因为要同时传「类型、内容、工具名、预览」等多种字段，JSON 结构化最清晰。

---

## 3. 为什么不用 EventSource

浏览器原生有 `EventSource` API，但本项目**没用它**，原因很实在：

| 限制 | 说明 |
| --- | --- |
| ❌ 只能 GET | 对话请求要 POST 带消息体和 thread_id |
| ❌ 不能带自定义请求头 | 本项目需要 `Authorization: Bearer <token>` |
| ❌ 不能传请求体 | 同上 |

所以必须用 **`fetch` + 手动解析 `ReadableStream`**。

> **面试话术**：「`EventSource` 只支持 GET 且不能自定义请求头，而我的接口要 POST 传消息体、要带 JWT。所以用 fetch 手动解析流——顺带也获得了对半包和异常格式的完全控制权。」

---

## 4. 后端：StreamingResponse

`api/ai.py:82-105`：

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
            "Cache-Control": "no-cache",          # 禁止浏览器缓存
            "Connection": "keep-alive",           # 保持长连接
            "X-Accel-Buffering": "no",            # ★ 禁止 Nginx 缓冲，否则流式变"一次性"
        },
    )
```

**三个响应头都要能解释**：

| 头 | 作用 |
| --- | --- |
| `Cache-Control: no-cache` | 不让浏览器/代理缓存响应 |
| `Connection: keep-alive` | 保持长连接 |
| **`X-Accel-Buffering: no`** | **关键**：告诉 Nginx 不要缓冲响应。生产环境不加这个，Nginx 会把整个响应攒够再发，流式直接失效 |

> `X-Accel-Buffering` 是个很实用的知识点，说出来能证明你真部署过。

**为什么路由必须是 `async def`**：`event_gen()` 是异步生成器，内部 `await agent_service.stream_agent(...)`。同步路由无法 `await`。

---

## 5. 事件协议设计

`agent_service.py:367-418`（`_stream_events`）产出的事件类型：

| type | 何时发 | 前端动作 |
| --- | --- | --- |
| `status` | 一开始 | 显示「正在思考…」 |
| `tool_start` | 工具开始 | 「正在检索实验室知识库…」+ 记一步 |
| `tool_end` | 工具结束 | 「检索实验室知识库完成」+ 结果预览 |
| `token` | 模型逐字输出 | 追加到气泡文本 |
| `approval_required` | 命中写库工具 | **弹审批确认框**，携带 thread_id 和 payload |
| `done` | 正常结束 | 关闭加载态 |
| `error` | 异常 | 提示错误 |

### 中断事件怎么检测（版本细节）

```python
if kind == "on_chain_stream" and event.get("name") == "LangGraph":
    chunk = (event.get("data") or {}).get("chunk") or {}
    interrupts = chunk.get("__interrupt__")
    if interrupts:
        yield {"type": "approval_required",
               "thread_id": thread_id,
               "payload": _interrupt_payload(interrupts)}
        return        # 立即结束本轮流
```

LangGraph 1.2 里，图的中断是通过 `on_chain_stream` 事件、块里带 `__interrupt__` 键来表达的。

### 一个容易忽略的过滤

```python
elif kind == "on_chat_model_stream":
    meta = event.get("metadata") or {}
    if meta.get("langgraph_node") not in (None, "agent"):
        continue        # 只接受 agent 节点的模型输出
```

**为什么**：如果将来接入查询改写、摘要等其它模型调用，它们的输出**不能**混进对话气泡。按 `langgraph_node` 元数据过滤。

---

## 6. 前端：fetch + ReadableStream

`frontend/src/api/ai.js:22-76`：

```js
const res = await fetch(`${baseURL}${path}`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  },
  body: JSON.stringify(data)
})

// 状态码检查
if (res.status === 401) throw new Error('登录已失效，请重新登录')
if (!res.ok || !res.body) throw new Error('流式接口请求失败')

// 内容类型检查：后端可能返回的是错误 JSON 而不是流
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
  buffer += decoder.decode(value, { stream: true })

  const chunks = buffer.split('\n\n')
  buffer = chunks.pop() || ''        // ★ 最后一段可能不完整，留到下次

  for (const chunk of chunks) {
    const line = chunk.split('\n').map(i => i.trim())
                      .find(i => i.startsWith('data:'))
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
```

---

## 7. 半包问题的三种处理

**半包**：网络一次 `read()` 拿到的数据不一定正好是一条完整消息，可能是一条消息的一半，也可能包含 3.5 条。

本项目用了**三重防护**：

### 防护 1：缓冲区 + `pop()`

```js
const chunks = buffer.split('\n\n')
buffer = chunks.pop() || ''     // 最后一段不完整，留着
```

`split('\n\n')` 后，最后一段通常是「还没发完的半条」，**不能解析**，要留在 buffer 里等下一帧拼上。

### 防护 2：`TextDecoder` 的 `stream: true`

```js
buffer += decoder.decode(value, { stream: true })
```

**为什么关键**：中文是多字节 UTF-8，一个「你」占 3 字节。如果一次 `read()` 正好切在中间，不带 `stream: true` 会解出乱码。`stream: true` 让解码器**记住未完成的字节序列**，下次接着解。

> 这是中文环境下最容易踩的坑，面试讲出来很加分。

### 防护 3：`JSON.parse` 的 try/catch

```js
try { onEvent(JSON.parse(raw)) } catch { /* 跳过，等下一帧 */ }
```

脏数据或半包时不崩溃，跳过等下一帧。

---

## 8. Markdown 渲染与 XSS 防护

AI 返回的内容含 Markdown，前端要渲染成 HTML：

```js
const parseMarkdown = (text) => {
  if (!text) return ''
  marked.setOptions({ breaks: true })
  const rawHtml = marked.parse(text)
  return DOMPurify.sanitize(rawHtml)      // ★ 必须净化
}
```

**为什么必须 DOMPurify**：

AI 输出的内容**不可信**——它可能来自用户上传的文档（RAG 检索到的内容），攻击者可以上传含恶意 HTML/JS 的文档，诱导 AI 输出，进而**在你的页面上执行脚本**（存储型 XSS + 提示注入的组合攻击）。

`marked` 只负责 Markdown → HTML，不做安全过滤；`DOMPurify` 负责剔除 `<script>`、`onerror` 等危险内容。**两者必须配合**。

> **面试话术**：「RAG 场景下 AI 输出的内容可能来自用户上传的文档，属于不可信输入。所以 Markdown 渲染必须经过 DOMPurify 净化，否则就是一个存储型 XSS 入口。」

---

## 9. 最小可运行骨架

**后端**（`pip install fastapi uvicorn`，存为 `mini_sse.py`）：

```python
"""最小骨架：SSE 流式后端。模拟 Agent 的「思考 → 调工具 → 逐字输出」全过程。"""

import asyncio
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


def sse_line(payload: dict) -> str:
    """拼一条 SSE 帧。★ 必须以 \n\n 结尾，这是 SSE 的消息分隔符。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def agent_events():
    """模拟 Agent 的事件流：状态 → 工具开始/结束 → 逐字 → 完成。"""
    yield sse_line({"type": "status", "message": "正在思考…"})
    await asyncio.sleep(0.3)

    # 工具调用过程（Agent 的关键价值：把中间过程也推给用户）
    yield sse_line({"type": "tool_start", "name": "search_lab_docs",
                    "label": "检索实验室知识库"})
    await asyncio.sleep(0.6)
    yield sse_line({"type": "tool_end", "name": "search_lab_docs",
                    "label": "检索实验室知识库",
                    "preview": "开放时间 8:00-22:00…"})

    # 逐字输出：这就是用户看到的"打字机"效果
    for ch in "实验室开放时间是每天 8:00 至 22:00。":
        yield sse_line({"type": "token", "content": ch})
        await asyncio.sleep(0.05)

    yield sse_line({"type": "done"})


@app.post("/chat/stream")
async def chat_stream():
    return StreamingResponse(
        agent_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",     # ★ 禁 Nginx 缓冲，否则流式失效
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

**前端**（保存为 `mini_sse.html`，用浏览器打开即可，需先启动上面的后端）：

```html
<!DOCTYPE html>
<html lang="zh">
<body>
  <button onclick="start()">发送</button>
  <pre id="out" style="white-space:pre-wrap"></pre>

<script>
async function start() {
  const out = document.getElementById('out')
  out.textContent = ''
  const res = await fetch('http://127.0.0.1:8000/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ messages: [] })
  })
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''            // ★ 缓冲区：存放不完整的半包

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    // ★ stream:true 让解码器记住被截断的多字节字符（中文一个字 3 字节）
    buffer += decoder.decode(value, { stream: true })

    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''          // ★ 最后一段可能不完整，留到下次

    for (const chunk of chunks) {
      const line = chunk.split('\n').map(s => s.trim())
                        .find(s => s.startsWith('data:'))
      if (!line) continue
      const raw = line.slice(5).trim()
      if (!raw || raw === '[DONE]') continue
      try {
        const evt = JSON.parse(raw)
        if (evt.type === 'token') out.textContent += evt.content
        else if (evt.type === 'status') out.textContent += `[${evt.message}]\n`
        else if (evt.type === 'tool_start') out.textContent += `[正在${evt.label}…]\n`
        else if (evt.type === 'tool_end') out.textContent += `[${evt.label}完成]\n`
      } catch {
        // 半包或脏数据：跳过，等下一帧
      }
    }
  }
}
</script>
</body>
</html>
```

**预期的逐字效果**：

```text
[正在思考…]
[正在检索实验室知识库…]
[检索实验室知识库完成]
实验室开放时间是每天 8:00 至 22:00。   ← 逐字出现
```

---

## 10. 项目里对应哪块代码

### 后端

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| SSE 帧拼接 | `api/ai.py:77-79` | `_sse_line` → `data: {json}\n\n` |
| 流式接口 | `api/ai.py:82-105` | `chat_stream` + 三个响应头 |
| 流式恢复 | `api/ai.py:108-133` | `chat_stream_resume`（审批后继续） |
| 非流式 | `api/ai.py:25-46` | `chat`（含 `ApprovalRequired` 捕获） |
| 事件生成 | `agent_service.py:367-418` | `_stream_events` |
| 中断检测 | `agent_service.py:377-386` | `on_chain_stream` + `__interrupt__` |
| 工具事件 | `agent_service.py:388-404` | `on_tool_start` / `on_tool_end` |
| token 过滤 | `agent_service.py:405-411` | 只取 `agent` 节点的输出 |
| 流式入口 | `agent_service.py:421-441` | `stream_agent` / `resume_stream_agent` |
| 结果预览 | `agent_service.py:359-364` | `_tool_output_preview`（截断 200 字） |

### 前端

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| **流式解析** | `api/ai.js:22-76` | fetch + getReader + 缓冲区 |
| 半包处理 | `api/ai.js:57-58 / 70-72` | `pop()` 留半包 + try/catch 跳过 |
| UTF-8 解码 | `api/ai.js:55` | `decoder.decode(value, {stream:true})` |
| 401 处理 | `api/ai.js:35-37` | 抛「登录已失效」 |
| 事件应用 | `views/AIChat.vue` | `applyStreamEvents` 按 type 更新 UI |
| **XSS 防护** | `views/AIChat.vue` | `DOMPurify.sanitize(marked.parse(text))` |
| thread_id | `views/AIChat.vue` | `crypto.randomUUID()` 一个会话一个 |
| 工具中文名 | `views/AIChat.vue` | `TOOL_LABELS` |
| 审批确认框 | `views/AIChat.vue` | `ElMessageBox` 确认后调 resume |

---

## 11. 面试高频问答

**Q1：为什么用 SSE 不用 WebSocket？**
> 对话是**单向**的：客户端发一次请求，服务端持续推送。WebSocket 是双向全双工，用在聊天场景是过度设计——要处理心跳、重连、连接状态管理。SSE 基于普通 HTTP，天然穿透代理和防火墙，实现简单，还能自动利用 HTTP 的压缩。

**Q2：为什么不用浏览器原生的 EventSource？**
> 三个硬限制：`EventSource` 只支持 GET、不能自定义请求头、不能带请求体。而我的接口要 POST 传消息内容，还要带 `Authorization: Bearer <token>`。所以用 `fetch` 手动读 `ReadableStream`——顺便获得了对半包和异常格式的完全控制权。

**Q3：半包问题怎么处理的？**
> 三重防护：① 用缓冲区累积，`split('\n\n')` 后把最后一段 `pop()` 出来留着，因为它是没发完的半条；② `TextDecoder` 传 `stream: true`，让解码器记住被截断的多字节字符——**中文一个字 3 字节，切在中间不解这个会出乱码**；③ `JSON.parse` 包 try/catch，脏数据跳过等下一帧。

**Q4：`X-Accel-Buffering: no` 是干什么的？**
> 告诉 Nginx 不要缓冲响应。生产环境如果不加，Nginx 默认会把整个响应攒够再一次性发给客户端，流式就退化成「等 15 秒突然全出来」。这是部署时才暴露的坑。

**Q5：流式接口报错了怎么提示？**
> 两层：① 检查 HTTP 状态码（401 → 登录失效）；② 检查 `content-type` 是不是 `text/event-stream`——如果后端抛异常返回了普通 JSON，这里能识别出来并解析出错误信息，而不是当成流去读导致白屏。

**Q6：审批中断在流式里怎么体现？**
> 后端检测到 `__interrupt__` 后推一条 `type: "approval_required"` 事件（携带 thread_id 和工具参数），然后立即结束本轮流。前端收到后弹确认框，用户点确认再用 `chatStreamResumeApi` 带上 thread_id 和 approved 重新发起流式请求，从断点继续。

**Q7：为什么 `on_chat_model_stream` 要过滤节点？**
> 因为将来可能接入查询改写、摘要等其它模型调用，它们的输出不能混进对话气泡。用 `metadata.langgraph_node` 判断，只接受 `agent` 节点的输出。

**Q8：AI 输出渲染成 HTML 有什么风险？**
> 存储型 XSS。RAG 场景下 AI 的输出可能来自用户上传的文档，攻击者可以上传含恶意脚本的文档诱导 AI 输出。`marked` 只做 Markdown 转 HTML 不过滤，所以必须过一遍 `DOMPurify.sanitize()` 剔除 `<script>`、`onerror` 等。

**Q9：流式接口怎么做鉴权和限流？**
> 和普通接口一样用依赖注入：`Depends(get_current_user)` 解析 JWT，`Depends(ai_rate_limiter)` 用 Redis 做每分钟 20 次的限流。因为是普通 HTTP 请求，鉴权流程完全复用。

**Q10：连接断了怎么办？**
> 目前是让流自然结束，前端 `done` 后关闭加载态。如果要做断线重连，可以利用 checkpointer 的 thread_id——重连时用同一个 thread_id 就能拿到断点前的状态继续。这是 checkpointer 带来的额外好处。

---

## 12. 速记卡

```text
为什么流式：大模型 5~30s，白屏不可接受
           Agent 更要推"过程"（思考/调工具/等审批）

SSE 格式：data: {json}\n\n  ← ★空行是消息分隔符
         结束可发 data: [DONE]

不用 EventSource：只 GET / 不能自定义头 / 不能带 body
                 → 用 fetch + getReader

后端三响应头：
  Cache-Control: no-cache
  Connection: keep-alive
  ★X-Accel-Buffering: no  ← 禁 Nginx 缓冲，否则流式失效
  路由必须 async def（异步生成器要 await）

事件协议：
  status / tool_start / tool_end / token / approval_required / done / error
  中断 = on_chain_stream 里 chunk["__interrupt__"]
  过滤 metadata.langgraph_node == "agent"，避免其它模型输出混入

前端半包三重防护：
  ① buffer.split('\n\n') 后 pop() 留半包
  ② TextDecoder(stream:true) ← 中文 3 字节截断会乱码
  ③ JSON.parse 包 try/catch 跳过脏数据

安全：marked(转HTML) + DOMPurify(净化) ← RAG 输出不可信，防存储型 XSS

断点续传：approve 后带同一 thread_id 再发起流式 resume
```
