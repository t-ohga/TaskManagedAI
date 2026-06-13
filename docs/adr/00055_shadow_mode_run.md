---
id: "ADR-00055"
title: "Shadow Mode Run — side-effect 隔離付き shadow 実行 (P0.1 foundational increment)"
status: "accepted"
date: "2026-06-13"
authors:
  - "Claude (autonomous, user 承認 scope)"
related_sprints:
  - "SP-029_shadow_mode"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #2 (DB schema: `agent_runs` additive 列) + #4 (AI エージェント権限: shadow 実行の副作用境界) に該当する判断を記録する。実装前に proposed として作成し、plan-review + 合意後に accepted へ更新する。

最終更新: 2026-06-13

## 背景

- 決定対象: production state を一切変更せずに AI 実行を試走する **shadow run** を、AgentRun の不変条件 (16 状態 / `blocked_reason` 3 / ContextSnapshot 10 列) を壊さずに表現・実行する方法。SP-029 の foundational increment に限定。
- 関連 Sprint: SP-029_shadow_mode (P0.1)。P0 Exit (SP-011/011-5/012) は完了済。
- 前提 / 制約:
  - P0 invariant 不変: AgentRun 16 status / `blocked_reason` 3 / ContextSnapshot 10 列 / 22+ event types の exact set。
  - 既存 pipeline (`AgentRunOrchestrator.execute_provider_step`: provider call → Compliance Gate → preflight → execute → record_provider_usage(BudgetGuard) → schema validate → repair retry → transition_with_event) を再利用する。
  - Provider Compliance Matrix / `provider_request_preflight` / SecretBroker / tenant・project boundary は shadow でも **bypass しない**。
  - additive migration のみ (破壊的変更なし)。
  - **scope**: shadow run 実行 + telemetry capture (side-effect 隔離) に限定。A/B 比較 UI / provider bake-off / production telemetry baseline 集計は後続増分へ defer (本 ADR の対象外)。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: `agent_runs.run_mode` additive flag | `run_mode in ('production','shadow')` 列を additive 追加 (default `'production'`)。orchestrator が shadow 時に副作用 stage を skip。既存 pipeline / status / snapshot をそのまま再利用 | 16 status 不変、pipeline 再利用、KPI active-scope に `run_mode='production'` filter 1 個追加で分離、rollback = drop column | shadow 専用の副作用 skip を pipeline 全 mutating 経路 (approval / repo / runner / merge) で漏れなく enforce する必要 |
| B: 別 `shadow_runs` table (parallel model) | shadow を agent_runs と別 table で表現 | production data と物理分離 | pipeline / repository / status machine を二重化、event/snapshot/KPI も二系統化で複雑・drift リスク大、コード重複 |
| C: 新 status (`shadow_*`) を 16 status に追加 | shadow を status enum で表現 | status 1 個で判別 | **16 status 不変条件を破壊** (5+ source enum 全変更、Hard Gate fixture 影響)、P0 invariant 違反で却下 |

## 採用案

- 採用: **A (`agent_runs.run_mode` additive flag + orchestrator 副作用隔離)**
- 理由: P0 invariant (16 status 等) を一切変更せず、既存 pipeline を再利用でき、KPI 分離は active-scope に filter 1 個追加で済む。rollback は additive column の drop のみで安全。B は二系統化で drift リスク大、C は invariant 破壊で却下。
- 実装 Sprint: SP-029 (本 increment)
- 実装対象ファイル:
  - `backend/app/config.py` (`shadow_mode_enabled: bool = False` feature toggle + `shadow_run_max_cost_usd` per-run hard cap)
  - `migrations/versions/0048_*_agent_run_run_mode.py` (additive `run_mode` 列 + CHECK + default backfill)
  - `backend/app/db/models/agent_run.py` (`run_mode` Mapped 列 + CheckConstraint)
  - `backend/app/services/providers/usage_logger.py` (shadow cost を production budget accumulator に加算しない分岐)
  - `backend/app/domain/agent_runtime/run_mode.py` (`RunMode` Literal + `ALL_RUN_MODES` frozenset、5+ source 整合の正本)
  - `backend/app/services/agent_runtime/state_machine.py` (shadow 専用の run_mode-gated terminal transition を許可遷移表に追加)
  - `backend/app/services/agent_runtime/orchestrator.py` (shadow 時に副作用 stage を skip する境界)
  - `backend/app/services/agent_runtime/shadow_guard.py` (新規: shadow run が approval / repo / runner / merge / deploy を起動しないことを fail-closed で enforce する guard)
  - KPI / cost active-scope (`backend/app/services/eval/*` / `backend/app/services/metrics/*`): `cost_per_completed_task` 等の production KPI から `run_mode='shadow'` を除外
  - `frontend/lib/domain/agent-run.ts` 等: `run_mode` 表示 (Sprint 後続で UI)
