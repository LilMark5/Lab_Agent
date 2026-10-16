# 06 · LangChain 企业级应用：它到底帮你做了什么

## 1. 先破除一个误区

LangChain 不是“会魔法的大模型库”，而是一套**把大模型、提示词、工具、记忆、
检索组织成可复用应用**的框架。

你完全可以不用 LangChain，直接用 `openai` SDK 调模型。LangChain 的价值在于：

- 统一不同模型的接口。
- 把消息、工具、输出解析抽象成标准对象。
- 和 LangGraph、向量库、文档加载器衔接。

## 2. 本项目的两代实现

### 2.1 第一代：直接用 OpenAI SDK

`ai_service.py` 直接创建 OpenAI 客户端：

```python
from openai import OpenAI
client = OpenAI(api_key=..., base_url=...)
res = client.chat.completions.create(model=..., messages=..., tools=...)
```

这是理解 LLM 调用最透明的写法。

### 2.2 第二代：用 LangChain 包装模型

`agent_service.py` 使用：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    api_key=settings.LLM_API_KEY,
    base_url=settings.LLM_BASE_URL,
    model=settings.LLM_MODEL,
    streaming=True,
).bind_tools(tools)
```

`ChatOpenAI` 兼容 OpenAI 协议，`bind_tools` 会把 Python 工具转成模型的
tool schema。底层仍然是 OpenAI 接口，但上层对象更统一。

## 3. 核心抽象：Message

LangChain 用消息对象表达对话：

```python
SystemMessage(content=SYSTEM_PROMPT)
HumanMessage(content="帮我预约明天下午的实验室")
AIMessage(content="好的，请确认...")
ToolMessage(content='{"ok": true}')
```

这些消息组成列表，就是模型的输入上下文。LangGraph 的状态（MessagesState）
本质也是这个列表。

## 4. 核心抽象：Tool

`langchain_core.tools` 的 `@tool` 装饰器会读取函数签名和 docstring：

```python
@tool
def list_open_labs(keywords: str = "") -> str:
    """查询开放的实验室列表。"""
```

LangChain 自动生成：

```json
{
  "name": "list_open_labs",
  "description": "查询开放的实验室列表。",
  "parameters": {"keywords": {"type": "string"}}
}
```

这个 JSON Schema 就是模型看到的“工具说明书”。

## 5. 企业级使用 LangChain 的建议

### 5.1 不要过度抽象

如果只是简单调用模型，直接 SDK 更可控。LangChain 适合：

- 多个模型/供应商切换。
- 结构化输出。
- 复杂 RAG 管道。
- Agent 工作流。

### 5.2 把 Prompt 当代码管理

本项目提示词是常量。生产上应该版本化、可测试、可回滚。

### 5.3 关注成本与超时

工具循环会多次调模型。要限制轮数、设置超时、记录 token 消耗。

### 5.4 安全边界

工具能写数据库，就必须有权限控制和确认机制。
本项目在提示词里强制“用户确认后才预约”，工具侧也用当前登录用户落库。

## 6. 检查清单

- LangChain 是模型，还是框架？
- `bind_tools` 做了什么？
- SystemMessage 和 HumanMessage 有什么区别？
- 企业项目中为什么不能无限工具循环？
