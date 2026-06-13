---
id: "ADR-00057"
title: "AgentRun Worker Driver — arq worker が queued run を orchestrator pipeline で駆動 (shadow-first foundational slice)"
status: "accepted"
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

> **status: proposed (plan-review R1+R2 反映済、accepted 未昇格)**。
>
> **R1** (3 HIGH + 2 MEDIUM、全 adopt): F1 cancel transport / F2 enqueue orphan / F3 atomic claim / F4 provenance / F5 non-terminal。
>
> **R2** (no-ship、3 HIGH、全 adopt、実コード照合済): **R2-F1** enqueue 失敗の「log + queued 残置」は recovery でない (再駆動主体不在 = silent orphan) → fail-closed `queued->failed` 補償遷移 (error_code=enqueue_dispatch_failed)。**R2-F2** MCP `bridge_run_cancel` (api_bridge.py:653) が `run.status="cancelled"` を直接 set し `run_cancelled` event 非 append + signal なし (AgentRunEvent 正本 invariant 破壊) → `cancel_agent_run` service 経由に統一 + cancel 許可遷移を transient state へ拡張 + actor plumbing。**R2-F3** `provider_incomplete -> repair_exhausted` は **不許可** (state_machine.py:35、provider_incomplete は running/failed/cancelled のみ) → closure を `validation_failed`(→repair_exhausted) と `provider_incomplete`(→running/failed) で分離。
>
> **R3** (no-ship、2 HIGH、全 adopt、実コード照合済): **R3-F1** `cancel_agent_run` は **DB-first commit でない** (`transition_with_event` は commit せず caller が `session.begin()` で wrap して commit、event_log.py:49-53)。MCP `get_db_session` は yield のみ → `bridge_run_cancel` を service 化する際に **明示 commit を残さないと rollback** され cancel/event が永続しない。signal も commit 前 publish。→ driver 正本は **post-commit DB status 再読**、`bridge_run_cancel` は cancel_agent_run 後に明示 commit、signal は best-effort pre-commit と正確化。**R3-F2** `provider_incomplete` の bounded retry は **durable でない** (retry_count 列なし、execute_repair_decision_step は validation_failed 専用、worker crash + arq 再実行は claim-miss で非終端残留)。→ 本 slice は **provider_incomplete → 即 `failed`** (in-slice retry なし、durable counter / resume は後続)。worker-crash-mid-drive の resume/reclaim も後続 defer (atomic claim は double-drive を防ぐが crash 後の再駆動は別途、crashed run は非終端で可視・silent loss なし)。
>
> **R4** (no-ship、2 HIGH、全 adopt、tactical、実コード照合済): **R4-F1** `error→failed` は state machine 上 running/provider_incomplete/blocked からしか許されず、driver が gathering_context/generated_artifact/schema_validated/validation_failed まで commit 後に例外を起こすと終端化できず stuck (通常例外経路、crash defer ではない)。→ `failed` edge を **driver-reachable な全 non-terminal state** から additive 追加。**R4-F2** task signature が keyword-only なのに enqueue が positional で worker dispatch 時 TypeError → atomic claim 前に落ち queued orphan。→ enqueue を **keyword 引数**に統一 + wrapper 経由 dispatch test。
>
> R1+R2+R3+R4 = 計 12 findings 全 adopt。R4 の findings は tactical (edge 網羅 / enqueue 引数規約) で design は sound。doc plan-review はここで R4 fix 反映をもって完了とし、残る tactical correctness は **実装後の Codex adversarial loop (実コード review、§14.1 CRITICAL gate)** を authoritative gate とする (doc review の限界収益 < 実コード review)。foundational scope = 最小 robust: atomic claim + happy-path 駆動 + cancel (post-commit DB-status + entrypoint 統一 + 明示 commit) + enqueue fail-closed (keyword dispatch) + provenance + non-terminal closure (validation_failed→repair_exhausted / provider_incomplete→failed) + state machine additive edge (全 driver non-terminal → failed/cancelled)。**durability hardening (durable retry counter / crash resume / reclaim sweeper) と production runtime は明示 defer**。§sprint-pack-adr-gate.md §12 で proposed → accepted 昇格 + 採否判定 後に実装着手。

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

