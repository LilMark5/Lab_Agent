"""JWT 工具。

JWT 是一段签过名的字符串，里面可以携带用户 ID、过期时间等信息。
服务端用密钥签名/验签，客户端无法篡改。
"""

from datetime import datetime, timedelta

import jwt

from app.config import settings


def create_access_token(user_id: int) -> str:
    """为指定用户生成访问令牌。"""
    expire = datetime.now() + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {"user_id": user_id, "exp": expire}
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    """解析令牌。无效、过期、篡改都会抛出异常，由调用方捕获。"""
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
