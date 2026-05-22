---
id: "p0-exit-final-hardening-2026-05-22"
type: "master-plan-supplement"
status: "ready"
created_at: "2026-05-22"
updated_at: "2026-05-22"
readiness_gate:
  verdict: "READY"
  codex_plan_review_rounds: 3
  codex_findings: 19  # R1: 17 + R2: 2 + R3: 0 (CLEAN)
  plan_reviewer_rounds: 2
  plan_reviewer_findings: 7  # R1: 7 (BLOCK 1 + WARN 3 + INFO 3) + R2: 0 (CLEAN)
  total_findings: 26
  adopted: 26  # 100% adopt
  rejected: 0
  deferred: 0
  critical_remaining: 0
  high_remaining: 0
  block_remaining: 0
  warn_remaining: 0
  codex_adversarial_loop_status: "optional_skip"  # CRITICAL=0+HIGH=0 既達のため
  ledger_path: "~/.claude/local/codex-reviews/2026-05-22/sprint-SP-012-batch-7-taskhub-admin-cli/plan-review-ledger.md"
target_days: 2
max_days: 4
related_master_plan: "docs/設計検討/2026-05-13_p0_exit_master_plan.md"
related_sprints:
  - "SP-012_p0_acceptance (partial_completed_with_carry_over)"
  - "SP-022_framework_intake_hardening (draft、本 plan で must_ship 完遂導線)"
related_adrs:
  - "ADR-00021 (accepted at SP022-T00 2026-05-19、host migration drill PASS 待ち)"
  - "ADR-00007 (accepted at SP022-T00 2026-05-19、Tailscale 閉域 invariant)"
  - "ADR-00020 (accepted at SP022-T00 2026-05-19、framework intake checklist)"
  - "ADR-00022 (accepted、dev login cookie secure attribute)"
adr_gate_review:
  - "本 plan の修正対象は routing inconsistency fix (URL convention 修正) + typed routes verify gap fix (build 経路追加) + actions.ts Route 型 cast (型 annotation only)。いずれも ADR Gate Criteria 11 種非該当 (認証・認可 logic 不変 / DB schema 不変 / API 契約不変 / 破壊的操作なし / 広範囲 refactor は単一意図の URL convention 修正のみ)"
session_context:
  - "2026-05-22 後半 session で SP022-T09 prep Mac single-host smoke verification 実施中に発覚"
  - "Layer A typecheck PASS は false positive (tsc --noEmit は Next.js typed routes build-time check を見ない)"
  - "Docker compose build (Layer B §2) で typed routes 不整合 2 件発覚 = actions.ts Route 型 cast 漏れ + navigation.tsx 3-way routing inconsistency"
must_ship:
  - "本 plan の Codex review loop READY 達成 (CRITICAL=0 + HIGH≤2)"
  - "routing fix PR 起票 → Codex multi-round adopt → merge"
  - "Layer A 強化 (Next.js build を verify 経路に追加)"
  - "Layer B smoke (Claude autonomous で実行可能箇所)"
  - "Layer C smoke の autonomous 可能箇所"
defer_if_over_budget:
  - "SOP UI 操作箇所 (§6 dev login / §8-§11 ブラウザ UI smoke) は user 必須なので本 plan の autonomous scope 外"
  - "T09 host migration drill は user 物理作業必須、本 plan は drill 着手前提条件の整備に集中"
---

# P0 Exit Final Hardening Plan (2026-05-22 起票)

## 0. Executive Summary

