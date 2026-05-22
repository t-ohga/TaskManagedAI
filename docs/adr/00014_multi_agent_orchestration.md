---
id: "ADR-00014"
title: "Multi-Agent Orchestration Foundation: 10 標準役職 (code enum) + project_agent_roles + role ⊥ capability authorization + orchestrator requester-only + lease/heartbeat/failover/kill-switch + max_* 上限 + remote_agent_gateway 連動"
status: "accepted"
date: "2026-05-10"
accepted_at: "2026-05-22"
authors:
  - "t-ohga"
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md (Phase D R1-R4 + Phase E = 56 finding 全件 adopt)"
  - "Phase A-1/A-2/B-1/B-2 Codex deep-dive 結果"
supersedes: null
superseded_by: null
acceptance_resolved_by:
  - "P0 (Sprint 1-12) 完了: 2026-05-22 PR #103 P0 Exit Declaration で完遂"
  - "Phase F-0 完了: 2026-05-22 SP-012-7 Sprint Pack 全 3 件 must_ship 完遂 (PR #106 + #107 + #108)、`backend/app/domain/policy/action_class.py` は既に 7 種 enum (provider_call 追加 + read/search 削除済)、DB CHECK constraint 3 か所 (policy_rules + approval_requests + policy_decisions) も同期済確認 (PR #106)"
  - "ADR-00018/19/20 + 既存 ADR-00004/00009/00013 accepted: ADR-00020 既 accepted (SP022-T00 2026-05-19)、ADR-00004/00009 既 accepted、ADR-00019 は本 PR で同時 accepted、ADR-00018/00013 は各 owning sprint (SP-015 / P0.1+) kickoff 時 accepted で再解釈 (SP-013 着手時には未 accepted catch-22 解消)"
---

最終更新: 2026-05-22 (accepted 昇格、SP-013 kickoff 直前 promotion)

## 背景

- 決定対象: TaskManagedAI を「**AI 集合体 = 一つの会社**」メタファーで稼働させるための multi-agent foundation を P0.1 で導入。本 ADR は (1) 10 標準役職 taxonomy、(2) `project_agent_roles` table と agent_runs.role_id/role_scope、(3) **role ⊥ capability authorization invariant**、(4) **orchestrator は requester only、approval decider にならない**、(5) lease/heartbeat/failover/kill-switch + max_* 上限、(6) remote_agent_gateway (ADR-00013) 連動の 6 点を固定。
- 関連 Sprint: SP-013 (foundation: project_agent_roles + agent_runs 拡張)、SP-014 (orchestrator agent: lease/dispatch/failover)、SP-015 (inter-agent、ADR-00018)、SP-016 (UI/CLI parity、ADR-00015).
- 前提 / 制約 (既存 invariant 不変):
  - AgentRun 16 状態 + blocked_reason 3 種 (rules/agentrun-state-machine.md §1-2)
  - ContextSnapshot 10 列 (rules/core.md §9, DD-03)
  - Provider Compliance v2 13 reason_code
  - SecretBroker atomic claim + OperationContext fingerprint
  - Approval Workflow 4 整合 + **decider human-only** + self-approval 禁止 (server-owned-boundary §3-4, ADR-00009)
  - Cross-source enum 5+ source 整合 (cross-source-enum-integrity §1)
  - **既存 action_class 7 種 (ADR-00009)**: 本 ADR では拡張しない (新 operation は event_type / Tool Registry / policy_profile に分散)
  - 全 id=uuid + tenant_id=bigint NOT NULL + 複合 FK pattern
  - 3 gateway 分離 (tool_mutating_gateway_stub / runner_mutation_gateway / remote_agent_gateway)
  - tickets / projects / agent_runs に **`unique (tenant_id, project_id, id)`** を Phase F-0 で追加 (PD-R2-F-001 / PE-F-007 fix)
- ADR Gate Criteria #4 (AI 権限) 主、#1 (認証認可) / #2 (DB schema) / #3 (API/event schema) 補助.

