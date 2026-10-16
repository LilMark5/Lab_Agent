# 09 · Tool Calling：让模型学会“调用函数”

## 1. 什么是 Too l Calling？

普通对话模型只能输出文字。Tool Calling 允许模型输出一个“函数调用”：

```json
{
  "name": "list_open_labs",
  "arguments": {"keywords": "人工智能"}
}
```

后端执行这个函数，把结果再还给模型，模型根据结果生成最终回答。

注意：**模型并不直接执行工具**。它只负责“决定调哪个函数、传什么参数”，
真正执行的是你的后端代码。

## 2. 完整循环

```text
用户问题
  -> 模型判断需要工具
  -> 返回 tool_calls
  -> 后端执行函数
  -> 结果以 role=tool 塞回消息
  -> 再次调用模型
  -> 模型输出自然语言
```

本项目手写版本在 `ai_service.py`：

```python
for _ in range(3):
    res = client.chat.completions.create(messages=messages, tools=TOOLS)
    msg = res.choices[0].message
    if not msg.tool_calls:
        return msg.content
    # 执行工具，追加 tool 消息
```

LangGraph 版本则把循环交给图：

```python
graph.add_conditional_edges("agent", tools_condition)
graph.add_node("tools", ToolNode(tools))
graph.add_edge("tools", "agent")
```

## 3. 工具定义

工具必须给模型清晰的说明：

```python
{
  "name": "list_lab_equipments",
  "description": "查询某个实验室下的设备列表",
  "parameters": {
    "type": "object",
    "properties": {
      "lab_id": {"type": "integer", "description": "实验室 ID"}
    }
  }
}
```

描述越准确，模型调用越可靠。描述模糊是 Tool Calling 出错的主要原因。

## 4. 工具结果要“瘦”

不要返回整张表，只给模型回答问题需要的字段：

```python
rows = [{"id": item.id, "name": item.name, "capacity": item.capacity} for item in page.list]
```

原因：

- 节省 token。
- 减少无关信息干扰模型。
- 防止把敏感字段暴露给模型。

## 5. 工具出错怎么办？

工具内部要捕获异常，返回结构化 JSON，而不是让整个对话崩掉：

```python
except Exception as exc:
    return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
```

模型看到错误后，可以换参数重试或向用户解释。

## 6. 安全边界

写操作工具比读操作危险：

- 只给最小权限。
- 高风险操作要求确认。
- 对模型传入的参数做完整业务校验。

本项目 `create_lab_reservation` 最终还是调用 `reservation_service.create_reservation`，
里面有日期、开放时间、冲突等完整校验。模型“说预约”不等于“直接插库”。

## 7. 常见问题

- **模型不调用工具**：检查工具描述、模型是否支持 function calling。
- **参数错误**：给参数加 description、示例，必要时用 JSON Schema 约束 enum。
- **死循环**：限制最大轮数，或检测重复调用。
- **超时**：工具循环增加延迟，前端超时要放大，或改流式。

## 8. 检查清单

- 模型会执行工具吗？还是只输出调用参数？
- `role=tool` 消息的作用是什么？
- 为什么要限制工具循环次数？
- 写数据库工具和读数据库工具有什么不同？
