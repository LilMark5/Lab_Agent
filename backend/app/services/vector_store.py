"""向量库抽象层。

同一套 RAG 代码可以在 ChromaDB 和 Milvus 之间切换，体现“面向接口编程”。
Milvus 使用 Milvus Lite（嵌入式文件模式），无需独立部署也能跑真正的 Milvus。
"""

import logging
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)

KB_DIR = BASE_DIR / "data" / "kb"
CHROMA_DIR = BASE_DIR / "data" / "chroma"

# 向量维度与 embedding 模型。
EMBEDDING_MODEL = settings.EMBEDDING_MODEL
EMBEDDING_DIM = 384  # bge-small-zh-v1.5 默认 384 维
_sentence_model = None


def _load_kb_files() -> list[dict]:
    """读取 data/kb 下的所有 Markdown，作为知识文档。"""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        files.append({"id": path.stem, "doc": text, "meta": {"source": path.name}})
    return files


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """用本地 sentence-transformers 模型把文本转成向量。"""
    global _sentence_model
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # 未安装时给出明确提示。
        raise RuntimeError("未安装 sentence-transformers，无法进行向量化") from exc

    # 模型加载很重，必须复用同一个实例，不能每次检索都重新加载。
    if _sentence_model is None:
        _sentence_model = SentenceTransformer(EMBEDDING_MODEL)
    vectors = _sentence_model.encode(texts, normalize_embeddings=True).tolist()
    return vectors


class ChromaVectorStore:
    """基于 ChromaDB 的向量存储实现。"""

    def __init__(self) -> None:
        self._col = None
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    def _ensure(self):
        if self._col is not None:
            return self._col
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except Exception as exc:
            raise RuntimeError("未安装 chromadb") from exc

        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        col = client.get_or_create_collection(
            name="lab_kb", embedding_function=embedding_fn
        )
        if col.count() == 0:
            files = _load_kb_files()
            if files:
                col.add(
                    ids=[f["id"] for f in files],
                    documents=[f["doc"] for f in files],
                    metadatas=[f["meta"] for f in files],
                )
        self._col = col
        self._ready = True
        return col

    def count(self) -> int:
        col = self._ensure()
        return int(col.count())

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        col = self._ensure()
        res = col.query(query_texts=[query], n_results=min(top_k, col.count()))
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        hits = []
        for doc, meta, dist in zip(docs, metas, distances):
            score = 1 / (1 + float(dist))  # 距离越小，分数越高。
            hits.append({"id": meta.get("source", ""), "doc": doc, "meta": meta, "score": score})
        return hits


class MilvusVectorStore:
    """基于 Milvus Lite 的向量存储实现。"""

    COLLECTION = "lab_kb"

    def __init__(self) -> None:
        self._client = None
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    def _ensure(self):
        if self._client is not None:
            return self._client
        try:
            from pymilvus import DataType, MilvusClient
        except Exception as exc:
            raise RuntimeError("未安装 pymilvus，无法使用 Milvus") from exc

        Path(settings.MILVUS_LOCAL_URI).parent.mkdir(parents=True, exist_ok=True)
        client = MilvusClient(uri=settings.MILVUS_LOCAL_URI)

        if not client.has_collection(self.COLLECTION):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("pk", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
            schema.add_field("text", DataType.VARCHAR, max_length=8192)
            schema.add_field("source", DataType.VARCHAR, max_length=512)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="FLAT",
                metric_type="COSINE",
            )
            client.create_collection(
                collection_name=self.COLLECTION,
                schema=schema,
                index_params=index_params,
            )

        files = _load_kb_files()
        if files:
            vectors = _embed_texts([f["doc"] for f in files])
            rows = [
                {
                    "pk": f["id"],
                    "embedding": vector,
                    "text": f["doc"],
                    "source": f["meta"]["source"],
                }
                for f, vector in zip(files, vectors)
            ]
            # upsert 按主键幂等，重复启动不会产生重复数据。
            client.upsert(collection_name=self.COLLECTION, data=rows)

        self._client = client
        self._ready = True
        return client

    def count(self) -> int:
        client = self._ensure()
        try:
            stats = client.get_collection_stats(self.COLLECTION)
            return int(stats.get("row_count", 0))
        except Exception:
            return len(_load_kb_files())

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        client = self._ensure()
        vector = _embed_texts([query])[0]
        res = client.search(
            collection_name=self.COLLECTION,
            data=[vector],
            limit=top_k,
            output_fields=["pk", "text", "source"],
        )
        hits = []
        for hit in res[0]:
            entity = hit.get("entity") or {}
            hits.append(
                {
                    "id": entity.get("pk", ""),
                    "doc": entity.get("text", ""),
                    "meta": {"source": entity.get("source", "")},
                    "score": float(hit.get("distance", 0)),  # COSINE 越大越相关
                }
            )
        return hits


_store: Any = None
_init_attempted = False


def get_vector_store():
    """按配置选择向量库；失败时回退到可用的实现。"""
    global _store, _init_attempted
    if _store is not None:
        return _store
    if _init_attempted:
        # 已经试过且失败，就不再阻塞后续请求；下次进程重启再重试。
        return None
    _init_attempted = True

    preferred = settings.VECTOR_BACKEND.lower()
    if preferred == "milvus":
        try:
            store = MilvusVectorStore()
            store._ensure()
            _store = store
            return store
        except Exception as exc:
            logger.warning("Milvus 初始化失败，回退 ChromaDB：%s", exc)

    try:
        store = ChromaVectorStore()
        store._ensure()
        _store = store
        return store
    except Exception:
        logger.warning("ChromaDB 不可用，RAG 功能降级为空实现")
        _store = None
        return None


def warmup() -> None:
    """启动时预热向量库和 embedding 模型。"""
    try:
        store = get_vector_store()
        if store and store.count() > 0:
            store.search("预热", top_k=1)
            logger.info("向量库预热完成，后端：%s", type(store).__name__)
    except Exception as exc:
        logger.warning("向量库预热失败，服务继续启动：%s", exc)
