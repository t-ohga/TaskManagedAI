# task-02: SP-012-8 — UI 日本語化 (Frontend i18n)

**優先**: P0、**計画必須**: 必須、**self-review**: Plan 1-2 round + Impl 1 round 必須 (§3 Self-Review Protocol)、**想定 effort**: 1-1.5 day

> `codex-all-loops` は Claude 専用 skill (`00-codex-behavior-guide.md` §3.0)。Codex は self-review で同等観点を確保。

## 1. 目的

frontend/app/(admin)/ 配下の全 page (~25 file) と共通 components の **英語 → 日本語化**。Sprint Pack SP-012-8 の must_ship を満たす。

## 2. 起動 protocol

### 2.1 Read order

1. `docs/codex-handoff/2026-05-22-3day-autonomous/README.md`
2. `docs/codex-handoff/2026-05-22-3day-autonomous/00-codex-behavior-guide.md` (全文)
3. `docs/codex-handoff/2026-05-22-3day-autonomous/01-current-state.md`
4. **本 file**
5. `docs/sprints/SP-012-8_ui_i18n.md` (Sprint Pack 本体、なければ task-02 完了時に起票)
6. `.claude/rules/rendering.md` (frontend rendering 規律)
7. `frontend/components/navigation.tsx` (i18n base ファイル)
8. 既存 `frontend/app/(admin)/tickets/*.tsx` (i18n 適用後 pattern として参考)

