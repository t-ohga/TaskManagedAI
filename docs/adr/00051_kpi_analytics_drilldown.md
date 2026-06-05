---
id: "ADR-00051"
title: "KPI Analytics Drilldown (SP-026: 運用実績 time series + eval provider breakdown, read-only)"
status: "accepted"
date: "2026-06-05"
accepted_at: "2026-06-05"
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

最終更新: 2026-06-05 (plan-review R1 9 + R2 0 = 収束、accepted)

## 背景

SP-026 (partial_skeleton) は P0 の read-only Eval Dashboard を「5 KPI × time series × provider/project
breakdown の drill-down」へ拡張する。現状 `frontend/app/(admin)/eval-dashboard/analytics/page.tsx` は
**skeleton (~90 行、`--` placeholder + static BarChart)** で、backend aggregation endpoint も drill-down も
未実装。

### 実コード突合 + plan-review R1 (9 findings) で判明した P0 データ現実 (設計に直結)

1. **5 KPI の P0-Exit source-of-truth は fixture corpus** (`eval/quality/<kpi_id>/`、`compute_kpi_rollup()`、
   `GET /api/v1/eval/kpi-rollup`) = **point-in-time 測定**。fixture KPI は P0 Exit 正本なので**改変しない**。
2. **operational live metric は既存 service に canonical 実装が存在** (`backend/app/services/metrics/`)。
   SP-026 は **これらを再利用** し、time-series bucketing を被せる (公式を複製しない、Pack 残リスク回避):
   - `OrchestratorKpiRollupService` (SP-014): `completed_run_count` / `cost_per_completed_task_usd`
     (= provider_total_cost / **全 completed run 数** が分母) / `time_to_merge_proxy_median_ms` /
     `approval_wait_median_ms` を**まとめて**算出。
   - `ApprovalWaitMsMetricService` (AC-KPI-03): `status in ('approved','rejected')` AND `decided_at NOT NULL`
     AND `decided_at >= requested_at` の `percentile_cont(0.5)` median_ms。
   - `AdoptedArtifactCitationCoverageService` (SP-020): citation_coverage は **final-adopted artifact**
     (`adoption_state='final'`, `finalized_at`) を分母にする (**raw claims ではない**)。
   - `AgentRunKpiService` (AC-KPI-02): `time_to_merge_proxy` = `repo_pr_opened_to_agent_run_completed`。
     **real merge は P0 deny だが proxy が存在する** (= 「空」ではなく proxy。UI で proxy と明示)。
3. **acceptance_pass_rate の operational source**: 専用 metric service は無い。operational では
   `acceptance_criteria.status` (`satisfied` / `rejected`) の比率を用いる (fixture KPI と公式 semantics 同一、
   data は live)。**operational acceptance であることを明示**。
4. **range vocabulary**: 既存は `CostSummaryRange = today|week|month|quarter|all` (`quarter`=90日)。SP-026 は
   `week(7d)|month(30d)|quarter(90d)` を採用 (`year` は誤り、F-006)。
5. **provider dimension**: `agent_runs` に provider column 無し (run→single-provider 帰属は不正確)。provider は
   **`eval_runs.provider`** (bake-off) のみ。eval_runs は project_id 非保持で **tenant-scoped**。provider
   breakdown は tenant-wide であることを response/UI に明示 (F-005)。

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

`GET /api/v1/eval/kpi_timeseries?bucket=day|week&range=week|month|quarter&project_id=<uuid>`

- `actor_id = Depends(get_current_actor_id)` + `tenant_id = Depends(get_tenant_id)` (authenticated)。
- **既存 metric service の公式を再利用**し、`date_trunc(bucket, <time_col>, 'UTC')` で GROUP BY bucket を被せる。
  公式 (status set / denominator / source / time source) は既存 service と**共有定数/共有 SQL fragment**で
  揃え、drift guard test で固定する (F-009)。各 KPI の per-bucket 集計と time source:

