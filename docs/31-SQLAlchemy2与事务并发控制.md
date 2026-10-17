# 31 · SQLAlchemy 2.x 与事务并发控制

> **速成定位**：简历里最硬的一段。「你怎么防止两个人同时订到同一时段」——这道题答好了，面试官基本认定你懂后端。
> **一句话**：用 `SELECT ... FOR UPDATE` 行锁把并发串行化，用区间重叠算法 `A.start < B.end AND A.end > B.start` 判断时间冲突，再用显式事务边界保证 commit 失败能回滚。

---

## 目录

1. [ORM 与 SQLAlchemy 2.x 新写法](#1-orm-与-sqlalchemy-2x-新写法)
2. [Engine、Session 与连接池](#2-enginesession-与连接池)
3. [声明式模型与公共字段](#3-声明式模型与公共字段)
4. [事务边界：commit 失败必须 rollback](#4-事务边界)
5. [并发控制：从「先查后插」的竞态说起](#5-并发控制)
6. [区间重叠算法](#6-区间重叠算法)
7. [Alembic 迁移](#7-alembic-迁移)
8. [最小可运行骨架](#8-最小可运行骨架)
9. [项目里对应哪块代码](#9-项目里对应哪块代码)
10. [面试高频问答](#10-面试高频问答)
11. [速记卡](#11-速记卡)

---

## 1. ORM 与 SQLAlchemy 2.x 新写法

**ORM（对象关系映射）** 把表映射成类、行映射成对象：

```python
db.query(Lab).filter(Lab.id == 1).first()   # 不用手写 SELECT * FROM labs WHERE id=1
```

好处：换数据库不用改代码、防 SQL 注入（参数化）、关联关系自动加载。
代价：复杂查询性能不如原生 SQL、有 N+1 陷阱。

### 2.0 的新写法（项目用的就是这个）

旧写法（1.x）：

```python
class Lab(Base):
    __tablename__ = "labs"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
```

新写法（2.x，类型注解驱动）：

```python
class Lab(Base):
    __tablename__ = "labs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
```

**为什么更好**：`Mapped[int]` 让静态类型检查器和 IDE 能推断字段类型，写错字段名在编辑器里就能发现。项目实测版本 SQLAlchemy **2.1.4**。

---

## 2. Engine、Session 与连接池

三个概念必须分清（面试爱问）：

| 概念 | 是什么 | 生命周期 |
| --- | --- | --- |
| **Engine** | 连接池 + 方言，真正管 TCP 连接 | 全局单例，进程启动建一次 |
| **Session** | 一次「工作单元」，跟踪对象改动，管事务 | 每请求一个，用完关 |
| **SessionLocal** | 会话工厂（`sessionmaker`） | 全局单例 |

本项目 `database.py:20-31`：

```python
if settings.DATABASE_URL:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,     # 每次取连接前先探活，避免拿到被 DB 断掉的连接
        pool_size=10,           # 常驻连接数
        max_overflow=20,        # 峰值可临时再开 20 个
    )
else:
    engine = create_engine(
        "sqlite:///./lab_agent.db",
        connect_args={"check_same_thread": False},  # SQLite 多线程必需
    )
```

- **`pool_pre_ping=True`**：数据库可能主动断开空闲连接，不探活就会偶发「connection has been closed」。
- **`check_same_thread=False`**：SQLite 默认只允许创建连接的线程使用，FastAPI 的线程池会跨线程，必须关掉。

```python
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

- **`autoflush=False`**：查询前不自动把未提交的改动刷进库。项目刻意关掉，让「什么时候写库」完全可控（数据库注释里写明了原因）。
- **`autocommit=False`**：显式事务，必须手动 `commit()`。

---

## 3. 声明式模型与公共字段

`database.py:54-66` 定义公共基类：

```python
class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="主键ID")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
```

**注意两个细节**：
- `default=datetime.now` 传的是**函数本身**不是 `datetime.now()`（后者会在导入时求值一次，所有行时间相同）。
- `onupdate=datetime.now` 更新时自动刷新时间。

5 张表（`backend/app/models/`）：

| 表 | 文件 | 关键字段 |
| --- | --- | --- |
| `users` | `user.py` | username, password, name, **role**, email, phone, avatar, status |
| `labs` | `lab.py` | name, location, capacity, open_time, close_time, status |
| `equipments` | `equipment.py` | lab_id, name, spec, quantity, status |
| `reservations` | `reservation.py` | user_id, lab_id, equipment_id, date, start_time, end_time, **status** |
| `kb_documents` | `kb_document.py` | id(32位字符串), filename, size_bytes, sha256, status |

**预约状态机**（面试要能说）：`0=待审核 → 1=已通过 / 2=已驳回`，`3=已取消`。只有 `status in [0,1]` 的预约才占用时段。

---

## 4. 事务边界

### 为什么必须显式 rollback

错误写法（很多项目这么写）：

```python
db.add(reservation)
db.commit()          # 如果这里抛异常（唯一键冲突 / 网络断开）
# 会话里还残留着未回滚的脏状态；若这个会话被复用，后续查询行为不可预期
```

正确写法（本项目 `reservation_service.py:89-94`）：

```python
db.add(reservation)
try:
    db.commit()
except Exception:
    db.rollback()
    raise
```

`raise` 不能省——吞掉异常会让上层以为成功了。

### 第二道防线：get_db 兜底

`database.py:37-51`：

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()      # 兜底：业务代码忘了 rollback，这里保证不留脏会话
        raise
    finally:
        db.close()
```

> **面试话术**：「业务层四处写库都包了 try/commit/except/rollback，另外 `get_db` 依赖里还有一层兜底回滚。两层不是重复，是**纵深防御**——业务层负责精确回滚，`get_db` 保证任何漏网的异常也不会把脏会话还回去。」

项目里四处写库全部补齐（这是之前代码审查发现并修复的缺陷 C1）：

| 函数 | 位置 |
| --- | --- |
| `create_reservation` | `reservation_service.py:90-94` |
| `cancel_reservation` | `reservation_service.py:137-141` |
| `audit_reservation` | `reservation_service.py:153-157` |
| `expire_pending_reservations` | `reservation_service.py:174-178` |

---

## 5. 并发控制

### 5.1 「先查后插」的竞态

朴素写法：

```python
conflict = db.query(Reservation).filter(...).first()
if conflict:
    raise BusinessException("该时段已预约")
db.add(Reservation(...))
db.commit()
```

两个请求同时进来：

```text
时刻1  请求A 查询冲突 → 无
时刻2  请求B 查询冲突 → 无     ← A 还没插入，B 也看不到
时刻3  请求A 插入提交 → 成功
时刻4  请求B 插入提交 → 成功   ← 双重预订！
```

**这是典型的 check-then-act 竞态**，在高并发下必然出现。

### 5.2 解法：悲观锁 `SELECT ... FOR UPDATE`

`reservation_service.py:41`：

```python
lab = db.query(Lab).filter(Lab.id == data.lab_id).with_for_update().first()
```

`with_for_update()` 生成的 SQL：

```sql
SELECT * FROM labs WHERE id = 1 FOR UPDATE;
```

**语义**：数据库对命中的行加**排他行锁**，在事务提交前，其它事务也想 `FOR UPDATE` 这一行就必须**阻塞等待**。于是：

```text
请求A 拿到 lab 行锁 → 查冲突(无) → 插入 → commit(释放锁)
请求B 阻塞等待...  → 拿到锁 → 查冲突(发现A的记录) → 抛「该时段已预约」
```

**贯穿始终的考点**：加锁之后**必须重新查冲突**，不能复用加锁前的查询结果。

### 5.3 为什么锁「实验室行」而不是「预约表」

这是本项目的设计巧思，面试要讲：

> 预约表里**还没有**要锁的行（新预约尚未插入），所以没法锁预约记录。锁**父实体（实验室）**相当于把「同一实验室的所有预约操作」串行化——这是一种**用父行做锁粒度**的常见手法，比锁整张表性能好得多。

### 5.4 SQLite 下的行为

项目注释（`reservation_service.py:39-40`）如实写明：

```python
# Postgres 下会生成 SELECT ... FOR UPDATE；SQLite 忽略该子句，靠写锁串行。
```

SQLite 不支持 `FOR UPDATE`，但它对整个数据库文件加写锁，天然串行，所以**功能上仍然正确**。这是诚实的表述，面试时主动说出来是加分项。

### 5.5 悲观锁 vs 乐观锁（面试对比题）

| | 悲观锁（`FOR UPDATE`） | 乐观锁（版本号） |
| --- | --- | --- |
| 假设 | 冲突频繁，先锁再操作 | 冲突少，提交时校验 |
| 实现 | `with_for_update()` | `version` 字段 + `UPDATE ... WHERE version = ?` |
| 代价 | 阻塞等待、可能死锁 | 冲突时要重试 |
| 适用 | 本项目这种**冲突代价高**的场景（超卖/双重预订） | 读多写少 |

本项目选悲观锁，因为「两个人订到同一时段」的后果是**业务事故**，宁可让第二个请求阻塞等待。

---

## 6. 区间重叠算法

`reservation_service.py:60-75`：

```python
query = db.query(Reservation).filter(
    Reservation.lab_id == data.lab_id,
    Reservation.date == data.date,
    Reservation.status.in_([0, 1]),          # 只算待审核 + 已通过
    Reservation.start_time < data.end_time,   # A.start < B.end
    Reservation.end_time > data.start_time,   # A.end   > B.start
)
```

### 为什么这个公式对

两个区间 `[A.start, A.end)` 和 `[B.start, B.end)` **重叠，当且仅当**：

```text
A.start < B.end   AND   A.end > B.start
```

画个数轴验证（面试可以直接画图讲）：

```text
情况1  A: |-----|          B:        |-----|     不重叠：A.end <= B.start ✓ 排除
情况2  A:        |-----|   B: |-----|            不重叠：A.start >= B.end ✓ 排除
情况3  A:   |--------|      B:    |-----|        重叠：两条件都成立 ✓ 命中
情况4  A:    |--|           B: |-----------|     包含：两条件都成立 ✓ 命中
```

**边界处理**：用 `<` 和 `>`（严格不等），所以「A 结束于 14:00，B 开始于 14:00」判定为**不冲突**——这正是我们想要的，背靠背预约是合法的。

### 设备预约的额外条件

```python
if data.equipment_id:
    query = query.filter(Reservation.equipment_id == data.equipment_id)
else:
    query = query.filter(Reservation.equipment_id.is_(None))
```

**关键点**：预约实验室（不带设备）时，只和「同样不带设备」的预约比；预约某设备时，只和「同一个设备」的预约比。如果不加这层过滤，「订实验室」会被「订该实验室某设备」的记录误判为冲突。

### 幂等性由此天然成立

项目注释（`reservation_service.py:62-63`）写明了这个结论：

> 冲突检测覆盖 `status in [0,1]`，配合行锁，**重复提交同一时段会命中冲突而被拒绝**，所以不需要额外的幂等表。

---

## 7. Alembic 迁移

**为什么不用 `create_all`**：`create_all` 只会创建**不存在的表**，字段变了它不管。Alembic 记录版本化的变更脚本，可前进可回退。

本项目 `backend/alembic/versions/` 有 **2 个迁移**：

```text
0001_initial_schema.py     初始 4 张业务表
0002_add_kb_documents.py   新增知识库文档表（后加的功能）
```

启动时的策略（`main.py:32-34`）：

```python
if not settings.DATABASE_URL:
    Base.metadata.create_all(bind=engine)   # SQLite：零配置直接建表
```

即：**PostgreSQL 走 Alembic（`alembic upgrade head`），SQLite 零配置用 `create_all`**。

常用命令（面试背这三个）：

```bash
alembic revision --autogenerate -m "说明"   # 对比模型与库，生成迁移脚本
alembic upgrade head                        # 升到最新
alembic downgrade -1                        # 回退一个版本
```

> ⚠️ **面试提醒**：`--autogenerate` 生成后**必须人工检查**，它识别不出「字段重命名」（会变成 drop + add，丢数据）。

---

## 8. 最小可运行骨架

存成 `mini_concurrent.py` 直接跑（`pip install sqlalchemy`）。它用真实 SQLite 演示**行锁 + 区间重叠**的效果。

```python
"""最小骨架：SQLAlchemy 2.x 模型 + 事务边界 + 区间重叠冲突检测。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


# ============ 1. 公共基类：抽公共字段 ============
class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 注意 default 传函数本身，不是调用结果
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ============ 2. 模型：类型注解驱动 ============
class Lab(Base):
    __tablename__ = "labs"
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=1)   # 1=开放 0=关闭


class Reservation(Base):
    __tablename__ = "reservations"
    lab_id: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)
    start_time: Mapped[str] = mapped_column(String(20), nullable=False)
    end_time: Mapped[str] = mapped_column(String(20), nullable=False)
    # 0=待审核 1=已通过 2=已驳回 3=已取消
    status: Mapped[int] = mapped_column(Integer, default=0)


# ============ 3. Engine + 会话工厂 ============
engine = create_engine("sqlite:///./mini.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


class BizError(Exception):
    """业务异常：可预期的错误分支。"""


# ============ 4. Service：业务规则 + 并发控制 ============
def create_reservation(db, lab_id: int, date: str, start: str, end: str) -> int:
    """创建预约，核心是「加锁 → 重查冲突 → 插入 → 事务提交」。"""
    if end <= start:
        raise BizError("结束时间必须晚于开始时间")

    # (1) 悲观锁：把同一实验室的预约操作串行化。
    #     Postgres 生成 SELECT ... FOR UPDATE；SQLite 忽略该子句（靠写锁串行）。
    lab = db.execute(
        select(Lab).where(Lab.id == lab_id).with_for_update()
    ).scalar_one_or_none()
    if not lab:
        raise BizError("实验室不存在")
    if lab.status != 1:
        raise BizError("实验室已关闭")

    # (2) 加锁之后【重新】查冲突：区间重叠 A.start < B.end AND A.end > B.start
    conflict = db.execute(
        select(Reservation).where(
            Reservation.lab_id == lab_id,
            Reservation.date == date,
            Reservation.status.in_([0, 1]),        # 只有待审核/已通过占用时段
            Reservation.start_time < end,          # A.start < B.end
            Reservation.end_time > start,          # A.end   > B.start
        )
    ).scalar_one_or_none()
    if conflict:
        raise BizError("该时段已预约")

    # (3) 插入
    res = Reservation(lab_id=lab_id, date=date, start_time=start, end_time=end, status=0)
    db.add(res)

    # (4) 显式事务边界：commit 失败必须 rollback，避免会话残留脏状态
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return res.id


# ============ 5. 自测：验证冲突检测 ============
if __name__ == "__main__":
    db = SessionLocal()
    db.add(Lab(name="量子实验室", status=1))
    db.commit()

    ok = create_reservation(db, 1, "2026-10-18", "14:00", "15:00")
    print(f"第一次预约成功 id={ok}")

    # 同样的时段再订一次 → 应命中冲突
    try:
        create_reservation(db, 1, "2026-10-18", "14:30", "15:30")
        print("❌ 没有拦截到冲突，逻辑有问题")
    except BizError as e:
        print(f"✅ 重叠时段被拦截：{e}")

    # 背靠背时段（15:00 开始）→ 应允许，这是边界正确性的关键
    ok2 = create_reservation(db, 1, "2026-10-18", "15:00", "16:00")
    print(f"✅ 背靠背时段允许预约 id={ok2}")
    db.close()
```

**跑出来的预期输出**：

```text
第一次预约成功 id=1
✅ 重叠时段被拦截：该时段已预约
✅ 背靠背时段允许预约 id=2
```

这三行输出就是你对着面试官讲并发控制的**实证**。

---

## 9. 项目里对应哪块代码

### 9.1 基础设施

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| Engine + 连接池 | `database.py:20-31` | PG 走 `pool_pre_ping/pool_size=10/max_overflow=20`，SQLite 走 `check_same_thread=False` |
| SessionLocal | `database.py:34` | `autoflush=False, autocommit=False` |
| `get_db` 依赖 | `database.py:37-51` | yield 会话 + **`except: rollback()` 兜底** + `finally: close()` |
| Base 公共字段 | `database.py:54-66` | `id / create_time / update_time` |

### 9.2 并发控制核心（必背行号）

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| **悲观行锁** | `reservation_service.py:41` | `db.query(Lab).filter(...).with_for_update().first()` |
| **区间重叠** | `reservation_service.py:64-70` | `start_time < end AND end_time > start`，`status.in_([0,1])` |
| **设备分流** | `reservation_service.py:71-74` | 有设备按设备比，无设备按 `equipment_id.is_(None)` 比 |
| **事务边界** | `reservation_service.py:89-94` | `try: commit / except: rollback; raise` |
| 状态过滤 | `reservation_service.py:67` | `status in [0,1]`（待审核+已通过才占时段） |

### 9.3 其它三处事务边界

- 取消：`reservation_service.py:137-141`
- 审核：`reservation_service.py:153-157`
- 过期扫描：`reservation_service.py:174-178`（后台任务自己开 `SessionLocal()`，`finally: db.close()`）

### 9.4 后台过期任务

`reservation_service.py:183-187`：

```python
async def run_expire_scan() -> None:
    while True:
        expire_pending_reservations()
        await asyncio.sleep(60)
```

由 `main.py:47` 用 `asyncio.create_task` 启动，`main.py:49` 在关闭时 `task.cancel()`。

> **面试注意**：这是个简化实现（轮询全表）。真实生产应该用定时任务框架（APScheduler / Celery beat）或数据库的过期索引，面试官若追问，主动说「我知道轮询全表在数据量大时不合适，生产会换成定时调度 + 按时间索引过滤」。

### 9.5 关联查询与 N+1

`reservation_service.py:117-124` 遍历时访问 `item.user.name`、`item.lab.name`，依赖 `models/reservation.py:33-35` 的 `relationship()`。

> 数据量小时问题不大；数据量大应该用 `selectinload()` 预加载，否则每条记录都多查一次用户表和实验室表（N+1）。**这是你可以主动承认并给出改进方向的点。**

---

## 10. 面试高频问答

**Q1：怎么防止两个人同时订到同一时段？**
> 三层保障：① `with_for_update()` 对实验室行加排他锁，把同一实验室的并发操作串行化；② 加锁后重新用区间重叠算法查冲突 `A.start < B.end AND A.end > B.start`，且只算 `status in [0,1]` 的记录；③ 两道都过了才插入并 `commit`。我有并发集成测试验证两个线程抢同一时段只有一个成功。

**Q2：为什么加锁后还要再查一次冲突？**
> 因为加锁前查到的结果在等待锁期间可能已经失效（另一个事务刚提交）。`FOR UPDATE` 保证的是**从拿到锁到提交这段时间的独占**，所以必须在锁内重新读。

**Q3：为什么用悲观锁不用乐观锁？**
> 双重预订的代价是业务事故，冲突概率在热门时段并不低。悲观锁让第二个请求阻塞等待而不是失败重试，用户体验更可控。乐观锁更适合读多写少、冲突代价低的场景。

**Q4：SQLite 下 `FOR UPDATE` 无效怎么办？**
> SQLite 不支持该子句，但它对数据库文件加写锁，天然串行，所以功能仍然正确。项目注释里如实写了这一点。生产环境我用 PostgreSQL，行锁是真的生效的。

**Q5：commit 失败为什么要 rollback？**
> commit 抛异常（唯一键冲突、连接断开）时，会话里还有未刷出的改动和未结束的事务。不 rollback 就把脏会话还回去，后续在这个会话上的查询结果不可预期。项目里业务层四处写库都包了 try/commit/except/rollback，`get_db` 依赖里还有一层兜底回滚。

**Q6：区间重叠为什么用严格不等号？**
> 用 `<` 和 `>` 而非 `<=` `>=`，使得「A 到 15:00 结束，B 从 15:00 开始」判定为不冲突——背靠背预约是合法业务，这是我特意验证过的边界。

**Q7：`autoflush=False` 是什么意思？**
> 默认 `autoflush=True` 时，每次查询前 SQLAlchemy 会先把未提交的改动自动刷进数据库，容易产生意料之外的写入。关掉之后「什么时候写库」完全由我的代码控制，行为更可预测。

**Q8：预约的幂等性怎么保证？**
> 冲突检测覆盖 `status in [0,1]`，重复提交同一时段会命中冲突被拒绝，所以天然幂等，不需要额外的幂等表或唯一索引。我评估过加应用层查重的方案，但它会破坏「两线程抢同一时段应返回 busy」的互斥语义，所以没加。

---

## 11. 速记卡

```text
SQLAlchemy 2.x：Mapped[int] + mapped_column(...)  类型注解驱动
Engine(全局,连接池) / Session(每请求) / sessionmaker(工厂)
pool_pre_ping=True 防断连；SQLite 需 check_same_thread=False
autoflush=False 行为可控；autocommit=False 显式事务

Base 公共字段：id / create_time(default=datetime.now 传函数) / update_time(onupdate)

并发三重奏：
  1. with_for_update()  锁父实体(实验室行)，因为新预约还没有行可锁
  2. 锁内重查冲突：status.in_([0,1])
  3. 区间重叠 A.start < B.end AND A.end > B.start（严格不等 → 背靠背合法）

事务：try: commit / except: rollback; raise   ← 业务层 4 处
      get_db 里 except: rollback()            ← 第二道防线
悲观锁(串行/冲突代价高) vs 乐观锁(版本号/读多写少)

Alembic：revision --autogenerate / upgrade head / downgrade -1
         2 个迁移；PG 走 Alembic，SQLite 走 create_all
```
