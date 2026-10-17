# 第 13 章 · Function Calling

## 开篇：从「文本」到「结构化动作」

第 4 章我们讲过一个大实话：

> **工具调用不是模型的某个特殊功能，它就是模型生成的一段结构化文本，被 API 服务端解析成了 JSON。**

这一章讲这个过程的**工程细节**——那些你在调试时真正会遇到的东西：

- `tool_calls` 里每个字段是干嘛的
- 为什么漏了 `tool_call_id` 会报 400
- 流式场景下 tool_calls 是**分片**来的（这是真实的大坑）
- 怎么让模型同时调多个工具

这些知识，你在「跑通 demo」时不会遇到，但在「上线」时一定会遇到。

---

## 一、完整的数据结构

### 1.1 请求：你发给 API 的

```json
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "你是实验室预约助手..."},
    {"role": "user", "content": "有哪些细胞相关的实验室？"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "search_labs",
        "description": "根据关键词搜索实验室。当用户想查找实验室时调用。",
        "parameters": {
          "type": "object",
          "properties": {
            "keyword": {
              "type": "string",
              "description": "实验室名称关键词，留空表示查询全部"
            }
          },
          "required": []
        }
      }
    }
  ],
  "tool_choice": "auto",
  "temperature": 0,
  "stream": true
}
```

**关键字段**：

| 字段 | 作用 |
|---|---|
| `tools` | 工具定义数组，每个是 JSON Schema |
| `tool_choice` | 控制模型是否必须调工具（见第三节） |
| `parallel_tool_calls` | 是否允许一次调多个 |

### 1.2 响应：API 返回给你的（非流式）

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,                    // ← 注意！调工具时 content 通常是 null
      "tool_calls": [
        {
          "id": "call_abc123",            // ← 工具调用的唯一 ID
          "type": "function",
          "function": {
            "name": "search_labs",        // ← 工具名
            "arguments": "{\"keyword\": \"细胞\"}"   // ← 注意：是字符串不是对象！
          }
        }
      ]
    },
    "finish_reason": "tool_calls"         // ← 表示流程应该继续
  }],
  "usage": {"prompt_tokens": 320, "completion_tokens": 28, "total_tokens": 348}
}
```

**五个必须注意的点**：

| # | 点 | 坑 |
|---|---|---|
| 1 | `content` 是 `null` | 调工具时模型通常不输出文字 |
| 2 | `arguments` 是**字符串** | 要自己 `json.loads`，而且**可能不是合法 JSON**（模型生成错误时） |
| 3 | `id` 一定要保存 | 配对 ToolMessage 用 |
| 4 | `finish_reason` 是 `tool_calls` | 不是 `stop`，表示「还要继续」 |
| 5 | 可能有多个 tool_calls | 并行调用 |

### 1.3 你回传给 API 的工具结果

```json
{
  "role": "tool",
  "tool_call_id": "call_abc123",       // ★ 必须和上面的 id 一致
  "name": "search_labs",                // 有些模型要求
  "content": "[{\"id\": 1, \"name\": \"A301 细胞生物学实验室\"}]"
}
```

**`tool_call_id` 配对规则**：

> API 要求：每条 `tool` 角色的消息，必须紧跟在「包含对应 `tool_calls` 的 `assistant` 消息」之后，且 `tool_call_id` 必须匹配。

**违反会怎样？**

```
400 Bad Request:
An assistant message with 'tool_calls' must be followed by tool messages
responding to each tool_call_id.
```

**这个错误在什么时候容易出现？**

**在上下文裁剪的时候。** 如果你把历史的 `assistant`（含 tool_calls）保留了，但把后面的 `tool` 消息删了，就会报这个错。

> ⚠️ **这正是第 19 章上下文裁剪必须处理的问题**：裁剪时要保证 tool_calls 和它的 ToolMessage 成对保留或成对删除。项目里的 `_trim_messages` 专门做了这个保护。

---

## 二、`bind_tools`：LangChain 做了什么

你写的是：

```python
llm = ChatOpenAI(model="deepseek-chat").bind_tools(tools)
```

**`bind_tools` 实际做的事**：

```
1. 遍历 tools 列表
2. 每个 tool 转成 JSON Schema：
   - name ← 函数名
   - description ← docstring（第一段）
   - parameters ← 类型注解 / args_schema（Pydantic 模型）
