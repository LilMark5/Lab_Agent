"""预约服务测试：业务规则 + PostgreSQL 并发控制。"""

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.common.exceptions import BusinessException
from app.config import settings
from app.database import Base
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest
from app.services import reservation_service


def _make_user(db, username: str) -> User:
    user = User(username=username, password="x", name=username, role="student", status=1)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_lab(db, name: str) -> Lab:
    lab = Lab(name=name, location="A区", capacity=10, status=1)
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return lab


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _request(lab_id: int, start: str, end: str) -> ReservationCreateRequest:
    return ReservationCreateRequest(
        lab_id=lab_id,
        date=_tomorrow(),
        start_time=start,
        end_time=end,
    )


def test_overlap_rejected_and_free_slot_accepted():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session()

    user = _make_user(db, "stu1")
    lab = _make_lab(db, "lab1")

    reservation_service.create_reservation(db, user, _request(lab.id, "14:00", "15:00"))
    with pytest.raises(BusinessException):
        reservation_service.create_reservation(db, user, _request(lab.id, "14:30", "15:30"))

    # 紧邻不重叠的时段应当成功。
    reservation_service.create_reservation(db, user, _request(lab.id, "15:00", "16:00"))
    db.close()


@pytest.mark.skipif(
    not (settings.DATABASE_URL or "").startswith("postgresql"),
    reason="并发控制测试需要 PostgreSQL（SELECT ... FOR UPDATE）",
)
def test_concurrent_reservation_no_double_booking():
    from app.database import SessionLocal

    suffix = uuid.uuid4().hex[:8]
    admin_db = SessionLocal()
    user = _make_user(admin_db, f"u_{suffix}")
    lab = _make_lab(admin_db, f"lab_{suffix}")
    request = _request(lab.id, "14:00", "15:00")
    results: list[str] = []

    def worker():
        db = SessionLocal()
        try:
            reservation_service.create_reservation(db, user, request)
            results.append("ok")
        except BusinessException:
            results.append("busy")
        finally:
            db.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results) == ["busy", "ok"]

    # 清理测试数据，避免污染开发库。
    admin_db.query(Reservation).filter(Reservation.lab_id == lab.id).delete()
    admin_db.query(Lab).filter(Lab.id == lab.id).delete()
    admin_db.query(User).filter(User.id == user.id).delete()
    admin_db.commit()
    admin_db.close()
