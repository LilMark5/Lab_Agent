"""全局配置。

本项目使用 pydantic-settings 读取环境变量和 `.env` 文件。
好处：配置与代码分离，密钥不会硬编码进代码里。
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 后端项目根目录。`config.py` 位于 backend/app/，所以 `.parent.parent` 是 backend/。
BASE_DIR = Path(__file__).resolve().parent.parent

# 文件上传目录。头像、实验室封面、设备图片都会放到这里。
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 知识库 Markdown 源文件目录。
KB_DIR = BASE_DIR / "data" / "kb"

# 文件上传限制：100MB，实际业务通常只允许图片。
MAX_FILE_SIZE = 100 * 1024 * 1024

# 允许上传的后缀。做文件上传时白名单比黑名单安全。
ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
}


class Settings(BaseSettings):
    """应用配置类。

    字段名会映射到环境变量或 `.env` 中的同名键。
    `extra="ignore"` 表示 `.env` 里多出来的键不会报错。
    """

    # 数据库连接串。缺省时自动使用本地 SQLite，方便零配置直接运行。
    # PostgreSQL 示例（生产推荐）：
    #   postgresql+psycopg2://postgres:123456@127.0.0.1:5432/lab_agent
    # MySQL 示例：mysql+pymysql://root:123456@127.0.0.1:3306/lab_agent
    DATABASE_URL: str | None = None

    # JWT 配置。生产环境必须换成足够长的随机密钥，并放到环境变量中。
    JWT_SECRET_KEY: str = "dev-only-secret-key-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # LLM 配置。走 OpenAI 兼容协议，可以接 OpenAI、DeepSeek、Agnes 等。
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"

    # RAG 使用的本地向量模型。第一次运行会自动下载，耗时可能较长。
    EMBEDDING_MODEL: str = "BAAI/bge-small-zh-v1.5"
    HF_ENDPOINT: str | None = None
    # 文档切块：递归字符切分器的块大小与重叠量。
    CHUNK_SIZE: int = 200
    CHUNK_OVERLAP: int = 40
    # 检索：每路召回 top-k、最终保留块数、父上下文扩展窗口。
    RETRIEVAL_TOP_K: int = 5
    FINAL_CONTEXT_K: int = 3
    CONTEXT_WINDOW: int = 1

    # 向量库后端：auto / chroma / milvus。
    # milvus 使用 Milvus Lite（嵌入式文件模式，零运维，仍是真正的 Milvus）。
    # pgvector：需要把 DATABASE_URL 指向启用 pgvector 扩展的 PostgreSQL。
    VECTOR_BACKEND: str = "auto"
    # 注意：不要叫 MILVUS_URI，pymilvus 会自动读同名环境变量并当作服务器地址。
    MILVUS_LOCAL_URI: str = "./data/milvus.db"

    # 混合检索：向量召回 + BM25 关键词召回 + 可选 rerank 重排。
    HYBRID_SEARCH_ENABLED: bool = True
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "BAAI/bge-reranker-base"

    # Redis：用于 AI 接口限流与相似问题缓存。
    REDIS_URL: str | None = None

    # MCP：是否让 Agent 优先从 MCP Server 加载工具。
    MCP_ENABLED: bool = True
    MCP_TRANSPORT: str = "streamable_http"
    MCP_URL: str = "http://127.0.0.1:8100/mcp"

    # LangGraph checkpointer：会话状态持久化到本地 SQLite。
    # 生产可替换为 PostgreSQL（langgraph-checkpoint-postgres）。
    CHECKPOINT_DB_PATH: str = str(BASE_DIR / "data" / "checkpoints.db")

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# 把镜像地址写进环境变量，sentence-transformers 会自动读取。
if settings.HF_ENDPOINT:
    os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
