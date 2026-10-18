# 25 · Windows 下安装与部署 PostgreSQL / Docker

> 写给：没在 Windows 上装过这两样、但 WSL 里已经有 PostgreSQL 的你。
> 你的环境：Windows 11 家庭版、CPU 虚拟化已开启、内存 15 GB、磁盘充足。

---

## 0. 先想清楚：你到底需要哪一个？

这个项目把「数据库」和「向量库」分得很开，所以**PostgreSQL 和 Docker 不是都要装**：

| 你想干什么 | 需要装什么 | 难度 |
| --- | --- | --- |
| 只想让项目用 **pgvector** 跑起来（开发） | **什么都不用装**——直接复用 WSL 里的 PostgreSQL | ⭐ |
| 想学 Docker / 体验一键部署 | Docker Desktop | ⭐⭐⭐ |
| 想把整个项目打包给别人 | Docker Desktop + compose | ⭐⭐⭐ |

**结论：先走路线 A（复用 WSL 的 PostgreSQL），5 分钟搞定；Docker 想学再装。**

---

## 路线 A：复用 WSL 里已有的 PostgreSQL（推荐）

### A.1 原理：WSL2 的 localhost 转发

WSL2 默认开启 `localhostForwarding`：**Windows 访问 `127.0.0.1:5432`，会自动转发到 WSL 里的 5432 端口**。
所以 Windows 上跑的后端不用改任何地址，`backend/.env` 里写的
`postgresql+psycopg2://postgres:123456@127.0.0.1:5432/lab_agent` 直接就能连上 WSL 的库。

前提是：**WSL 里的 PostgreSQL 正在运行**，并且装了 **pgvector** 扩展（项目要存向量）。

### A.2 在 WSL 里执行（打开 WSL 终端）

开始菜单搜「Ubuntu」或「WSL」，或在 PowerShell 里输入 `wsl` 回车，就进入 Linux 环境。

我把所有步骤写成了一个脚本 `scripts/setup-pg-wsl.sh`，你只需要：

```bash
# 在 WSL 里进入项目目录（Windows 的 D 盘挂在 /mnt/d）
cd /mnt/d/Work/projects/lab_agent_std/scripts
bash setup-pg-wsl.sh
```

脚本会做这五件事（你也可以手动逐步执行）：

```bash
# 1. 启动 PostgreSQL
sudo service postgresql start

# 2. 装 pgvector（假设你的 PG 是 16，psql --version 能查到版本号）
sudo apt-get update
sudo apt-get install -y postgresql-16-pgvector
#   如果提示找不到包，就用源码编译：
#   sudo apt-get install -y build-essential git postgresql-server-dev-16
#   git clone --depth 1 https://github.com/pgvector/pgvector.git
#   cd pgvector && make && sudo make install

# 3. 建库 + 启用 vector 扩展
sudo -u postgres createdb lab_agent
sudo -u postgres psql -d lab_agent -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4. 给 postgres 设密码（和 .env 里的 123456 对上）
sudo -u postgres psql -c "ALTER USER postgres PASSWORD '123456';"

# 5. 重启让配置生效
sudo service postgresql restart
```

> **为什么第 4 步要设密码**：WSL 里你平时用 `sudo -u postgres psql` 是走 **peer 认证**
> （Unix socket，看 Linux 用户名，不要密码）。但 Windows 通过 TCP `127.0.0.1:5432`
> 连接时走的是 **密码认证**，postgres 默认没密码就连不上。设成 `123456` 和 `.env` 对齐即可。

### A.3 回 Windows 验证连通

```powershell
cd D:\Work\projects\lab_agent_std\backend
.\.venv-clean\Scripts\python.exe -c "from sqlalchemy import create_engine; create_engine('postgresql+psycopg2://postgres:123456@127.0.0.1:5432/lab_agent').connect(); print('PG 连接 OK')"
```

看到 `PG 连接 OK` 就通了。

### A.4 建表 + 启动

PG 模式不像 SQLite 会自动建表，要先跑迁移：

```powershell
.\.venv-clean\Scripts\python.exe -m alembic upgrade head
.\.venv-clean\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1
```

> **注意**：这次**不要**加 `$env:DATABASE_URL=""` 覆盖了——你要用 `.env` 里的 PG 配置。
> 启动日志里应看到向量后端走 pgvector，不再有「Connection refused」。

### A.5 如果 `127.0.0.1:5432` 连不上（少数情况）

某些网络配置下 localhost 转发会失效。两条排查路：

1. 改用 WSL 的真实 IP。WSL 里 `hostname -I` 拿到 IP（如 `172.x.x.x`），把 `.env` 里
   `127.0.0.1` 换成它，并在 WSL 里让 PG 监听所有地址：
   编辑 `/etc/postgresql/16/main/postgresql.conf`，把 `#listen_addresses = 'localhost'`
   改成 `listen_addresses = '*'`，再 `sudo service postgresql restart`。
2. 检查 Windows 防火墙是否拦了 5432 入站。

