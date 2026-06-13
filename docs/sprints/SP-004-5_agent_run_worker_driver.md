---
id: "SP-004-5_agent_run_worker_driver"
type: "heavy"
status: "draft"
sprint_no: 4
created_at: "2026-06-13"
updated_at: "2026-06-13"
target_days: 2
max_days: 4
planned_adr_refs:
  - "[ADR-00057](../adr/00057_agent_run_worker_driver.md)"
related_sprints:
  - "SP-004_agent_runtime"
  - "SP-005_provider_adapter"
  - "SP-029_shadow_mode"
risks:
  - "atomic claim 不在で concurrent worker / 二重 enqueue が同一 run 二重駆動 (F3)"
  - "cancel entrypoint 不統一 (MCP bridge_run_cancel が event/signal bypass、R2-F2)"
  - "enqueue 失敗 → silent orphan queued run (F2/R2-F1)"
  - "ContextSnapshot/ProviderRequest provenance が placeholder 化 (F4)"
  - "non-terminal closure 取り違え (provider_incomplete→repair_exhausted は不許可、R2-F3)"
  - "state machine additive edge が 16 status/event exact set を壊す (R2-F1/F2)"
  - "Mock provider 行が Compliance Matrix 未登録で deny"
  - "production run を誤 enqueue (shadow-only 漏れ)"
  - "bulk/superintendent cancel (1686) の event-append 統一 follow-up"
---

## 目的

SP-004 (agent_runtime、completed) が「Sprint 4.5」へ defer した **arq worker driver** を実装し、`queued` shadow AgentRun を既存 orchestrator step で end-to-end (queued → completed) に駆動する。これにより shadow run が初めて **実際に実行可能** になり、SP-029 shadow mode + 後続増分 (SP-037 aggregate cap、A/B、bake-off) の前提を満たす。

## 背景

現状 worker は `noop_task` のみ、run_create は `queued` run を作るだけで誰も駆動しない (SP-004 §残リスク「worker は Sprint 4.5 で詳細化」)。本 Sprint は **shadow-first foundational slice** として Mock provider で shadow run を駆動。production runtime (post-validation pipeline + real provider) は後続。詳細は ADR-00057。

## 対象外

- production run の駆動 (post-validation pipeline = policy_lint/diff_ready/approval/runner/repo 未実装、SP-007/008 範囲)
- real provider (OpenAI/Anthropic/Gemini) 駆動 (Mock 固定)
- provider mid-call kill / Redis per-run channel transport 整合 (step 境界 DB-status cancel のみ in scope、mid-call interruption は後続)
- orphan の **transient 自動再試行** sweep/outbox (本 slice は enqueue 失敗を fail-closed `failed` で silent orphan 解消、自動再試行のみ後続。F5 closure は in scope)
- **bulk/superintendent cancel (api_bridge.py:1686) の event-append 統一** (R2-F2 派生 follow-up、driver は DB status で stop するため driver 動作には非影響、AgentRunEvent invariant 完全 close は別作業)

## 設計判断 (plan-review R1 F1-F5 + R2 F1-F3 反映、実コード照合済)

- arq task `execute_agent_run` + **shadow-only enqueue** (ADR-00057 §採用案)。全 run enqueue / 同期駆動は却下。
- 既存 orchestrator step / state machine / ContextSnapshot / BudgetGuard / Compliance Gate / SecretBroker を再利用 (再実装なし)。
- **atomic claim (F3)**: enqueue は run commit 後、task は `UPDATE agent_runs SET status='gathering_context' WHERE tenant_id=:t AND id=:r AND run_mode='shadow' AND status='queued' RETURNING *` で **claim**。**0 rows = benign loser → no-op return (failed にしない)**。concurrent worker / 二重 enqueue / production 誤 enqueue を single-flight + run_mode gate で防御。SP-029/SP-037 の concurrency 前提を満たす。
- **provenance binding (F4)**: ProviderRequest を先に構築 → ContextSnapshot input に exact fingerprint 格納 (placeholder 禁止)。snapshot/request/result fingerprint + matrix version + Artifact payload_data_class の相互一致を test 固定。
- **non-terminal closure 分離 (F5 + R2-F3)**: `provider_incomplete` と `validation_failed` は許可遷移が異なる (`state_machine.py:35-36` 照合)。`validation_failed` → `execute_repair_decision_step` → `repair_exhausted`。`provider_incomplete` → bounded retry `running`、上限/retry 不能は `failed` (**`provider_incomplete -> repair_exhausted` は不許可**)。
- **cancellation = DB-status 検知 + entrypoint 統一 (F1 + R2-F2)**: `cancel_agent_run` は DB-first (cancelled 遷移 commit → best-effort signal) のため driver は **step 境界で run.status 再読**して cancelled 検知 → graceful stop (Redis transport 非依存)。MCP `bridge_run_cancel` (現状 `run.status="cancelled"` 直接 set、`run_cancelled` event 非 append = invariant 破壊、api_bridge.py:653) を `cancel_agent_run` 経由に統一 + actor_id plumbing。
- **state machine additive 拡張 (R2-F1/F2 由来、CRITICAL invariant、Python+test のみ migration 不要)**: `queued->failed` (enqueue 失敗補償) + `{queued, gathering_context, generated_artifact, schema_validated}->cancelled` (cancel 統一 regress 防止) を additive 追加。16 status / event exact set 不変。
- **enqueue 回復 = fail-closed (F2 + R2-F1)**: enqueue 失敗は呑まず **補償遷移で run `failed`** (error_code=enqueue_dispatch_failed) → silent orphan 禁止。「log + queued 残置」は R2-F1 で recovery でないと判明し不採用。自動 sweeper/outbox (transient 再試行) のみ後続 defer。
- error → failed、blocked → stop (resume 待ち、driver 再駆動しない)。concurrent status-change miss は failed でなく no-op (F3 benign)。

