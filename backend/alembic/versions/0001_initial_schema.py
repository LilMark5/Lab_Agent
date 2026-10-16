"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-16

"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键ID"),
        sa.Column("username", sa.String(50), nullable=False, comment="账号"),
        sa.Column("password", sa.String(255), nullable=False, comment="密码"),
        sa.Column("name", sa.String(50), nullable=False, comment="名称"),
        sa.Column("role", sa.String(50), nullable=False, comment="角色：student-学生，admin-管理员"),
        sa.Column("email", sa.String(50), nullable=True, comment="邮箱"),
        sa.Column("phone", sa.String(50), nullable=True, comment="手机号"),
        sa.Column("avatar", sa.String(255), nullable=True, comment="头像"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态：0-禁用，1-正常"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        comment="用户信息表",
    )

    op.create_table(
        "labs",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键ID"),
        sa.Column("name", sa.String(50), nullable=False, comment="实验室名称"),
        sa.Column("location", sa.String(100), nullable=True, comment="位置"),
        sa.Column("capacity", sa.Integer(), nullable=False, comment="容纳人数"),
        sa.Column("open_time", sa.String(20), nullable=True, comment="开放开始时间"),
        sa.Column("close_time", sa.String(20), nullable=True, comment="开放结束时间"),
        sa.Column("description", sa.String(500), nullable=True, comment="简介"),
        sa.Column("img", sa.String(200), nullable=True, comment="封面图"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态：0-关闭，1-开放"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        comment="实验室信息表",
    )

    op.create_table(
        "equipments",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键ID"),
        sa.Column("lab_id", sa.Integer(), sa.ForeignKey("labs.id"), nullable=False, comment="所属实验室"),
        sa.Column("name", sa.String(50), nullable=False, comment="设备名称"),
        sa.Column("description", sa.String(500), nullable=True, comment="说明"),
        sa.Column("img", sa.String(200), nullable=True, comment="图片"),
        sa.Column("spec", sa.String(100), nullable=True, comment="型号规格"),
        sa.Column("quantity", sa.Integer(), nullable=False, comment="数量"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态：0-维修，1-正常"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        comment="实验室设备表",
    )

    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True, comment="主键ID"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, comment="预约人"),
        sa.Column("lab_id", sa.Integer(), sa.ForeignKey("labs.id"), nullable=False, comment="实验室"),
        sa.Column(
            "equipment_id",
            sa.Integer(),
            sa.ForeignKey("equipments.id"),
            nullable=True,
            comment="设备，空表示预约实验室",
        ),
        sa.Column("date", sa.String(20), nullable=False, comment="预约日期"),
        sa.Column("start_time", sa.String(20), nullable=False, comment="开始时间"),
        sa.Column("end_time", sa.String(20), nullable=False, comment="结束时间"),
        sa.Column("remark", sa.String(255), nullable=True, comment="备注"),
        sa.Column(
            "status",
            sa.Integer(),
            nullable=False,
            comment="预约状态 0待审核，1已通过，2已拒绝，3已取消",
        ),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("update_time", sa.DateTime(), nullable=False, comment="更新时间"),
        comment="预约信息",
    )


def downgrade() -> None:
    op.drop_table("reservations")
    op.drop_table("equipments")
    op.drop_table("labs")
    op.drop_table("users")
