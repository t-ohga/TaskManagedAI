---
id: "SP-004-5_agent_run_worker_driver"
type: "heavy"
status: "draft"
sprint_no: 4
created_at: "2026-06-13"
updated_at: "2026-06-13"
target_days: 2
max_days: 4
adr_refs:
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
  - "cancel service 化で明示 commit 漏れ → rollback で cancel/event 非永続 (R3-F1)"
  - "worker-crash-mid-drive で run 非終端残留 (durable resume 後続、R3-F2)"
  - "state machine additive edge が 16 status/event exact set を壊す (R2-F1/F2/R4-F1)"
  - "error→failed edge 不足で driver transient 例外時 stuck (R4-F1)"
  - "enqueue 引数 contract 不整合で worker dispatch TypeError (R4-F2)"
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
- **worker-crash-mid-drive の resume / reclaim** (R3-F2、atomic claim は queued のみ対象、transient state まで進めた run が crash 後 claim-miss で非終端残留 = silent loss ではないが自動 re-drive は後続。stale-run reclaim sweeper defer)
- **provider_incomplete の durable bounded retry** (R3-F2、retry_count 列 + resume 経路が必要。本 slice は provider_incomplete→即 failed)
- **bulk/superintendent cancel (api_bridge.py:1686) の event-append 統一** (R2-F2 派生 follow-up、driver は DB status で stop するため driver 動作には非影響、AgentRunEvent invariant 完全 close は別作業)

## 設計判断 (plan-review R1 F1-F5 + R2 F1-F3 反映、実コード照合済)

- arq task `execute_agent_run` + **shadow-only enqueue** (ADR-00057 §採用案)。全 run enqueue / 同期駆動は却下。
- 既存 orchestrator step / state machine / ContextSnapshot / BudgetGuard / Compliance Gate / SecretBroker を再利用 (再実装なし)。
- **atomic claim (F3)**: enqueue は run commit 後、task は `UPDATE agent_runs SET status='gathering_context' WHERE tenant_id=:t AND id=:r AND run_mode='shadow' AND status='queued' RETURNING *` で **claim**。**0 rows = benign loser → no-op return (failed にしない)**。concurrent worker / 二重 enqueue / production 誤 enqueue を single-flight + run_mode gate で防御。SP-029/SP-037 の concurrency 前提を満たす。
- **provenance binding (F4)**: ProviderRequest を先に構築 → ContextSnapshot input に exact fingerprint 格納 (placeholder 禁止)。snapshot/request/result fingerprint + matrix version + Artifact payload_data_class の相互一致を test 固定。
- **non-terminal closure 分離 + durable 終端 (F5 + R2-F3 + R3-F2)**: `validation_failed` → `execute_repair_decision_step` → `repair_exhausted` (同一 job 内完結、retry_count in-process)。`provider_incomplete` → **即 `failed`** (本 slice、durable retry counter 無し = R3-F2、in-process retry は worker crash で reset し終端保証を破る)。bounded retry (provider_incomplete→running) は durable counter + resume が要るため後続 defer。**`provider_incomplete -> repair_exhausted` は不許可**。
- **cancellation = post-commit DB-status 検知 + entrypoint 統一 + 明示 commit (F1 + R2-F2 + R3-F1)**: `cancel_agent_run` は **commit しない** (transition_with_event は caller が commit、signal は pre-commit best-effort、event_log.py:49-53 = R3-F1)。driver は **step 境界で post-commit DB status 再読**して cancelled 検知 → graceful stop (Redis transport 非依存、pre-commit signal にも非依存)。MCP `bridge_run_cancel` (現状 `run.status="cancelled"` 直接 set + commit、`run_cancelled` event 非 append = invariant 破壊、api_bridge.py:653) を `cancel_agent_run` 経由に統一 + **明示 commit を残す** (落とすと MCP session yield 後 rollback) + actor_id plumbing。
- **state machine additive 拡張 (R2-F1/F2 + R4-F1 由来、CRITICAL invariant、Python+test のみ migration 不要)**: 不変条件「driver-reachable な全 non-terminal → failed/cancelled exit 可能」を満たすため `{queued, gathering_context, generated_artifact, schema_validated, validation_failed}->failed`(run_failed、R4-F1: 既存 running 系のみだと transient で例外時 stuck) + `->cancelled`(run_cancelled、cancel 統一 regress 防止) を additive 追加 + `_CANCELABLE_STATES` 同集合拡張。production-only state (policy_linted/diff_ready/waiting_approval) は shadow driver 非進入で対象外。16 status / event exact set 不変。
- **enqueue 引数規約 (R4-F2)**: task `execute_agent_run(ctx, *, run_id, tenant_id)` は keyword-only → enqueue も keyword `enqueue_job("execute_agent_run", run_id=..., tenant_id=...)` 正本 (positional は wrapper 転送で worker TypeError → claim 前に落ち queued orphan)。`bridge_run_create` は `arq.create_pool` で pool 作成 → enqueue → close。wrapper 経由 dispatch test 必須。
- **enqueue 回復 = fail-closed (F2 + R2-F1)**: enqueue 失敗は呑まず **補償遷移で run `failed`** (error_code=enqueue_dispatch_failed) → silent orphan 禁止。「log + queued 残置」は R2-F1 で recovery でないと判明し不採用。自動 sweeper/outbox (transient 再試行) のみ後続 defer。
- error → failed、blocked → stop (resume 待ち、driver 再駆動しない)。concurrent status-change miss は failed でなく no-op (F3 benign)。

