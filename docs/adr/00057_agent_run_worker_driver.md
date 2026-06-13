---
id: "ADR-00057"
title: "AgentRun Worker Driver — arq worker が queued run を orchestrator pipeline で駆動 (shadow-first foundational slice)"
status: "proposed"
date: "2026-06-13"
authors:
  - "Claude (autonomous, user 承認 scope: runtime driver 推奨方向)"
related_sprints:
  - "SP-004-5_agent_run_worker_driver"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #4 (AI エージェント権限: AI 実行を end-to-end 駆動する runtime loop) + #3 (event schema: job lifecycle event) に該当。SP-004 (agent_runtime、completed) が **worker / arq job を「Sprint 4.5」へ明示 defer** したが Sprint 4.5 Pack は未作成。本 ADR はその gap を埋める runtime driver を、まず **shadow run の end-to-end 実行 (Mock provider)** に scope した foundational slice として定義する。

最終更新: 2026-06-13

> **status: proposed (plan-review R1 反映済、accepted 未昇格)**。codex plan-review R1 で 3 HIGH + 2 MEDIUM の設計欠陥を実装前に捕捉し全 adopt: F1 cancel transport 不整合 (per-run `cancel:run:{run_id}` ↔ worker `worker_cancel_channel`) / F2 enqueue 失敗 → orphan queued run / F3 status guard では concurrency 不足 (atomic claim `UPDATE...RETURNING` 必須、claim-miss=no-op) / F4 ContextSnapshot/ProviderRequest provenance が placeholder 化しうる (ProviderRequest 先行構築 + exact fingerprint) / F5 non-terminal (`provider_incomplete`/`validation_failed`) 未 close (repair loop)。これにより本 slice は **当初想定 (queued run を step に流すだけ) より substantial な core-runtime piece** (atomic claim + cancel transport 整合 + enqueue 回復 + provenance binding + non-terminal handling + full adversarial loop) と判明。実装着手直前に plan-review R2 → §sprint-pack-adr-gate.md §12 に従い proposed → accepted 昇格 + 採否判定経由。

## 背景

- 決定対象: `queued` AgentRun を arq worker が pickup し、既存 orchestrator step (`execute_provider_step` → `execute_validation_step` → `execute_shadow_completion_step` 等、SP-004/5.5/SP-029) を順次呼んで **end-to-end で terminal まで駆動** する runtime loop。現状 worker は `noop_task` のみで、run_create は `queued` run を作るだけで誰も駆動しない (SP-004 §残リスクで「worker は Sprint 4.5 で詳細化」と defer)。
- 関連 Sprint: SP-004 (agent_runtime、completed、orchestrator step + state machine + ContextSnapshot + BudgetGuard + SecretBroker を実装)、SP-005 (provider_adapter、Mock/OpenAI/Anthropic/Gemini)、SP-029 (shadow mode、shadow terminal step + budget/guard)。
- 前提 / 制約:
  - 既存 orchestrator step / state machine / ContextSnapshot 10 列 / BudgetGuard / Compliance Gate / preflight / SecretBroker を **再利用** (再実装しない)。
  - AgentRun 16 status / blocked_reason 3 / event types exact set / ContextSnapshot 10 列を壊さない。
  - production の post-validation pipeline (policy_lint → diff_ready → approval → runner/repo) は **未実装** (SP-007 runner / SP-008 repoproxy は別 Sprint で stub/部分)。よって本 slice は **shadow run のみ end-to-end 完遂** (schema_validated → completed)、production run は driver 対象外 (従来通り queued のまま、production runtime は後続増分)。
  - **Mock provider 固定**: shadow 試走の foundational slice は `MockProviderAdapter` で実行 (real provider key / Compliance 実送信なし)。real provider 駆動は後続。
  - additive のみ。worker 既存構造 (gate-wrapped functions / cancel pubsub / max_jobs) を踏襲。

## 選択肢

1. **arq task `execute_agent_run` + shadow-only enqueue (採用)**: 新 task を `with_active_registry_gate` でラップし `WorkerSettings.functions` に追加。`bridge_run_create` が **shadow run のみ** `enqueue_job("execute_agent_run", run_id, tenant_id)`。task が orchestrator step を順次駆動。
2. **全 run enqueue (却下)**: production run も enqueue すると post-validation pipeline 未実装で schema_validated 停止 + real provider 課金リスク。production runtime は別 increment。
3. **同期駆動 (run_create 内で直接 pipeline、却下)**: API request 内で provider call を同期実行 = timeout / API latency / cancellation 不能。arq 非同期が前提 (SP-004 設計)。

## 採用案

選択肢 1。

