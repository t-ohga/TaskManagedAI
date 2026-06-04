---
id: "SP-032_research_advanced"
type: "light"
status: "partial"
sprint_no: 32
created_at: "2026-05-26"
updated_at: "2026-06-04"
target_days: 2
max_days: 3
---

## 目的

- conflict_group_id + freshness_score + domain trust registry + 矛盾検出

## 対象外

- P0 invariant の変更 (16 status / 3 blocked_reason / 10 ContextSnapshot columns は不変)
- 破壊的 migration (additive のみ)

## 受け入れ条件

- [ ] 実装完了 + lint / typecheck / test PASS
- [ ] 既存 Hard Gate / KPI に regression なし
- [ ] Sprint Pack Review 章更新

## 検証手順

```bash
uv run ruff check backend tests && uv run mypy backend
cd frontend && pnpm typecheck && pnpm lint && pnpm test
uv run pytest -q
```

## 残リスク

- ADR Gate 該当の場合は heavy Pack 化 + ADR 起票が必要

## Review

(2026-06-04 台帳監査) **部分実装**。claim model / schema に `conflict_group_id` / `freshness_score` フィールドは存在 (SP-010 由来の reserved column) するが、SP-032 の目的である矛盾検出ロジック / freshness 計算 / domain trust registry 連携は未実装。受け入れ条件も全て未チェック。SP-027 (source trust registry) とも依存。commit `1b9cad6` (#261) の一括 status flip 対象。実態に合わせ `partial` へ訂正。
