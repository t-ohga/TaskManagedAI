#!/usr/bin/env bash
# posttool-bash-file-dispatcher.sh
# Bash 経由のファイル変更後、Pre/Post snapshot diff + HEAD 遷移 + staged tree 比較で
# 「この Bash で変更されたファイル」を網羅的に取得し、対応 hook を file_path 付きで再実行する。
#
# 入力: stdin で {"tool_input": {"command": "..."}, "tool_response": {...}}
# 出力: 各 hook の出力を集約した systemMessage (warning + BLOCK 両方を伝播)
#
# 検出する変更パターン:
# - dirty file の hash 変化 (modified)
# - dirty file の新規追加 (untracked)
# - dirty file の削除 (Pre にあって Post にない)
# - HEAD 遷移時の `git diff <pre_head> <post_head> --name-only` (commit / reset / cherry-pick / merge 等)
# - staged tree の変化 (git add で stage された path)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../lib/common.sh"

# 自己再帰防止: env guard で dispatcher が呼び出した子 hook が Bash を起動した場合のループを防ぐ。
# command 文字列マッチは禁止 (ユーザー制御可能で bypass 容易)。
if [[ "${TASKMANAGEDAI_BASH_DISPATCHER_RUNNING:-}" == "1" ]]; then
  cat >/dev/null  # stdin を消費して parent の hang を防ぐ
  exit 0
fi
export TASKMANAGEDAI_BASH_DISPATCHER_RUNNING=1

# stdin から JSON を取得（消費しないと parent が hang する）
# shellcheck disable=SC2034  # 子 hook へは fake_payload を渡すので未使用だが consume は必須
input_json="$(cat)"

project_root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$project_root" 2>/dev/null || exit 0

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# project boundary guard (cross-project dispatcher leak 防止、lib/common.sh § is_taskmanagedai_path)
# dispatcher は file_path 抽出前に project_root で判定し、TaskManagedAI 外なら一切 dispatch しない
if ! is_taskmanagedai_path "$project_root"; then
  exit 0
fi

