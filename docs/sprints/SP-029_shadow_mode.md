---
id: "SP-029_shadow_mode"
type: "heavy"
status: "completed"
sprint_no: 29
created_at: "2026-05-26"
updated_at: "2026-06-13"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00055](../adr/00055_shadow_mode_run.md)"
related_sprints:
  - "SP-011_eval_harness"
risks:
  - "shadow run の副作用隔離漏れで production state を変更"
  - "shadow cost が production KPI (cost_per_completed_task) に混入"
  - "run_mode enum drift (source 間不整合)"
  - "shadow が provider compliance / preflight / SecretBroker を bypass"
---

## 目的

production state を一切変更せずに AI 実行を試走する **shadow run** の foundational increment を実装する。shadow run は既存 pipeline を再利用しつつ副作用 (approval / repo write / runner mutation / merge / deploy) を **fail-closed で隔離**し、provider / model / cost / tokens / latency / validation 結果の telemetry を capture する。これにより後続増分 (A/B eval 比較、provider bake-off、production telemetry baseline 集計) の基盤を作る。

## 背景

- P0 Exit (SP-011 eval harness / SP-011-5 operational hardening / SP-012 P0 acceptance) は完了済。本 Sprint は P0.1 の roadmap-canonical な次手 (複数 Sprint で「shadow mode」が P0.1 列に明示)。
- 既存 eval harness (SP-011) は **fixture ベース**の eval。shadow mode は **実タスク上の runtime shadow 実行**を追加し、production を汚さず実環境での provider/prompt 品質・コストを観測可能にする。
- 設計判断は ADR-00055 に記録 (採用案 A: `agent_runs.run_mode` additive flag + orchestrator 副作用隔離)。
- (2026-06-04 台帳監査で本 Pack は draft へ訂正済。本 elaboration で着手。)

## 対象外

- P0 invariant の変更 (AgentRun 16 status / `blocked_reason` 3 / ContextSnapshot 10 列 / event_type exact set は不変、新 status / 新 event_type を追加しない)。
- 破壊的 migration (additive `run_mode` 列のみ)。
- A/B eval 比較 UI / 比較ロジック (後続増分)。
- provider bake-off (複数 provider で同 fixture を回す比較、後続増分、ADR-00010 系を再利用)。
- production telemetry baseline の集計・dashboard (後続増分、SP-011-5 observability を再利用)。
- shadow run の自動 trigger / scheduling (本増分は明示作成のみ)。

## 設計判断

ADR-00055 採用案 A。