## 選択肢

| # | 案 | 採否 | 根拠 |
|---|---|---|---|
| **A (採用)** | 10 標準役職 (code enum) + project_agent_roles (project-scoped) + role ⊥ capability + orchestrator requester-only + lease/max_* 上限 + remote_agent_gateway 連動 | adopt | 既存 invariant 全件不変、Phase B-2 14 risks + Phase D 40 + Phase E 16 = 56 finding 全件 mitigation |
| B | framework full embed (LangGraph or AutoGen runtime) | reject | Phase B-1 で全 framework full embed skip 判定、R-007/008/013/014 すべて該当 |
| C | orchestrator が approval decider | reject | Phase B-2 R-002 + Phase D PD-F-005 CRITICAL: human-only invariant 違反 |
| D | role-based authorization (role=security_agent → secret 解除可) | reject | Phase B-2 R-009 + Phase D PD-F-005 / Phase E PE-F-001: role 偽装で権限昇格 |

## 採用案

採用: **A**。既存 invariant 全件不変 + 56 finding 全件 mitigation の唯一構成.

### §1: 10 標準役職 (code enum、5+ source 整合)

`backend/app/domain/agent_role/taxonomy.py` の Python Literal で固定:

```python
STANDARD_ROLE_IDS: Final[frozenset[str]] = frozenset({
    "orchestrator", "implementer", "reviewer", "tester", "security_agent",
    "researcher", "observer", "curator", "dispatcher", "repair_specialist",
})
```

5+ source: Python Literal + Pydantic Field validator + pytest EXPECTED constant + frontend TypeScript enum (Sprint 17) + DB CHECK は不要 (text 列 metadata).

**Phase E PE-F-001 mitigation**: `STANDARD_ROLE_IDS` は **custom role_id として禁止 (reserved namespace)**、`project_agent_roles` 作成時に同名で reject (DB unique 違反 + service guard).

### §2: project_agent_roles (project-scoped table、PD-F-001 / PD-R2-F-001 fix)

```sql
create table project_agent_roles (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid not null,
    role_id text not null check (role_id ~ '^[a-z][a-z0-9_]{1,31}$'),
    display_name text not null,
    description text not null,
    recommended_provider_tier text not null default 'balanced'
        check (recommended_provider_tier in ('balanced','high-quality','low-cost','mock')),
    icon_ref text,
    created_by_actor_id uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deprecated_at timestamptz,
    unique (tenant_id, id),
    unique (tenant_id, project_id, id),
    unique (tenant_id, project_id, role_id),
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, created_by_actor_id) references actors(tenant_id, id)
);
```

`recommended_action_class` 列は **存在しない** (R-009 / PD-F-005 / PE-F-001 mitigation: role が capability を授与しない).

### §3: agent_runs 拡張 + role_scope DB 防御 (PD-R2-F-002 / PD-R3-F-007 / PD-R4-F-002 / PE-F-012 fix)

```sql
alter table agent_runs
    add column role_id text,
    add column role_scope text check (role_scope in ('global','project')),
    add column orchestrator_lease_token uuid,
    add column orchestrator_lease_expires_at timestamptz,                   -- PD-R2-F-012 / PD-R4-F-002 fix
    add column lease_renewed_at timestamptz,
    add column orchestrator_kill_at timestamptz,
    add column last_progress_at timestamptz,                                 -- PE-F-004 fix (no-progress detection)
    add column progress_seq bigint not null default 0,                       -- PE-F-004 fix
    add constraint agent_runs_tenant_project_id_uniq unique (tenant_id, project_id, id),
    -- PD-R4-F-002 strict fail-closed CHECK:
    add constraint agent_runs_role_consistency check (
        (role_id is null and role_scope is null)
        or (role_id is not null and role_scope is not null and role_scope in ('global','project'))
    );

-- PE-F-012 mitigation: trigger を tenant_id, project_id, role_id, role_scope の更新でも発火
create trigger agent_runs_check_project_role
    before insert or update of tenant_id, project_id, role_id, role_scope on agent_runs
    for each row execute function check_project_role_link();
```

