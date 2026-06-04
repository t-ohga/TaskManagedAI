---
id: "SP-028_webhook_ux"
type: "light"
status: "partial"
sprint_no: 28
created_at: "2026-05-26"
updated_at: "2026-06-04"
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

## Review

(2026-06-04 台帳監査) **部分実装**。`backend/app/api/github_webhooks.py` で GitHub webhook **受信** は実装済だが、SP-028 の目的である UX 層 (webhook event の toast 通知 / CI status live update / PR timeline 統合) は未実装。受け入れ条件も全て未チェック。commit `1b9cad6` (#261) の一括 status flip 対象。実態に合わせ `partial` へ訂正。残 UX 着手時に frontend 配線 + test。
