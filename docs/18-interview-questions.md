# 18 · 核心面试题库（含参考答案）

先自己答一遍，再看答案。答案给的是“面试能讲出口”的版本，不是背课文。

## 一、Python 与异步

### 1. list 和 tuple 区别？为什么哈希键用 tuple？

list 可变、tuple 不可变。不可变对象哈希值稳定，所以能当字典 key 和集合元素；
list 会变，哈希会变，不能当 key。

### 2. 什么是装饰器？`@tool` 做了什么？

装饰器是接收函数、返回新函数的函数，用于不改原函数代码地扩展行为。
`@tool` 读取函数名、签名和 docstring，生成大模型能理解的 JSON Schema，
并把函数包装成 LangChain 工具对象。

### 3. 什么是生成器？yield 和 return 区别？

生成器是惰性求值的迭代器，`yield` 暂停函数并返回值，下次 `next` 继续；
`return` 直接结束。SSE 流式输出就是靠 `yield` 一段一段吐数据。

### 4. async def 和普通 def 在 FastAPI 里执行差别？

`async def` 在事件循环里跑，适合调用异步 HTTP/数据库；普通 `def` 被丢进线程池，
适合同步 SQLAlchemy 这类阻塞操作。混用会阻塞事件循环。

### 5. 什么时候用 asyncio.gather、asyncio.to_thread？

多个相互独立的异步任务用 `gather` 并发；把同步阻塞函数交给线程池用 `to_thread`，
避免卡住事件循环。本项目启动预热向量库就用了 `asyncio.to_thread`。

### 6. GIL 是什么？影响你的 Agent 项目吗？

GIL 让 CPython 同一时刻只有一个线程执行字节码。对计算密集影响大；但 Agent
主要瓶颈是网络 I/O 和 LLM 调用，用异步就能并发，GIL 影响很小。

## 二、HTTP 与后端

### 1. GET 和 POST 区别？哪些操作用 PUT/DELETE？

GET 只读、参数在 URL、可缓存；POST 创建/提交、参数在 body。REST 惯例：
PUT 更新、DELETE 删除。本项目就按 `/api/lab/{id}` 的 PUT/DELETE 设计。

### 2. 状态码含义？

200 成功、301 永久重定向、400 请求错误、401 未认证、403 无权限、
404 不存在、429 限流、500 服务器错误。

### 3. 跨域是什么？两种解决方式？

浏览器同源策略限制跨源请求。后端加 CORS 响应头，或前端开发用 Vite 代理把
`/api` 转发到后端，让浏览器“看起来”同源。生产环境常是 Nginx 反代。

### 4. FastAPI 的 Depends 解决什么？

依赖注入：函数声明需要什么，框架负责构造和复用。鉴权、数据库会话都能用
`Depends` 写一次、处处复用，也方便测试时替换。

### 5. 统一响应和全局异常的价值？

前端只写一个拦截器；错误结构稳定；兜底异常防止把堆栈暴露给用户。业务错误
用 code 表达、HTTP 仍 200；认证错误用 HTTP 401，两者语义不同。

### 6. 文件上传怎么防任意文件写入？

用后缀白名单、限制大小、随机文件名、不信任用户原始文件名，且上传目录
不放在可执行位置。本项目就是白名单 + 时间戳 + 随机串。

## 三、数据库与 ORM

### 1. 索引是什么？username 建索引为何加速登录？

索引是排好序的结构，查询不用全表扫。`username` 建索引后，等值查询从 O(n)
降到接近 O(log n)。但索引占空间、拖慢写入，不是越多越好。

### 2. INNER JOIN 和 LEFT JOIN？

INNER 只返回两边都匹配的行；LEFT 保留左表全部行，右表没匹配就补 NULL。
查“实验室及其设备”用 LEFT，避免没有设备的实验室被漏掉。

### 3. 事务 ACID？

原子性、一致性、隔离性、持久性。`commit` 落库，`rollback` 撤销。预约校验和
插入应在同一事务里，失败就回滚。

