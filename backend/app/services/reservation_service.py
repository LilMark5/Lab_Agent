"""预约业务逻辑。"""

import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.database import SessionLocal
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest, ReservationResponse


def create_reservation(
    db: Session, current_user: User, data: ReservationCreateRequest
) -> None:
    """创建预约。

    核心校验：
    1. 日期/时间不能是过去。
    2. 实验室/设备必须存在且开放。
    3. 时间段不能和待审核、已通过的预约重叠。
    """
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    if data.date < current_date:
        raise BusinessException(message="预约日期不能小于当前的日期")
    if data.end_time < data.start_time:
        raise BusinessException(message="预约的结束时间不能小于开始时间")
    if data.date == current_date and data.start_time < current_time:
        raise BusinessException(message="预约开始时间不能小于当前的时间")

    # 先锁住实验室行：并发预约同一实验室时串行执行，避免“先查冲突再插入”的竞态。
    # Postgres 下会生成 SELECT ... FOR UPDATE；SQLite 忽略该子句，靠写锁串行。
    lab = db.query(Lab).filter(Lab.id == data.lab_id).with_for_update().first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    if lab.status != 1:
        raise BusinessException(message="实验室已关闭")
    if lab.open_time and data.start_time < lab.open_time:
        raise BusinessException(message="预约时间不能早于实验室的开放时间")
    if lab.close_time and data.end_time > lab.close_time:
        raise BusinessException(message="预约时间不能晚于实验室的关闭时间")

    if data.equipment_id:
        equipment = (
            db.query(Equipment).filter(Equipment.id == data.equipment_id).first()
        )
        if not equipment:
            raise BusinessException(message="实验室设备不存在")
        if equipment.status != 1:
            raise BusinessException(message="实验室设备正在维修")

    # 冲突判断采用区间重叠算法：已有 A 与 新 B 重叠，
    # 当且仅当 A.start < B.end 且 A.end > B.start。
    # 该检测覆盖 status in [0,1]（待审核 + 已通过），配合 with_for_update 行锁，
    # 天然具备「重复预订防护」的幂等性——同一时段重复提交会命中冲突而拒绝。
    query = db.query(Reservation).filter(
        Reservation.lab_id == data.lab_id,
        Reservation.date == data.date,
        Reservation.status.in_([0, 1]),
        Reservation.start_time < data.end_time,
        Reservation.end_time > data.start_time,
    )
    if data.equipment_id:
        query = query.filter(Reservation.equipment_id == data.equipment_id)
    else:
        query = query.filter(Reservation.equipment_id.is_(None))
    if query.first():
        raise BusinessException(message="该时段已预约")

    reservation = Reservation(
        user_id=current_user.id,
        lab_id=data.lab_id,
        equipment_id=data.equipment_id,
        date=data.date,
        start_time=data.start_time,
        end_time=data.end_time,
        remark=data.remark,
        status=0,
    )
    db.add(reservation)
    # 显式事务边界：commit 失败时回滚，避免会话残留脏状态。
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_reservation_page_list(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    status: int | None = None,
) -> PageResponse:
    query = db.query(Reservation)
    if current_user.role != "admin":
        query = query.filter(Reservation.user_id == current_user.id)
    if status is not None:
        query = query.filter(Reservation.status == status)

    total = query.count()
    items = (
        query.order_by(Reservation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for item in items:
        res = ReservationResponse.model_validate(item)
        res.user_name = item.user.name if item.user else None
        res.lab_name = item.lab.name if item.lab else None
        res.equipment_name = item.equipment.name if item.equipment else None
        res.type = "设备" if item.equipment_id else "实验室"
        result.append(res)
    return PageResponse(list=result, total=total)


def cancel_reservation(db: Session, current_user: User, reservation_id: int) -> None:
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.user_id != current_user.id:
        raise BusinessException(message="无权限", code=403)
    if item.status != 0:
        raise BusinessException(message="当前状态无法取消")
    item.status = 3
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def audit_reservation(db: Session, reservation_id: int, status: int) -> None:
    if status not in (1, 2):
        raise BusinessException(message="审核状态错误")
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.status != 0:
        raise BusinessException(message="当前状态不支持审核")
    item.status = status
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def expire_pending_reservations() -> None:
    """把已经过期的待审核预约改为已取消，释放时段。"""
    db = SessionLocal()
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        now_time = now.strftime("%H:%M")
        items = db.query(Reservation).filter(Reservation.status == 0).all()
        changed = False
        for item in items:
            if item.date < today or (item.date == today and item.end_time <= now_time):
                item.status = 3
                changed = True
        if changed:
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise
    finally:
        db.close()


async def run_expire_scan() -> None:
    """后台任务：每 60 秒扫描一次过期待审核预约。"""
    while True:
        expire_pending_reservations()
        await asyncio.sleep(60)
