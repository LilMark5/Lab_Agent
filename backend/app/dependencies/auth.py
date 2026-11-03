"""登录鉴权依赖。

FastAPI 的 `Depends` 是依赖注入：路由函数声明
`current_user: User = Depends(get_current_user)`，FastAPI 就会先执行
`get_current_user`，把返回值传给路由函数。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.database import get_db
from app.models.user import User
from app.utils.jwt import decode_access_token

# tokenUrl 只用于 OpenAPI 文档，真正的认证逻辑在 get_current_user。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """从 Authorization: Bearer <token> 中解析并校验当前用户。"""
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在"
        )
    if user.status != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户被禁用"
        )
    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """管理员鉴权：先登录，再判断角色。"""
    if current_user.role != "admin":
        raise BusinessException(message="无权限访问", code=403)
    return current_user