### 4. N+1 查询？怎么解决？

循环里逐个查关联对象，产生 N+1 条 SQL。用 `joinedload` 或 `selectinload`
一次预加载关系，减少查询次数。

### 5. ORM 和手写 SQL 优缺点？

ORM 类型安全、防注入、可切库、开发快；手写 SQL 灵活、能精细优化。复杂报表
常混用：常规用 ORM，复杂查询用原生 SQL。

### 6. PostgreSQL 和 MySQL？pgvector？

PG 类型更强、扩展更丰富；MySQL 生态普及。`pgvector` 让 PG 能存向量并做相似度
检索，适合把业务库和向量库合并，减少一套存储。

## 四、Redis 与缓存

### 1. Redis 常用数据结构？

string 字符串、hash 对象、list 队列、set 去重集合、zset 带权排序集合。

### 2. Redis 限流思路？

```python
count = redis.incr("ratelimit:user:1")
if count == 1:
    redis.expire("ratelimit:user:1", 60)
if count > 20:
    raise HTTPException(429)
```

INCR 原子自增，第一次设 60 秒过期，形成“每分钟最多 N 次”的固定窗口。

### 3. 缓存穿透、击穿、雪崩？

穿透：查不存在的 key，穿透到 DB，可用布隆过滤器或缓存空值；击穿：热点 key
过期瞬间大量请求打 DB，可加互斥锁；雪崩：大量 key 同时过期，可随机化 TTL。

### 4. RAG 结果适合缓存吗？key 怎么设计？

适合缓存“相似问题→检索结果”。key 用问题哈希：`rag:md5(query)`。但要注意
知识库更新后缓存要失效，否则旧答案继续被命中。

### 5. 缓存和数据库一致性？

常见做法：更新数据库后删除缓存，读时重建；强一致场景用延迟双删或消息队列
异步更新。业务允许短暂不一致时，优先选简单方案。

## 五、大模型基础

### 1. token 是什么？中文为什么更费 token？

token 是模型处理文本的最小单位，大致是子词。中文一个字常是一个 token，
英文常见单词可被切得更稀疏，所以同样字数中文往往更费 token。

### 2. temperature、top_p？

temperature 控制采样随机性，低更确定、高更多样；top_p 只从累计概率前 p 的
候选里采样。Agent 任务常用低 temperature 保证稳定。

### 3. system / user / assistant 消息？

system 定人设和规则，user 是用户输入，assistant 是模型回复。多轮对话把历史
user/assistant 一起发给模型。

### 4. 上下文窗口？超了怎么办？

是模型一次能读的 token 上限。超了可裁剪旧消息、摘要历史、或用检索只给相关内容。
本项目前端只保留文本历史，后端限制工具轮数，都在控上下文。

### 5. 一次对话成本怎么算？

输入 token 数 × 输入单价 + 输出 token 数 × 输出单价。Agent 多轮工具调用会把
同样上下文反复发给模型，成本成倍放大，所以要限制轮数、精简工具结果。

## 六、RAG 专题

### 1. RAG 和微调区别？

RAG 不改模型权重，外部知识即时检索后拼进 Prompt，更新快、可解释；微调改权重，
让模型内化某类能力，成本高、更新慢。多数知识问答先做 RAG。

### 2. embedding 是什么？和 LLM 分工？

embedding 把文本映射成向量，让语义相近的文本向量距离近；LLM 负责理解上下文
并生成回答。检索用 embedding 模型，生成用 LLM，两个模型分工。

### 3. 为什么切块 chunking？太大太小？

太大：检索粒度粗、噪声多、超上下文；太小：语义不完整。要根据文档结构和
问答长度选，常见 256-512 token 并保留重叠。

### 4. 向量和关键词检索？混合检索怎么融合？

向量擅长语义、同义改写；关键词擅长精确词和专有名词。混合是两路都召回，
再用 RRF 按名次融合，取长补短。

### 5. RRF 是什么？为什么稳？