## 実装チケット / タスク一覧

1. `services/agent_runtime/state_machine.py` (additive、先に): `ALLOWED_TRANSITIONS` + `EVENT_TYPE_FOR_TRANSITION` に `queued->failed`(run_failed) + `{queued,gathering_context,generated_artifact,schema_validated}->cancelled`(run_cancelled) 追加 + `cancel.py` `_CANCELABLE_STATES` 拡張。state machine test の `EXPECTED_*` 整合 (5+ source)。
2. `workers/agent_run_driver.py`: `execute_agent_run(ctx, *, run_id, tenant_id)` — gate verify → **atomic claim (F3、`UPDATE...RETURNING`、claim-miss=no-op)** + 同一 tx で context_gathered event + ContextSnapshot(F4 exact fingerprint) → running → execute_provider_step(Mock) → execute_validation_step → execute_shadow_completion_step → **non-terminal 分離 closure (F5+R2-F3: validation_failed→repair→repair_exhausted / provider_incomplete→running or failed)** → **step 境界 DB-status cancel 検知 (F1+R2-F2)** → error→failed。
3. `workers/main.py`: `functions` に `with_active_registry_gate(execute_agent_run)` 追加。
4. `mcp/api_bridge.py` `bridge_run_create`: shadow run commit 後に enqueue (production は非 enqueue)。**enqueue 失敗 → 補償遷移で run failed (error_code=enqueue_dispatch_failed、R2-F1 fail-closed)**。
5. **cancel entrypoint 統一 (F1+R2-F2)**: `mcp/api_bridge.py` `bridge_run_cancel` を `cancel_agent_run` 経由に統一 (run_cancelled event + signal) + `mcp/server.py` `run_cancel` に actor_id plumbing。
6. **provenance binding (F4)**: ProviderRequest を先に構築する helper + ContextSnapshot input に exact fingerprint 格納 (10 列 driver default)、Artifact (mock structured output)、ProviderRequest (shadow payload_data_class)。
7. test: DB-gated end-to-end 駆動 / **atomic claim concurrent (benign-loser-not-failed、F3)** / **enqueue 失敗→failed (silent orphan なし、R2-F1)** / production 非駆動・非 enqueue / blocked stop / **cancel parity (REST + MCP 両方で run_cancelled event + driver stop、R2-F2)** / transient state cancel (新 edge) / **non-terminal 分離 (validation_failed→repair_exhausted、provider_incomplete→failed、repair_exhausted に行かない assert、R2-F3)** / **provenance fingerprint 一致 (F4)** / state machine 新 edge の EXPECTED_* / ContextSnapshot+Artifact+event timeline 検証。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer |
|---|---|---|
| shadow run end-to-end 駆動 (queued→completed、Mock) | ✓ | |
| shadow-only enqueue (production 非 enqueue) | ✓ | |
| **atomic claim single-flight (F3、claim-miss=no-op、concurrent 二重駆動防止)** | ✓ | |
| **provenance binding exact fingerprint (F4、placeholder 禁止)** | ✓ | |
| **DB-status cooperative cancel + entrypoint 統一 (F1+R2-F2、REST+MCP parity)** | ✓ | |
| **state machine additive edge (queued→failed / transient→cancelled、R2-F1/F2)** | ✓ | |
| **non-terminal closure 分離 (validation_failed→repair_exhausted / provider_incomplete→failed、F5+R2-F3)** | ✓ | |
| **enqueue 失敗 fail-closed (補償 failed、silent orphan 禁止、R2-F1)** | ✓ | |
| error→failed / blocked→stop | ✓ | |
| ContextSnapshot input + Artifact + event timeline | ✓ | |
| provider mid-call kill | | ✓ |
| orphan の transient 自動 sweeper / outbox (R2-F1 fail-closed 済、自動再試行のみ defer) | | ✓ |
| bulk/superintendent cancel の event-append 統一 (api_bridge.py:1686、R2-F2 派生 follow-up) | | ✓ |
| production runtime / real provider | | ✓ |
| 実 prompt pack 配線 (driver default lock の精緻化) | | ✓ |

