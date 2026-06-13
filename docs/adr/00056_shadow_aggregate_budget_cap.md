---
id: "ADR-00056"
title: "Shadow Aggregate Budget Cap — per-tenant rolling-window で shadow 総コストを上限化"
status: "proposed"
date: "2026-06-13"
authors:
  - "Claude (autonomous, user 承認 scope: shadow 後続増分)"
related_sprints:
  - "SP-037_shadow_aggregate_budget_cap"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #2 (DB schema: partial index migration) + #4 (AI エージェント権限: shadow コスト境界拡張) + #8 (DB advisory locking) に該当。ADR-00055 (Shadow Mode Run) の budget 設計を **per-run cap → aggregate cap** へ拡張する判断を記録する。

最終更新: 2026-06-13

> **status: proposed (deferred、2026-06-13 user 判断)**。plan-review R1 で aggregate cap は migration + DB advisory locking + event-based 集計を要する高リスク増分と判明し、かつ解く問題 (cross-run concurrency) は **runtime worker driver 不在の現状では未発生**。実装は **runtime driver 増分と同時** へ defer。本 ADR は plan-review R1 (F1-F4) 反映済の **実装 ready な設計** として保存し、runtime 統合時に plan-review R2 → accepted → 実装する。

## 背景

- 決定対象: SP-029 (ADR-00055) で実装した shadow **per-run** cap (`shadow_run_max_cost_usd` / `shadow_run_max_total_tokens`) は **1 shadow run** の cost/token を上限化するが、**多数の shadow run を手動作成すると aggregate cost が無制限に積み上がる** (SP-029 R3 residual + R12 で defer 済)。本 ADR は per-tenant の aggregate shadow cost を rolling window で上限化する。
- 関連 Sprint: SP-037 (shadow 後続増分)。SP-029 (P0.1 foundational) は完了・merged。
- 前提 / 制約:
  - SP-029 の不変条件を一切壊さない: 16 status 不変、production budget 非擾乱 (shadow cost を production accumulator 非加算)、shadow 副作用隔離、KPI 除外。
  - aggregate cap は **shadow run のみ** に適用 (production budget は別系統で不変)。
  - additive のみ (DB schema 変更なし)。既存 `agent_runs_idx_tenant_created_at` (tenant_id, created_at) index を aggregate 集計に再利用 → **migration 不要**。
  - backend-only foundational increment (SP-029 と同様、runtime driver 不在で未到達だが foundational plumbing として先行整備)。
  - scope: per-tenant aggregate cost cap のみ。per-project 粒度 / token aggregate / auto-trigger / dashboard は後続へ defer。

## 選択肢

1. **config-based per-tenant rolling-window cap (採用)**: `shadow_aggregate_max_cost_usd` + `shadow_aggregate_window_hours` を settings に追加し、shadow budget choke point で `SUM(cost_usd) WHERE tenant_id=:t AND run_mode='shadow' AND created_at >= now()-window` を集計して上限判定。per-run cap (config-based) と一貫。
2. **Budget table-based (却下)**: 新 Budget level (`shadow_aggregate`) を Budget table に追加。重量級 (schema/migration) + per-run cap が config-based なので不整合。
3. **all-time aggregate (却下)**: window なし。一度上限到達で shadow が **永久に** 無効化 (reset 手段なし) → 試走機能が使えなくなり過剰制限。

## 採用案

選択肢 1 + plan-review R1 (F1-F4) 反映。

- **config** (`backend/app/config.py`):
  - `shadow_aggregate_max_cost_usd: Decimal` (default `Decimal("10.00")`, gt=0) — per-tenant rolling-window 総 shadow cost 上限。
  - `shadow_aggregate_window_hours: int` (default `24`, gt=0) — rolling window 幅 (時間)。
