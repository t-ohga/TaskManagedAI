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

### Step 2: **inline review (diff) comments (必須、ここを見落としがち)**

```bash
# diff line に紐付く inline finding (Codex の主要 output 経路)
gh api repos/t-ohga/TaskManagedAI/pulls/<N>/comments --jq '.[] | {user: .user.login, path, line, body: (.body[0:400])}'
```

→ inline finding がここに乗る。`gh pr view --json reviews` の body だけでは **絶対に取れない**。

### Step 2b: **PR conversation comments (Codex PR #7 R1 F-PR7-004 P2 adopt、別 endpoint で見落としがち)**

```bash
# PR conversation thread (review に紐付かない一般 comment、Codex 失敗 / 再 review request 等)
gh api repos/t-ohga/TaskManagedAI/issues/<N>/comments --jq '.[] | {user: .user.login, body: (.body[0:400])}'
# 簡易には gh pr view --comments も可 (出力 format は別)
gh pr view <N> --comments
```

GitHub は PR diff comments (`pulls/N/comments`) と PR conversation comments (`issues/N/comments`) を **別 endpoint** で持つ。Codex bot は両方に post し得る。

### Step 3: merge readiness

```bash
gh pr view <N> --json reviewDecision,mergeStateStatus,mergeable
```

→ `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE` 確認。

## one-liner helper (push 後すぐ叩く)

```bash
# Codex PR #7 R1 F-PR7-001 P2 adopt: fail-closed 化。silent suppression は
# 同じ事故 (clean と誤判定) を再生産するため、gh api 失敗時は exit 1 で abort。
codex_pr_review() {
  local pr=$1
  set -e  # fail-closed
  echo "=== PR #${pr} top-level review ==="
  gh pr view "$pr" --json reviews \
    -q '.reviews[] | "[\(.author.login)] state=\(.state)\n  body: \(.body[0:200])"' || {
      echo "ERROR: top-level fetch failed (auth / repo slug / gh missing?)" >&2
      return 1
    }
  echo ""
  echo "=== PR #${pr} inline (diff) comments ==="
  gh api "repos/t-ohga/TaskManagedAI/pulls/${pr}/comments" \
    --jq '.[] | "[\(.user.login)] \(.path):\(.line)\n  \(.body[0:300])\n"' || {
      echo "ERROR: inline fetch failed (DO NOT mark clean!)" >&2
      return 1
    }
  echo ""
  echo "=== PR #${pr} conversation comments ==="
  gh api "repos/t-ohga/TaskManagedAI/issues/${pr}/comments" \
    --jq '.[] | "[\(.user.login)]\n  \(.body[0:300])\n"' || {
      echo "ERROR: conversation fetch failed (DO NOT mark clean!)" >&2
      return 1
    }
  echo ""
  echo "=== PR #${pr} merge state ==="
  gh pr view "$pr" --json reviewDecision,mergeStateStatus,mergeable
}
```

`~/.zshrc` 等にコピーすれば全 PR で再利用可能。**silent suppression (`2>/dev/null || echo "no comments"`) を絶対に使わない** (Codex F-PR7-001 P2)。

## Polling (review 未完了時)

push 後すぐは review が来ていない可能性が高いため、bg polling で待つ。**Codex PR #7 R1 F-PR7-002 P2 adopt: latest push 後の comment を待つ必要があるため、push 時刻 (commit pushedDate / head sha) を baseline にする**:

```bash
# 30s × 12 = 6 分 polling、最新 push 後の Codex review が来たら break。
PR=<N>
# baseline: 最新 push (= 最新 commit) の created_at
LATEST_PUSH_AT=$(gh pr view "$PR" --json commits -q '.commits[-1].authoredDate')
# baseline: 最新 commit sha (commit_id 比較に使う、Codex review の commit_id が新 sha 一致するまで待つ)
LATEST_SHA=$(gh pr view "$PR" --json headRefOid -q '.headRefOid')

for i in $(seq 12); do
  sleep 30
  # 新しい review/comment が来たか
  NEW_INLINE=$(gh api "repos/t-ohga/TaskManagedAI/pulls/${PR}/comments" \
    --jq "[.[] | select(.commit_id == \"${LATEST_SHA}\")] | length")
  NEW_REVIEW=$(gh pr view "$PR" --json reviews \
    -q "[.reviews[] | select(.submittedAt > \"${LATEST_PUSH_AT}\")] | length")
  echo "[$((i*30))s] new_inline_for_${LATEST_SHA:0:7}=${NEW_INLINE}, new_reviews_after_push=${NEW_REVIEW}"
  if [[ "${NEW_INLINE}" -gt 0 || "${NEW_REVIEW}" -gt 0 ]]; then
    codex_pr_review "$PR"
    break
  fi
done
```

古い review/comment で break しないよう、**新 push の commit_id / pushedDate 以降に絞って検索** すること。

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
| P2 / MEDIUM | HIGH | **ユーザー承認必須** (Codex PR #7 R1 F-PR7-003 P2 adopt) |
| P3 / LOW | * | backlog or defer |

**security 関連 (runner / approval / secret broker / provider compliance) は severity を 1 段上げて判定する** (P2 → P1 扱い)。

**Codex PR #7 R1 F-PR7-003 P2 adopt**: P2 / MEDIUM finding でも HIGH risk_to_apply (= auth / DB schema / API contract / runner / secret boundary / 3+ file 横断的変更) の場合、**ユーザー承認必須** (CLAUDE.md §6.5.0 リスク分岐と整合)。medium severity だからと自動 apply してはいけない (migration / contract 破壊 risk あり)。具体的に該当する変更例:

- DB migration (schema 変更、column rename、constraint 追加/削除)
- API contract (request / response schema 変更、削除)
- auth / approval / SecretBroker 4 整合 binding 変更
- runner / sandbox boundary 変更 (forbidden_path / dangerous_command 等)
- 3+ file 横断的なリファクタ
- public interface (public method / export) 変更

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