## 実装チケット / タスク一覧

1. `services/agent_runtime/state_machine.py` (additive、先に): `ALLOWED_TRANSITIONS` + `EVENT_TYPE_FOR_TRANSITION` に `{queued,gathering_context,generated_artifact,schema_validated,validation_failed}->failed`(run_failed、R4-F1) + 同集合 `->cancelled`(run_cancelled) 追加 + `cancel.py` `_CANCELABLE_STATES` 拡張。state machine test の `EXPECTED_*` 整合 (5+ source)。
2. `workers/agent_run_driver.py`: `execute_agent_run(ctx, *, run_id, tenant_id)` — gate verify → **atomic claim (F3、`UPDATE...RETURNING`、claim-miss=no-op)** + 同一 tx で context_gathered event + ContextSnapshot(F4 exact fingerprint) → running → execute_provider_step(Mock) → execute_validation_step → execute_shadow_completion_step → **non-terminal 分離 closure (F5+R2-F3+R3-F2: validation_failed→repair→repair_exhausted / provider_incomplete→即 failed)** → **step 境界 post-commit DB-status cancel 検知 (F1+R2-F2+R3-F1)** → error→failed。
3. `workers/main.py`: `functions` に `with_active_registry_gate(execute_agent_run)` 追加。
4. `mcp/api_bridge.py` `bridge_run_create`: shadow run commit 後に **keyword 引数 enqueue** (`arq.create_pool` → `enqueue_job("execute_agent_run", run_id=..., tenant_id=...)` → close、production 非 enqueue、R4-F2)。**enqueue 失敗 → 補償遷移で run failed (error_code=enqueue_dispatch_failed、R2-F1 fail-closed)**。
5. **cancel entrypoint 統一 (F1+R2-F2+R3-F1)**: `mcp/api_bridge.py` `bridge_run_cancel` を `cancel_agent_run` 経由に統一 (run_cancelled event + signal) **+ 呼出後に明示 commit** (transition_with_event は commit しないため、R3-F1) + `mcp/server.py` `run_cancel` に actor_id plumbing。
6. **provenance binding (F4)**: ProviderRequest を先に構築する helper + ContextSnapshot input に exact fingerprint 格納 (10 列 driver default)、Artifact (mock structured output)、ProviderRequest (shadow payload_data_class)。
7. test: DB-gated end-to-end 駆動 / **atomic claim concurrent (benign-loser-not-failed、F3)** / **非 queued run 再駆動=no-op (crash 後 arq 再実行の安全性、R3-F2)** / **wrapper 経由 keyword dispatch が claim まで到達 (TypeError なし、R4-F2)** / **enqueue 失敗→failed (silent orphan なし、R2-F1)** / **各 driver state (gathering_context/running/generated_artifact/schema_validated/validation_failed) で例外注入→その state から failed (stuck なし、R4-F1)** / production 非駆動・非 enqueue / blocked stop / **cancel parity (REST + MCP 両方で run_cancelled event を実 DB に永続 + driver stop、R2-F2+R3-F1)** / transient state cancel (新 edge) / **non-terminal 分離 (validation_failed→repair_exhausted、provider_incomplete→即 failed、running/repair_exhausted に行かない assert、R2-F3+R3-F2)** / **provenance fingerprint 一致 (F4)** / state machine 新 edge の EXPECTED_* / ContextSnapshot+Artifact+event timeline 検証。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer |
|---|---|---|
| shadow run end-to-end 駆動 (queued→completed、Mock) | ✓ | |
| shadow-only enqueue (production 非 enqueue) | ✓ | |
| **atomic claim single-flight (F3、claim-miss=no-op、concurrent 二重駆動防止)** | ✓ | |
| **provenance binding exact fingerprint (F4、placeholder 禁止)** | ✓ | |
| **post-commit DB-status cancel + entrypoint 統一 + 明示 commit (F1+R2-F2+R3-F1、REST+MCP DB 永続 parity)** | ✓ | |
| **state machine additive edge (全 driver non-terminal → failed/cancelled、R2-F1/F2+R4-F1)** | ✓ | |
| **enqueue keyword dispatch contract (wrapper 経由 claim 到達、R4-F2)** | ✓ | |
| **non-terminal closure 分離 (validation_failed→repair_exhausted / provider_incomplete→即 failed、F5+R2-F3+R3-F2)** | ✓ | |
| **enqueue 失敗 fail-closed (補償 failed、silent orphan 禁止、R2-F1)** | ✓ | |
| **非 queued run 再駆動=no-op (crash 後 arq 再実行で double-drive しない、R3-F2)** | ✓ | |
| error→failed / blocked→stop | ✓ | |
| ContextSnapshot input + Artifact + event timeline | ✓ | |
| provider mid-call kill | | ✓ |
| **worker-crash-mid-drive の resume/reclaim sweeper (R3-F2、非終端残留は可視・非 silent)** | | ✓ |
| **provider_incomplete durable bounded retry (durable counter + resume、R3-F2)** | | ✓ |
| orphan の transient 自動 sweeper / outbox (R2-F1 fail-closed 済、自動再試行のみ defer) | | ✓ |
| bulk/superintendent cancel の event-append 統一 (api_bridge.py:1686、R2-F2 派生 follow-up) | | ✓ |
| production runtime / real provider | | ✓ |
| 実 prompt pack 配線 (driver default lock の精緻化) | | ✓ |

