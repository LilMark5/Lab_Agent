"""add kb_documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.String(32), primary_key=True, comment="文档ID"),
        sa.Column("filename", sa.String(255), nullable=False, comment="原始文件名"),
        sa.Column("content_type", sa.String(100), nullable=True, comment="MIME 类型"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, comment="文件大小(字节)"),
        sa.Column("sha256", sa.String(64), nullable=True, comment="内容 SHA-256"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            comment="状态：ready/failed",
        ),
        sa.Column("error", sa.String(500), nullable=True, comment="失败原因"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        comment="知识库文档注册表",
    )


def downgrade() -> None:
    op.drop_table("kb_documents")
