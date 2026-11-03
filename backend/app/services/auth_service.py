"""登录与注册业务逻辑。"""

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest
from app.schemas.user import UserResponse
from app.utils.jwt import create_access_token
from app.utils.password import hash_password, verify_password


def login(db: Session, data: LoginRequest) -> LoginResponse:
    """校验账号密码，返回 token 和用户信息。"""
    user = db.query(User).filter(User.username == data.username).first()

    # 账号不存在或密码错误，统一提示同一条，避免泄露“哪个账号存在”。
    if not user or not verify_password(data.password, user.password):
        raise BusinessException(message="账号或密码错误")
    if user.status != 1:
        raise BusinessException(message="账号被禁用")

    token = create_access_token(user.id)
    return LoginResponse(token=token, user=UserResponse.model_validate(user))


def register(db: Session, data: RegisterRequest) -> None:
    """注册普通学生账号。"""
    exists = db.query(User).filter(User.username == data.username).first()
    if exists:
        raise BusinessException(message="账号已存在")

    user = User(
        username=data.username,
        password=hash_password(data.password),
        name=data.name or data.username,
        role="student",
        status=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
