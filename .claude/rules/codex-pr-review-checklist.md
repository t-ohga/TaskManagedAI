# Codex PR Review Checklist (2026-05-15 確立、TaskManagedAI 正本)

## 目的

Codex auto-review (chatgpt-codex-connector[bot]) の **inline (file/line specific) finding を見逃さず**、merge 前に全件 adopt / reject / defer 判定するための checklist。CLAUDE.md §6.5.9 の helper 正本。

## 前提

- repo: `t-ohga/TaskManagedAI`
- bot: `chatgpt-codex-connector[bot]`
- review trigger: PR open / draft→ready / `@codex review` コメント
- review timing: push から 1-5 分 (10 file 未満) / 5-10 分 (50+ file)

## 必須確認順序 (PR 起票後 / push 後 / merge 前、全 3 タイミング)

### Step 1: top-level review body (テンプレ + 全体コメント)

```bash
gh pr view <N> --json reviews -q '.reviews[] | {author: .author.login, state, body: (.body[0:300])}'
```

→ 「**指摘なし**」テンプレ + 👍 reaction なら top-level は clean。

### Step 2: **inline review comments (必須、ここを見落としがち)**

```bash
gh api repos/t-ohga/TaskManagedAI/pulls/<N>/comments --jq '.[] | {user: .user.login, path, line, body: (.body[0:400])}'
```

→ inline finding がここに乗る。`gh pr view --json reviews` の body だけでは **絶対に取れない**。

### Step 3: merge readiness

```bash
gh pr view <N> --json reviewDecision,mergeStateStatus,mergeable
```

→ `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE` 確認。

## one-liner helper (push 後すぐ叩く)

```bash
codex_pr_review() {
  local pr=$1
  echo "=== PR #${pr} top-level review ==="
  gh pr view "$pr" --json reviews -q '.reviews[] | "[\(.author.login)] state=\(.state)\n  body: \(.body[0:200])"' 2>/dev/null || echo "(no reviews yet)"
  echo ""
  echo "=== PR #${pr} inline comments ==="
  gh api "repos/t-ohga/TaskManagedAI/pulls/${pr}/comments" --jq '.[] | "[\(.user.login)] \(.path):\(.line)\n  \(.body[0:300])\n"' 2>/dev/null || echo "(no inline comments yet)"
  echo ""
  echo "=== PR #${pr} merge state ==="
  gh pr view "$pr" --json reviewDecision,mergeStateStatus,mergeable
}
```

`~/.zshrc` 等にコピーすれば全 PR で再利用可能。

## Polling (review 未完了時)

push 後すぐは review が来ていない可能性が高いため、bg polling で待つ:

```bash
# 30s × 12 = 6 分 polling、Codex review が来たら break
for i in $(seq 12); do
  sleep 30
  COUNT=$(gh api "repos/t-ohga/TaskManagedAI/pulls/${PR}/comments" --jq 'length')
  STATE=$(gh pr view "$PR" --json reviews -q '.reviews | length')
  echo "[$((i*30))s] inline=$COUNT, reviews=$STATE"
  [[ "$COUNT" -gt 0 || "$STATE" -gt 0 ]] && { codex_pr_review "$PR"; break; }
done
```

## 採否判定 (CLAUDE.md §6.5.9 と同じフロー)

各 inline finding に対して:

| 分類 | 条件 | アクション |
|---|---|---|
| **adopt** | 根拠明確、プロジェクト規約と整合 | merge 前: 同 PR に追加 commit / merge 後: follow-up PR |
| **reject** | Codex の誤認、文脈不整合 | reject reason を PR コメント or commit message に記載 |
| **defer** | 別 Sprint / 別 PR で扱う、ただし adopt 判定は維持 | defer 理由 + 移送先を PR コメントに記載 + memory 記録 |

### Severity (Codex 出力) と risk_to_apply (適用リスク) は独立評価

| Severity | risk_to_apply | 経路 |
|---|---|---|
| P1 / CRITICAL | LOW | 即 fix (自動) |
| P1 / CRITICAL | HIGH | ユーザー承認 + diff/影響/rollback 説明後 fix |
| P2 / MEDIUM | LOW | 自動 fix |
| P2 / MEDIUM | HIGH | adopt 判断 + 自動 fix (security/security 関連は無条件 fix) |
| P3 / LOW | * | backlog or defer |

**security 関連 (runner / approval / secret broker / provider compliance) は severity を 1 段上げて判定する** (P2 → P1 扱い)。

## Post-merge 発覚 fix flow

merged 後に inline finding 発覚した場合:

```bash
git switch main && git pull origin main
git switch -c "fix/pr${ORIGINAL_PR}-codex-${SCOPE}"
# fix 実装 (Codex 委譲 if needed)
git add . && git commit -m "fix(...): Codex PR #${ORIGINAL_PR} R1 findings adopt"
git push -u origin "fix/pr${ORIGINAL_PR}-codex-${SCOPE}"
gh pr create --title "fix(...): PR #${ORIGINAL_PR} Codex findings follow-up" --body "..."
```

PR body に **元 PR # back-reference** + Codex finding 全文引用は必須。

## Common pitfall

| pitfall | 防御 |
|---|---|
| `gh pr view --json reviews` だけ見て clean 判定 | inline 確認も必須 |
| top-level 「指摘なし」テンプレで安心 | inline に P1 finding がいる可能性 |
| push 直後の確認で「まだ来てない」と諦め | 5-10 分 polling で必ず待つ |
| merge 後の発覚を「もう手遅れ」と放置 | follow-up PR 起票が必須経路 |
| Codex 自己の誤認だと決めつけ reject | severity × confidence 両方高い場合は再検証 (本 session の F-PR4-001 のように Claude 設計バグの可能性) |

## 参照

- CLAUDE.md §6.5.9 (本 checklist の caller)
- `.claude/rules/codex-usage-policy.md` (Codex 全般)
- CLAUDE.md §6.5.0 Codex-first ポリシー
- `~/.claude/CLAUDE.md` 「Codex 連携ルール」(全プロジェクト共通)