state_dir="${TASKMANAGEDAI_HOOK_STATE_DIR:-$project_root/.claude/.hook-state/bash}"
if [[ "$state_dir" != /* ]]; then
  state_dir="$project_root/$state_dir"
fi
if [[ ! -d "$state_dir" || ! -w "$state_dir" ]]; then
  emit_system_message "PostToolUse" "BLOCK bash-dispatcher: state dir unavailable (fail-closed). Run the matching PreToolUse snapshot or verify TASKMANAGEDAI_HOOK_STATE_DIR: $state_dir" 2>/dev/null || true
  exit 2
fi
pre_file="$state_dir/last-pre.tsv"
pre_meta_file="$state_dir/last-pre-meta.tsv"

# Pre snapshot 欠落時は fail-closed: 全 dirty file を dispatch 対象にする (state 削除攻撃対策)。
# state は repo 内で mutable なので、欠落・改ざんを「無事の証」と扱わず、最大検査範囲で再検査する。
SNAPSHOT_FALLBACK="0"
if [[ ! -f "$pre_file" ]]; then
  SNAPSHOT_FALLBACK="1"
  emit_system_message "PostToolUse" "WARN bash-dispatcher: Pre snapshot missing; falling back to full dirty-tree scan (state-deletion mitigation)" 2>/dev/null || true
fi

# --- 1. Post snapshot を作成 (現在の dirty file の hash) ---
post_file="$state_dir/last-post.tsv"
{
  git status --porcelain=v1 -uall 2>/dev/null | awk '{print substr($0, 4)}' | sort -u | while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ ! -e "$f" ]] && continue
    h=$(shasum -a 256 "$f" 2>/dev/null | awk '{print $1}')
    if [[ -n "$h" ]]; then
      printf '%s\t%s\n' "$h" "$f"
    fi
  done
} > "$post_file" 2>/dev/null || true

# --- 2. dirty file の changed/new/deleted を抽出 ---
if [[ "$SNAPSHOT_FALLBACK" == "1" ]]; then
  # Pre snapshot 欠落 → 全 dirty file を dispatch 対象に (state 削除攻撃対策)
  changed_files=$(awk -F'\t' '{print $2}' "$post_file" 2>/dev/null || true)
else
  changed_files=$(
    awk -F'\t' '
      NR==FNR { pre[$2]=$1; next }
      { post[$2]=$1 }
      END {
        # Post にあって、Pre にないか hash 変化した path
        for (p in post) {
          if (!(p in pre) || pre[p] != post[p]) print p
        }
        # Pre にあって、Post にない path（削除）
        for (p in pre) {
          if (!(p in post)) print p
        }
      }
    ' "$pre_file" "$post_file"
  )
fi

# --- 3. HEAD 遷移 / staged tree 変化を反映 ---
if [[ -f "$pre_meta_file" ]]; then
  pre_head=$(awk -F'\t' '$1 == "HEAD" {print $2}' "$pre_meta_file")
  pre_staged=$(awk -F'\t' '$1 == "STAGED_TREE" {print $2}' "$pre_meta_file")

  post_head=$(git rev-parse HEAD 2>/dev/null || echo "")
  post_staged=$(git write-tree 2>/dev/null || echo "")

  # HEAD 遷移時: pre と post の HEAD diff を全て候補化 (commit / reset / merge / cherry-pick 等)
  if [[ -n "$pre_head" && -n "$post_head" && "$pre_head" != "$post_head" ]]; then
    head_diff=$(git diff --name-only "$pre_head" "$post_head" 2>/dev/null || true)
    if [[ -n "$head_diff" ]]; then
      changed_files=$(printf '%s\n%s' "$changed_files" "$head_diff")
    fi
  fi

  # staged tree 変化時: cached diff を候補化 (git add)
  if [[ -n "$pre_staged" && -n "$post_staged" && "$pre_staged" != "$post_staged" ]]; then
    staged_diff=$(git diff --name-only --cached 2>/dev/null || true)
    if [[ -n "$staged_diff" ]]; then
      changed_files=$(printf '%s\n%s' "$changed_files" "$staged_diff")
    fi
  fi
fi

# --- 4. 重複除去 + .claude/.hook-state/ 自身の変更を除外 ---
changed_files=$(printf '%s\n' "$changed_files" | awk 'NF' | sort -u | grep -v '^\.claude/\.hook-state/' || true)

if [[ -z "$changed_files" ]]; then
  exit 0
fi

# --- 4.0. 制御面 (control-plane) ファイルの同一 Bash 実行内変更を fail-closed で検出 ---
# .claude/hooks/** / .claude/settings.json / .claude/.hook-state/** が変更されたら
# 後続実行で hook を改ざんできるため、即 BLOCK し ADR Gate / 人手承認を要求する。
control_plane_violations=()
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  case "$f" in
    .claude/hooks/*|.claude/settings.json|.claude/.hook-state/*)
      control_plane_violations+=("$f")
      ;;
    /*)
      # 絶対 path 形態でも repo-relative に正規化して再判定
      rel="${f#"$project_root"/}"
      case "$rel" in
        .claude/hooks/*|.claude/settings.json|.claude/.hook-state/*)
          control_plane_violations+=("$rel")
          ;;
      esac
      ;;
  esac
done <<< "$changed_files"

if [[ ${#control_plane_violations[@]} -gt 0 ]]; then
  msg=$(printf '%s\n' "${control_plane_violations[@]}")
  emit_system_message "PostToolUse" "BLOCK bash-dispatcher: control-plane mutation detected (fail-closed). Hook code / settings / state must not change inside a Bash tool call. Move the change to an explicit Edit/Write with ADR review:\n$msg" 2>/dev/null || printf '%s\n' "$msg" >&2
  exit 2
fi

# Hook に file_path を渡して dispatch する hook list (PostToolUse Edit|Write 相当)
hooks_to_dispatch=(
  "$SCRIPT_DIR/../sprint/check-sprint-pack-frontmatter.sh"
  "$SCRIPT_DIR/../adr/check-adr-gate.sh"
  "$SCRIPT_DIR/../provider/check-payload-data-class.sh"
  "$SCRIPT_DIR/../secretbroker/check-secretbroker-ddl.sh"
  "$SCRIPT_DIR/../agentrun/check-state-enum.sh"
  "$SCRIPT_DIR/../postgres/check-tenant-boundary-ddl.sh"
  "$SCRIPT_DIR/../runner/check-dangerous-command-fixture.sh"
  "$SCRIPT_DIR/../tailscale/check-tailscale-grants.sh"
  "$SCRIPT_DIR/../file-changed/warn-external-migration-edit.sh"
  "$SCRIPT_DIR/../quality/check-payload-data-class-on-toml.sh"
)

# --- 4.5. 各 child hook の存在 + 実行可能性を事前検証 (改ざん耐性: chmod -x / 削除されていないか) ---
# 不在または非実行可能な child hook は fail-closed で BLOCK
hook_integrity_failures=()
for hook in "${hooks_to_dispatch[@]}"; do
  if [[ ! -f "$hook" ]]; then
    hook_integrity_failures+=("$(basename "$hook"): file missing")
  elif [[ ! -x "$hook" ]]; then
    hook_integrity_failures+=("$(basename "$hook"): not executable (chmod -x?)")
  fi
done

if [[ ${#hook_integrity_failures[@]} -gt 0 ]]; then
  msg=$(printf '%s\n' "${hook_integrity_failures[@]}")
  emit_system_message "PostToolUse" "BLOCK bash-dispatcher: child hook integrity failure (fail-closed): $msg" 2>/dev/null || printf '%s\n' "$msg" >&2
  exit 2
fi

# --- 5. 各 hook を 1 回だけ実行し、stdout/stderr/exit を capture (warning も BLOCK も伝播) ---
overall_exit=0
collected_messages=()

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  # 絶対 path 化
  if [[ "$file" != /* ]]; then
    file="$project_root/$file"
  fi
  # 削除された file でも file_path として hook に渡す（hook 側で existence check）

  # 各 hook へ Edit 風の JSON を作って投げる
  fake_payload=$(jq -n \
    --arg fp "$file" \
    --arg src "bash-dispatcher" \
    '{tool_input: {file_path: $fp}, tool_response: {file_path: $fp}, _dispatched_from: $src}')

  for hook in "${hooks_to_dispatch[@]}"; do
    # integrity check は §4.5 で実施済。ここでは set +e で実行
    set +e
    hook_output="$(printf '%s' "$fake_payload" | "$hook" 2>&1)"
    rc=$?
    set -e

    # 非空 output を集約 (warning も BLOCK も保持)
    if [[ -n "$hook_output" ]]; then
      collected_messages+=("[$(basename "$hook")] for $file:")
      collected_messages+=("$hook_output")
      collected_messages+=("---")
    fi

    if [[ $rc -eq 2 ]]; then
      overall_exit=2
    fi
  done
done <<< "$changed_files"

# --- 6. 集約された message を出力 (lib/common.sh の helper 使用) ---
if [[ ${#collected_messages[@]} -gt 0 ]]; then
  full_msg=$(printf '%s\n' "${collected_messages[@]}")
  if [[ "$overall_exit" -eq 2 ]]; then
    emit_system_message "PostToolUse" "BLOCK bash-dispatcher: $full_msg" 2>/dev/null || printf '%s\n' "$full_msg" >&2
  else
    emit_additional_context "$full_msg" 2>/dev/null || printf '%s\n' "$full_msg" >&2
  fi
fi

exit "$overall_exit"
