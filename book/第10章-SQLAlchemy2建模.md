# 第 10 章 · SQLAlchemy 2.0 建模

## 开篇：为什么 2.0 的写法和网上教程不一样

你搜「SQLAlchemy 查询」，90% 的结果是这样的：

```python
# 1.x 写法
users = session.query(User).filter(User.name == "张三").all()
```

但 SQLAlchemy 2.0 推荐这样：

```python
# 2.0 写法
stmt = select(User).where(User.name == "张三")
users = session.execute(stmt).scalars().all()
```

**两种都能跑**（2.0 保留了 `query()` 兼容），但 2.0 的新写法有实质优势：

| | 1.x `query()` | 2.0 `select()` |
|---|---|---|
| 类型提示 | 弱 | **强**（IDE 能补全、能检查） |
| 组合性 | 差 | 强（可以拼装、复用） |
| 异步支持 | ❌ | ✅（`AsyncSession`） |
| 官方定位 | 遗留 API | 主推 |

> ⚠️ **面试重要**：如果你简历写 SQLAlchemy 2.0，面试官问「2.0 和 1.x 有什么区别」，答不上来就会被认为是「用了新版本但写着旧代码」。这一章就是要让你真的说出区别。

---

## 一、2.0 的声明式建模

### 1.1 新语法三件套

```python
from sqlalchemy.orm import Mapped, mapped_column

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(50))     # 可选
    status: Mapped[int] = mapped_column(default=1)
```

| 元素 | 作用 |
|---|---|
| `Mapped[str]` | **类型注解**，告诉 SQLAlchemy 和 IDE 这个字段是 str |
| `mapped_column(...)` | 列定义（类型、约束、注释） |
| `Mapped[str \| None]` | **可选字段**（NULL 允许） |

**关键理解**：

- `Mapped[str]` → `NOT NULL`
- `Mapped[str | None]` → `NULL` 允许

**这个映射是自动的**，你不用再写 `nullable=False`。

### 1.2 对比 1.x

```python
# 1.x
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False)
    email = Column(String(50))          # 默认可空

# 2.0
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(50))
```

**2.0 的好处**：IDE 能知道 `user.username` 是 `str`，`user.email` 是 `str | None`。这样：

1. 自动补全能用
2. mypy 能检查类型错误
3. 访问 `user.email.upper()` 时 IDE 会提醒你可能是 None

> 💡 **面试话术**：「SQLAlchemy 2.0 最大的变化是类型注解驱动。`Mapped[str]` 自动映射成 NOT NULL，`Mapped[str | None]` 映射成可空。好处是 IDE 和 mypy 能真正检查——我访问一个可空字段时 IDE 会提醒我判空。1.x 的 `Column()` 写法类型信息是丢失的。」

### 1.3 主键

项目里的 5 张表，主键有两种：

```python
# 方式一：自增整数（users / labs / equipments / reservations）
class User(Base):
    id: Mapped[int] = mapped_column(primary_key=True)   # 自动推断 autoincrement

# 方式二：字符串业务主键（kb_documents）
class KbDocument(Base):
    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="文档ID")
```

**为什么 kb_documents 用字符串主键？**

因为文档 ID 要和**向量库里的 document_id** 对应。向量库（Chroma）用字符串 ID 更方便，而且文档可能来自不同来源（上传文件、内置文档），用 UUID 或哈希更合适。

**自增 ID vs UUID 的取舍**：

| | 自增 int | UUID/字符串 |
|---|---|---|
| 存储 | 小（4-8 字节） | 大（36 字节） |
| 索引性能 | 好 | 一般（随机分布） |
| 可猜测 | ✅ 能猜（安全风险） | ❌ 难猜 |
| 分布式生成 | ❌ 需要中心化 | ✅ 可本地生成 |
| 跨系统关联 | 需要映射 | 天然一致 |

---

## 二、关系建模

### 2.1 外键与 relationship

```python
class Reservation(Base):
    __tablename__ = "reservations"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), nullable=False)
    equipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("equipments.id"), nullable=True   # 可空：预约实验室时没有设备
    )

    # 关系（对象导航，不是列）
    user: Mapped[User] = relationship()
    lab: Mapped[Lab] = relationship()
    equipment: Mapped[Equipment | None] = relationship()
```

**两个概念要分清**：

| | `ForeignKey` | `relationship()` |
|---|---|---|
| 是什么 | **数据库列**（真实的外键约束） | **Python 对象导航**（不是列） |
| 在 SQL 里 | `FOREIGN KEY (user_id) REFERENCES users(id)` | 不产生列 |
| 作用 | 数据完整性 | `reservation.user.name` 这样访问 |

### 2.2 可选关系

```python
equipment_id: Mapped[int | None] = mapped_column(...)   # 可空外键
equipment: Mapped[Equipment | None] = relationship()    # 对应地，关系也要标可选
```

**如果外键可空但 relationship 没标 `| None`**，mypy 会报错。这就是类型系统的价值。

### 2.3 懒加载与 N+1 问题（重要！）

