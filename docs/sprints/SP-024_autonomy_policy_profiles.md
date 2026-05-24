---
id: "SP-024_autonomy_policy_profiles"
type: "heavy"
status: "ready"
sprint_no: 24
created_at: "2026-05-24"
updated_at: "2026-05-24"
target_days: 4
max_days: 6
adr_refs:
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted; action_class 7 fixed / policy_profile server-owned semantics"
  - "[ADR-00012](../adr/00012_hook_trust_boundary.md) # accepted; Hook Trust Boundary prerequisite for autonomy upgrade"
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # accepted; human-only decider / role capability separation"
  - "[ADR-00006](../adr/00006_secretbroker_contract.md) # accepted; secret_access remains human approval required"
  - "[ADR-00010](../adr/00010_provider_compliance_matrix.md) # accepted; provider_call remains human approval required"
  - "[ADR-00025](../adr/00025_autonomy_policy_profiles.md) # accepted 2026-05-24; autonomy L0-L3 policy profiles"
planned_adr_refs: []
related_sprints:
  - "SP-003_policy_approval"
  - "SP-006_cli_artifact"
  - "SP-007_runner_sandbox"
  - "SP-014_orchestrator_agent"
  - "SP-016_ui_cli_parity"
  - "SP-022_framework_intake_hardening"
risks:
  - "autonomy upgrade can bypass approval if policy_profile is accepted from caller input"
  - "L1-L3 auto-allow drift can turn an approval skip into an agent decider unless human-only invariants are kept separate"
  - "DB/API/UI/CLI surfaces can diverge if autonomy_level enum is not kept in 5+ source sync"
  - "global kill switch, Provider Matrix block, Tool/MCP Gateway deny, and budget exceeded must override all autonomy levels"
  - "projects.policy_profile already exists as a server-owned DB field; migration must not remove or repurpose it until ADR-00009 compatibility is proven"
---

最終更新: 2026-05-24 (SP024-T04 low-risk profile evaluator completed)

## 目的

ADR-00025 の autonomy L0-L3 を、approval / policy / audit / UI / CLI の境界を壊さず実装する。最初の出荷単位は **caller-visible な `autonomy_level`** と **server-owned な `policy_profile`** を分離し、default L0 / fail-closed / human-only decider を維持したまま、L1-L3 の auto-allow path を段階的に有効化できる基盤にする。

## 背景

- ADR-00025 は SP024-T01 で accepted 化され、`SP-024` を実装 Sprint として確定している。
- ADR-00012 は accepted で、SP-022 Phase 5 completion により Hook Trust Boundary prerequisite は満たされた。
- ADR-00009 は `policy_profile` / `policy_profile_action_effects` を accepted 実装済みで、`default + low_risk_auto_allow x 7 action_class = 14 rows exact` が SP-020 で regression gate 化済み。
- 現行 code は `ProjectCreate` で caller-supplied `policy_profile` を拒否し、repository payload でも `policy_profile` を server-owned として reject している。`projects.policy_profile` は DB 上の server-owned field として存在するため、SP024-T01 で ADR-00009 互換の server-owned DB cache / FK として維持する判断を確定した。
- ユーザー要望は「approval 不要で AI が自動実行できる範囲を 4 段階で切替」だが、`secret_access` / `merge` / `deploy` / `provider_call` は全 level で human approval 必須のままにする。

## 対象外

- agent / orchestrator / service / provider を approval decider に昇格させること。
- `secret_access` / `merge` / `deploy` / `provider_call` の auto-allow。
- production deploy / admin bypass merge / external provider call の自動実行。
- `action_class` 7 種の追加、削除、名称変更。
- `policy_profile_action_effects` 14 row seed の破壊的変更。
- character image generation (SP-021)。
- cron / routines Wave 23。

## Readiness Gate

| gate | status | note |
|---|---|---|
| ADR-00025 accepted | ready | SP024-T01 で accepted 化済み |
| ADR-00012 accepted | ready | Hook Trust Boundary ADR は accepted |
| SP-022 Phase 5 complete | ready | PR #80 completion log で Phase 5 完遂、SP-012 carry-over も 2026-05-22 完遂済み |
| caller-supplied `policy_profile` rejection | ready | `ProjectCreate` extra forbid + repository reject test が存在する |
| `projects.policy_profile` compatibility decision | ready | SP024-T01 decision: ADR-00009 の server-owned DB cache / FK として維持する |
| GitHub Actions | blocked infra | 月次 quota blocked のため、local verify + review thread inspection を正本にする |

