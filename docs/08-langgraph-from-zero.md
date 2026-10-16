# 08 · 零基础入门 LangGraph

## 1. 一句话理解 LangGraph

LangGraph 把 Agent 拆成**节点(Node)**和**边(Edge)**，组成一张**图(Graph)**。
节点做具体工作，边决定下一步去哪。图会维护一个共享的**状态(State)**。

```text
START → agent → 有 tool_calls？ → tools → agent → ...
                    ↓ 没有
                   END
```

## 2. 为什么要用图？

手写 while 循环也能实现 Agent，但图有三个好处：

1. **可视化**：流程一目了然，方便讲解和排查。
2. **状态管理**：LangGraph 自动保存/恢复消息列表。
3. **可扩展**：后面可以加多 Agent、人机协作、检查点。

## 3. 核心概念

### 3.1 State

本项目用 `MessagesState`：

```python
from langgraph.graph import MessagesState
```

它内部就是 `{"messages": [...]}`。节点每次返回新增消息，LangGraph 自动合并。

### 3.2 Node

节点是一个函数：

```python
def agent_node(state: MessagesState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}
```

输入是当前 state，输出是 state 的增量。

### 3.3 Edge

普通边固定流向：

```python
graph.add_edge(START, "agent")
graph.add_edge("tools", "agent")
```

条件边根据函数返回的下一个节点名分流：

```python
graph.add_conditional_edges("agent", tools_condition)
```

`tools_condition` 检查最后一条 AI 消息有没有 `tool_calls`：

- 有 -> 去 `tools`。
- 没有 -> 去 `END`。

## 4. 本项目 Agent 图怎么搭？

```python
graph = StateGraph(MessagesState)
graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(tools))
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", tools_condition)
graph.add_edge("tools", "agent")
return graph.compile()
```

运行一次：

```python
result = agent.invoke(
    {"messages": [SystemMessage(content=SYSTEM_PROMPT), *history]},
    config={"recursion_limit": 10}
)
```

`recursion_limit=10` 防止 agent 和 tools 无限来回，烧 token。

## 5. Agent 到底转了几圈？

以“帮我预约明天下午的实验室”为例：

1. `agent`：模型说“我需要先查今天日期”，产生 `get_today` 工具调用。
2. `tools`：执行 `get_today`，返回日期。
3. `agent`：模型说“明天是 X 日，我帮你查开放的实验室”，产生 `list_open_labs`。
4. `tools`：查库，返回实验室列表。
5. `agent`：模型复述要预约的内容，询问是否确认。**没有 tool_calls，结束。**

用户下一次回复“确认”，会作为新 HTTP 请求，带上上一轮文本历史，再跑一次图。

## 6. 为什么要“用户确认”？

AI 工具会真实写数据库。如果不确认，模型可能误判用户意图直接落库。
工程上的安全原则是：**高风险操作必须显式确认或人机审批。**

本项目在提示词里要求：

```text
用户没有明确说“确认”“确认预约”“就这样预约”之前，
不要调用 create_lab_reservation。
```

提示词约束不是绝对安全，但配合后端业务校验和权限，可以显著降低风险。

## 7. 常见误区

- **节点名和函数名容易混淆**：`add_node("agent", agent_node)` 里字符串才是图里的名字。
- **忘记 add_edge**：图没有边就不会流转。
- **状态返回错误**：节点应返回 state 的一部分，而不是任意值。
- **把工具当业务逻辑**：工具应该薄，真正逻辑仍放在 service。

## 8. 下一步可以学什么？

- `StateGraph` 自定义复杂 State。
- `MemorySaver` 检查点，实现长期记忆。
- 多 Agent：supervisor、并行执行。
- Human-in-the-loop：在关键节点暂停等人工批准。

## 9. 检查清单

- Node、Edge、State 分别是什么？
- `tools_condition` 如何决定下一步？
- `recursion_limit` 的作用？
- 为什么写数据库的 Agent 工具需要用户确认？
