"""检索融合逻辑的单元测试。"""

import asyncio
from types import SimpleNamespace

from app.services import kb_service


def test_rrf_fusion_keys_by_chunk_id():
    vector_hits = [{"id": "a#0", "doc": "x", "meta": {}, "score": 0.9}]
    keyword_hits = [
        {"id": "a#0", "doc": "x", "meta": {}, "score": 0.8},
        {"id": "b#0", "doc": "y", "meta": {}, "score": 0.7},
    ]
    merged = kb_service._rrf_fusion(vector_hits, keyword_hits)
    assert len(merged) == 2
    by_id = {hit["id"]: hit for hit in merged}
    assert by_id["a#0"]["rrf"] > by_id["b#0"]["rrf"]


class _FakeStore:
    """只实现 list_chunks 的假向量库，用于验证语料来源。"""

    def list_chunks(self):
        return [
            {
                "id": "doc1#0",
                "doc": "量子计算平台每周一开放",
                "meta": {"source": "量子.md", "chunk_index": 0, "document_id": "doc1"},
            }
        ]


def test_chunks_come_from_vector_store(monkeypatch):
    kb_service.invalidate_cache()
    monkeypatch.setattr(kb_service.vector_store, "get_vector_store", lambda: _FakeStore())
    chunks = kb_service._get_chunks()
    assert chunks[0]["meta"]["document_id"] == "doc1"
    kb_service.invalidate_cache()


def test_bm25_covers_uploaded_document(monkeypatch):
    kb_service.invalidate_cache()
    monkeypatch.setattr(kb_service.vector_store, "get_vector_store", lambda: _FakeStore())
    hits = kb_service._bm25_search("量子计算", top_k=3)
    assert any(hit["meta"]["document_id"] == "doc1" for hit in hits)
    kb_service.invalidate_cache()


def test_search_passes_document_scope(monkeypatch):
    captured = {}

    def fake_retrieve(query, top_k=None, document_id=None):
        captured["document_id"] = document_id
        return []

    monkeypatch.setattr(kb_service, "retrieve", fake_retrieve)
    kb_service.search("开放时间", document_id="static")
    assert captured["document_id"] == "static"


def test_build_tools_respects_include_uploaded(monkeypatch):
    from app.services import agent_tools

    monkeypatch.setattr(agent_tools.settings, "MCP_ENABLED", False)
    user = SimpleNamespace(id=1, role="student")

    tools_all = asyncio.run(
        agent_tools.build_tools(None, user, include_uploaded=True)
    )
    tools_static = asyncio.run(
        agent_tools.build_tools(None, user, include_uploaded=False)
    )

    search_all = next(t for t in tools_all if t.name == "search_lab_docs")
    search_static = next(t for t in tools_static if t.name == "search_lab_docs")
    assert "用户上传" in (search_all.description or "")
    assert "不包含用户上传" in (search_static.description or "")


def test_rewrite_query_disabled_returns_original(monkeypatch):
    """关闭查询改写时，原样返回，且不发任何 LLM 请求。"""
    monkeypatch.setattr(kb_service.settings, "QUERY_REWRITE_ENABLED", False)
    assert kb_service._rewrite_query("实验室开放时间是几点") == "实验室开放时间是几点"


def test_rewrite_query_falls_back_on_error(monkeypatch):
    """LLM 调用失败时回退原始问题，不抛异常。"""
    monkeypatch.setattr(kb_service.settings, "QUERY_REWRITE_ENABLED", True)
    monkeypatch.setattr(kb_service.settings, "LLM_API_KEY", "sk-test")

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        @property
        def chat(self):
            raise RuntimeError("network down")

    # _rewrite_query 内部是 `from openai import OpenAI`，直接换掉它。
    import openai as openai_module

    monkeypatch.setattr(openai_module, "OpenAI", _BoomClient)
    monkeypatch.setattr(kb_service, "_rewrite_client", None)
    q = "实验室开放时间是几点"
    assert kb_service._rewrite_query(q) == q


def test_retrieve_applies_rewrite(monkeypatch):
    """检索入口确实用改写后的查询去召回。"""
    captured = {}

    monkeypatch.setattr(kb_service, "_rewrite_query", lambda q: "开放时间")
    monkeypatch.setattr(kb_service.settings, "HYBRID_SEARCH_ENABLED", False)

    def fake_vector(query, top_k=5, document_id=None):
        captured["query"] = query
        return []

    monkeypatch.setattr(kb_service, "_vector_search", fake_vector)
    kb_service.retrieve("实验室开放时间是几点")
    assert captured["query"] == "开放时间"


def test_load_mcp_tools_works_in_async_context(monkeypatch):
    """流式场景（async 上下文）下 MCP 工具应能正常加载，不再返回 None。"""
    from app.services import agent_tools

    monkeypatch.setattr(agent_tools.settings, "MCP_ENABLED", True)
    agent_tools._mcp_cache["tried"] = False
    agent_tools._mcp_cache["tools"] = None

    class _FakeTool:
        def __init__(self, name):
            self.name = name

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def get_tools(self):
            return [_FakeTool("mcp_list_labs")]

    import langchain_mcp_adapters.client as client_mod

    monkeypatch.setattr(client_mod, "MultiServerMCPClient", _FakeClient)

    tools = asyncio.run(agent_tools._load_mcp_tools())
    assert tools is not None
    assert [t.name for t in tools] == ["mcp_list_labs"]
    # 结果已缓存，二次调用直接命中缓存，不再新建连接。
    agent_tools._mcp_cache["tried"] = True
    cached = asyncio.run(agent_tools._load_mcp_tools())
    assert cached == tools
