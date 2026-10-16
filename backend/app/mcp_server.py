"""独立运行的 MCP Server。

把实验室知识检索、实验室/设备查询暴露成标准 MCP 工具，
任何支持 MCP 的客户端（Claude、Codex、自研 Agent）都能接入。

运行方式：
    python -m app.mcp_server

这里只暴露“读”工具；写库（预约）仍留在有鉴权的 LangGraph Agent 里，
这是刻意的安全边界：公开协议服务不直接接受写操作。
"""

import json
import os

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.services import kb_service


def _db() -> Session:
    return SessionLocal()  # 每个工具自己开一个短会话，用完关闭


def build_mcp_server():
    """构建 FastMCP 实例。依赖未安装时抛异常，由调用方处理。"""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(name="lab-agent-mcp", instructions="智能实验室预约系统 MCP 服务")  # 服务元信息

    @mcp.tool()
    def search_lab_docs(query: str) -> str:
        """检索知识库（内置文档与用户上传文档，含预约规则、开放时间、安全规范等）。"""
        result = kb_service.search(query)
        return result or "没有检索到相关资料"

    @mcp.tool()
    def list_open_labs(keywords: str = "") -> str:
        """查询开放中的实验室列表。"""
        db = _db()
        try:
            query = db.query(Lab).filter(Lab.status == 1)  # 只查开放中的实验室
            if keywords.strip():
                like = f"%{keywords.strip()}%"  # SQL 模糊匹配通配符
                query = query.filter(
                    (Lab.name.ilike(like)) | (Lab.location.ilike(like))
                )
            rows = [  # 只返回回答需要的字段，避免整表外泄
                {
                    "id": lab.id,
                    "name": lab.name,
                    "location": lab.location,
                    "capacity": lab.capacity,
                    "open_time": lab.open_time,
                    "close_time": lab.close_time,
                }
                for lab in query.limit(20).all()
            ]
            return json.dumps({"total": len(rows), "labs": rows}, ensure_ascii=False)  # 中文不转义
        finally:
            db.close()

    @mcp.tool()
    def list_lab_equipments(lab_id: int, keywords: str = "") -> str:
        """查询某个实验室下的设备列表。"""
        db = _db()
        try:
            query = db.query(Equipment).filter(Equipment.lab_id == lab_id)  # 设备挂在该实验室下
            if keywords.strip():
                query = query.filter(Equipment.name.ilike(f"%{keywords.strip()}%"))
            rows = [
                {
                    "id": e.id,
                    "name": e.name,
                    "lab_id": e.lab_id,
                    "spec": e.spec,
                    "quantity": e.quantity,
                    "status": e.status,
                }
                for e in query.limit(20).all()
            ]
            return json.dumps(
                {"total": len(rows), "equipments": rows}, ensure_ascii=False
            )
        finally:
            db.close()

    return mcp


def main() -> None:
    """入口：用 streamable HTTP 跑 MCP Server。"""
    mcp = build_mcp_server()
    port = int(os.environ.get("MCP_PORT", "8100"))
    mcp.run(transport="streamable-http", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