- **task** (`backend/app/workers/agent_run_driver.py` 新規): `async def execute_agent_run(ctx, *, run_id, tenant_id)`:
  1. `verify_worker_dequeue_if_configured(ctx)` (active registry gate)。
  2. **atomic claim (plan-review F3、must_ship)**: 単一 `UPDATE agent_runs SET status='gathering_context', updated_at=now() WHERE tenant_id=:t AND id=:r AND run_mode='shadow' AND status='queued' RETURNING *` + 同一 transaction で `context_gathered` event + ContextSnapshot。**0 rows = claim-miss → no-op return (failed にしない)**。これにより max_jobs=10 の duplicate job / concurrent worker が single-flight 化され、benign loser を failed 誤分類しない。**この atomic claim が SP-029/SP-037 で「driver の single-flight が cover する」と defer した concurrency 前提を満たす根拠** (per-run の record_provider_usage は claim 済 1 worker のみ駆動)。
  3. **provenance binding (plan-review F4、must_ship)**: ProviderRequest を **先に** 正規 helper (request + `provider_request_fingerprint_payload`) で構築 → ContextSnapshot `input` に **その exact fingerprint** を格納 (placeholder 禁止)。10 列 (prompt_pack/policy は実 lock 値、repo_state/tool_manifest/evidence_set は driver 定義、provider_continuation_ref null)。snapshot fingerprint / ProviderRequest matrix version / Artifact payload_data_class / provider result fingerprint の相互一致を test で assert。
  4. 駆動 (各 step は `transition_with_event` 三重 guard 経由):
     - claim 済 (`gathering_context`) → `running` (`provider_requested`)。
     - `execute_provider_step` (MockProviderAdapter + shadow preflight/budget/guard、SP-029): → generated_artifact / blocked / provider_incomplete / provider_refused。Artifact 生成。
     - `execute_validation_step`: → schema_validated / validation_failed。
     - `execute_shadow_completion_step`: `schema_validated → completed` (`run_completed`)。
  5. **non-terminal outcome handling (plan-review F5、must_ship)**: `provider_incomplete` / `validation_failed` は非 terminal。本 slice は `execute_repair_decision_step` (retry / repair_exhausted) を **driver loop に含める** (bounded retry → repair_exhausted terminal)。retry 不能な provider_incomplete は documented policy で `failed` or resume-owned。Mock を forced incomplete / refusal / unsupported_schema / schema_mismatch にする test を含める (happy path だけにしない)。
  6. **error handling**: 例外時は run を `failed` (`run_failed`、error_code/error_summary、raw secret なし)。**concurrent status-change 例外 (transition_with_event の conditional update miss) は failed でなく no-op 扱い** (F3、benign duplicate)。blocked は stop (resume 待ち、driver 再駆動しない)。
  7. **cancellation (plan-review F1、must_ship)**: 既存 `cancel.py` は **per-run channel `cancel:run:{run_id}`** に publish するが worker は `worker_cancel_channel` のみ subscribe。**transport を整合させる**: (a) run cancel を worker channel に run_id payload 付きで publish、or (b) job 開始時に per-run channel を subscribe。driver は step 境界で cancel flag を check → `cancelled`。実 `publish_cancel_signal` message 形状で integration test。
- **worker registration**: `WorkerSettings.functions` に `with_active_registry_gate(execute_agent_run)` 追加。
- **Mock provider / ContextSnapshot / Artifact**: SP-005 MockProviderAdapter + SP-004 `create_snapshot` + Artifact repository を再利用。ProviderRequest は shadow 用 `payload_data_class` (driver default、Compliance Gate は Mock provider 行が Matrix にある前提、無ければ deny = fail-closed)。
- **idempotency / re-entrancy**: task は `status='queued'` を atomic に確認してから駆動 (二重 enqueue は 2 個目が no-op)。orchestrator lease (SP-014) は multi-agent 用、single shadow run には status guard で十分。

## 却下案

- 全 run enqueue (選択肢 2): production runtime 未実装 + 課金リスク。
- 同期駆動 (選択肢 3): timeout / cancel 不能。
- 新 state machine / 新 event type: 不要 (既存 step + event を再利用、16 status / event exact set 不変)。

## リスク

