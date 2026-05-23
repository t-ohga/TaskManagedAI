#!/usr/bin/env bash
# codex_pr_full_review.sh — Codex の全 finding を必ず取得する verify helper
#
# 使用必須タイミング (CLAUDE.md §6.5.9 + .claude/scripts/codex_pr_full_review.README.md):
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
CODEX_CLEAN_COMMENT_PATTERN="Didn't find any major issues"

echo "==================================================================="
echo "PR #${PR} — Codex full review check (ALL endpoints, paginated)"
echo "==================================================================="

echo ""
echo "=== 1) Inline diff comments (paginated + slurped, Codex bot only) ==="
# Codex PR #7 R5 F-PR7-017 P2 adopt: `gh api --paginate` は GH CLI version に
# よっては各 page を別 JSON document として emit する。`jq -s 'flatten'` で
# 確実に全 page を flat array に統合し、複数 page (30 件超 comment) でも
# 正しく count する。
INLINE_JSON=$(gh api --paginate "repos/${REPO}/pulls/${PR}/comments" | jq -s 'flatten')
INLINE_COUNT=$(jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length' <<<"$INLINE_JSON")
jq -r --arg bot "$BOT" '
  .[] | select(.user.login == $bot)
  | "[\(.commit_id[0:7]) \(.created_at)] \(.path):\(.line)\n  \(.body | gsub("[\r\n]+"; " "))\n"
' <<<"$INLINE_JSON"
echo "(total inline Codex findings: ${INLINE_COUNT})"

echo ""
echo "=== 2) Conversation comments (paginated + slurped, Codex bot only) ==="
CONV_JSON=$(gh api --paginate "repos/${REPO}/issues/${PR}/comments" | jq -s 'flatten')
CONV_ACTIONABLE_JSON=$(jq --arg bot "$BOT" --arg clean "$CODEX_CLEAN_COMMENT_PATTERN" '
  [.[] | select(.user.login == $bot) | select(((.body // "") | contains($clean)) | not)]
' <<<"$CONV_JSON")
CONV_INFO_COUNT=$(jq --arg bot "$BOT" --arg clean "$CODEX_CLEAN_COMMENT_PATTERN" '
  [.[] | select(.user.login == $bot) | select((.body // "") | contains($clean))] | length
' <<<"$CONV_JSON")
CONV_COUNT=$(jq 'length' <<<"$CONV_ACTIONABLE_JSON")
jq -r --arg bot "$BOT" '
  .[] | select(.user.login == $bot)
  | "[\(.created_at)]\n  \(.body | gsub("[\r\n]+"; " "))\n"
' <<<"$CONV_ACTIONABLE_JSON"
echo "(total actionable conversation Codex comments: ${CONV_COUNT})"
echo "(ignored informational clean Codex comments: ${CONV_INFO_COUNT})"

echo ""
echo "=== 3) Top-level reviews (Codex reviewer only) ==="
gh pr view "${PR}" --repo "${REPO}" --json reviews -q '.reviews' \
  | jq -r --arg author "$REVIEWER" '
    .[] | select(.author.login == $author or .author.login == ($author + "[bot]"))
    | "[\(.submittedAt)] state=\(.state)\n  \(.body | gsub("[\r\n]+"; " "))\n"
  '

echo ""
echo "=== 4) Merge readiness ==="
gh pr view "${PR}" --repo "${REPO}" --json reviewDecision,mergeStateStatus,mergeable

# Codex PR #7 R5 F-PR7-021 P2 adopt: top-level Codex review も TOTAL に含める
# (Codex が inline / conv なしで top-level review body にのみ書く scenario の検出)
REVIEW_COUNT=$(gh pr view "${PR}" --repo "${REPO}" --json reviews -q '.reviews' \
  | jq --arg author "$REVIEWER" --arg clean "$CODEX_CLEAN_COMMENT_PATTERN" '
    [
      .[]
      | select(.author.login == $author or .author.login == ($author + "[bot]"))
      | select(((.body // "") | contains($clean)) | not)
    ] | length
  ')

echo ""
echo "=== Summary ==="
TOTAL=$((INLINE_COUNT + CONV_COUNT + REVIEW_COUNT))
echo "Codex total findings (inline + conversation + top-level review): ${TOTAL} (i=${INLINE_COUNT} c=${CONV_COUNT} r=${REVIEW_COUNT})"
if [ "${TOTAL}" -eq 0 ]; then
  echo "✅ NO Codex findings detected (review 未送信の可能性は polling 側で確認)"
else
  echo "⚠️  ${TOTAL} Codex findings to triage (adopt / reject / defer)"
fi