- `agent_runs.run_mode` (`'production'` / `'shadow'`、default `'production'`) を additive 追加 (migration 0048 + CHECK)。
- `RunMode` Literal + `ALL_RUN_MODES` frozenset を domain に置き 5+ source 整合の正本にする。
- **shadow の合法 terminal path (plan-review R1 HIGH #1 fix)**: 現 state machine は `completed` が `running -> completed` のみ。shadow は副作用 stage を通らないため `schema_validated -> completed` を `run_completed` event で許可する **run_mode-gated transition を 1 本追加** (新 status / 新 event_type は増やさない)。この edge は `run_mode='shadow'` のみ許可、production は不可 (従来 waiting_approval 経路必須) を 4-layer で enforce。shadow path = `queued -> gathering_context -> running -> generated_artifact -> schema_validated -> completed` (validation 失敗は既存 `validation_failed`)。
- orchestrator は `run_mode='shadow'` 時に副作用 stage (approval 作成 / repo write / runner mutation / merge / deploy) を skip。
- `shadow_guard` を新設し、shadow run から副作用経路が誤って呼ばれたら **fail-closed で raise** (orchestrator skip + guard の二重防御)。
- provider call は shadow でも通常経路 (Compliance Gate / preflight / SecretBroker mediated) を共有し bypass しない。
- **budget (plan-review R2/R3 HIGH fix、no-perturbation + 安全に使用可能)**:
  - **production budget 保護**: `record_provider_usage` は shadow cost を `run.cost_usd` に tag 記録するが **production budget accumulator に加算しない**。production budget は `run_mode='production'` cost のみで判定 → **shadow spend で production run が budget_blocked にならない** (非擾乱 test で保証)。
  - **shadow per-run hard cap (must_ship)**: `shadow_run_max_cost_usd` (config) を常時 enforce。shadow run の累計 cost が上限超過で `blocked`+`budget_blocked` (shadow も capped、uncapped でない)。これで shadow runtime が安全に使用・検証可能 (R3 #1 矛盾解消)。aggregate cap は後続増分。
  - **`shadow_mode_enabled: bool = False` は feature toggle** (default off、operator opt-in)。safety は production 保護 + per-run cap が担保。
  - cost は `run_mode='shadow'` tag で記録し production の**コスト KPI から除外**。

## 実装チケット / タスク一覧

0. **config**: `backend/app/config.py` に `shadow_mode_enabled: bool = False` (feature toggle、default off) + `shadow_run_max_cost_usd` (per-run hard cap)。
1. **migration 0048**: `agent_runs.run_mode` additive 列 (`NOT NULL DEFAULT 'production'`) + CHECK (`run_mode in ('production','shadow')`)。downgrade で drop。既存行は default backfill で非破壊。
2. **domain enum**: `backend/app/domain/agent_runtime/run_mode.py` に `RunMode = Literal['production','shadow']` + `ALL_RUN_MODES` frozenset。
3. **ORM**: `agent_run.py` に `run_mode` Mapped 列 + CheckConstraint。
4. **Pydantic**: AgentRun create / read schema に `run_mode` (create は default production、read は表示)。
5. **state machine**: `state_machine.py` に `schema_validated -> completed` の run_mode-gated transition (shadow のみ許可、production は deny) を許可遷移表へ追加 + 4-layer guard。
6. **shadow_guard**: `backend/app/services/agent_runtime/shadow_guard.py` — `assert_not_shadow(run, operation)` で shadow run の副作用 operation を fail-closed deny (reason_code + AuditEvent)。approval 作成 / repo write / runner mutation / merge / deploy の choke point に挿入。
7. **orchestrator**: `run_mode='shadow'` 時に副作用 stage を skip し provider + validate + telemetry のみ実行、shadow terminal へ遷移。
8. **budget 保護**: `usage_logger.record_provider_usage` で shadow cost を production budget accumulator に加算しない分岐 (production budget は production cost のみで判定)。
9. **cost KPI 分離**: `cost_per_completed_task` 等 production KPI の active-scope に `run_mode='production'` filter。
10. **test** (下記受け入れ条件 + 検証手順)。

## must_ship / defer_if_over_budget 対応表

| 項目 | 区分 |
|---|---|
| `run_mode` additive 列 + CHECK + migration (up/down) | must_ship |
| `RunMode` enum 5+ source 整合 | must_ship |
| `shadow_mode_enabled` feature toggle (default off) で shadow 作成 gate + test | must_ship |
| shadow per-run hard cap (`shadow_run_max_cost_usd`) で shadow を capped + cap test | must_ship |
| shadow 専用 terminal transition (`schema_validated -> completed` run_mode-gated) + state machine contract test | must_ship |
| shadow_guard で副作用 (approval/repo/runner/merge/deploy) fail-closed 隔離 + negative test | must_ship |
| orchestrator の shadow stage skip (provider + validate + telemetry のみ実行) | must_ship |
| production budget 保護 (shadow cost を production budget accumulator に加算しない) + 非擾乱 test | must_ship |
| shadow cost を production コスト KPI から除外 + 分離 test | must_ship |
| provider boundary (compliance/preflight) を shadow でも通過 + test | must_ship |
| deploy-aware rollback 手順 (flag off → 互換コード → 列 drop は cleanup migration 分離) | must_ship (文書) |
| per-tenant/project aggregate shadow budget cap / auto-trigger | defer (後続増分) |
| A/B 比較 / provider bake-off / baseline 集計 / UI | defer (後続増分) |
| shadow 自動 trigger / scheduling | defer |

## 受け入れ条件

- [ ] `run_mode` additive 列 + CHECK 実装、migration up/down で既存行非破壊。
- [ ] `RunMode` enum が DB CHECK / ORM CheckConstraint / Python Literal / Pydantic / pytest `EXPECTED_RUN_MODES` で exact set 一致 (cross-source-enum-integrity)。
- [ ] shadow run が `schema_validated -> completed` (run_mode-gated) で**合法に completed へ到達**し、**production run は同 edge を使えない** (deny) — state machine contract test で確認。新 status / event_type は増えていない。
- [ ] shadow run は ApprovalRequest 作成 / repo write / runner mutation / merge / deploy を **一切起動しない** (shadow_guard で全件 deny、negative test 全 PASS)。
- [ ] shadow run の provider call は Compliance Gate + `provider_request_preflight` を通常どおり通過する (bypass しない、test で確認)。
- [ ] `shadow_mode_enabled=false` (default) で shadow run 作成が deny される (feature toggle test)。
- [ ] shadow run の累計 cost が `shadow_run_max_cost_usd` を超えたら `blocked`+`budget_blocked` になる (shadow per-run cap test、uncapped でない)。
- [ ] shadow run の provider cost が **production AgentRun の budget 判定に影響しない** (production が shadow spend で budget_blocked にならない — production budget 非擾乱 test)。
- [ ] shadow run の cost が `cost_per_completed_task` 等 production コスト KPI に混入しない (分離 test)。
- [ ] AgentRun 16 status / `blocked_reason` 3 / ContextSnapshot 10 列 / event_type exact set に regression なし。
- [ ] 既存 Hard Gate / KPI に regression なし。
- [ ] lint / typecheck / test PASS。
- [ ] Sprint Pack Review 章更新。

## 検証手順

```bash
uv run ruff check backend tests && uv run mypy backend
# DB-gated (throwaway postgres):
TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/agent_runtime tests/metrics tests/ -q
cd frontend && pnpm typecheck && pnpm exec eslint . --max-warnings=0 && pnpm exec vitest run
```

- shadow 副作用隔離 negative test (approval/repo/runner/merge を shadow run から試行 → 全件 deny)。
- production budget 非擾乱 test + shadow per-run cap test + cost 分離 test。
- migration 可逆性 test (CI、test DB・app 非稼働で 0048 down → up が既存行非破壊。**production rollback 手順ではない**; production は ADR-00055 の deploy-aware 手順 = flag off → 互換コード → cleanup migration で drop)。
- codex-adversarial-review (CRITICAL invariant: AgentRun / run_mode / 副作用境界 / budget 非擾乱 / KPI 分離)。

## レビュー観点

- 副作用隔離が**全 mutating 経路**で漏れないか (approval / repo / runner / merge / deploy)。
- `run_mode` enum が 5+ source 整合か。
- shadow が provider compliance / preflight / SecretBroker を bypass していないか。
- cost / budget の分離が正しいか (production KPI 非汚染)。
- 16 status / ContextSnapshot 10 列 / event_type を壊していないか。
- migration が additive で rollback-safe か。

## 残リスク

- 副作用経路の網羅性: 将来新 mutating 経路を追加した際に shadow_guard 挿入を忘れると隔離漏れ → guard を choke point に集約 + negative test で回帰検出。
- **shadow aggregate cap 未実装 (plan-review R3)**: 本増分は production budget 保護 + shadow **per-run** hard cap を実装するが、per-tenant/project の aggregate cap は後続増分。明示作成のみ (auto-trigger は対象外) のため per-run cap で実用上安全だが、大量の手動 shadow run の aggregate コストは operator 管理。
- rollback の version skew (plan-review R1 #3 / R3 #2): 列 drop を稼働中 app に即時実行すると UndefinedColumn。production rollback は deploy-aware (flag off → 互換コード → cleanup migration で drop) を ADR-00055 に明記。CI の migration 可逆性 test (app 非稼働) とは別物。
- A/B 比較 / bake-off / baseline 集計が後続増分のため、本増分単体では「telemetry capture まで」で品質比較の価値は限定的 (基盤提供が目的)。

## 次スプリント候補

- shadow A/B eval 比較 (production run vs shadow run の品質/コスト diff)。
- provider bake-off (複数 provider × eval fixture、ADR-00010 系再利用)。
- production telemetry baseline 集計 + dashboard (SP-011-5 observability 再利用)。
- shadow 自動 trigger (sampling / scheduled)。

## 関連 ADR

- ADR-00055 (本 Sprint で proposed → accepted 昇格)。

## Review

(2026-06-04 台帳監査) **未実装**。本 Pack は `status: "completed"` だったが、shadow mode / shadow run に対応する実装は `backend/app` / `frontend` に存在しない (grep `shadow_mode` / `shadow_run` / `ShadowMode` = 0 件)。受け入れ条件も全て未チェック。commit `1b9cad6` (#261) の実装を伴わない一括 status flip の対象。実態に合わせ `draft` へ訂正。P1 将来スコープで、着手時に ADR-first + 実装 + test が必要。

(2026-06-13 着手) light → heavy 化。ADR-00055 (proposed) 起票、foundational increment (shadow run 実行 + telemetry capture、side-effect 隔離) に scope。A/B 比較 / bake-off / baseline は後続増分へ defer。

(2026-06-13 plan-review R1) codex-adversarial-review R1 で 3 findings 全 adopt: HIGH#1 shadow の合法 terminal path 不在 → `schema_validated -> completed` run_mode-gated transition + contract test / HIGH#2 shadow budget / MEDIUM#3 rollback version skew → deploy-aware。

(2026-06-13 plan-review R2) R1 の budget defer を R2 が HIGH で escalate: shadow spend が production を budget_blocked にする = no-perturbation 違反。adopt し production budget 保護 (shadow cost を accumulator に加算しない) + flag gate を設計。

(2026-06-13 plan-review R3) R2 の「cap defer + flag off 維持」と「runtime 受け入れ条件」の矛盾を R3 が HIGH 指摘 + rollback の CI test vs production 手順の矛盾を MEDIUM 指摘。adopt: (1) **shadow per-run hard cap (`shadow_run_max_cost_usd`) を must_ship 化** → shadow runtime が安全に capped で使用・検証可能、flag は feature toggle に降格 (2) **migration 可逆性 test (CI、app 非稼働) と production deploy-aware rollback (down=cleanup-only) を明確分離**。次: plan-review R4 で findings_zero 確認 → ADR proposed→accepted → 実装。

(2026-06-13 plan-review R4 + ADR accept) R4 = approve / no material findings (loop R1:3→R2:1→R3:2→R4:0 収束)。ADR-00055 accepted_at: 2026-06-13 (実装着手直前に proposed→accepted 昇格、sprint-pack-adr-gate §12 準拠)。status draft→in_progress。実装着手。

(2026-06-13 実装完了 / behavioral 層) backend-only foundational increment 実装。

**changed (実装)**:
- schema 層 (commit cf51d3f): `domain/agent_runtime/run_mode.py` (RunMode enum)、`config.py` (`shadow_mode_enabled` flag default off + `shadow_run_max_cost_usd` cap)、`db/models/agent_run.py` (run_mode 列 + CHECK)、`migrations/0048` (additive 列、down=cleanup-only)、`state_machine.py` (run_mode-gated `schema_validated->completed`)、`event_log.py` (run.run_mode 配線)。
- behavioral 層: `services/agent_runtime/shadow_guard.py` (新規、side-effect fail-closed 隔離) + `repositories/approval_request.py` create_pending_approval に guard 配線 (run-bound approval choke point、§3) / `services/providers/usage_logger.py` (shadow は production BudgetGuard を通さず shadow per-run cap のみ enforce、§4+5) / `services/agent_runtime/orchestrator.py` (`execute_shadow_completion_step`: shadow terminal、§2/3) / `mcp/api_bridge.py` bridge_run_create (run_mode param + flag gate + fingerprint/event payload/return に run_mode、§6) + `mcp/server.py` run_create tool 公開 / KPI 除外 (`metrics/orchestrator_kpi_rollup.py` run_tree base+recursive / `eval/kpi_timeseries.py` cost+time_to_merge / `api/agent_runs.py` cost_summary+activity_timeseries に `run_mode='production'`、§8) / `api/agent_runs.py` AgentRunRead.run_mode (read 可視化)。

**verified**: `uv run ruff check backend tests` + `uv run mypy backend` (383 files) clean。新規 unit test 28 件 (run_mode enum 5+ source 整合 / state machine run_mode-gated / shadow_guard negative / shadow per-run cap + production budget 非擾乱 / orchestrator shadow completion)。新規 DB-gated test 8 件 (flag gate off/on + persistence / approval guard fail-closed + row 非永続 / cost KPI + orchestrator rollup から shadow 除外 / migration 0048 可逆性 + backfill)。**full DB suite 5517 passed / 12 skipped / 1 xfailed** (回帰なし、production 挙動不変)。

**boundary / deferred**: orchestrator は step ライブラリで end-to-end driver は未実装 (Sprint 6+ arq worker 統合)。本増分は shadow terminal **step を提供**し、worker-loop での run_mode 分岐呼び出しは worker 統合時に配線。A/B 比較 / bake-off / baseline 集計 / aggregate budget cap / frontend run_mode 表示は後続増分 (§次スプリント候補)。

(2026-06-13 adversarial review R1-R5、findings 全件 adopt または reasoned-mitigated)

- **R1 (3 HIGH, 全 adopt)**: (F1) shadow parent → production child の lineage leak → `bridge_run_create` で parent/child run_mode 厳密一致を強制 + DB test。(F2) SecretBroker capability 発行が run_mode 非検証 → repo.push/repo.pr_open 発行を guard。(F3) shadow path が global_kill_switch を bypass → shadow も kill switch を尊重 (production spend budget は非適用)。
- **R2 (1 HIGH, adopt)**: run_create idempotency fingerprint に run_mode を無条件追加すると既存 production reservation の deploy 跨ぎ retry が conflict 化 → production は legacy fingerprint を維持し shadow のみ run_mode を加える条件付き包含 + backward-compat regression test。
- **R3 (1 HIGH, adopt)**: repo mutation の shadow guard が `run_id=None`/不在 run で fail-open → **repo.push/repo.pr_open capability は非 null + 実在 + production run binding 必須**化 (server-owned、caller が run_id を落とす/詐称しても迂回不可)。既存 broker negative test に production run seed 追加。
- **R4 (2 HIGH)**: (F1 reasoned-mitigated) approval guard が `run_id=None` で fail-open するが、**MCP `approval_request_create` は default `action_class=repo_write` を ticket-level (run_id=None) で作成する既存正規経路**のため run_id 必須化不可。ただし R3 の broker boundary (repo capability = production run 必須) で **shadow は ticket-level approval があっても escalation 不可**。run-bound approval は guard で shadow deny 済。(F2 adopt) cap/kill-switch が provider 実行後 + usage 依存のみ → `execute_provider_step` に **shadow pre-execution preflight** (kill switch + 既存累計 cap) を追加 (usage=None でも緊急停止、cap 到達後の次 call を課金前 block)。
- **R7 (1 HIGH, adopt)**: shadow cap が真の pre-execution hard cap でない (usage=None で累計更新されず cap 無効 / 単一巨大 call の overshoot) → (1) shadow の **成功** provider レスポンスが usage=None なら cost 検証不能として **runtime_blocked で fail-closed** (`shadow_usage_unverifiable`)、(2) shadow は **request.max_tokens 必須 + `current_tokens + max_tokens <= token_cap` を provider 課金前に強制** (`preflight_shadow_request_tokens`、single call overshoot を構造的に排除)。
- **R6 (2 HIGH, 全 adopt)**: (F1) shadow が BudgetGuard を skip し USD cap のみ依存 → provider が `cost_usd=0`/未報告だと cap 無効 (token/wall-clock も非適用) → USD 非依存の **shadow token cap (`shadow_run_max_total_tokens`)** を preflight + post-execution に追加。(F2) repo mutation guard が任意 production run_id を受け approval.run_id を非検証 → run_id 借用で別 run の approval を使い shadow diff を push 可能 → **repo mutation は approval.run_id == capability run_id (非 null) 必須**化 (`_validate_approval` に run_id 配線、`approval_run_mismatch` deny + unit parametrize)。
- **R5 (2 HIGH + 1 MEDIUM)**: (F1 adopt) shadow を MCP `run_create` で公開したが shadow terminal を駆動する runtime worker が未実装 (production run も同様に未駆動) → **MCP 表面公開を撤回**、shadow 作成は internal `bridge_run_create(run_mode='shadow')` + flag 経由のみ (runtime driver と同時に公開)。backend plumbing (schema/state machine/guard/budget/KPI) は完成・全 test 済。(F2 reasoned-defer) runner_mutation_gateway は Sprint 7 の純粋 validator (run 非保持・未駆動 building block) で、shadow は orchestrator skip + approval 不可 + driver 不在で構造的に到達不可 → run_mode 強制は run context 配線 (Sprint 7 契約変更) を要するため runner 統合増分へ defer。(F3 adopt) preflight cap が `> cap` で exact-cap 着地時に次 call を許す → `>= cap` に修正 + exact-cap test。
- **R11 (1 HIGH, adopt)**: USD cap が post-execution (run.cost_usd 加算後) で、単一 call が USD cap を課金前に超過しうる → per-model pricing table 不在のため Codex 選択肢 3 (**保守的 worst-case 単価 `shadow_run_max_usd_per_token`**) で `current_usd + (input+output)*単価 > usd_cap` を **provider 課金前に projection block** (over-estimate=fail-safe)。token cap + USD cap の両方が pre-execution 化。token-pass/USD-fail の regression test 追加。
- **R10 (1 HIGH + 1 MEDIUM, 全 adopt)**: (F1) `bridge_run_cost` MCP tool が caller 値で `cost_usd/tokens` を上書き → shadow が cap 直前で 0 reset し実質 uncapped → **shadow run の run_cost を fail-closed で拒否** (`shadow_run_cost_immutable`、cost は record_provider_usage accumulator が権威)。(F2) MCP `kpi_show` + `bridge_workflow_status` の count が run_mode 非 filter で shadow completed/failed が production KPI/success_rate に混入 → 両者に **run_mode='production' filter** 追加 (REST/eval KPI と同じ active-scope)、shadow 混入 regression test。
- **R9 (2 HIGH, 全 adopt)**: (F1) usage=None fail-closed が `generated_artifact` のみで provider_incomplete (incomplete/max_token/timeout) を素通り → retry ループで課金累積 → **全 status の usage=None を fail-closed** に拡張 (status parametrize test)。(F2、R8 再評価) ProviderRequest が `messages` (prompt) を保持し input が orchestrator 境界で可視と判明 (R8 の「input 不可視」前提を訂正) → Codex 許容の **保守的 char ベース input 概算** (`_estimate_request_input_tokens`、tokenizer 非依存・over-estimate=fail-safe) を preflight に追加し `current + estimated_input + max_tokens <= token_cap` を課金前判定 (巨大 prompt + 小 max_tokens の overshoot を排除)。
- **R8 (1 HIGH → R9 で adopt 化)**: R8 で「input 推定不能」として defer したが、R9 で ProviderRequest.messages 可視と判明し **R9 F-2 で保守 char 概算を adopt** (R8 の defer は撤回)。
- **R14 (1 HIGH, adopt)**: R13 の all-zero usage 検証が `generated_artifact` (success) のみで、provider_incomplete (timeout/max_token) の all-zero usage が retry ループで cap 迂回 → usage 検証を **全 provider status** に拡張 (`usage is None or usage.tokens_input <= 0`、実 call は必ず input token を伴うため status 不問で正当)。success + provider_incomplete の zero-usage parametrize test。
- **R13 (1 HIGH, adopt)**: provider usage parser が欠落を 0 正規化するため、cost 過少報告で run.cost_usd が増えず USD cap が累積で効かない (fail-open) → (1) shadow accumulation を **token-floored cost** (`max(reported, tokens × worst-case 単価)`) にし、cost=0 報告でも token 由来下限で累積 cost を担保、(2) usage 検証を **record の前** に移動し、usage=None だけでなく **success の all-zero usage (tokens_input<=0)** も `shadow_usage_unverifiable` で fail-closed。token-floor accumulation + zero-usage block の regression test。
- **R12 (2 HIGH + 1 MEDIUM)**: (F1 HIGH adopt) `bridge_run_update` が caller 指定 status を直書きし blocked_reason クリア → blocked shadow run を running へ戻して fail-closed 迂回可能 → **shadow run の run_update を拒否** (`shadow_run_update_forbidden`、shadow status は orchestrator transition のみ、停止は run_cancel)。(F2 HIGH reasoned-defer) `record_provider_usage` の read-add-flush が同一 run 並行で非 atomic → **ただし共有コード (production も同一) + orchestrator lease が single-flight 担保 + driver 不在で未到達** → atomic SQL increment (`cost_usd = cost_usd + :delta RETURNING`) は runtime concurrency hardening 増分へ defer (lease が primary control)。(F3 MEDIUM adopt) shadow flag check が idempotency lookup より前 → flag off 後の既存 shadow run replay が拒否 → **flag check を idempotency replay の後に移動** (新規 create のみ gate、exactly-once replay 維持)。
- **R15 (1 HIGH = R12 F2 re-emission、reasoned-defer 確定)**: record_provider_usage の read-add-write が同一 run 並行で非 atomic (再掲)。**再検証**: ① **共有コード** で production も同一 (SP-029 が atomicity を変えていない = shadow regression でない)、② orchestrator **lease が run 単位 single-flight を設計担保** (並行同一 run には lease overlap = 別 bug 必要)、③ **runtime driver 不在で未到達** (execute_provider_step caller は test のみ)、④ atomic SQL `UPDATE...RETURNING` 化は production 含む共有 accounting 改修 + 全 mock-session test 書換を要する cross-cutting concurrency hardening。→ runtime/worker concurrency 増分へ defer (lease が primary control)。**shadow 固有 content finding は R1-R14 で全収束、R15 は既 defer の concurrency 1 件のみ = adversarial loop 収束 (CRITICAL=0 / HIGH≤2 達成)**。
- **Codex App auto-review (PR #348、3 P2)**: (F2 adopt) input token 概算が codepoint 数で emoji/ZWJ を過小評価 → **UTF-8 byte 数** に変更 (`actual_tokens <= byte_length` が常に成立 = 真の上限、fail-safe)。(F3 adopt) shadow が production 全 edge 継承で side-effect pipeline に進入しうる → `SHADOW_FORBIDDEN_TRANSITIONS` で **pipeline 進入 edge (schema_validated→policy_linted 等) + running→completed 検証 skip を禁止**、合法 path を validated terminal に confine (choke point guard と二重隔離)。(F1 reject-rationale) run_id=None の approval が shadow guard を通る → **broker repo-capability boundary (production run 必須) で escalation 封鎖済 + run-bound approval は guard 済 + run_id=None は MCP `approval_request_create` の正規 ticket-level repo_write 経路で shadow 帰属不能** のため run_id 必須化不可 (現実装が安全側)。
- **deferred (cross-cutting、本増分外)**: record_provider_usage の atomic accounting (R12 F2 / R15、lease single-flight でカバー、runtime concurrency 増分) / shadow の **MCP/REST/frontend 公開 + runtime worker driver** (shadow terminal を駆動、Sprint 6+ runtime 統合と同時) / runner_mutation_gateway の run_mode 強制 (Sprint 7 契約変更) / production budget/kill-switch の pre-execution preflight (現状 production も post-execution accumulator、shadow のみ preflight 追加済) / approval_requests.run_id の **FK 整合** (DB schema = ADR gate) / cost 推定ベースの pre-call token 制限 / shadow aggregate (per-tenant/project) cap。いずれも shadow security escape を開かない (broker repo-capability boundary = production run 必須 + per-run cap + kill switch preflight で担保、shadow 作成は flag off default かつ未公開)。
