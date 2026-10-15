#!/bin/sh
# Write .env.production with new secrets. Refuses to overwrite an existing file.
set -eu

out="${1:-.env.production}"
if [ -e "$out" ]; then
  echo "$out already exists. Remove it yourself before generating another." >&2
  exit 1
fi

if [ -z "${DATABOX_DOMAIN:-}" ]; then
  printf "Domain name (for example databox.example.com): "
  read -r DATABOX_DOMAIN
fi

case "$DATABOX_DOMAIN" in
  ""|*[!A-Za-z0-9.-]*|*..*)
    echo "Use a plain domain name, not a URL and not an IP address." >&2
    exit 1
    ;;
esac

secret() {
  openssl rand -hex 32
}

postgres_password="$(secret)"
redis_password="$(secret)"

umask 077
cat > "$out" <<EOF
APP_ENV=production
DATABOX_DOMAIN=${DATABOX_DOMAIN}
POSTGRES_USER=databox
POSTGRES_PASSWORD=${postgres_password}
POSTGRES_DB=databox
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABOX_REDIS_PASSWORD=${redis_password}
DATABOX_REDIS_URL=redis://:${redis_password}@redis:6379/0
DATABOX_STORAGE=volume
DATABOX_LOCAL_DIR=/var/lib/databox/objects
DATABOX_RENDER_QUEUE=http
DATABOX_RENDER_URL=http://render-worker:8091/internal/tasks/render
DATABOX_TASK_SECRET=$(secret)
DATABOX_AUTH_SECRET=$(secret)
DATABOX_TOKEN_PEPPER=$(secret)
DATABOX_VIEW_TOKEN_SECRET=$(secret)
EOF

echo "Wrote $out. Point ${DATABOX_DOMAIN} at this server, then run: docker compose -f docker-compose.prod.yml up --build -d"
