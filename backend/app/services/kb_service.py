"""知识库检索服务：向量召回 + BM25 关键词召回 + rerank 重排。

这是简历上最有含金量的一块之一：
1. 向量检索解决“语义相近但用词不同”。
2. BM25 关键词检索解决“精确词、专有名词”。
3. RRF 融合两种排序。
4. 交叉编码器 rerank 做精排。
5. Redis 缓存相似问题，体现成本意识。
"""

import hashlib
import logging

from app.config import BASE_DIR, settings
from app.services import vector_store

logger = logging.getLogger(__name__)

KB_DIR = BASE_DIR / "data" / "kb"
_redis = None


def _tokenize(text: str) -> list[str]:
    """中文友好的分词近似：单字 + 二元组。

    不引入 jieba 也能处理“开放时间”“实验室预约”这类中文词，
    因为二元组覆盖了大部分双字词。
    """
    cleaned = [ch for ch in text.lower() if ch.isalnum()]  # 去掉标点和空格
    unigrams = list(cleaned)                                # 单字
    bigrams = [a + b for a, b in zip(cleaned, cleaned[1:])]  # 二元组
    return unigrams + bigrams


def _load_kb_files() -> list[dict]:
    KB_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            files.append({"id": path.stem, "doc": text, "meta": {"source": path.name}})
    return files


def _bm25_search(query: str, top_k: int = 5) -> list[dict]:
    """BM25 关键词召回。优先用 rank_bm25，否则退化为 token 重叠打分。"""
    files = _load_kb_files()                          # 用原始 KB 文件做关键词检索
    corpus = [_tokenize(f["doc"]) for f in files]     # 每个文档变成词袋
    if not corpus:
        return []
    try:
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi(corpus)                      # BM25 统计模型
        scores = bm25.get_scores(_tokenize(query))    # 给每个文档打分
    except Exception:
        # 没装 rank_bm25 时的降级：词集合交集大小当分数
        query_tokens = set(_tokenize(query))
        scores = [len(query_tokens & set(tokens)) for tokens in corpus]

    hits = [
        {"doc": f["doc"], "meta": f["meta"], "score": float(score)}
        for f, score in zip(files, scores)
    ]
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


def _vector_search(query: str, top_k: int = 5) -> list[dict]:
    store = vector_store.get_vector_store()  # 可能是 Chroma 或 Milvus
    if store is None:
        return []
    try:
        return store.search(query, top_k=top_k)
    except Exception as exc:
        logger.warning("向量检索失败：%s", exc)
        return []


def _rrf_fusion(vector_hits: list[dict], keyword_hits: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion：按名次融合多路召回，简单且效果稳定。"""
    fused: dict[str, dict] = {}  # key -> 命中的文档项
    for rank, hit in enumerate(vector_hits):
        key = hit.get("meta", {}).get("source") or hit.get("doc", "")[:32]  # 用文件名做唯一键
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)  # RRF 名次分
    for rank, hit in enumerate(keyword_hits):
        key = hit.get("meta", {}).get("source") or hit.get("doc", "")[:32]
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    merged = list(fused.values())
    merged.sort(key=lambda x: x.get("rrf", 0), reverse=True)
    return merged


def _rerank(query: str, hits: list[dict]) -> list[dict]:
    """用 CrossEncoder 对召回结果精排。失败则保持原顺序。"""
    if not settings.RERANK_ENABLED or len(hits) < 2:
        return hits
    try:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(settings.RERANK_MODEL)          # 交叉编码器：更准但更慢
        pairs = [(query, h["doc"]) for h in hits]            # 问题-文档成对打分
        scores = model.predict(pairs)
        for h, score in zip(hits, scores):
            h["rerank"] = float(score)
        hits.sort(key=lambda x: x.get("rerank", 0), reverse=True)
    except Exception as exc:
        logger.warning("rerank 不可用，使用融合排序：%s", exc)
    return hits


def _redis_client():
    if not settings.REDIS_URL:  # 没配 Redis 就不缓存
        return None
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis

        _redis = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        _redis = None
    return _redis


def _cache_get(key: str) -> str | None:
    client = _redis_client()
    if client is None:
        return None
    try:
        return client.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: str, ttl: int = 3600) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.set(key, value, ex=ttl)
    except Exception:
        pass


def search(query: str) -> str:
    """检索并返回拼好的资料文本。"""
    if not query.strip():
        return ""

    cache_key = "rag:" + hashlib.md5(query.encode("utf-8")).hexdigest()  # 问题做缓存键
    cached = _cache_get(cache_key)  # 先查缓存
    if cached:
        return cached

    vector_hits = _vector_search(query, top_k=5)               # 语义召回
    keyword_hits = _bm25_search(query, top_k=5) if settings.HYBRID_SEARCH_ENABLED else []  # 关键词召回

    if not vector_hits and not keyword_hits:
        return ""

    merged = _rrf_fusion(vector_hits, keyword_hits)  # 两路召回融合
    if settings.RERANK_ENABLED:
        merged = _rerank(query, merged)              # 精排

    parts = []
    for hit in merged[:2]:
        source = hit.get("meta", {}).get("source") or ""  # 拼上来源，方便大模型引用
        parts.append(f"[{source}]\n{hit['doc']}")
    result = "\n\n".join(parts)
    _cache_set(cache_key, result)
    return result


def warmup() -> None:
    vector_store.warmup()
