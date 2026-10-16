# 04 · SQLAlchemy 与数据库：从 ORM 到查询优化

## 1. 为什么要用 ORM？

ORM 把数据库表映射成 Python 类，让你少写 SQL：

```python
db.query(User).filter(User.username == "admin").first()
```

等价于：

```sql
SELECT * FROM users WHERE username = 'admin' LIMIT 1;
```

好处：类型提示、字段校验、避免 SQL 注入、方便切换数据库。

## 2. 核心对象

- `engine`：数据库连接引擎，真正执行 SQL。
- `Session`：一次业务操作的工作单元，负责事务。
- `Base`：所有模型的父类。
- `Mapped` / `mapped_column`：SQLAlchemy 2.0 的类型标注方式。

```python
class Lab(Base):
    __tablename__ = "labs"
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=0)
```

## 3. 外键与关系

设备属于实验室，用外键建立关联：

```python
class Equipment(Base):
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"))
    lab: Mapped[Lab] = relationship()
```

`lab_id` 是数据库真正存储的外键，`lab` 是 ORM 层面的对象关系。
拿到 equipment 后可以直接 `equipment.lab.name`。

## 4. 分页查询骨架

项目里每个列表页都用这个模式：

```python
query = db.query(Lab)
if keywords:
    query = query.filter(Lab.name.ilike(f"%{keywords}%"))

total = query.count()
items = query.order_by(Lab.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
```

关键点：

- 先 count 得到总数，再 offset/limit 得到当前页。
- 模糊查询 `ilike` 不区分大小写。
- 参数化条件逐层叠加，避免写一堆 if 拼 SQL。

## 5. 增删改查事务

```python
lab = Lab(**data.model_dump())
db.add(lab)
db.commit()      # 提交事务
db.refresh(lab)  # 拿回数据库生成的 id、时间等字段
```

修改对象直接 setattr，删除用 `db.delete`。所有变更在 commit 前不会真正落库。

## 6. 常见坑

### 6.1 N+1 查询

设备列表里要显示实验室名称，如果循环里查实验室，就会产生 N+1：

```python
for item in equipments:
    print(item.lab.name)  # 每个 item 都可能发一条 SQL
```

本项目数据量小看不出问题，生产上要用 `joinedload` 或 `selectinload` 预加载关系：

```python
from sqlalchemy.orm import joinedload
query = db.query(Equipment).options(joinedload(Equipment.lab))
```

### 6.2 时间比较

预约日期 `YYYY-MM-DD`、时间 `HH:MM` 都是定长字符串，字典序比较恰好等于时间先后。
但如果格式不统一，例如 `9:00` 和 `10:00`，字符串比较就会错。

### 6.3 并发冲突

“时段是否已预约”先查再插，两个请求同时进来可能都通过。
学习项目可接受，生产上要加唯一约束、锁或乐观锁。

## 7. SQLite 与 MySQL 的区别

本项目默认 SQLite 是为了零配置。SQLite 是单文件数据库，不适合高并发写入。
MySQL 是 C/S 架构，适合真实部署。切换只需要改 `DATABASE_URL`：

```text
mysql+pymysql://root:123456@127.0.0.1:3306/lab_agent
```

SQLAlchemy 屏蔽了大部分差异，但 SQLite 不支持某些 MySQL 专有语法。

## 8. 生产环境要掌握

- Alembic 数据库迁移。
- 索引：给 `username`、`lab_id`、`date` 等常查字段加索引。
- 事务边界：跨多个写操作要么全成功，要么全回滚。
- 连接池：理解 `pool_pre_ping`、超时、最大连接数。

## 9. 检查清单

- `ForeignKey` 和 `relationship` 分别表示什么？
- 分页为什么要先 count 再 offset/limit？
- 什么是 N+1 查询？怎么解决？