```python
reservations = session.query(Reservation).all()   # 1 次查询
for r in reservations:
    print(r.user.name)      # ← 每次访问都发一次 SELECT！N 次查询
    print(r.lab.name)       # ← 又是 N 次
```

**这就是 N+1 问题**：1 次查主表 + N 次查关联表。100 条预约 = 201 次查询。

**三种解法**：

```python
# 解法一：joinedload（LEFT JOIN 一次性查出来，推荐）
from sqlalchemy.orm import joinedload
stmt = select(Reservation).options(joinedload(Reservation.user), joinedload(Reservation.lab))
reservations = session.execute(stmt).scalars().unique().all()

# 解法二：selectinload（分两条 SQL：先查主表，再 IN 查关联表）
from sqlalchemy.orm import selectinload
stmt = select(Reservation).options(selectinload(Reservation.user))

# 解法三：查询时直接 join 并只取需要的字段
stmt = select(Reservation, User.name, Lab.name).join(User).join(Lab)
```

| 解法 | SQL 次数 | 适合 |
|---|---|---|
| `joinedload` | 1（JOIN） | 一对一、多对一 |
| `selectinload` | 2（主表 + IN 查询） | 一对多（避免 JOIN 导致行膨胀） |
| 手写 join | 1 | 只需要少量字段 |

> ⚠️ **注意 `joinedload` 的 `.unique()`**：JOIN 会产生重复的主表行（一对多时），必须加 `.unique()` 去重。

> 💡 **面试话术**：「我遇到过 N+1 问题：查预约列表时，循环里访问 `r.user.name` 导致每条记录都发一次查询，100 条记录就是 200 次查询。
>
> 解法是用 `joinedload` 预加载——它用 LEFT JOIN 一次性把关联数据查出来。注意一对多关系要用 `selectinload`，因为 JOIN 会导致行膨胀（一个预约有 5 个设备就变成 5 行），而 `selectinload` 是两条 SQL（主表 + IN 查询），没有这个问题。
>
> 另外用 `joinedload` 时要记得加 `.unique()`，因为 JOIN 会产生重复行。」

### 2.4 项目里的实际做法

回顾 `ReservationResponse`：

```python
class ReservationResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None      # ← 需要 user.name
    lab_id: int
    lab_name: str | None = None       # ← 需要 lab.name
```

说明 service 层做了关联查询。看一下典型实现：

```python
# 方式：先查主表，再批量查关联（避免 N+1）
def list_reservations(db, ...):
    rows = db.query(Reservation).filter(...).all()
    user_ids = {r.user_id for r in rows}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    # 手动拼装
    for r in rows:
        r.user_name = users.get(r.user_id).name if ...
```

**这种「手动批量查 + 拼装」也是避免 N+1 的有效手段**，虽然不如 `joinedload` 优雅，但它更灵活（可以做额外的加工）。

---

## 三、Session 的生命周期与状态

### 3.1 对象状态机

SQLAlchemy 的对象有四种状态：

```
                    db.add(obj)
   ┌──────────┐  ─────────────►  ┌──────────┐
   │ Transient│                  │ Pending  │
   │(未关联)   │  ◄─────────────  │(待插入)   │
   └──────────┘   session.rollback()  └────┬─────┘
                                            │ flush/commit
                                            ▼
   ┌──────────┐                       ┌──────────┐
   │ Detached │  ◄────────────────    │Persistent│
   │(分离)     │   session.close()     │(已持久化) │
   └──────────┘                       └──────────┘
                                            │ db.delete()
                                            ▼
                                      ┌──────────┐
                                      │ Deleted  │
                                      └──────────┘
```

| 状态 | 含义 | 怎么产生 |
|---|---|---|
| Transient | 刚 `User()` 创建，未关联 Session | - |
| Pending | `db.add()` 后，未 flush | `db.add(obj)` |
| Persistent | 已 flush，和数据库同步 | `db.commit()` / `db.flush()` |
| Detached | Session 关闭后对象仍存在 | `db.close()` |
| Deleted | 标记删除，未 commit | `db.delete(obj)` |

### 3.2 最常见的错误：DetachedInstanceError

```python
def get_reservation(db, rid):
    return db.query(Reservation).get(rid)

# 在另一个地方
r = get_reservation(db, 1)
# db 被 close 了（请求结束）
print(r.user.name)      # ❌ DetachedInstanceError!
```

**原因**：`r` 现在是 Detached 状态，访问懒加载的 `r.user` 需要发 SQL，但 Session 已关闭。

**四种解法**：

```python
# 解法一：预加载（推荐）
stmt = select(Reservation).options(joinedload(Reservation.user))

# 解法二：在 Session 关闭前访问（触发加载）
r.user.name    # 在 service 里先访问一次，加载到内存

# 解法三：转成 Pydantic / dict（推荐）
return ReservationResponse.model_validate(r)   # 用 from_attributes

# 解法四：expire_on_commit=False
SessionLocal = sessionmaker(expire_on_commit=False)
```

**解法四是全局开关**：默认 `expire_on_commit=True`，commit 后所有对象被「过期」（属性被清空，下次访问重新查库）。设成 `False` 就不会过期。

