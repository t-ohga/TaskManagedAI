#!/usr/bin/env bash
# codex_pr_full_review.sh — Codex の全 finding を必ず取得する verify helper
#
# 使用必須タイミング (CLAUDE.md §6.5.9 + .claude/rules/codex-pr-review-checklist.md):
# - PR 起票直後 / push 後 / merge 直前 / `@codex review` trigger 後
#
# 内部実装 (Codex PR #7 R4 finding 反映):
# 1. inline diff comments を --paginate で全件取得 (F-PR7-011 adopt)
# 2. conversation comments を --paginate で全件取得 (mandatory)
# 3. top-level reviews も全件
# 4. Codex bot のみ filter (F-PR7-012 adopt)
# 5. commit_id filter は使わない (line tracking 取りこぼし防止)
# 6. fail-closed: API 失敗時 exit 1

set -e -o pipefail

PR="${1:?usage: $0 <PR-number>}"
REPO="${REPO:-t-ohga/TaskManagedAI}"
BOT="chatgpt-codex-connector[bot]"
REVIEWER="chatgpt-codex-connector"

echo "==================================================================="
echo "PR #${PR} — Codex full review check (ALL endpoints, paginated)"
echo "==================================================================="

echo ""
echo "=== 1) Inline diff comments (paginated, Codex bot only) ==="
INLINE_JSON=$(gh api --paginate "repos/${REPO}/pulls/${PR}/comments")
INLINE_COUNT=$(jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length' <<<"$INLINE_JSON")
jq -r --arg bot "$BOT" '
  .[] | select(.user.login == $bot)
  | "[\(.commit_id[0:7]) \(.created_at)] \(.path):\(.line)\n  \(.body[0:280] | gsub("[\r\n]+"; " "))\n"
' <<<"$INLINE_JSON"
echo "(total inline Codex findings: ${INLINE_COUNT})"

echo ""
echo "=== 2) Conversation comments (paginated, Codex bot only) ==="
CONV_JSON=$(gh api --paginate "repos/${REPO}/issues/${PR}/comments")
CONV_COUNT=$(jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length' <<<"$CONV_JSON")
jq -r --arg bot "$BOT" '
  .[] | select(.user.login == $bot)
  | "[\(.created_at)]\n  \(.body[0:280] | gsub("[\r\n]+"; " "))\n"
' <<<"$CONV_JSON"
echo "(total conversation Codex comments: ${CONV_COUNT})"

echo ""
echo "=== 3) Top-level reviews (Codex reviewer only) ==="
gh pr view "${PR}" --repo "${REPO}" --json reviews -q '.reviews' \
  | jq -r --arg author "$REVIEWER" '
    .[] | select(.author.login == $author)
    | "[\(.submittedAt)] state=\(.state)\n  \(.body[0:280] | gsub("[\r\n]+"; " "))\n"
  '

echo ""
echo "=== 4) Merge readiness ==="
gh pr view "${PR}" --repo "${REPO}" --json reviewDecision,mergeStateStatus,mergeable

echo ""
echo "=== Summary ==="
TOTAL=$((INLINE_COUNT + CONV_COUNT))
echo "Codex total findings (inline + conversation): ${TOTAL}"
if [ "${TOTAL}" -eq 0 ]; then
  echo "✅ NO Codex findings detected (review 未送信の可能性は polling 側で確認)"
else
  echo "⚠️  ${TOTAL} Codex findings to triage (adopt / reject / defer)"
fi
