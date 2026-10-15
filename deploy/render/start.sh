#!/bin/sh
set -eu

export PORT="${PORT:-10000}"
export DATABOX_STORAGE="${DATABOX_STORAGE:-volume}"
export DATABOX_LOCAL_DIR="${DATABOX_LOCAL_DIR:-/var/lib/databox/objects}"
export DATABOX_RENDER_QUEUE="${DATABOX_RENDER_QUEUE:-http}"
export DATABOX_RENDER_URL="${DATABOX_RENDER_URL:-http://127.0.0.1:8091/internal/tasks/render}"
mkdir -p "$DATABOX_LOCAL_DIR"

cd /app
alembic upgrade head

uvicorn app.main:app --host 127.0.0.1 --port 8000 &
uvicorn app.collab_main:app --host 127.0.0.1 --port 8001 &
uvicorn app.render_main:app --host 127.0.0.1 --port 8091 &

envsubst '${PORT}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
rm -f /etc/nginx/sites-enabled/default
exec nginx -g 'daemon off;'