| | `expire_on_commit=True`（默认） | `False` |
|---|---|---|
| commit 后访问属性 | 重新查库 | 用内存里的值 |
| 数据新鲜度 | 高（总能拿到最新） | 低（可能是旧值） |
| DetachedInstanceError | 容易触发 | 不易触发 |
| 性能 | 每次访问可能查库 | 少查 |

> ⚠️ **权衡**：`False` 性能好、不易报错，但可能拿到过期数据。项目里用的是默认（True），配合 `model_validate` 转成 Pydantic 来规避问题。

### 3.3 flush vs commit

```python
db.add(obj)
db.flush()      # 发 INSERT 语句，但**不提交事务**
                # obj.id 此时已经有值了（自增 ID 从数据库返回）
db.commit()     # 提交事务
```

**什么时候用 flush？**

当你需要在同一个事务里拿到自增 ID 去做别的操作：

```python
reservation = Reservation(...)
db.add(reservation)
db.flush()                      # 拿到 reservation.id

log = AuditLog(reservation_id=reservation.id, ...)   # 用这个 id
db.add(log)

db.commit()                     # 一起提交（原子）
```

**flush 不是提交**——如果后面 rollback，flush 的 INSERT 也会回滚。

---

## 四、查询：2.0 风格

### 4.1 基础查询

```python
from sqlalchemy import select

# 查单个（主键）
user = db.get(User, 1)                          # 2.0 推荐（替代 query().get()）

# 条件查询
stmt = select(User).where(User.username == "张三")
users = db.execute(stmt).scalars().all()        # 返回 User 对象列表

# 查单个
stmt = select(User).where(User.username == "张三")
user = db.execute(stmt).scalar_one_or_none()    # 0 或 1 条，多条报错

# 计数
from sqlalchemy import func
stmt = select(func.count()).select_from(User)
count = db.execute(stmt).scalar()
```

**`scalars()` vs `scalar()`**：

| | 返回 |
|---|---|
| `db.execute(stmt)` | `Result` 对象（行是 tuple） |
| `.scalars()` | `ScalarResult`（行是对象） |
| `.all()` | 列表 |
| `.scalar_one_or_none()` | 单个对象或 None |
| `.scalar()` | 第一行的第一列（用于 count） |

### 4.2 复杂条件

```python
from sqlalchemy import and_, or_, not_

# AND（多个 where 就是 AND）
stmt = select(Reservation).where(
    Reservation.lab_id == 1,
    Reservation.status.in_([0, 1]),
)

# OR
stmt = select(Reservation).where(
    or_(Reservation.status == 0, Reservation.status == 1)
)

# 区间重叠（第 11 章重点）
stmt = select(Reservation).where(
    Reservation.lab_id == 1,
    Reservation.start_time < end_time,
    Reservation.end_time > start_time,
)
```

### 4.3 排序、分页

```python
stmt = (
    select(Reservation)
    .where(Reservation.user_id == user_id)
    .order_by(Reservation.date.desc(), Reservation.start_time.asc())
    .offset((page - 1) * size)
    .limit(size)
)
```

### 4.4 更新与删除

```python
# 方式一：ORM 方式（先查再改）
r = db.get(Reservation, 1)
r.status = 1
db.commit()

# 方式二：批量 UPDATE（不查直接改，性能好）
from sqlalchemy import update
stmt = (
    update(Reservation)
    .where(Reservation.lab_id == 1, Reservation.status == 0)
    .values(status=3)
)
db.execute(stmt)
db.commit()

# 批量删除
from sqlalchemy import delete
stmt = delete(Reservation).where(Reservation.status == 3)
db.execute(stmt)
db.commit()
```

**批量 UPDATE 的优势**：不需要先把对象查到内存，一条 SQL 搞定。更新 1000 条记录时差异巨大。

> ⚠️ **注意**：批量 update 会绕过 ORM 的事件钩子（比如 `@event.listens_for`），如果你的业务逻辑依赖这些钩子，要用 ORM 方式。

---

## 五、项目里的 5 张表

### 5.1 表结构总览

```
┌─────────────┐
│    users    │
│ id (PK)     │
│ username    │──┐
│ password    │  │
│ name        │  │
│ role        │  │  student / admin
│ status      │  │
└─────────────┘  │
                 │ user_id
┌─────────────┐  │
│    labs     │  │
│ id (PK)     │──┼──┐ lab_id
│ name        │  │  │
│ location    │  │  │
│ capacity    │  │  │
│ open_time   │  │  │
│ close_time  │  │  │
│ status      │  │  │
└─────────────┘  │  │
                 │  │
┌─────────────┐  │  │
│ equipments  │  │  │
│ id (PK)     │──┼──┼──┐ equipment_id (可空)
│ lab_id (FK) │  │  │  │
│ name        │  │  │  │
│ status      │  │  │  │
└─────────────┘  │  │  │
                 │  │  │
         ┌───────┴──┴──┴────┐
         │   reservations   │
         │ id (PK)          │
         │ user_id (FK)     │
         │ lab_id (FK)      │
         │ equipment_id (FK)│  可空
         │ date             │  String(20)
         │ start_time       │  String(20)
         │ end_time         │  String(20)
         │ status           │  0待审/1通过/2拒绝/3取消
         └──────────────────┘

┌─────────────────┐
│  kb_documents   │  独立表，无外键
│ id (PK) String  │  和向量库 document_id 对应
│ filename        │
│ sha256          │
│ status          │
└─────────────────┘
```

