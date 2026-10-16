"""LangGraph Agent 使用的工具。

工具就是普通函数，用 @tool 装饰后，LangChain 会自动读取函数签名和
docstring，生成大模型能看懂的 JSON Schema。
"""

import json
import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest
from app.services import equipment_service, kb_service, lab_service, reservation_service

try:
    from langchain_core.tools import tool as langchain_tool

    TOOL_DECORATOR_AVAILABLE = True
except Exception:
    langchain_tool = None
    TOOL_DECORATOR_AVAILABLE = False

# MCP 工具缓存：只尝试连接一次，失败后回退本地工具，避免每个请求都重连。
_mcp_cache = {"tried": False, "client": None, "tools": None}


def _load_mcp_tools():
    """从独立 MCP Server 加载读工具。不可用时返回 None。"""
    if not settings.MCP_ENABLED:
        return None
    if _mcp_cache["tried"]:
        return _mcp_cache["tools"]
    _mcp_cache["tried"] = True
    try:
        asyncio.get_running_loop()
        # 已经在 async 上下文里，不能再 asyncio.run；跳过 MCP，走本地工具。
        return None
    except RuntimeError:
        pass
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        async def _get_tools():
            client = MultiServerMCPClient(
                {
                    "lab": {
                        "url": settings.MCP_URL,
                        "transport": settings.MCP_TRANSPORT,
                    }
                }
            )
            tools = await client.get_tools()
            return client, tools

        client, tools = asyncio.run(_get_tools())
        _mcp_cache["client"] = client
        _mcp_cache["tools"] = tools
        return tools
    except Exception:
        return None


def build_tools(db: Session, current_user: User, include_uploaded: bool = True):
    """根据当前请求的 db 和用户构建工具列表。

    把 db、current_user 用闭包传进去，工具函数内部就不用每次传 Session。
    include_uploaded=False 时，知识检索只在系统内置文档范围内进行。
    """
    if not TOOL_DECORATOR_AVAILABLE:
        raise BusinessException(message="未安装 langchain-core 依赖")

    scope_document_id = None if include_uploaded else "static"

    def _search_lab_docs(query: str) -> str:
        try:
            return (
                kb_service.search(query, document_id=scope_document_id)
                or "没有检索到相关的资料"
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    _search_lab_docs.__name__ = "search_lab_docs"
    _search_lab_docs.__doc__ = (
        "根据用户的提问检索知识库，包含系统内置文档和用户上传的文档。"
        if include_uploaded
        else "根据用户的提问检索系统内置知识库，不包含用户上传的文档。"
    )
    search_lab_docs = langchain_tool(_search_lab_docs)

    @langchain_tool
    def list_open_labs(keywords: str = "") -> str:
        """查询开放的实验室列表。"""
        try:
            keywords = keywords.strip() or None
            page = lab_service.get_lab_page_list(
                db, page=1, page_size=10, keywords=keywords, status=1
            )
            rows = [
                {
                    "id": item.id,
                    "name": item.name,
                    "location": item.location,
                    "capacity": item.capacity,
                    "open_time": item.open_time,
                    "close_time": item.close_time,
                }
                for item in page.list
            ]
            return json.dumps({"total": page.total, "labs": rows}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @langchain_tool
    def list_lab_equipments(lab_id: int, keywords: str = "") -> str:
        """查询某个实验室的设备列表。"""
        try:
            keywords = keywords.strip() or None
            page = equipment_service.get_equipment_page_list(
                db, page=1, page_size=10, lab_id=int(lab_id), keywords=keywords
            )
            rows = [
                {
                    "id": item.id,
                    "name": item.name,
                    "lab_id": item.lab_id,
                    "lab_name": item.lab_name,
                    "spec": item.spec,
                    "quantity": item.quantity,
                    "status": item.status,
                }
                for item in page.list
            ]
            return json.dumps(
                {"total": page.total, "equipments": rows}, ensure_ascii=False
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @langchain_tool
    def create_lab_reservation(
        lab_id: int,
        date: str,
        start_time: str,
        end_time: str,
        equipment_id: int | None = None,
        remark: str | None = None,
    ) -> str:
        """创建预约单，预约实验室或设备。"""
        try:
            data = ReservationCreateRequest(
                lab_id=lab_id,
                equipment_id=equipment_id,
                date=date,
                start_time=start_time,
                end_time=end_time,
                remark=remark,
            )
            reservation_service.create_reservation(db, current_user, data)
            return json.dumps(
                {
                    "ok": True,
                    "message": "预约已提交，请等待管理员审核",
                    "lab_id": lab_id,
                    "equipment_id": equipment_id,
                    "date": date,
                    "start_time": start_time,
                    "end_time": end_time,
                },
                ensure_ascii=False,
            )
        except BusinessException as exc:
            return json.dumps({"ok": False, "error": exc.message}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @langchain_tool
    def get_today() -> str:
        """获取服务器当前日期，格式如 2026-09-20。"""
        return datetime.now().strftime("%Y-%m-%d")

    # 优先使用 MCP 里的读工具，写工具和日期工具仍在本地（带鉴权）。
    mcp_tools = _load_mcp_tools()
    if mcp_tools:
        return [*mcp_tools, create_lab_reservation, get_today]

    return [
        search_lab_docs,
        list_open_labs,
        list_lab_equipments,
        create_lab_reservation,
        get_today,
    ]