## 設計判断

- **L0 is default and safe**: migration は既存 project を `autonomy_level='L0'` に固定し、global downgrade があれば常に L0 として扱う。
- **policy_profile remains server-owned**: caller は `autonomy_level` だけを設定できる。`policy_profile` は Policy Engine / resolver が server-side に決める値で、API / CLI / UI の write surface から受け取らない。
- **SP024-T01 compatibility decision**: `projects.policy_profile` は削除せず、ADR-00009 の server-owned DB cache / FK として維持する。caller は `autonomy_level` だけを渡し、Policy Engine が `policy_profile` を server-side に resolve / update する。
- **auto-allow is not self-approval**: auto-allow path は `approval_requests` row を作らないだけで、decider を agent に移譲しない。approval が必要な action は従来通り human-only decider を維持する。
- **deny overrides allow**: budget exceeded、global kill switch、Provider Matrix blocked、Tool/MCP Gateway deny、low-risk profile fail のいずれかで、level に関係なく `effect=deny` または approval path fallback とする。
- **feature-flagged rollout**: L1-L3 の runtime auto-allow は default disabled とし、T05/T06 の regression gate が揃うまで L0 semantics だけを enforce する。

## 実装チケット

- SP024-T00: plan-only gate (本 PR)。Sprint Pack / registry / ADR drift note を起票し、runtime 実装を分離する。
- SP024-T01: ADR-00025 readiness gate (completed)。ADR-00025 を current implementation と同期し、accepted 化、batch split、`projects.policy_profile` compatibility decision を確定する。
- SP024-T02: `autonomy_level` enum + DB migration (completed)。default L0、DB CHECK / SQLAlchemy / Python Literal / Pydantic / pytest / docs の 5+ source 整合を作る。
- SP024-T03: server-owned policy resolver (completed)。caller-supplied `policy_profile` write path を引き続き reject し、`autonomy_level -> policy_profile` を Policy Engine 内部で解決する。
- SP024-T04: low-risk profile evaluator (completed)。payload data class / change scope (diff size + file count) / forbidden path / dangerous command / provider preflight / runner gateway / ContextSnapshot の 7 軸 fail-closed 判定を実装し、各軸 negative test と all-pass positive test を追加する。
- SP024-T05: Policy Engine integration (completed)。L0-L3 matrix、human-required actions、kill switch / provider block / tool deny / budget cap override を統合する。
- SP024-T06: audit / AgentRunEvent / policy_decisions trace。auto-allow path でも `policy_profile` / `policy_version` / `auto_allow_reason` / `effective_action_class` / `applied_level` を raw payload なしで記録する。
- SP024-T07: UI / CLI autonomy setting。`autonomy_level` だけを表示・更新し、`policy_profile` の setter / input / command option を作らない。
- SP024-T08: regression / rollback gates。migration up-down、enum drift、caller payload reject、human-required action、kill switch override、14 row seed維持をまとめて close する。

## タスク一覧

- [x] SP024-T00 plan-only gate
- [x] SP024-T01 ADR-00025 readiness gate
- [x] SP024-T02 autonomy_level enum + DB migration
- [x] SP024-T03 server-owned resolver + caller policy_profile reject
- [x] SP024-T04 low-risk profile evaluator
- [x] SP024-T05 Policy Engine L0-L3 integration
- [ ] SP024-T06 audit / AgentRunEvent / policy_decisions trace
- [ ] SP024-T07 UI / CLI autonomy settings
- [ ] SP024-T08 regression / rollback closeout

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| ADR-00025 accepted before runtime implementation | ○ | - |
| `projects.autonomy_level` default L0 migration | ○ | - |
| autonomy_level enum 5+ source integrity | ○ | - |
| caller-supplied `policy_profile` reject path | ○ | - |
| server-owned `autonomy_level -> policy_profile` resolver | ○ | - |
| low-risk profile 7 axis fail-closed evaluator | ○ | advanced thresholds can defer if L1-L3 runtime remains disabled |
| human-required actions always approval | ○ | - |
| kill switch / provider block / tool deny / budget cap override | ○ | - |
| audit / AgentRunEvent / policy_decisions trace | ○ | dashboard polish may defer |
| UI / CLI write surface for `autonomy_level` only | ○ | UI polish may defer; CLI/API contract must ship |
| L3 draft PR auto-open runtime enablement | × | post-SP024 dogfooding, disabled until explicit enablement |
| cron / routines | × | Wave 23 |