### 5.2 一个值得讨论的设计：时间存成字符串

```python
date: Mapped[str] = mapped_column(String(20), comment="预约日期")
start_time: Mapped[str] = mapped_column(String(20), comment="开始时间")
end_time: Mapped[str] = mapped_column(String(20), comment="结束时间")
```

**为什么不用 DateTime？**

| 用 String | 用 DateTime |
|---|---|
| 前后端传递方便（不用处理时区序列化） | 要处理时区、格式 |
| 字符串比较能做时段重叠判断（格式统一时） | 数据库原生支持时间函数 |
| 简单直接 | 规范 |

**这个设计的风险**：

1. **格式不统一就失效**。如果一条是 `"14:00"`，另一条是 `"14:00:00"`，字符串比较会出错
2. **跨天预约无法表达**。date 和 time 分开存，跨天的时段（22:00-次日 02:00）没法表示
3. **无法用数据库的时间函数**。比如「查询未来 7 天的预约」要手动算

**面试时怎么答？**

> 💡 **诚实 + 有判断力的答法**：
>
> 「预约时间我用的是 date + start_time + end_time 三个字符串字段。这样做的好处是前后端传递简单，不用处理时区序列化，而且时段重叠判断用字符串比较就能做——只要格式统一。
>
> 但说实话这个设计有局限：一是依赖格式严格统一，如果混进 `14:00` 和 `14:00:00` 两种格式，比较就会出错；二是没法表达跨天时段；三是没法用数据库的时间函数做范围查询。
>
> 如果要改进，我会用一个 `start_at` 和 `end_at` 两个 `DateTime` 字段（带时区），重叠判断变成标准的区间比较，也能支持跨天和范围查询。前端显示时再格式化。这是我现在会做的选择。」

**这种「知道自己设计的局限、知道怎么改进」的回答，比「我觉得这样挺好」专业得多。**

### 5.3 status 用整数

```python
status: Mapped[int] = mapped_column(
    comment="预约状态 0待审核，1已通过，2已拒绝，3已取消", default=0
)
```

**整数 vs 枚举字符串**：

| | 整数 | 字符串枚举 |
|---|---|---|
| 存储 | 小 | 大 |
| 可读性 | 差（0 是什么？） | 好（"pending"） |
| 排序 | 数值排序 | 字典序 |
| 扩展 | 加数字 | 加字符串 |
| 数据库约束 | 无（能存 99） | 可用 CHECK 或 Enum 类型 |

**项目用整数 + comment 说明**。可读性靠注释和常量维护。

**改进方案**：用 Python 的 `enum` + SQLAlchemy 的 `Enum` 类型：

```python
import enum
class ReservationStatus(enum.IntEnum):
    PENDING = 0
    APPROVED = 1
    REJECTED = 2
    CANCELLED = 3

class Reservation(Base):
    status: Mapped[ReservationStatus] = mapped_column(
        default=ReservationStatus.PENDING
    )
```

这样代码里写 `Reservation.status == ReservationStatus.PENDING`，可读性大幅提升。

---

## 六、索引与性能

### 6.1 该建哪些索引

```python
class Reservation(Base):
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"), index=True)
    date: Mapped[str] = mapped_column(String(20), index=True)
```

**索引决策依据**：看查询模式。

| 查询 | 需要的索引 |
|---|---|
| 「我的预约」`WHERE user_id = ?` | `user_id` |
| 「某实验室的预约」`WHERE lab_id = ?` | `lab_id` |
| 「某天的预约」`WHERE date = ?` | `date` |
| 「某实验室某天的预约」 | **联合索引** `(lab_id, date)` |

**联合索引的最左前缀原则**：

```python
__table_args__ = (
    Index("ix_resv_lab_date", "lab_id", "date"),
)
```

这个索引能加速：
- `WHERE lab_id = ?` ✅（最左前缀）
- `WHERE lab_id = ? AND date = ?` ✅
- `WHERE date = ?` ❌（跳过了最左列）

> ⚠️ **项目现状**：模型里**没有显式建索引**（只有主键和外键）。对于小数据量没问题，但并发冲突检测那个查询（`WHERE lab_id = ? AND status IN (...) AND start_time < ? AND end_time > ?`）在大数据量下会全表扫描。这是可以改进的点。

### 6.2 外键索引

**MySQL 会自动给外键建索引，PostgreSQL 不会。**

如果你用 PostgreSQL，记得手动给外键列加索引——否则 JOIN 和删除时会很慢。

---

## 七、Alembic 迁移

### 7.1 为什么需要迁移

改了模型后，数据库结构不会自动变。你需要：

```bash
# 生成迁移脚本
alembic revision --autogenerate -m "添加预约表"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```

### 7.2 项目里的 2 个迁移

```
alembic/versions/
├── xxxx_initial_schema.py
└── xxxx_add_kb_documents.py
```