## 受け入れ条件

- [ ] shadow run を作成 → `execute_agent_run` で `completed` 到達、event timeline (context_gathered → provider_requested → provider_responded/artifact_generated → schema_validated → run_completed) + ContextSnapshot input (10 列) + Artifact 生成を検証。
- [ ] **(F3) atomic claim**: 同一 shadow run へ concurrent に 2 回駆動 → 1 個だけ claim 成功、他は no-op (status 不変、failed にならない)。queued でない run も no-op。
- [ ] production run を `execute_agent_run` に渡すと no-op (atomic claim の run_mode='shadow' 条件で claim-miss)。
- [ ] **(F4) provenance**: ContextSnapshot input fingerprint == ProviderRequest fingerprint == provider result fingerprint、matrix version 一致、Artifact payload_data_class 一致 (placeholder = test fail)。
- [ ] **(F5+R2-F3+R3-F2) non-terminal 分離 + durable 終端**: Mock forced `validation_failed` → repair loop → `repair_exhausted` terminal。Mock forced `provider_incomplete` → **即 `failed`** (**`running` にも `repair_exhausted` にも行かないことを assert**)。refusal → `provider_refused`。unsupported_schema/schema_mismatch も close。
- [ ] **(R3-F2) crash 安全性**: 非 queued (transient/terminal) run を `execute_agent_run` に再投入 → claim-miss no-op (double-drive しない)。crash 後 arq 再実行が安全。
- [ ] **(R4-F1) error→failed 全 state 網羅**: gathering_context/running/generated_artifact/schema_validated/validation_failed の各時点で例外注入 → その state から `failed` 終端化 (stuck non-terminal が出ないことを各 state で assert)。
- [ ] **(R4-F2) enqueue dispatch contract**: `with_active_registry_gate(execute_agent_run)` wrapper 経由で keyword 引数 enqueue が TypeError なく atomic claim まで到達。
- [ ] **(F1+R2-F2+R3-F1) cancel parity + DB 永続**: REST `cancel_agent_run`(+commit) と MCP `run_cancel` の **両方**で `run_cancelled` event が **実 DB に永続** + driver が step 境界 post-commit DB-status 検知で stop。queued / transient state からの cancel も新 edge で `run_cancelled` 付き cancelled 到達。MCP cancel で session commit が落ちず status/event が永続することを DB-gated で検証。
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
- **worker-crash-mid-drive の自動 recovery なし (R3-F2)**: transient state まで進めた run が crash すると非終端で残る (status で可視、silent loss でない、atomic claim で double-drive は防止)。resume/reclaim sweeper は後続。foundational scope の明示的限界。
- **provider_incomplete は即 failed (R3-F2)**: durable retry counter 不在のため bounded retry は後続。試走では incomplete=failed で許容。
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

