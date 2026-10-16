# 16 · Redis、PostgreSQL 与 Docker 部署

## 1. Redis 在本项目里的两个用途

### 1.1 限流

AI 接口很贵，必须防止被刷。用 `INCR + EXPIRE` 实现滑动窗口式的每分钟限流：

```text
key = ai:ratelimit:{user_id}
每次请求 INCR
第一次设置 60 秒过期
超过阈值返回 429
```

代码在 [rate_limit.py](../../backend/app/dependencies/rate_limit.py)。

### 1.2 缓存

相似问题的 RAG 检索结果可以缓存，减少重复向量检索：

```python
cache_key = "rag:" + md5(query)
```

代码在 [kb_service.py](../../backend/app/services/kb_service.py)。

## 2. PostgreSQL + pgvector

PostgreSQL 当业务主库，`pgvector` 扩展让它也能存向量。于是：

```text
PostgreSQL -> 用户、实验室、预约等关系数据
pgvector / Milvus -> 向量检索
```

关系查询和向量检索可以各取所长。

## 3. Docker 部署架构

[docker-compose.yml](../../docker-compose.yml) 包含：

```text
postgres(pgvector)  关系库
redis               缓存/限流
backend             FastAPI + LangGraph Agent
frontend            nginx + 打包好的 Vue3
```

一条命令：

```bash
docker compose up --build
```

## 4. 前后端在容器里怎么通信

浏览器访问 nginx，nginx 把 `/api/` 反代给 `backend:8000`。
SSE 流式输出需要关闭代理缓冲，否则过程事件会卡住：

```nginx
proxy_buffering off;
proxy_cache off;
```

## 5. 面试答法

“我用 Redis 做 AI 接口限流和相似问题缓存，PostgreSQL 存关系数据、pgvector/Milvus
存向量，最后用 Docker Compose 把数据库、Redis、后端、前端一起编排部署。”

## 6. 练习清单

- 自己写一遍 `INCR + EXPIRE` 限流。
- 把项目用 `docker compose up` 跑起来。
- 说说为什么 nginx 反代 SSE 要关缓冲。
