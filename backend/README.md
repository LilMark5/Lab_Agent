# 后端说明

## 快速启动

建议 Python 3.11 / 3.12。Python 3.14 运行业务部分没问题，
但 chromadb / sentence-transformers 可能没有对应预编译包。

```powershell
cd backend
py -3.11 -m venv .venv-clean
.venv-clean\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app --port 8000 --host 127.0.0.1
```

不配置 `.env` 时默认使用本地 SQLite，并自动创建：

- 管理员：`admin / 123456`
- 学生：`student / 123456`

## 使用 MySQL

1. 创建数据库 `lab_agent`。
2. 复制 `.env.example` 为 `.env`，填写 `DATABASE_URL`。
3. 重启后端，表结构会自动创建。

## 使用 AI 能力

在 `.env` 中填写 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
系统使用 OpenAI 兼容接口，可以接 OpenAI、DeepSeek、Agnes 等。
RAG 使用 ChromaDB + 本地 `BAAI/bge-small-zh-v1.5` 向量模型，首次运行会下载模型。
