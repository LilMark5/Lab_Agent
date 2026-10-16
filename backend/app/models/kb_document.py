"""知识库文档注册表。

这里只存文档的元数据（文件名、大小、哈希、状态），真正的切块和向量
由向量存储层管理。两者通过 document_id 关联，支持按文档过滤检索和删除。
"""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KbDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = {"comment": "知识库文档注册表"}

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="文档ID")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    content_type: Mapped[str | None] = mapped_column(String(100), comment="MIME 类型")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, comment="文件大小(字节)")
    sha256: Mapped[str | None] = mapped_column(String(64), comment="内容 SHA-256")
    status: Mapped[str] = mapped_column(String(20), default="ready", comment="状态：ready/failed")
    error: Mapped[str | None] = mapped_column(String(500), comment="失败原因")
