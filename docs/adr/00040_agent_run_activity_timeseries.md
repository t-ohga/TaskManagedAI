---
id: "ADR-00040"
title: "AgentRun アクティビティ時系列エンドポイント (read-only、D-3 / D-4)"
status: "accepted"
date: "2026-06-01"
accepted_at: "2026-06-01"
deciders: ["t-ohga"]
adr_gate_criteria: [3]
related_adr:
  - "ADR-00033 (AgentRun コスト集計 / range cutoff + active-scope の先例)"
  - "ADR-00039 (Dashboard/Runs 集計 / SQL introspection test pattern)"
related_dd:
  - "DD-02 (データモデル / tenant 境界)"
  - "DD-03 (AI オーケストレーション / AgentRun)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00040: AgentRun アクティビティ時系列エンドポイント (read-only、D-3 / D-4)

最終更新: 2026-06-01

## 背景

UI 改善監査の残項目 **D-3 (日次/週次トレンドグラフ)** と **D-4 (コスト推移グラフ、AI 実行)** は
未実装 (ダッシュボードに時系列描画なし)。両者とも `agent_runs` の `created_at` を時間 bucket で
集計するもので、

- D-3: AI 実行のアクティビティ推移 (bucket あたりの run 件数)
- D-4: コスト推移 (bucket あたりの cost_usd 合計)

を 1 つの時系列から得られる。`agent_runs.created_at` は index 済
(`agent_runs_idx_tenant_created_at`)、`cost_usd` も既存カラム → **migration 不要**。
描画は既存 `BarChart` (label + value) を bucket 開始日ラベルで流用でき **新 chart component 不要**。

ADR-00033 (cost_summary) の range cutoff + active-scope、ADR-00039 の SQL introspection test を踏襲する。

## 決定対象

read-only な時系列集計エンドポイントを 1 本新設し、D-3 (run_count) と D-4 (cost_usd) を同時に賄う。
ADR Gate Criteria #3 (API 契約) に該当。

`GET /api/v1/agent_runs/activity_timeseries?bucket=<day|week>&range=<today|week|month|quarter|all>`

## 前提 / 制約

- read-only。mutation なし。migration なし。
- tenant 境界を強制 (`tenant_id` を session から resolve、caller-supplied 禁止)。
- **active-scope**: `soft_deleted_ticket_run_exclusion()` を適用 (cost_summary / list と同経路。
  soft-deleted ticket bound run を時系列から除外、ticket-less run は含む)。
- **bucket は `Literal["day","week"]`** (FastAPI が検証、不正値は 422)。`date_trunc` の第 1 引数は
  **enum 値のみ**を渡し caller 文字列を SQL に直接展開しない (injection 防止)。
- **bucket 境界は UTC 固定 (Codex ADR R2)**: `date_trunc` は timestamptz を DB session TimeZone で
  切り詰めるため、PostgreSQL 16 の 3 引数形 `date_trunc(bucket, created_at, 'UTC')` を使い、session
  TimeZone 非依存の UTC bucket にする。frontend も `bucket_start` を UTC で整形する (両端 UTC 固定)。
- **range cutoff は server 側で算出** (`_cost_summary_cutoff` を再利用、caller-supplied date 禁止)。
- 集計は SQL `date_trunc` + `GROUP BY bucket` + `SUM/COUNT`、unbounded materialize を避ける。
- raw secret / provider key は含まない (件数・cost のみ)。
- cost_usd は bucket 内に measured run (cost_usd not null) が 0 件なら **null** (未計測を $0 と
  誤認させない、ADR-00033 / Codex の cost_summary 教訓を踏襲)。各 bucket に
  `measured_run_count` / `unmeasured_run_count` を併記する。
- **sparse series**: server は active run が 1 件以上ある bucket のみ返す (`run_count=0` bucket を
  生成しない)。frontend は欠損 bucket を 0 補完しない (詳細は採用案)。

## 採用案

```
GET /api/v1/agent_runs/activity_timeseries?bucket=day&range=month

Response (ActivityTimeseriesResponse):
{
  "buckets": [
    { "bucket_start": "2026-05-01T00:00:00Z", "run_count": 12,
      "cost_usd": 3.21, "measured_run_count": 12, "unmeasured_run_count": 0 },
    { "bucket_start": "2026-05-03T00:00:00Z", "run_count": 4,
      "cost_usd": null, "measured_run_count": 0,  "unmeasured_run_count": 4 }
  ],
  "bucket": "day",
  "range": "month"
}
```

- **sparse series (Codex ADR R1-3、固定)**: `bucket_start` は `date_trunc(bucket, created_at)` の昇順で、
  **range cutoff 内に active run が 1 件以上ある bucket のみ**返す。`run_count: 0` の bucket は返さない
  (空 bucket を server が生成しない、`generate_series` 不使用 = `range=all` でも有界)。frontend は
  返ってきた bucket を **そのまま離散バーとして描画し、欠損 bucket を 0 補完しない** (無活動期間は
  バー間の gap として表現)。dense series が必要になれば別 ADR で range_start/range_end + generate_series
  を契約化する。