**autogenerate 的局限**（面试会问）：

| 能自动检测 | 不能自动检测 |
|---|---|
| 新增/删除表 | 表重命名（会识别成删表+建表，**丢数据！**） |
| 新增/删除列 | 列重命名（同上） |
| 改列类型 | 数据迁移（比如把 A 列的值算出来填到 B 列） |
| 索引变更 | 约束变更（部分） |

> ⚠️ **坑**：重命名列时 autogenerate 会生成 `drop_column` + `add_column`，**数据全丢**。必须手动改成 `alter_column(..., new_column_name=...)`。

### 7.3 迁移的最佳实践

1. **每次迁移要能回滚**（写好 `downgrade`）
2. **生产迁移前先在 staging 试**
3. **大表加列要小心锁表**（PostgreSQL 11+ 的 `ADD COLUMN ... DEFAULT` 不锁表，但老版本会）
4. **数据迁移和结构迁移分开**：先加列（可空），再写脚本填数据，最后加约束

---

## 八、最小可运行骨架

```python
"""
sqlalchemy2_demo.py —— SQLAlchemy 2.0 核心用法
运行：pip install "sqlalchemy>=2" && python sqlalchemy2_demo.py
演示：2.0 建模、关系、N+1 问题与解决、Session 状态、事务
"""
from typing import Optional

from sqlalchemy import ForeignKey, String, create_engine, select, func
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, Session, mapped_column,
    relationship, joinedload, selectinload, sessionmaker,
)

# ══════════════════════════════════════════════════════════
# 1. 2.0 建模
# ══════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default="student")
    status: Mapped[int] = mapped_column(default=1)
    # 关系：一个用户有多个预约
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="user")

class Lab(Base):
    __tablename__ = "labs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    capacity: Mapped[int] = mapped_column(default=0)
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="lab")

class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"))
    date: Mapped[str] = mapped_column(String(20))
    start_time: Mapped[str] = mapped_column(String(20))
    end_time: Mapped[str] = mapped_column(String(20))
    status: Mapped[int] = mapped_column(default=0)   # 0待审 1通过 2拒绝 3取消

    user: Mapped[User] = relationship(back_populates="reservations")
    lab: Mapped[Lab] = relationship(back_populates="reservations")

# ══════════════════════════════════════════════════════════
# 2. 准备数据
# ══════════════════════════════════════════════════════════

engine = create_engine("sqlite:///:memory:", echo=False)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

QUERY_COUNT = 0

@event.listens_for(engine, "before_cursor_execute") if False else (lambda *a: None)
def _noop(): pass

def seed():
    with SessionLocal() as db:
        users = [User(username=f"u{i}", name=f"用户{i}",
                      role="admin" if i == 0 else "student") for i in range(1, 6)]
        labs = [Lab(name=f"L{i}0{i}", capacity=20) for i in range(1, 4)]
        db.add_all(users + labs)
        db.flush()

        import random
        for u in users:
            for l in labs:
                db.add(Reservation(
                    user_id=u.id, lab_id=l.id,
                    date="2025-01-17",
                    start_time=f"{10 + random.randint(0,6):02d}:00",
                    end_time=f"{14 + random.randint(0,6):02d}:00",
                    status=random.choice([0, 1]),
                ))
        db.commit()
    print("  种子数据：5 用户 × 3 实验室 = 15 条预约\n")

# ══════════════════════════════════════════════════════════
# 3. 2.0 查询风格
# ══════════════════════════════════════════════════════════

def demo_query_styles():
    print("【1. 2.0 vs 1.x 查询风格】")
    with SessionLocal() as db:
        # 2.0 推荐
        stmt = select(User).where(User.role == "student").order_by(User.id)
        students = db.execute(stmt).scalars().all()
        print(f"  2.0: select().where() → {len(students)} 个学生")

        # 1.x 遗留（仍可用）
        legacy = db.query(User).filter(User.role == "student").all()
        print(f"  1.x: query().filter() → {len(legacy)} 个学生（兼容但非推荐）")

        # 计数
        cnt = db.execute(select(func.count()).select_from(Reservation)).scalar()
        print(f"  计数: {cnt} 条预约")

        # 主键查询（2.0 用 db.get）
        u = db.get(User, 1)
        print(f"  主键查询 db.get(User, 1) → {u.name}")
    print()

# ══════════════════════════════════════════════════════════
# 4. N+1 问题
# ══════════════════════════════════════════════════════════

def demo_n_plus_1():
    print("【2. N+1 问题与解决】")

    with SessionLocal() as db:
        # ❌ 有 N+1
        rows = db.execute(select(Reservation)).scalars().all()
        names = [f"{r.user.name}@{r.lab.name}" for r in rows]
        print(f"  ❌ 直接访问关系：{len(rows)} 条记录，会发 1 + {len(rows)*2} 次查询")

    with SessionLocal() as db:
        # ✅ joinedload（多对一关系用这个）
        stmt = select(Reservation).options(
            joinedload(Reservation.user),
            joinedload(Reservation.lab),
        )
        rows = db.execute(stmt).scalars().unique().all()
        names = [f"{r.user.name}@{r.lab.name}" for r in rows]
        print(f"  ✅ joinedload：1 次 JOIN 查询搞定，取到 {len(names)} 条")
        print(f"     示例：{names[0]}")

    with SessionLocal() as db:
        # ✅ selectinload（一对多关系用这个，避免行膨胀）
        stmt = select(User).options(selectinload(User.reservations))
        users = db.execute(stmt).scalars().unique().all()
        total = sum(len(u.reservations) for u in users)
        print(f"  ✅ selectinload：2 次查询（主表 + IN），{len(users)} 用户共 {total} 条预约")
    print()

# ══════════════════════════════════════════════════════════
# 5. Session 状态
# ══════════════════════════════════════════════════════════

def demo_session_state():
    print("【3. Session 状态与 DetachedInstanceError】")
    db = SessionLocal()

    obj = User(username="new", name="新建")
    print(f"  Transient: id={obj.id} (未关联 Session)")

    db.add(obj)
    print(f"  Pending:   add 之后，还没 flush")

    db.flush()
    print(f"  Persistent: flush 之后 id={obj.id}（自增 ID 拿到了，但事务未提交）")

    db.commit()
    print(f"  commit 之后：默认 expire_on_commit=True，属性被清空")

    db.close()
    print(f"  Detached:  close 之后")

    try:
        _ = obj.name       # 触发重新加载 → 报错
        print("  访问属性：成功（意外）")
    except Exception as e:
        print(f"  ❌ 访问属性：{type(e).__name__}")

    # 解法：expire_on_commit=False
    print("\n  ✅ 解法对比：")
    print("     1. joinedload 预加载")
    print("     2. 在 Session 内先访问一次")
    print("     3. 转成 Pydantic / dict")
    print("     4. sessionmaker(expire_on_commit=False)")
    print()

# ══════════════════════════════════════════════════════════
# 6. 事务与 flush
# ══════════════════════════════════════════════════════════

def demo_transaction():
    print("【4. flush vs commit】")
    db = SessionLocal()

    r = Reservation(user_id=1, lab_id=1, date="2025-01-20",
                    start_time="09:00", end_time="10:00")
    db.add(r)
    db.flush()                 # 发 INSERT，拿 id，但不提交
    print(f"  flush 后 id={r.id}（已写入但未提交）")

    db.rollback()              # 回滚
    print(f"  rollback 后，这条记录还在吗？")

    exists = db.execute(
        select(func.count()).select_from(Reservation).where(Reservation.id == r.id)
    ).scalar()
    print(f"  → 数据库中 count = {exists}  {'✅ flush 也被回滚了' if exists == 0 else '❌ 没回滚'}")

    # 原子性演示
    try:
        r2 = Reservation(user_id=1, lab_id=1, date="2025-01-21",
                         start_time="11:00", end_time="12:00")
        db.add(r2)
        db.flush()
        raise RuntimeError("故意失败")
        db.commit()
    except Exception:
        db.rollback()
    cnt = db.execute(
        select(func.count()).select_from(Reservation).where(Reservation.date == "2025-01-21")
    ).scalar()
    print(f"  异常后 rollback，1-21 的记录数 = {cnt}  {'✅ 原子性保证' if cnt == 0 else '❌ 脏数据'}")
    db.close()
    print()

# ══════════════════════════════════════════════════════════
# 7. 时段重叠查询（第 11 章预览）
# ══════════════════════════════════════════════════════════

def demo_overlap():
    print("【5. 时段重叠查询】")
    with SessionLocal() as db:
        # 假设已有 10:00-12:00
        db.add(Reservation(user_id=1, lab_id=1, date="2025-01-22",
                           start_time="10:00", end_time="12:00", status=1))
        db.commit()

        def has_conflict(new_start, new_end):
            cnt = db.execute(
                select(func.count()).select_from(Reservation).where(
                    Reservation.lab_id == 1,
                    Reservation.date == "2025-01-22",
                    Reservation.status.in_([0, 1]),
                    Reservation.start_time < new_end,     # ★ 关键
                    Reservation.end_time > new_start,     # ★ 关键
                )
            ).scalar()
            return cnt > 0

        cases = [
            ("09:00", "10:00", False),   # 背靠背，不冲突
            ("09:00", "10:30", True),    # 部分重叠
            ("10:00", "12:00", True),    # 完全重叠
            ("11:00", "13:00", True),    # 部分重叠
            ("12:00", "13:00", False),   # 背靠背
            ("13:00", "14:00", False),   # 完全不重叠
            ("09:00", "13:00", True),    # 包含
        ]
        print(f"  已有预约：10:00-12:00")
        for s, e, expect in cases:
            got = has_conflict(s, e)
            flag = "✅" if got == expect else "❌"
            print(f"  {flag} {s}-{e}: 冲突={got}（期望 {expect}）")
    print()

# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("SQLAlchemy 2.0 演示")
    print("=" * 60 + "\n")
    seed()
    demo_query_styles()
    demo_n_plus_1()
    demo_session_state()
    demo_transaction()
    demo_overlap()
```

