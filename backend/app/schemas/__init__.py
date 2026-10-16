"""Pydantic Schema 包。

Schema 是接口层的数据契约：
- Request：前端传给后端的数据。
- Response：后端返回给前端的数据。
它和 ORM 模型分离，避免数据库字段直接暴露给接口。
"""