---

## 路线 B：装 Docker Desktop（学 Docker / 一键部署）

### B.1 你的机器满足条件

| 要求 | 你的情况 |
| --- | --- |
| Windows 10 2004+ / Windows 11 | ✅ Win11 家庭版（Build 26200） |
| CPU 虚拟化开启 | ✅ 已开启 |
| 内存 ≥ 4 GB | ✅ 15 GB |
| WSL2 | ✅ 已有 |

> 家庭版**也能**用 Docker Desktop——装的时候选 **WSL 2 后端**（默认就是），
> 不选 Hyper-V（Hyper-V 后端才要专业版）。

### B.2 安装步骤

1. 下载安装包：<https://www.docker.com/products/docker-desktop/> 点「Download for Windows - AMD64」（约 500 MB）。
2. 双击运行，**保持勾选「Use WSL 2 instead of Hyper-V」**（家庭版必须用它）。
3. 装完**重启电脑**。
4. 重启后打开 Docker Desktop，等左下角鲸鱼图标变绿（Engine running）。
5. 验证（新开 PowerShell）：
   ```powershell
   docker version
   docker run hello-world
   ```
   能拉取并打印欢迎信息就装好了。

> 安装时它会让你登出/登入一次以启用 WSL 集成，这是正常现象。

### B.3 用 Docker 跑整个项目

compose 里会起 4 个容器：postgres(pgvector)、redis、backend、frontend。
**我已经把 compose 的几个坑修好了**（见第 3 节），现在直接：

```powershell
cd D:\Work\projects\lab_agent_std
# 首次构建会拉镜像 + 装依赖，要几分钟
docker compose up --build
```

然后打开 <http://127.0.0.1:5175/>（前端）和 <http://127.0.0.1:8000/docs>（接口文档）。

停止与清理：

```powershell
docker compose down          # 停掉但保留数据
docker compose down -v       # 连数据卷一起删（重置数据库）
```

---

## 3. 我帮你修好的 Docker 部署缺陷

之前 `docker-compose.yml` 直接 `up` 是跑不起来的，这次一并修了：

| 缺陷 | 后果 | 修复 |
| --- | --- | --- |
| backend 没跑 `alembic upgrade head` | PG 模式下首次启动必崩（main.py 不做 create_all） | compose 里 command 改为先迁移再启动 |
| `VECTOR_BACKEND: milvus` 但没定义 Milvus 容器 | 后端起向量库时报错 | 改为 `pgvector`（compose 本来就有 pgvector 版 PG，一物两用） |
| 没有 `.dockerignore` | `COPY . .` 把 `.env`（含密钥）打进镜像 | 新增 `backend/.dockerignore`、`frontend/.dockerignore` |
| nginx 缺 `proxy_read_timeout` | 默认 60 秒切断逐字吐 token 的 SSE 长连接 | `frontend/nginx.conf` 加 `proxy_read_timeout 3600s` |

> **一个待你验证的点**：`alembic` 目前只有两个迁移脚本（`0001_initial_schema`、
> `0002_add_kb_documents`）。如果 `docker compose up` 后后端报「表不存在」，
> 说明迁移脚本没覆盖所有表——那种情况下最省事的做法是临时把 `main.py` 里
> PG 分支也加上 `Base.metadata.create_all(bind=engine)` 兜底。

---

## 4. 验证清单

路线 A 跑通后应满足：

- [ ] WSL 里 `sudo service postgresql status` 显示 online
- [ ] Windows 侧 `PG 连接 OK`
- [ ] `alembic upgrade head` 无报错
- [ ] 后端启动日志有 `Application startup complete`，向量后端是 pgvector
- [ ] AI 助手问「实验室开放时间是几点」能命中《开放时间.md》

路线 B 跑通后应满足：

- [ ] `docker compose ps` 四个容器都是 running/healthy
- [ ] `docker compose logs backend` 里有 `Application startup complete`
- [ ] <http://127.0.0.1:5175/> 能登录（admin/123456）

---

## 5. 常见问题

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| WSL 连不上 PG | 服务没起 | `sudo service postgresql start` |
| 密码认证失败 | 没设密码 / hba 不允许 | 跑脚本第 4、6 步 |
| `Connection refused` | PG 没监听 5432 | 确认 `ss -ltnp \| grep 5432` |
| Docker 拉镜像超时 | 网络被墙 | 配镜像加速器：设置 → Docker Engine → `registry-mirrors` |
| compose 起 backend 一直 restart | alembic 迁移失败 | `docker compose logs backend` 看具体错误 |
| 端口 8000/5175 被占 | 本地手动起过服务 | 先停掉手动起的，或改 compose 端口映射 |
| 前端报 `EACCES 127.0.0.1:517x` | Radmin VPN 的 RvControlSvc 以 Bound 状态预占了一批端口（1030–14995 区间），Vite 对 EACCES 不会自动换端口 | 换空闲端口改 `vite.config.js` 的 `server.port`，或退出 Radmin VPN |
