---
title: SP022-T09 prep — Mac single-host smoke verification plan
type: light
status: ready
sprint: SP-022
related_tickets:
  - SP022-T09 (実機 host migration drill、本 plan は drill 前提条件確立)
  - SP022-T08 batch 5 (signed journal CLI DB mode、PR #90 merged)
  - SP022-T08 batch 6 (frontend backend wiring、PR #91 merged)
  - SP022-T06 (Mac KPI baseline、PR #89 merged)
related_adrs:
  - ADR-00021 (host-portable deployment、本 plan は drill 前提)
  - ADR-00020 (framework intake checklist)
created_at: "2026-05-22"
target_days: 0.5
max_days: 1
adr_gate: none  # ADR Gate Criteria 11 種いずれにも非該当 (single-host smoke verification)
---

# SP022-T09 prep — Mac single-host smoke verification plan

## 1. 背景 + 目的

### 背景

SP-012 must_ship + SP-022 T00-T07 + T08 batch 1-6 + T06 Mac KPI = 全て code-level / individual test-level で完了 (累計 59 Codex rounds / 238 findings 100% adopt、23 PR merged)。

しかし **GitHub Actions CI billing-blocked により直近 20 runs 連続 failure** = main 上の全体 regression / docker compose smoke / e2e は CI で一度も走っていない。各 PR は admin bypass (`gh api -X PUT pulls/N/merge`) で merge。

つまり「Mac single-host で TaskManagedAI が **実際に** 動く」立証が **未完了**。T09 host migration drill (Mac→VPS) の前に Mac single-host の動作実証が必要。

### 目的

T09 host migration drill 実施前に **Mac single-host で P0 TaskManagedAI が動作する** ことを 3 layer で立証する:

- **Layer A** (autonomous、worktree 内): main 上の全 static check + regression PASS
- **Layer B** (Mac 実機、user): docker compose stack が clean に動く
- **Layer C** (Mac 実機、user、ブラウザ + CLI): P0 機能 + CLI smoke + golden flow

Layer A は本 session 内で私が完遂、Layer B/C は手順書を整備して user が実機実施可能な状態にする。

## 2. 対象外

- T09 host migration drill 本体 (本 plan の後続作業、`docs/deploy/half-yearly-drill-sop.md` §11 + 本 session 内提示済の手順)
- Linux/VPS KPI baseline (物理 host 取得待ち、SP022-T06 carry-over)
- Private staging E2E full activation (admin Tailscale OAuth setup 待ち)
- production deploy (P3+ SP-023 以降の scope)
- ADR-00021 / ADR-00007 frontmatter `status: proposed → accepted` 昇格 (T09 drill PASS 後に実施)
- P0 Exit declaration (Hard Gates 7 / KPIs 5 全件 PASS + T09 drill PASS + ADR accepted 完了後)

## 3. 設計判断

1. **3 layer 分離**: autonomous で立証可能な静的検証 (Layer A) と、Mac 実機で必要な動的検証 (Layer B/C) を明示分離。layer 間 dependency は順次 (A → B → C → T09 drill)。
2. **Layer A 即実施**: 本 session 内で私 (Claude) が worktree 内で実行可能、結果を evidence file に永続化。
3. **Layer B/C 手順書化**: user 実機で実施するため、commands + expected outcome + failure escalation を含む detailed SOP を新規 `docs/deploy/mac-single-host-smoke-sop.md` に追加。
4. **既存資産活用**: ci-smoke.yml の job design (backend-quality / frontend-quality / docker-smoke / frontend-e2e) を SOP の checklist 構造として踏襲、CI billing 解消後の自動化 path を残す。
5. **品質担保**: Layer A は失敗 1 件でも明示記録 (TaskManagedAI rules `testing.md §13` 完了条件遵守)、Layer B/C は user が実施結果を fact-based で記録できる template を提供。

## 4. 実装チケット

### Layer A (autonomous、本 session): 私が実施

| # | task | command | expected | log file |
|---|---|---|---|---|
| A-1 | dependency install verify | `uv sync && cd frontend && pnpm install --frozen-lockfile` | exit 0、lockfile drift なし | `.claude/local/smoke-evidence/A-1-deps.log` |
| A-2 | backend full pytest | `uv run pytest -x 2>&1 \| tee evidence` | 全 test PASS、exit 0 | `.claude/local/smoke-evidence/A-2-pytest.log` |
| A-3 | backend ruff + mypy | `uv run ruff check backend tests && uv run mypy backend` | 0 error、0 warning | `.claude/local/smoke-evidence/A-3-lint.log` |
| A-4 | frontend full vitest | `cd frontend && pnpm vitest run` | 53+ tests PASS | `.claude/local/smoke-evidence/A-4-vitest.log` |
| A-5 | frontend typecheck + eslint | `cd frontend && pnpm typecheck && pnpm exec eslint . --max-warnings=0` | 0 error | `.claude/local/smoke-evidence/A-5-fe-static.log` |
| A-6 | alembic check + upgrade head | test DB に対して `uv run alembic check && uv run alembic upgrade head` | exit 0、全 migration apply 成功 | `.claude/local/smoke-evidence/A-6-alembic.log` |
| A-7 | **frontend production build (typed routes verify、p0-exit-final-hardening 2026-05-22 追加)** | `cd frontend && pnpm build` | exit 0、`.next/types/` 生成 + Next.js typed routes strict check PASS (initial PR #93 で見逃された latent bug 防止) | `.claude/local/smoke-evidence/A-7-build.log` |

**A-7 追加の経緯** (p0-exit-final-hardening-2026-05-22 plan §3.1 + Layer A 強化):

- `pnpm typecheck` (= `tsc --noEmit`) は Next.js `experimental.typedRoutes` (`frontend/next.config.ts`) が生成する `.next/types/` declaration を import するが、未生成だと strict check が走らない (false positive)
- 結果として PR #93 までは A-5 PASS でも実際の Docker build で typed routes type error が発覚するリスクが残っていた
- A-7 (`pnpm build`) を追加することで `.next/types/` 生成 + typed routes union strict check + production build error catch を Layer A で完結

各 task の evidence を `.claude/local/smoke-evidence/<task-id>.log` に保存 (commit には含めず、`A-summary.md` に結果サマリのみ含める)。

### Layer B (Mac 実機、user 実施): 手順書整備

`docs/deploy/mac-single-host-smoke-sop.md` §2 (Layer B) として追加。内容:

- B-1: `.env.local` 設定 (TASKMANAGEDAI_ENVIRONMENT=development 等)
- B-2: `docker compose --env-file .env.local build`
- B-3: `docker compose up -d` + 5 service healthy 待機
- B-4: `/healthz` 応答確認 (api / frontend)
- B-5: alembic head が migrate 適用済確認

### Layer C (Mac 実機、user 実施、ブラウザ + CLI): 手順書整備

`docs/deploy/mac-single-host-smoke-sop.md` §3 (Layer C) として追加。内容:

- C-1: dev login flow (browser、cookie set)
- C-2: Eval Dashboard 実表示 (`/eval-dashboard`、live KPI rollup backend 経由、route group `(admin)` は URL prefix に含まれない)
- C-3: Ticket 一覧 / 詳細
- C-4: Approval Inbox (approve / reject)
- C-5: Agent Runs 一覧 (16 状態表示)
- C-6: Audit Log (raw secret 漏れ無し)
- C-7: taskhub approval issue smoke
- C-8: signed journal verify CLI (`--from-db`)
- C-9: taskhub backup real smoke (small DB)
- C-10: golden flow Ticket→PR smoke (BL-0140a 12 step)

## 5. タスク一覧

- [ ] Layer A 全 6 件 実施 (autonomous、本 session)
- [ ] Layer B 手順書 SOP 整備 (user 実機手順、所要 30-60 min 想定)
- [ ] Layer C 手順書 SOP 整備 (機能 smoke、所要 30-90 min 想定)
- [ ] memory persist (`feedback_taskmanagedai_autonomous_full_drive.md` + `project_session_2026_05_22_p0_exit_ready_handoff.md`)
- [ ] PR 起票 + Codex review + admin merge

## 6. must_ship / defer_if_over_budget

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| Layer A 6 件全 PASS | ✅ | (個別失敗時は明示記録 + 修正 PR、本 plan は autonomous 完遂前提) |
| Layer B SOP 整備 (5 step) | ✅ | - |
| Layer C SOP 整備 (10 step) | ✅ | golden flow C-10 詳細は BL-0140a smoke として既存 docs 参照 link で代替可 |
| memory persist | ✅ | - |
| PR 起票 + Codex review | ✅ | - |

## 7. 受け入れ条件

- [ ] Layer A 全 6 件 PASS (失敗時は明示記録)
- [ ] `docs/deploy/mac-single-host-smoke-sop.md` 新規作成、Layer B + C 全 step 含む
- [ ] `.claude/plans/sp022-t09-prep-mac-smoke.md` (本 plan) merged
- [ ] memory file に Layer A 結果 + Layer B/C user 残作業 + T09 drill 手順が persist
- [ ] PR で Codex R1+ CLEAN signal 達成
- [ ] CRITICAL=0 (本 plan は ADR Gate Criteria 非該当のため lint-only check)

## 8. 検証手順

1. Layer A 6 件を順次実行、各結果を evidence file に save
2. 全 PASS で `A-summary.md` 作成
3. `docs/deploy/mac-single-host-smoke-sop.md` を整備
4. PR 起票 (`docs(sp022-t09-prep): Mac single-host smoke SOP + Layer A evidence`)
5. Codex `@codex review` trigger
6. R1 CLEAN signal で admin merge
7. memory update + 本 session 完遂

## 9. レビュー観点

- Layer A 各 evidence が `\d+ passed` を含み verifiable か
- Layer B 手順書が user が読んで実行可能 (各 step に expected outcome + failure escalation)
- Layer C 手順書が 7 mandatory checklist 形式で fact-based 記録可能
- 残作業 list (T09 drill / ADR accepted / P0 Exit) が memory に明示記録
- ADR Gate Criteria 11 種への該当なし confirmation

## 10. 残リスク

- Layer A 失敗時の対処 = autonomous で修正 PR 起票 (CLAUDE.md §14.1 mandatory Codex gates 経由)
- Layer B/C user 実機実施は本 plan scope 外 = user の手動 work
- T09 drill 本体 (Mac→VPS host migration) は本 plan の後続 user work
- CI billing 解消は admin-only、本 plan scope 外

## 11. 次スプリント候補

T09 drill PASS 後の作業 (post-本 plan):

1. SP022-T09 retro Pack 作成 (`docs/sprints/SP-022_framework_intake_hardening.md` `## Review` 追加)
2. ADR-00021 + ADR-00007 frontmatter `status: proposed → accepted` 昇格
3. SP-012 + SP-022 frontmatter `status: → completed`
4. P0 Exit declaration PR (master plan §10-§11 P0.1 unblock + Hard Gates / KPIs evidence link)
5. `TASKHUB_P0_1_OPENED=1` 解禁 + sealed CI guard 解除
6. SP-013 multi-agent orchestration 着手

## 12. 関連 ADR

- ADR-00021 host-portable deployment (本 plan は T09 drill 前 prerequisite)
- ADR-00020 framework intake checklist (SP022-T01 で機械化済)
- ADR Gate Criteria 11 種いずれにも該当なし (single-host smoke verification、ADR 不要)

## Review

(本 plan 実施完了時に追記)
