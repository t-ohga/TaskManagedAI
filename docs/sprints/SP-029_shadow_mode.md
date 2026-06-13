---
id: "SP-029_shadow_mode"
type: "heavy"
status: "in_progress"
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
