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
  - additive のみ (破壊的変更なし)。**plan-review R1 F4 + App F4 で partial index migration が in scope** に変更 (当初「migration 不要」前提は撤回、§採用案 index 参照)。
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
- **prospective projection (plan-review F1 / App F7)**: preflight は既存 aggregate だけでなく **今回 call の projected cost を加えて** 判定する (`aggregate_window + projected_call_usd > cap` で課金前 block、post は保険で `aggregate_window > cap`)。projected_call_usd は `(estimated_input_tokens + max_tokens) × shadow_run_max_usd_per_token`。これらは `preflight_shadow_budget` の signature に無いため、**aggregate prospective 評価は `preflight_shadow_request_tokens` (request を持つ) に scope する** (App F7、`preflight_shadow_budget` には既存 aggregate のみの保険 check を置く程度)。
- **cross-run 排他 (plan-review F2 / App F6)**: aggregate は cross-run のため SUM 直読みでは concurrent shadow run が同じ余力を二重消費する。**advisory xact lock を aggregate 評価〜record の同一 transaction 内で取得**し tenant 単位直列化 (lease は run 単位 single-flight、aggregate は cross-run で別途)。**lock key は単一 64-bit (`pg_advisory_xact_lock(:bigint_key)`、`bigint_key = hash('shadow_aggregate', tenant_id)`) を使う** — 2-arg form (int32×2) は `tenants.id` が BigInteger のため truncation する (App F6)。lock は xact 終了で自動解放。
- **enforcement** (`backend/app/services/providers/usage_logger.py` の shadow budget path 拡張):
  - aggregate helper `_shadow_aggregate_cost(session, *, tenant_id, window_start) -> Decimal`。
  - aggregate prospective 評価を `preflight_shadow_request_tokens`、post 評価を `_evaluate_shadow_block` に追加 (budget_level `shadow_aggregate_cap`)。評価順: kill switch → per-run USD → per-run token → **aggregate USD**。
  - production budget は一切読まない・誘発しない (§SP-029 非擾乱 維持)。

## 実装時の未解決設計事項 (Codex App #349 指摘、実装着手 = runtime driver 増分時に解決)

- **(App F3) provider_responded event の cost 可用性 + ordering**: 現 `_provider_event_payload()` は metadata-only で **cost を含まない**、かつ `record_provider_usage()` は provider_responded transition append **より前** に走る。よって event-based 集計 (`SUM(provider_responded event cost)`) は実 provider call で 0/null を読み、直近 call の spend を post-check に含められない。実装時に **(a) provider_responded event payload に cost を追加** (event 契約変更 + redaction 確認) し append 順を aggregate check より前にする、**または (b) run.cost_usd (token-floored accumulator) を集計源にし created_at でなく `updated_at` (最終 cost 更新時刻) で window 判定** (event 変更回避だが timestamp 近似) のいずれかを選ぶ。cost-aligned 正確性 (F3) と実装コストの trade-off を plan-review R2 で決定。
- **(App F4) index の shadow 選択性**: partial index `WHERE event_type='provider_responded'` は **production の provider_responded も含む** ため、production traffic 多数 tenant では aggregate path が production event を scan する (migration の目的「production 行を引きずらない」を満たさない)。実装時に **shadow-selective access path** (indexed shadow runs から駆動 / event に run_mode を denormalize+index / 上記 (b) の run.cost_usd 集計なら `agent_runs` の shadow partial index) を選ぶ。
- **(App F1/F2 ADR §前提整合)**: migration in scope (§前提 撤回済)、advisory lock 必須 (concurrency)。

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
- DB-gated: 同一 tenant に複数 shadow run + provider_responded event を seed (cost 合計が cap 超過 / 未満)、preflight + record_provider_usage で aggregate block を検証。**window 判定は cost 発生時刻 (event.created_at) 基準** (App F2): 古い run の **window 内 event** は集計対象、新しい run の **window 外 event** は対象外、を両方 test する (run.created_at で aging しない)。production run の cost は aggregate に混入しない。
- 非擾乱: aggregate 評価が production budget を読まない (BudgetGuard 非呼び出し)。
