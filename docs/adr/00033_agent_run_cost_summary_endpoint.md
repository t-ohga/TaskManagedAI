---
id: "ADR-00033"
title: "AgentRun コスト集計エンドポイント (read-only)"
status: "accepted"
date: "2026-05-28"
deciders: ["t-ohga"]
adr_gate_criteria: [3]
---

# ADR-00033: AgentRun コスト集計エンドポイント (read-only)

## 背景

UI 改善計画 D-4 (コスト推移グラフ) を実装するため、AgentRun の
`cost_usd` / `tokens_input` / `tokens_output` を集計する read-only エンドポイントが必要。
これらのフィールドは `agent_runs` テーブルに既存 (migration 不要)。

## 決定対象

`GET /api/v1/agent_runs/cost_summary` を新規追加する。
ADR Gate Criteria #3 (API 契約 / event schema) に該当。

## 前提 / 制約

- read-only。mutation なし。
- tenant 境界を強制 (`tenant_id` を session から resolve、caller-supplied 禁止)。
- 既存 `list_agent_runs_endpoint` と同じ actor/tenant dependency pattern。
- raw secret / provider key は含まない (cost_usd と token 数のみ)。
- 集計は SQL `SUM` / `COUNT` で実行、unbounded SELECT を避ける。

## 選択肢

1. **新規 read-only エンドポイント (採用)**: `GET /cost_summary` で SQL 集計を返す。
2. frontend で `/api/v1/agent_runs?limit=200` を取得して集計: limit 上限で不正確になる (既存 D-1 で同問題が Codex に指摘済み)。却下。
3. 既存 KPI rollup に統合: cost は AC-KPI-05 と別 dimension で混乱を招く。却下。

## 採用案

```
GET /api/v1/agent_runs/cost_summary?range=<today|week|month|quarter|all>

Response (CostSummaryResponse):
{
  "total_cost_usd": number | null,
  "total_tokens_input": number,
  "total_tokens_output": number,
  "run_count": number,
  "by_status": [{ "status": string, "cost_usd": number, "run_count": number }],
  "range": string
}
```

- `range` は created_at の cutoff フィルタ (server 側で算出、caller-supplied date 禁止)。
- 集計は `func.sum` / `func.count` + `group_by(status)`。

## 却下案

- frontend 集計 (選択肢 2): limit 上限で母数が不正確。
- mutation を伴う cost 記録: cost は AgentRun lifecycle で記録済み、本エンドポイントは read-only。

## リスク

- LOW。read-only、既存フィールド、tenant 境界強制、migration なし。
- 集計クエリの性能: `agent_runs(tenant_id, created_at)` index が既存。range フィルタで scope 限定。

## rollback 手順

- エンドポイント追加のみ。revert はルート定義と schema の削除で完結。DB 変更なし。

## 実装対象ファイル

- `backend/app/api/agent_runs.py`: `cost_summary` endpoint + `CostSummaryResponse` schema
- `backend/tests/api/test_agent_runs_cost_summary.py`: tenant 境界 + 集計 + range negative test

## テスト指針

- tenant 越境 negative (別 tenant の cost が混入しないこと)
- range フィルタ (today/week/month/quarter/all) の cutoff 正確性
- cost_usd=null の run が SUM で無視されること
- raw secret が response に含まれないこと (assert_no_raw_secret)