1. **arq task `execute_agent_run` + shadow-only enqueue (採用)**: 新 task を `with_active_registry_gate` でラップし `WorkerSettings.functions` に追加。`bridge_run_create` が **shadow run のみ** enqueue。**enqueue 引数規約 (R4-F2、必須統一)**: task signature `execute_agent_run(ctx, *, run_id, tenant_id)` は keyword-only のため、enqueue も **keyword** で `enqueue_job("execute_agent_run", run_id=str(run.id), tenant_id=run.tenant_id)` を正本にする (positional `enqueue_job(..., run_id, tenant_id)` は `with_active_registry_gate` wrapper の `task_fn(ctx, *args, **kwargs)` 転送で worker 実行時 TypeError になり atomic claim 前に落ちて queued orphan を作る、active_registry_worker_gate.py:193-239 照合)。`bridge_run_create` は arq pool を持たないため `arq.create_pool(redis_settings_from_url(settings.redis_url))` で pool を作り enqueue → close (worker 側 `ctx["redis"]` は API process に無い)。**wrapper 経由の dispatch test を必須** (keyword 転送で claim まで到達することを検証)。
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
  5. **non-terminal outcome handling (plan-review F5 + R2-F3 + R3-F2、must_ship、closure policy を分離 + durable 終端)**: `provider_incomplete` と `validation_failed` は **state machine 上の許可遷移が異なる** (R2-F3、`state_machine.py:35-36` 照合済) かつ **durable retry counter が無い** (R3-F2、AgentRun に retry_count 列なし、execute_repair_decision_step は validation_failed 専用で caller が retry_count を渡す):
     - `validation_failed` → `execute_repair_decision_step` で bounded retry → **`repair_exhausted` terminal** (許可遷移 `validation_failed -> repair_exhausted`、retry_count は driver loop が in-process 管理、validation_failed は同一 job 内で完結するため durable 不要)。
     - `provider_incomplete` → 本 slice は **即 `failed`** (`run_failed`、許可遷移 `provider_incomplete -> failed`)。bounded retry (`provider_incomplete -> running`) は **durable provider retry counter + resume/claim 経路が必要**なため後続 increment へ defer (R3-F2、in-process counter は worker crash で reset し終端保証を破る)。`provider_incomplete -> repair_exhausted` は不許可なので送らない。
     - Mock を forced incomplete / validation_failed / refusal / unsupported_schema / schema_mismatch にする negative test を **各 closure path 個別**に含める。provider_incomplete は `failed` 終端を assert (running へ retry しないこと)。
  6. **error handling (R4-F1)**: 例外時は run を **現在の committed status から** `failed` に遷移 (`run_failed`、error_code/error_summary、raw secret なし)。driver は post-commit で queued/gathering_context/running/generated_artifact/schema_validated/validation_failed のいずれにも居るため、**全 driver-reachable non-terminal → failed edge が必須** (上記 state machine additive)。例外 handler は run.status を refresh して現 state から failed へ遷移する (固定 from-state を仮定しない)。**concurrent status-change 例外 (transition_with_event の conditional update miss / 既に terminal) は failed でなく no-op 扱い** (F3、benign duplicate、cancelled/terminal を上書きしない)。blocked は stop (resume 待ち、driver 再駆動しない)。
  7. **cancellation (plan-review F1 + R2-F2 + R3-F1、must_ship、全 entrypoint 統一 + post-commit DB-status 検知)**: 実コード照合で **`cancel_agent_run` は DB-first commit ではない** (R3-F1): `transition_with_event` は commit せず caller が `session.begin()` で wrap して commit する (event_log.py:49-53)、`publish_cancel_signal` は **caller commit 前** に発火する best-effort 通知。よって driver の cooperative cancel は:
     - **driver 正本 = post-commit DB status 再読** (Redis signal は best-effort pre-commit で driver は依存しない)。driver は step 境界で run.status を別 transaction で refresh → `cancelled` (committed) を検知したら graceful stop (driver は cancelled へ自分で遷移しない)。transient state 中に cancel が race して次 transition が validation fail したら catch → status 再読 → cancelled なら no-op stop (F3 benign)。commit 前 signal で cancel が後に rollback された場合は status が cancelled でないため driver は誤停止しない (post-commit 読みの利点)。
     - **全 cancel entrypoint 統一 (R2-F2 + R3-F1、`api_bridge.py:653` 照合済)**: MCP `bridge_run_cancel` は現状 `run.status="cancelled"` 直接 set + `session.commit()` で **`run_cancelled` event を append しない** (AgentRunEvent 正本 invariant 破壊)。これを `cancel_agent_run` service 経由に統一 (event append + signal) **かつ呼出後に明示 commit を残す** (R3-F1: transition_with_event は commit しないため、commit を落とすと MCP session yield 後に rollback され cancel/event が永続しない)。`bridge_run_cancel` / `server.py:run_cancel` に actor_id を plumbing。MCP integration test は **実 DB 上の status=cancelled + run_cancelled event 永続**まで検証する。bulk/superintendent cancel (`api_bridge.py:1686`) の event-append 統一は別 follow-up (本 ADR §残課題、driver は DB status で stop するため driver 動作には非影響)。
     - **cancel 許可遷移の拡張 (R2-F2 副作用)**: 統一すると `cancel_agent_run` の validate_transition を通るため、現状 bypass で可能だった **queued / driver-transient state からの cancel が regress する** (`_CANCELABLE_STATES` は `{running, blocked, waiting_approval, provider_incomplete}` のみ、queued→cancelled は不許可)。regress 防止のため **`queued` / `gathering_context` / `generated_artifact` / `schema_validated` → `cancelled` (event `run_cancelled`) を additive に許可**し `_CANCELABLE_STATES` を拡張。cancelled は clean terminal exit のため shadow confinement (SHADOW_FORBIDDEN は pipeline-entry edge のみ禁止) と矛盾しない。
     - acceptance: REST `cancel_agent_run` と MCP `run_cancel` の **両方**で `run_cancelled` event append + driver stop を integration test。