**scope 再評価 (R2)**: R2 により state machine additive 拡張 (queued→failed / transient→cancelled) + MCP cancel API 契約変更 (actor_id) が in scope に追加。

(2026-06-13 plan-review R3、**no-ship**) R2 fix を再レビュー、**2 HIGH 追加、全 adopt** (実コード照合済):
- **R3-F1 (HIGH) cancel_agent_run は DB-first commit でない**: `transition_with_event` は commit せず caller が `session.begin()` で wrap (event_log.py:49-53)。MCP `get_db_session` は yield のみ → `bridge_run_cancel` を service 化する際 **明示 commit を残さないと rollback** され cancel/event 非永続。signal も pre-commit。→ driver 正本を **post-commit DB status 再読**に正確化、bridge_run_cancel に明示 commit、MCP integration test は実 DB 永続まで検証。
- **R3-F2 (HIGH) provider_incomplete bounded retry が durable でない**: retry_count 列なし、execute_repair_decision_step は validation_failed 専用、worker crash + arq 再実行は claim-miss で非終端残留。→ 本 slice は **provider_incomplete → 即 failed** (durable counter / resume は後続 defer)。worker-crash-mid-drive の resume/reclaim も後続 defer (atomic claim は double-drive 防止、crashed run は非終端で可視・silent loss なし)。

**scope 確定 (R3)**: foundational scope を **最小 robust** に確定 — happy-path 駆動 + atomic claim + cancel (post-commit DB-status + entrypoint 統一 + 明示 commit) + enqueue fail-closed + provenance + non-terminal closure (validation_failed→repair_exhausted / provider_incomplete→即 failed) + state machine additive edge。**durability hardening + production runtime は明示 defer**。

(2026-06-13 plan-review R4、**no-ship**、tactical) R3 fix を再レビュー、**2 HIGH 追加、全 adopt** (実コード照合済、tactical):
- **R4-F1 (HIGH) error→failed の edge 不足**: state machine の `failed` edge は running/provider_incomplete/blocked のみ。driver が gathering_context/generated_artifact/schema_validated/validation_failed まで commit 後に例外を起こすと終端化できず stuck (通常例外経路)。→ `failed` edge を **driver-reachable な全 non-terminal state** から additive 追加 (不変条件「全 driver non-terminal → failed/cancelled exit 可能」)。
- **R4-F2 (HIGH) enqueue 引数 contract 不整合**: keyword-only signature に positional enqueue → wrapper 転送で worker TypeError → claim 前に落ち queued orphan。→ keyword enqueue に統一 + wrapper 経由 dispatch test。

**doc plan-review 完了判断 (R4)**: R1→R2→R3→R4 = 計 12 findings 全 adopt、finding 推移は 5→3→2→2 と収束し R4 は tactical (edge 網羅 / 引数規約、design は sound)。doc review の限界収益 < 実コード review のため、**doc plan-review は R4 fix 反映で完了**とし、残る tactical correctness は **実装後の Codex adversarial loop (実コード review、§14.1 CRITICAL gate)** を authoritative gate とする。

(2026-06-13 **ADR-00057 accepted 昇格**、§sprint-pack-adr-gate §12) 実装着手直前に ADR-00057 を proposed → accepted 昇格 (codex-plan-review R1-R4 + 採否判定 = §12.4 hard gate 充足、minimum R1 を大幅に超過)。§12.1 promotion 条件: must_ship 受け入れ条件と矛盾なし / 関連 rules (agentrun-state-machine: additive edge は 16 status・event exact set 不変で整合) / DD-02 ADR-00004 state machine 整合 / `planned_adr_refs` → `adr_refs` 移動済。accepted_at: 2026-06-13。次: Codex-first 実装 → adversarial loop findings_zero (CRITICAL=0/HIGH≤2) → CI green → user merge。
