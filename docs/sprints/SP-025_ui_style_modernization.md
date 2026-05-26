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