`check_project_role_link()` 関数: `role_scope='project'` のとき `project_agent_roles` に row が存在しなければ raise exception。`role_scope='global'` のとき `STANDARD_ROLE_IDS` に含まれることを application layer で validate.

**より堅い案 (PE-F-012)**: `agent_run_project_roles` link table を SP-013 で導入し DB level FK enforce、global role は `STANDARD_ROLE_IDS_MIRROR` table (immutable seed) で CHECK generated。SP-013 着手時に link table 案を最終決定.

### §4: role ⊥ capability authorization (R-009 / S-2 / AP-2 / AP-9、CRITICAL invariant)

agent_runs.role_id (text metadata) + role_scope は **dispatch hint のみ**、authorization は capability token + action_class + 3 gateway + Tool Registry で別軸:

```text
agent_run.role_id (metadata)
        │
        ├─ display / dispatch hint / provider tier 推奨
        │
        ▼
authorization の正本:
   1. Policy Engine が action_class 7 種 (ADR-00009) で判定
   2. Approval Workflow が requester/decider 確認、decider human-only
   3. SecretBroker capability token が actor/run/fingerprint binding
   4. ProviderAdapter が payload_data_class / allowed_data_class 判定
   5. Tool Registry allowed_actions (Sprint 4.5) で read_only_research / read_only_audit 等を許可
   6. 3 gateway: tool_mutating_gateway_stub / runner_mutation_gateway / remote_agent_gateway
```

### §5: 3 階層 operation 分散 (action_class 7 種不変、AP-8 / PD-F-004 fix)

| 階層 | 旧 (rejected、AP-8) | 新 (採用、既存 invariant 不変) |
|---|---|---|
| Tier 1 | `orchestrator_dispatch` (action_class 候補) | `agent_run_event_type='orchestrator_dispatched'` (event_type 22→31、ADR-00004 update) |
| Tier 1 | `inter_agent_message` (action_class 候補) | `agent_run_event_type='inter_agent_message_sent_ref/consumed_ref'` + audit_events 独立 (ADR-00018) |
| Tier 2 | `auto_approve_low_risk` (action_class 候補) | `policy_profile='low_risk_auto_allow'` (Policy Engine effect=allow、approval_requests 作らない、ADR-00009 update) |
| Tier 1 | `read_only_research` (action_class 候補) | Tool Registry `allowed_actions=['web_fetch','docs_search']` (network enum 化 ADR、P0 deny-only) |
| Tier 1 | `read_only_audit` (action_class 候補) | Tool Registry `allowed_actions=['trace_read','metric_read']` |

**Tier 2 の重要 invariant (PD-F-005 / PE-F-003 mitigation)**: Tier 2 は **approval_requests を作らない** (Policy Engine が自動 allow)。reviewer agent は `review_artifacts` table の作成者で、Policy Engine の input。`approval_requests.decided_by_actor_id` は **常に human のみ** (DB CHECK + service guard 4 重防御).

### §6: review_artifacts table (PD-R2-F-003 / PE-F-003 fix)

```sql
create table review_artifacts (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid not null,
    parent_run_id uuid not null,
    requester_run_id uuid not null,
    reviewer_run_id uuid not null,
    review_target_artifact_id uuid not null,
    review_artifact_id uuid not null,
    -- PD-R2-F-003 fix: verdict 語彙を Approval (approved/rejected) と分離
    review_verdict text not null check (review_verdict in ('pass','fail','needs_revision')),
    findings_count int not null default 0,
    created_at timestamptz not null default now(),
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, project_id, parent_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, requester_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, reviewer_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, review_target_artifact_id) references artifacts(tenant_id, id),
    foreign key (tenant_id, review_artifact_id) references artifacts(tenant_id, id),
    -- Phase H PH-F-008 fix: SP-013 hard gate (artifacts.project_id materialize、ADR-00021 §11.5/§3.11) 完了後に
    -- 上記 2 FK を `(tenant_id, project_id, <id>) references artifacts(tenant_id, project_id, id)` に変更
    -- それまで service layer guard で cross-project artifact reference を reject (DB level 完全防御は SP-013 後)
    check (reviewer_run_id <> requester_run_id)
);
-- PE-F-003 4 重防御 (service/Pydantic/contract test):
-- - reviewer_run_id の role_id='reviewer' + role_scope='global' を service guard
-- - reviewer_run と requester_run の parent_run_id 同一 + project 同一 を Pydantic validator
-- - orchestrator/reviewer role shadowing 排除を contract test
-- - review_target hash + policy_version + provider_request_fingerprint + action_class を policy_decision input と一致 (PE-F-003)
```