| KPI | 既存 service / source | per-bucket 公式 | time source | P0 状態 |
|---|---|---|---|---|
| acceptance_pass_rate | acceptance_criteria (operational) | `count(status='satisfied') / nullif(count(status in ('satisfied','rejected')),0)` | created_at | measured |
| approval_wait_ms | `ApprovalWaitMsMetricService` | `percentile_cont(0.5)` of wait_ms、`status in ('approved','rejected')` AND `decided_at NOT NULL` AND `decided_at>=requested_at` | requested_at | measured |
| citation_coverage | `AdoptedArtifactCitationCoverageService` | **final-adopted artifact** (`adoption_state='final'`) 基準の coverage | finalized_at | measured |
| cost_per_completed_task | `OrchestratorKpiRollupService` | `sum(provider cost) / nullif(completed_run_count,0)` (分母=**全 completed run**)。`measured/unmeasured_completed_run_count` も返す (F-002) | completed_at | measured / partial_unmeasured |
| time_to_merge | `AgentRunKpiService` proxy | `time_to_merge_proxy` (`repo_pr_opened_to_agent_run_completed`) の median。**proxy であることを明示** (F-004) | completed_at | proxy |

- **response `KpiTimeseriesResponse`**: `{ bucket, range, series: [{ kpi_id, unit, threshold, direction, measurement_kind: 'measured'|'proxy', buckets: [{bucket_start, value|null, state, numerator_count?, denominator_count?, measured_count?, unmeasured_count?}] }] }`。
- **bucket `state` enum (F-008)**: `measured` (値有) / `no_denominator` (分母 0、value=null) / `partial_unmeasured`
  (cost で unmeasured_completed>0) / `proxy` (time_to_merge)。sparse (data 無 bucket は出さない) と
  `no_denominator` (bucket は有るが分母 0) を区別。`value=null` の理由を state で表現。
- **KPI definition authority = backend** (F-009): unit / threshold / direction / measurement_kind は backend が
  返し、frontend は表示のみ (threshold 定数を frontend で再定義しない)。
- `project_id` 任意 filter: acceptance/citation/cost は project_id 列で限定。approval は `run_id → agent_runs.project_id`
  join (run_id nullable・FK TODO) のため、project 指定時は **`unattributed_approval_count` を別途返す**。
  **adversarial F-2 fix**: unattributed は **run_id null / stale (join 不成立) のみ**カウント (別 project の
  正当な approval を「未紐付」と誤計上しない)。未指定は tenant 全体。
- **active-scope (adversarial F-1 + 既存 precedent 整合)**: cost / time_to_merge / acceptance / **citation** は
  全て `soft_deleted_ticket_run_exclusion()` 相当 (soft-deleted ticket に紐づく run/artifact を除外)。citation は
  当初実装で欠落していたため fix 済。tenant boundary 必須。
  - **archived project は除外しない (project-active 部分は reject)**: 既存の canonical active-scope helper
    `soft_deleted_ticket_run_exclusion()` は全 default read path (cost_summary / activity_timeseries / KPI rollup)
    で **soft-deleted ticket のみ除外し archived project は含める** (archived = read-only-visible、ADR-00037)。
    KPI の cost は cost_summary と同一 agent_runs data を使うため、KPI だけ project-archive 除外すると
    cost_summary と数値が不整合になる。よって既存 precedent に合わせ archived は historical operational data
    として含める (consistency 優先、rejected.md に記録)。
- raw 値を返し frontend が threshold 比較表示 (direction も backend が返す)。

### (B) eval provider breakdown endpoint

`GET /api/v1/eval/provider_breakdown?range=week|month|quarter`

- `eval_runs.provider` × `eval_scores` を join し、**provider 別**に `{ provider, model, run_count, metric_key 別
  pass_rate / median score }` を集計 (tenant-scoped、started_at range cutoff)。