- **worker registration**: `WorkerSettings.functions` に `with_active_registry_gate(execute_agent_run)` 追加。
- **enqueue 回復 (plan-review F2 + R2-F1、must_ship、fail-closed、silent orphan 禁止)**: R2-F1 で「log + queued 残置」は **recovery でない** (再 enqueue 主体が本 Sprint に無く、claim 可能なだけで誰も claim しない = 永続未実行 orphan) と判明。fail-closed に修正: shadow run commit **後**に enqueue、enqueue 失敗時は補償 transaction で run を **`failed`** に遷移 (`run_failed`、error_code=`enqueue_dispatch_failed`、raw secret なし) → silent orphan を作らない (失敗が run status に可視化、再駆動 = caller が新 run 作成)。queued→failed は現状不許可 (`queued` は gathering_context のみ) のため **`queued -> failed` (event `run_failed`) を additive に許可**。transient-retry の自動 sweeper / transactional outbox は後続 defer (但し silent orphan は本 fix で解消済、defer するのは「自動再試行」のみ)。
- **state machine additive 拡張 (R2-F1 + R2-F2 + R4-F1 由来、CRITICAL invariant、Python+test のみ、migration 不要)**: 不変条件「**driver-reachable な全 non-terminal state は `failed` (error) と `cancelled` (cancel) へ exit できる**」を満たすため、`ALLOWED_TRANSITIONS` + `EVENT_TYPE_FOR_TRANSITION` に additive 追加:
  - **`failed` (run_failed) を `{queued, gathering_context, generated_artifact, schema_validated, validation_failed}` から** (既存 running/provider_incomplete/blocked と合わせ driver が post-commit で取り得る全 non-terminal を網羅、**R4-F1**: 既存は running 系のみで gathering_context 等での例外が終端化できず stuck になる)。
  - **`cancelled` (run_cancelled) を `{queued, gathering_context, generated_artifact, schema_validated, validation_failed}` から** (既存 running/blocked/waiting_approval/provider_incomplete と合わせ網羅、cancel 統一 regress 防止 + 任意 state cancel)。
  - production-only pipeline state (`policy_linted` / `diff_ready` / `waiting_approval`) は shadow driver が進入しない (SHADOW_FORBIDDEN) ため本 slice では追加しない (production runtime Sprint で対応)。
  - 16 status enum / event exact set は不変 (新 status / 新 event_type なし、run_failed/run_cancelled は既存)。transition は DB CHECK 対象外 (status enum のみ DB CHECK)、5+ source 整合は state_machine.py + 該当 transition test の `EXPECTED_*` で固定。`_CANCELABLE_STATES` も同集合へ拡張。