## 受け入れ条件

- [ ] shadow run を作成 → `execute_agent_run` で `completed` 到達、event timeline (context_gathered → provider_requested → provider_responded/artifact_generated → schema_validated → run_completed) + ContextSnapshot input (10 列) + Artifact 生成を検証。
- [ ] **(F3) atomic claim**: 同一 shadow run へ concurrent に 2 回駆動 → 1 個だけ claim 成功、他は no-op (status 不変、failed にならない)。queued でない run も no-op。
- [ ] production run を `execute_agent_run` に渡すと no-op (atomic claim の run_mode='shadow' 条件で claim-miss)。
- [ ] **(F4) provenance**: ContextSnapshot input fingerprint == ProviderRequest fingerprint == provider result fingerprint、matrix version 一致、Artifact payload_data_class 一致 (placeholder = test fail)。
- [ ] **(F5+R2-F3) non-terminal 分離**: Mock forced `validation_failed` → repair loop → `repair_exhausted` terminal。Mock forced `provider_incomplete` → bounded retry `running` → 上限で `failed` (**`repair_exhausted` に行かないことを assert**)。refusal → `provider_refused`。unsupported_schema/schema_mismatch も close。
- [ ] **(F1+R2-F2) cancel parity**: REST `cancel_agent_run` と MCP `run_cancel` の **両方**で `run_cancelled` event append + driver が step 境界 DB-status 検知で stop。queued / transient state からの cancel も新 edge で `run_cancelled` 付き cancelled 到達。
- [ ] **(R2-F1) enqueue fail-closed**: enqueue 失敗 (redis 例外) で補償遷移 run `failed` (error_code=enqueue_dispatch_failed)。**queued 残置 = silent orphan を作らないことを assert**。
- [ ] **(R2-F1/F2) state machine 新 edge**: `queued->failed` / `{queued,gathering_context,generated_artifact,schema_validated}->cancelled` が allowed + 正しい event、16 status / event exact set 不変 (EXPECTED_* 整合)。
- [ ] provider blocked (budget/usage) で run blocked、driver 再駆動しない。
- [ ] 例外で run `failed` + error_code (raw secret なし)。concurrent status-change miss は failed でなく no-op。
- [ ] shadow run_create で enqueue、production run_create で非 enqueue (mock redis 検証)。
- [ ] SP-029 不変条件 (shadow budget/guard/KPI 除外/16 status 不変/副作用隔離) を駆動経路で保持。

## 検証手順

```bash
uv run ruff check backend tests && uv run mypy backend
TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_agent_run_driver.py tests/ -q
```

## レビュー観点

- **atomic claim (F3)** の single-flight 正当性: claim-miss が no-op (failed 誤分類なし)、concurrent 二重駆動なし、run_mode='shadow' gate で production 非駆動。
- shadow-only enqueue + atomic claim run_mode gate の二重防御 (production 誤駆動なし)。
- 駆動経路が SP-029 shadow budget/guard/KPI 除外/state machine confine/16 status 不変を保持するか。
- **provenance (F4)**: ContextSnapshot 10 列 / Artifact / ProviderRequest の fingerprint・matrix version・payload_data_class 相互一致 (placeholder bypass なし、Compliance Gate / preflight bypass なし)。
- **non-terminal 分離 (F5+R2-F3)**: validation_failed→repair_exhausted、provider_incomplete→running/failed (repair_exhausted へ行かない)、refusal→provider_refused を許可遷移通りに close (宙吊りなし)。
- **cancel 統一 (F1+R2-F2)**: REST + MCP 両 entrypoint で `run_cancelled` event append + driver DB-status stop。bulk cancel (1686) follow-up が driver 動作を壊さないこと。
- **state machine additive edge (R2-F1/F2)**: queued→failed / transient→cancelled が 16 status / event exact set を壊さず EXPECTED_* 整合。
- error/blocked handling + **enqueue fail-closed (R2-F1、silent orphan なし)**。

## 残リスク

- Mock 固定 (real provider 駆動は後続)。
- ContextSnapshot driver default 値 (実 prompt pack 配線は後続)。
- enqueue transient 失敗の自動再試行 (fail-closed failed までは in scope、自動 sweeper/outbox は後続)。
- cancel step 境界のみ (mid-call kill 後続)。
- bulk/superintendent cancel (api_bridge.py:1686) の event-append 統一は follow-up (driver は DB status で stop するため非影響だが AgentRunEvent invariant 完全 close は別作業)。

## 次スプリント候補

