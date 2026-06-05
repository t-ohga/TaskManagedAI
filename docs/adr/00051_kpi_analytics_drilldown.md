---
id: "ADR-00051"
title: "KPI Analytics Drilldown (SP-026: 運用実績 time series + eval provider breakdown, read-only)"
status: "proposed"
date: "2026-06-05"
accepted_at: null
deciders: ["t-ohga"]
adr_gate_criteria: [3]
related_adr:
  - "ADR-00040 (D-3/D-4 activity/cost 時系列、date_trunc UTC bucket 先例)"
  - "ADR-00039 (D-5/C-4 集計 endpoint、active-scope + SQL introspection test 先例)"
  - "ADR-00041 (read-only enrichment endpoint 先例)"
related_dd:
  - "DD-04 (Eval Harness / Quality KPIs)"
related_sprints:
  - "SP-026_analytics_drilldown (partial_skeleton。本 ADR で drilldown の未実装部分を実装)"
supersedes: null
superseded_by: null
---

# ADR-00051: KPI Analytics Drilldown (SP-026)

最終更新: 2026-06-05

## 背景

SP-026 (partial_skeleton) は P0 の read-only Eval Dashboard を「5 KPI × time series × provider/project
breakdown の drill-down」へ拡張する。現状 `frontend/app/(admin)/eval-dashboard/analytics/page.tsx` は
**skeleton (~90 行、`--` placeholder + static BarChart)** で、backend aggregation endpoint も drill-down も
未実装。

### 実コード突合で判明した P0 データ現実 (設計に直結)

1. **5 KPI の source-of-truth は fixture corpus** (`eval/quality/<kpi_id>/`、`compute_kpi_rollup()` pure
   function、`GET /api/v1/eval/kpi-rollup`)。これは **P0 Exit 判定用の point-in-time 測定**であり time series
   ではない。fixture KPI は P0 Exit の正本なので**改変しない**。
2. **operational live data の有無 (DB)**:
   - acceptance_pass_rate ← `acceptance_criteria.status` (satisfied/rejected)、created_at、project_id ✅
   - approval_wait_ms ← `approval_requests` (requested_at→decided_at)、index 有 ✅
   - citation_coverage ← `claims` + `evidence_items` (claim_id FK)、project_id、created_at ✅
   - cost_per_completed_task ← `agent_runs` (cost_usd, status=completed, created_at, project_id) ✅
   - **time_to_merge ← merge は P0 deny (`rules/core.md`、merge=P0 deny)。real merge / merge timestamp が
     存在しない → P0 では live data ゼロ** (fixture KPI のみが測定)。
3. **provider dimension**: `agent_runs` に **provider column は無い** (run→single-provider 帰属は意味的にも
   不正確)。provider は **`eval_runs.provider`** (provider bake-off、eval harness) に存在。eval_runs は
   project_id を持たず tenant-scoped。

## 決定対象

read-only な **(A) operational KPI time series endpoint** と **(B) eval provider breakdown endpoint** を追加し、
analytics page を drill-down 化する。**fixture P0-Exit KPI (kpi-rollup) は不変**、別軸として operational
trend を可視化する。

## 前提 / 制約

