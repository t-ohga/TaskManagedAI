#!/usr/bin/env bash
# Verify the repo-external TaskManagedAI hook trust root without mutating it.

set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/verify-hook-trust-root.sh [options]

Options:
  --repo-root <path>   Repository root. Defaults to git rev-parse --show-toplevel.
  --trust-root <path>  Trusted wrapper directory. Defaults to ~/.claude-trusted.
  --state-root <path>  Trusted state directory. Defaults to ~/.claude-trusted-state/taskmanagedai.
  --skip-self-test     Do not run wrapper --self-test.
  -h, --help           Show this help.
USAGE
}

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
trust_root="${HOME}/.claude-trusted"
state_root="${HOME}/.claude-trusted-state/taskmanagedai"
run_self_test="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="${2:?--repo-root requires a path}"
      shift 2
      ;;
    --trust-root)
      trust_root="${2:?--trust-root requires a path}"
      shift 2
      ;;
    --state-root)
      state_root="${2:?--state-root requires a path}"
      shift 2
      ;;
    --skip-self-test)
      run_self_test="0"
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

wrapper_path="$trust_root/taskmanagedai-hook-wrapper.sh"
manifest_path="$trust_root/taskmanagedai-hook-manifest.sha256"

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 2
}

ok() {
  printf '[OK] %s\n' "$1"
}

require_not_group_world_writable() {
  local path="$1"
  if [[ -n "$(find "$path" -prune -perm -022 -print -quit 2>/dev/null)" ]]; then
    fail "path is group/world writable: $path"
  fi
}

cd "$repo_root" 2>/dev/null || fail "repo root is not accessible: $repo_root"
[[ -d ".claude/hooks" ]] || fail ".claude/hooks is missing under repo root: $repo_root"

[[ -d "$trust_root" ]] || fail "trust root is missing: $trust_root"
require_not_group_world_writable "$trust_root"
ok "trust root exists and is not group/world writable"

[[ -f "$wrapper_path" ]] || fail "wrapper is missing: $wrapper_path"
[[ -x "$wrapper_path" ]] || fail "wrapper is not executable: $wrapper_path"
require_not_group_world_writable "$wrapper_path"
ok "wrapper exists and is executable"

[[ -f "$manifest_path" ]] || fail "manifest is missing: $manifest_path"
[[ -r "$manifest_path" ]] || fail "manifest is not readable: $manifest_path"
require_not_group_world_writable "$manifest_path"
ok "manifest exists and is readable"

[[ -d "$state_root" ]] || fail "state root is missing: $state_root"
[[ -w "$state_root" ]] || fail "state root is not writable: $state_root"
require_not_group_world_writable "$state_root"
ok "state root exists and is writable"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
expected_manifest="$tmp_dir/taskmanagedai-hook-manifest.sha256"

bash "$repo_root/scripts/regenerate-hook-manifest.sh" \
  --repo-root "$repo_root" \
  --output "$expected_manifest"

if ! cmp -s "$expected_manifest" "$manifest_path"; then
  fail "manifest mismatch: $manifest_path does not match current repo hooks"
fi
ok "manifest matches current repo hooks"

if [[ "$run_self_test" == "1" ]]; then
  TASKMANAGEDAI_HOOK_REPO_ROOT="$repo_root" \
    TASKMANAGEDAI_HOOK_MANIFEST="$manifest_path" \
    TASKMANAGEDAI_HOOK_STATE_DIR="$state_root" \
    "$wrapper_path" --self-test >/dev/null
  ok "wrapper self-test passed"
fi
