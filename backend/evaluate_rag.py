"""RAG 离线评估脚本（块粒度版）。

对比三种策略在文档级上的检索质量：
- vector：纯向量召回
- hybrid：向量 + BM25 + RRF 融合
- hybrid+rerank：融合后再过交叉编码器精排

指标：Hit@1 / Hit@3 / MRR / nDCG@3。
"""

import math

from app.services import kb_service

# 每条：问题 -> 应命中的知识文档名（不含 .md 后缀）。
LABELED_CASES = [
    ("实验室开放时间是几点", "开放时间"),
    ("预约之后可以取消吗", "预约规则"),
    ("设备损坏了怎么办", "安全规范"),
    ("预约设备要注意什么", "设备使用"),
]


def _sources(hits: list[dict]) -> list[str]:
    """按顺序取出每个命中的源文档名，并去重。"""
    seen = []
    for hit in hits:
        source = (hit.get("meta") or {}).get("source") or ""
        source = source.replace(".md", "")
        if source and source not in seen:
            seen.append(source)
    return seen


def _mrr(expected: str, sources: list[str]) -> float:
    for rank, source in enumerate(sources, start=1):
        if source == expected:
            return 1 / rank
    return 0.0


def _ndcg_at_k(expected: str, sources: list[str], k: int) -> float:
    for rank, source in enumerate(sources[:k], start=1):
        if source == expected:
            return 1 / math.log2(rank + 1)
    return 0.0


STRATEGIES = {
    "vector": lambda q: kb_service._vector_search(q, top_k=5),
    "hybrid": lambda q: kb_service._rrf_fusion(
        kb_service._vector_search(q, top_k=5),
        kb_service._bm25_search(q, top_k=5),
    ),
    "hybrid+rerank": lambda q: kb_service.retrieve(q, top_k=5),
}


def evaluate():
    print("=" * 72)
    print("RAG 检索评估（块粒度，文档级命中）")
    print("=" * 72)

    for name, strategy in STRATEGIES.items():
        hit1 = hit3 = 0
        mrr_total = 0.0
        ndcg_total = 0.0

        print(f"\n策略：{name}")
        for question, expected in LABELED_CASES:
            hits = strategy(question)
            sources = _sources(hits)
            hit1 += int(expected in sources[:1])
            hit3 += int(expected in sources[:3])
            mrr_total += _mrr(expected, sources)
            ndcg_total += _ndcg_at_k(expected, sources, 3)
            print(f"  {question} -> {sources or ['(无命中)']}")

        n = len(LABELED_CASES)
        print(
            "  汇总：Hit@1=%d/%d  Hit@3=%d/%d  MRR=%.3f  nDCG@3=%.3f"
            % (
                hit1,
                n,
                hit3,
                n,
                mrr_total / n,
                ndcg_total / n,
            )
        )


if __name__ == "__main__":
    evaluate()
