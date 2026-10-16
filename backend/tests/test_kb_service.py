"""检索融合逻辑的单元测试。"""

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

    tools_all = agent_tools.build_tools(None, user, include_uploaded=True)
    tools_static = agent_tools.build_tools(None, user, include_uploaded=False)

    search_all = next(t for t in tools_all if t.name == "search_lab_docs")
    search_static = next(t for t in tools_static if t.name == "search_lab_docs")
    assert "用户上传" in (search_all.description or "")
    assert "不包含用户上传" in (search_static.description or "")
