"""登录/注册相关 Schema。"""

from pydantic import BaseModel, Field

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, description="账号")
    password: str = Field(min_length=1, description="密码")


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=3, max_length=50)
    name: str | None = None


class LoginResponse(BaseModel):
    token: str
    user: UserResponse