- Mock provider 固定のため real provider 駆動の検証は後続 (foundational slice の明示的 scope 限定)。
- **provenance binding (F4)**: ContextSnapshot 10 列の driver default 値の妥当性 (prompt_pack/policy version 等)。fingerprint は placeholder 禁止 (ProviderRequest を先に構築し exact fingerprint を格納) だが、prompt_pack/policy lock は SP-004 既存 default / lock 値を流用、無ければ実 prompt pack 配線を後続。snapshot fingerprint / ProviderRequest matrix version / Artifact payload_data_class / provider result fingerprint の相互一致を test で固定。
- **cancellation transport (F1)**: cancel は step 境界のみ (provider mid-call kill 不可) → job_timeout (300s) + 後続で kill policy。既存 `cancel.py` の per-run channel `cancel:run:{run_id}` と worker の `worker_cancel_channel` の transport 不整合を **本 slice で必ず整合** (must_ship)。実 `publish_cancel_signal` message 形状で integration test (mock で済ませない)。
- **enqueue atomicity / orphan queued run (F2)**: run commit 後 enqueue (enqueue 失敗で run が queued のまま残る = orphan)。foundational では **enqueue を run commit と同一 path で best-effort + 失敗時 log + run は queued 残置** (status guard により後で再 enqueue/claim 可能)。**自動 sweeper / outbox は後続 increment へ defer** (orphan は atomic claim 可能なため data 不整合にはならない、駆動されないだけ)。本 slice の atomic claim (F3) は二重 enqueue・concurrent worker を no-op 化するので、再 enqueue 時の重複駆動リスクはない。
- **atomic claim / concurrency (F3)**: status guard 単独では concurrent worker / 二重 enqueue で同一 run を二重駆動しうる。`UPDATE ... WHERE status='queued' RETURNING` の atomic claim で single-flight 化、**0 rows = benign loser → no-op (failed 誤分類しない)**。これにより SP-029/SP-037 で「driver の single-flight が cover」と defer した per-run record_provider_usage の concurrency 前提が満たされる。
- **non-terminal outcome (F5)**: `provider_incomplete` / `validation_failed` を放置すると run が宙吊り。本 slice は `execute_repair_decision_step` を driver loop に含め bounded retry → `repair_exhausted` terminal で close。retry 不能 provider_incomplete は documented policy で `failed` or resume-owned。Mock を forced incomplete / refusal / unsupported_schema / schema_mismatch にする negative test を含める (happy path だけにしない)。
- Compliance Gate / preflight / SecretBroker を shadow も通す (SP-029 §7) → Mock provider 行が Matrix 未登録だと deny。Matrix に mock 行があるか実装時確認。
- production run を誤って enqueue しない (shadow-only gate) → enqueue 経路 + task 内 atomic claim の `run_mode='shadow'` 条件の二重防御 + negative test。

## rollback 手順

- enqueue を無効化 (`bridge_run_create` の enqueue を flag gate `shadow_mode_enabled` 連動、off で enqueue しない) → 即時 rollback (shadow run は queued のまま、従来挙動)。
- `WorkerSettings.functions` から `execute_agent_run` を除去 (worker は noop に戻る)。
- DB schema 変更なし → migration rollback 不要。
- shadow 機能自体は `shadow_mode_enabled=false` で全停止 (SP-029 上位 flag)。

## 実装対象ファイル

- `backend/app/workers/agent_run_driver.py` (新規 task)
- `backend/app/workers/main.py` (functions に追加)
- `backend/app/mcp/api_bridge.py` (`bridge_run_create` で shadow run の enqueue)
- `backend/app/workers/main.py` (`propagate_agent_run_cancel` を run_id 一致 cancel flag へ拡張)
- `tests/runtime/test_agent_run_driver.py` (新規: shadow end-to-end 駆動 / error→failed / 二重 enqueue no-op / production 非 enqueue / cancel、unit + DB-gated)

## テスト指針

- DB-gated: shadow run を作成 → `execute_agent_run` を直接 await → run が `completed` 到達、event timeline (context_gathered → provider_requested → ... → run_completed) + ContextSnapshot input + Artifact + shadow budget event を検証。
- **atomic claim (F3)**: queued でない run (既 running/completed) → no-op (二重 enqueue 防御)。**同一 shadow run に対し `execute_agent_run` を concurrent に 2 回駆動 → 1 個だけ claim 成功・他は no-op (failed にならない)** (DB-gated concurrent test、benign-loser-not-failed)。
- **provenance binding (F4)**: ContextSnapshot input fingerprint == ProviderRequest fingerprint == provider result fingerprint、ContextSnapshot matrix version == ProviderRequest matrix version、Artifact payload_data_class 一致を assert (placeholder 検出 = test fail)。
- **non-terminal handling (F5)**: Mock を forced `provider_incomplete` / `validation_failed` / refusal / unsupported_schema / schema_mismatch にし、driver が repair loop → `repair_exhausted` terminal で close する / refusal は `provider_refused` terminal を検証 (happy path 以外を必ず close)。
- **cancellation transport (F1)**: 実 `publish_cancel_signal(run_id)` (cancel.py の per-run channel) を発火 → driver が step 境界で検知し `cancelled` 到達 (mock channel でなく実 transport 形状で integration test)。
- production run を `execute_agent_run` に渡す → no-op (atomic claim の run_mode='shadow' 条件で claim-miss)。
- provider が blocked を誘発 (budget/usage) → run が blocked、driver は再駆動しない。
- 例外注入 → run `failed` + error_code、raw secret なし。concurrent status-change による conditional update miss は failed でなく no-op (F3 benign)。
- enqueue: shadow run_create で enqueue 呼ばれ、production run_create で呼ばれない (mock redis で検証)。enqueue 失敗 (redis 例外) → run は queued 残置・例外を呑まず log (orphan は後で claim 可能、F2)。
