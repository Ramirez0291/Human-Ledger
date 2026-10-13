#!/bin/sh
# 启动前自动执行数据库迁移，使升级镜像即完成 schema 升级。
set -e

cd /app/backend

echo "[entrypoint] applying database migrations..."
python -m alembic upgrade head

echo "[entrypoint] starting server on 0.0.0.0:8000"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