### §7: orchestrator lease + heartbeat + failover + kill-switch + progress detection

| 機構 | 仕様 | child run 影響 |
|---|---|---|
| lease | `agent_runs.orchestrator_lease_token` (UUID) + `orchestrator_lease_expires_at` | child は既存 16 状態のみ使用 |
| heartbeat | 60s 以内に renew (atomic UPDATE + AgentRunEvent append 同一 transaction) | renew 失敗 = `orchestrator_lease_expired` event + dispatch reject |
| failover | `lease_expired` 検知 → 別 orchestrator (next-in-queue) 起動 | active child は `cancel_requested -> cancelled` (default) または `blocked + runtime_blocked` (force_kill=true) |
| kill-switch | `orchestrator_kill_at` 設定 | active child を停止、terminal child は変更不可 |
| **progress lease (PE-F-004)** | `last_progress_at` + `progress_seq` を AgentRunEvent と同一 transaction で更新 | N 分 (default 30 分、tenant_config で 5-120 分) no-progress で `blocked + runtime_blocked` |
| max_children | default 8、tenant_config override、絶対上限 ≤20 (DB CHECK) | dispatch reject |
| max_depth | default 3、絶対上限 ≤5 | dispatch reject |
| max_turns | inter-agent message per parent_run、default 100、絶対上限 ≤500 | publish reject + pairwise repeated payload hash detector で loop 検知 (PE-F-004) |
| max_iterations | repair retry (既存 BudgetGuard) | `repair_exhausted` (既存) |
| budget ceiling | 1 orchestrator + 全 children 合算、default 90 分/$5、絶対上限 ≤$50 | `blocked + budget_blocked` (既存) |

### §8: remote_agent_gateway 連動 (PD-F-008 / PD-R2-F-010 / PE-F-013 fix)

`orchestrator_dispatched` event で remote child を作る場合は ADR-00013 の `remote_agent_gateway` 経由必須:

| 期間 | remote_agent_gateway 状態 |
|---|---|
| P0 (Sprint 1-12) | 実装 path 完全になし (P0 sealed guard で `backend/app/services/remote_agent_gateway.py` + `backend/app/adapters/remote_agent/**` + `backend/app/api/remote_agent_router.py` + `frontend/app/remote-agent/**` + `config/remote_agent_compliance.toml` + `tests/**/remote_agent/**` 禁止、PE-F-013) |
| P0.1 開始時 (SP-014) | deny-only stub 作成 (orchestrator_dispatched が remote child 試行 → 全件 deny + `remote_agent_dispatch_denied` audit、PE-F-013) |
| P0.1〜P1 (SP-014/SP-018+) | ADR-00013 段階承認で Codex app-server / Claude SDK を allowlist 拡張 |

### §9: SecretBroker multi-agent invariant (PD-F-009 / PE-F-014 fix)

各 child run は独立に SecretBroker から token 取得 (agent 間 pass-through 禁止)。SP-014/015/016 で **6 negative case + 個別 reason_code** を must_ship:

| substitution case | reason_code |
|---|---|
| parent token used by child | `cross_run_token_substitution` |
| child token used by parent | 同上 |
| inter_agent_message token payload (raw token を message に含めようとする) | `secret_in_message_payload` |
| approval_id substitution | `approval_target_mismatch` (既存 + multi-agent 拡張) |
| payload_hash substitution | `payload_hash_mismatch` (既存) |
| run_id substitution | `run_binding_mismatch` |

### §10: KPI rollup (PD-R2-F-008 / PD-R3-F-004 / PD-R4-F-001 / PE-F-015 fix、Phase F metrics ADR で詳細化)

KPI source は **既存正本** に固定:

- `acceptance_pass_rate`: eval_runs + eval_scores
- `time_to_merge`: agent_run_events.event_type='repo_pr_opened' (current) / `repo_pr_merged` は ADR-00004 update で future
- `approval_wait_ms`: approval_requests.requested_at/decided_at、approval per measurement (dedupe)
- `citation_coverage`: claims + evidence_items + adopted_artifacts link table (Phase F で確定、PE-F-015)
- `cost_per_completed_task`: agent_run_events.event_type='provider_responded' usage、recursive CTE で descendant sum、event idempotency_key で dedupe (PE-F-015)

### §11: Sprint と対象ファイル

- 実装 Sprint: SP-013 → SP-014 → SP-015 (ADR-00018) → SP-016 (ADR-00015)
- 実装対象: `backend/app/db/models/{project_agent_role,review_artifact,agent_run}.py` / `backend/app/domain/agent_role/taxonomy.py` / `backend/app/services/orchestrator/{dispatcher,lease_manager,heartbeat,failover,kill_switch,limits,progress_lease}.py` / `migrations/versions/0013_p0_1_multi_agent_foundation.py` 〜 `0014_p0_1_orchestrator_lease.py` / `tests/multi_agent/*` / `eval/multi_agent/*`

### §12: テスト指針 (主要)

- `test_role_taxonomy_enum.py`: 10 標準 role 5+ source 整合 + STANDARD_ROLE_IDS reserved namespace + custom role create/deprecate
- `test_role_orthogonal_to_capability.py`: R-009 negative (role=security_agent でも capability token なしに secret_access deny)
- `test_orchestrator_requester_only.py`: R-002 negative (orchestrator が approval decider 不可)
- `test_orchestrator_lease_failover.py`: lease/heartbeat/failover/kill-switch
- `test_progress_lease.py`: PE-F-004 (no-progress 30 分で blocked+runtime_blocked)
- `test_max_limits.py`: children/depth/turns/budget 違反すべて
- `test_action_class_3tier.py`: Tier 1 自律 / Tier 2 Policy auto-allow (decider なし) / Tier 3 human approval 必須
- `test_secretbroker_multi_agent_negative.py`: 6 substitution case 個別 reason_code
- `test_remote_agent_gateway_p0_1_stub.py`: deny-only stub + audit
- `test_review_artifact_4_defense.py`: PE-F-003 (reviewer != requester / role=reviewer / parent 同一 / project 同一)
- `eval/multi_agent/role_authorization_negative/`: AC-HARD 候補

## 却下案

(B/C/D は §選択肢 表参照)

## リスク / rollback

| リスク | 検知 | 軽減 |
|---|---|---|
| project custom role の cross-project 参照 | constraint trigger + service guard test | PE-F-012 strengthening (link table 案) を SP-013 で再評価 |
| Tier 2 で agent decider 経路残存 | `test_orchestrator_requester_only.py` + `eval/multi_agent/role_authorization_negative/` | DB CHECK + service guard + Pydantic + test 4 重防御 |
| max_* tenant_config override で絶対上限超え | DB CHECK | application で config 読込時に CHECK 違反 fail-closed |
| 既存 invariant break | Phase D R1-R4 + Phase E で全件 verify、SP-013-016 contract test | additive extension のみ、既存 invariant への新規 path なし |
| P0 期間中 multi-agent 経路露出 | P0 sealed CI guard (rg denylist) | TASKHUB_P0_1_OPENED env で gate 解除 |
| Hard Gate fixture multi-agent fail | SP-013 で AC-HARD-01/03/05/07 を multi-agent 文脈で再 verify | SP-022 で全件最終 verify |