- 実装ガイダンス:
  - **shadow の合法 terminal path (R1 plan-review HIGH #1 fix)**: 現 state machine は `completed` が `running -> completed` のみ。shadow は副作用 stage (waiting_approval / runner / repo) を通らないため、**`schema_validated -> completed` を `run_completed` event で許可する run_mode-gated transition を 1 本追加**する (新 status / 新 event_type は増やさない)。この edge は `run_mode='shadow'` の時のみ許可 (production は従来どおり waiting_approval -> running -> completed を必須とし、この edge を使えない) を transition guard で 4-layer enforce。shadow path = `queued -> gathering_context -> running -> generated_artifact -> schema_validated -> completed` (validation 失敗時は既存 `validation_failed`)。policy_linted / diff_ready (非 mutating check) の shadow 経由は後続増分で検討。
  - **副作用隔離 (fail-closed)**: shadow run では (1) ApprovalRequest 作成禁止 (2) RepoProxy 経由 repo write 禁止 (3) `runner_mutation_gateway` mutation 禁止 (4) merge / deploy 禁止 (P0 deny は元々)。これらは `shadow_guard` で「shadow run から呼ばれたら raise」する二重防御 (orchestrator が stage を skip + guard が誤呼び出しを拒否)。
  - **provider call は実行**: shadow でも Compliance Gate / preflight / SecretBroker mediated provider.call は通常どおり (compliance を bypass しない)。コストは `record_provider_usage` で `run_mode='shadow'` tag 付きで記録する。
  - **budget の扱い (R2/R3 plan-review HIGH fix、no-perturbation + 安全に使用可能)**: shadow が production を擾乱せず、かつ uncapped 暴走もしない両立を本増分で達成する:
    - (1) **production budget 保護**: `record_provider_usage` は shadow run の cost を `run.cost_usd` に `run_mode='shadow'` tag 付きで記録するが、**production budget accumulator / BudgetGuard の production budget enforcement に加算しない**。production budget は `run_mode='production'` の cost のみで判定され、**shadow spend で production run が budget_blocked になることはない** (非擾乱を test で保証)。
    - (2) **shadow per-run hard cap (本増分 must_ship)**: shadow run 自体の暴走を防ぐため、**`shadow_run_max_cost_usd` (config、per-run 上限) を常時 enforce** する。shadow run の累計 cost がこの上限を超えたら既存 `blocked` + `budget_blocked` へ遷移 (shadow も capped)。これにより shadow runtime は安全に使用・検証可能 (R3 #1 の「cap 未実装で runtime 受け入れ条件を満たせない」矛盾を解消)。per-tenant/project の aggregate cap は後続増分 (現状は明示作成のみで auto-trigger は対象外のため per-run cap で十分安全)。
    - (3) **`shadow_mode_enabled: bool = False` は feature toggle (default off、operator opt-in)**。safety は (1)+(2) が担保するため flag は「機能の有効/無効」であり「cap が無いから開けない gate」ではない。default off で誤って shadow が走らないようにしつつ、operator が有効化すれば per-run cap 下で安全に試走できる。
  - **cost KPI 分離**: shadow cost は `cost_per_completed_task` 等 production KPI から `run_mode='production'` filter で除外する (品質/コスト KPI を汚染しない)。
  - **telemetry**: shadow run の provider / model / cost_usd / tokens / latency / validation 結果 / artifact_hash は既存 AgentRun 列 + AgentRunEvent (新 event_type は追加しない、既存で表現) で capture。集計・比較は後続増分。
  - **audit**: shadow run も AgentRunEvent / AuditEvent を残す (raw secret なし、`run_mode` を payload に含む)。
  - **invariant**: 16 status / blocked_reason / ContextSnapshot 10 列 / event_type exact set は変更しない。`run_mode` は cross-source (DB CHECK / ORM / Literal / Pydantic / pytest EXPECTED_*) で整合。
- テスト指針:
  - `uv run pytest tests/agent_runtime/` state machine contract: **shadow run が `schema_validated -> completed` (run_mode-gated) で合法に完了**し、**production run は同 edge を使えない (deny)** ことを test。shadow も 16 status enum を辿る。
  - shadow 副作用隔離 negative test: shadow run から approval 作成 / repo write / runner mutation を試行 → 全件 deny (`shadow_guard` raise) + AuditEvent。
  - **production budget 非擾乱 test (必須)**: shadow run が provider cost を計上しても、同一 tenant/project の **production AgentRun の budget 判定が影響を受けない** (production budget accumulator に shadow cost が加算されず、production が budget_blocked にならない)。
  - **shadow per-run cap test (必須)**: shadow run の累計 cost が `shadow_run_max_cost_usd` を超えたら `blocked` + `budget_blocked` になる (shadow も capped、uncapped でない)。
  - **shadow disabled-by-default test**: `shadow_mode_enabled=false` (default) で shadow run の作成が deny される。
  - cost 分離 test: shadow run の cost が `cost_per_completed_task` 等 production KPI に**混入しない** (active-scope filter)。
  - cross-source enum test: `run_mode` の DB CHECK / ORM / Literal / Pydantic / pytest EXPECTED set 完全一致。
  - **migration 可逆性 test (CI、test DB、app 非稼働)**: 0048 down → up が test DB 上で既存行非破壊に通る (migration 正当性の検証であり、稼働中 app への production rollback 手順ではない。production rollback は下記 deploy-aware 手順を厳守)。
  - `uv run ruff check backend tests` + `uv run mypy backend`。

## 却下案

- B (別 shadow_runs table): pipeline / status machine / event / snapshot / KPI を二系統化し drift・コード重複リスクが大きい。additive flag で同等の分離が低コストに達成できるため却下。
- C (新 status を 16 に追加): AgentRun 16 status は P0 の CRITICAL invariant (5+ source 整合 + Hard Gate fixture)。shadow のために status を増やすと invariant 破壊・広範囲影響となるため却下 (SP-029 対象外明記とも一致)。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| shadow run が副作用経路を漏れなく隔離できず production state を変更 | shadow 副作用 negative test (approval/repo/runner/merge を試行→deny) | orchestrator stage skip + `shadow_guard` fail-closed の二重防御、全 mutating 経路を guard で網羅 |
| shadow run が合法 terminal に到達できず詰まる / 実体のない approval event を発行 | state machine contract test (shadow が `schema_validated -> completed` で完了、production は同 edge 不可) | run_mode-gated transition を許可遷移表に 1 本追加、4-layer で enforce、新 status/event は増やさない |
| shadow cost が production KPI (cost_per_completed_task) に混入 | cost 分離 test (shadow cost が KPI に出ない) | 全 production KPI active-scope に `run_mode='production'` filter |
| **shadow spend が production run を budget_blocked にする (production 擾乱)** | production budget 非擾乱 test (shadow cost で production budget 判定が変わらない) | `record_provider_usage` で shadow cost を production budget accumulator に**加算しない** (production は run_mode='production' cost のみで判定) |
| shadow run が uncapped で provider cost を暴走 | shadow per-run cap test (上限超過で budget_blocked) | `shadow_run_max_cost_usd` per-run hard cap を常時 enforce (shadow も capped)。`shadow_mode_enabled=false` の feature toggle と二重に安全側 |
| migration の即時 down を production rollback と誤認し稼働中 app を UndefinedColumn で停止 | rollback drill (deploy-aware 順序を検証)、CI 可逆性 test は app 非稼働の test DB に限定 | 0048 down は **cleanup-only**。production rollback は flag off → 互換コード → cleanup migration の順。CI の down→up は migration 正当性検証であり production 手順ではないと ADR/Sprint 両方で明記 |
| `run_mode` enum drift (source 間不整合) | cross-source enum test (exact set 比較) | DB CHECK / ORM / Literal / Pydantic / pytest EXPECTED の 5+ source 整合 |
| shadow run が provider compliance / preflight / SecretBroker を bypass | provider boundary test (shadow でも Compliance Gate / preflight 通過必須) | shadow は副作用のみ skip、provider 境界は通常経路を共有 (bypass 不可) |
| migration が既存行を破壊 | migration 可逆性 test (既存 agent_runs 行非破壊) | additive column + default `'production'` backfill、downgrade で drop のみ |

## rollback 手順

**deploy-aware rollback (R1 plan-review MEDIUM #3 fix)**: `run_mode` 列を ORM/Pydantic が参照する新コードが稼働したまま列を drop すると `UndefinedColumn` で AgentRun の全 read/write が落ちる (version skew)。よって列 drop は**即時 rollback step ではなく、コードを戻した後の cleanup migration に分離**する。

1. rollback trigger: shadow run が production state を変更した / cost KPI 汚染 / enum drift / budget 暴走が検出された場合。
2. rollback step (順序厳守):
   - (a) **`shadow_mode_enabled=false` に戻す** (default off。即時に新規 shadow run 作成を止める。`run_mode` 列はそのまま残す)。これだけで新規 shadow run は止まり、既存 production は無影響。
   - (b) 必要なら **全 app instance を `run_mode` 欠損に耐える旧/互換コードへ戻す** (ORM/Pydantic から run_mode 参照を除去 or nullable 互換)。
   - (c) 全 instance が (b) 完了後に**初めて** cleanup migration で `run_mode` 列を drop (additive のため既存 production 行のデータは非破壊)。即時には drop しない。
3. verification after rollback: 既存 production AgentRun が全件健在 (列 drop 前後で status/event 不変)、`cost_per_completed_task` 等 KPI が rollback 前後で一致、`uv run pytest tests/agent_runtime tests/metrics` PASS、稼働中 app で AgentRun read/write が UndefinedColumn を起こさない。
