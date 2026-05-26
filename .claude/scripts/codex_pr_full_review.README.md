# Codex PR Review Checklist (2026-05-15 確立、TaskManagedAI 正本)

## 目的

Codex auto-review (chatgpt-codex-connector[bot]) の **inline (file/line specific) finding を見逃さず**、merge 前に全件 adopt / reject / defer 判定するための checklist。CLAUDE.md §6.5.9 の helper 正本。

## 🔴 MANDATORY: 必ず `.claude/scripts/codex_pr_full_review.sh` を使う

**2026-05-15 self-violation 事故** ([[feedback_codex_review_must_use_full_helper]]) の再発防止として、本 checklist の **shell helper 部分は手書きで実行しない**。必ず以下を実行:

```bash
.claude/scripts/codex_pr_full_review.sh <PR>
```

helper 内部は本 checklist の Step 1〜4 を **paginated + Codex bot filter + 全 commit 横断** で実行する。

### なぜ helper 必須か (失敗パターン 5 件)

| 失敗 | 教訓 |
|---|---|
| `inline_for_head` filter のみ追跡 (commit_id match) | line tracking で過去 commit に残る finding 取りこぼし。**commit_id filter は禁止** |
| `pulls/N/comments` (inline) のみ確認 | conversation comments を見落とし。**両 endpoint mandatory** |
| polling timeout 4-5 分で「真の 0 件」判定 | Codex は 6-10 分後にも new finding 出す。**polling は最低 10 分** (Codex F-PR7-014 P3 adopt) |
| pagination 未対応 (gh api default 30 件) | 30 件超で truncate。**`gh api --paginate` 必須** (Codex F-PR7-011 P2 adopt) |
| Codex bot filter なし | 人間 / 私自身の `@codex review` comment と Codex review を混同して誤判定。**`user.login == "chatgpt-codex-connector[bot]"` で filter 必須** (Codex F-PR7-012 P2 adopt) |

## 前提

- repo: `t-ohga/TaskManagedAI`
- bot: `chatgpt-codex-connector[bot]`
- review trigger: PR open / push / draft→ready (自動)。`@codex review` コメントは手動トリガーとして使えるが、通常は不要 (自動で走るため)
- review timing: push から 1-5 分 (10 file 未満) / 5-10 分 (50+ file)

## 必須確認順序 (PR 起票後 / push 後 / merge 前、全 3 タイミング)

### Step 1: top-level review body (テンプレ + 全体コメント)

```bash
gh pr view <N> --json reviews -q '.reviews[] | {author: .author.login, state, body: (.body[0:300])}'
```

→ 「**指摘なし**」テンプレ + 👍 reaction なら top-level は clean。

### Step 2: **inline review (diff) comments (必須)**

```bash
# diff line に紐付く inline finding (Codex の主要 output 経路)
gh api repos/t-ohga/TaskManagedAI/pulls/<N>/comments --jq '.[] | {user: .user.login, path, line, body: (.body[0:400])}'
```

→ inline finding がここに乗る。`gh pr view --json reviews` の body だけでは **絶対に取れない**。

### Step 3: **PR conversation comments (必須、Codex PR #7 R3 F-PR7-004〜006 P2 adopt)**

```bash
# PR conversation thread (review に紐付かない PR 全体 comment、Codex 失敗報告 / 再 review request / 一般 finding)
gh api repos/t-ohga/TaskManagedAI/issues/<N>/comments --jq '.[] | {user: .user.login, body: (.body[0:400])}'
```

GitHub は PR diff comments (`pulls/N/comments`) と PR conversation comments (`issues/N/comments`) を **別 endpoint** で持ち、Codex bot は両方に post する可能性がある。**両方 mandatory** で確認。`gh pr view <N> --comments` でも閲覧できるが、必ず両 endpoint を fetch するのが正本。

### Step 4: merge readiness

```bash
gh pr view <N> --json reviewDecision,mergeStateStatus,mergeable
```

→ `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE` 確認。

## one-liner helper (簡易版、push 後すぐ叩く)