## 受け入れ条件

- ADR-00025 は accepted 化前に ADR-00009 / current code と同期され、`projects.policy_profile` の扱いが明示されている。
- `ProjectCreate` / update API / CLI / UI は `policy_profile` を受け取らず、caller payload に含まれる場合は reject する。
- `autonomy_level` は L0/L1/L2/L3 のみ許可され、DB CHECK / SQLAlchemy / Python Literal / Pydantic / pytest / docs が exact match する。
- 既存 project は migration 後に `autonomy_level='L0'` となり、L1-L3 は明示的な upgrade gate が揃うまで runtime effect を持たない。
- `secret_access` / `merge` / `deploy` / `provider_call` は L0-L3 全 level で human approval 必須のまま維持される。
- low-risk profile は 7 軸のうち 1 軸でも fail したら auto-allow せず、approval path または deny path に fall back する。
- budget exceeded / global kill switch / Provider Matrix blocked / Tool/MCP Gateway deny は level を無視して fail-closed する。
- auto-allow path でも audit / AgentRunEvent / policy_decisions trace が残り、raw secret / raw prompt / raw provider payload / capability token は記録されない。
- migration は isolated PostgreSQL DB で upgrade / downgrade / upgrade round-trip を確認する。

## 検証手順

```bash
# plan-only gate
.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-024_autonomy_policy_profiles.md
git diff --check

# implementation batches after ADR-00025 acceptance
uv run ruff check backend/app/domain/policy backend/app/services/policy backend/app/schemas tests/policy tests/db
PYTHONPATH=cli uv run mypy backend/app/domain/policy backend/app/services/policy backend/app/schemas tests/policy tests/db
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic upgrade head
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic downgrade -1
TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run alembic upgrade head
TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL=<test-db-url> uv run pytest \
  tests/policy/test_autonomy_level_enum.py \
  tests/policy/test_autonomy_level_resolve.py \
  tests/policy/test_low_risk_profile.py \
  tests/policy/test_autonomy_upgrade_gate.py \
  tests/policy/test_autonomy_caller_supplied_policy_profile.py \
  tests/policy/test_autonomy_human_required_actions.py \
  tests/policy/test_autonomy_kill_switch_override.py \
  tests/policy/test_policy_profile_seed.py \
  tests/db/test_schema_introspection.py \
  -q
```

## Batch Rule

| batch | ticket | scope | risk | PR gate |
|---|---|---|---|---|
| 0a | SP024-T00 | Sprint Pack / registry / ADR drift note | docs / gate only | frontmatter + diff check + review thread inspection |
| 0b | SP024-T01 | ADR-00025 accepted promotion + batch split | policy decision | ADR/current-code drift review + no runtime changes |
| 0c | SP024-T02 | autonomy_level enum + migration | DB schema | migration up/down + 5+ source enum test |
| 0d | SP024-T03 | server-owned resolver / caller reject | API / policy boundary | payload reject + repository/service negative |
| 0e | SP024-T04 | low-risk evaluator | auto-allow safety | 7 axis negative + all-pass positive |
| 0f | SP024-T05 | Policy Engine integration | approval bypass risk | human-required actions + kill switch override |
| 0g | SP024-T06 | trace / audit / AgentRunEvent | raw payload leakage | no raw secret/prompt/provider payload assertions |
| 0h | SP024-T07 | UI / CLI settings | caller-owned drift | autonomy_level-only contract tests |
| 0i | SP024-T08 | closeout regression / rollback | cross-source drift | full policy/db regression + Sprint closeout |

Batch rule: 0c-0i must each run immediate self-review and PR review thread inspection after PR creation. Do not widen scope from a failed batch; fix, split, or defer explicitly.

## レビュー観点

- `policy_profile` が caller-supplied input として復活していないか。
- L1-L3 auto-allow が human-only decider invariant を壊していないか。
- `secret_access` / `merge` / `deploy` / `provider_call` が全 level で human approval 必須のままか。
- `autonomy_level` enum が DB / ORM / Python / Pydantic / tests / docs で drift していないか。
- low-risk profile の negative test が軸ごとに独立しているか。
- auto-allow trace に raw secret、raw prompt、raw provider payload、capability token が出ていないか。
- kill switch / provider block / tool deny / budget cap が allow より優先されるか。
- migration rollback が data loss と schema drift を起こさないか。

