"""统一响应格式。

为什么要统一响应？
前端 axios 可以统一判断 `code`，不用为每个接口写不同的判断逻辑。
"""

from typing import Any, List

from pydantic import BaseModel, Field


class Response(BaseModel):
    """普通接口的统一返回结构。"""

    code: int
    message: str
    data: Any = None

    @classmethod
    def success(cls, message: str = "请求成功", data: Any = None):
        return cls(code=200, message=message, data=data)

    @classmethod
    def error(cls, code: int = 500, message: str = "请求失败"):
        return cls(code=code, message=message)


class PageResponse(BaseModel):
    """分页接口的统一返回结构。"""

    # 注意：字段名是 `list`，如果注解也写 `list[Any]`，会在类命名空间里
    # 把内置 `list` 遮蔽成 FieldInfo，导致 Pydantic 求值失败。
    # 因此这里显式用 typing.List。
    list: List[Any] = Field(default_factory=list)
    total: int = 0