**注意**: 本 helper は **`.claude/scripts/codex_pr_full_review.sh`** に統合済み (mandatory verify path)。以下は実装参考のみ。

```bash
# Codex PR #7 R1 F-PR7-001 P2 adopt: fail-closed 化。silent suppression は
# 同じ事故 (clean と誤判定) を再生産するため、gh api 失敗時は return 1 で abort。
# Codex PR #7 R3 F-PR7-009 P3 adopt: subshell `( set -e ... )` で実行し、
# caller の shell option (errexit / nounset 等) を leak しない。
codex_pr_review() {
  ( set -e -o pipefail
    local pr=$1
    [ -n "$pr" ] || { echo "usage: codex_pr_review <PR-number>" >&2; exit 2; }

    echo "=== PR #${pr} top-level review ==="
    gh pr view "$pr" --json reviews \
      -q '.reviews[] | "[\(.author.login)] state=\(.state)\n  body: \(.body[0:200])"' || {
        echo "ERROR: top-level fetch failed (auth / repo slug / gh missing?)" >&2
        exit 1
      }
    echo ""
    echo "=== PR #${pr} inline (diff) comments ==="
    gh api "repos/t-ohga/TaskManagedAI/pulls/${pr}/comments" \
      --jq '.[] | "[\(.user.login)] \(.path):\(.line)\n  \(.body[0:300])\n"' || {
        echo "ERROR: inline fetch failed (DO NOT mark clean!)" >&2
        exit 1
      }
    echo ""
    echo "=== PR #${pr} conversation comments ==="
    gh api "repos/t-ohga/TaskManagedAI/issues/${pr}/comments" \
      --jq '.[] | "[\(.user.login)]\n  \(.body[0:300])\n"' || {
        echo "ERROR: conversation fetch failed (DO NOT mark clean!)" >&2
        exit 1
      }
    echo ""
    echo "=== PR #${pr} merge state ==="
    gh pr view "$pr" --json reviewDecision,mergeStateStatus,mergeable
  )
}
```

`~/.zshrc` 等にコピーすれば全 PR で再利用可能。**silent suppression (`2>/dev/null || echo "no comments"`) を絶対に使わない** (Codex F-PR7-001 P2)。**`set -e` は subshell `( ... )` 内に閉じ込め、caller shell の errexit を leak しない** (Codex F-PR7-009 P3)。

## Polling (review 未完了時) — 最低 **10 分** (Codex F-PR7-014 P3 adopt)

push 後すぐは review が来ていない可能性が高いため、bg polling で待つ。**最低 10 分**、大 PR (50+ file) は **20 分**。Codex は 6-10 分後にも new finding を出すため、4-5 分の polling は早すぎる (2026-05-15 self-violation の根本原因 1)。

**Codex PR #7 R1 F-PR7-002 + R3 F-PR7-007/008/010 + R4 F-PR7-011/012/013/014 P2/P3 adopt: latest push 後 (= latest commit) の review/comment を待ち、未完了なら timeout で fail-closed**。**Codex bot のみ filter**、**pagination 必須**、**top-level review は commit match 必須**。

baseline は **`headRefOid` (latest commit SHA)** を使う。`authoredDate` は commit author timestamp で push 時刻ではない (GraphQL に `pushedDate` フィールドはないため、push 時刻は直接取得不能)。**新 commit に紐付く review/comment があるか** で判定する方が信頼性高い。

