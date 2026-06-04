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

(2026-06-04 台帳監査) **実装確認、completed 維持**。shadcn/ui component (`frontend/components/ui/` の badge/button/card/table/tabs 等) + status badge (AgentRun 16 状態 / Approval 状態) 実装済。Dark mode toggle は M-2 (PR #320、ADR-00047) で完成。**loading/error/empty の「全 page 統一」は App Router route-level convention で達成**: `app/loading.tsx` / `app/error.tsx` + `app/(admin)/loading.tsx` / `app/(admin)/error.tsx` (+ tickets/runs の loading.tsx) が admin 全 route の loading/error UI を統一 (route group の Suspense / error boundary)、empty は `EmptyState` (page-states.tsx) を使用。地上真実 (2026-06-04): frontend vitest 423 pass + next build / tsc / eslint clean。

**Codex CLI F-L6 への採否判定 (adopt 事実 / reject downgrade)**: page-states.tsx の `LoadingState` / `ErrorState` export が app 未使用 (dead export) という事実は確認・**adopt** (当初 Review が page-states を loading/error の evidence として citation したのは不正確、上記に訂正)。ただし「loading/error の統一 acceptance が未達」という downgrade 推奨は **reject**: 統一は route-level `loading.tsx`/`error.tsx` (Next.js App Router の idiomatic 手段) で実際に満たされており、未使用なのは shared component の重複 export のみ。よって status は completed 維持。dead export 整理は別 scope の minor cleanup。
