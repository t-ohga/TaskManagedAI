#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL_FAST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fail-fast)
      FAIL_FAST=1
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

run_section() {
  local name="$1"
  shift
  local status=0

  echo "==> ${name}"
  if "$@"; then
    return 0
  else
    status=$?
  fi

  echo "Section failed: ${name}" >&2
  if [[ ${FAIL_FAST} -eq 1 ]]; then
    exit "${status}"
  fi

  return "${status}"
}

record_section() {
  local status=0

  if run_section "$@"; then
    return 0
  else
    status=$?
  fi

  if [[ ${overall_status} -eq 0 ]]; then
    overall_status=${status}
  fi

  return 0
}

overall_status=0

cd "${ROOT_DIR}"

record_section "backend pytest" env TASKMANAGEDAI_RUN_DB_TESTS="${TASKMANAGEDAI_RUN_DB_TESTS:-1}" uv run pytest tests/ -v
record_section "frontend vitest" bash -c 'cd frontend && pnpm test'
record_section "frontend playwright" bash -c 'cd frontend && pnpm exec playwright test'

exit "${overall_status}"