Reciprocal Rank Fusion：`Σ 1/(k+rank)`，只按名次不按分数绝对值。不同召回器的
分数尺度不同，直接相加会失衡，RRF 只排名次，所以稳、无需调参。

### 6. rerank 和召回区别？

召回是双塔模型，快但粗，负责从海量文档筛候选；rerank 用交叉编码器对
“问题+文档”成对打分，慢但准，只精排前几名。

### 7. 怎么评估 RAG？

faithfulness 回答是否忠于检索内容，recall 相关文档是否被找回，hit@k 正确文档
是否进 top-k。本项目用自研脚本算 hit@2，对比纯向量和混合检索。

### 8. 检索不到相关内容怎么办？

诚实回答“不知道”或提示去对应页面，不要让模型硬编。工程上可加阈值过滤、
查询改写，或走兜底回复。

## 七、Agent / Tool Calling

### 1. 模型会执行函数吗？

不会。模型只输出“调哪个函数、传什么参数”的 tool_calls，真正执行的是后端。
这决定了安全边界在你这边。

### 2. 工具结果以什么角色塞回？

`role=tool`，并带 `tool_call_id` 对应那次调用。模型据此知道这是上一步的结果。

### 3. 为什么限制工具循环次数？

防止模型反复调工具造成死循环，烧 token、超时、成本失控。本项目手写版 3 轮，
LangGraph 版 `recursion_limit=10`。

### 4. 写库工具为什么需要确认？

高风险操作一旦误判就真实落库。通过提示词要求用户确认 + 后端完整校验 + 当前
登录用户权限三层保护。

### 5. 工具结果为什么不能把整张表给模型？

token 成本高、无关信息干扰判断、可能泄露敏感字段。只返回回答问题需要的字段。

### 6. ReAct 是什么？

Reasoning + Acting：模型交替 Thought（想）→ Action（调工具）→ Observation（看结果），
直到能给出最终答案。解决“光想会幻觉、乱调会出错”的问题。

### 7. LangGraph 的 State/Node/Edge？

State 是图维护的共享状态（如消息列表）；Node 是执行单元（如 agent、tools）；
Edge 决定流转。普通边固定流向，条件边按函数返回值分流。

### 8. tools_condition 怎么决定下一步？

检查最后一条 AI 消息有没有 `tool_calls`：有就去 tools 节点，没有就去 END。

### 9. recursion_limit？

限制图内 agent⇄tools 来回次数，防止空转。超过就抛错，相当于兜底熔断。

## 八、MCP

### 1. MCP 解决什么？和 Function Calling 区别？

MCP 是让模型统一连接工具/数据的开放协议，像 USB。Function Calling 是厂商
能力，MCP 是跨模型、跨应用的协议，把工具打包成服务。

### 2. Host/Client/Server？

Host 承载 AI 应用，Client 发请求，Server 提供工具/资源。本项目 Agent 是 Client，
`mcp_server.py` 是 Server。

### 3. 为什么公开 MCP Server 一般只暴露读工具？

无状态公开协议难做细粒度鉴权，写操作风险高。本项目把写库留在带 JWT 的
Agent 里，MCP 只提供读。

### 4. 你的 Agent 怎么接入 MCP？

通过 `langchain_mcp_adapters` 的客户端加载 MCP 工具，失败则回退到本地工具，
保证可用性。

### 5. MCP 传输方式？

stdio 本地进程，SSE 和 streamable HTTP 用于远程。本项目用 streamable HTTP。

## 九、流式与工程化

### 1. SSE 和 WebSocket？为什么 AI 用 SSE？

SSE 单向服务器推送、走 HTTP、实现简单；WebSocket 双向、协议重。AI 输出主要是
服务器持续吐字，SSE 足够。

### 2. SSE 消息格式？

每条以 `data:` 开头，以空行 `\n\n` 结束，多条连续推送。

### 3. 为什么不用 EventSource？

