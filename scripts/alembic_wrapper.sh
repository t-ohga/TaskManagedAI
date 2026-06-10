#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/alembic_wrapper.sh [--dry-run] [alembic args...]

Runs Alembic inside the api container while stripping host/container
TASKMANAGEDAI_DATABASE_URL and DATABASE_URL overrides from the Alembic process.
Defaults to `current` when no alembic args are provided.
EOF
}

dry_run=0
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--dry-run" ]]; then
  dry_run=1
  shift
fi

if [[ "$#" -eq 0 ]]; then
  alembic_args=(current)
else
  alembic_args=("$@")
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

env_file="${TASKHUB_ALEMBIC_ENV_FILE:-.env.local}"
compose_files=(-f docker-compose.yml -f docker-compose.dev.yml)
compose_cmd=(
  docker compose
  "${compose_files[@]}"
  --env-file "$env_file"
  exec -T api
  env -u TASKMANAGEDAI_DATABASE_URL -u DATABASE_URL
  uv run --no-sync alembic
  "${alembic_args[@]}"
)
host_env=(env -u TASKMANAGEDAI_DATABASE_URL -u DATABASE_URL)

if [[ "$dry_run" -eq 1 ]]; then
  printf 'repo_root=%q\n' "$repo_root"
  printf 'env_file=%q\n' "$env_file"
  printf 'command='
  printf '%q ' "${host_env[@]}" "${compose_cmd[@]}"
  printf '\n'
  exit 0
fi

if [[ ! -f "$env_file" ]]; then
  printf 'ERROR: env file not found: %s\n' "$env_file" >&2
  exit 2
fi

exec "${host_env[@]}" "${compose_cmd[@]}"