---

## 本章速记卡

1. **2.0 新语法**：`Mapped[str]`（NOT NULL）、`Mapped[str | None]`（可空）、`select()` + `db.execute().scalars()`。
2. **类型注解驱动**是 2.0 的核心改进，IDE 和 mypy 能真正检查。
3. **`ForeignKey` 是列，`relationship()` 不是列**，是 Python 对象导航。
4. **N+1 问题**：循环访问关系属性导致大量查询。用 `joinedload`（多对一）或 `selectinload`（一对多）。
5. **`joinedload` 要加 `.unique()`**（JOIN 产生重复行）。
6. **DetachedInstanceError**：Session 关闭后访问懒加载属性。解法：预加载 / 提前访问 / 转 Pydantic / `expire_on_commit=False`。
7. **`flush` 拿自增 ID 但不提交**，配合后续操作形成原子事务。
8. **批量 update/delete** 性能好但绕过 ORM 钩子。
9. **外键索引**：MySQL 自动建，PostgreSQL 不自动。
10. **Alembic autogenerate 不能识别重命名**（会丢数据，必须手动改）。

---

## 面试问答：ORM 与数据建模

### Q1：「SQLAlchemy 2.0 和 1.x 有什么区别？」

**满分答法**：

> 最大的变化是类型注解驱动。2.0 用 `Mapped[str]` 声明字段类型，它会自动映射成 NOT NULL；`Mapped[str | None]` 映射成可空。1.x 用 `Column(String(50), nullable=False)`，类型信息对 IDE 是丢失的。
>
> 第二个变化是查询 API。2.0 主推 `select(User).where(...)` 配合 `db.execute(stmt).scalars().all()`，1.x 的 `db.query(User).filter(...)` 仍然可用但被定位为遗留 API。2.0 的写法组合性更好——你可以把 `stmt` 当对象传来传去、动态拼装。
>
> 第三是异步支持。2.0 有 `AsyncSession`，配合 `asyncio` 使用；1.x 没有官方异步。
>
> 还有一些细节：`db.get(User, 1)` 替代了 `db.query(User).get(1)`；`scalars()` / `scalar_one_or_none()` 这些方法让返回类型更明确。