## SP024-T01 compatibility decision

`projects.policy_profile` は削除しない。理由は、ADR-00009 accepted 実装で `policy_profiles` / `policy_profile_action_effects` / `policy_decisions_policy_profile_fkey` が確立済みで、SP-020 でも 14 row exact seed と review artifact guard が regression 化されているため。SP-024 はこの server-owned DB field を caller-visible に戻さず、`autonomy_level` から resolver が server-side に `policy_profile` を決める層を追加する。

## 残リスク

- L1-L3 runtime enablement は dogfooding で段階的に開く必要がある。SP024-T08 完了時点でも default disabled を維持し、別 Sprint で opt-in enablement を扱う。
- `projects.policy_profile` は維持決定済みだが、T03 で API / CLI / UI / repository の write surface を再確認し、caller-supplied `policy_profile` が復活していないことを regression 化する必要がある。
- GitHub Actions quota が復旧するまで、PR checks は local verify / Codex review / inline thread inspection で補完する。

## 次スプリント候補

- SP-021 AI Character Generation (optional / P2)。
- Wave 23 cron / routines Sprint。
- SP-024 dogfooding enablement (L1/L2 opt-in rollout、SP024-T08 完了後)。

## 関連 ADR

- [ADR-00025](../adr/00025_autonomy_policy_profiles.md): autonomy L0-L3 policy profiles。
- [ADR-00009](../adr/00009_action_class_taxonomy.md): action_class taxonomy / policy_profile server-owned semantics。
- [ADR-00012](../adr/00012_hook_trust_boundary.md): Hook Trust Boundary。
- [ADR-00014](../adr/00014_multi_agent_orchestration.md): human-only decider / multi-agent boundary。
- [ADR-00006](../adr/00006_secretbroker_contract.md): SecretBroker。
- [ADR-00010](../adr/00010_provider_compliance_matrix.md): Provider Compliance Matrix。

## Review

### 2026-05-24 SP024-T00 plan-only gate

changed:
- `docs/sprints/SP-024_autonomy_policy_profiles.md`
- `docs/sprints/README.md`
- `docs/adr/00025_autonomy_policy_profiles.md`
- `docs/adr/00009_action_class_taxonomy.md`

implemented:
- SP-024 heavy Sprint Pack 起票。
- ADR-00025 / ADR-00009 の SP-017 candidate drift を SP-024 へ同期。
- current code drift (`ProjectCreate` は既に `policy_profile` reject、`projects.policy_profile` は server-owned DB field として存在) を T01 blocker として明示。

verified:
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-024_autonomy_policy_profiles.md`
- `git diff --check`

deferred:
- ADR-00025 accepted promotion、DB migration、Policy Engine / UI / CLI 実装は SP024-T01+ に defer。

risks:
- T01 で `projects.policy_profile` compatibility decision を確定するまで migration へ進まない。

### 2026-05-24 SP024-T01 ADR readiness gate

changed:
- `docs/adr/00025_autonomy_policy_profiles.md`
- `docs/sprints/SP-024_autonomy_policy_profiles.md`
- `docs/sprints/README.md`

implemented:
- ADR-00025 を `proposed` から `accepted` に昇格。
- `projects.policy_profile` は ADR-00009 の server-owned DB cache / FK として維持する decision を確定。
- SP024-T02+ の implementation gate を、`autonomy_level` 追加 + server-owned resolver + caller-supplied `policy_profile` reject regression に分離。

verified:
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-024_autonomy_policy_profiles.md`
- `git diff --check`

deferred:
- DB migration、Policy Engine / UI / CLI 実装は SP024-T02+ に defer。

risks:
- runtime effect は SP024-T02+ の regression gate 完了まで default disabled のままにする。

### 2026-05-24 SP024-T02 autonomy_level enum + migration

changed:
- `backend/app/domain/policy/autonomy_level.py`
- `backend/app/db/models/project.py`
- `backend/app/schemas/project.py`
- `backend/app/api/me.py`
- `frontend/lib/api/session.ts`
- `migrations/versions/0034_sp024_autonomy_level.py`
- `tests/policy/test_autonomy_level_enum.py`
- `tests/db/test_schema_introspection.py`
- `tests/db/test_repository_layer.py`
- `tests/test_seeds.py`
- `frontend/__tests__/settings-auth-common-i18n.test.tsx`

