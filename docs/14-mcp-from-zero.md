# 14 · MCP 从零入门

## 1. MCP 是什么？

MCP（Model Context Protocol）是一个开放协议，目标是让大模型**用统一的方式连接工具和数据**。

以前每个模型、每个工具都要单独写适配；有了 MCP：

```text
任意 AI 客户端  ->  MCP 协议  ->  任意工具/数据源
```

就像 USB 接口：电脑不用关心插的是什么设备，设备也不用关心是哪个电脑。

## 2. 核心角色

```text
MCP Host    宿主：承载 AI 客户端，比如 Claude、Codex、你的应用
MCP Client  客户端：发请求的一方
MCP Server  服务端：提供工具/资源的一方
```

本项目里：

- MCP Server 是 [mcp_server.py](../../backend/app/mcp_server.py)，暴露三个工具。
- Agent 是 Client，通过 `langchain-mcp-adapters` 加载工具。

## 3. 一个工具长什么样

```python
@mcp.tool()
def list_open_labs(keywords: str = "") -> str:
    """查询开放中的实验室列表。"""
```

函数名、参数类型、docstring 会被自动转成模型看得懂的 Schema。

## 4. 本项目的 MCP 架构

```text
自研 Agent(LangGraph)
  -> langchain-mcp-adapters(Client)
  -> http://127.0.0.1:8100/mcp
  -> FastMCP Server
  -> search_lab_docs / list_open_labs / list_lab_equipments
```

运行 MCP Server：

```bash
python -m app.mcp_server
```

## 5. 为什么只暴露“读”工具？

MCP Server 是无状态公开协议服务，不适合直接接收写操作。写库（预约）留在
有 JWT 鉴权的 LangGraph Agent 里。这是安全边界设计，面试可以讲。

## 6. 和 Function Calling 的区别

Function Calling 是“模型厂商提供的能力”，工具定义和调用格式由厂商定。
MCP 是“跨模型、跨应用的协议”，把工具打包成服务，任何客户端都能接。

可以理解成：Function Calling 是内置接口，MCP 是外接标准。

## 7. 面试答法

“我把业务查询能力封装成 MCP Server，Agent 通过适配器加载工具。好处是工具
与业务解耦，换成 Claude、Codex 或其他 Agent 都能复用；同时只暴露读接口，
写操作保留在带鉴权的 Agent 里，保证安全。”

## 8. 下一步可以学

- MCP Resources：向模型暴露文件、数据源。
- 鉴权：给 MCP Server 加 token。
- 远程部署：把 MCP Server 放到独立服务。
