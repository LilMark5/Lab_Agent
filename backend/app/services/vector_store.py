"""向量库抽象层。

同一个 RAG 检索代码可以在 ChromaDB / Milvus / pgvector 之间切换，体现“面向接口编程”。
三者的共同接口：
    is_ready() -> bool
    count()    -> int
    add_chunks(chunks)            # 新增/更新块（按 id 幂等）
    delete_chunks(document_id)    # 删除某文档的全部块
    search(query, top_k, document_id=None) -> list[dict]

每个块通过 meta.document_id 归属到文档：静态知识库用 "static"，上传文档用其注册 ID。
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
_sentence_model = None
_embedding_dim = None


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


def get_embedding_dim() -> int:
    """动态获取 embedding 维度，避免换模型后维度写死导致建表/建索引失败。"""
    global _embedding_dim
    if _embedding_dim is None:
        _embedding_dim = len(_embed_texts(["dim"])[0])
    return _embedding_dim


class ChromaVectorStore:
    """基于 ChromaDB 的向量存储实现。"""

    COLLECTION = "lab_kb_chunks_v2"

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
        self._col = col
        if col.count() == 0:
            self.add_chunks(kb_chunking.load_kb_chunks())
        self._ready = True
        return col

    def add_chunks(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        col = self._ensure()
        col.upsert(
            ids=[c["id"] for c in chunks],
            documents=[c["doc"] for c in chunks],
            metadatas=[c["meta"] for c in chunks],
        )

    def delete_chunks(self, document_id: str) -> None:
        col = self._ensure()
        col.delete(where={"document_id": document_id})

    def list_chunks(self) -> list[dict]:
        col = self._ensure()
        if col.count() == 0:
            return []
        res = col.get(include=["documents", "metadatas"])
        ids = res.get("ids") or []
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        return [
            {"id": i, "doc": d, "meta": m or {}}
            for i, d, m in zip(ids, docs, metas)
        ]

    def count(self) -> int:
        return int(self._ensure().count())

    def search(self, query: str, top_k: int = 5, document_id: str | None = None) -> list[dict]:
        col = self._ensure()
        where = {"document_id": document_id} if document_id else None
        res = col.query(
            query_texts=[query],
            n_results=min(top_k, col.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        hits = []
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
            score = 1 / (1 + float(dist))
            hits.append({"id": chunk_id, "doc": doc, "meta": meta or {}, "score": score})
        return hits


class MilvusVectorStore:
    """基于 Milvus 的向量存储实现（Lite 文件模式或独立服务）。"""

    COLLECTION = "lab_kb_chunks_v2"

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
        self._client = client

        if not client.has_collection(self.COLLECTION):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("pk", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=get_embedding_dim())
            schema.add_field("text", DataType.VARCHAR, max_length=8192)
            schema.add_field("source", DataType.VARCHAR, max_length=512)
            schema.add_field("chunk_index", DataType.INT64)
            schema.add_field("document_id", DataType.VARCHAR, max_length=64)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding", index_type="FLAT", metric_type="COSINE"
            )
            client.create_collection(
                collection_name=self.COLLECTION, schema=schema, index_params=index_params
            )

        self.add_chunks(kb_chunking.load_kb_chunks())
        self._ready = True
        return client

    def add_chunks(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        client = self._ensure()
        vectors = _embed_texts([c["doc"] for c in chunks])
        rows = [
            {
                "pk": c["id"],
                "embedding": vector,
                "text": c["doc"],
                "source": c["meta"]["source"],
                "chunk_index": int(c["meta"]["chunk_index"]),
                "document_id": c["meta"].get("document_id") or "static",
            }
            for c, vector in zip(chunks, vectors)
        ]
        client.upsert(collection_name=self.COLLECTION, data=rows)

    def delete_chunks(self, document_id: str) -> None:
        client = self._ensure()
        client.delete(collection_name=self.COLLECTION, filter=f'document_id == "{document_id}"')

    def list_chunks(self) -> list[dict]:
        client = self._ensure()
        try:
            rows = client.query(
                collection_name=self.COLLECTION,
                filter="",
                output_fields=["pk", "text", "source", "chunk_index", "document_id"],
                limit=16384,
            )
        except Exception:
            return []
        return [
            {
                "id": row.get("pk", ""),
                "doc": row.get("text", ""),
                "meta": {
                    "source": row.get("source", ""),
                    "chunk_index": row.get("chunk_index"),
                    "document_id": row.get("document_id"),
                },
            }
            for row in rows
        ]

    def count(self) -> int:
        client = self._ensure()
        try:
            stats = client.get_collection_stats(self.COLLECTION)
            return int(stats.get("row_count", 0))
        except Exception:
            return len(kb_chunking.load_kb_chunks())

    def search(self, query: str, top_k: int = 5, document_id: str | None = None) -> list[dict]:
        client = self._ensure()
        vector = _embed_texts([query])[0]
        filter_expr = f'document_id == "{document_id}"' if document_id else None
        res = client.search(
            collection_name=self.COLLECTION,
            data=[vector],
            limit=top_k,
            filter=filter_expr,
            output_fields=["pk", "text", "source", "chunk_index", "document_id"],
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
                        "document_id": entity.get("document_id"),
                    },
                    "score": float(hit.get("distance", 0)),
                }
            )
        return hits


class PgVectorStore:
    """基于 PostgreSQL + pgvector 的向量存储实现。"""

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
        dim = get_embedding_dim()

        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            existing_dim = conn.execute(
                text(
                    "SELECT a.atttypmod FROM pg_attribute a "
                    "JOIN pg_class c ON a.attrelid = c.oid "
                    "WHERE c.relname = :t AND a.attname = 'embedding'"
                ),
                {"t": table},
            ).scalar()
            if existing_dim and int(existing_dim) != dim:
                conn.execute(text(f"DROP TABLE {table}"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id VARCHAR(255) PRIMARY KEY,
                        text TEXT NOT NULL,
                        source VARCHAR(512) NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        document_id VARCHAR(64),
                        embedding vector({dim}) NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS document_id VARCHAR(64)")
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_embedding "
                    f"ON {table} USING hnsw (embedding vector_cosine_ops)"
                )
            )

        self.add_chunks(kb_chunking.load_kb_chunks())
        self._ready = True
        return self._engine

    def add_chunks(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        from sqlalchemy import text

        engine = self._ensure()
        vectors = _embed_texts([c["doc"] for c in chunks])
        with engine.begin() as conn:
            for chunk, vector in zip(chunks, vectors):
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {self.TABLE}
                            (id, text, source, chunk_index, document_id, embedding)
                        VALUES
                            (:id, :text, :source, :chunk_index, :document_id,
                             CAST(:embedding AS vector))
                        ON CONFLICT (id) DO UPDATE SET
                            text = EXCLUDED.text,
                            source = EXCLUDED.source,
                            chunk_index = EXCLUDED.chunk_index,
                            document_id = EXCLUDED.document_id,
                            embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "id": chunk["id"],
                        "text": chunk["doc"],
                        "source": chunk["meta"]["source"],
                        "chunk_index": int(chunk["meta"]["chunk_index"]),
                        "document_id": chunk["meta"].get("document_id") or "static",
                        "embedding": str(vector),
                    },
                )

    def delete_chunks(self, document_id: str) -> None:
        from sqlalchemy import text

        engine = self._ensure()
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {self.TABLE} WHERE document_id = :d"),
                {"d": document_id},
            )

    def list_chunks(self) -> list[dict]:
        from sqlalchemy import text

        engine = self._ensure()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT id, text, source, chunk_index, document_id FROM {self.TABLE}"
                )
            ).mappings().all()
        return [
            {
                "id": row["id"],
                "doc": row["text"],
                "meta": {
                    "source": row["source"],
                    "chunk_index": row["chunk_index"],
                    "document_id": row["document_id"],
                },
            }
            for row in rows
        ]

    def count(self) -> int:
        from sqlalchemy import text

        engine = self._ensure()
        with engine.connect() as conn:
            return int(
                conn.execute(text(f"SELECT count(*) FROM {self.TABLE}")).scalar_one()
            )

    def search(self, query: str, top_k: int = 5, document_id: str | None = None) -> list[dict]:
        from sqlalchemy import text

        engine = self._ensure()
        vector = _embed_texts([query])[0]
        where = "WHERE document_id = :doc" if document_id else ""
        params: dict[str, Any] = {"vec": str(vector), "k": top_k}
        if document_id:
            params["doc"] = document_id
        sql = text(
            f"""
            SELECT id, text, source, chunk_index, document_id,
                   1 - (embedding <=> CAST(:vec AS vector)) AS score
            FROM {self.TABLE}
            {where}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
            """
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()

        hits = []
        for row in rows:
            hits.append(
                {
                    "id": row["id"],
                    "doc": row["text"],
                    "meta": {
                        "source": row["source"],
                        "chunk_index": row["chunk_index"],
                        "document_id": row["document_id"],
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
            logger.warning(
                "Milvus 初始化失败，回退 ChromaDB（Windows 不支持 Milvus Lite，"
                "需用 Docker 部署 Milvus 服务）：%s",
                exc,
            )

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