EventSource 只支持 GET，不能自定义 Authorization 头。项目要带 JWT，
所以用 fetch + ReadableStream。

### 4. 代理为什么关缓冲？

Nginx/Vite 默认缓冲响应，SSE 会被攒成一大段才吐。关掉 `proxy_buffering`
和 `cache`，过程事件才能实时到前端。

### 5. 流式中文半个字节被截断？

TCP 拆包可能把多字节字符拆开。用 `TextDecoder.decode(chunk, {stream:true})`
让解码器暂存不完整字节，配合 buffer 攒到完整再解析。

### 6. Docker 多服务怎么通信？healthcheck 作用？

同一 compose 网络里用服务名互访，如 `backend` 连 `postgres:5432`。
healthcheck 标记服务就绪，`depends_on: condition: service_healthy` 让依赖方
等它就绪再启动。

## 十、项目场景题

### 1. 介绍 Agent 完整调用链

前端 fetch SSE → FastAPI → Redis 限流 → LangGraph 图 → 模型判断是否调工具 →
工具查 RAG/SQL → 结果还给模型 → 需要确认时复述请求确认 → 确认后写库 → SSE 推回。

### 2. “帮我预约明天下午的实验室”每一步？

先 `get_today` 算日期 → `list_open_labs` 查开放实验室 → 复述实验室、日期、时段
请求确认 → 用户说“确认”后 `create_lab_reservation` 走业务校验落库 → 返回待审核。

### 3. 模型把日期听错怎么兜底？

后端 `create_reservation` 校验日期不能是过去、时段在开放时间内、时段不冲突，
模型传错参数会得到明确错误，再由模型向用户澄清。

### 4. 两人同时约同一时段？

本项目用“先查再插”的冲突检测，学习项目够用；生产要加数据库唯一约束或锁。
诚实说明这个局限是加分项。

### 5. 模型反复调同一工具？

限制轮数 + 检测重复调用 + 超时熔断。本项目 `recursion_limit` 兜底。

### 6. 知识库更新了旧答案没变？

向量没重新生成。本项目删除向量库目录或重启重灌；生产应做增量更新和缓存失效。

### 7. 怎么统计成本和延迟？

记录每次 LLM 调用的 token、耗时、工具链路，接入 Langfuse/LangSmith 或自建日志，
按用户/工具聚合出报表。

### 8. 部署到生产还缺什么？

数据库迁移(Alembic)、配置中心、日志与监控、CI/CD、HTTPS、限流与告警、测试。

## 十一、手写/设计题

### 1. 手写 Redis 限流

见“四、2”的代码：INCR + EXPIRE + 超阈值返回 429。

### 2. 设计预约表结构

```text
reservations(id, user_id FK, lab_id FK, equipment_id FK 可空,
             date, start_time, end_time, status, remark, create_time)
索引：user_id、lab_id、(lab_id,date,start_time)
```

status：0 待审核 1 已通过 2 已拒绝 3 已取消。

### 3. 二分查找

```python
def binary_search(nums, target):
    left, right = 0, len(nums) - 1
    while left <= right:
        mid = (left + right) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
```

### 4. 设计一个 RAG 系统

文档加载 → 切块 → embedding 写入向量库 → 用户问题向量化 → 混合检索 →
rerank 精排 → 拼进 Prompt → LLM 生成 → 记录评估指标。

### 5. 多 Agent 分工

规划者拆任务、执行者调工具干活、评审者检查结果。它们通过共享状态或消息传递
协作，LangGraph 可用 supervisor 拓扑实现。

## 十二、反问面试官

这部分没有标准答案，挑 2 个问：

- 团队现在 Agent 用 LangGraph 还是自研编排？为什么这么选？
- 目前 Agent 最大的工程痛点是什么？
- 实习生进来会先负责哪一块？
- 团队怎么评估 Agent 质量？

## 使用建议

每天练 5 题，先口头回答再看答案；讲不清就回 `docs/01-17` 补原理。
最后三天重点过第七、十、十一部分。