- **Mock provider / ContextSnapshot / Artifact**: SP-005 MockProviderAdapter + SP-004 `create_snapshot` + Artifact repository を再利用。ProviderRequest は shadow 用 `payload_data_class` (driver default、Compliance Gate は Mock provider 行が Matrix にある前提、無ければ deny = fail-closed)。
- **idempotency / re-entrancy**: task は atomic claim (F3) で `status='queued'` を atomic に取得してから駆動 (二重 enqueue は 2 個目が claim-miss=no-op)。orchestrator lease (SP-014) は multi-agent 用、single shadow run には atomic claim で十分。

## 却下案

- 全 run enqueue (選択肢 2): production runtime 未実装 + 課金リスク。
- 同期駆動 (選択肢 3): timeout / cancel 不能。
- 新 state machine / 新 event type: 不要 (既存 step + event を再利用、16 status / event exact set 不変)。

## リスク

- Mock provider 固定のため real provider 駆動の検証は後続 (foundational slice の明示的 scope 限定)。
- **provenance binding (F4)**: ContextSnapshot 10 列の driver default 値の妥当性 (prompt_pack/policy version 等)。fingerprint は placeholder 禁止 (ProviderRequest を先に構築し exact fingerprint を格納) だが、prompt_pack/policy lock は SP-004 既存 default / lock 値を流用、無ければ実 prompt pack 配線を後続。snapshot fingerprint / ProviderRequest matrix version / Artifact payload_data_class / provider result fingerprint の相互一致を test で固定。
- **cancellation (F1 + R2-F2 + R3-F1)**: cooperative cancel は **post-commit DB status 再読**が正本 (`cancel_agent_run` は commit しない — caller が commit、signal は pre-commit best-effort)。`bridge_run_cancel` を `cancel_agent_run` 経由に統一する際は **明示 commit を残す** (落とすと MCP session yield 後 rollback)。provider mid-call kill は不可 (step 境界のみ) → job_timeout (300s) + 後続で kill policy。全 cancel entrypoint (REST + MCP) で `run_cancelled` event append + 実 DB 永続を integration test。
- **enqueue atomicity / orphan queued run (F2 + R2-F1)**: run commit 後 enqueue、**enqueue 失敗時は補償 transaction で run を `failed` に遷移** (fail-closed、silent orphan 禁止)。「log + queued 残置」は R2-F1 で recovery でないと判明したため不採用。自動 sweeper / transactional outbox (transient 失敗の自動再試行) は後続 defer (但し失敗は run status=failed として可視化済、defer 対象は「自動再試行」のみで silent orphan ではない)。atomic claim (F3) が二重 enqueue・concurrent worker を no-op 化するので再駆動時の重複駆動リスクはない。
- **atomic claim / concurrency (F3)**: status guard 単独では concurrent worker / 二重 enqueue で同一 run を二重駆動しうる。`UPDATE ... WHERE status='queued' RETURNING` の atomic claim で single-flight 化、**0 rows = benign loser → no-op (failed 誤分類しない)**。これにより SP-029/SP-037 で「driver の single-flight が cover」と defer した per-run record_provider_usage の concurrency 前提が満たされる。
- **non-terminal outcome (F5 + R2-F3 + R3-F2)**: closure を許可遷移に合わせ分離 + durable 終端。`validation_failed` → `execute_repair_decision_step` → `repair_exhausted` (同一 job 内完結、retry_count は in-process)。`provider_incomplete` → **即 `failed`** (本 slice、durable retry counter 無し = in-process retry は crash で reset し終端保証を破るため retry は後続 defer)。Mock forced incomplete / validation_failed / refusal / unsupported_schema / schema_mismatch を各 closure path 個別 negative test。
- Compliance Gate / preflight / SecretBroker を shadow も通す (SP-029 §7) → Mock provider 行が Matrix 未登録だと deny。Matrix に mock 行があるか実装時確認。
- production run を誤って enqueue しない (shadow-only gate) → enqueue 経路 + task 内 atomic claim の `run_mode='shadow'` 条件の二重防御 + negative test。