### 2.2 worktree

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-02-sp012-8-i18n origin/main
cd .claude/worktrees/codex-task-02-sp012-8-i18n
bash scripts/worktree_setup.sh
```

## 3. 計画 phase (必須)

**Self-Plan-Review (§3.1)**:
- target: `docs/sprints/SP-012-8_ui_i18n.md` + 関連 ADR / rules / 過去類似 PR
- Round 1 (構造): 抜け漏れ / 整合性 / 曖昧さ / 依存 / 5+ source enum / cascade pattern リスク
- Round 2 (敵対視点): assumption / race / boundary / security / regression cover
- Readiness Gate: 残存 CRITICAL=0/HIGH≤2 で実装着手可

### 3.1 計画 checklist

- [ ] batch 分割確定 (推奨: batch 1 navigation / batch 2 tickets / batch 3 approvals / batch 4 agent-runs / batch 5 audit / batch 6 settings / batch 7 common UI)
- [ ] 翻訳 glossary 確定 (`tenant_id`, `actor_id`, `role_id`, `payload_data_class` 等 technical term は **untranslated** 維持)
- [ ] accessible-name 維持戦略 (`aria-label` + visible text 両方翻訳、`role="..."` 維持)
- [ ] error message 翻訳範囲 (`backend/app/api/*.py` の HTTPException detail も対象か別 task か確定)
- [ ] toast / snackbar 文言の i18n
- [ ] form validation error 文言の i18n
- [ ] loading / empty state 文言の i18n

## 4. 実装 phase (batch 分割)

### 4.1 batch 1: navigation.tsx

**scope**: `frontend/components/navigation.tsx` (5-10 nav item 日本語化)

**Self-Impl-Review (§3.2)**:
- 実装 target: `frontend/components` (files: `navigation.tsx`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

translation pairs:
- `Tickets` → `チケット`
- `Approvals` → `承認待ち`
- `Agent Runs` → `AI 実行`
- `Audit` → `監査ログ`
- `Settings` → `設定`
- `Eval Dashboard` → `評価ダッシュボード`
- (技術用語は untranslated: `payload_data_class`, `role_id`, `tenant_id` 等)

### 4.2 batch 2: tickets/*.tsx

**scope**: `frontend/app/(admin)/tickets/` 配下全 file (page.tsx + new/page.tsx + [id]/page.tsx + [id]/edit/page.tsx + components)

**Self-Impl-Review (§3.2)**:
- 実装 target: `frontend/app/` (files: `page.tsx,new/page.tsx,[id]/page.tsx,[id]/edit/page.tsx`)
- 実装後 Self-Adversarial-Review 1 round (§3.2 Step 2、invariant 観点全件 check + boundary edge case + regression test)
- Readiness Gate: 残存 CRITICAL=0 で PR 起票可
- local verify (§3.2 Step 4): ruff + mypy + pytest 該当 dir clean

translation pairs:
- `Tickets` → `チケット一覧`
- `Create new ticket` → `新規チケット作成`
- `Title` → `タイトル`
- `Description` → `説明`
- `Status` → `状態`
- `Priority` → `優先度`
- `Created at` → `作成日時`
- `Updated at` → `更新日時`
- form validation: `Title is required` → `タイトルは必須項目です` 等

### 4.3 batch 3-6: approvals / agent-runs / audit / settings

batch 2 と同様の pattern で各 page を翻訳。

### 4.4 batch 7: common UI (loading / error / empty state)

**scope**: `frontend/components/ui/` 配下 + `frontend/app/error.tsx` + `frontend/app/loading.tsx` + `frontend/app/not-found.tsx`

translation pairs:
- `Loading...` → `読み込み中...`
- `Error` → `エラー`
- `Something went wrong` → `エラーが発生しました`
- `Try again` → `再試行`
- `Empty` → `データなし`
- `No data` → `データがありません`

## 5. 検証手順

### 5.1 各 batch 完了時

```bash
cd frontend
pnpm typecheck  # type 不変
pnpm lint       # eslint clean
pnpm vitest run # 既存 70+ test PASS (i18n 後の文言は test 側も update 必要)
```

### 5.2 accessible-name 確認 (batch 完了時)

```bash
# vitest 内で role / aria-label / accessible name を verify
# 例: expect(screen.getByRole('button', { name: '新規チケット作成' })).toBeInTheDocument()
```

`testing.md` §3 弱い assertion 禁止: `toBeDefined()` ではなく `toBeInTheDocument()` / `toBeVisible()` を使う。

## 6. PR 起票 + admin bypass merge

```bash
git push -u origin feat/sp012-8-batch-1-navigation-japanese-2026-05-23
gh pr create --base main --head feat/sp012-8-batch-1-navigation-japanese-2026-05-23 \
  --title "feat(sp012-8-batch-1): navigation 日本語化" \
  --body "$(cat <<'EOF'
## Summary
SP-012-8 batch 1: navigation.tsx の日本語化 + accessible-name 維持

## verification
- pnpm typecheck: clean
- pnpm lint: clean
- pnpm vitest run: N PASS / 0 FAIL (test 側文言 update 含む)

## invariant 遵守
- accessible-name: ✅ aria-label + visible text 両方翻訳
- 技術用語 untranslated: ✅ payload_data_class / role_id / tenant_id 等は英語維持
- a11y role 維持: ✅

## ADR Gate
非該当 (UI 文言変更、Criteria 11 種いずれも非該当)
EOF
)"
```

## 7. Codex auto-review baseline (必須)

```bash
sleep 60
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -200
```

## 8. DoD checklist

- [ ] batch 1-7 全件実装完了 (~25 frontend file)
- [ ] 技術用語 untranslated (glossary 参照)
- [ ] accessible-name 維持 (aria-label + visible text 両方翻訳)
- [ ] toast / snackbar / form validation / loading / empty state 全件翻訳
- [ ] pnpm typecheck + lint + vitest 全件 clean
- [ ] Sprint Pack SP-012-8 frontmatter `status: ready → completed` + Review 章追加 (なければ起票)
- [ ] 完了報告 `completion/task-02-completed.md` 起票

## 9. blocker / 緊急停止

- 既存 a11y test の文言依存 で大量 regression → batch 分割を細かくして段階 fix
- accessible-name 維持と visible text 翻訳の整合性問題 → AskUserQuestion (本 handoff scope では Codex 自律判断、ambigous なら STOPPED.md)

## 10. 関連参照

- `frontend/components/navigation.tsx` (本 task の i18n base)
- `.claude/rules/rendering.md` (a11y / role / accessible-name)
- `.claude/rules/testing.md` §5 (Vitest 弱い assertion 禁止)
- 過去類似 batch: PR #122-#127 (tickets page 実装、i18n 適用前 pattern)
