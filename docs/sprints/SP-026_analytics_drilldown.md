---
id: "SP-026_analytics_drilldown"
type: "light"
status: "completed"
sprint_no: 26
created_at: "2026-05-26"
updated_at: "2026-06-05"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00051](../adr/00051_kpi_analytics_drilldown.md)"
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

## Review

(2026-06-04 台帳監査) **部分実装**。`frontend/app/(admin)/eval-dashboard/analytics/page.tsx` (#261、~90 行) は存在するが、受け入れ条件 5 件は全て未チェックで、5 KPI × time series drill-down / provider・project filter / backend aggregation endpoint / drill-down route は未実装。KPI は SP-011 eval harness の流用で SP-026 固有の drilldown ロジックは無い。commit `1b9cad6` (#261) が status を実態より先に completed へ変更していた。実態に合わせ `partial_skeleton` へ訂正 (dogfooding seed は `partial_skeleton`→in_progress ticket に projection。bare `partial` は seed mapping 未対応で fallback=open になるため不可、Codex App F-L1)。残 must_ship 着手時に backend aggregation + frontend drilldown + test。

(2026-06-05、PR #327 merged → **completed**) ADR-00051 に基づき KPI analytics drilldown を実装完遂。

- **ADR-00051 accepted_at: 2026-06-05** (plan-review R1 9 + R2 0 = 収束)。最大の是正: operational KPI 公式を
  独自再実装せず **既存 4 metric service** (OrchestratorKpiRollup / ApprovalWaitMs / AdoptedArtifactCitationCoverage /
  AgentRunKpi proxy) の公式を bucketing 再利用 (Pack 残リスク「KPI 計算ロジック重複」回避)。
- 実装: kpi_timeseries service (5 KPI × date_trunc UTC bucket + project filter + active-scope + state enum
  measured/no_denominator/partial_unmeasured/proxy) + provider_breakdown (eval_runs bake-off、tenant-wide) +
  frontend (operational time series + range/scope tab + fixture KPI とラベル分離 + fail-closed)。
- codex-adversarial R1 (F-2 unattributed approval over-count / F-1 citation soft-delete = 2 HIGH adopt、
  F-1 project-active reject [archived=visible 既存 precedent 整合]) → R2 **approve**。
- 受け入れ条件: drill-down UI / 5 KPI time series (7d/30d/90d) / project filter / backend aggregation /
  既存 KPI source-of-truth 整合 = 全達成 (✅、14 no-DB + 5 DB-gated + 15 vitest)。
- **scope note**: provider 軸は eval_runs (operational metric tables に provider 列無し)。time_to_merge は既存
  proxy。fixture P0-Exit KPI は不変 (別軸)。機能削減なし。
- 残: ブラウザ実機検証 (user 委譲)。
