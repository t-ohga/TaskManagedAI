#!/usr/bin/env bash
# pretool-bash-snapshot.sh
# Bash 実行直前に worktree state のスナップショット（dirty file hash + HEAD SHA + index ref）を取り、
# 後続 PostToolUse dispatcher が「この Bash で変更されたファイル」のみを dispatch 対象にできるようにする。
#
# 入力: stdin で {"tool_input": {"command": "..."}}
# 出力: snapshot を $state_dir/last-pre.tsv と $state_dir/last-pre-meta.tsv に書き出し
#
# 詳細: dispatcher は worktree 全体の dirty tree を見ると、現在の Bash と無関係な既存の
# 変更まで再 dispatch して BLOCK 化される。PreToolUse 時点の snapshot を保存し、
# PostToolUse で変更された path だけを dispatch することで誤発火を防ぐ。
# さらに HEAD 遷移 / 削除 / commit / stash / reset も後続で検出できるよう、
# HEAD SHA と staged tree も保存する。

set -euo pipefail

# 自己再帰防止: dispatcher が走っている最中に子 hook 経由で Bash が呼ばれてもスナップショット更新しない
if [[ "${TASKMANAGEDAI_BASH_DISPATCHER_RUNNING:-}" == "1" ]]; then
  cat >/dev/null
  exit 0
fi

# stdin を消費（消費しないと parent が hang する場合がある）
cat >/dev/null

project_root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$project_root" 2>/dev/null || exit 0

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# project boundary guard (lightweight inline、lib/common.sh source 不要)
# cross-project hook leak 防止: TaskManagedAI worktree 外なら snapshot 不要
# HBG-R1-003 + HBG-R1-004 + R2-001 fix: macOS /bin/realpath -m 非対応のため Python3 fallback
_pr_abs="$project_root"
if command -v python3 >/dev/null 2>&1; then
  _pr_resolved="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$project_root" 2>/dev/null || true)"
  [ -n "$_pr_resolved" ] && _pr_abs="$_pr_resolved"
elif command -v realpath >/dev/null 2>&1; then
  _pr_resolved="$(realpath -m "$project_root" 2>/dev/null || realpath "$project_root" 2>/dev/null || true)"
  [ -n "$_pr_resolved" ] && _pr_abs="$_pr_resolved"
fi
case "$_pr_abs" in
  */TaskManagedAI|*/TaskManagedAI/*|*/taskmanagedai|*/taskmanagedai/*) ;;
  *) exit 0 ;;
esac
unset _pr_abs _pr_resolved

state_dir="$project_root/.claude/.hook-state/bash"
if ! mkdir -p "$state_dir" 2>/dev/null; then
  # state dir 作成不能 = Post 側が fail-closed の SNAPSHOT_FALLBACK 経路へ落ちる
  # ここでは BLOCK にせず、Post 側の fail-closed に委ねる (Pre で BLOCK すると Bash が走らず観測不能になる)
  exit 0
fi

# --- 1. dirty file (modified + untracked) の hash snapshot ---
# fmt: <sha256>\t<path>\n
# 書き込み失敗時は古い snapshot を残さず削除して、Post 側の SNAPSHOT_FALLBACK 経路へ確実に落とす。
tmp_pre="$state_dir/last-pre.tsv.tmp.$$"
if {
  git status --porcelain=v1 -uall 2>/dev/null | awk '{print substr($0, 4)}' | sort -u | while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ ! -e "$f" ]] && continue
    h=$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')
    if [[ -n "$h" ]]; then
      printf '%s\t%s\n' "$h" "$f"
    fi
  done
} > "$tmp_pre" 2>/dev/null && mv "$tmp_pre" "$state_dir/last-pre.tsv" 2>/dev/null; then
  :
else
  rm -f "$tmp_pre" "$state_dir/last-pre.tsv" 2>/dev/null || true
fi

# --- 2. repo state metadata snapshot (HEAD / branch / staged tree) ---
# fmt: <kind>\t<value>\n
tmp_meta="$state_dir/last-pre-meta.tsv.tmp.$$"
if {
  head_sha=$(git rev-parse HEAD 2>/dev/null || echo "")
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  staged_tree=$(git write-tree 2>/dev/null || echo "")
  printf 'HEAD\t%s\n' "$head_sha"
  printf 'BRANCH\t%s\n' "$branch"
  printf 'STAGED_TREE\t%s\n' "$staged_tree"
} > "$tmp_meta" 2>/dev/null && mv "$tmp_meta" "$state_dir/last-pre-meta.tsv" 2>/dev/null; then
  :
else
  rm -f "$tmp_meta" "$state_dir/last-pre-meta.tsv" 2>/dev/null || true
fi

exit 0
