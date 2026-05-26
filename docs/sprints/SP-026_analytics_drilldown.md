---
id: "SP-026_analytics_drilldown"
type: "light"
status: "draft"
sprint_no: 26
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 3
max_days: 5
---

## 目的

- P0 の read-only Eval Dashboard を拡張し、KPI → detail → time series の drill-down を実装
- acceptance_pass_rate / time_to_merge / approval_wait_ms / citation_coverage / cost_per_completed_task の 5 KPI を時系列グラフ + filter で表示
- provider 別 / project 別 / period 別の breakdown

## 対象外

- 新規 KPI の追加
- Real-time streaming (polling で十分)
- 外部 BI ツール連携

## 受け入れ条件

- [ ] /eval/analytics route に drill-down UI 実装
- [ ] 5 KPI × time series chart (7d / 30d / 90d)
- [ ] provider / project filter
- [ ] backend aggregation API endpoint
- [ ] 既存 KPI source-of-truth との整合

## 検証手順

```bash
cd frontend && pnpm typecheck && pnpm lint && pnpm test
uv run pytest tests/ -k "kpi or analytics" -q
```

## 残リスク

- 大量データでの aggregation 性能 (N+1 / unbounded query)
- KPI 計算ロジックの重複 (eval harness vs analytics endpoint)
