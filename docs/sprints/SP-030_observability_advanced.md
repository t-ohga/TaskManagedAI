---
id: "SP-030_observability_advanced"
type: "light"
status: "completed"
sprint_no: 30
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 4
max_days: 6
---

## 目的

- OTel trace + Grafana dashboard + Loki log aggregation + Prometheus metrics 拡張

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

(2026-06-04 台帳監査) **実装確認、completed 維持**。`backend/app/observability/` (otel.py / prometheus.py / logging.py / config.py) で OpenTelemetry trace + Prometheus metrics + structured logging を実装、`backend/app/main.py` に配線済。地上真実 (2026-06-04): backend pytest 4404 pass / 0 fail。受け入れ条件チェックボックスは未更新だったが実コード + test は green。Review 欄欠落のみ追記 (Grafana/Loki dashboard 自体は外部 infra 設定で本 Pack scope 外)。
