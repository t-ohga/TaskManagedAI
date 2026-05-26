---
id: "SP-028_webhook_ux"
type: "light"
status: "completed"
sprint_no: 28
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 3
max_days: 5
---

## 目的

- GitHub webhook event の toast 通知 + CI status live update + PR timeline 統合

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