3. 把这个 schema 列表存起来
4. 每次调用模型时，自动塞进请求的 tools 字段
5. 收到响应时，自动解析 tool_calls 到 AIMessage.tool_calls
```

**验证一下**（不需要 API Key）：

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    keyword: str = Field(default="", description="实验室名称关键词，留空查全部")

@tool(args_schema=SearchInput)
def search_labs(keyword: str = "") -> str:
    """根据关键词搜索实验室。当用户想查找实验室、询问有哪些实验室时调用。"""
    return "..."

print(search_labs.name)          # search_labs
print(search_labs.description)   # 根据关键词搜索实验室。当用户想...
print(search_labs.args)          # {'keyword': {'default': '', 'description': '...', 'type': 'string'}}
```

**关键**：

| 来源 | 变成 |
|---|---|
| 函数名 | `name` |
| docstring | `description` |
| 类型注解 / `args_schema` | `parameters` |

**所以 docstring 有多重要？** 它是模型判断「什么时候调用」的**唯一依据**（除了 System Prompt）。

---

## 三、`tool_choice`：三种模式

```python
llm.bind_tools(tools, tool_choice="auto")
```

| 模式 | 含义 | 什么时候用 |
|---|---|---|
| `"auto"`（默认） | 模型自己决定调不调 | **绝大多数场景** |
| `"none"` | 禁止调工具 | 你想让模型纯聊天时 |
| `"required"` | **必须**调至少一个工具 | 强制走工具（但会失去灵活性） |
| `{"type": "function", "function": {"name": "xxx"}}` | 强制调指定的工具 | 你知道该调哪个时 |

### 3.1 为什么本项目用默认的 auto？

考虑 `"required"` 的副作用：

```
用户："你好"
模型：（被迫）→ search_labs()
用户：😅
```

简单问候也被迫调工具，浪费钱和时间。

**什么时候该用 `required`？**

- 你已经确定这一步必须查数据（比如意图分类后确定是查询类）
- 你发现模型偷懒不调工具，且 Prompt 优化无效

> 💡 **面试话术**：「我用默认的 auto，不用 required。因为 required 会让模型在简单问候时也被迫调工具，浪费钱和时间。
>
> 我处理『模型不调工具』的手段是 Prompt 层：System Prompt 里明确『查询类问题必须调工具』，工具描述里写清触发场景，再配合反向约束『不要凭记忆回答』。如果这些都不奏效才会考虑 required。
>
> 不过有个更好的做法：先做意图分类，确定是查询类之后再用 required 强制调工具——这样既保证调用率，又不会在闲聊时浪费。」

### 3.2 一个高级技巧：动态 tool_choice

```python
# 先让模型自己决定一次
response = await llm.ainvoke(messages)

if not response.tool_calls and should_have_used_tool(user_input):
    # 它没调，但我们认为它该调 → 强制重来
    response = await llm.bind_tools(tools, tool_choice="required").ainvoke(messages)
```

这是「检测 + 纠正」模式。代价是多一次调用。

---

## 四、并行工具调用（Parallel Tool Calling）

### 4.1 现象

模型可能一次返回多个 tool_calls：

```json
{
  "tool_calls": [
    {"id": "call_1", "function": {"name": "search_labs", "arguments": "{}"}},
    {"id": "call_2", "function": {"name": "list_equipments", "arguments": "{\"lab_id\": 1}"}}
  ]
}
```

**什么时候会并行？** 当模型认为这几个调用**互不依赖**时。

**什么时候不会？** 有依赖时（比如先查实验室 ID，再用 ID 查设备），模型会串行。

### 4.2 执行时该并行还是串行？

**项目里是串行的**（`tool_node` 里 for 循环）：

```python
for tc in tool_calls:
    ...
    content = await _invoke_tool_with_retry(tool, args)
```

**为什么串行？**

| 理由 | 说明 |
|---|---|
| 简单 | 代码清晰，错误处理简单 |
| 安全 | 工具可能有隐含的顺序依赖 |
| 够用 | 大部分场景模型一次只调 1 个工具 |

**什么时候该改成并行？**

当模型经常一次调 3+ 个独立工具时。改法：

```python
import asyncio

async def tool_node(state):
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []

    # 并行执行所有工具
    results = await asyncio.gather(*[
        _invoke_tool_with_retry(tools_by_name.get(tc["name"]), tc["args"] or {})
        for tc in tool_calls
    ], return_exceptions=True)     # ★ 一个失败不影响其他

    messages = []
    for tc, result in zip(tool_calls, results):
        if isinstance(result, Exception):
            content = json.dumps({"ok": False, "error": str(result)}, ensure_ascii=False)
        else:
            content = result
        messages.append(ToolMessage(content=content, tool_call_id=tc["id"], name=tc["name"]))
    return {"messages": messages}
```

