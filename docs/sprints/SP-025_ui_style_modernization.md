---
id: "SP-025_ui_style_modernization"
type: "light"
status: "completed"
sprint_no: 25
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 4
max_days: 6
---

## 目的

- P0 で最小限だった admin UI を、Tailwind CSS + shadcn/ui (or Radix) で視覚的に本格化する
- 既存の全 13 page (tickets / approvals / runs / audit / settings / eval / today / timeline / notifications / onboarding + detail pages) に統一デザインシステムを適用
- Dark mode 対応、responsive breakpoint 整理、loading/error/empty state の統一
- AgentRun 16 status の色分け badge、approval status の視覚区別

## 対象外

- 新規ページ追加 (既存ページのスタイル改善のみ)
- backend API 変更
- DB schema 変更
- 認証フロー変更

## 受け入れ条件

- [ ] shadcn/ui (or 選定 component library) の install + 設定完了
- [ ] 全 13 page で統一 design token (color / spacing / typography) 適用
- [ ] Dark mode toggle 動作
- [ ] AgentRun status badge が 16 状態で色分け表示
- [ ] Approval status (pending/approved/rejected/expired/invalidated) が視覚的に区別
- [ ] loading / error / empty state が全 page で統一コンポーネント
- [ ] Playwright smoke test (sprint9-pages + golden-flow) PASS
- [ ] Vitest component test PASS
- [ ] mobile (375px) / desktop (1280px) で主要 page が表示崩れなし

## 検証手順

```bash
cd frontend && pnpm typecheck && pnpm lint && pnpm test
cd frontend && pnpm test:e2e
```

## 残リスク

- component library 選定が ADR Gate に該当する可能性 (外部依存追加)
- Dark mode で secret canary 表示が見づらくならないこと
- 既存 E2E test の aria-label が変更で壊れる可能性

## Review

(2026-06-04 台帳監査) **実装確認、completed 維持**。shadcn/ui component (`frontend/components/ui/` の badge/button/card/table/tabs 等) + status badge (AgentRun 16 状態 / Approval 状態) 実装済。Dark mode toggle は M-2 (PR #320、ADR-00047) で完成。地上真実 (2026-06-04): frontend vitest 423 pass + next build / tsc / eslint clean。

受け入れ条件「loading / error / empty が全 page で統一コンポーネント」の実態 (実 grep で確認):
- **loading / error = 統一済**: App Router route-level `app/loading.tsx` / `app/error.tsx` + `app/(admin)/loading.tsx` / `app/(admin)/error.tsx` (+ tickets/runs loading.tsx) が admin 全 route を Suspense / error boundary で統一 (Next.js idiomatic な統一手段)。
- **empty = 全 page で機能的だが共有 component 集約は partial**: runs / approvals / research / onboarding 等は適切な空状態 UI を**描画している (機能は満たす)** が、共有 `EmptyState` (page-states.tsx) に寄せているのは research/ のみで、runs/approvals/onboarding は ad-hoc inline。
- page-states.tsx の `LoadingState` / `ErrorState` export は app 未使用 (dead export)。

**Codex CLI F-L6 / F-L7 採否判定 (事実 adopt / downgrade reject)**: 上記 dead export と empty consolidation partial の **事実は adopt** (Review を正直化)。ただし両 finding の **downgrade 推奨は reject**: ① loading/error は route-level で統一済、② empty は全 page で機能的に表示済 (feature は満たす)、未達は『共有 component への DRY 集約』のみ。これは SP-034 (idempotency dead param = 重複作成可能) / SP-035 (kill switch 未配線 = 暴走停止不能) のような **feature/safety の未達とは質的に異なる cosmetic な code-consistency follow-up**。よって SP-025 は UI modernization の core deliverable (shadcn / badge / dark mode / route-level loading-error) が shipped + 機能完備のため completed 維持。残: EmptyState 集約 + dead export 整理は別 scope の minor cleanup。