- production runtime driver (post-validation pipeline + real provider、SP-007/008 連動)。
- repair retry auto-loop / orphan sweep / provider mid-call kill。
- SP-037 aggregate cap 実装 (driver で concurrency 発生後)。
- shadow A/B 比較 / bake-off / frontend run_mode 表示。

## 関連 ADR

- ADR-00057 (本 Sprint で proposed → accepted 昇格予定)。
- ADR-00004 (AgentRun state machine、駆動が従う正本)。

## Review

(2026-06-13 起票) SP-029 完了 + SP-037 planning defer を受け、推奨方向 (runtime driver) として SP-004 defer 分の worker driver を shadow-first foundational slice で draft 起票。ADR-00057 proposed。次: codex-plan-review → (scope 検証) → ADR accepted → 実装。

(2026-06-13 plan-review R1) codex plan-review で **3 HIGH + 2 MEDIUM** の設計欠陥を実装前に捕捉、全 adopt (実コード照合済の正当な欠陥):
- **F1 (HIGH) cancel transport 不整合**: `cancel.py` は per-run channel `cancel:run:{run_id}` に publish するが worker は `worker_cancel_channel` のみ subscribe → cancel が届かない。transport を整合 (must_ship)。
- **F2 (HIGH) enqueue 失敗 → orphan queued run**: enqueue を呑むと run が永久 queued。log + 残置 + atomic claim 再駆動可能化 (must_ship)、自動 sweeper は後続 defer。
- **F3 (HIGH) status guard が concurrency 不足**: 「status='queued' を確認してから駆動」では concurrent worker / 二重 enqueue で二重駆動。`UPDATE...RETURNING` atomic claim で single-flight、**claim-miss=benign loser=no-op (failed 誤分類しない)** (must_ship)。**この atomic claim が SP-029/SP-037 で「driver の single-flight が cover する」と reasoned-defer した per-run concurrency 前提を実際に満たす根拠**。
- **F4 (MEDIUM) provenance binding placeholder 化**: ContextSnapshot/ProviderRequest を placeholder fingerprint で構築しうる。ProviderRequest 先行構築 + exact fingerprint 格納 + 相互一致 test (must_ship)。
- **F5 (MEDIUM) non-terminal 未 close**: `provider_incomplete`/`validation_failed` 放置で宙吊り。execute_repair_decision_step を driver loop に含め repair_exhausted で close (must_ship、当初 defer 予定を昇格)。

**scope 再評価 (R1)**: plan-review R1 により本 slice は当初想定 (queued run を step に流すだけの薄い driver) より **substantial な core-runtime piece** と判明 — atomic claim + cancel transport 整合 + enqueue 回復 + provenance binding + non-terminal handling、加えて ADR Gate Criteria #4 (AI 実行 end-to-end 駆動権限) 直結のため実装後 full adversarial loop (findings_zero、codex-usage-policy §14.1) が必要。

(2026-06-13 plan-review R2、**no-ship**) R1 fix を反映した plan を再レビューし **3 HIGH を追加捕捉、全 adopt** (実コード照合済):
- **R2-F1 (HIGH) enqueue「log + queued 残置」は recovery でない**: 再駆動主体が本 Sprint に無く、atomic claim 可能なだけで誰も claim しない = 永続未実行の silent orphan。→ **fail-closed に修正**: enqueue 失敗時は補償遷移で run を `failed` (error_code=enqueue_dispatch_failed)。`queued->failed` を additive 許可。自動再試行 sweeper のみ defer。
- **R2-F2 (HIGH) MCP cancel が worker/event invariant を bypass**: `bridge_run_cancel` (api_bridge.py:653) が `run.status="cancelled"` を直接 set + commit し `run_cancelled` event 非 append。→ **全 cancel entrypoint を `cancel_agent_run` 経由に統一** + actor_id plumbing + driver は DB-status 検知。統一で regress する queued/transient cancel を防ぐため `{queued,gathering_context,generated_artifact,schema_validated}->cancelled` を additive 許可。bulk cancel (1686) は follow-up。
- **R2-F3 (HIGH) provider_incomplete→repair_exhausted は不許可**: state_machine.py:35 で provider_incomplete は running/failed/cancelled のみ。→ closure を **分離**: validation_failed→repair_exhausted、provider_incomplete→running(retry)/failed。

**scope 再評価 (R2)**: R2 により state machine additive 拡張 (queued→failed / transient→cancelled) + MCP cancel API 契約変更 (actor_id) が in scope に追加。CRITICAL state machine + MCP boundary 直結のため実装後 adversarial loop は findings_zero まで必須。**本 Pack + ADR-00057 は R1+R2 反映済の実装 ready な planning**。実装着手は plan-review R3 (R2 fix 副作用確認) → clean → ADR accepted 昇格 → Codex-first 実装 → adversarial loop。
