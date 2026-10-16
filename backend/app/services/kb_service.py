"""知识库检索服务：向量召回 + BM25 关键词召回 + rerank 重排。

这是简历上最有含金量的一块之一：
1. 向量检索解决“语义相近但用词不同”。
2. BM25 关键词检索解决“精确词、专有名词”。
3. RRF 融合两种排序。
4. 交叉编码器 rerank 做精排。
5. 检索粒度是“块”，命中后按 source + chunk_index 扩展父上下文并带引用。
6. Redis 缓存相似问题，体现成本意识。
"""

import hashlib
import logging

from app.config import settings
from app.services import kb_chunking, vector_store

logger = logging.getLogger(__name__)

_redis = None
_chunks_cache: list[dict] | None = None
_rerank_model = None


def _get_chunks() -> list[dict]:
    """知识库块的内存缓存；文件是静态的，缓存一次即可。"""
    global _chunks_cache
    if _chunks_cache is None:
        _chunks_cache = kb_chunking.load_kb_chunks()
    return _chunks_cache


def _tokenize(text: str) -> list[str]:
    """中文友好的分词近似：单字 + 二元组。

    不引入 jieba 也能处理“开放时间”“实验室预约”这类中文词，
    因为二元组覆盖了大部分双字词。
    """
    cleaned = [ch for ch in text.lower() if ch.isalnum()]
    unigrams = list(cleaned)
    bigrams = [a + b for a, b in zip(cleaned, cleaned[1:])]
    return unigrams + bigrams


def _bm25_search(query: str, top_k: int = 5, document_id: str | None = None) -> list[dict]:
    """BM25 关键词召回，在“块”粒度上打分。"""
    chunks = _get_chunks()
    if document_id:
        chunks = [c for c in chunks if c["meta"].get("document_id") == document_id]
    corpus = [_tokenize(c["doc"]) for c in chunks]
    if not corpus:
        return []
    try:
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(_tokenize(query))
    except Exception:
        query_tokens = set(_tokenize(query))
        scores = [len(query_tokens & set(tokens)) for tokens in corpus]

    hits = [
        {"id": c["id"], "doc": c["doc"], "meta": c["meta"], "score": float(score)}
        for c, score in zip(chunks, scores)
    ]
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


def _vector_search(query: str, top_k: int = 5, document_id: str | None = None) -> list[dict]:
    store = vector_store.get_vector_store()
    if store is None:
        return []
    try:
        return store.search(query, top_k=top_k, document_id=document_id)
    except Exception as exc:
        logger.warning("向量检索失败：%s", exc)
        return []


def _rrf_fusion(vector_hits: list[dict], keyword_hits: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion：按名次融合多路召回，块 id 作为唯一键。"""
    fused: dict[str, dict] = {}
    for rank, hit in enumerate(vector_hits):
        key = hit.get("id") or hit.get("meta", {}).get("source", "") or hit["doc"][:32]
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    for rank, hit in enumerate(keyword_hits):
        key = hit.get("id") or hit.get("meta", {}).get("source", "") or hit["doc"][:32]
        item = fused.setdefault(key, dict(hit))
        item["rrf"] = item.get("rrf", 0) + 1 / (k + rank + 1)
    merged = list(fused.values())
    merged.sort(key=lambda x: x.get("rrf", 0), reverse=True)
    return merged


def _rerank(query: str, hits: list[dict]) -> list[dict]:
    """用 CrossEncoder 对召回结果精排。失败则保持原顺序。"""
    global _rerank_model
    if not settings.RERANK_ENABLED or len(hits) < 2:
        return hits
    try:
        from sentence_transformers import CrossEncoder

        if _rerank_model is None:
            _rerank_model = CrossEncoder(settings.RERANK_MODEL)
        pairs = [(query, h["doc"]) for h in hits]
        scores = _rerank_model.predict(pairs)
        for h, score in zip(hits, scores):
            h["rerank"] = float(score)
        hits.sort(key=lambda x: x.get("rerank", 0), reverse=True)
    except Exception as exc:
        logger.warning("rerank 不可用，使用融合排序：%s", exc)
    return hits


def retrieve(query: str, top_k: int | None = None, document_id: str | None = None) -> list[dict]:
    """检索主入口：返回融合 + 重排后的块命中列表。"""
    if not query.strip():
        return []
    top_k = top_k or settings.RETRIEVAL_TOP_K

    vector_hits = _vector_search(query, top_k=top_k, document_id=document_id)
    keyword_hits = (
        _bm25_search(query, top_k=top_k, document_id=document_id)
        if settings.HYBRID_SEARCH_ENABLED
        else []
    )
    if not vector_hits and not keyword_hits:
        return []

    merged = _rrf_fusion(vector_hits, keyword_hits)
    if settings.RERANK_ENABLED:
        merged = _rerank(query, merged)
    return merged[:top_k]


def _expand_context(hit: dict, window: int | None = None) -> str:
    """把命中的小块扩展成父上下文：同源文档里前后各 window 块拼起来。"""
    window = window if window is not None else settings.CONTEXT_WINDOW
    source = hit.get("meta", {}).get("source")
    chunk_index = hit.get("meta", {}).get("chunk_index")
    if source is None or chunk_index is None:
        return hit.get("doc", "")

    document_id = hit.get("meta", {}).get("document_id")
    same_source = [
        c
        for c in _get_chunks()
        if c["meta"].get("source") == source
        and c["meta"].get("document_id") == document_id
    ]
    if not same_source:
        # 动态上传文档不在静态块缓存里，直接返回命中块本身。
        return hit.get("doc", "")
    low = max(0, int(chunk_index) - window)
    high = min(len(same_source), int(chunk_index) + window + 1)
    return "\n".join(c["doc"] for c in same_source[low:high])


def _redis_client():
    if not settings.REDIS_URL:
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
    """检索并返回拼好的、带引用的资料文本。"""
    if not query.strip():
        return ""

    cache_key = "rag:" + hashlib.md5(query.encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached:
        return cached

    hits = retrieve(query, top_k=settings.FINAL_CONTEXT_K)
    if not hits:
        return ""

    parts = []
    for hit in hits:
        source = hit.get("meta", {}).get("source") or ""
        chunk_index = hit.get("meta", {}).get("chunk_index")
        context = _expand_context(hit)
        parts.append(f"[{source}#{chunk_index}]\n{context}")

    result = "\n\n".join(parts)
    _cache_set(cache_key, result)
    return result


def search_document(document_id: str, query: str) -> str:
    """在指定文档内检索，返回带引用的资料文本。"""
    if not query.strip():
        return ""
    hits = retrieve(query, top_k=settings.RETRIEVAL_TOP_K, document_id=document_id)
    if not hits:
        return ""

    parts = []
    for hit in hits[: settings.FINAL_CONTEXT_K]:
        source = hit.get("meta", {}).get("source") or ""
        chunk_index = hit.get("meta", {}).get("chunk_index")
        parts.append(f"[{source}#{chunk_index}]\n{_expand_context(hit)}")
    return "\n\n".join(parts)


def warmup() -> None:
    vector_store.warmup()
    _get_chunks()
