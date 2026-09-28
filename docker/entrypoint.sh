#!/bin/sh
# Run migrations, then start the server.
set -e

cd /app/backend

# Generate SECRET_KEY once and keep it in the data volume.
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