implemented:
- `projects.autonomy_level` を default `L0` / NOT NULL / CHECK `L0|L1|L2|L3` で追加。
- Python Literal / frozenset / SQLAlchemy CheckConstraint / Pydantic read schema / migration CHECK / pytest expected / ADR docs の 5+ source drift gate を追加。
- backend `/api/v1/me/projects` と frontend session schema に read-only `autonomy_level` を追加。write surface は未追加で、L1-L3 runtime effect はまだ disabled。

verified:
- `uv run ruff check backend/app/domain/policy/autonomy_level.py backend/app/db/models/project.py backend/app/schemas/project.py backend/app/api/me.py tests/policy/test_autonomy_level_enum.py tests/db/test_repository_layer.py tests/test_seeds.py tests/db/test_schema_introspection.py migrations/versions/0034_sp024_autonomy_level.py`
- `PYTHONPATH=cli uv run mypy backend/app/domain/policy/autonomy_level.py backend/app/db/models/project.py backend/app/schemas/project.py backend/app/api/me.py tests/policy/test_autonomy_level_enum.py`
- `uv run pytest tests/policy/test_autonomy_level_enum.py -q`
- `TASKMANAGEDAI_DATABASE_URL=<isolated 127.0.0.1:55434 test db> uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
- `TASKMANAGEDAI_DATABASE_URL=<isolated 127.0.0.1:55434 test db> TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/db/test_schema_introspection.py::test_workspace_project_repository_contract_columns_and_constraints tests/db/test_repository_layer.py::test_project_repository_create_injects_matching_tenant_id tests/policy/test_policy_profile_seed.py::test_project_policy_profile_defaults_and_rejects_unknown_profile tests/test_seeds.py -q`
- `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
- `corepack pnpm@10.18.0 --dir frontend exec vitest run __tests__/settings-auth-common-i18n.test.tsx`
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-024_autonomy_policy_profiles.md`
- `git diff --check`

deferred:
- low-risk evaluator, Policy Engine L0-L3 runtime integration, audit trace, UI/CLI settings remain SP024-T04+.

risks:
- Existing `/api/v1/me/projects` now exposes `autonomy_level` read-only; no caller write path exists yet. T07 must add settings UI/CLI without accepting `policy_profile`.

### 2026-05-24 SP024-T03 server-owned resolver + caller reject

changed:
- `backend/app/services/policy/autonomy_profile_resolver.py`
- `backend/app/services/policy/__init__.py`
- `backend/app/repositories/project.py`
- `tests/policy/test_autonomy_profile_resolver.py`
- `docs/adr/00025_autonomy_policy_profiles.md`
- `docs/sprints/SP-024_autonomy_policy_profiles.md`

implemented:
- `resolve_autonomy_policy_profile()` を追加し、SP024-T03 時点では L0-L3 全 level を server-owned `policy_profile='default'` / `auto_allow_enabled=False` に fail-closed 解決。
- 既存 `low_risk_auto_allow` は `provider_call` allow row を含むため、ADR-00025 の human-required action invariant を満たす T05 更新まで resolver から返さない guard を追加。
- generic `ProjectRepository` payload で `policy_profile` と `autonomy_level` の直書きを reject。

verified:
- `uv run ruff check backend/app/services/policy/autonomy_profile_resolver.py backend/app/services/policy/__init__.py backend/app/repositories/project.py tests/policy/test_autonomy_profile_resolver.py docs/adr/00025_autonomy_policy_profiles.md docs/sprints/SP-024_autonomy_policy_profiles.md`
- `PYTHONPATH=cli uv run mypy backend/app/services/policy/autonomy_profile_resolver.py backend/app/services/policy/__init__.py backend/app/repositories/project.py tests/policy/test_autonomy_profile_resolver.py`
- `uv run pytest tests/policy/test_autonomy_profile_resolver.py tests/policy/test_autonomy_level_enum.py -q`
- `TASKMANAGEDAI_DATABASE_URL=<isolated 127.0.0.1:55434 test db> TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/policy/test_policy_profile_seed.py::test_project_repository_rejects_policy_profile_payload -q`
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-024_autonomy_policy_profiles.md`
- `git diff --check`

deferred:
- low-risk evaluator、Policy Engine L0-L3 runtime integration、audit trace、UI/CLI settings remain SP024-T04+.

risks:
- T05 以降も DB-backed `policy_profile` は `default` profile に解決され、L1-L3 matrix は Policy Engine service 層で apply される。`low_risk_auto_allow` profile は `provider_call` allow row を含むため、ADR-00025 の autonomy resolver から返さない。