---

### Q2：「什么是 N+1 问题？你怎么解决？」

**满分答法**：

> N+1 是指：查主表 1 次，然后在循环里访问每条记录的关联对象，每次都触发一次额外查询，所以总共是 1 + N 次。100 条记录就是 200 次查询，性能极差。
>
> 我解决过这个问题：查预约列表时循环里访问 `r.user.name` 和 `r.lab.name`，导致每条记录多两次查询。
>
> 解法有两种，看关系类型：
>
> **多对一**（预约 → 用户）用 `joinedload`，它用 LEFT JOIN 一次性把关联数据查出来。注意要加 `.unique()`，因为 JOIN 会产生重复行。
>
> **一对多**（用户 → 他的预约列表）用 `selectinload`，因为 JOIN 会导致行膨胀——一个用户有 5 条预约就变成 5 行，主表数据重复。`selectinload` 是两条 SQL：先查主表，再用 IN 查关联表，没有膨胀问题。
>
> 另外还有一种手动解法：先查主表，收集所有 user_id，再用 `IN` 批量查一次，然后手动拼装。不如 ORM 的 loader 优雅，但更灵活。

---

### Q3：「DetachedInstanceError 遇到过吗？怎么解决？」

**满分答法**：

> 遇到过。这是 Session 关闭后访问懒加载属性导致的——对象变成 Detached 状态，访问关系需要发 SQL，但 Session 没了。
>
> 四种解法：
>
> 一是预加载，用 `joinedload` 在查询时就把关系查出来。这是最标准的做法。
>
> 二是在 Session 还开着的时候先访问一次，把数据加载到内存。
>
> 三是转成 Pydantic 或 dict——我项目里主要用这个。service 返回前用 `ReservationResponse.model_validate(orm_obj)`（配合 `from_attributes=True`），把 ORM 对象转成纯数据的 Pydantic 模型，Session 关闭后也不受影响。
>
> 四是设 `sessionmaker(expire_on_commit=False)`。默认是 True，commit 后所有对象属性被清空（下次访问要重新查库）。设成 False 就不会过期。但代价是可能拿到过期数据——如果别的事务改了这条记录，你内存里的还是旧值。我项目里用的是默认配置，靠转成 Pydantic 来规避。

---

### Q4：「为什么预约时间存成字符串而不是 DateTime？」（陷阱题）

**满分答法**（诚实 + 有判断力）：

> 我当时选字符串是因为前后端传递简单——不用处理时区序列化，前端拿到直接显示；而且时段重叠判断用字符串比较就能做，只要格式统一。
>
> 但现在看这个设计有三个局限：
>
> 一是**依赖格式严格统一**。如果数据库里混进 `14:00` 和 `14:00:00` 两种格式，字符串比较就会出错（`'14:00' < '14:00:00'` 是 True，但语义上它们相等）。这个风险要靠严格的输入校验来防。
>
> 二是**没法表达跨天时段**。date 和 time 分开存，22:00 到次日 02:00 这种预约没法表示。
>
> 三是**没法用数据库的时间函数**。比如「查询未来 7 天所有预约」，用 DateTime 可以 `BETWEEN now() AND now() + interval '7 days'`，用字符串就得在应用层算好日期再拼条件。
>
> 如果要改进，我会改成 `start_at` 和 `end_at` 两个带时区的 DateTime 字段。重叠判断变成标准的区间比较，也支持跨天和范围查询，前端显示时再格式化。这是我现在会做的选择。