- **集計 source (plan-review F3: cost-aligned timestamp)**: run.created_at ではなく **`provider_responded` event の cost × event.created_at** を集計源にする。`SUM(provider_responded event cost) WHERE event.tenant_id=:t AND run.run_mode='shadow' AND event.created_at >= :window_start`。理由: cost は run 作成時でなく provider call (usage 記録) 時に発生するため、長時間 queued/running/retry の run でも「コスト発生時刻」で window 判定できる (run.created_at だと古い run のコストが window から落ちる)。event payload の cost 抽出は KPI (`_PROVIDER_COST_EXPR` / orchestrator_kpi_rollup) と同じ正規表現を再利用 (drift guard)。
- **prospective projection (plan-review F1)**: preflight は既存 aggregate だけでなく **今回 call の projected cost を加えて** 判定する。`aggregate_window + projected_call_usd > cap` なら provider 課金前に block (projected_call_usd は SP-029 の per-run preflight と同じ `(estimated_input_tokens + max_tokens) × shadow_run_max_usd_per_token`)。post-execution は保険として `aggregate_window > cap` を残す。
- **cross-run 排他 (plan-review F2)**: aggregate は本質的に cross-run のため、SUM 直読みでは concurrent shadow run が同じ余力を二重消費する。**`pg_advisory_xact_lock(hashtext('shadow_aggregate'), tenant_id)` を aggregate preflight + record の同一 transaction 内で取得** し、tenant 単位で aggregate 評価〜cost 記録を直列化する (lease は run 単位 single-flight だが aggregate は cross-run なので別途必要)。advisory lock は transaction 終了で自動解放。
- **enforcement** (`backend/app/services/providers/usage_logger.py` の shadow budget path 拡張):
  - aggregate helper `_shadow_aggregate_cost(session, *, tenant_id, window_start) -> Decimal` (上記 event-based SUM)。
  - **preflight** (`preflight_shadow_budget` / `preflight_shadow_request_tokens`): advisory lock 取得 → `aggregate + projected_call_usd > cap` で block (budget_level `shadow_aggregate_cap`)。
  - **post-execution** (`_evaluate_shadow_block`): advisory lock 取得 → cost 加算後 `aggregate > cap` で block。
  - 評価順: kill switch → per-run USD → per-run token → **aggregate USD** (広い緊急停止から)。
  - production budget は一切読まない・誘発しない (§SP-029 非擾乱 維持)。
- **index (plan-review F4)**: production run 多数 tenant で `(tenant_id, created_at)` index が production 行を引きずらないよう、**partial index** `agent_run_events (tenant_id, created_at) WHERE event_type='provider_responded'` を additive migration で追加する (event-based 集計の range scan を provider_responded のみに限定)。→ 本 ADR は migration を伴う (ADR Gate #2/#8、rollback は index drop = cleanup-only)。

## 却下案

- Budget table-based (選択肢 2): config-based per-run cap との不整合 + schema 重量。
- all-time aggregate (選択肢 3): reset 不能で過剰制限。
- per-call ごとの aggregate キャッシュ: 整合複雑、shadow run 少数で SUM 直読みで十分。

## リスク

- aggregate event SUM が provider call ごとに走る perf コスト → partial index `agent_run_events WHERE event_type='provider_responded'` で provider_responded 行のみ range scan、shadow run 少数 (driver 未公開) で許容。
- advisory lock の contention: tenant 単位で aggregate 評価〜record を直列化するため、同 tenant の concurrent shadow run は順次化 (production には別 lock key で無影響)。shadow は試走 = 高 throughput 不要なので許容。lock は xact 終了で自動解放 (deadlock 回避: 単一 lock key、ネストなし)。
- rolling window 境界 (window 端で古い高コスト event が抜けて cap 余裕が復活) → rolling の仕様として明示 (calendar-day でなく rolling-N-hours)。
- not user-reachable (driver 不在) → foundational plumbing。SP-029 と同じ位置付けで、runtime 統合時に有効化。
- per-run / aggregate の二重評価で block reason が分かりにくい → audit payload に `budget_level` (`shadow_run_cap` / `shadow_run_token_cap` / `shadow_request_usd` / `shadow_aggregate_cap`) を明示。
- event-based 集計の cost 抽出が KPI の `_PROVIDER_COST_EXPR` と drift → drift guard test で正規表現一致を固定。

## rollback 手順

- `shadow_aggregate_max_cost_usd` を十分大きく設定 (実質無効化) → 即時 rollback (config のみ、deploy 不要)。
- code rollback: `_shadow_aggregate_cost` + aggregate 判定 + advisory lock を revert (per-run cap は維持)。
- migration rollback: partial index を drop (cleanup-only、deploy-aware = 稼働中 app に即時 drop しない、SP-029 §9 と同方針)。
- shadow 機能自体は `shadow_mode_enabled=false` で全停止可 (SP-029 の flag、上位 gate)。

## 実装対象ファイル

- `backend/app/config.py` (2 settings 追加)
- `migrations/versions/00NN_shadow_aggregate_event_index.py` (partial index、additive、down=drop index)
- `backend/app/services/providers/usage_logger.py` (`_shadow_aggregate_cost` event-based SUM + advisory lock + `_evaluate_shadow_block` / preflight に aggregate prospective 評価)
- `tests/runtime/test_shadow_run_cap.py` + `tests/runtime/test_shadow_mode_db.py` (aggregate cap unit + DB-gated: window 内外 / projection / concurrent / 非擾乱 / cost-aligned / migration 可逆性)

## テスト指針

- unit: aggregate 集計 helper を monkeypatch し、window 内 aggregate >= cap で preflight block / > cap で post block / 未満で pass。
- DB-gated: 同一 tenant に複数 shadow completed run を seed (cost 合計が cap 超過 / 未満)、preflight + record_provider_usage で aggregate block を検証。window 外 (created_at 古い) run は集計対象外。production run は aggregate に混入しない。
- 非擾乱: aggregate 評価が production budget を読まない (BudgetGuard 非呼び出し)。
