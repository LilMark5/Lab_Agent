"""用户相关 Schema。"""

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: int

    model_config = ConfigDict(from_attributes=True)


class UserUpdateRequest(BaseModel):
    """普通用户修改自己的信息；role/status 不能在这里改。"""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None


class PasswordUpdateRequest(BaseModel):
    old_password: str
    new_password: str


class UserCreateRequest(BaseModel):
    """管理员创建用户。"""

    username: str
    password: str = "123456"
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    role: str = "student"
    status: int = 1


class UserAdminUpdateRequest(BaseModel):
    """管理员编辑用户，可以改角色和状态。"""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    role: str | None = None
    status: int | None = None