- provider bake-off (どの provider が eval で良い結果か) を可視化。
- **scope 明示 (F-005)**: eval_runs は project_id 非保持 → response に `scope: 'tenant'` +
  `project_filter_applied: false` を含め、UI で「tenant-wide eval bake-off」と表示 (project filter が効いている
  ように誤読させない)。
- secret なし、集計のみ。

### frontend (analytics page 本実装)

- `lib/api/eval-analytics.ts` (server fetch、`fetchBackendJson` = cache:no-store + session-bound、fail-closed loader `{ok}`)。
- `lib/domain/kpi-analytics.ts` (client-safe pure: zod schema + value 整形 + state 別表示。**KPI 定義 (unit/
  threshold/direction) は backend response から受ける**、frontend で再定義しない、F-009)。
- analytics page: ① range tab (**7d=week / 30d=month / 90d=quarter**、F-006) ② project filter (現 project / 全体、
  operational series のみに効く) ③ 5 KPI operational time series chart (既存 BarChart 流用、time_to_merge は
  **「proxy (PR open→completed)」と明示**、cost は partial_unmeasured 注記) ④ provider breakdown table
  (**tenant-wide bake-off と明示**、project filter 非適用)。**fixture P0-Exit KPI とは別 section + ラベル明示**で混同防止。
- **state 別表示 (F-008)**: `measured` (値) / `no_denominator` (「対象データ無し」) / `partial_unmeasured`
  (「一部未計測」) / `proxy` (「代理指標」) / sparse 欠落 (bucket 非表示) / 取得失敗 (「取得失敗」) を**全て別文言**で
  区別。0 と null を混同しない。

## 却下案
- fixture KPI の time series 化 (選択肢 1)。
- agent_runs provider column 追加 (選択肢 2)。
- **operational KPI 公式の独自再実装** — ❌ 却下 (Pack 残リスク「KPI 計算ロジック重複」)。既存 metric service
  (`OrchestratorKpiRollupService` / `ApprovalWaitMsMetricService` / `AdoptedArtifactCitationCoverageService` /
  `AgentRunKpiService`) の公式を共有定数/fragment で再利用する。
- time_to_merge を「P0 空」とする (当初案) — ❌ 却下。既存 `time_to_merge_proxy` を proxy として採用 (F-004)。
- real-time streaming / 外部 BI 連携 (Pack 対象外)。

## リスク

- **aggregation 性能 (N+1 / unbounded)**: range cutoff + UTC bucket GROUP BY で bound。median は `percentile_cont`
  単一 query、citation は final-adoption + evidence の集合演算で N+1 回避。**ただし index 現状は source ごとに
  異なる (F-007)**: `approval_requests_idx_requested_at` は有るが、`acceptance_criteria` / `claims` /
  `evidence_items` の `(tenant_id, project_id, created_at)` range index、`eval_runs(tenant_id, started_at)` は
  未整備。**P0 dogfooding 規模では migration なしで許容、データ増加時は follow-up index migration**と明記
  (本 ADR の性能 claim を「現規模で許容」に弱める)。DB-gated で row-count bound smoke を入れる。
- **KPI 公式の drift (F-009)**: operational 集計は既存 metric service と **同一公式 (status set / denominator /
  source / time source)** を共有定数/fragment で揃え、no-DB introspection で `status in (...)` / denominator /
  `date_trunc(...,'UTC')` / active-scope 極性まで assert + 既存 service の定数との drift guard test で固定。
  threshold/unit/direction は backend authority。
- **fixture KPI との混同**: UI で「P0 Exit 判定 (fixture)」/「運用実績 (live)」を別 section + ラベル分離。
- **citation 分母の取り違え (F-001)**: final-adopted artifact を分母にする (raw claims 不可)。draft/non-adopted が
  分母に入らない DB-gated negative test を must-ship。
- **approval の project 取りこぼし (F-003)**: run 未紐付 approval を `unattributed_approval_count` で開示。
- **provider breakdown の scope 誤読 (F-005)**: tenant-wide を response/UI に明示。