```bash
PR=<N>
BOT='chatgpt-codex-connector[bot]'
REPO=t-ohga/TaskManagedAI
LATEST_SHA=$(gh pr view "$PR" --json headRefOid -q '.headRefOid')
# トリガー前の Codex finding 数 baseline (inline + conv、Codex bot のみ filter)
# Codex PR #7 R5 F-PR7-017 P2 adopt: --paginate は GH CLI version で multi-document
# emit するため `jq -s 'flatten'` で全 page を flat array に統合 (slurp)。
PRE_INLINE=$(gh api --paginate "repos/$REPO/pulls/$PR/comments" \
  | jq -s 'flatten' \
  | jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length')
PRE_CONV=$(gh api --paginate "repos/$REPO/issues/$PR/comments" \
  | jq -s 'flatten' \
  | jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length')
# Codex PR #7 R5 F-PR7-016 P2 adopt: baseline と loop の比較対象を **同じ scope** に
# 揃える。両方とも HEAD commit 限定 (`commit_id == LATEST_SHA`) で count する
# (history 全 review count を baseline にすると、new head review が 1 件来ても
# delta が負になり false negative)。
# Codex F-PR7-019 P2 adopt: commit_id / commit.oid 両 field name に対応
PRE_REVIEW_FOR_HEAD=$(gh pr view "$PR" --json reviews \
  -q "[.reviews[] | select((.author.login | startswith(\"chatgpt-codex-connector\")) and ((.commit_id // .commit.oid) == \"$LATEST_SHA\"))] | length")

# Codex F-PR7-014 P3 adopt: 最低 10 分 (大 PR は 20 分推奨)。
# 6 min は短すぎる、Codex は 6-10 min 後にも new finding 出す。
for i in $(seq 20); do
  sleep 30
  # 全 inline (paginated, Codex bot only)
  CUR_INLINE=$(gh api --paginate "repos/$REPO/pulls/$PR/comments" \
    | jq -s 'flatten' \
    | jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length')
  CUR_CONV=$(gh api --paginate "repos/$REPO/issues/$PR/comments" \
    | jq -s 'flatten' \
    | jq --arg bot "$BOT" '[.[] | select(.user.login == $bot)] | length')
  # Codex F-PR7-013/016 P2 adopt: top-level review は head commit match、baseline も同じ scope
  # Codex PR #7 R5 F-PR7-019 P2 adopt: `gh pr view --json reviews` の commit 識別子は
  # version によって `.commit_id` または `.commit.oid` のどちらか。両方 fallback で確認。
  CUR_REVIEW_FOR_HEAD=$(gh pr view "$PR" --json reviews \
    -q "[.reviews[] | select((.author.login | startswith(\"chatgpt-codex-connector\")) and ((.commit_id // .commit.oid) == \"$LATEST_SHA\"))] | length")
  DELTA_INLINE=$((CUR_INLINE - PRE_INLINE))
  DELTA_CONV=$((CUR_CONV - PRE_CONV))
  DELTA_REVIEW=$((CUR_REVIEW_FOR_HEAD - PRE_REVIEW_FOR_HEAD))
  echo "[$((i*30))s] codex inline=+$DELTA_INLINE conv=+$DELTA_CONV review_for_head=+$DELTA_REVIEW"
  if [[ "$DELTA_INLINE" -gt 0 || "$DELTA_CONV" -gt 0 || "$DELTA_REVIEW" -gt 0 ]]; then
    .claude/scripts/codex_pr_full_review.sh "$PR"
    exit 0
  fi
done
# Codex F-PR7-010 + R5 F-PR7-020 P2 adopt: fail-closed + reaction-only clean 注意
# Codex は新 comment / review を出さず **👍 reaction** だけで「no major issues」を示す
# こともある (Codex GitHub integration の clean case)。本 polling は reaction を
# poll しないため、10 min 経過で finding が出なかった場合は **明示的に user 確認**
# を要する (silent clean 判定禁止)。
echo "WARNING: PR #${PR} no new Codex inline/conv/review for ${LATEST_SHA:0:7} after 10 min." >&2
echo "         → Codex が reaction-only clean (👍) で完了した可能性 (`gh api repos/.../reactions`)、" >&2
echo "           または review 未送信。**clean と自動判定せず**、user 確認後に proceed。" >&2
exit 1
```

**baseline は `headRefOid` (commit SHA) + Codex bot filter で判定**。`authoredDate` は rebase / amend で同じ commit が再 push される場合に不一致になるため secondary。`commit_id == LATEST_SHA` filter が最も信頼性高い (Codex F-PR7-007 P2)。

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