## 残課題 (本 ADR scope 外、follow-up)

- **worker-crash-mid-drive の resume / reclaim (R3-F2 派生、durability)**: atomic claim は `status='queued'` のみ対象のため、driver が transient state (gathering_context / running / generated_artifact / schema_validated) まで進めた後 worker が crash し arq が同 job を再実行すると **claim-miss=no-op** で run が非終端のまま残る (silent loss ではない、status で可視)。stale-run の resume/reclaim sweeper は **後続 increment へ defer**。本 slice の保証は「double-drive しない (atomic claim) + silent orphan/loss を作らない」までで、「crash 後の自動 re-drive」は scope 外。
- **durable provider retry counter (R3-F2)**: `provider_incomplete` の bounded retry (→running) には persistent な provider retry attempt counter + resume/claim 経路が必要。本 slice は provider_incomplete → 即 failed で終端し、retry は後続。
- **bulk/superintendent cancel の event-append 統一 (R2-F2 派生)**: `api_bridge.py:1686` の `UPDATE agent_runs SET status='cancelled'` (bulk/superintendent 経路) も直接 UPDATE で `run_cancelled` event を append しない。本 ADR は driver と直結する `bridge_run_cancel` (single run) を統一するが、bulk 経路の event-append 統一は **別 follow-up** (driver は DB status で stop するため driver 正常動作には影響しないが、AgentRunEvent 正本 invariant の完全 close には bulk 経路修正が必要)。
- **自動 sweeper / transactional outbox (R2-F1 の transient 再試行)**: enqueue 失敗は fail-closed (failed) で silent orphan は解消済だが、transient Redis 障害の自動再試行は後続。
- **provider mid-call kill (F1)**: step 境界 cancel のみ。Redis per-run channel ↔ worker channel transport 整合 + mid-call interruption は後続。

## rollback 手順

- enqueue を無効化 (`bridge_run_create` の enqueue を flag gate `shadow_mode_enabled` 連動、off で enqueue しない) → 即時 rollback (shadow run は queued のまま、従来挙動)。
- `WorkerSettings.functions` から `execute_agent_run` を除去 (worker は noop に戻る)。
- state machine additive 拡張 (`queued->failed` / transient→cancelled)、`bridge_run_cancel` の `cancel_agent_run` 統一は **code revert で戻る (migration 不要、transition は Python-only)**。ただし cancel 統一を revert すると MCP cancel が再び event 非 append の旧挙動に戻る点に留意 (invariant fix のため revert は driver 除去時のみ)。
- DB schema 変更なし → migration rollback 不要。
- shadow 機能自体は `shadow_mode_enabled=false` で全停止 (SP-029 上位 flag)。

## 実装対象ファイル