## rollback 手順

1. **既存 schema/data に additive** (新 read endpoint 2 本 + frontend、migration なし)。
2. rollback: revert PR (endpoint + frontend 削除)。既存 kpi-rollup / eval-dashboard は不変。

## 実装対象ファイル

- `backend/app/services/eval/kpi_timeseries.py` (bucketed aggregation。既存 metric service の公式 fragment/
  定数を import/共有して time-series 化、独自再実装しない)
- `backend/app/api/eval_analytics.py` (kpi_timeseries + provider_breakdown endpoint、KPI definition authority) + router 登録
- `frontend/lib/domain/kpi-analytics.ts` (pure、backend 定義を受ける) + `frontend/lib/api/eval-analytics.ts` (server fetch)
- `frontend/app/(admin)/eval-dashboard/analytics/page.tsx` (skeleton → 本実装)
- tests: no-DB (SQL introspection + 公式 drift guard + zod) + DB-gated (集計値/state/filter/breakdown) + frontend vitest

## テスト指針 (must-ship)

- **SQL introspection (no-DB)**: 各 KPI query が `tenant_id =` + active-scope (`NOT (EXISTS`) + `date_trunc(...,'UTC')`
  + `GROUP BY` + range cutoff を含む (capturing session、ADR-00039 先例)。
- **公式 drift guard (no-DB、F-009)**: 各 KPI の status set / denominator / time source が既存 metric service
  (`ApprovalWaitMsMetricService` の status set、`OrchestratorKpiRollupService` の completed denominator、
  `AdoptedArtifactCitationCoverageService` の final-adopted) の定数と一致。threshold/unit/direction は backend
  authority (frontend で再定義しない) を assert。
- **citation final-adopted 境界 (DB-gated、F-001)**: draft / non-adopted / 中間 research claim が **分母に入らない**
  (final-adopted artifact のみ)、negative test。
- **cost measured/unmeasured (DB-gated、F-002)**: completed=2 で cost_usd が `0` と `null` の fixture →
  分母=全 completed (2)、`unmeasured_completed_run_count` で未計測を開示、0 と未計測を分離。
- **approval contract (DB-gated、F-003)**: `status in ('approved','rejected')` + `decided_at NOT NULL` +
  `decided_at>=requested_at` のみ集計、`expired/invalidated` / `run_id=null` / stale run_id を除外し
  `unattributed_approval_count` で開示 (project filter 時に静かに落とさない)。
- **time_to_merge proxy (DB-gated/no-DB、F-004)**: `repo_pr_opened_to_agent_run_completed` proxy を使い、
  measurement_kind='proxy'。real merge を使わないことを固定。
- **bucket state enum (DB-gated、F-008)**: `measured` / `no_denominator` (分母 0) / `partial_unmeasured` /
  `proxy` を区別、sparse 欠落と `no_denominator` を別物として返す。
- **project filter + active-scope (DB-gated)**: project_id で当該 project のみ、soft-deleted ticket run を cost
  集計から除外。
- **provider breakdown scope (DB-gated、F-005)**: eval_runs.provider 別、tenant-scoped、`scope='tenant'` +
  `project_filter_applied=false` を返す。
- **range vocab (no-DB、F-006)**: `week=7d / month=30d / quarter=90d` の cutoff、OpenAPI enum が `week|month|quarter`。
- **frontend**: range tab、project filter、state 別文言 (measured/no_denominator/partial_unmeasured/proxy/取得失敗)
  区別、provider table の tenant-wide 明示、text-only、RSC 境界 (next build)、fixture KPI と operational のラベル分離。

## Hard Gates / KPI への trace

- 既存 Hard Gate / KPI に regression なし (read-only additive、fixture KPI 不変)。
- DD-04 Eval Harness の KPI semantics と整合 (operational は同公式・別 data、provider bake-off は eval 拡張)。
