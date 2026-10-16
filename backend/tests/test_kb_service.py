"""检索融合逻辑的单元测试。"""

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