> ⚠️ **风险**：如果工具之间有依赖（比如第一个工具创建记录，第二个工具查询它），并行会出错。
>
> **折中方案**：给工具加一个标记 `parallel_safe: bool`，只对标记了 safe 的工具并行。

> 💡 **面试话术**：「我项目里工具是串行执行的（for 循环）。如果要优化，可以改成 `asyncio.gather` 并行——因为模型返回多个 tool_calls 时，这些调用通常是互不依赖的。
>
> 但要注意两个问题：一是有些工具有隐含依赖（比如先创建再查询），需要用 `return_exceptions=True` 保证一个失败不影响其他；二是要小心数据库会话的并发使用——同一个 Session 在多个线程里同时用会出问题。
>
> 我没做这个优化，因为大部分场景模型一次只调一个工具，收益有限。这是我明确记录的技术债。」

---

## 五、流式场景下的 tool_calls：一个真实的坑

**这是本章最有价值的部分。**

### 5.1 问题

流式输出时，模型的响应是**分块**来的。对于普通文本，每块是一个字：

```
data: {"choices":[{"delta":{"content":"找"}}]}
data: {"choices":[{"delta":{"content":"到"}}]}
data: {"choices":[{"delta":{"content":"了"}}]}
```

**但 tool_calls 是增量 JSON**：

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","type":"function","function":{"name":"search_labs","arguments":""}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"key"}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"word\":"}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"细胞\"}"}}]}}]}
```

**你必须把 `arguments` 的这些片段拼接起来**，才能得到完整的 `{"keyword": "细胞"}`。

### 5.2 为什么这是个坑

如果你直接处理每个 chunk：

```python
# ❌ 错误
for chunk in stream:
    tc = chunk.tool_calls[0]
    args = json.loads(tc["function"]["arguments"])   # 💥 JSON 解析失败！