---

### Q5：「Alembic 用过吗？有什么坑？」

**满分答法**：

> 用过，项目里有 2 个迁移版本。
>
> 最常见的坑是 **autogenerate 不能识别重命名**。你把一个列从 `name` 改成 `title`，autogenerate 会生成 `drop_column('name')` + `add_column('title')`——数据全丢了。必须手动改成 `op.alter_column(..., new_column_name='title')`。
>
> 第二个坑是**大表加列会锁表**。老版本 PostgreSQL 上 `ADD COLUMN ... DEFAULT` 会重写整张表，大表上可能锁几分钟。解法是先加可空列（不加 default），再分批更新数据，最后加约束。
>
> 第三个是**生产迁移要能回滚**。每次写迁移都要认真写 `downgrade`，并且先在 staging 环境跑一遍。
>
> 另外我的习惯是**结构迁移和数据迁移分开**：先加列（可空），跑脚本填数据，确认没问题后再加 NOT NULL 约束。这样每一步都能单独回滚。

---

### Q6：「索引怎么设计？」

**满分答法**：

> 索引设计完全由查询模式决定。
>
> 我会先列出所有的查询场景，再看每个场景需要什么索引。比如：
>
> 「查询我的预约」是 `WHERE user_id = ?` → 需要 `user_id` 索引。
> 「查询某实验室某天的预约」是 `WHERE lab_id = ? AND date = ?` → 需要联合索引 `(lab_id, date)`。
>
> 联合索引要注意**最左前缀原则**：`(lab_id, date)` 能加速只用 `lab_id` 的查询，但不能加速只用 `date` 的查询。所以列的顺序要按查询频率和选择性来定。
>
> 还有一个容易忽略的点：**MySQL 会自动给外键建索引，PostgreSQL 不会**。如果用 PG，外键列要手动加索引，否则 JOIN 和删除时会很慢。
>
> 说实话我项目里现在只依赖主键和外键索引，没有显式建业务索引。数据量小的时候没问题，但并发冲突检测那个查询（lab_id + status + 时间区间）在大数据量下会全表扫描。如果要上生产，这是我首先要补的。

---

## 常见坑

### 坑 1：用 1.x 写法但简历写 2.0

面试官一问就露馅。

### 坑 2：N+1 查询

列表页最常见。用 `joinedload` / `selectinload`。

### 坑 3：`joinedload` 忘了 `.unique()`

结果条数不对（JOIN 重复行）。

### 坑 4：DetachedInstanceError

Session 关闭后访问关系。转 Pydantic 解决。

### 坑 5：Alembic 重命名列丢数据

autogenerate 生成 drop + add。手动改成 alter。

### 坑 6：时间存字符串导致格式不一致

比较失效。要么严格校验，要么用 DateTime。

### 坑 7：commit 后访问属性触发新查询

`expire_on_commit=True` 的默认行为。

### 坑 8：PostgreSQL 外键没索引

JOIN 慢。

### 坑 9：`db.query()` 和 `select()` 混用

风格不统一。2.0 项目统一用 `select()`。

---

## 动手练习

### 练习 1（必做）

跑通第八节的 `sqlalchemy2_demo.py`，重点观察：

1. N+1 的两种解法差异
2. `flush` 后 rollback，数据是否还在
3. 时段重叠判断的 7 个用例是否都符合预期

### 练习 2

给项目模型加索引：

```python
__table_args__ = (
    Index("ix_resv_lab_date", "lab_id", "date"),
)
```

然后用 `EXPLAIN QUERY PLAN` 对比加索引前后的查询计划。

### 练习 3

把 `Reservation.status` 从整数改成枚举：

```python
class ReservationStatus(enum.IntEnum):
    PENDING = 0
    APPROVED = 1
    REJECTED = 2
    CANCELLED = 3
```

改完后跑测试，看有多少地方要改。体会「可读性改进的成本」。

### 练习 4（进阶）

用 Alembic 做一次「重命名列」的迁移：

1. 先用 autogenerate 生成，看它生成了什么（应该是 drop + add）
2. 手动改成 `alter_column(..., new_column_name=...)`
3. 验证数据没丢

---

## 下一章

**第 11 章 · 事务与并发控制**

这是简历含金量最高的一章，也是这个项目最能体现「工程能力」的地方。

两个用户同时抢同一个实验室时段——怎么保证不超卖？

这一章讲透：事务的 ACID、`SELECT FOR UPDATE` 行锁、区间重叠判断、SQLite 和 PostgreSQL 的锁差异（这是个真实的坑，会导致并发测试「假通过」）、以及项目里那个 C1 缺陷（commit 没有 rollback）的完整修复过程。
