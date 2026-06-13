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
  - "cancel transport 不整合 (per-run channel ↔ worker channel、F1)"
  - "enqueue 失敗 → orphan queued run (F2)"
  - "ContextSnapshot/ProviderRequest provenance が placeholder 化 (F4)"
  - "non-terminal (provider_incomplete/validation_failed) 未 close (F5)"
  - "Mock provider 行が Compliance Matrix 未登録で deny"
  - "production run を誤 enqueue (shadow-only 漏れ)"
  - "cancel が step 境界のみ (provider mid-call kill 不可)"
---

## 目的

SP-004 (agent_runtime、completed) が「Sprint 4.5」へ defer した **arq worker driver** を実装し、`queued` shadow AgentRun を既存 orchestrator step で end-to-end (queued → completed) に駆動する。これにより shadow run が初めて **実際に実行可能** になり、SP-029 shadow mode + 後続増分 (SP-037 aggregate cap、A/B、bake-off) の前提を満たす。

## 背景

現状 worker は `noop_task` のみ、run_create は `queued` run を作るだけで誰も駆動しない (SP-004 §残リスク「worker は Sprint 4.5 で詳細化」)。本 Sprint は **shadow-first foundational slice** として Mock provider で shadow run を駆動。production runtime (post-validation pipeline + real provider) は後続。詳細は ADR-00057。

## 対象外

- production run の駆動 (post-validation pipeline = policy_lint/diff_ready/approval/runner/repo 未実装、SP-007/008 範囲)
- real provider (OpenAI/Anthropic/Gemini) 駆動 (Mock 固定)
- provider mid-call kill / 詳細 cancel kill policy (step 境界 cancel のみ、transport 整合は F1 で in scope)
- orphan queued run の **自動** sweep/再 enqueue (本 slice は enqueue 失敗を log + queued 残置 + atomic claim で再駆動可能化のみ、自動 sweeper/outbox は後続。F5 repair loop は in scope)

## 設計判断 (plan-review R1 F1-F5 反映)

- arq task `execute_agent_run` + **shadow-only enqueue** (ADR-00057 §採用案)。全 run enqueue / 同期駆動は却下。
- 既存 orchestrator step / state machine / ContextSnapshot / BudgetGuard / Compliance Gate / SecretBroker を再利用 (再実装なし)。
- **atomic claim (F3)**: enqueue は run commit 後、task は `UPDATE agent_runs SET status='gathering_context' WHERE tenant_id=:t AND id=:r AND run_mode='shadow' AND status='queued' RETURNING *` で **claim** (status 再確認でなく atomic 取得)。**0 rows = benign loser → no-op return (failed にしない)**。concurrent worker / 二重 enqueue / production 誤 enqueue を single-flight + run_mode gate で防御。この single-flight が SP-029/SP-037 の concurrency 前提を満たす。
- **provenance binding (F4)**: ProviderRequest を先に構築 → ContextSnapshot input に exact fingerprint 格納 (placeholder 禁止)。snapshot/request/result fingerprint + matrix version + Artifact payload_data_class の相互一致を test 固定。
- **non-terminal handling (F5)**: `provider_incomplete`/`validation_failed` は `execute_repair_decision_step` を driver loop に含めて bounded retry → `repair_exhausted` terminal で close。
- **cancellation transport (F1)**: 既存 `cancel.py` の per-run channel `cancel:run:{run_id}` と worker channel の transport を整合させ、step 境界 cancel を実 transport 形状で配線。
- **enqueue 回復 (F2)**: enqueue 失敗は呑まず log + run queued 残置 (atomic claim で後から再駆動可能、data 不整合なし)。自動 sweeper は後続 defer。
- error → failed、blocked → stop (resume 待ち、driver 再駆動しない)。concurrent status-change miss は failed でなく no-op (F3 benign)。

## 実装チケット / タスク一覧