P0 Exit declaration までの残作業を **これまでの作業 (PR #75-#93、累計 59 rounds / 238 findings 100% adopt) を 100% 活用** + **本 session で発覚した routing inconsistency 系 latent issues を統合した改善として取り込み** + **Codex review loop で完璧化** する統合計画。

`docs/設計検討/2026-05-13_p0_exit_master_plan.md` (P0 Exit Master Plan 本体) §10-§11 で定義された **SP-022 must_ship 全件完了 → P0 Exit declaration → P0.1 unblock** path に対し、本 plan は **2026-05-22 後半 session で新たに発覚した latent issues を SP-022 must_ship に追加統合** する supplement plan として位置付ける。

新規追加 must_ship (本 plan で取り込み):
1. **routing 3-way inconsistency fix** (navigation.tsx href + smoke SOP URL + 実 app/ 配置の整合化、source of truth = 実 app/ 配置)
2. **actions.ts Route 型 cast** (Next.js typed routes build-time check 通過、latent build bug fix)
3. **Layer A verify 経路強化** (`pnpm typecheck` のみでは Next.js typed routes を catch しないため、`next build` または `.next/types/` 生成 + tsc を統合)
4. **smoke SOP の URL 修正** (`/admin/*` prefix 誤記を `/eval-dashboard`, `/tickets` 等の実 route に修正)

これらは **小規模 (4-5 file / 100-200 行) かつ ADR Gate 非該当** だが、**Layer B/C smoke 成立条件 + T09 drill UI 動作確認の前提条件** であり、SP-022 T09 unblock 直接 gate に組み込む必要がある。

期待効果:
- Layer B smoke 完遂可能 (Docker build success)
- Layer C UI smoke の正しい URL での動作確認可能
- T09 drill 前提条件 100% 整備
- post-P0.1 で同種 latent build bug 再発防止 (Layer A verify 強化)

## 1. 現状 (2026-05-22 後半 session 時点)

### 1.1 完了済 (これまでの作業、無駄にしない base)

| Sprint / Phase | 状態 | 証跡 |
|---|---|---|
| SP-010 Research/Evidence | completed | PR #19/21/22/24/26/27 |
| SP-011 Eval Harness | completed | PR #38/#39 |
| SP-011.5 Operational Hardening | completed | PR #40-#54 系列 |
| SP-012 P0 Acceptance (skeleton) | partial_completed_with_carry_over | PR #59-#67 (9 PR、skeleton 完了) |
| SP-012 must_ship | completed | PR #76-#88 (47 rounds / 212 findings 100% adopt) |
| SP-022 T00 pre-implementation gate | completed | PR #69 (3 ADR accepted 化) |
| SP-022 T01-T07 | completed | PR #70-#80 (CI / migrate / drill SOP / Phase E audit / KPI / production checklist / Phase G) |
| SP-022 T06 Mac KPI baseline | completed | PR #89 (R1-R2 CLEAN、4 findings adopt) |
| SP-022 T08 batch 1-6 | completed | PR #76,77,78,79,90,91 (累計 26 findings adopt) |
| SP-022 Sprint Pack Review update | completed | PR #92 (docs-only) |
| SP022-T09 prep Mac smoke Layer A + B/C SOP | partial | PR #93 merged (Layer A PASS 報告 + SOP 整備、ただし本 plan §1.3 で false positive 判明) |

累計: PR merged 24 / Codex multi-round 59 rounds / findings 238 100% adopt / CRITICAL=0 / HIGH≤2 全 PR 達成。

### 1.2 残作業 (P0 Exit declaration までの blocker、本 plan 前の認識)

handoff memory (`project_session_2026_05_22_p0_exit_ready_handoff.md`) 時点の認識:

| # | task | 実施者 | 所要 | 状態 |
|---|---|---|---|---|
| 1 | Mac single-host Layer B (docker compose smoke) | user (本来) | 30-60 min | ⏳ 未着手 |
| 2 | Mac single-host Layer C (機能 + CLI smoke) | user | 60-120 min | ⏳ 未着手 |
| 3 | SP022-T09 host migration drill (Mac→VPS、RTO≤4h) | user | 2.5-4 h | ⏳ 物理 drill 待ち |
| 4 | retro Pack 作成 + ADR 昇格 (T09 後) | Claude | 30-45 min | ⏳ drill 完了通知後 |
| 5 | SP-012 + SP-022 frontmatter `completed` 化 | Claude | 10 min | ⏳ ADR accepted 後 (ただし ADR は既に accepted 済) |
| 6 | P0 Exit declaration PR 起票 (master plan §10-§11 + §1.3/§5 update) | Claude | 1-2 h | ⏳ frontmatter completed 後 |
| 7 | TASKHUB_P0_1_OPENED=1 解禁 + sealed CI guard 解除 | Claude | 30 min | ⏳ P0 Exit declaration merged 後 |
| 8 | SP-013 multi-agent orchestration 着手 | Claude | post-P0 | ⏳ P0.1 unblock 後 |

### 1.3 本 session 発覚 latent issues (P0 Exit 直接 gate に影響)

SP022-T09 prep Mac smoke verification を実施中に **Layer A の typecheck PASS は false positive** + **routing 3-way inconsistency** + **actions.ts typed routes cast 漏れ** が発覚:

#### Issue A: typed routes verify gap (Layer A の false positive)

- `pnpm typecheck` = `tsc --noEmit` のみ
- Next.js typed routes (`experimental.typedRoutes: true` in `frontend/next.config.ts`) は **build process が `.next/types/` directory に declaration 生成** することで動作
- `.next/types/` が存在しない場合、`tsc --noEmit` は typed routes の strict check を見逃す
- Layer A の typecheck PASS は false positive、実 Docker build (`pnpm build`) で初めて catch される

#### Issue B: actions.ts Route 型 cast 漏れ (latent build bug)

- `frontend/app/(auth)/login/actions.ts:219` で `redirect(safeRedirectPath(parsed.data.next))` が typed routes 上 type error
- `safeRedirectPath` の戻り値が `string` だが Next.js `redirect()` は `Route` 型を要求
- 修正: `import type { Route }` + `safeRedirectPath` 戻り値を `Route` に変更 + `value as Route` cast
- 前 Claude session で既に試みていた fix が **valid だった** ことが本 session で確認 (stash 保存済)

#### Issue C: navigation.tsx href の 3-way routing inconsistency

実 app/ 配置 (`frontend/app/(admin)/<thing>/page.tsx`、route group `(admin)` は URL prefix に含まれない) に対し、`frontend/components/navigation.tsx` の nav items は **存在しない `/dashboard/*` path を href として参照**:

| nav href | 実 page 配置 | 実 URL | 整合 |
|---|---|---|---|
| `/dashboard` | `app/(admin)/dashboard/page.tsx` | `/dashboard` | ✅ |
| `/dashboard/tickets` | `app/(admin)/tickets/page.tsx` | `/tickets` | ❌ |
| `/approvals` | `app/(admin)/approvals/page.tsx` | `/approvals` | ✅ |
| `/dashboard/agent-runs` | `app/(admin)/runs/page.tsx` | `/runs` | ❌ |
| `/dashboard/audit` | `app/(admin)/audit/page.tsx` | `/audit` | ❌ |
| `/dashboard/settings` | `app/(admin)/settings/page.tsx` | `/settings` | ❌ |
| `/login` | `app/(auth)/login/page.tsx` | `/login` | ✅ |

origin: `git log --oneline -10 frontend/components/navigation.tsx` で **commit `003e4b4` (SP-012 batch 6 BL-0149 skeleton) で navigation + admin routes 同時作成** された時点から不整合。typed routes が build-time でしか catch しない + UI 操作 (`pnpm dev` 起動) が CI で行われていない + Docker build が CI billing-blocked で 20 runs 連続 failure ため見逃された。

#### Issue D: smoke SOP の URL も `/admin/*` で誤記

`docs/deploy/mac-single-host-smoke-sop.md` §7-§11 の Layer C 確認 URL が `/admin/eval-dashboard`, `/admin/tickets`, `/admin/approvals`, `/admin/agent-runs`, `/admin/audit-log` と書かれているが、実 URL は `(admin)` route group で `/eval-dashboard`, `/tickets`, `/approvals`, `/runs`, `/audit`。

SOP に従って `/admin/eval-dashboard` を開いても 404 になり、Layer C 動作確認が成立しない。

#### Issue 影響範囲

| Issue | smoke 影響 | T09 drill 影響 | P0 Exit gate 影響 |
|---|---|---|---|
| A. typed routes verify gap | Layer A false positive (build 失敗を catch せず) | post-restore verify で同種見落とし risk | regression verify gap として持ち越し |
| B. actions.ts cast 漏れ | Layer B Docker build 失敗 (frontend) | drill 中の login flow 失敗 risk | Eval Dashboard UI smoke 不能 |
| C. nav routing inconsistency | navigation Link click が 404 | drill 中の admin UI 操作不能 | UI 動作確認の前提条件未達 |
| D. SOP URL 誤記 | Layer C 手順実行不能 | drill 手順 (`docs/deploy/half-yearly-drill-sop.md`) は SOP 流用 | drill 完了判定の verify 経路欠落 |

これらは P0 Exit declaration 前に解決必須。

## 2. 本 plan の目的と非目的

### 2.1 目的

1. 本 session 発覚 latent issues 4 件 (Issue A-D) を SP-022 must_ship の追加分として整合的に取り込み
2. これまでの作業 (PR #75-#93) を 100% 活用、何も捨てない方向 (新 PR で delta 修正のみ追加)
3. Codex review loop で本 plan を polish → READY 達成
4. Layer B/C smoke 経路を実動作可能にする
5. T09 drill 前提条件 100% 整備

### 2.2 非目的 (scope creep 防止)

- ADR Gate 11 種該当変更を含めない (URL convention 修正 + 型 annotation のみ)
- routing 構造の根本 refactor (例: `app/` の全 page 再配置) は実施しない。**実 app/ 配置を source of truth として固定**、navigation + SOP を fix
- 新 feature 追加を行わない
- SP-013+ 着手は本 plan の scope 外 (P0.1 unblock 後)
- master plan 本体 (`docs/設計検討/2026-05-13_p0_exit_master_plan.md`) の §3-§9 historical sections は本 plan 完了後の P0 Exit declaration PR で update (master plan Q6 default 維持、本 plan で前倒し partial update しない)

### 2.3 本 plan 完了後 〜 P0 Exit declaration merge までの boundary (F-R1-015 LOW adopt、pre-P0 freeze)

本 plan の Phase 6 (routing fix PR merged) 完了後、P0 Exit declaration PR (Phase 8) が **merge されるまでの間**は以下に **作業を制限**:

#### 許可作業 (pre-P0 freeze 期間内)

- routing fix follow-up (本 plan の rollback / Codex finding 追加対応)
- Layer B/C smoke 追加 evidence 収集
- T09 host migration drill 実施 (user 物理作業) + drill 結果 retro
- release docs 起票 (`docs/release/p0_exit_2026_05_DD.md`)
- Sprint Pack frontmatter `completed` 化 (Phase 8.2-8.3)
- master plan §3-§9 update (Phase 8.4、P0 Exit declaration PR 内)
- TASKHUB_P0_1_OPENED=1 解禁 PR の準備 (Phase 8.6、ただし merge は P0 Exit declaration merge 後)

#### 禁止作業 (TASKHUB_P0_1_OPENED=1 merge までは禁止)

- **SP-013 multi-agent orchestration 実装着手** (TASKHUB_P0_1_OPENED=1 merge 後にのみ unblock)
- SP-013 関連 ADR-00014 / ADR-00016 / ADR-00018 / ADR-00019 の `accepted` 昇格
- migration 追加 (特に P0 sealed CI guard 対象 `*event_type_37*` 等)
- 既存 Sprint Pack の must_ship 表変更 (SP-022 含む)
- routing 構造の追加 refactor (本 plan で固定した source of truth を破壊しない)

**理由**: P0 Exit declaration は Hard Gates 7 + Quality KPIs 5 全件 PASS の **凍結された evidence set** に対する declaration であり、declaration merge 前の変更は evidence invalidation を招く。

## 3. Latent Issue 統合分析

### 3.1 Issue A: typed routes verify gap

#### root cause

- `experimental.typedRoutes: true` (`frontend/next.config.ts`) は Next.js build 時に `.next/types/` に declaration を生成
- `tsc --noEmit` (= `pnpm typecheck`) は `.next/types/` を import するが、未生成だと strict check が走らない
- Layer A の手順では `pnpm install` → `pnpm typecheck` → `pnpm vitest` → `pnpm lint` の順、`pnpm build` を含めない

#### 修正方向 (1 案に固定、F-R1-002 HIGH adopt)

**採用 (固定)**: Layer A SOP の verify sequence に **`pnpm build` を別 step として追加**する。`pnpm typecheck` の意味 (= `tsc --noEmit`) は不変、`package.json` も触らない。

**理由**:
- `pnpm typecheck` を `next build && tsc --noEmit` に書き換える案 (旧 §4.2 item 8) は developer workflow 影響大 (CI 時間 / 既存 task 名 / dev cycle) + rollback 範囲拡大、scope creep のため不採用
- 採用案は SOP / Layer A plan の手順追加のみで package script 不変、Docker build と等価の typed routes check を追加可能

**棄却した代替案** (検討済、不採用):

| # | 案 | 不採用理由 |
|---|---|---|
| A | `pnpm typecheck` の前に `next build` で `.next/types/` 生成 | scope は同等だが、build を typecheck の sub-step にすると意図と命名が乖離 |
| C | typed routes を development mode で disable | runtime safety 低下 (build-time check 喪失)、ADR Gate 該当の可能性 |
| D | `package.json` の `typecheck` を `next build --no-warnings && tsc --noEmit` に強化 | developer workflow 影響大、scope 拡大、rollback 範囲拡大 |

**運用**:
- Layer A の手順 A-5 (frontend typecheck + eslint) の直後に **A-7 `pnpm build`** を追加
- `pnpm build` exit 0 で Layer A PASS、non-zero で failure (Layer A 結果に build log 添付)
- `package.json` / `tsconfig.json` / `next.config.ts` は不変

実装対象: `.claude/plans/sp022-t09-prep-mac-smoke.md` (Layer A plan) + `docs/deploy/smoke-evidence/2026-05-22-layer-A-addendum.md` (false positive + build step 追加記述)

### 3.2 Issue B: actions.ts Route 型 cast 漏れ

#### 修正内容 (前 Claude session の修正を本格採用 + F-PR-R1-WARN-1 反映)

```diff
 "use server";

+import type { Route } from "next";
 import { cookies } from "next/headers";
 import { redirect } from "next/navigation";
 import { z } from "zod";

 ...

-function safeRedirectPath(value: string | undefined): string {
+function safeRedirectPath(value: string | undefined): Route {
   if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
-    return "/dashboard";
+    return "/dashboard" as Route;
   }
-  return value;
   return value as Route;
 }
```

**注**: `"/dashboard"` literal を `as Route` 明示 cast する (F-PR-R1-WARN-1 adopt)。理由:
- Next.js `experimental.typedRoutes` で生成される Route union type は build 時に `app/(admin)/dashboard/page.tsx` が正しく registration されることに依存
- 万一 Route union に `"/dashboard"` literal が含まれない (build edge case) 場合の narrowing fail を防ぐため明示 cast を入れる
- Phase 2 step 9 の `pnpm build` PASS で間接 verify されるが、source code level で明示する方が安全 (`safer` pattern)

#### ADR Gate 該当性

- 修正内容: 型 annotation 追加のみ
- `safeRedirectPath` の validation logic (`startsWith("/")` / `startsWith("//")` reject / `\\` reject) は不変
- 認証・認可 semantics (cookie 発行 / session 検証) も不変
- ADR Gate Criteria 1 (認証・認可) の "logic 変更" には該当しない (型 annotation のみ、runtime 動作不変)

**判定**: ADR Gate 非該当。ただし PR description で「latent typed routes build bug fix、認証・認可 logic 不変」と明示する。

#### 安全境界 (F-R1-003 HIGH adopt、cast の runtime safety 過大評価防止)

**修正の目的を明確に分離**:

| 目的 | 担保方法 | 本 plan の修正対象? |
|---|---|---|
| **typed routes 型エラー解消 (build PASS)** | `value as Route` cast | ✅ 本 plan の対象 |
| **open redirect 防止 (security)** | 既存 `safeRedirectPath` 内部 validation (`startsWith("/")` reject `startsWith("//")` reject `\\` reject) | ✅ 既存実装で担保済 (本 plan で変更しない) |
| **typed routes 既知性 (実 route であることの runtime 保証)** | (本 plan では担保しない、accepted limitation) | ❌ 本 plan scope 外 |
| **post-login redirect allowlist** | (本 plan では導入しない、accepted limitation) | ❌ P0 scope 外 |
| **query / hash の許容ルール** | 既存 implementation 不変 (本 plan で変更しない) | ❌ 変更しない |

**結論**: `value as Route` cast は **型エラー解消のみ** を目的とし、security boundary (open redirect 防止) は既存 `safeRedirectPath` 内部 path validation が引き続き担保。allowed-route runtime allowlist 等の強化は **P0 scope 外、accepted limitation** として明示。

**verify 経路**:
- 既存 unit test (`frontend/__tests__/login-actions.test.ts` 等あれば) で validation logic を引き続き verify
- 本 plan の routing fix PR で test 追加が必要なら最小 negative test (`safeRedirectPath('//evil.com')` → '/dashboard'、`safeRedirectPath('/legit')` → '/legit') 追加
- runtime allowlist 強化 (future hardening) は post-P0.1 で別 PR、ADR-Gate 1 (認証・認可) 該当判定で別途検討

### 3.3 Issue C: navigation.tsx href 修正

#### 修正内容

```diff
 const navItems = [
   { href: "/dashboard", label: "Dashboard", current: true },
-  { href: "/dashboard/tickets", label: "Tickets", current: false },
+  { href: "/tickets", label: "Tickets", current: false },
   { href: "/approvals", label: "Approvals", current: false },
-  { href: "/dashboard/agent-runs", label: "Agent Runs", current: false },
+  { href: "/runs", label: "Agent Runs", current: false },
-  { href: "/dashboard/audit", label: "Audit", current: false },
+  { href: "/audit", label: "Audit", current: false },
-  { href: "/dashboard/settings", label: "Settings", current: false }
+  { href: "/settings", label: "Settings", current: false }
 ] as const;
```

#### ADR Gate 該当性

- URL 構造変更ではあるが、`/dashboard/tickets` 等は **そもそも存在しない route** (`app/(admin)/dashboard/tickets/page.tsx` ファイル無し)
- 修正は「存在しない URL 参照を実 URL に揃える」だけで、新 URL の追加 / 既存 URL の削除なし
- UI/UX の表示文言・layout・behavior 不変 (nav item label / order / styling 不変)
- ADR Gate Criteria 7 (外部公開設定) 非該当 (Tailscale 閉域内動作、外部公開 ingress 変更なし)

**判定**: ADR Gate 非該当 (latent UI bug fix)。

#### Eval Dashboard nav item 追加判定 (F-R1-012 LOW adopt、IA + placement 明示)

- PR #91 で `app/(admin)/eval-dashboard/page.tsx` 追加
- navigation の nav items に Eval Dashboard が無い → admin UI から到達経路欠落
- **本 plan で nav item 追加を提案** (permanent admin nav item):

  ```diff
   const navItems = [
     { href: "/dashboard", label: "Dashboard", current: true },
     { href: "/tickets", label: "Tickets", current: false },
  +  { href: "/eval-dashboard", label: "Eval Dashboard", current: false },
     { href: "/approvals", label: "Approvals", current: false },
     { href: "/runs", label: "Agent Runs", current: false },
     { href: "/audit", label: "Audit", current: false },
     { href: "/settings", label: "Settings", current: false }
   ];
  ```

- **IA / 表示条件** (F-R1-012 adopt):
  - 性質: **permanent admin nav item** (一時導線ではない、KPI 系として恒久)
  - placement: **Tickets と Approvals の間** (Dashboard / Tickets / Eval Dashboard / Approvals / Runs / Audit / Settings の順、KPI 系を前段に寄せる)
  - label: `Eval Dashboard`
  - active state: 既存 nav と同等の static `current: true/false` (本 plan §3.3 末尾 F-013 limitation 参照)
  - auth / admin layout 配下での表示条件: 既存 nav items と同等 (admin layout 配下、別 auth 制約なし)
  - これも latent UI gap fix で ADR Gate 非該当

#### nav active state semantics (F-R1-013 LOW adopt、accepted limitation)

- 現行 navigation は **static skeleton** で `current: true/false` を hard-code (`Dashboard` のみ true 固定)
- 修正後も active state は static、route 切替時の active 反映は本 plan scope 外
- **accepted limitation** として明記:
  - P0 Exit gate に含めず (本 plan で直さない)
  - 別 task として post-P0 UI polish backlog に記録
  - 本 plan の routing fix PR `## Review` で「nav active-state semantics は static skeleton accepted limitation、別 task 化」と明示

### 3.4 Issue D: SOP URL 修正 (F-R2-001 + F-R2-002 HIGH adopt、§6 + 他 docs 統合)

#### 修正対象 (`docs/deploy/mac-single-host-smoke-sop.md`)

**§7-§11 (admin page URL)**:

| 現状 | 修正後 |
|---|---|
| `http://127.0.0.1:3000/admin/eval-dashboard` | `http://127.0.0.1:3000/eval-dashboard` |
| `http://127.0.0.1:3000/admin/tickets` | `http://127.0.0.1:3000/tickets` |
| `http://127.0.0.1:3000/admin/approvals` | `http://127.0.0.1:3000/approvals` |
| `http://127.0.0.1:3000/admin/agent-runs` | `http://127.0.0.1:3000/runs` |
| `http://127.0.0.1:3000/admin/audit-log` | `http://127.0.0.1:3000/audit` |

**§6 dev login flow** (F-R2-001 HIGH adopt + F-PR-R1-BLOCK-1 §1 + F-PR-R1-WARN-2 反映、実コード + E2E 突合):

実装は `middleware.ts` で `PUBLIC_PATHS = ["/login", "/api/healthz"]` 以外への未認証アクセスを `/login?next=<original-path>` に redirect、login action 完了後に `next` query param 経由で元 URL に戻す構造。SOP §6 が `/` 開いて token 入力後 `/admin` redirect を期待しているのは **完全に誤認** (`/admin` route は存在しない、route group `(admin)` は URL prefix にならない)。

#### 修正後 SOP §6: 2 path 明示 (F-PR-R1-WARN-2 adopt)

**primary path (E2E test 正本と同経路、推奨)**:

| step | URL / 操作 | 期待 |
|---|---|---|
| 1 | `open http://127.0.0.1:3000/dashboard` | middleware で未認証 → `/login?next=%2Fdashboard` redirect |
| 2 | login form 表示 (`/login?next=%2Fdashboard`) | dev login token 入力 form 表示 |
| 3 | dev login token 入力 → "Sign in" click | login action 実行 + `taskmanagedai_session` cookie 発行 |
| 4 | redirect 到達 | `/dashboard` に戻る + admin navigation 表示 |
| 5 | DevTools 確認 | `taskmanagedai_session` cookie (HttpOnly + SameSite=Lax + Secure 属性 development では false) |

**alternative path (root landing page 経由)**:

| step | URL / 操作 | 期待 |
|---|---|---|
| 1 | `open http://127.0.0.1:3000/` | root landing page 表示 (Login + Dashboard link 含む) |
| 2 | "Dashboard" link click (未認証) | middleware で未認証 → `/login?next=%2Fdashboard` redirect |
| 3 以降 | primary path step 2-5 と同じ | 同上 |

**正本**: `frontend/tests/e2e/login.spec.ts` の dev login flow ("dev login proxies through the backend and shows the authenticated actor") は **primary path と完全に一致** (lines 28-46)。SOP §6 をこの spec と同期化必須。

**E2E test との同期化必須** (F-PR-R1-BLOCK-1 §1 adopt):
- SOP §6 修正で `/dashboard` 直接 GET → `/login?next=%2Fdashboard` redirect → token 入力 → `/dashboard` に戻る flow に変更
- E2E spec の URL pattern `/\/login\?next=%2Fdashboard$/u` (line 28) と SOP §6 の手順が同じ regex で表現できることを PR description `## Review` で明示
- E2E spec の `expect(page.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page")` (line 39) は **本 plan §3.3 末尾の nav active state accepted limitation** と整合 (`Dashboard` のみ `current: true` 固定で E2E test 通過)
- 本 plan の navigation 修正 (Eval Dashboard nav item 追加) は `Dashboard` link assertion に影響しない (`Eval Dashboard` は別 link)

#### 他 docs / plans の stale URL (F-R2-002 HIGH adopt、grep で発覚)

実 grep 結果と分類:

| file:line | 内容 | 分類 | 対応 |
|---|---|---|---|
| `docs/deploy/mac-single-host-smoke-sop.md` (上記 §7-§11 + §6) | smoke SOP URL | **active fix** | 本 PR で修正 (本 plan §4.2.3 file table item 3) |
| `docs/設計検討/2026-05-13_p0_exit_master_plan.md:338` | `cd frontend && pnpm exec axe http://localhost:3000/admin/tickets --rules wcag2aa,wcag21aa` (accessibility check command) | **active fix** | 本 PR で `/tickets` に修正 (P0 Exit master plan は active reference) |
| `docs/sprints/SP-011-5_operational_hardening.md:222` | 同 axe command (`/admin/tickets`) | **historical exception** | Sprint 11.5 は completed Sprint Pack、accepted exception として ledger 記録 (再実行不要、historical reference) |
| `docs/sprints/SP-012_p0_acceptance.md:432,437` | `frontend/__tests__/app/admin/eval-dashboard/page.test.tsx` | **false positive** | これは test file path (URL ではない)、修正不要 |
| `docs/設計検討/tailscale-private-staging-acl.md:17,28` | `https://login.tailscale.com/admin/*` | **false positive** | Tailscale 外部 service URL、本 app URL ではない、修正不要 |
| `.claude/plans/sp022-t09-prep-mac-smoke.md:89` (R2 finding 言及) | (再 grep で確認、active fix 候補) | **active fix** | 本 PR で確認 + 修正 |

#### Half-yearly drill SOP の確認

`docs/deploy/half-yearly-drill-sop.md` §11 にも UI smoke が含まれる場合、同種 URL 修正が必要。本 plan §5 Phase 2 step 3 (§4.2.1 同種 issue scan) で grep 確認 + active fix or historical exception 分類。

#### ADR Gate 該当性

- docs-only 修正
- 既存 SOP の URL 誤記を実 URL に修正するだけ
- 手順内容 (確認項目 / 期待値 / 失敗時対応) 不変
- §6 dev login flow も既存実装 (middleware.ts + E2E spec) に合わせるだけで認証・認可 logic 不変

**判定**: ADR Gate 非該当。

### 3.5 これらが P0 Exit gate にどう影響するか

#### Hard Gates 7 への影響 (F-PR-R1-WARN-3 adopt、過大評価修正)

| Hard Gate | 影響 | 説明 |
|---|---|---|
| AC-HARD-01 policy_block_recall | 無影響 | backend policy engine、frontend routing と無関係 |
| AC-HARD-02 secret_canary_no_leak | 無影響 | provider preflight、frontend と無関係 |
| AC-HARD-03 tenant_isolation_negative_pass | 無影響 | DB level、frontend と無関係 |
| AC-HARD-04 backup_restore_rpo_rto | **計測本体は無影響** (RTO 計測は backend CLI で完結)。T09 drill 後の UI smoke step で 404 → drill 完了判定の二次影響あり (UI verify は drill RTO 必須 step ではない、本 plan の routing fix で解消すれば二次影響も解消) | |
| AC-HARD-05 forbidden_path_block | 無影響 | runner sandbox、frontend と無関係 |
| AC-HARD-06 dangerous_command_block | 無影響 | runner sandbox、frontend と無関係 |
| AC-HARD-07 prompt_injection_resist | 無影響 | provider preflight、frontend と無関係 |

#### Quality KPIs 5 への影響 (F-PR-R1-WARN-3 adopt、過大評価修正)

| Quality KPI | 影響 | 説明 |
|---|---|---|
| AC-KPI-01 acceptance_pass_rate | **計測本体は無影響** (backend / EvalResult 計測で完結)、Eval Dashboard UI 表示確認 path で 404 (本 plan の routing fix で解消) |
| AC-KPI-02 time_to_merge | 無影響 | PR 計測 |
| AC-KPI-03 approval_wait_ms | **計測本体は無影響** (DB `approval_request.decided_at - requested_at` 計測で完結)、Approval Inbox UI 動作確認に URL 修正必要 |
| AC-KPI-04 citation_coverage | 無影響 | DB 計測 |
| AC-KPI-05 cost_per_completed_task | **計測本体は無影響** (`AgentRun.cost` 計測で完結)、Eval Dashboard UI 表示確認 path で 404 (本 plan の routing fix で解消) |

#### 結論 (F-PR-R1-WARN-3 修正後)

routing fix は **本質的に UI smoke / dashboard 表示の補助** であり、Hard Gates / Quality KPIs の **計測本体は全件 backend / DB / CLI で完結** (計測 fixture は影響なし)。ただし T09 drill 完了判定の UI verify step + dashboard 表示 path の 404 を解消する **二次効果** が必要。本 plan で SP-022 must_ship 追加分として取り込み、本質的には scope 小規模 hardening。

## 4. 修正方針 (今までの作業を活用)

### 4.1 設計判断: 実 app/ 配置 ((admin) route group) を source of truth

理由:
1. **実 page が存在する** = TypeScript / Next.js が route として認識している
2. **PR #91 (Eval Dashboard) も `(admin)/eval-dashboard/` に追加済** = 既存 pattern を踏襲済
3. **modify 範囲が最小** = navigation 6 行 + SOP 5 URL + actions.ts 4 行
4. **後方互換性** = `/admin/*` や `/dashboard/<sub>` への外部 link が存在しない (内部 nav と SOP のみ)
5. **設計意図と整合** = route group `(admin)` は URL prefix を出さず admin layout 共通化目的、初期設計の意図と一致

代替案 (採用しない、理由):

| # | 案 | 不採用理由 |
|---|---|---|
| A | `app/(admin)/` を `app/admin/` に refactor (route group やめ) | 多数 file 移動 + URL 構造変更 = 外部公開設定 ADR Gate 該当の可能性 + scope 拡大 |
| B | `app/(admin)/tickets/` を `app/(admin)/dashboard/tickets/` に nest 化 | file 移動 + scope 拡大 + SOP rewrite 必要 |

### 4.2 修正対象と変更内容 (F-R1-001 + F-R1-004 + F-R1-007 + F-R1-002 adopt)

#### 4.2.0 admin route inventory (Step 0、F-R1-001 HIGH adopt + F-PR-R1-BLOCK-1 §2 + F-PR-R1-WARN-2 反映)

実装着手前に **admin route 全体の URL inventory** を作成、本 plan §4 §5 §7 の acceptance criteria に組込む:

| route group | 実 page | 期待 URL | nav 掲載 | SOP 掲載 | UI smoke 対象 |
|---|---|---|---|---|---|
| (admin) | `app/(admin)/dashboard/page.tsx` | `/dashboard` | ✅ 既存 (`current: true` 固定 = accepted limitation) | ✅ | (default landing、E2E test 正本) |
| (admin) | `app/(admin)/tickets/page.tsx` | `/tickets` | 修正後 ✅ | ✅ §8 | ✅ Ticket smoke |
| (admin) | `app/(admin)/tickets/[id]/page.tsx` | `/tickets/<id>` | (dynamic、nav 掲載不要) | ✅ §8 | ✅ Ticket detail |
| (admin) | `app/(admin)/eval-dashboard/page.tsx` | `/eval-dashboard` | 修正後 ✅ (新規 nav item、Tickets と Approvals 間) | ✅ §7 | ✅ Eval smoke |
| (admin) | `app/(admin)/approvals/page.tsx` | `/approvals` | ✅ 既存 | ✅ §9 | ✅ Approval smoke |
| (admin) | `app/(admin)/approvals/[id]/page.tsx` | `/approvals/<id>` | (dynamic、nav 掲載不要) | ✅ §9 | ✅ Approval detail |
| (admin) | `app/(admin)/runs/page.tsx` | `/runs` | 修正後 ✅ | ✅ §10 | ✅ Agent Runs |
| (admin) | `app/(admin)/audit/page.tsx` | `/audit` | 修正後 ✅ | ✅ §11 | ✅ Audit log |
| (admin) | `app/(admin)/notifications/page.tsx` | `/notifications` | **`NotificationBadge` 経由で nav header から到達可能** (top-level nav item ではない、`frontend/components/notification-badge.tsx:17` `href="/notifications"`) | ❌ | (accepted defer、UI smoke 対象外) |
| (admin) | `app/(admin)/research/page.tsx` | `/research` | (top-level nav 不掲載、要確認) | ❌ | (accepted defer) |
| (admin) | `app/(admin)/research/[id]/page.tsx` | `/research/<id>` | (dynamic、nav 掲載不要) | ❌ | (accepted defer) |
| (admin) | `app/(admin)/settings/page.tsx` | `/settings` | 修正後 ✅ | ❌ | (accepted defer) |
| (auth) | `app/(auth)/login/page.tsx` | `/login` | ✅ logout 経路 | ✅ §6 | ✅ login flow |
| root | `app/page.tsx` | `/` | **landing page** (Login link + Dashboard link 2 箇所、`frontend/app/page.tsx:21,44` `href="/dashboard"`、未認証 click で `/login?next=%2Fdashboard` redirect) | ✅ §6 (optional path) | ✅ landing page UI |

**重要な注記** (F-PR-R1-WARN-2 adopt):
- root `/` は **redirect ではなく landing page** で、Login / Dashboard link 2 箇所を含む。未認証 click で middleware が `/login?next=<href>` redirect する。
- `notifications` route は top-level nav item に掲載しない (accepted defer) が、`NotificationBadge` component (nav header に常時 render) 経由で **click 可能** = nav header から到達可能。inventory として「nav top item 不掲載、ただし nav header から `NotificationBadge` 経由で到達」と扱う。

**未掲載判定** (F-R1-001 acceptance criteria):
- nav item 追加対象: **Eval Dashboard のみ** (本 plan §3.3 で固定)
- `notifications` / `research` の nav 掲載は **post-P0 UI polish backlog** に accepted defer (本 plan scope 外、SOP smoke 対象外でも到達性は dynamic link / breadcrumb で代替可能)
- `settings` の SOP smoke 対象外も accepted defer (UI 動作は他 nav item と同等の skeleton)

#### 4.2.1 同種 issue scan taxonomy (F-R1-004 MEDIUM adopt)

Phase 2 実装前に以下 6 category で同種 issue scan を実施、検出結果を adopt/defer/reject で記録:

| category | scan 対象 | 期待検出 |
|---|---|---|
| route literals (string) | `/dashboard/*`, `/admin/*` の hardcoded URL を全 repo grep | nav.tsx / SOP / runbook / test fixture / smoke script |
| Next navigation APIs | `redirect()`, `permanentRedirect()`, `router.push()`, `router.replace()`, `<Link href=...>` 全件 | actions.ts と同種 typed routes cast 漏れ |
| SOP / runbook URL | `docs/deploy/*.md` 内の `localhost:3000/`, `127.0.0.1:3000/` URL 全件 | SOP §1-§15 内 URL |
| smoke scripts | `scripts/*.py`, `scripts/*.sh` 内の URL 全件 | taskhub CLI smoke での URL 参照 |
| test fixtures | `tests/**/*.py`, `tests/**/*.ts` 内の URL 全件 | E2E test fixture |
| redirect query handling | `?next=`, `?redirect=`, `?return_to=` 等の path validation 全件 | safeRedirectPath 類似経路 |

scan は `Skill(Explore)` 推奨 (broad codebase grep)、または直接 `Grep` で実施。

#### 4.2.2 PR boundary 定義 (F-R1-007 MEDIUM adopt)

**単一 PR 採用、scope は明確分離**:

| 定義 | 内容 |
|---|---|
| **latent build bug fix** | Next.js build failure を解消する最小 code 変更 = `actions.ts` Route 型 cast |
| **routing inconsistency fix** | source-of-truth URL (実 app/ 配置) と参照の同期 = `navigation.tsx` href + SOP URL + (grep 後判明分) docs |

**PR scope (single PR で扱う)**:
- ✅ in-scope: 上記 2 種 + Layer A SOP 強化 (build step 追加) + Layer A evidence addendum
- ❌ out-of-scope (non-goals): SP-022 must_ship 表変更、routing 構造 refactor、UI/UX 文言・layout 変更、active state semantics 実装、allowed-redirect allowlist 強化

**PR title 案**: `feat(routing-build-hardening): typed routes cast + admin URL inventory sync + Layer A build step`

#### 4.2.3 修正対象 file table (修正後、F-R2-001 + F-R2-002 反映)

| # | file | 変更行数 | 種別 | reference |
|---|---|---|---|---|
| 1 | `frontend/app/(auth)/login/actions.ts` | +2 / -2 (import + 戻り値 + cast) | 型 annotation only (open redirect 防止は既存 path validation で担保、§3.2) |
| 2 | `frontend/components/navigation.tsx` | +1 / -5 (Eval Dashboard nav item 追加 + 5 href 修正、Tickets と Approvals 間に挿入) | routing fix (§3.3) |
| 3 | `docs/deploy/mac-single-host-smoke-sop.md` | -5 / +5 (§7-§11 URL 修正) + §6 dev login flow 修正 (F-R2-001) | docs-only (§3.4) |
| 4 | `docs/deploy/half-yearly-drill-sop.md` | scan 後判明分 (Phase 2 §4.2.1 で確定) | docs-only |
| 5 | `docs/deploy/operator-runbook.md` | scan 後判明分 (Phase 2 §4.2.1 で確定) | docs-only |
| 6 | `.claude/plans/sp022-t09-prep-mac-smoke.md` | Layer A SOP に build step (A-7) 追加 + L89 `/admin/eval-dashboard` 修正 (F-R2-002 active fix) | plan annotation |
| 7 | `docs/deploy/smoke-evidence/2026-05-22-layer-A-addendum.md` | + addendum (false positive 認識 + build step 追加) | docs-only addendum |
| 8 | `docs/設計検討/2026-05-13_p0_exit_master_plan.md:338` | `axe http://localhost:3000/admin/tickets` → `/tickets` (F-R2-002 active fix、master plan は active reference) | docs-only |
| ~~9~~ | ~~`docs/sprints/SP-011-5_operational_hardening.md:222`~~ | **historical exception** (Sprint 11.5 は completed、accepted exception として ledger 記録、本 PR で修正しない) | (除外、F-R2-002 分類) |
| ~~10~~ | ~~`docs/sprints/SP-012_p0_acceptance.md:432,437`~~ | **false positive** (test file path `frontend/__tests__/app/admin/eval-dashboard/page.test.tsx`、URL ではない) | (除外、F-R2-002 分類) |
| ~~11~~ | ~~`docs/設計検討/tailscale-private-staging-acl.md`~~ | **false positive** (Tailscale 外部 service URL、本 app URL ではない) | (除外、F-R2-002 分類) |
| ~~12~~ | ~~`frontend/package.json`~~ | **不変** (F-R1-002 採用案 = SOP step 追加、package script 変更しない) | (削除) |

合計: 約 8 file / 約 30-50 行修正 / scope 小規模 / ADR Gate 非該当。

**重要**: file #8 (`master plan 2026-05-13_p0_exit_master_plan.md`) は本 plan §9.3.3 で「P0 Exit declaration PR で 1 回 update (Q6 default 維持)」と固定したが、line 338 の axe command は **historical record ではなく active verification command** なので **本 PR で active fix** が必要 (Q6 default の対象は §3-§9 historical sections のみで、active commands は対象外)。

### 4.3 ADR Gate 該当性判定 (まとめ)

| 修正対象 | ADR Gate Criteria 11 種 | 該当判定 |
|---|---|---|
| actions.ts Route 型 cast | 1 認証・認可 (logic 不変、型のみ) | 非該当 |
| navigation.tsx href | 7 外部公開 (Tailscale 閉域内、外部 ingress 不変) | 非該当 |
| smoke SOP URL | docs-only | 非該当 |
| Layer A 強化 (build 追加) | docs-only (手順追加) | 非該当 |

**判定**: 全件 ADR Gate 非該当。ただし PR description / Sprint Pack `## Review` で「latent build bug fix + routing inconsistency fix、認証・認可 / 外部公開 logic 不変」を明示。

#### 4.3.1 ADR Gate 非該当 evidence 必須 4 点 (F-R1-011 MEDIUM adopt)

PR description に以下 4 点の evidence を添付:

| # | evidence | 確認方法 |
|---|---|---|
| 1 | route references scan | §4.2.1 同種 issue scan の 6 category 全件結果、未対応分は accepted defer 記載 |
| 2 | SOP / runbook URL scan | `docs/deploy/*.md` 全 URL 参照の修正前後 diff |
| 3 | known external ingress unchanged | Tailscale Serve config / Funnel 不使用 / 公開 bind 無 (`docker-compose.yml` 等の bind address 不変 verify) |
| 4 | API contract unchanged | `backend/app/api/**` の OpenAPI spec / endpoint signature 不変 (`git diff origin/main -- backend/app/api/` 0 件 verify) |

**accepted risk** (個人運用 P0):
- 既存 bookmark / 外部 link への影響: 個人運用 P0 (Tailscale 閉域内) のため accepted、PR description で明示
- nav active state semantics: §3.3 末尾 F-013 limitation で別 task 化、PR description で明示

### 4.4 後方互換 / 移行影響

- 外部 link / bookmark: 個人運用 P0 (Tailscale 閉域内) のため bookmark 移行影響は無視可能
- API contract: 不変 (`/api/v1/*` backend endpoint 一切触らず)
- session cookie / auth: 不変 (actions.ts の `safeRedirectPath` runtime 動作不変)
- DB schema: 不変
- migration: 不変

## 5. 実装手順 (Phase 分割)

### Phase 1: 本 plan 起票 + Codex review loop (本 plan stage)

1. 本 plan draft 起票 (`.claude/plans/p0-exit-final-hardening-2026-05-22.md`、本 file)
2. `codex-review-loop` を本 plan に対し起動 (mode=plan、Phase 1 = review-loop)
3. R{N} round で findings 100% adopt + R{N} CLEAN signal
4. `codex-adversarial-loop` を Phase 2 として起動 (security / race / edge case 視点)
5. Readiness Gate (CRITICAL=0 + HIGH≤2) 達成
6. plan-reviewer subagent 独立検証 (Codex 視点との交差)
7. plan READY signal

### Phase 2: routing fix branch 起票 + 実装 (F-R1-001/004/007 adopt step 統合)

1. 新 branch `routing-fix-2026-05-22` を `origin/main` から checkout
2. **§4.2.0 admin route inventory 作成** (実 app/ tree を grep して URL inventory table を埋める、未対応分は accepted defer 記載)
3. **§4.2.1 同種 issue scan** 実施 (6 category × Explore/Grep)、scan 結果を `~/.claude/local/codex-reviews/2026-05-22/<project>/plan-review-ledger.md § scan-results` に記録
3.5. **route-reference reconciliation** (F-R2-002 HIGH adopt、stale refs 分類):
   - scan で出た全 stale refs を `active fix` (本 PR 修正) / `historical exception` (ledger 記録) / `false positive` (URL ではない or 外部 service) の 3 分類
   - active fix 対象は §4.2.3 file table に追加
   - historical exceptions は ledger `§ historical-exceptions` に owner / 期限 / P0 Exit impact 記録
   - false positives は ledger `§ false-positives` に grep 結果 + 除外理由を記録 (再 grep 時の重複防止)
4. **§4.2.2 PR boundary 確認** (scope = §4.2.3 file table、non-goals = SP-022 must_ship 変更 / refactor / UI/UX 文言変更)
5. actions.ts Route 型 cast 適用 (型 annotation only、§3.2 safety 境界明示遵守)
6. navigation.tsx href 修正 + Eval Dashboard nav item 追加 (Tickets / Approvals 間)
7. smoke SOP URL 修正 (`mac-single-host-smoke-sop.md`)
8. operator-runbook / half-yearly-drill-sop の URL scan + 修正 (scan で判明分を反映)
9. local verify (順次実行、いずれかが fail なら Phase 2 失敗、F-PR-R1-INFO-2 adopt = build → typecheck 順序):
   - `cd frontend && pnpm install --frozen-lockfile`
   - `cd frontend && pnpm build` (= next build、`.next/types/` 生成 + typed routes check + build error catch)
   - `cd frontend && pnpm typecheck` (= tsc --noEmit、`.next/types/` 生成後に走らせる方が typed routes union を fully verify)
   - `cd frontend && pnpm vitest run`
   - `cd frontend && pnpm lint`
   - `cd frontend && pnpm test:e2e` (= Playwright、login flow + 主要 admin UI 経路 verify、F-PR-R1-BLOCK-1 §3 adopt) **または** 本 plan の routing fix は doc / type / static change 中心のため E2E 不要として明示 (運用判断は Phase 2 実行時に決定、CI で別途 run する場合は明示)
   - `docker compose --env-file .env.local build` (Docker build 全 5 service 成功確認)
10. evidence 4 点 (§4.3.1) 確認 + PR description draft 作成

### Phase 3: Layer A verify 強化 (F-R1-002 採用案 = SOP step 追加、package.json 不変)

1. `.claude/plans/sp022-t09-prep-mac-smoke.md` に Layer A 強化記述追加:
   - A-5 (frontend typecheck + eslint) の直後に **A-7 `pnpm build`** を追加
   - exit 0 で PASS、non-zero で failure (build log 添付)
2. `docs/deploy/smoke-evidence/2026-05-22-layer-A-addendum.md` 新規作成:
   - false positive 認識 (`pnpm typecheck` PASS でも Next.js typed routes は catch されない)
   - 本 PR で `pnpm build` step 追加で hardening 完了
   - 強化前 / 強化後の verify sequence 比較表
3. `frontend/package.json` は **不変** (F-R1-002 採用案により package script を触らない、棄却理由は §3.1 棄却した代替案 D)
4. local verify: `cd frontend && pnpm build` 単独実行で typed routes 含む全 check PASS 確認 + build artifact 削除

### Phase 4: Layer B smoke (Claude autonomous で実行可能箇所)

1. `cd /Users/tohga/repo/TaskManagedAI && git checkout smoke-2026-05-22` (already exists、`origin/main` 由来 + actions.ts working tree fix)
2. routing fix branch merge or rebase で Phase 2 修正取り込み
3. SOP §2 docker compose build (retry、ここで成功必須)
4. SOP §3 docker compose up -d + 5 service healthy 待機
5. SOP §4 alembic upgrade head
6. SOP §5 /healthz + frontend HTML + redis PING + postgres version
7. evidence 記録 (`~/.taskhub/drills/mac-single-host-smoke/2026-05-22/`)

### Phase 5: Layer C smoke の autonomous 可能箇所 (F-R1-008 MEDIUM adopt、preflight checklist 化)

#### 5.5.0 preflight checklist (各 smoke 実行前必須確認)

各 smoke を実行する前に以下を確認、不足は smoke skip + accepted defer 記録:

| # | 確認項目 | 判定 |
|---|---|---|
| 1 | required env: `.env.local` に `TASKMANAGEDAI_*` 必須 key 全件設定 | smoke 全件 |
| 2 | required secrets: 該当 smoke 用 SOPS / age / capability token bootstrap 済 | §12 §14 |
| 3 | required keys: `~/.taskhub/keys/approval-signing-key` (Ed25519) / `~/.taskhub/keys/age.key.txt` 存在確認 | §12 §14 |
| 4 | required seeded records: DB に test tenant_id=1 + smoke fixture seed 適用済 | §13 §15 |
| 5 | service health: §3 docker compose ps で 5 service healthy | smoke 全件 |
| 6 | side effects: smoke が生成する artifact (`~/.taskhub/backups/*`, `~/.taskhub/approvals/*`) の path 確保 + cleanup 想定 | §12 §14 |
| 7 | failure classification: smoke 失敗時の原因切り分け (routing fix 問題 / 環境問題 / 既知 latent issue) を log で判別可能か | smoke 全件 |

#### 5.5.1 smoke 分類 (required / best-effort / user-deferred)

| smoke | 分類 | autonomous 可? | P0 Exit gate に必須? |
|---|---|---|---|
| §6 dev login flow (UI cookie set) | user-deferred | ❌ user 必須 | ✅ 必須 (Hard Gate 経路) |
| §7 Eval Dashboard live wiring (API curl 経路) | **required** | ✅ autonomous | ✅ 必須 (KPI 経路) |
| §7 Eval Dashboard UI 表示確認 | user-deferred | ❌ user UI 必須 | best-effort (curl で代替可) |
| §8 Ticket 一覧 / 詳細 UI | user-deferred | ❌ user UI 必須 | best-effort |
| §9 Approval Inbox UI | user-deferred | ❌ user UI 必須 | best-effort |
| §10 Agent Runs 一覧 UI | user-deferred | ❌ user UI 必須 | best-effort |
| §11 Audit Log UI | user-deferred | ❌ user UI 必須 | best-effort |
| §12 taskhub approval issue smoke (CLI) | **required** (key bootstrap 後) | ✅ autonomous | ✅ 必須 (capability token 経路) |
| §13 signed journal verify CLI (--from-db) | **required** | ✅ autonomous | ✅ 必須 (audit chain verify) |
| §14 taskhub backup real smoke | **required** (age key bootstrap 後) | ✅ autonomous | ✅ 必須 (Hard Gate AC-HARD-04) |
| §15 golden flow Ticket→PR smoke (pytest) | best-effort | ✅ autonomous | best-effort |

#### 5.5.2 実行手順 (preflight PASS した required smoke のみ)

1. §7 Eval Dashboard live wiring (curl で `/api/v1/eval/kpi-rollup` 確認、UI 操作なしでも backend 動作確認可能)
2. §12 taskhub approval issue smoke (`~/.taskhub/keys` bootstrap 必要、preflight #3 で判定)
3. §13 signed journal verify CLI (`--from-db` mode、DB 接続のみ、preflight #4 で判定)
4. §14 taskhub backup real smoke (age key 必要、preflight #3 で判定)
5. §15 golden flow Ticket→PR smoke (`uv run pytest tests/eval/ticket_to_pr_smoke -v`、autonomous 可能)
6. evidence 記録 (`~/.taskhub/drills/mac-single-host-smoke/2026-05-22/` + 各 smoke の output + cleanup verify)

user 必須箇所 = §6 dev login UI / §7 UI 表示 / §8-§11 admin UI smoke は本 plan の autonomous scope 外、Layer C SOP に従い user 実施依頼。P0 Exit gate 必須なのは §6 dev login のみ (UI 経路、他は curl で代替可能)。

### Phase 6: PR 起票 + Codex review loop + merge

1. routing-fix branch から PR 起票 (`gh pr create`)
2. Codex auto-review 待機 + `codex_pr_full_review.sh <PR>` で baseline 内容確認
3. R{N} round で findings 全件 adopt/reject/defer 判定 + inline 反映 (R{N} CLEAN まで polish)
4. user merge (admin bypass `gh api -X PUT pulls/N/merge` で先行 merge も可、CI billing-blocked 環境のため)
5. main / origin/main へ反映

### Phase 7: Mac single-host 運用立証 (P0 Exit 直接 gate) + VPS migration drill (post-acceptance)

**重要訂正 (2026-05-22 PR #99、本 plan §1.3 latent issues 13 件目 = plan 自体の Phase 7 scope 誤認)**:

旧 Phase 7 「T09 host migration drill (Mac→VPS、RTO≤4h)」は **user 明示優先目的 (Mac で運用できることが第一、VPS はその後)** と整合しない scope 誤認だった。本訂正で Phase 7 を **7a (Mac 優先、P0 Exit 直接 gate) + 7b (VPS post-acceptance)** に分離:

#### Phase 7a: Mac single-host 運用立証 (P0 Exit declaration 直接 gate、user 必須 30-60 min × 2)

**目的**: user の優先目的 = Mac で P0 機能が運用可能な立証。Mac single-host で完結、VPS 不要。

##### 7a-1: Mac UI smoke (本 plan §5.5.1 user-deferred 全件、`docs/deploy/mac-single-host-operation-drill-sop.md` 経由)

- §6 dev login UI flow (Primary path: `http://127.0.0.1:3000/dashboard` → middleware で `/login?next=%2Fdashboard` redirect → token 入力 → `/dashboard` に戻る、E2E spec 正本同経路)
- §7 Eval Dashboard UI 表示確認 (nav から "Eval Dashboard" click、`/eval-dashboard`、PR #95 で新 nav item 追加)
- §8 Ticket 一覧 / 詳細 UI
- §9 Approval Inbox UI
- §10 Agent Runs 一覧 UI + 16 状態表示
- §11 Audit Log UI + raw secret 漏れなし確認

evidence: `~/.taskhub/drills/mac-single-host-smoke/<date>/C-ui-smoke-checklist.md` (本 plan §10.2 evidence dir)

##### 7a-2: Mac local backup/restore drill (AC-HARD-04 PASS、user 必須 30-60 min)

**重要**: 本 plan §3.5 で「AC-HARD-04 backup_restore_rpo_rto = **計測本体は backend CLI で完結 (RTO 計測は backend CLI で完結)**」と明示済 = **Mac local だけで AC-HARD-04 PASS 可能、VPS 不要**。

drill SOP: `docs/deploy/mac-single-host-operation-drill-sop.md` §2 (新規起票) または既存 SOP §12 §14 経路:

1. operator-runbook §1 で approval signing key (Ed25519) + age key bootstrap (~/.taskhub/keys/、mode 0600)
2. `taskhub approval issue` (smoke + backup approval、SOP §12)
3. `taskhub backup --output ~/.taskhub/backups/mac-local-drill-<date>.tar.age` (SOP §14)
4. 7 mandatory checklist verify (`docs/deploy/half-yearly-drill-sop.md` §11、ただし host migration step は skip = Mac local):
   - backup exit 0 + output file 存在 ✅
   - age decrypt 成功 ✅
   - tar listing 全 file 構造存在 (ADR-00021 §4) ✅
   - checksums verify (`shasum -a 256 -c checksums.txt`) ✅
   - private key 非混入 (CRITICAL invariant) ✅
   - pg_restore --list parse 成功 ✅
   - cleanup verified (`/tmp/taskhub-backup-*` 0 件) ✅
5. **Mac local restore drill** (新規 PostgreSQL container に decrypted backup を restore、RTO ≤ 4h 計測):
   - new PostgreSQL container 起動 (別 port、e.g. 5433)
   - decrypted pg_dump.dump を `pg_restore` で新 container に restore
   - 完了時刻 - 開始時刻 = RTO (target ≤ 4h)

evidence: `~/.taskhub/drills/mac-single-host-smoke/<date>/D-local-backup-restore-drill-checklist.json` + RTO 計測値

#### Phase 7b: VPS migration drill (T09、post-acceptance、P0.1 unblock 後)

**位置**: ADR-00021 host-portable deployment の post-acceptance verification。**P0 Exit declaration の直接 gate ではない** (本 plan §1.3 訂正)。

実施 timing: P0 Exit declaration merge 後 (post-P0.1)、ADR-00021 の host-portable invariant を実機 Mac→VPS migration で立証 (RTO ≤ 4h):

- SOP: `docs/deploy/half-yearly-drill-sop.md` §11 (7 mandatory checklist items)
- 設計: ADR-00021 §4 (file structure) / §6 (RTO target ≤ 4h)
- operator runbook: `docs/deploy/operator-runbook.md` §1-§22
- 必要前提: 物理 host 2 台 (Mac + VPS) + Tailscale 閉域接続 + SOPS age key 安全運搬 + signed approval

drill 完了後、user から checklist results を渡され、Claude が ADR-00021 post-acceptance verification を記録 (SP-022 Sprint Pack `## Review § Additional Hardening Gate § VPS migration drill (T09)` subsection)。

#### Phase 7a vs 7b 関係

| 観点 | Phase 7a (Mac 運用立証) | Phase 7b (VPS migration drill) |
|---|---|---|
| 目的 | Mac で P0 機能運用立証 | Mac→VPS host-portable verify |
| host | Mac 1 台 | Mac + VPS 2 台 |
| 所要 | 60-120 min (7a-1 UI + 7a-2 backup/restore) | 2.5-4 h |
| P0 Exit declaration gate | ✅ **直接 gate** (AC-HARD-04 PASS + Hard Gates 7 件中 Mac で計測可能項目全件) | △ post-acceptance (ADR-00021 verification、P0 Exit declaration の direct gate ではない) |
| 実施 timing | 本 plan 完了直後 (Phase 6 PR merge 後) | post-P0.1 unblock 後 (or P0 Exit declaration merge 後の任意 timing) |

#### 補足: Mac→VPS migration drill が P0 Exit declaration 直接 gate ではない根拠

- AC-HARD-04 (`backup_restore_rpo_rto`): RPO ≤ 24h + RTO ≤ 4h + PITR drill。**single host での backup→restore で計測完結** (本 plan §3.5 + `.claude/reference/hard-gates-and-kpis.md` 参照)
- ADR-00021 (host-portable deployment): post-acceptance verification = host migration drill。P0 Exit declaration **には ADR-00021 design accepted = SP022-T00 で済 (2026-05-19)**、post-acceptance verification は P0 Exit 後 or 任意 timing
- master plan §10.C で「host migration drill (Mac→VPS) RTO ≤ 4h PASS」を P0 Exit declaration condition として書いた記述は **本 PR で訂正**: 「Mac local backup/restore RPO/RTO drill PASS (AC-HARD-04 evidence)」が P0 Exit declaration direct gate、VPS migration drill は post-acceptance verification として分離

### Phase 8: P0 Exit declaration PR

1. SP022-T09 retro Pack 作成 (`docs/sprints/SP-022_framework_intake_hardening.md` `## Review` 追加 + checklist results 取り込み)
2. SP-012 frontmatter `status: partial_completed_with_carry_over → completed`
3. SP-022 frontmatter `status: draft → completed`
4. master plan `docs/設計検討/2026-05-13_p0_exit_master_plan.md` の §0/§1.1/§1.2/§3-§9 historical sections を P0 Exit declaration content で update
5. `docs/release/p0_exit_2026_05_DD.md` 起票 (Hard Gates 7 全件 PASS + Quality KPIs 5 未達 1 個以下 + backup/restore drill + 実機 host migration drill PASS evidence link)
6. `TASKHUB_P0_1_OPENED=1` 解禁 (`.env.example` / `docker-compose.yml` / CI guard update)
7. P0 sealed CI guard 解除 (`migrations/versions/*event_type_37*` 等の P0.1 path 追加禁止 lift)
8. PR 起票 → Codex review loop → user merge

## 6. Codex Review Loop Strategy

### 6.1 本 plan に対し (Phase 1)

| step | tool | 期待 round |
|---|---|---|
| R1-R{N} review | `Skill(codex-review-loop)` または `Skill(codex-all-loops)` mode=plan Phase 1 | 3-6 round |
| R1-R{N} adversarial | `Skill(codex-adversarial-loop)` または `Skill(codex-all-loops)` mode=plan Phase 2 | 2-4 round |
| 独立検証 | `Agent(plan-reviewer)` subagent | 1-2 round |

Readiness Gate: CRITICAL=0 + HIGH≤2 達成で plan READY signal。

### 6.2 各実装 batch に対し (Phase 6)

routing fix PR は小規模 (4-8 file / 30-50 行) のため:

| step | tool | 期待 round |
|---|---|---|
| Codex auto-review | GitHub PR auto-trigger | R1 (auto) |
| baseline 確認 + adopt/reject/defer | `codex_pr_full_review.sh <PR>` | R{N} (full helper for inline + conv + reviews) |

Readiness Gate: PR finding 全件 adopt/reject/defer 判定 + CLEAN signal で merge。

### 6.3 Round budget 見積 (F-PR-R1-INFO-1 adopt、plan-reviewer R2 round 追加)

| Phase | round | 所要 | 状態 (2026-05-22 本 plan 作成時点) |
|---|---|---|---|
| Phase 1 plan review (codex-plan-review) | 3 R | 30-45 min | ✅ 完了 (R1 17 findings / R2 2 / R3 0 CLEAN、累計 19 件全件 adopt) |
| Phase 1 plan-reviewer R1 (independent verify) | 1 R | 10-15 min | ✅ 完了 (BLOCK 1 + WARN 3 + INFO 3 = 7 件、全件 adopt + inline 反映済) |
| Phase 1 plan-reviewer R2 (BLOCK/WARN 反映後の verify) | 0-1 R | 5-10 min | ⏳ 本 plan 完了時に走らせる (BLOCK 解消確認用) |
| Phase 1 plan adversarial (codex-adversarial-loop、optional) | 1 R | 10-20 min | ⏳ plan-reviewer R2 後の追加 safety net (CRITICAL=0 + HIGH=0 既達なら skip 可) |
| Phase 6 PR auto-review (Codex bot + multi-round) | 1-3 R | 10-30 min | ⏳ PR 起票後 |

合計: 約 6-8 round / 65-120 min。本 plan target_days 2 / max_days 4 の内訳の plan stage 約 1-2 h (実績: 約 70 min 経過 + plan-reviewer R2 で +15 min 想定)。

## 7. Readiness Gate

### 7.1 plan READY 条件 (F-R1-001 + F-R1-014 + F-R1-017 adopt)

- [ ] Phase 1 Codex review loop R{N} CLEAN signal 達成
- [ ] Phase 1 Codex adversarial R{N} findings_zero 達成
- [ ] Phase 1 plan-reviewer agent CRITICAL=0 + HIGH≤2 達成
- [ ] 本 plan §0-§10 全 section に未確定 (TBD) なし
- [ ] ADR Gate 該当性判定 (本 plan §4.3 + §4.3.1 evidence 4 点) 全件 inline 確認
- [ ] **§4.2.0 admin route inventory が全件 reviewed** (F-R1-001、未対応分は accepted defer 記載)
- [ ] **active stale refs = 0** (F-R2-002、§4.2.1 scan 結果で active fix 対象全件 PR 内で修正済)
- [ ] **historical exceptions が ledger に列挙済** (F-R2-002、completed Sprint Pack 内 stale URL は accepted exception として `plan-review-ledger.md § historical-exceptions` に owner / 期限 / P0 Exit impact 記録)
- [ ] **§6 dev login flow SOP が `frontend/tests/e2e/login.spec.ts` 経路と完全一致** (F-R2-001、active fix)
- [ ] **plan review ledger が ~/.claude/local/codex-reviews/.../plan-review-ledger.md に作成済** (F-R1-014、本 plan の review/finding/decision の single source of truth)
- [ ] **HIGH 残存時は accepted-high.md に owner / reason / defer target / P0 Exit impact 記録済** (F-R1-017、ただし P0 Exit declaration READY では unresolved HIGH=0 を原則 — §7.3 参照)
- [ ] user 提示 + 着手承認 (or autonomous_full_drive policy に従い継続、§10.3 approval table 参照)

### 7.2 各 implementation batch READY 条件

- [ ] local verify: `pnpm typecheck && pnpm build && pnpm vitest && pnpm lint` PASS
- [ ] local verify: `docker compose --env-file .env.local build` PASS
- [ ] PR 起票 + Codex auto-review baseline 確認 (`codex_pr_full_review.sh <PR>` で内容確認、+0 delta misjudge 防止)
- [ ] R{N} round で findings 全件 adopt/reject/defer 判定
- [ ] CRITICAL=0 + HIGH≤2 達成

### 7.3 P0 Exit declaration READY 条件 (F-R1-017 LOW adopt、unresolved HIGH=0 原則)

- [ ] SP-022 T08 全 batch (1-6) completed (済)
- [ ] **Phase 7a-1 Mac UI smoke 完了** (user ブラウザ操作、§6-§11 全 page 動作確認 + UI smoke checklist)
- [ ] **Phase 7a-2 Mac local backup/restore drill PASS** (user CLI 実行、AC-HARD-04 = backup/restore RPO ≤ 24h + RTO ≤ 4h + 7 mandatory checklist PASS、Mac single-host で完結)
- [ ] (post-acceptance、P0 Exit declaration 直接 gate ではない) Phase 7b T09 Mac→VPS migration drill PASS (ADR-00021 host-portable post-acceptance verification、user 物理作業)
- ~~[ ] SP-022 T09 host migration drill PASS + checklist 7 件 PASS (user 待ち)~~ → **Phase 7a/7b 分離** (本 PR 訂正、Phase 7a が P0 Exit declaration 直接 gate、Phase 7b は post-acceptance)
- [ ] 本 plan の routing fix PR merged (Phase 6)
- [ ] Layer B smoke PASS (Phase 4)
- [ ] Layer C smoke autonomous 可能箇所 (§5.5.1 required 全件) PASS (Phase 5)
- [ ] Layer C smoke user 必須箇所 (§6 dev login UI、他は best-effort) PASS (user 報告待ち)
- [ ] retro Pack + frontmatter completed 化 (Phase 8.1-8.3)
- [ ] SP-022 Sprint Pack `## Review § Additional P0 Exit Hardening Gate` 追加 (本 plan の必須項目 + PR + evidence link、§9.1 参照)
- [ ] master plan §3-§9 update (Phase 8.4)
- [ ] `docs/release/p0_exit_2026_05_DD.md` 起票 (Phase 8.5)
- [ ] Hard Gates 7 全件 PASS evidence link
- [ ] Quality KPIs 5 未達 1 個以下 evidence link
- [ ] TASKHUB_P0_1_OPENED=1 解禁 PR merged (Phase 8.6-8.7)
- [ ] **unresolved HIGH = 0** (F-R1-017、plan/PR review HIGH 残存禁止、P0 Exit 直前 hardening は CRITICAL=0+HIGH=0 厳格)
- [ ] **unresolved MEDIUM ≤ 3** (本 plan で許容、各 MEDIUM は owner + defer target + P0 Exit impact 明記)

## 8. Risk + Rollback

### 8.1 主要 Risk

| # | risk | likelihood | impact | mitigation |
|---|---|---|---|---|
| 1 | routing fix が想定外 backwards-incompatible 影響を起こす | low | medium | Tailscale 閉域内動作 + 外部 link 無 + `pnpm build` 全 page check で latent issue catch |
| 2 | typed routes 強化が Layer A 時間を増やす | medium | low | `pnpm build` 追加で +30-60s 程度、許容範囲 |
| 3 | Codex review loop で deep adversarial finding が出て plan rewrite に追い込まれる | low | medium | 本 plan は小規模 scope (routing + cast + verify gap)、deep finding 余地小 |
| 4 | Layer B smoke で Docker build 後の up + healthy が新 issue を出す | medium | medium | Phase 4 で逐次確認 + log 保存、新 issue 発覚時は本 plan §10 で別 batch 追加 |
| 5 | T09 drill が user 都合で遅れ P0 Exit declaration が遅延 | medium | low | drill は本 plan scope 外、本 plan は drill 前提条件整備に集中 |
| 6 | 本 session 時間切れ (auto-compact) で context 喪失 | medium | low | memory persist 利用、handoff memory 起票で次 session continuation 可能 |

### 8.2 Rollback Strategy (F-R1-009 MEDIUM adopt、evidence invalidation 追加)

#### 8.2.1 code rollback (差分 revert)

| Phase | code rollback |
|---|---|
| Phase 1 (plan) | plan file 削除 or frontmatter `status: rejected` で defer |
| Phase 2 (routing fix branch) | branch 削除、stash も drop で完全 revert |
| Phase 6 (PR) | `git revert <merge SHA>` PR で revert (低リスク、6-7 file 修正のみ、§4.2.3 file table 参照) |
| Phase 8 (P0 Exit declaration) | declaration PR revert + master plan update revert |

#### 8.2.2 evidence invalidation (F-R1-009 adopt、code rollback と独立に処理)

routing fix PR (Phase 6) が merge 後に revert された場合、code 以外に以下 evidence を invalidate + 再実行対象を明示:

| invalidated evidence | 再実行 |
|---|---|
| `docs/deploy/smoke-evidence/2026-05-22-layer-A-addendum.md` | Layer A 再実行 (build step 含む) |
| `~/.taskhub/drills/mac-single-host-smoke/2026-05-22/B-*` | Layer B 再実行 (docker compose build + up + healthy) |
| `~/.taskhub/drills/mac-single-host-smoke/2026-05-22/C-*` | Layer C autonomous 部分再実行 (§5.5.1 required 全件) |
| `~/.taskhub/drills/mac-single-host-smoke/2026-05-22/result.json` | invalidate + 新 result.json 生成 |
| Sprint Pack `## Review § Additional P0 Exit Hardening Gate` subsection (§9.1) | `status: reverted` + 再実行 plan link 追記 |
| P0 Exit declaration PR (Phase 8) | hold (declaration 進めず) |

#### 8.2.3 P0 Exit declaration READY 巻き戻し条件

routing fix revert が決定した場合:

1. P0 Exit declaration PR (Phase 8) を draft に戻す (or close)
2. `TASKHUB_P0_1_OPENED=1` 解禁 PR (Phase 8.6) も hold
3. SP-013 multi-agent 着手 hold (post-P0.1 boundary 維持)
4. routing fix 代替案を Phase 1 から再起票 (新 plan or 本 plan revision)

## 9. 既存作業との関係 (無駄にしない明示)

### 9.1 SP-022 Sprint Pack との関係 (F-R1-005 MEDIUM adopt、1 案固定)

**採用 (固定)**: SP-022 Sprint Pack (`docs/sprints/SP-022_framework_intake_hardening.md`) の **must_ship 表は変更しない** (T08 9 件 / T09 drill 1 件のまま)。

本 plan で追加する routing fix は **`## Review § Additional P0 Exit Hardening Gate`** という新規 subsection で記録 (T08 batch 7 として must_ship 表に追加しない)。

**理由**:
- must_ship 表は **着手時の意思決定 boundary** であり、後から判明した latent issue を追加すると frontmatter `status: partial_completed_with_carry_over` の意味が曖昧になる
- Sprint Pack must_ship を凍結し、Additional Hardening は separate gate として明示する方が P0 Exit declaration PR でも追跡しやすい

**Additional P0 Exit Hardening Gate subsection の必須項目** (P0 Exit declaration READY §7.3 参照、F-PR-R1-INFO-3 adopt = DoD trace 追加):

| # | 項目 | 内容 | sprint-pack-adr-gate.md §7 DoD trace |
|---|---|---|---|
| 1 | 必須項目 | 本 plan §4.2.3 file table 全件 PASS | DoD-3 受け入れ条件が観測可能 + DoD-4 検証手順が実行可能 |
| 2 | PR link | routing fix PR (PR #?) | DoD-10 Review 欄の更新タイミングが決まっている |
| 3 | evidence link | Layer A addendum / Layer B smoke / Layer C autonomous smoke / scan results / inventory table | DoD-4 検証手順 + DoD-9 Hard Gates / Quality KPIs への trace |
| 4 | 完了判定 | code PASS + Layer A/B PASS + Layer C required smoke PASS + Codex review CLEAN + plan-reviewer 独立検証 CLEAN | DoD-3 + DoD-4 |
| 5 | accepted defer | nav active state semantics / notifications / research / settings nav 掲載 | DoD-5 rollback が現実的 + DoD-9 影響範囲 |
| 6 | rollback 手順 | §8.2 code + evidence + READY 巻き戻し 3 種を本 PR description に link | DoD-5 |
| 7 | audit event | (本 plan は routing/build/docs のみで audit event 不変、明示記載) | DoD-6 audit event が定義されている (本 plan で audit event 追加なしを明示) |
| 8 | DoD-8 影響表 | Provider Matrix / SecretBroker / AgentRun / DB invariant 不変を明示 | DoD-8 |

Phase 8.1 retro Pack 作成時に本 subsection を SP-022 Sprint Pack `## Review` に append。

### 9.2 PR #75-#93 との関係

- PR #75-#93 は全件 valid。本 plan の routing fix は **既存 PR の up-stream 修正**ではなく、**新 PR で delta 追加** (PR #94 想定)
- 既存 PR の content / commit を rewrite せず、累積 delta として新 PR 1 件で追加
- 本 plan に従えば PR 25 件目 (PR #94) で全 routing fix が反映され、P0 Exit declaration PR (PR #95 想定) へ進める

### 9.3 master plan §10-§11 との関係 (F-R1-010 MEDIUM adopt、supplement/override 関係明示)

#### 9.3.1 本 plan は master plan §10.C への temporary supplement

- master plan §10.C 実装着手順序の **SP-022 must_ship 全件完了 → P0 Exit declaration** path は不変
- ただし、本 plan は P0 Exit declaration 前に **追加の routing fix PR / Layer A 強化 / Layer B/C smoke を gate 化** するため、§10.C の着手順序に **新 prerequisite を挿入する supplement plan** として位置付ける
- master plan §10.C の修正は本 plan 完了後の **P0 Exit declaration PR で実績差分として反映** (Phase 8.4)

#### 9.3.2 P0 Exit declaration PR で master plan §10.C に反映する項目 (実績差分)

| 反映先 | 反映内容 |
|---|---|
| master plan §1.1 完了 Sprint | `本 plan (`.claude/plans/p0-exit-final-hardening-2026-05-22.md`)` を Additional Hardening Gate として追加 |
| master plan §1.3 ADR 状態 | (変更なし、本 plan 内 ADR Gate 非該当) |
| master plan §10.C 実装着手順序 | step 1.7 (SP022-T08 後) として「routing fix PR + Layer B/C smoke (本 plan)」を追加 |
| master plan §10.C 残作業 list | 「本 plan の Phase 6 routing fix PR merged」を P0 Exit declaration READY 条件に追加 |
| master plan §11 Open Decisions | Q6 default 維持 (P0 Exit declaration PR で 1 回 update) |

#### 9.3.3 反映 timing

master plan の partial update は **P0 Exit declaration PR で 1 回** (Q6 default 維持)。本 plan 完了後 〜 P0 Exit declaration merge までは master plan に partial update を入れない (scope creep 防止、Q6 reject 撤回しない)。

## 10. 進行管理

### 10.1 TaskCreate tracking

本 session で TaskCreate ID 1-6 が起票済 (現状把握 → plan draft → Codex review Phase 1 → Phase 2 → plan-reviewer → plan READY)。Phase 2 以降の各 batch は plan READY 後に追加 TaskCreate で tracking。

### 10.1.1 plan review ledger SoT (F-R1-014 LOW adopt、single source of truth)

本 plan の review / finding / decision を全 round 横断で追跡する single source of truth として:

```
~/.claude/local/codex-reviews/2026-05-22/sprint-SP-012-batch-7-taskhub-admin-cli/plan-review-ledger.md
```

を作成し、以下を全 round で append:

| column | 内容 |
|---|---|
| round | R1 / R2 / R3 / adversarial R1 / plan-reviewer R1 等 |
| finding id | F-R1-001 / F-R2-001 / F-ADV-R1-001 / F-PR-R1-001 等 |
| severity | CRITICAL / HIGH / MEDIUM / LOW |
| category | planning / missing / inconsistency / ambiguity / risk |
| decision | adopt / reject / defer |
| patch section | 本 plan §<section> (修正後追記) or rejected reason |
| residual risk | adopt 後の残余 risk 概要、accepted limitation との関係 |

各 round 完了時に ledger に append (Edit Tool で進める)、本 plan の `## Appendix C` セクションから ledger path をリンク。

### 10.2 evidence / log 保存先

| 種別 | 保存先 |
|---|---|
| plan review log | `~/.claude/local/codex-reviews/2026-05-22/TaskManagedAI/p0-exit-final-hardening/` |
| Layer A 強化 evidence | `docs/deploy/smoke-evidence/2026-05-22-layer-A-addendum.md` |
| Layer B smoke evidence | `~/.taskhub/drills/mac-single-host-smoke/2026-05-22/` |
| Layer C smoke evidence | `~/.taskhub/drills/mac-single-host-smoke/2026-05-22/` |
| T09 drill evidence | `~/.taskhub/drills/<date>/checklist-results.json` (user 提供) |

### 10.3 user 承認 checkpoint + merge 境界 (F-R1-006 MEDIUM + F-R1-016 LOW adopt)

#### 10.3.1 Phase 別 approval table (固定、autonomous vs explicit approval 境界明示)

| Phase | autonomous 範囲 | approval 区分 | merge 経路 |
|---|---|---|---|
| Phase 1 (plan) | plan draft / Codex review loop / inline 反映 | **notify-only** (user 提示は plan READY 時) | (merge なし) |
| Phase 2 (routing fix branch / 実装) | branch 起票 / 実装 / local verify | **notify-only** | (merge なし、PR 起票で Phase 6 へ) |
| Phase 3 (Layer A 強化) | SOP 修正 / addendum 起票 | **notify-only** | (Phase 6 PR に含める) |
| Phase 4 (Layer B smoke) | docker build / up / alembic / healthz | **notify-only** | evidence 記録 |
| Phase 5 (Layer C autonomous smoke) | curl + CLI smoke (required 分) | **notify-only** | evidence 記録 |
| Phase 5 (Layer C user 必須) | (none) | **explicit user approval** (user UI 操作必須) | user 完遂報告 |
| Phase 6 (PR 起票) | PR 起票 / Codex auto-review polling / R{N} polish | **notify-only** | (起票のみ) |
| Phase 6 (PR merge) | (none) | **explicit user approval** (user 直接 merge 原則) | user merge or admin bypass (§10.3.2 条件付き) |
| **Phase 7a-1 (Mac UI smoke、user 必須 30-60 min)** | (none) | **explicit user approval** (user ブラウザ操作必須) | user 完遂報告 (`~/.taskhub/drills/.../C-ui-smoke-checklist.md`) |
| **Phase 7a-2 (Mac local backup/restore drill、AC-HARD-04、user 必須 30-60 min)** | (Claude が CLI 提示、user が drill 実行 + RTO 計測) | **explicit user approval** (user CLI 実行、Mac single-host で完結) | user 完遂報告 (7 mandatory checklist + RTO 計測値) |
| **Phase 7b (T09 Mac→VPS migration drill、post-acceptance、2.5-4 h)** | (none) | **explicit user approval** (user 物理作業必須、Mac + VPS 2 台) | P0 Exit declaration 後 or 任意 timing (ADR-00021 post-acceptance verification、P0 Exit 直接 gate ではない) |
| Phase 8 (P0 Exit declaration PR 起票) | PR 起票 / master plan update / release docs (Phase 7a evidence link + Phase 7b は post-acceptance として記載) | **notify-only** | (起票のみ) |
| Phase 8 (P0 Exit declaration merge) | (none) | **explicit user approval** | user merge |

#### 10.3.2 admin bypass merge 条件 (F-R1-016 LOW adopt、5 点必須 + user 承認)

CI billing-blocked 環境下で admin bypass merge (`gh api -X PUT /repos/<owner>/<repo>/pulls/<N>/merge`) を許可する条件は **全 5 点 + user 明示承認必須**:

| # | 必須条件 | 確認方法 |
|---|---|---|
| 1 | clean branch from origin/main | PR branch が `origin/main` 由来 / divergent commit 無 (PR description にcommit graph 添付) |
| 2 | local command transcript | `pnpm typecheck && pnpm build && pnpm vitest && pnpm lint && docker compose build` 全件 exit 0 の transcript (PR description 添付) |
| 3 | docker build PASS | `docker compose --env-file .env.local build` 全 5 service exit 0 (Layer B 経路) |
| 4 | review loop CLEAN | Codex R{N} CLEAN + plan-reviewer 独立検証 CLEAN (CRITICAL=0 + HIGH=0) |
| 5 | PR description の evidence link | local transcript + Layer A/B evidence link / scan results link |
| 6 | user/admin approval | user (= admin) が `gh api -X PUT` 実行 (Claude が自動実行禁止、user 明示承認必須) |

**禁止経路**:
- Claude が自動で `gh api -X PUT` を実行する経路は禁止 (上記 #6 違反)
- CI billing-blocked が emergency excuse として恒久化しない (CI 復活時は通常 merge に戻す)

### 10.4 autonomous_full_drive policy 適用 (F-R1-006 adopt、境界明示)

`feedback_taskmanagedai_autonomous_full_drive.md` (project memory) に従い:
- **autonomous 範囲**: §10.3.1 「notify-only」と分類された Phase の作業 (plan draft / 実装 / review / PR 起票 / evidence 記録 / docs update)
- **explicit user approval 必須**: §10.3.1 「explicit user approval」と分類された箇所 (PR merge / T09 drill / P0 Exit declaration merge)
- AskUserQuestion は plan-level (routing 方向性判断) と spec 衝突 (ADR Gate 該当判定) と explicit approval Phase でのみ使用
- ScheduleWakeup で Codex R{N} polling 継続
- session auto-compact 走った後も本 plan + memory file から rehydrate して継続

---

## Appendix A: 本 plan 起票時の git state

```text
Current worktree: /Users/tohga/repo/TaskManagedAI/.claude/worktrees/sprint-SP-012-batch-7-taskhub-admin-cli
Current branch: worktree-sp022-t09-prep-mac-smoke (HEAD: 5fc48de)
Real repo (cd /Users/tohga/repo/TaskManagedAI):
  - Created new branch 'smoke-2026-05-22' from origin/main
  - Stashed actions.ts typed routes fix from previous Claude session (now applied to working tree)
  - .env.local pre-smoke backup at .env.local.pre-smoke-20260522-125529.bak
origin/main HEAD: f91dc70 (PR #93 merged)
```

## Appendix B: 関連 file 参照

- `docs/設計検討/2026-05-13_p0_exit_master_plan.md` (P0 Exit Master Plan 本体)
- `docs/sprints/SP-022_framework_intake_hardening.md` (SP-022 Sprint Pack)
- `docs/sprints/SP-012_p0_acceptance.md` (SP-012 Sprint Pack)
- `docs/adr/00021_host_portable_deployment.md` (ADR-00021 accepted)
- `docs/adr/00007_external_exposure.md` (ADR-00007 accepted)
- `docs/adr/00020_framework_intake_checklist.md` (ADR-00020 accepted)
- `docs/adr/00022_dev_login_cookie_secure_attribute.md` (ADR-00022 accepted)
- `docs/deploy/mac-single-host-smoke-sop.md` (Mac smoke SOP、本 plan で URL 修正対象)
- `docs/deploy/operator-runbook.md` (operator runbook、grep 確認対象)
- `docs/deploy/half-yearly-drill-sop.md` (T09 drill SOP)
- `.claude/plans/sp022-t09-prep-mac-smoke.md` (Layer A plan、本 plan で強化記述追加)
- `docs/deploy/smoke-evidence/2026-05-22-layer-A.md` (Layer A evidence、本 plan で addendum 追加)
- `frontend/app/(auth)/login/actions.ts` (Issue B 修正対象)
- `frontend/components/navigation.tsx` (Issue C 修正対象)
- `frontend/next.config.ts` (typedRoutes 設定確認)
- `frontend/package.json` (Issue A 強化対象 = typecheck script)

## Appendix C: Codex review prompt template (Phase 1 用)

```
本 plan (`.claude/plans/p0-exit-final-hardening-2026-05-22.md`) を以下 3 観点で review:

1. 抜け漏れ
   - routing inconsistency fix scope に漏れがないか (operator-runbook 等の grep が必要)
   - Layer A 強化方法の trade-off が他に存在しないか
   - P0 Exit declaration までの依存関係に gap がないか

2. 整合性
   - master plan (`docs/設計検討/2026-05-13_p0_exit_master_plan.md`) §10.C と矛盾しないか
   - SP-022 Sprint Pack must_ship 表との関係が明確か
   - ADR Gate 該当性判定 (本 plan §4.3) の根拠が正しいか
   - autonomous_full_drive policy との整合

3. 曖昧さ
   - 「latent build bug fix」「routing inconsistency fix」の定義が明確か
   - Phase 5 autonomous scope の境界 (curl 可 vs UI 操作必須) が明確か
   - rollback strategy の具体性
   - 本 plan 完了後の post-P0.1 boundary が明確か

severity: CRITICAL / HIGH / MEDIUM / LOW で finding を分類、CRITICAL=0 + HIGH≤2 で CLEAN。
```
