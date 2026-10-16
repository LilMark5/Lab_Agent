# 01 · 项目总览与架构

## 1. 这个项目到底在解决什么问题？

很多同学学完 FastAPI、Vue、LangChain，却不知道怎么把技术拼成一个真实系统。
这个项目故意走一条“由业务到 AI”的路线：

```text
传统 CRUD 业务系统
  → 接大模型对话
  → 用 RAG 给模型补充资料
  → 用 Tool Calling 让模型查真实数据库
  → 用 LangGraph 把“思考/查库/确认/预约”组织成工作流
  → 用 SSE 把过程实时显示到前端
```

这个顺序很重要：**AI 不是替代业务，而是站在业务之上增强业务。**
如果预约接口都写不对，AI Agent 也不可能正确落库。

## 2. 系统长什么样

角色分两类：

- 学生：注册登录、看实验室、看设备、提交预约、取消预约、用 AI 助手。
- 管理员：管理用户、实验室、设备，审核预约。

核心业务闭环：

```text
学生选实验室/设备
  -> 填日期和时段
  -> 提交预约(status=0 待审核)
  -> 管理员通过(status=1)或拒绝(status=2jjb
  -> 学生可取消待审核预约(status=3)
```

AI 层不是独立系统，而是复用这些 Service：

```text
用户问题
  -> LangGraph Agent
  -> 调 search_lab_docs / list_open_labs / list_lab_equipments / create_lab_reservation
  -> 复用 reservation_service / lab_service / equipment_service
  -> 最终回答或落库
```

## 3. 分层架构

后端采用经典三层：

```text
api/      接口层：参数校验、鉴权依赖、调用 service
services/ 业务层：核心逻辑，AI 工具也复用这里
models/   数据层：ORM 模型，对应数据库表
schemas/  契约层：接口入参出参，和数据库模型隔离
common/   公共层：统一响应、异常处理
utils/    工具层：JWT、密码
```

为什么要把 `schemas` 和 `models` 分开？

- ORM 模型包含数据库细节，可能不适合直接返回前端。
- Schema 只暴露接口需要的数据，例如用户响应里永远不包含 password。
- 未来换数据库、加字段时，接口契约不会被迫改变。

## 4. 一次请求的完整数据流

以前端“登录”为例：

```text
Vue 页面点击登录
  -> api/auth.js 调 axios
  -> /api/auth/login
  -> Vite 代理转发到 FastAPI
  -> Auth API 接收 LoginRequest
  -> auth_service.login 查 users 表
  -> bcrypt 校验密码
  -> JWT 生成 token
  -> 统一响应 {code,message,data}
  -> 前端保存 token，跳转首页
```

后续请求都会带 `Authorization: Bearer <token>`，FastAPI 的
`get_current_user` 解析 token 后拿到当前用户。

## 5. 项目里最重要的设计原则

### 5.1 单一职责

接口函数不做业务判断，业务逻辑全部在 service。这样 AI 工具和普通接口
可以调用同一套函数，避免重复。

### 5.2 依赖注入

FastAPI 的 `Depends(get_db)`、`Depends(get_current_user)` 就是依赖注入。
函数声明自己需要什么，框架负责提供，测试时可以替换。

### 5.3 显式错误

可预期的业务错误用 `BusinessException`，未知错误用全局兜底。
前端看到的是稳定的 `{code,message,data}`，不会把 Python 堆栈暴露给用户。

## 6. 建议的调试方法

1. 先用 Swagger 文档调试后端：`http://127.0.0.1:8000/docs`。
2. 再联调前端，打开浏览器 Network 看请求与响应。
3. AI 部分打开后端控制台，注意 `print` 出来的检索内容和工具结果。
4. 出问题时先确认“数据是否进了数据库”，再确认“模型是否返回了工具调用”。

## 7. 你可以复用到其他项目的骨架

把这个项目改造成“图书预约”“会议室预约”“门诊预约”，业务逻辑几乎一样。
真正要替换的只有 models、schemas 和 service 里的字段。
