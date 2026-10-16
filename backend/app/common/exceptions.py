"""业务异常和全局异常处理。

FastAPI 原生异常会返回它自己的 JSON。这里统一成 {code, message, data}，
前端处理起来更简单。业务错误仍返回 HTTP 200，通过 code 区分，方便 axios
在响应拦截器里统一提示。
"""

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.common.response import Response


class BusinessException(Exception):
    """自定义业务异常，用于可预期的错误，例如“账号已存在”。"""

    def __init__(self, message: str, code: int = 500):
        self.message = message
        self.code = code
        super().__init__(message)


async def business_exception_handler(request: Request, exc: BusinessException):
    """业务异常：HTTP 状态仍为 200，用 body 里的 code 表达错误。"""
    return JSONResponse(
        status_code=200,
        content=Response.error(code=exc.code, message=exc.message).model_dump(),
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """FastAPI 抛出的 HTTPException，例如 401 未登录。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=Response.error(
            code=exc.status_code, message=str(exc.detail)
        ).model_dump(),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 参数校验失败。"""
    return JSONResponse(
        status_code=422,
        content=Response.error(code=422, message="请求参数校验错误").model_dump(),
    )


async def global_exception_handler(request: Request, exc: Exception):
    """兜底异常：捕获所有未处理的错误，避免把堆栈直接暴露给前端。"""
    return JSONResponse(
        status_code=500,
        content=Response.error(code=500, message="服务器内部错误").model_dump(),
    )
