"""FastAPI 应用入口。"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api
from app.common.exceptions import (
    BusinessException,
    business_exception_handler,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.config import UPLOAD_DIR
from app.database import Base, engine
from app.init_data import seed_if_empty
from app.models import equipment, lab, reservation, user  # noqa: F401
from app.services import agent_service, kb_service, reservation_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时执行的生命周期逻辑。"""
    # 1. 建表并写入演示数据。
    Base.metadata.create_all(bind=engine)
    seed_if_empty()

    # 2. 预热向量库，把模型加载成本放在启动阶段。
    try:
        # 加超时：模型下载受网络影响时，不让服务启动被无限期拖住。
        await asyncio.wait_for(asyncio.to_thread(kb_service.warmup), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("向量库预热超时，服务先启动，首个 RAG 请求会稍慢")
    except Exception:
        logger.exception("向量库预热失败，服务继续启动")

    # 3. 启动后台扫描：每 60 秒把过期待审核预约自动取消。
    task = asyncio.create_task(reservation_service.run_expire_scan())
    yield
    task.cancel()
    await agent_service.close_checkpointer()


app = FastAPI(
    title="智能实验室预约系统",
    description="FastAPI + Vue3 + RAG + LangGraph 毕业设计项目",
    version="1.0.0",
    lifespan=lifespan,
)

# 跨域配置：开发阶段前端跑在 Vite 的端口，需要允许跨域。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # 前端用 Authorization 头鉴权，不走 Cookie，credentials 必须关掉，
    # 否则浏览器会因为“通配符 origin + credentials”直接拒绝跨域请求。
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一异常处理。注意：Exception 兜底必须最后注册。
app.add_exception_handler(BusinessException, business_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# 业务路由统一挂到 /api 前缀。
app.include_router(api)

# 上传文件静态访问：/uploads/xxx.jpg -> backend/uploads/xxx.jpg
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/")
def root():
    """健康检查接口。"""
    return {"message": "智能实验室预约系统后端运行正常"}
