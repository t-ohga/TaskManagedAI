#!/usr/bin/env bash
# Deterministically generate the TaskManagedAI hook sha256 manifest.
#
# This script is safe by default: it writes only to an explicit --output path or
# to stdout via --stdout. Installing the result into ~/.claude-trusted is a
# separate operator step.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/regenerate-hook-manifest.sh --output <path> [--repo-root <path>]
  bash scripts/regenerate-hook-manifest.sh --stdout [--repo-root <path>]

Options:
  --repo-root <path>  Repository root. Defaults to git rev-parse --show-toplevel.
  --output <path>    Manifest output path. Parent directory must already exist.
  --stdout           Print manifest to stdout.
  -h, --help         Show this help.
USAGE
}

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
output_path=""
to_stdout="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="${2:?--repo-root requires a path}"
      shift 2
      ;;
    --output)
      output_path="${2:?--output requires a path}"
      shift 2
      ;;
    --stdout)
      to_stdout="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '[ERROR] unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$to_stdout" == "1" && -n "$output_path" ]]; then
  printf '[ERROR] use either --stdout or --output, not both\n' >&2
  exit 2
fi
if [[ "$to_stdout" != "1" && -z "$output_path" ]]; then
  printf '[ERROR] explicit --output or --stdout is required\n' >&2
  usage >&2
  exit 2
fi

cd "$repo_root"

if [[ ! -d ".claude/hooks" ]]; then
  printf '[ERROR] .claude/hooks does not exist under repo root: %s\n' "$repo_root" >&2
  exit 2
fi

hash_file() {
  local file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    printf '[ERROR] shasum or sha256sum is required\n' >&2
    return 127
  fi
}

build_manifest() {
  local hooks=()
  local hook
  while IFS= read -r hook; do
    hooks+=("$hook")
  done < <(find .claude/hooks -type f -name '*.sh' -print | LC_ALL=C sort)

  if [[ ${#hooks[@]} -eq 0 ]]; then
    printf '[ERROR] no hook scripts found under .claude/hooks\n' >&2
    return 2
  fi

  for hook in "${hooks[@]}"; do
    if [[ ! -x "$hook" ]]; then
      printf '[ERROR] hook is not executable: %s\n' "$hook" >&2
      return 2
    fi
    printf '%s  %s\n' "$(hash_file "$hook")" "$hook"
  done
}

if [[ "$to_stdout" == "1" ]]; then
  build_manifest
else
  output_dir="$(dirname "$output_path")"
  if [[ ! -d "$output_dir" ]]; then
    printf '[ERROR] output directory does not exist: %s\n' "$output_dir" >&2
    exit 2
  fi
  tmp_path="$(mktemp "$output_dir/.hook-manifest.XXXXXX")"
  trap 'rm -f "$tmp_path"' EXIT
  build_manifest > "$tmp_path"
  mv "$tmp_path" "$output_path"
  trap - EXIT
fi