1. `workers/agent_run_driver.py`: `execute_agent_run(ctx, *, run_id, tenant_id)` — gate verify → **atomic claim (F3、`UPDATE...RETURNING`、claim-miss=no-op)** + 同一 tx で context_gathered event + ContextSnapshot → running → execute_provider_step(Mock) → execute_validation_step → execute_shadow_completion_step → non-terminal は execute_repair_decision_step (F5) → error/blocked/cancel handling。
2. `workers/main.py`: `functions` に `with_active_registry_gate(execute_agent_run)` 追加。
3. `mcp/api_bridge.py` `bridge_run_create`: shadow run commit 後に enqueue (production は非 enqueue)。enqueue 失敗は log + queued 残置 (F2)。
4. **cancel transport 整合 (F1)**: `cancel.py` per-run channel `cancel:run:{run_id}` と worker subscribe を整合 (run cancel を worker 経路へ配線 or job 開始時 per-run subscribe)、driver step 境界で cancel flag check。
5. **provenance binding (F4)**: ProviderRequest を先に構築する helper + ContextSnapshot input に exact fingerprint 格納 (10 列 driver default)、Artifact (mock structured output)、ProviderRequest (shadow payload_data_class)。
6. test: DB-gated end-to-end 駆動 / **atomic claim concurrent (benign-loser-not-failed、F3)** / error→failed / production 非駆動・非 enqueue / blocked stop / **cancel 実 transport (F1)** / **non-terminal repair→repair_exhausted (F5)** / **provenance fingerprint 一致 (F4)** / ContextSnapshot+Artifact+event timeline 検証。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer |
|---|---|---|
| shadow run end-to-end 駆動 (queued→completed、Mock) | ✓ | |
| shadow-only enqueue (production 非 enqueue) | ✓ | |
| **atomic claim single-flight (F3、claim-miss=no-op、concurrent 二重駆動防止)** | ✓ | |
| **provenance binding exact fingerprint (F4、placeholder 禁止)** | ✓ | |
| **cancel transport 整合 + 実 transport integration test (F1)** | ✓ | |
| **non-terminal handling: repair loop → repair_exhausted (F5)** | ✓ | |
| **enqueue 失敗を呑まず log + queued 残置 (F2)** | ✓ | |
| error→failed / blocked→stop | ✓ | |
| ContextSnapshot input + Artifact + event timeline | ✓ | |
| step-boundary cancel | ✓ | |
| provider mid-call kill | | ✓ |
| orphan queued run 自動 sweeper / outbox (F2 の自動回復) | | ✓ |
| production runtime / real provider | | ✓ |
| 実 prompt pack 配線 (driver default lock の精緻化) | | ✓ |

## 受け入れ条件

- [ ] shadow run を作成 → `execute_agent_run` で `completed` 到達、event timeline (context_gathered → provider_requested → provider_responded/artifact_generated → schema_validated → run_completed) + ContextSnapshot input (10 列) + Artifact 生成を検証。
- [ ] **(F3) atomic claim**: 同一 shadow run へ concurrent に 2 回駆動 → 1 個だけ claim 成功、他は no-op (status 不変、failed にならない)。queued でない run も no-op。
- [ ] production run を `execute_agent_run` に渡すと no-op (atomic claim の run_mode='shadow' 条件で claim-miss)。
- [ ] **(F4) provenance**: ContextSnapshot input fingerprint == ProviderRequest fingerprint == provider result fingerprint、matrix version 一致、Artifact payload_data_class 一致 (placeholder = test fail)。
- [ ] **(F5) non-terminal**: Mock forced `provider_incomplete`/`validation_failed` → repair loop → `repair_exhausted` terminal で close。refusal → `provider_refused` terminal。unsupported_schema/schema_mismatch も close。
- [ ] **(F1) cancel**: 実 `publish_cancel_signal(run_id)` (per-run channel) 発火 → step 境界 `cancelled` 到達 (実 transport 形状の integration test)。
- [ ] **(F2) enqueue 回復**: enqueue 失敗 (redis 例外) で例外を呑まず log + run queued 残置 (後で claim 可能)。
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
- **non-terminal (F5)**: provider_incomplete/validation_failed/refusal を terminal へ確実に close (宙吊りなし)。
- **cancel transport (F1)**: per-run channel ↔ worker channel の整合、実 transport 形状の test。
- error/blocked handling + enqueue 回復 (F2、orphan を呑まない)。

## 残リスク

- Mock 固定 (real provider 駆動は後続)。
- ContextSnapshot driver default 値 (実 prompt pack 配線は後続)。
- enqueue orphan (sweep 後続)。
- cancel step 境界のみ (mid-call kill 後続)。

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

**scope 再評価**: plan-review R1 により本 slice は当初想定 (queued run を step に流すだけの薄い driver) より **substantial な core-runtime piece** と判明 — atomic claim + cancel transport 整合 + enqueue 回復 + provenance binding + non-terminal handling、加えて ADR Gate Criteria #4 (AI 実行 end-to-end 駆動権限) 直結のため実装後 full adversarial loop (findings_zero、codex-usage-policy §14.1) が必要。**本 Pack + ADR-00057 は plan-review R1 反映済の実装 ready な planning として保存**。実装着手は plan-review R2 → ADR accepted 昇格 → Codex-first 実装 (codex-task) → adversarial loop の手順を踏む。
