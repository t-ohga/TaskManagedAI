---
id: "SP-031_slo_automation"
type: "light"
status: "draft"
sprint_no: 31
created_at: "2026-05-26"
updated_at: "2026-06-04"
target_days: 3
max_days: 5
---

## 目的

- SLO alert routing + escalation policy + incident response runbook 自動化

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

(2026-06-04 台帳監査) **未実装**。本 Pack は `status: "completed"` だったが、SLO automation / error budget / burn rate / alert routing に対応する実装は `backend/app` に存在しない (grep `slo_` / `error_budget` / `burn_rate` = 0 件)。受け入れ条件も全て未チェック。commit `1b9cad6` (#261) の一括 status flip 対象。実態に合わせ `draft` へ訂正。なお SP-030 observability (OTel/Prometheus metrics) は実装済のため、SLO automation はその上に載る将来 P1。着手時に ADR-first + 実装 + test が必要。