- `run_count` = bucket 内 active run 件数 (D-3)。
- `cost_usd` = bucket 内 cost_usd 合計、**measured run (cost_usd not null) が 0 件なら null** (D-4)。
  `measured_run_count` / `unmeasured_run_count` を併記し (ADR-00033 と同契約)、frontend は
  **null / unmeasured を 0 として描画しない** (「測定済み 0 件」と「一部測定で合計 0」を区別)。
- frontend は `bucket_start` をラベル、`run_count` / `cost_usd` を value にして既存 `BarChart` で
  2 系列 (アクティビティ / コスト) を描画する。cost 系列は cost_usd=null の bucket を value=0 にせず
  「未計測」として除外 or 別表現する。

## 却下案

- D-3 と D-4 を別エンドポイントに分割: 同一 `agent_runs` 時系列を 2 回 query するのは非効率。1 endpoint に統合。
- frontend で `/agent_runs?limit=N` を取得し client 側で bucket 集計: limit 上限で母数不正確
  (ADR-00033 / ADR-00039 と同じ反 pattern)。却下。
- 新 LineChart component の追加: 既存 BarChart で時系列を表現でき、scope を最小化。却下。
- ticket 時系列を含める: D-3/D-4 は AI 実行が対象。ticket 時系列は別途必要になれば別 ADR。

## リスク

- LOW。read-only、既存カラム、tenant 境界 + active-scope 強制、migration なし。
- `date_trunc` の bucket 引数を Literal 検証し SQL injection を防ぐ。
- 性能: `agent_runs(tenant_id, created_at)` index 済。range cutoff で scope 限定。
- rollback は endpoint + schema の削除で完結 (DB 変更なし)。

## rollback 手順

- ルート定義 (`agent_runs.py`) と response schema の削除で revert 完結。DB 変更なし。
- frontend は trend 描画を削除 (1 commit revert)。

## 実装対象ファイル

- `backend/app/api/agent_runs.py`: `activity_timeseries` endpoint + `ActivityTimeseriesResponse` /
  `ActivityBucket` schema。**`/{run_id}` より前** (cost_summary / role_facet と同じ静的 route block)。
- `tests/api/test_agent_runs_activity_timeseries.py`: route 登録 + route ordering + schema no-secret +
  bucket 422 + SQL introspection (tenant / active-scope / date_trunc / GROUP BY)。
- `frontend/lib/api/agent-runs.ts` (または dashboard.ts): `fetchActivityTimeseries`。
- `frontend/app/(admin)/dashboard/page.tsx`: BarChart で run 活動 + コスト推移を描画 (取得失敗は
  ADR-00039 R1-2 と同じ ok/error degraded 表示)。

## テスト指針

- route 登録 + `/{run_id}` より前の route ordering。
- bucket=day/week は 200、`bucket=hour` 等は 422。
- response schema が bucket_start / run_count / cost_usd / measured_run_count / unmeasured_run_count
  のみ (raw secret なし、`assert_no_raw_secret` 相当)。
- **SQL introspection (Codex ADR R1-1、強化)**: compile SQL に次をすべて固定で含むこと:
  - tenant 境界 (`agent_runs.tenant_id =`)
  - **active-scope の極性と相関**: `NOT (EXISTS` (NOT EXISTS の極性) +
    `tickets.tenant_id = agent_runs.tenant_id` + `tickets.project_id = agent_runs.project_id` +
    `tickets.id = agent_runs.ticket_id` + その内側に `tickets.deleted_at IS NOT NULL`
    (EXISTS / 非相関 JOIN / 極性反転を catch する)
  - `date_trunc(` による bucket 化 + `GROUP BY` (bucket 式)
- **active-scope DB negative (CI Compose)**: soft-deleted ticket bound run は除外、ticket-less run は
  含む、restore 後は再集計される (host dev では test-password 不一致で実行不可、CI Compose で実行)。
- **cost measurement 契約 (Codex ADR R1-2)**: mixed bucket / measured-zero / all-unmeasured の各 case で
  `cost_usd` の null (measured 0) と 0 (cost=0 の measured run) を区別し、`measured_run_count` /
  `unmeasured_run_count` が整合すること。frontend が null/unmeasured を value=0 に丸めないこと。
- **sparse 契約 (Codex ADR R1-3)**: server は `run_count=0` の bucket を返さない (sparse)。
  frontend が欠損 bucket を 0 補完しないこと。
- 取得失敗時に dashboard が時系列を「空/0」でなく degraded 表示にすること (ADR-00039 R1-2 踏襲)。