```

因为第一块的 `arguments` 是空字符串，第二块是 `{"key` —— 都不是合法 JSON。

### 5.3 怎么正确处理

**方法一：用 LangChain 的消息累加（推荐）**

LangChain 的 `AIMessageChunk` 支持 `+` 运算，会自动合并 tool_calls：

```python
full = None
async for chunk in llm.astream(messages):
    full = chunk if full is None else full + chunk

# full 现在是完整的 AIMessage，tool_calls 已合并
if full.tool_calls:
    for tc in full.tool_calls:
        print(tc["name"], tc["args"])     # args 已经是 dict 了
```

**原理**：`AIMessageChunk.__add__` 内部维护了一个 `tool_call_chunks` 列表，按 `index` 合并 `arguments` 字符串，最后尝试 `json.loads`。

**方法二：手动累加（理解原理）**

```python
tool_calls_buffer = {}

async for chunk in stream:
    for tc_delta in chunk.tool_calls or []:
        idx = tc_delta.get("index", 0)
        if idx not in tool_calls_buffer:
            tool_calls_buffer[idx] = {
                "id": tc_delta.get("id", ""),
                "name": tc_delta.get("function", {}).get("name", ""),
                "args_str": tc_delta.get("function", {}).get("arguments", ""),
            }
        else:
            buf = tool_calls_buffer[idx]
            if tc_delta.get("id"):
                buf["id"] = tc_delta["id"]
            if tc_delta.get("function", {}).get("name"):
                buf["name"] = tc_delta["function"]["name"]
            buf["args_str"] += tc_delta.get("function", {}).get("arguments", "")

# 流结束后解析
for idx, buf in tool_calls_buffer.items():
    try:
        args = json.loads(buf["args_str"]) if buf["args_str"] else {}
    except json.JSONDecodeError:
        args = {}      # 模型生成了非法 JSON，兜底
    print(buf["name"], args)
```

> ⚠️ **注意 `index` 字段**：多个并行工具调用时，用 `index` 区分是哪个调用的片段。**不用 index 会把两个调用的参数拼在一起。**

### 5.4 项目里是怎么规避的

项目用的是 `astream_events`，它已经处理好了这个合并：

```python
async for event in agent.astream_events(inputs, version="v2", config=...):
    kind = event.get("event")
    if kind == "on_chat_model_stream":
        text = _chunk_text((event.get("data") or {}).get("chunk"))
        if text:
            yield {"type": "token", "content": text}   # ← 只转发文本
```

**关键**：项目**只转发文本 token，不处理 tool_calls**。

tool_calls 的处理在哪？在 LangGraph 内部的 `agent` 节点——它用的是 `ainvoke`（非流式拿到完整结果），图的状态里就是完整的 AIMessage。

**所以项目规避了这个坑**：流式只用于展示文本，工具调用走非流式路径。

> 💡 **面试话术**：「流式场景下 tool_calls 是**增量 JSON**——arguments 被切成好几块，第一块可能是空字符串，中间几块不是合法 JSON。直接 `json.loads` 会失败。
>
> 正确做法是按 `index` 累加字符串，流结束后再解析。LangChain 的 `AIMessageChunk` 已经实现了这个合并（`chunk1 + chunk2`），所以用它就不用自己处理。
>
> 我项目里规避得更彻底：流式只用于推送文本 token 给前端做打字机效果，工具调用走 LangGraph 内部的非流式路径。这样既保证了前端体验，又不用处理增量 JSON 的复杂性。」

---

## 六、错误处理：模型生成的 arguments 不合法

**模型生成的 `arguments` 可能不是合法 JSON。** 这是真实会发生的。

### 6.1 常见错误形态

| 形态 | 例子 | 原因 |
|---|---|---|
| 截断 | `{"keyword": "细` | max_tokens 不够 |
| 多余逗号 | `{"a": 1,}` | 模型生成失误 |
| 单引号 | `{'keyword': '细胞'}` | Python 风格 |
| 中文引号 | `{"keyword": "细胞"}` | 全角字符 |
| 类型错误 | `{"lab_id": "A301"}` | 模型没理解类型 |
| Python 字面量 | `{"flag": True}`（应为 true） | 同上 |

### 6.2 兜底策略

```python
import json
import ast

def parse_tool_args(raw: str) -> dict:
    """宽松解析模型生成的 arguments。"""
    if not raw or not raw.strip():
        return {}

    # 1. 先尝试标准 JSON
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. 尝试 Python 字面量（处理 True/False/None、单引号）
    try:
        result = ast.literal_eval(raw)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError):
        pass

    # 3. 修复常见问题后重试
    fixed = raw.replace("'", '"').replace("True", "true") \
               .replace("False", "false").replace("None", "null")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 4. 实在不行，返回空 dict，让工具用默认值
    #    更好的做法：返回错误信息让模型重来
    return {"__parse_error__": raw}
```

**更好的做法**：解析失败时把错误回填给模型：

```python
if "__parse_error__" in args:
    content = json.dumps({
        "ok": False,
        "error": f"参数格式错误，请重新生成合法的 JSON。你生成的是：{raw[:100]}"
    }, ensure_ascii=False)
else:
    content = tool.invoke(args)
```

这样模型有机会改正——这正是 ReAct 的价值。

> ⚠️ **项目现状**：LangChain 的 `bind_tools` 内部会做解析，失败时会抛异常或返回空。项目里没有专门做宽松解析，这是一个可以加固的点。

---

## 七、最小可运行骨架

```python
"""
function_calling_demo.py —— Function Calling 的工程细节
运行：pip install "langchain-core" && python function_calling_demo.py
（无需 API Key，用模拟数据演示结构）
演示：tool_calls 结构、bind_tools、tool_choice、流式增量合并、参数容错
"""
import json
from typing import Any

# ══════════════════════════════════════════════════════════
# 1. tool_calls 结构解剖
# ══════════════════════════════════════════════════════════

def demo_structure():
    print("【1. tool_calls 完整结构】")

    request = {
        "tools": [{
            "type": "function",
            "function": {
                "name": "search_labs",
                "description": "根据关键词搜索实验室",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "关键词"}
                    },
                    "required": [],
                },
            },
        }],
        "tool_choice": "auto",
    }
    print("  请求里的 tools：")
    print(f"    {json.dumps(request['tools'][0]['function'], ensure_ascii=False)[:100]}...")

    response_message = {
        "role": "assistant",
        "content": None,                      # ⚠️ 调工具时通常是 null
        "tool_calls": [{
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "search_labs",
                "arguments": '{"keyword": "细胞"}',   # ⚠️ 字符串不是对象
            },
        }],
    }
    print("\n  响应里的 message：")
    print(f"    content = {response_message['content']}  ← 调工具时是 null")
    print(f"    tool_calls[0].id = {response_message['tool_calls'][0]['id']}")
    print(f"    tool_calls[0].function.arguments = "
          f"{response_message['tool_calls'][0]['function']['arguments']}  ← 字符串！")

    tool_message = {
        "role": "tool",
        "tool_call_id": "call_abc123",        # ★ 必须配对
        "content": '[{"id": 1, "name": "A301"}]',
    }
    print("\n  回传的工具结果：")
    print(f"    tool_call_id = {tool_message['tool_call_id']}  ← 必须与上面的 id 一致")

    print("\n  ⚠️ 配对规则：")
    print("     tool 消息必须紧跟在含 tool_calls 的 assistant 消息之后")
    print("     且每个 tool_call_id 都要有对应的 tool 消息")
    print("     违反 → 400 Bad Request")
    print("     ⚠️ 这个坑在做上下文裁剪时最容易踩！")
    print()

# ══════════════════════════════════════════════════════════
# 2. bind_tools 做了什么
# ══════════════════════════════════════════════════════════

def demo_bind_tools():
    print("【2. bind_tools 的转换过程】")
    print("""
  你写的 Python：

      @tool(args_schema=SearchInput)
      def search_labs(keyword: str = "") -> str:
          \"\"\"根据关键词搜索实验室。当用户想查找实验室时调用。\"\"\"
          ...

  bind_tools 转成：

      {
        "name": "search_labs",                    ← 函数名
        "description": "根据关键词搜索实验室...",   ← docstring ★
        "parameters": {                           ← 类型注解 / Pydantic
          "type": "object",
          "properties": {
            "keyword": {
              "type": "string",
              "description": "实验室名称关键词，留空查全部"   ← Field description ★
            }
          },
          "required": []
        }
      }

  ★ 标记的两处是模型判断"何时调用、怎么填参数"的唯一依据
    """)

# ══════════════════════════════════════════════════════════
# 3. tool_choice 三种模式
# ══════════════════════════════════════════════════════════

def demo_tool_choice():
    print("【3. tool_choice 模式对比】")
    print(f"  {'模式':<22}{'行为':<32}{'适用'}")
    print("  " + "-" * 74)
    rows = [
        ("auto (默认)", "模型自己决定", "绝大多数场景 ★项目用这个"),
        ("none", "禁止调工具", "纯聊天、总结"),
        ("required", "必须调至少一个", "确定要查数据时（但会误伤闲聊）"),
        ('{"name": "xxx"}', "强制调指定工具", "已知该调哪个"),
    ]
    for a, b, c in rows:
        print(f"  {a:<22}{b:<32}{c}")

    print("""
  ⚠️ required 的副作用：
     用户："你好"
     模型：（被迫）search_labs()   ← 浪费钱和时间

  ✅ 更好的做法：
     先意图分类 → 确定是查询类 → 再用 required 强制调工具
    """)

# ══════════════════════════════════════════════════════════
# 4. 流式 tool_calls 增量合并（重点！）
# ══════════════════════════════════════════════════════════

def demo_stream_delta():
    print("【4. 流式场景：tool_calls 是增量 JSON】")

    # 模拟流式 chunks
    chunks = [
        {"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                         "function": {"name": "search_labs", "arguments": ""}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": '{"key'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": 'word"'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": ':"细'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": '胞"}'}}]},
    ]

    print("\n  ❌ 错误做法：直接解析每块")
    for i, c in enumerate(chunks[:3], 1):
        raw = c["tool_calls"][0]["function"].get("arguments", "")
        try:
            json.loads(raw)
            print(f"    第{i}块 '{raw}' → 解析成功")
        except json.JSONDecodeError:
            print(f"    第{i}块 '{raw}' → 💥 JSON 解析失败")

    print("\n  ✅ 正确做法：按 index 累加，流结束再解析")
    buffer = {}
    for c in chunks:
        for tc in c.get("tool_calls", []):
            idx = tc.get("index", 0)
            if idx not in buffer:
                buffer[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
            b = buffer[idx]
            if tc.get("id"):
                b["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                b["name"] = fn["name"]
            b["args"] += fn.get("arguments", "")

    for idx, b in buffer.items():
        args = json.loads(b["args"])
        print(f"    index={idx}: id={b['id']}, name={b['name']}, args={args}")

    print("\n  ⚠️ 关键：必须按 index 区分！")
    print("     并行调用时多个 tool_call 的片段是交错来的")
    print("     不用 index 会把两个调用的参数拼在一起")
    print()

# ══════════════════════════════════════════════════════════
# 5. 参数容错
# ══════════════════════════════════════════════════════════

def parse_args_loose(raw: str) -> dict:
    """宽松解析模型生成的 arguments。"""
    import ast
    if not raw or not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        r = ast.literal_eval(raw)
        if isinstance(r, dict):
            return r
    except (ValueError, SyntaxError):
        pass
    fixed = (raw.replace("'", '"')
                .replace("True", "true")
                .replace("False", "false")
                .replace("None", "null"))
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    return {"__parse_error__": raw}

def demo_arg_tolerance():
    print("【5. 参数容错：模型生成的 arguments 可能不合法】")
    cases = [
        ('{"keyword": "细胞"}', "正常"),
        ('{"keyword": "细', "截断（max_tokens 不够）"),
        ('{"keyword": "细胞",}', "多余逗号"),
        ("{'keyword': '细胞'}", "单引号（Python 风格）"),
        ('{"lab_id": "A301"}', "类型错误（应该是 int）"),
        ('{"flag": True}', "Python 字面量"),
    ]
    print(f"  {'原始 arguments':<28}{'解析结果':<34}{'说明'}")
    print("  " + "-" * 80)
    for raw, note in cases:
        result = parse_args_loose(raw)
        r_str = str(result)[:32]
        print(f"  {raw:<28}{r_str:<34}{note}")

    print("\n  ✅ 兜底策略：")
    print("     1. 标准 JSON 解析")
    print("     2. Python literal_eval（处理单引号、True/None）")
    print("     3. 字符替换后重试")
    print("     4. 都失败 → 回填错误信息让模型重来（ReAct 自纠）")
    print()

# ══════════════════════════════════════════════════════════
# 6. 并行调用
# ══════════════════════════════════════════════════════════

def demo_parallel():
    print("【6. 并行工具调用】")
    print("""
  模型可能一次返回多个 tool_calls（当它认为互不依赖时）：

    tool_calls: [
      {"id": "call_1", "function": {"name": "search_labs", ...}},
      {"id": "call_2", "function": {"name": "list_equipments", ...}}
    ]

  执行策略：
  ┌────────┬──────────────────────┬──────────────────────┐
  │        │ 串行（项目现状）       │ 并行（优化方向）       │
  ├────────┼──────────────────────┼──────────────────────┤
  │ 代码   │ for 循环 await        │ asyncio.gather        │
  │ 延迟   │ 累加                  │ 取最大值               │
  │ 风险   │ 无                    │ 隐含依赖会出错         │
  │ 适用   │ 大部分场景（1个工具）  │ 经常调 3+ 独立工具      │
  └────────┴──────────────────────┴──────────────────────┘

  并行要点：
    - return_exceptions=True（一个失败不影响其他）
    - 注意 DB Session 不能跨线程共用
    - 可以标记 parallel_safe 只对安全工具并行

  我没做这个优化：大部分场景模型一次只调一个工具，收益有限
    """)

# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 76)
    print("Function Calling 工程细节")
    print("=" * 76 + "\n")
    demo_structure()
    demo_bind_tools()
    demo_tool_choice()
    demo_stream_delta()
    demo_arg_tolerance()
    demo_parallel()
```

---

## 八、项目代码定位

### 8.1 工具定义：`agent_tools.py`

```python
@tool
def search_labs(keyword: str = "") -> str:
    """搜索实验室，返回实验室列表（含 id、名称、容量、位置）。

    适用场景：用户想查找实验室、询问有哪些实验室、需要知道某个实验室的 ID。
    """
    ...
```

### 8.2 `bind_tools`：`agent_service.py:256-262`

```python
llm = ChatOpenAI(
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    model=settings.LLM_MODEL,
    temperature=0,
    streaming=True,
).bind_tools(tools)
```

### 8.3 tool_calls 处理：`agent_service.py:289-315`

```python
async def tool_node(state):
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    ...
    for tc in tool_calls:
        name = tc.get("name")
        args = tc.get("args") or {}
        tool = tools_by_name.get(name)
        ...
        messages.append(ToolMessage(
            content=content,
            tool_call_id=tc.get("id"),    # ★ 配对
            name=name,
        ))
```

**注意 `args` 的来源**：LangChain 已经把 `arguments` 字符串解析成了 dict，所以这里直接用 `tc.get("args")`。

### 8.4 流式只转发文本：`agent_service.py:478-484`

```python
elif kind == "on_chat_model_stream":
    meta = event.get("metadata") or {}
    if meta.get("langgraph_node") not in (None, "agent"):
        continue
    text = _chunk_text((event.get("data") or {}).get("chunk"))
    if text:
        yield {"type": "token", "content": text}
```

**`_chunk_text` 的作用**：从 chunk 里提取纯文本，**过滤掉 tool_calls 部分**（因为 content 是空时返回 ""）。

---

## 本章速记卡

1. **`tool_calls` 结构**：`{id, type, function: {name, arguments}}`。`arguments` 是**字符串**。
2. **`content` 在调工具时是 `null`**，不要当成空字符串处理。
3. **`tool_call_id` 必须配对**，且 tool 消息必须紧跟 assistant 消息。**上下文裁剪时最容易踩**。
4. **`bind_tools`**：函数名→name、docstring→description、类型注解→parameters。
5. **`tool_choice`**：auto（默认）/ none / required / 指定工具。required 有误伤。
6. **流式 tool_calls 是增量 JSON**，必须按 `index` 累加后解析。
7. **arguments 可能不合法**（截断、单引号、Python 字面量），要宽松解析 + 回填错误。
8. **并行调用**：模型可能一次返回多个，串行简单、并行快。
9. **项目规避了增量 JSON 的坑**：流式只推文本，工具走非流式路径。
10. **`_chunk_text` 过滤掉 tool_calls 片段**，只转发文本 token。

---

## 面试问答：Function Calling

### Q1：「Function Calling 的流程是怎样的？」

**满分答法**：

> 四步。
>
> **第一步，声明工具**。我定义好函数，用 `@tool` 装饰器或者 Pydantic 模型声明参数，LangChain 的 `bind_tools` 把它们转成 JSON Schema。函数名变成 `name`，docstring 变成 `description`，类型注解和 Field description 变成 `parameters`。
>
> **第二步，发给模型**。每次调用模型时，工具 schema 会一起发过去。模型看到后决定要不要调、调哪个、参数是什么。
>
> **第三步，模型返回 tool_calls**。注意返回的 `arguments` 是**字符串**不是对象，要自己解析。而且 `content` 通常是 null——调工具时模型不输出文字。
>
> **第四步，执行并回传**。我执行工具，把结果包装成 `tool` 角色的消息，带上 `tool_call_id` 配对，再发给模型，让模型基于结果继续。
>
> 关键细节是配对的规则：`tool` 消息必须紧跟在含 `tool_calls` 的 assistant 消息之后，每个 `tool_call_id` 都要有对应结果。违反会报 400。这个坑在做上下文裁剪时最容易踩——如果你保留了 assistant 消息但删了后面的 tool 消息，就会出错。

---

### Q2：「流式场景下 tool_calls 怎么处理？」

**满分答法**（这是区分度很高的问题）：

> 流式时 tool_calls 是**增量 JSON**——`arguments` 被切成好几块发过来，第一块可能是空字符串，中间几块不是合法 JSON。直接对每块 `json.loads` 会失败。
>
> 正确做法是按 `index` 累加字符串，等流结束后再整体解析。**必须用 index 区分**——并行调用时多个 tool_call 的片段是交错来的，不用 index 会把两个调用的参数拼在一起。
>
> LangChain 的 `AIMessageChunk` 已经实现了这个合并（`chunk1 + chunk2` 会自动累加），所以用 LangChain 就不用自己处理。
>
> 我项目里规避得更彻底：流式只用于推送文本 token 给前端做打字机效果；工具调用走 LangGraph 内部的非流式路径（`ainvoke` 拿完整结果）。这样既保证了前端体验，又不用处理增量 JSON 的复杂性。这是个明确的架构选择。

---

### Q3：「模型生成的参数不合法怎么办？」

**满分答法**：

> 这是真实会发生的。常见形态有：截断（max_tokens 不够）、多余逗号、单引号（Python 风格）、中文引号、类型错误（该是 int 传了字符串）、Python 字面量（True 而不是 true）。
>
> 我的兜底是分层的：先标准 JSON 解析；失败就用 `ast.literal_eval`（能处理单引号和 True/None）；再失败就做字符替换后重试；都不行就返回错误信息。
>
> 关键的设计是：**解析失败不抛异常，而是把错误回填给模型**。比如返回「参数格式错误，请重新生成合法的 JSON，你生成的是 xxx」。这样模型有机会改正——这正是 ReAct 循环的价值。抛异常的话图就断了，用户只看到 500。
>
> 说实话我项目里没有做完整的宽松解析，LangChain 内部会处理一部分。这是可以加固的点。

---

### Q4：「tool_choice 你怎么选？」

**满分答法**：

> 我用默认的 `auto`，让模型自己决定。
>
> 不用 `required` 是因为它有副作用：用户说「你好」，模型也被迫调工具，浪费钱和时间。
>
> 我处理「模型不调工具」的手段在 Prompt 层：System Prompt 里明确「查询类问题必须调工具」，工具描述里写清触发场景，再加反向约束「不要凭记忆回答」。
>
> 更好的做法是**动态 tool_choice**：先做意图分类，确定是查询类之后再用 `required` 强制调工具。这样既保证调用率，又不会误伤闲聊。我项目里没做到这一步，但这是我认为正确的方向。

---

### Q5：「并行工具调用怎么处理？」

**满分答法**：

> 模型可能一次返回多个 tool_calls，当它认为这些调用互不依赖时。
>
> 执行策略有两种：串行（for 循环 await）和并行（`asyncio.gather`）。
>
> 我项目里是串行的，三个理由：代码简单、错误处理清晰、而且大部分场景模型一次只调一个工具，并行的收益有限。
>
> 如果要改并行，要注意三点：一是 `return_exceptions=True`，保证一个工具失败不影响其他；二是数据库 Session 不能跨线程共用（我用的是同步 Session，会走 `to_thread`，要小心）；三是有些工具有隐含依赖（先创建再查询），不能无脑并行。折中方案是给工具标记 `parallel_safe`，只对标记了的工具并行。
>
> 这是我明确记录的技术债——现在收益不大，但如果将来模型经常一次调 3 个以上工具，这个优化的价值就大了。

---

### Q6：「Function Calling 和 MCP 是什么关系？」（追问）

**满分答法**：

> Function Calling 是**模型的能力**——模型输出结构化的调用请求。
>
> MCP 是**工具的协议**——规定工具怎么被描述、怎么被发现、怎么跨进程调用。
>
> 两者解决不同层面的问题：Function Calling 解决「模型怎么表达它想调什么」，MCP 解决「工具怎么被提供给模型」。
>
> 在 LangChain 里，MCP 工具加载进来之后会被转成普通的 LangChain Tool 对象，然后一样走 `bind_tools`。所以对模型来说，MCP 工具和本地函数没有区别——它们都被转成同样的 JSON Schema。
>
> 区别在工程层面：本地函数是进程内的，快但不能复用；MCP 工具是跨进程的，慢但可以被多个 Agent、甚至其他语言的项目复用。（第 30 章详讲）

---

## 常见坑

### 坑 1：`tool_call_id` 不配对

400 错误。上下文裁剪时最容易踩。

### 坑 2：流式直接解析 `arguments`

不是合法 JSON。要按 index 累加。

### 坑 3：把 `content: null` 当空字符串

调工具时 content 是 null，要做类型判断。

### 坑 4：用 `required` 导致闲聊也调工具

浪费钱。

### 坑 5：arguments 解析失败抛异常

图断了。应该回填错误让模型自纠。

### 坑 6：并行调用不用 index 区分

参数拼在一起。

### 坑 7：忘了 `bind_tools`

模型永远不知道有工具。这是最常见的新手错误。

### 坑 8：工具 schema 太长导致 token 超预算

工具多了要精简描述或按需加载。

---

## 动手练习

### 练习 1（必做）

跑通第七节的 `function_calling_demo.py`，重点看：

1. 流式增量的错误做法和正确做法
2. 参数容错的 6 个用例

然后**手动实现一个并行场景**：模拟两个 tool_call 的片段交错，验证必须用 index 区分。

### 练习 2

给项目加参数容错：

```python
def _parse_args(args) -> dict:
    """如果 args 是字符串（解析失败），做宽松解析。"""
    if isinstance(args, str):
        return parse_args_loose(args)
    return args
```

在 `tool_node` 里用它，并测试模型生成非法 JSON 的情况。

### 练习 3

打开 `agent_service.py` 的 `_chunk_text`，理解它为什么能过滤掉 tool_calls 片段。

写一个测试：构造一个 `arguments` 是 `{"key` 的 chunk，验证 `_chunk_text` 返回空字符串。

### 练习 4（进阶）

实现并行工具执行：

```python
results = await asyncio.gather(*[...], return_exceptions=True)
```

对比串行和并行在一个「模型一次调 3 个工具」场景下的耗时差异。

---

## 下一章

**第 14 章 · ReAct 范式深入**

第 12 章讲了 ReAct 的概念，第 13 章讲了 Function Calling 的细节。这一章把它们串起来，讲清楚 ReAct 的**完整实现**和**变体**。

包括：
- ReAct 的原始论文思路和现代实现差异
- 为什么现代 LLM 不再需要显式输出「Thought:」
- ReAct 的失败模式（循环、过早停止、过度调用）
- 其他 Agent 范式对比（Plan-and-Execute、Reflexion、ReWOO）
- 怎么选择范式

还有一个重点：**怎么给 ReAct 加防护栏**，让它既自主又可控。