### 2026-05-24 SP024-T05 Policy Engine integration

changed:
- `backend/app/services/policy/autonomy_policy_engine.py`
- `backend/app/services/policy/autonomy_profile_resolver.py`
- `backend/app/services/policy/__init__.py`
- `tests/policy/test_autonomy_policy_engine.py`
- `tests/policy/test_autonomy_profile_resolver.py`
- `docs/adr/00025_autonomy_policy_profiles.md`
- `docs/sprints/SP-024_autonomy_policy_profiles.md`

implemented:
- `resolve_autonomy_policy_action_effect()` / `evaluate_autonomy_policy_engine_decision()` を追加し、server-owned `autonomy_level -> policy_profile` resolver、DB-backed profile effect resolver、low-risk evaluator、deny override を 1 つの Policy Engine decision に統合。
- L0 は常に auto-allow なし、L1 は `task_write`、L2 は `task_write` + `repo_write`、L3 は `task_write` + `repo_write` + `pr_open` のみを low-risk PASS 時に `allow` とする matrix を追加。
- `secret_access` / `merge` / `deploy` / `provider_call` は profile effect が `allow` でも `require_approval` へ fallback し、global kill switch / budget exceeded / Provider Matrix deny / Tool Registry deny は matrix より先に `deny` する。
- `low_risk_auto_allow` seed/profile は変更せず、14 row seed invariant と `projects.policy_profile` server-owned DB cache を維持。

verified:
- `uv run ruff check backend/app/services/policy/autonomy_policy_engine.py backend/app/services/policy/autonomy_profile_resolver.py backend/app/services/policy/__init__.py tests/policy/test_autonomy_policy_engine.py tests/policy/test_autonomy_profile_resolver.py`
- `PYTHONPATH=cli uv run mypy backend/app/services/policy/autonomy_policy_engine.py backend/app/services/policy/autonomy_profile_resolver.py backend/app/services/policy/__init__.py tests/policy/test_autonomy_policy_engine.py tests/policy/test_autonomy_profile_resolver.py`
- `uv run pytest tests/policy/test_autonomy_policy_engine.py tests/policy/test_autonomy_profile_resolver.py tests/policy/test_low_risk_profile.py tests/policy/test_autonomy_level_enum.py -q`

deferred:
- `policy_decisions` / AgentRunEvent / audit event への append-only trace persistence は SP024-T06。
- UI / CLI の `autonomy_level` 設定 write surface は SP024-T07。

risks:
- T05 は service-level decision integration まで。runtime caller へ接続する前に、T06 で raw secret / raw prompt / raw provider payload / capability token が trace に漏れない regression を追加する必要がある。

### 2026-05-24 SP024-T04 low-risk profile evaluator

changed:
- `backend/app/services/policy/low_risk_profile.py`
- `backend/app/services/policy/__init__.py`
- `tests/policy/test_low_risk_profile.py`
- `docs/adr/00025_autonomy_policy_profiles.md`
- `docs/sprints/SP-024_autonomy_policy_profiles.md`

implemented:
- `evaluate_low_risk_profile()` を追加し、7 軸のうち 1 軸でも fail した場合に `allowed=False` / `reason_code=low_risk_profile_failed` を返す fail-closed evaluator を実装。
- default threshold は `payload_data_class <= internal`、diff <= 200 lines、file count <= 3。
- forbidden path、dangerous command、provider preflight、runner gateway、ContextSnapshot の各 negative を独立 test 化。

verified:
- `uv run ruff check backend/app/services/policy/low_risk_profile.py backend/app/services/policy/__init__.py tests/policy/test_low_risk_profile.py docs/adr/00025_autonomy_policy_profiles.md docs/sprints/SP-024_autonomy_policy_profiles.md`
- `PYTHONPATH=cli uv run mypy backend/app/services/policy/low_risk_profile.py backend/app/services/policy/__init__.py tests/policy/test_low_risk_profile.py`
- `uv run pytest tests/policy/test_low_risk_profile.py tests/policy/test_autonomy_profile_resolver.py tests/policy/test_autonomy_level_enum.py -q`
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-024_autonomy_policy_profiles.md`
- `git diff --check`

deferred:
- Policy Engine への接続、level ごとの threshold 変更、audit trace は SP024-T05+。

risks:
- evaluator は pure service として追加済みで runtime path には未接続。T05 で effect decision と audit reason を接続する必要がある。
