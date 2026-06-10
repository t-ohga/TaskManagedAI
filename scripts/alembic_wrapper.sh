#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/alembic_wrapper.sh [--dry-run] [alembic args...]

Runs Alembic inside the api container. Host-side TASKMANAGEDAI_DATABASE_URL /
DATABASE_URL overrides are stripped BEFORE invoking docker compose so that host
shell state cannot leak into compose interpolation. Inside the container the
.env.local-provided env (the same configuration the running api uses) is the
single source of truth and is intentionally left intact.
Before executing, the selected env file's TASKMANAGEDAI_DATABASE_URL is compared
(masked) against the running api container's env; a mismatch aborts (exit 3) to
prevent migrating against a container started from a different/stale env file.
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
# Mac 実機検証 B-4 fix (PR #336 再検証 FAIL): 旧版は container 内でも
# `env -u TASKMANAGEDAI_DATABASE_URL -u DATABASE_URL` で unset していたため、Alembic が
# Settings の _DEV_DATABASE_URL (default password) に fallback し、.env.local の実 password と
# ずれて InvalidPasswordError になっていた (default password 環境でしか動かない設計ミス)。
# container 内の env は .env.local 由来で実行中の api app と同一の正本。strip は host 側のみ。
compose_cmd=(
  docker compose
  "${compose_files[@]}"
  --env-file "$env_file"
  exec -T api
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

# B-4 R1 preflight (Codex adversarial HIGH): `docker compose --env-file` は compose 補間にのみ
# 効き、**起動済み container の env を再注入しない**。operator が TASKHUB_ALEMBIC_ENV_FILE で
# 別 env を選んだつもりでも、stale な env で起動済みの container に migration を当て得る。
# 選択 env file の TASKMANAGEDAI_DATABASE_URL と api container 実 env を比較し、不一致は
# fail-closed (誤 DB への migration 防止)。raw URL は password を含むため masked 表示のみ。
mask_url() {
  printf '%s' "$1" | sed 's|//[^@]*@|//***@|'
}

expected_url="$(grep -E '^TASKMANAGEDAI_DATABASE_URL=' "$env_file" | tail -n 1 | cut -d= -f2- || true)"
# R3 (Codex adversarial MEDIUM): 空同士の一致で素通りさせない。env file に URL が無い場合、
# Alembic は Settings の development default URL へ fallback し得るため、preflight の目的
# (選択 env file と実行中 api の DB binding 確認) が成立しない → 欠落自体を fail-closed。
if [[ -z "$expected_url" ]]; then
  {
    printf 'ERROR: %s に TASKMANAGEDAI_DATABASE_URL がありません (fail-closed)。\n' "$env_file"
    echo "ERROR: migration 先 DB を特定できないため中止します。env file に TASKMANAGEDAI_DATABASE_URL を定義してください。"
  } >&2
  exit 3
fi
actual_url="$("${host_env[@]}" docker compose "${compose_files[@]}" --env-file "$env_file" \
  exec -T api printenv TASKMANAGEDAI_DATABASE_URL 2>/dev/null || true)"
actual_url="${actual_url%$'\r'}"
if [[ -z "$actual_url" ]]; then
  {
    echo "ERROR: api container から TASKMANAGEDAI_DATABASE_URL を取得できません (fail-closed)。"
    echo "ERROR: api container が未起動か、env 未設定の container です。docker compose up -d api を確認してください。"
  } >&2
  exit 3
fi
if [[ "$expected_url" != "$actual_url" ]]; then
  {
    echo "ERROR: env file と api container の TASKMANAGEDAI_DATABASE_URL が一致しません (fail-closed)。"
    printf 'ERROR:   env file (%s): %s\n' "$env_file" "$(mask_url "$expected_url")"
    printf 'ERROR:   api container        : %s\n' "$(mask_url "$actual_url")"
    echo "ERROR: container が古い env で起動している可能性があります。"
    echo "ERROR: 対処: docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file $env_file up -d --force-recreate api"
  } >&2
  exit 3
fi

exec "${host_env[@]}" "${compose_cmd[@]}"