### Migration rollback

1. `pg_dump` + age 暗号化 backup
2. staging で `alembic upgrade head` + `alembic check` + `tests/multi_agent/*` 全 pass
3. production migration 後の不整合検出 → `alembic downgrade -1` または forward-fix migration
4. rollback verify: `uv run pytest tests/multi_agent/* tests/db/test_schema_introspection.py tests/policy/test_action_class_enum.py -q`

### 運用 rollback (orchestrator 暴走)

1. kill-switch engage (全 active orchestrator に `orchestrator_kill_at = now()`)
2. tenant_config で max_children/depth/turns=0
3. project_agent_roles を soft-delete (deprecated_at)
4. 既存 single-agent run (parent_run_id IS NULL) は影響なし
5. `tests/multi_agent/*` 全 negative pass を staging で verify

## 関連

- ADR-00018 (Inter-Agent Communication Protocol)
- ADR-00019 (Role Taxonomy)
- ADR-00020 (Framework Intake Checklist)
- ADR-00009 update (policy_profile schema + DD-02/03/04 enum 同期)
- ADR-00004 update (event_type 22→31 + parent/child semantics)
- ADR-00013 update (orchestrator integration)
- Phase C draft: `docs/設計検討/phase-c-multi-agent-spec-draft.md` §1, §3

## 外部参照モデル (Symphony cross-reference、2026-05-12 追記)

本 ADR の multi-agent orchestration 設計は、2026-04-27 公開の **OpenAI Symphony** (`https://openai.com/index/open-source-codex-orchestration-symphony/`、`github.com/openai/symphony`、v1.1.0 時点で Kata CLI 経由 Claude Code 対応) の **参照モデル** として位置付ける。

### Symphony との対応関係

| Symphony | TaskManagedAI 対応 | 整合 |
|---|---|---|
| Linear ticket | `tickets` table + `agent_runs.ticket_id` | 1:1 mapping |
| ticket board = control plane | UI Sprint 9 (4 面 UI: Board / Task Detail / Approval / Execution Log) | concept 同一 |
| agent = worker | `agent_runs` + `actor_type='agent'` + `role_id` (10 standard role) | 既存 |
| human = reviewer | Approval Workflow + `decider_actor_id` human-only invariant | 既存 |
| 各 ticket に 1 agent 割当 | orchestrator dispatch + lease/heartbeat/failover (本 ADR §) | 既存 |
| 自律実行 → human review | AgentRun 16 状態 (`generated_artifact → schema_validated → policy_linted → diff_ready → waiting_approval`) | 既存 |

### 取り入れ方針 (ADR-00020 適用)

- **pattern adoption only**: ticket board → control plane の UX 設計を Sprint 9 / SP-013 で参照する
- **reference impl は取り込まない**: Symphony は Elixir/BEAM 実装、TaskManagedAI は Python/TypeScript で独自実装、ADR-00020 §3 (No code embed) 遵守
- **Linear 前提は不採用**: TaskManagedAI は内製 `tickets` table が control plane
- **OpenAI は Symphony を standalone product として maintain しない**: 仕様 drift リスクあり、本 ADR の参照 spec バージョンは v1.1.0 (2026-05-12 時点)

### 採用済み invariant の不変保証

Symphony 参照モデル採用後も、本 ADR 既存の以下 invariant は不変:

- 10 standard role + role ⊥ capability authorization
- orchestrator は requester only、approval decider にならない
- human-only approval (decider_actor_id は actor_type='human' 必須)
- lease/heartbeat/failover/kill-switch + max_* 上限
- agent 間 secret pass-through 禁止 (ADR-00018)
- inter_agent_messages atomic consume + payload_hash + previous_hash chain

詳細統合判定は `docs/設計検討/2026-05-12_external_ai_concept_uiux_integration.md` §3 参照。
