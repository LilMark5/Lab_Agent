"""RAG 离线评估脚本。

不需要额外依赖，用一份小规模标注集验证检索质量：
- hit@1 / hit@2：正确文档是否进入 top-k。
- 同时对比“纯向量召回”和“混合召回(RRF)”，直观展示混合检索的提升。

运行：
    python evaluate_rag.py
"""

from app.services import kb_service

# 每条：问题 -> 应命中的知识文档名（不含 .md 后缀）。
LABELED_CASES = [
    ("实验室开放时间是几点", "开放时间"),
    ("预约之后可以取消吗", "预约规则"),
    ("设备损坏了怎么办", "安全规范"),
    ("预约设备要注意什么", "设备使用"),
]


def source_of(hit: dict) -> str:
    source = (hit.get("meta") or {}).get("source") or ""
    return source.replace(".md", "")


def evaluate():
    print("=" * 60)
    print("RAG 检索评估")
    print("=" * 60)

    vector_total = 0
    hybrid_total = 0

    for question, expected in LABELED_CASES:
        vector_hits = kb_service._vector_search(question, top_k=3)
        keyword_hits = kb_service._bm25_search(question, top_k=3)
        hybrid_hits = kb_service._rrf_fusion(vector_hits, keyword_hits)

        vector_sources = [source_of(h) for h in vector_hits]
        hybrid_sources = [source_of(h) for h in hybrid_hits]

        vector_hit = expected in vector_sources[:2]
        hybrid_hit = expected in hybrid_sources[:2]
        vector_total += int(vector_hit)
        hybrid_total += int(hybrid_hit)

        print(f"\n问题：{question}")
        print(f"  期望命中：{expected}")
        print(f"  纯向量 top3：{vector_sources or ['(无)']} -> hit@2={vector_hit}")
        print(f"  混合检索 top3：{hybrid_sources or ['(无)']} -> hit@2={hybrid_hit}")

    n = len(LABELED_CASES)
    print("\n" + "=" * 60)
    print(f"纯向量 hit@2：{vector_total}/{n}")
    print(f"混合检索 hit@2：{hybrid_total}/{n}")
    print("=" * 60)


if __name__ == "__main__":
    evaluate()
