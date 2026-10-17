#!/usr/bin/env bash
# ============================================================================
# setup-pg-wsl.sh —— 在 WSL(Ubuntu/Debian) 里初始化 PostgreSQL + pgvector
#
# 用途：让 Windows 侧的 FastAPI 后端（backend/.env 里 DATABASE_URL 指向
#       127.0.0.1:5432）直接连上 WSL 里已有的 PostgreSQL，不用装 Docker。
#
# 用法：在 WSL 终端里执行  bash setup-pg-wsl.sh
#
# 做的事：
#   1. 启动 PostgreSQL 服务
#   2. 安装 pgvector 扩展（apt 优先，不行则源码编译）
#   3. 建库 lab_agent，并启用 vector 扩展
#   4. 把 postgres 用户密码设为 123456（与 backend/.env 一致）
#   5. 确保允许 127.0.0.1 用密码连接（必要时改 pg_hba.conf 并重启）
#
# 环境变量可覆盖：DB_NAME=xxx DB_PASS=xxx bash setup-pg-wsl.sh
# ============================================================================
set -euo pipefail

DB_NAME="${DB_NAME:-lab_agent}"
DB_PASS="${DB_PASS:-123456}"

echo "==> 0. 确认 psql 可用"
if ! command -v psql >/dev/null 2>&1; then
    echo "    没找到 psql。先装：sudo apt-get install -y postgresql"
    exit 1
fi

echo "==> 1. 启动 PostgreSQL"
sudo service postgresql start
sleep 2

echo "==> 2. 检测版本"
PG_VER="$(psql --version | grep -oE '[0-9]+' | head -1)"
echo "    PostgreSQL 大版本: ${PG_VER}"

echo "==> 3. 安装 pgvector 扩展"
if sudo apt-get install -y "postgresql-${PG_VER}-pgvector" 2>/dev/null; then
    echo "    apt 安装成功"
else
    echo "    apt 源里没有 postgresql-${PG_VER}-pgvector，改用源码编译"
    sudo apt-get update -qq
    sudo apt-get install -y build-essential git "postgresql-server-dev-${PG_VER}"
    tmp="$(mktemp -d)"
    git clone --depth 1 --branch v0.8.0 https://github.com/pgvector/pgvector.git "${tmp}/pgvector"
    ( cd "${tmp}/pgvector" && make && sudo make install )
    rm -rf "${tmp}"
fi

echo "==> 4. 建库 ${DB_NAME} 并启用 vector"
if ! sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    sudo -u postgres createdb "${DB_NAME}"
    echo "    已建库"
else
    echo "    库已存在，跳过"
fi
sudo -u postgres psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "==> 5. 设置 postgres 密码为 ${DB_PASS}"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD '${DB_PASS}';"

echo "==> 6. 确保允许 127.0.0.1 密码认证"
HBA="$(sudo -u postgres psql -tAc 'SHOW hba_file;' | xargs)"
echo "    pg_hba.conf: ${HBA}"
if ! grep -qE '^host[[:space:]]+all[[:space:]]+all[[:space:]]+127\.0\.0\.1/32[[:space:]]+(scram-sha-256|md5)' "${HBA}"; then
    echo "    追加 127.0.0.1 密码认证规则"
    echo "host all all 127.0.0.1/32 scram-sha-256" | sudo tee -a "${HBA}" >/dev/null
fi
sudo service postgresql restart
sleep 2

echo ""
echo "全部完成。验证（在 WSL 里）："
echo "  psql -h 127.0.0.1 -U postgres -d ${DB_NAME} -c 'SELECT vector_dims(ARRAY[1,2]::vector);'"
echo "回 Windows 后验证后端能连："
echo "  cd backend"
echo "  .\\.venv-clean\\Scripts\\python.exe -c \"from sqlalchemy import create_engine; create_engine('postgresql+psycopg2://postgres:${DB_PASS}@127.0.0.1:5432/${DB_NAME}').connect(); print('PG 连接 OK')\""