- `backend/app/workers/agent_run_driver.py` (新規 task: atomic claim → 駆動 → non-terminal closure 分離 → DB-status cancel 検知 → error→failed)
- `backend/app/workers/main.py` (`WorkerSettings.functions` に `with_active_registry_gate(execute_agent_run)` 追加)
- `backend/app/services/agent_runtime/state_machine.py` + `cancel.py` (additive: `ALLOWED_TRANSITIONS` + `EVENT_TYPE_FOR_TRANSITION` に `{queued,gathering_context,generated_artifact,schema_validated,validation_failed}->failed` (run_failed) と `->cancelled` (run_cancelled) を追加、`_CANCELABLE_STATES` 同集合拡張、16 status / event exact set 不変)
- `backend/app/mcp/api_bridge.py` (`bridge_run_create`: shadow run の enqueue + 失敗時補償 failed / `bridge_run_cancel`: `cancel_agent_run` 経由へ統一 + actor_id)
- `backend/app/mcp/server.py` (`run_cancel`: actor_id plumbing)
- `tests/runtime/test_agent_run_driver.py` (新規: 下記テスト指針、unit + DB-gated)
- `tests/runtime/test_shadow_mode_transitions.py` 等 state machine test (新 cancel/failed edge の `EXPECTED_*` 整合)
- cancel parity test (REST cancel_agent_run + MCP run_cancel → run_cancelled event + driver stop)

## テスト指針

- DB-gated: shadow run を作成 → `execute_agent_run` を直接 await → run が `completed` 到達、event timeline (context_gathered → provider_requested → ... → run_completed) + ContextSnapshot input + Artifact + shadow budget event を検証。
- **atomic claim (F3)**: queued でない run (既 running/completed) → no-op (二重 enqueue 防御)。**同一 shadow run に対し `execute_agent_run` を concurrent に 2 回駆動 → 1 個だけ claim 成功・他は no-op (failed にならない)** (DB-gated concurrent test、benign-loser-not-failed)。
- **provenance binding (F4)**: ContextSnapshot input fingerprint == ProviderRequest fingerprint == provider result fingerprint、ContextSnapshot matrix version == ProviderRequest matrix version、Artifact payload_data_class 一致を assert (placeholder 検出 = test fail)。
- **non-terminal handling (F5 + R2-F3 + R3-F2、closure 分離 + durable 終端)**: Mock forced `validation_failed` → driver repair loop → `repair_exhausted` terminal。Mock forced `provider_incomplete` → **即 `failed`** (`repair_exhausted` にも `running` にも行かないことを assert)。refusal → `provider_refused` terminal。unsupported_schema / schema_mismatch も各 close を検証。
- **cancellation (F1 + R2-F2 + R3-F1、entrypoint parity + DB 永続)**: (a) REST `cancel_agent_run(run_id)` + caller commit で run cancelled → driver が step 境界 post-commit DB 再読で検知し graceful stop。(b) MCP `run_cancel` でも stop **かつ `run_cancelled` event が実 DB に永続** (統一 + 明示 commit、DB-gated で status=cancelled + event row を assert)。(c) queued / transient state からの cancel が allowed (新 edge) で `run_cancelled` event 付き cancelled 到達。
- production run を `execute_agent_run` に渡す → no-op (atomic claim の run_mode='shadow' 条件で claim-miss)。
- provider が blocked を誘発 (budget/usage) → run が blocked、driver は再駆動しない。
- **例外注入 from 各 state (R4-F1)**: gathering_context / running / generated_artifact / schema_validated / validation_failed の各時点で例外を注入 → run が **その state から `failed`** + error_code に終端化 (stuck non-terminal にならないことを各 state で assert)。raw secret なし。concurrent status-change による conditional update miss / terminal は failed でなく no-op (F3 benign)。
- **enqueue dispatch contract (R4-F2)**: `with_active_registry_gate(execute_agent_run)` wrapper 経由で keyword 引数 enqueue が atomic claim まで到達する (TypeError で落ちない) ことを検証。
- enqueue: shadow run_create で enqueue 呼ばれ、production run_create で呼ばれない (mock redis で検証)。**enqueue 失敗 (redis 例外) → 補償遷移で run `failed` (error_code=enqueue_dispatch_failed)、silent orphan を作らない** (R2-F1、queued 残置でないことを assert)。
