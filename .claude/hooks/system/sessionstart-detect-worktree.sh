#!/usr/bin/env bash
# Emit SessionStart worktree context for TaskManagedAI without modifying project files.
#
# 入力: stdin で JSON (tool_input / tool_response 等)
# 出力: exit 0 で許可、exit 2 で BLOCK + ユーザーへ system message
# 詳細: https://docs.claude.com/en/docs/claude-code/hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

HOOK_EVENT_NAME="SessionStart"

cwd="$(pwd)"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# project boundary guard (HBG-R1-005 fix: log dir/file write より前に判定)
# cross-project session で TaskManagedAI log を作成しない。
# - 別 project session で本 hook が呼ばれた場合 cwd は別 project root
# - boundary guard 通過後に初めて LOG_DIR / LOG_FILE を初期化する
if ! is_taskmanagedai_path "$cwd"; then
  exit 0
fi

LOG_DIR="$HOME/.claude/local/taskmanagedai"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/sessionstart-worktree-$(date +%Y-%m-%d).log"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf '[%s] cwd=%s not_in_git_repo=yes\n' "$timestamp" "$cwd" >>"$LOG_FILE"
  exit 0
fi

root="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$cwd")"
worktrees="$(git worktree list 2>/dev/null || true)"
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || printf '(detached)')"

is_worktree="no"
if printf '%s\n' "$worktrees" | grep -Fq "$root"; then
  primary_path="$(printf '%s\n' "$worktrees" | awk 'NR==1 {print $1}')"
  if [ "$root" != "$primary_path" ]; then
    is_worktree="yes"
  fi
fi

work_item=""
if [[ "$branch" =~ (SP-[0-9]+|BL-[0-9]+|ADR-[0-9]+|AC-HARD-[0-9]+) ]]; then
  work_item="${BASH_REMATCH[1]}"
fi

printf '[%s] cwd=%s root=%s branch=%s worktree=%s item=%s\n' "$timestamp" "$cwd" "$root" "$branch" "$is_worktree" "$work_item" >>"$LOG_FILE"

if [ "$is_worktree" = "yes" ]; then
  msg="TaskManagedAI worktree detected: root=${root}, branch=${branch}"
  if [ -n "$work_item" ]; then
    msg="${msg}, item=${work_item}"
  fi
  emit_additional_context "SessionStart" "$msg"
fi

exit 0

