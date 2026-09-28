#!/bin/sh
# 启动前自动执行数据库迁移，使升级镜像即完成 schema 升级。
set -e

cd /app/backend

# 未提供 SECRET_KEY 时自动生成一次并保存在数据卷里，重建容器后登录状态不丢
if [ -z "$SECRET_KEY" ]; then
  KEY_FILE="${DATA_DIR:-/app/data}/.secret_key"
  if [ ! -s "$KEY_FILE" ]; then
    echo "[entrypoint] generating SECRET_KEY at $KEY_FILE"
    python -c "import secrets;print(secrets.token_urlsafe(48))" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
  fi
  SECRET_KEY="$(cat "$KEY_FILE")"
  export SECRET_KEY
fi

echo "[entrypoint] applying database migrations..."
python -m alembic upgrade head

echo "[entrypoint] starting server on 0.0.0.0:8000"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
