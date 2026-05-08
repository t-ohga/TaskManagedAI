#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.dev.yml)
ENV_FILE="${ROOT_DIR}/.env.local"

cd "${ROOT_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp .env.example .env.local
  cat >&2 <<'MSG'
Created .env.local from .env.example.
Replace REPLACE_ME values, set TASKMANAGEDAI_ENVIRONMENT=development, then rerun scripts/dev/init.sh.
MSG
  exit 1
fi

export TASKMANAGEDAI_ENVIRONMENT="${TASKMANAGEDAI_ENVIRONMENT:-development}"

uv sync --locked

(
  cd "${FRONTEND_DIR}"
  pnpm install --frozen-lockfile
)

docker compose "${COMPOSE_FILES[@]}" --env-file .env.local pull postgres redis
docker compose "${COMPOSE_FILES[@]}" --env-file .env.local up -d postgres redis

uv run alembic upgrade head
uv run python -m backend.app.seeds.runner

echo "TaskManagedAI development environment initialized."

