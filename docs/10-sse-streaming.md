# 10 · SSE 流式输出与过程可见

## 1. 为什么需要 SSE？

普通 HTTP 请求要等后端全部算完才返回。但 Agent 可能多轮调工具、生成长文本，
用户只能干等。

SSE（Server-Sent Events）让服务器持续推送数据：

```text
HTTP/1.1 200
Content-Type: text/event-stream

data: {"type":"status","message":"正在思考…"}

data: {"type":"token","content":"你好"}
```

浏览器边收边渲染，体验像 ChatGPT 打字机。

## 2. SSE 和 WebSocket 的区别

| | SSE | WebSocket |
| --- | --- | --- |
| 方向 | 服务器 -> 客户端单向 | 双向 |
| 协议 | HTTP | 独立协议 |
| 实现 | 简单 | 复杂 |
| 场景 | 推送进度、流式回答 | 聊天、实时协作 |

AI 助手主要是服务器持续输出，SSE 足够。

## 3. 后端如何实现 SSE？

FastAPI 使用 `StreamingResponse`：

```python
def event_gen():
    for event in agent_service.stream_agent(db, current_user, data):
        yield _sse_line(event)

return StreamingResponse(event_gen(), media_type="text/event-stream")
```

关键规则：

- 每条消息以 `data:` 开头。
- 以空行 `\n\n` 结束。
- 中文用 `ensure_ascii=False`，避免变成 `\uXXXX`。

## 4. LangGraph 如何输出过程事件？

`agent.stream_events(version="v2")` 会冒出各种内部事件：

- `on_tool_start`：工具开始执行。
- `on_tool_end`：工具执行结束。
- `on_chat_model_stream`：模型逐字输出。

我们把它们转换成前端好理解的事件：

```python
yield {"type": "tool_start", "label": "查询开放实验室"}
yield {"type": "token", "content": "好的"}
yield {"type": "done"}
```

## 5. 为什么要处理半个汉字？

TCP 会把流拆成不定长的字节块。如果直接解码，可能把“实验”拆成两个不完整字节。
前端用 `TextDecoder` 和 buffer：

```js
buffer += decoder.decode(value, { stream: true })
```

`stream: true` 告诉解码器“后面还有字节”，让它暂存不完整的汉字。

## 6. 为什么不用 EventSource？

浏览器原生 `EventSource` 只支持 GET，不能自定义 `Authorization` 头。
本项目需要 JWT，所以用 `fetch` + `ReadableStream`：

```js
const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
const reader = res.body.getReader()
```

## 7. 常见坑

- **代理缓冲**：Nginx 或 Vite 代理可能把 SSE 缓冲成一大段，导致过程事件延迟。要设置
  `X-Accel-Buffering: no` 和 `Cache-Control: no-cache`。
- **错误不是 SSE**：后端若在流开始后抛普通 JSON，前端解析会失败。所以生成器内部错误
  也 `yield {"type":"error"}`。
- **正文重复**：`token` 已经拼出全文，`done` 不要再附完整正文。
- **响应式丢失**：流式更新字段必须用 `reactive`。

## 8. 检查清单

- SSE 的消息格式是什么？
- 为什么前端用 fetch 而不是 EventSource？
- `stream: true` 在 TextDecoder 里解决什么问题？
- Agent 的工具开始/结束事件从哪里来？