- **read-only API のみ (ADR Gate #3)**。migration なし (既存 table への live aggregation)。mutation なし。
- **fixture KPI 計算ロジックを複製しない (Pack 残リスク)**: operational time series は **同じ KPI 公式の
  semantics を再利用**するが、data source は live DB (fixture ではない)。fixture KPI (P0 Exit) と operational
  trend は **UI 上で明確にラベル分離** (「P0 Exit 判定 = fixture」/「運用実績 = live」)。
- tenant boundary + **active-scope** (`soft_deleted_ticket_run_exclusion()` 等) を全 aggregation で enforce。
- date_trunc は **'UTC' 3 引数** で session TZ 非依存 (ADR-00040 先例)、sparse response、null/0 区別。
- secret / raw payload を返さない (集計値のみ)。

## 選択肢

1. **fixture KPI を time series 化** — ❌ 却下。fixture は P0 Exit の point-in-time corpus で時系列の母数が無い
   (1 corpus = 1 測定)。改変は P0 Exit 判定の正本を壊す。
2. **agent_runs に provider column 追加 + 全 KPI を provider 別 live 集計** — ❌ 却下。run→single-provider 帰属は
   意味的に不正確 (1 run が複数 provider call)、migration + backfill (既存 run は provider 不明) のコスト過大。
3. **operational live time series (project/period) + eval provider breakdown (eval_runs.provider) を別軸で提供** —
   ✅ 採用。各 dimension を**正しい data source**から集計し、fixture KPI と分離ラベルで全 scope を欠落なく提供。

## 採用案 (詳細)

### (A) operational KPI time series endpoint

`GET /api/v1/eval/kpi_timeseries?bucket=day|week&range=week|month|year&project_id=<uuid>`

- `actor_id = Depends(get_current_actor_id)` + `tenant_id = Depends(get_tenant_id)` (authenticated)。
- **5 KPI それぞれ live aggregation** (UTC date_trunc bucket、tenant + active-scope + range cutoff、sparse):

| KPI | source | per-bucket 集計 (公式 semantics は fixture KPI と同一) | P0 |
|---|---|---|---|
| acceptance_pass_rate | acceptance_criteria | `count(status='satisfied') / nullif(count(status in ('satisfied','rejected')),0)` (created_at bucket) | ✅ |
| approval_wait_ms | approval_requests | `percentile_cont(0.5)` of `extract(epoch from decided_at-requested_at)*1000` (decided only、requested_at bucket) | ✅ |
| citation_coverage | claims⟕evidence_items | `count(claims with ≥1 evidence) / nullif(count(claims),0)` (claims.created_at bucket) | ✅ |
| cost_per_completed_task | agent_runs | `sum(cost_usd) filter(status='completed') / nullif(count filter(status='completed' and cost_usd not null),0)` | ✅ |
| time_to_merge | (merge event) | **P0 は merge deny → 常に空 bucket** (honest empty、fixture KPI が P0 Exit 用に測定) | ⚠️ empty |

- response `KpiTimeseriesResponse`: `{ bucket, range, series: [{ kpi_id, unit, threshold, buckets: [{bucket_start, value|null, sample_count}] }] }`。各 KPI は sparse (data 有 bucket のみ)、`value=null` は「測定不能/データ無し」(0 と区別)。
- `project_id` 任意 filter: 指定時は当該 project に限定 (acceptance/citation/cost は project_id 列、approval は run_id→agent_runs.project_id join)。未指定は actor の tenant 全体。
- **active-scope**: cost (agent_runs) は `soft_deleted_ticket_run_exclusion()`、acceptance/citation は project active + soft-delete 除外。
- 各 KPI の **value は閾値方向を含めず raw 値**を返し、frontend が threshold と比較表示。

### (B) eval provider breakdown endpoint

`GET /api/v1/eval/provider_breakdown?range=week|month|year`

- `eval_runs.provider` × `eval_scores` を join し、**provider 別**に `{ provider, model, run_count, metric_key 別 pass_rate / median score }` を集計 (tenant-scoped、started_at range cutoff)。
- provider bake-off (どの provider が eval で良い結果か) を可視化。eval_runs は project_id 非保持 → tenant 全体。
- secret なし、集計のみ。

### frontend (analytics page 本実装)

- `lib/api/eval-analytics.ts` (server fetch、`fetchBackendJson` = cache:no-store + session-bound、fail-closed loader `{ok}`)。
- `lib/domain/kpi-analytics.ts` (client-safe pure: zod schema + KPI 定義 + value 整形 + threshold 判定 tone)。
- analytics page: ① range tab (7d=week / 30d=month / 90d=year) ② project filter (現 project / 全体) ③ 5 KPI
  operational time series chart (既存 BarChart 流用、time_to_merge は「P0 では merge 無効のためデータ無し」明示)
  ④ provider breakdown table (eval bake-off)。**fixture P0-Exit KPI とは別 section + ラベル明示**で混同防止。
- 取得失敗 (fail-closed) は skeleton/「取得失敗」、空は「データ無し」、0 と null を区別表示。

## 却下案
- fixture KPI の time series 化 (選択肢 1)。
- agent_runs provider column 追加 (選択肢 2)。
- real-time streaming (Pack 対象外、polling で十分)。
- 外部 BI 連携 (Pack 対象外)。

## リスク

- **aggregation 性能 (N+1 / unbounded)**: range cutoff (week/month/year) + UTC bucket GROUP BY + 既存 index
  (approval_requests_idx_requested_at 等) で bound。citation の claims⟕evidence は claim 単位 GROUP BY +
  `exists(evidence)` で N+1 回避。median は `percentile_cont` 単一 query。
- **KPI 公式の drift**: operational 集計は fixture KPI と **同一公式 semantics** を使うが別 data。公式定数
  (threshold) を単一 source (frontend KPI_DEFINITIONS / backend) で揃え、drift guard test で固定。
- **fixture KPI との混同**: UI ラベルで「P0 Exit 判定 (fixture)」/「運用実績 (live)」を明確分離。
- **time_to_merge の空表示を「壊れ」と誤認**: 「P0 は merge 無効」注記で honest に表示 (機能削減ではない)。

## rollback 手順

1. **既存 schema/data に additive** (新 read endpoint 2 本 + frontend、migration なし)。
2. rollback: revert PR (endpoint + frontend 削除)。既存 kpi-rollup / eval-dashboard は不変。

## 実装対象ファイル

- `backend/app/services/eval/kpi_timeseries.py` (live aggregation SQL builder + 集計ロジック)
- `backend/app/api/eval_analytics.py` (kpi_timeseries + provider_breakdown endpoint) + router 登録
- `frontend/lib/domain/kpi-analytics.ts` (pure) + `frontend/lib/api/eval-analytics.ts` (server fetch)
- `frontend/app/(admin)/eval-dashboard/analytics/page.tsx` (skeleton → 本実装)
- tests: no-DB (SQL introspection: tenant/active-scope/date_trunc/group by 検証 + zod) + DB-gated
  (集計値正しさ/sparse/null-0 区別/project filter/provider breakdown) + frontend vitest (domain + page)

## テスト指針 (must-ship)

- **SQL introspection (no-DB)**: 各 KPI query が `tenant_id =` + active-scope (`NOT (EXISTS`) + `date_trunc(...,'UTC')`
  + `GROUP BY` + range cutoff を含む (capturing session で compiled SQL assert、ADR-00039 先例)。
- **集計正しさ (DB-gated)**: acceptance ratio / approval median / citation coverage / cost-per-completed が
  既知 fixture data で期待値、sparse (data 無 bucket は出ない)、value=null と 0 を区別。
- **project filter (DB-gated)**: project_id 指定で当該 project のみ、別 project の data を混ぜない。
- **active-scope (DB-gated)**: soft-deleted ticket の run を cost 集計から除外。
- **time_to_merge empty (DB-gated/no-DB)**: P0 では空 series + 「merge 無効」flag。
- **provider breakdown (DB-gated)**: eval_runs.provider 別 pass_rate / score、tenant-scoped。
- **公式 drift guard (no-DB)**: KPI threshold 定数が backend/frontend で一致。
- **frontend**: range tab 切替、project filter、null/0/取得失敗の 3 state 区別、text-only、RSC 境界 (next build)、
  fixture KPI と operational のラベル分離。

## Hard Gates / KPI への trace

- 既存 Hard Gate / KPI に regression なし (read-only additive、fixture KPI 不変)。
- DD-04 Eval Harness の KPI semantics と整合 (operational は同公式・別 data、provider bake-off は eval 拡張)。
