# start-dev.ps1 —— 一键启动「智能实验室预约系统」前后端（开发模式）
#
# 用法（PowerShell）：
#   Set-ExecutionPolicy -Scope Process Bypass    # 只在当前窗口临时放开
#   .\start-dev.ps1
#
# 说明：后端默认用 SQLite + Chroma 启动（零配置，不需要 PostgreSQL）。
# 如果你已经起好了 PostgreSQL + pgvector，把下面 $UseSqlite 改成 $false。

param(
    [switch]$WithMcp   # 加上这个参数会额外启动 MCP Server（8100 端口）
)

$ErrorActionPreference = "Stop"
$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$UseSqlite = $true

# 选 Python：优先项目自带的 .venv-clean
$py = Join-Path $backend ".venv-clean\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = Join-Path $backend ".venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) {
    $py = "python"
    Write-Host "[warn] 没找到项目虚拟环境，改用系统 python，依赖可能不全" -ForegroundColor Yellow
}

# 后端启动命令
if ($UseSqlite) {
    $envLine = '$env:DATABASE_URL=""; $env:VECTOR_BACKEND="chroma"; '
    $mode    = "SQLite + Chroma"
} else {
    $envLine = ''
    $mode    = ".env 里的配置（PostgreSQL + pgvector）"
}
$pyQuoted = "& '$py'"
$backendCmd = "cd '$backend'; $envLine$pyQuoted -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1"

Write-Host "==> 后端  http://127.0.0.1:8000/docs   [$mode]" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd

Start-Sleep -Seconds 2

Write-Host "==> 前端  http://127.0.0.1:5175/" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run dev -- --host 127.0.0.1"

if ($WithMcp) {
    Start-Sleep -Seconds 2
    Write-Host "==> MCP   http://127.0.0.1:8100/mcp" -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-Command",
        "cd '$backend'; $envLine$pyQuoted -m app.mcp_server"
}

Write-Host ""
Write-Host "启动中。后端首次加载向量模型要几秒，看到 Application startup complete 就可以用了。" -ForegroundColor Green
Write-Host "  接口文档  http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "  前端页面  http://127.0.0.1:5175/" -ForegroundColor Green
Write-Host "  账号      admin / 123456（管理员）   student / 123456（学生）" -ForegroundColor Green
