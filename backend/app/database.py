"""数据库引擎与会话管理。

这里做了三件核心事情：
1. 创建 SQLAlchemy 引擎（engine）：负责和数据库建立连接。
2. 创建会话工厂（SessionLocal）：每个请求拿一个独立会话，用完关闭。
3. 定义 Base：所有 ORM 模型的公共父类，包含 id/创建时间/更新时间。
"""

from datetime import datetime

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings

# 如果没配置 MySQL，默认使用本地 SQLite 文件，保证项目“开箱即跑”。
# SQLite 需要在多线程 FastAPI 环境下加 check_same_thread=False。
# 优先使用显式配置的关系数据库（PostgreSQL / MySQL）。
# 若未配置则回退到本地 SQLite，保证零配置可启动。
if settings.DATABASE_URL:
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
else:
    engine = create_engine(
        "sqlite:///./lab_agent.db",
        connect_args={"check_same_thread": False},
    )

# autoflush=False：不要在查询前自动把未提交的修改刷进数据库，行为更可控。
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI 依赖：为每个请求创建数据库会话，请求结束后关闭。

    使用 `yield` 而不是 return，是因为 `Depends(get_db)` 依赖注入机制
    需要在请求结束后执行 finally 里的清理代码。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    """所有表的公共父类。

    把 id、create_time、update_time 放在这里，业务模型就不用重复写。
    """

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="主键ID")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
