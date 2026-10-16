"""向量库抽象层。

同一个 RAG 检索代码可以在 ChromaDB / Milvus / pgvector 之间切换，体现“面向接口编程”。
三者的共同接口：
    is_ready() -> bool
    count()    -> int
    search(query, top_k) -> list[dict]  # 每项含 id / doc / meta / score

知识文档统一由 kb_chunking.load_kb_chunks() 切成块后再入库，
因此三个后端存的是“块”，而不是整篇 Markdown。
"""

import logging
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, settings
from app.services import kb_chunking

logger = logging.getLogger(__name__)

CHROMA_DIR = BASE_DIR / "data" / "chroma"

# 向量维度与 embedding 模型。
EMBEDDING_MODEL = settings.EMBEDDING_MODEL
EMBEDDING_DIM = 384  # bge-small-zh-v1.5 默认 384 维
_sentence_model = None


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """用本地 sentence-transformers 模型把文本转成向量。"""
    global _sentence_model
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise RuntimeError("未安装 sentence-transformers，无法进行向量化") from exc

    # 模型加载很重，必须复用同一个实例，不能每次检索都重新加载。
    if _sentence_model is None:
        _sentence_model = SentenceTransformer(EMBEDDING_MODEL)
    return _sentence_model.encode(texts, normalize_embeddings=True).tolist()


class ChromaVectorStore:
    """基于 ChromaDB 的向量存储实现。"""

    COLLECTION = "lab_kb_chunks"

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
            name=self.COLLECTION, embedding_function=embedding_fn
        )
        if col.count() == 0:
            chunks = kb_chunking.load_kb_chunks()
            if chunks:
                col.add(
                    ids=[c["id"] for c in chunks],
                    documents=[c["doc"] for c in chunks],
                    metadatas=[c["meta"] for c in chunks],
                )
        self._col = col
        self._ready = True
        return col

    def count(self) -> int:
        return int(self._ensure().count())

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        col = self._ensure()
        res = col.query(
            query_texts=[query],
            n_results=min(top_k, col.count()),
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        hits = []
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
            score = 1 / (1 + float(dist))  # 距离越小，分数越高。
            hits.append(
                {
                    "id": chunk_id,
                    "doc": doc,
                    "meta": meta or {},
                    "score": score,
                }
            )
        return hits


class MilvusVectorStore:
    """基于 Milvus Lite 的向量存储实现。"""

    COLLECTION = "lab_kb_chunks"

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
            schema.add_field("chunk_index", DataType.INT64)
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

        chunks = kb_chunking.load_kb_chunks()
        if chunks:
            vectors = _embed_texts([c["doc"] for c in chunks])
            rows = [
                {
                    "pk": c["id"],
                    "embedding": vector,
                    "text": c["doc"],
                    "source": c["meta"]["source"],
                    "chunk_index": int(c["meta"]["chunk_index"]),
                }
                for c, vector in zip(chunks, vectors)
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
            return len(kb_chunking.load_kb_chunks())

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        client = self._ensure()
        vector = _embed_texts([query])[0]
        res = client.search(
            collection_name=self.COLLECTION,
            data=[vector],
            limit=top_k,
            output_fields=["pk", "text", "source", "chunk_index"],
        )
        hits = []
        for hit in res[0]:
            entity = hit.get("entity") or {}
            hits.append(
                {
                    "id": entity.get("pk", ""),
                    "doc": entity.get("text", ""),
                    "meta": {
                        "source": entity.get("source", ""),
                        "chunk_index": entity.get("chunk_index"),
                    },
                    "score": float(hit.get("distance", 0)),  # COSINE 越大越相关
                }
            )
        return hits


class PgVectorStore:
    """基于 PostgreSQL + pgvector 的向量存储实现。

    业务数据与向量放在同一个 PostgreSQL 里，HNSW 索引 + cosine 距离。
    向量以字符串形式传参并在 SQL 里 `::vector` 强制转换，避免依赖连接级适配器注册。
    """

    TABLE = "kb_chunks"

    def __init__(self) -> None:
        self._engine = None
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    def _ensure(self):
        if self._engine is not None:
            return self._engine
        if not settings.DATABASE_URL:
            raise RuntimeError(
                "使用 pgvector 需要先配置 PostgreSQL 的 DATABASE_URL（镜像需启用 pgvector 扩展）"
            )

        from sqlalchemy import create_engine, text

        self._engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        table = self.TABLE

        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id VARCHAR(255) PRIMARY KEY,
                        text TEXT NOT NULL,
                        source VARCHAR(512) NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        embedding vector({EMBEDDING_DIM}) NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_embedding "
                    f"ON {table} USING hnsw (embedding vector_cosine_ops)"
                )
            )

        chunks = kb_chunking.load_kb_chunks()
        if chunks:
            vectors = _embed_texts([c["doc"] for c in chunks])
            with self._engine.begin() as conn:
                for chunk, vector in zip(chunks, vectors):
                    conn.execute(
                        text(
                            f"""
                            INSERT INTO {table}
                                (id, text, source, chunk_index, embedding)
                            VALUES
                                (:id, :text, :source, :chunk_index, :embedding::vector)
                            ON CONFLICT (id) DO UPDATE SET
                                text = EXCLUDED.text,
                                source = EXCLUDED.source,
                                chunk_index = EXCLUDED.chunk_index,
                                embedding = EXCLUDED.embedding
                            """
                        ),
                        {
                            "id": chunk["id"],
                            "text": chunk["doc"],
                            "source": chunk["meta"]["source"],
                            "chunk_index": int(chunk["meta"]["chunk_index"]),
                            "embedding": str(vector),
                        },
                    )

        self._ready = True
        return self._engine

    def count(self) -> int:
        from sqlalchemy import text

        engine = self._ensure()
        with engine.connect() as conn:
            return int(
                conn.execute(text(f"SELECT count(*) FROM {self.TABLE}")).scalar_one()
            )

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        from sqlalchemy import text

        engine = self._ensure()
        vector = _embed_texts([query])[0]
        sql = text(
            f"""
            SELECT id, text, source, chunk_index,
                   1 - (embedding <=> :vec::vector) AS score
            FROM {self.TABLE}
            ORDER BY embedding <=> :vec::vector
            LIMIT :k
            """
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, {"vec": str(vector), "k": top_k}).mappings().all()

        hits = []
        for row in rows:
            hits.append(
                {
                    "id": row["id"],
                    "doc": row["text"],
                    "meta": {
                        "source": row["source"],
                        "chunk_index": row["chunk_index"],
                    },
                    "score": float(row["score"]),
                }
            )
        return hits


_store: Any = None
_init_attempted = False


def get_vector_store():
    """按配置选择向量库。"""
    global _store, _init_attempted
    if _store is not None:
        return _store

    preferred = settings.VECTOR_BACKEND.lower()

    # 显式选 pgvector：失败直接抛出，不静默回退，避免“以为在用 pgvector 其实在用 Chroma”。
    if preferred == "pgvector":
        store = PgVectorStore()
        store._ensure()
        _store = store
        return store

    if _init_attempted:
        return None
    _init_attempted = True

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
