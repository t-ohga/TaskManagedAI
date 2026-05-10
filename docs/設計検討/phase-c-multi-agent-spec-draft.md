---
title: Phase C — TaskManagedAI Multi-Agent Vision 詳細仕様 draft
status: draft (Phase D R1+R2 完了 + 28 finding 全 adopt rewrite-v2、Phase E 未通過、Phase F 未着手)
created_at: 2026-05-10
updated_at: 2026-05-10 (Phase D R2 rewrite-v2)
related_phase: A + B + D R1 (20 findings) + D R2 (R1 6 fixed / 14 partially_fixed + 14 new findings = 計 28 件 adopt) 完了後 Claude orchestration draft
related_memory: project_taskmanagedai_vision_consolidation_plan.md
related_research: docs/設計検討/multi-agent-vision-research-plan.md
phase_d_findings_adopted: "計 28/28 全件 adopt (R1: PD-F-001〜PD-F-020 / R2: PD-R2-F-001〜PD-R2-F-014)"
finalize_in: ADR-00014 / 00015 / 00016 / 00017 / 00018 / 00019 / 00020 + ADR-00009 update (policy_profile + DD-02/03/04 同期) + ADR-00004 update (event_type 22→31 + parent/child semantics) + Tool Registry ADR (P0.1 で network_access enum 化) (Phase F)
existing_invariants_unchanged:
  - AgentRun 16 状態 + blocked サブ 3 (rules/agentrun-state-machine.md)
  - ContextSnapshot 10 列 (rules/core.md §9)
  - Provider Compliance v2 13 reason_code (rules/provider-compliance.md §9)
  - SecretBroker atomic claim + OperationContext fingerprint (rules/secretbroker-boundary.md §7-8)
  - Approval Workflow 4 整合 + decider human-only + self-approval 禁止 (rules/server-owned-boundary.md §3-4, ADR-00009)
  - Cross-source enum 5+ source 整合 (rules/cross-source-enum-integrity.md §1)
  - tool_mutating_gateway_stub / runner_mutation_gateway / remote_agent_gateway 3 gateway 分離 (ADR-00013)
  - 既存 action_class 7 種 (ADR-00009: task_write / repo_write / pr_open / secret_access / merge / deploy / provider_call、本仕様では拡張しない)
  - 全主要 table の id 型 = uuid、tenant_id のみ bigint NOT NULL DEFAULT 1 references tenants(id)
  - project boundary 強制 = 全 multi-agent 新 table で `(tenant_id, project_id, <foreign_id>)` 複合 FK (R2 PD-R2-F-001)
risk_mitigation_inputs:
  - B-2 CRITICAL 5 + HIGH 9 + 12 missing_safeguards + 7 anti-patterns
  - D-R1 20 findings + D-R2 14 findings + R1 partial 14 件詳細化 = 計 28 件
---

# Phase C — TaskManagedAI Multi-Agent Vision 詳細仕様 draft (Phase D R2 rewrite-v2)

> 本仕様は **Phase A + B (Codex Round 1-4) + Phase D R1 (20 findings) + Phase D R2 (R1 partial 14 件詳細化 + 14 new findings)** = 計 **28 finding 全件 adopt** で書き直した第 2 版 draft。Phase E (codex-adversarial-review) で固めてから Phase F で正式化されます。
>
> **既存 invariant は不変**。本仕様は **追加 (extension)** のみで、既存 invariant をいずれも上書きしません。R2 で発覚した「project boundary を tenant-only FK で逃げていた」(PD-R2-F-001 CRITICAL) は **全新 table で `(tenant_id, project_id, foreign_id)` 複合 FK 化** で修正済み。

---

## 0. Cross-Cutting Invariants (全 C-1〜C-5 共通必須)

### 0.1 取り込み方針 (3 layer、不変)

| Layer | 対象 | 採用 verdict |
|---|---|---|
| L1 (pattern only) | hermes-agent / MetaGPT / CrewAI / LangGraph / AutoGen / Anthropic Computer Use | **概念のみ取り込み**、TaskManagedAI 既存 boundary に再実装 |
| L2 (skip-as-embed) | AutoGPT autogpt_platform / 全 framework runtime / Swarm | **すべて skip** |
| L3 (TaskManagedAI 既存) | AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance / SecretBroker / Approval 4 整合 + decider human-only / 既存 action_class 7 種 / 3 gateway / id=uuid + tenant_id=bigint / project boundary 複合 FK | **絶対不変** |

### 0.2 Anti-patterns 12 件 reject 永続化 (Phase D で追加 5 件 = AP-8〜12 強化)

| # | rejected pattern | 永続 reject 根拠 |
|---|---|---|
| AP-1 | AutoGen 単一 global group chat as source of truth | R-001 |
| AP-2 | Role name/backstory as authorization boundary | R-009 / S-2 |
| AP-3 | Full framework embed | R-007/008/013/014 |
| AP-4 | Orchestrator auto-approval for high-risk | R-002 |
| AP-5 | Natural-language handoff → 直接 command/SQL/git/MCP 実行 | R-003/006 |
| AP-6 | Shared crew memory / external memory as ContextSnapshot replacement | R-013 / PD-F-014 |
| AP-7 | Hermes credential_pool soft lease | R-005 |
| AP-8 (D-R1) | action_class enum を新規追加 | PD-F-004 |
| AP-9 (D-R1) | agent (orchestrator/reviewer) を approval decider に | PD-F-005 |
| AP-10 (D-R1) | bigint ID を新 table に | PD-F-001/002/003 |
| AP-11 (D-R1+R2) | **project boundary を tenant-only FK で逃げる** (cross-project run/ticket/artifact 混在許容) | **PD-R2-F-001 CRITICAL** |
| AP-12 (D-R1+R2) | context_supplements jsonb を agent_runs に直接埋め込み + raw memory text 保存 | PD-F-014 |

### 0.3 共通必須 safeguard (R2 で 6 件追加 = 計 24 件)

| # | safeguard | 適用箇所 |
|---|---|---|
| S-1〜S-12 | (Phase B-2 由来、不変、§前版参照) | C-1〜C-5 |
| S-13 (D-R1) | 全 ID = uuid + tenant_id = bigint + 複合 FK | 全 DDL |
| S-14 (D-R1) | action_class 5 種追加→ event_type / Tool Registry / policy_profile に分散 | C-3 |
| S-15 (D-R1+R2) | Tier 2 = Policy Engine 自動 allow + policy_profile semantics ADR 化 (PD-R2-F-005) | C-3, ADR-00009 update |
| S-16 (D-R1+R2) | P0 sealed CI guard (`scripts/ci/check_p0_sealed_guard.sh` 擬似コード) (PD-R2-F-009) | C-3 |
| S-17 (D-R1) | memory retrieval = 別 table + immutable artifact ref + sanitizer_version | C-5 |
| S-18 (D-R1+R2) | orchestrator_dispatch remote child = remote_agent_gateway 経由必須、**P0/P0.1 ADR-00013 整合** (PD-R2-F-010) | C-3 |
| **S-19 (D-R2)** | **新 table 全 FK を `(tenant_id, project_id, foreign_id)` 複合 FK 化、parent table に `unique (tenant_id, project_id, id)` 追加** (PD-R2-F-001 CRITICAL) | 全新 table DDL |
| **S-20 (D-R2)** | **agent_runs.role_id project scope DB 防御** = constraint trigger or link table のいずれか確定 (PD-R2-F-002) | C-1 |
| **S-21 (D-R2)** | **review_artifacts.verdict 語彙を `pass/fail/needs_revision`** (Approval `approved/rejected` と衝突回避) (PD-R2-F-003) | C-3 |
| **S-22 (D-R2)** | **event_type 22→31 exact set + payload schema 表 + 5+ source 更新先 file 列挙** (PD-R2-F-004) | C-3, ADR-00004 update |
| **S-23 (D-R2)** | **policy_profile schema + 許可値 + profile ごとの action_class effect + project/tenant scope + unknown profile deny + policy_decisions 記録項目を ADR-00009 update で定義** (PD-R2-F-005) | C-3, ADR-00009 update |
| **S-24 (D-R2)** | **trusted_instruction CHECK に `action_class is not null` 追加** + approval target (artifact_hash/policy_version/fingerprint/action_class) の **server-owned refs 整合 FK/CHECK** (PD-R2-F-007 + R1 PD-F-020 partial) | C-2 |
| **S-25 (D-R2)** | **orchestrator_kpi_rollup を Phase C 本文 §3.8 に正式定義** (KPI ごとの source/query/dedupe/attribution、PD-R2-F-008 + R1 PD-F-015 partial) | C-3 §3.8 |
| **S-26 (D-R2)** | **agent_runs.orchestrator_lease_expires_at 列追加** + lease renew は token hash + renewed_at + expires_at を AgentRunEvent と同一 transaction (PD-R2-F-012 + R1 PD-F-007 partial) | C-3 |
| **S-27 (D-R2)** | **audit_events `inter_agent_message_sent/consumed/denied` 必須 payload schema 固定 + raw payload 非保存 test** (PD-R2-F-011) | C-2 |
| **S-28 (D-R2)** | **Tool Registry network_access boolean → enum 化 ADR (P0.1 で起票)** + P0 中は web_fetch/docs_search を deny-only (PD-R2-F-006 + R1 PD-F-017 partial) | C-3 |
| **S-29 (D-R2)** | **DD-02/03/04 ↔ ADR-00009 accepted enum 同期 task** (read/search 除去、provider_call 追加) を Phase F 前提に明記 (PD-R2-F-014) | Phase F 前提 |
| **S-30 (D-R2)** | **Sprint Pack DoD scaffold**: SP-013/014/015/016/018/022 を正式 Pack 直前レベル (acceptance/verification_commands/rollback/audit_events/hard_gate_kpi_trace/adr_refs) (PD-R2-F-013 + R1 PD-F-012 partial) | C §8 SP 個別小節 |
| **S-31 (D-R3)** | **artifact の project boundary strategy**: artifacts に project_id materialize (Phase F の DD-02 update で `(tenant_id, project_id, id)` unique 追加) + cross-project artifact negative test を inter_agent_messages/review_artifacts/memory_records すべて must_ship 化 (PD-R3-F-001) | 全 artifact_id 参照 table |
| **S-32 (D-R3)** | **approval_requests に artifact_hash/policy_version/provider_request_fingerprint 列追加** (Phase F の DD-02/ADR-00009 update + migration、現状は service 経由で resolve)。trusted_instruction approval target 4 整合の比較対象を明示 (PD-R3-F-002) | C-2, ADR-00009 update |
| **S-33 (D-R3)** | **policy_profile table を Phase C §3.9 に追加** (default + low_risk_auto_allow、action_class effect matrix、unknown profile deny、policy_decisions payload、AC-HARD-01 fixture 名) (PD-R3-F-003) | C-3 §3.9 |
| **S-34 (D-R3)** | **orchestrator_kpi_rollup source を既存正本に合わせる** (eval_scores/eval_runs / claims/evidence_items / repo_pr_opened まで限定、存在しない source 名削除) (PD-R3-F-004) | C-3 §3.8 |
| **S-35 (D-R3)** | **P0 sealed guard glob を recursive match に修正** + script self-test (forbidden/allowed positive/negative example) (PD-R3-F-005) | C-1 §1.6 |
| **S-36 (D-R3)** | **memory_records `unique (tenant_id, project_id, id)` を CREATE TABLE 内** に置く (memory_retrieval_artifacts FK 順序整合) (PD-R3-F-006) | C-5 §5.2 |
| **S-37 (D-R3)** | **agent_runs.role_scope CHECK を fail-closed**: `(role_id is null and role_scope is null) or (role_id is not null and role_scope in ('global','project'))` (PD-R3-F-007) | C-1 §1.4 |

---

## 1. C-1 — 役職定義 (Multi-Agent Role Taxonomy)

### 1.1 設計目標

不変 (会社メタファー / カスタム可 / role ⊥ authorization)。

### 1.2 標準役職 10 種 (code enum、5+ source、不変)

`backend/app/domain/agent_role/taxonomy.py` の `STANDARD_ROLE_IDS: frozenset[str]` で固定 (R1 確定):

```python
STANDARD_ROLE_IDS: Final[frozenset[str]] = frozenset({
    "orchestrator", "implementer", "reviewer", "tester", "security_agent",
    "researcher", "observer", "curator", "dispatcher", "repair_specialist",
})
```

5+ source: Python Literal + Pydantic Field validator + pytest EXPECTED constant + frontend TypeScript enum + (DB CHECK 不要、role_id は text 列).

### 1.3 custom role = project-scoped table (R1 確定 + R2 PD-R2-F-001 強化)

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
    unique (tenant_id, id),                                  -- S-19: parent unique
    unique (tenant_id, project_id, id),                      -- S-19: project boundary parent unique
    unique (tenant_id, project_id, role_id),
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, created_by_actor_id) references actors(tenant_id, id)
);

create index ix_project_agent_roles_active
    on project_agent_roles (tenant_id, project_id)
    where deprecated_at is null;
```

`recommended_action_class` 列は **存在しない** (R-009 / S-2 / AP-2 / AP-9).

### 1.4 agent_runs 拡張 + role_scope DB 防御 (R2 PD-R2-F-002 / S-20 fix)

```sql
alter table agent_runs
    add column role_id text,
    add column role_scope text check (role_scope in ('global','project')),
    add column orchestrator_lease_token uuid,
    add column orchestrator_lease_expires_at timestamptz,                   -- S-26 / R2 PD-R2-F-012 fix
    add column lease_renewed_at timestamptz,
    add column orchestrator_kill_at timestamptz,
    -- S-19: 親 table としての unique (project boundary 強制用)
    add constraint agent_runs_tenant_project_id_uniq unique (tenant_id, project_id, id),
    -- role_scope 整合 (S-37 / R3 PD-R3-F-007 + R4 PD-R4-F-002 fail-closed strict fix)
    -- PostgreSQL CHECK は UNKNOWN 真理値を許容するため、すべての NULL 判定を明示
    add constraint agent_runs_role_consistency check (
        (role_id is null and role_scope is null)
        or (role_id is not null and role_scope is not null and role_scope in ('global','project'))
    );
    -- negative test (SP-013 must_ship): (a) role_id non-null + role_scope null、
    --   (b) role_id null + role_scope='project'、(c) role_scope 未知値 の 3 case を全件 reject 確認

-- S-20: project custom role の DB 防御 = constraint trigger (採用案)
create or replace function check_project_role_link() returns trigger as $$
declare v_count int;
begin
    if new.role_scope = 'project' and new.role_id is not null then
        select count(*) into v_count from project_agent_roles
         where tenant_id = new.tenant_id
           and project_id = new.project_id
           and role_id = new.role_id
           and deprecated_at is null;
        if v_count = 0 then
            raise exception 'role_id % not found in project_agent_roles for tenant=% project=%',
                new.role_id, new.tenant_id, new.project_id;
        end if;
    elsif new.role_scope = 'global' and new.role_id is not null then
        -- STANDARD_ROLE_IDS は code enum、application layer で validate
        null;
    end if;
    return new;
end;
$$ language plpgsql;

create trigger agent_runs_check_project_role
    before insert or update of role_id, role_scope on agent_runs
    for each row execute function check_project_role_link();
```

(代案 B: `agent_run_project_roles` link table で FK を張る案も検討。Phase F の SP-013 着手時に最終決定、現時点では trigger 採用案を default).

### 1.5 role ⊥ capability authorization (不変、R-009 / S-2 / AP-2)

(R1 確定の通り) authorization の正本は Policy Engine + Approval + SecretBroker + ProviderAdapter + Tool Registry + 3 gateway。`project_agent_roles` に `recommended_action_class` 列なし.

### 1.6 P0 sealed CI guard 擬似コード (S-16 / R2 PD-R2-F-009 fix)

`scripts/ci/check_p0_sealed_guard.sh` (Sprint 1 で起票、P0.1 着手時に解除).

**実行 shell の固定 (R4 PD-R4-F-004 fix)**: CI / hook から必ず `bash scripts/ci/check_p0_sealed_guard.sh` で起動 (zsh native 実行は禁止、`case ... in $pat)` の glob expansion semantic が異なる)。`#!/usr/bin/env bash` shebang + CI 設定で `shell: bash` 明示。shell 非依存にしたい場合は将来 Python `fnmatch` 実装に置き換え可。

```bash
#!/usr/bin/env bash
# check_p0_sealed_guard.sh - P0 期間中 (Sprint 1-12) の multi-agent path 追加を deny する CI gate
set -euo pipefail

# P0.1 開始フラグ (P0.1 accepted gate で env で制御)
if [ "${TASKHUB_P0_1_OPENED:-0}" = "1" ]; then
    echo "P0.1 opened, sealed guard inactive."
    exit 0
fi

CHANGED=$(git diff --name-only origin/main...HEAD)

# forbidden globs (multi-agent implementation paths、S-35 / R3 PD-R3-F-005 fix: recursive match)
forbidden=(
    'backend/app/db/models/project_agent_role.py'
    'backend/app/db/models/inter_agent_message.py'
    'backend/app/db/models/memory_record.py'
    'backend/app/db/models/memory_retrieval_artifact.py'
    'backend/app/db/models/review_artifact.py'
    'backend/app/services/orchestrator/*'                          # recursive (R3 fix)
    'backend/app/services/inter_agent/*'                           # recursive (R3 fix)
    'backend/app/services/memory/*'                                # recursive (R3 fix)
    'backend/app/services/remote_agent_gateway.py'
    'frontend/app/(admin)/agent-roles/*'                           # recursive (R3 fix)
    'frontend/app/(admin)/orchestrator/*'                          # recursive (R3 fix)
    'cli/tm/*'                                                     # recursive (R3 fix)
    'migrations/versions/*multi_agent*'
    'migrations/versions/*orchestrator*'
    'migrations/versions/*memory*'
    'migrations/versions/*inter_agent*'
    'migrations/versions/*project_agent_role*'
)
# self-test fixture: tests/scripts/test_p0_sealed_guard.sh で
# forbidden positive (`backend/app/services/orchestrator/dispatcher.py` 等の deep file) → reject
# allowed exception positive (`docs/adr/00014_*.md` 等) → pass
# negative example (`backend/app/services/policy/engine.py` 等の P0 通常 path) → pass

# allowed exception globs (docs / ADR drafts)
allowed=(
    'docs/設計検討/phase-c-*.md'
    'docs/設計検討/multi-agent-*.md'
    'docs/設計検討/harness-v5-*.md'
    'docs/adr/00014_*.md' 'docs/adr/00015_*.md' 'docs/adr/00016_*.md'
    'docs/adr/00017_*.md' 'docs/adr/00018_*.md' 'docs/adr/00019_*.md'
    'docs/adr/00020_*.md'
    'docs/sprints/SP-013_*.md' 'docs/sprints/SP-014_*.md'
    'docs/sprints/SP-015_*.md' 'docs/sprints/SP-016_*.md'
    'docs/sprints/SP-017_*.md' 'docs/sprints/SP-018_*.md'
    'docs/sprints/SP-019_*.md' 'docs/sprints/SP-020_*.md'
    'docs/sprints/SP-021_*.md' 'docs/sprints/SP-022_*.md'
)

violations=()
while IFS= read -r f; do
    [ -z "$f" ] && continue
    is_forbidden=0
    for pat in "${forbidden[@]}"; do
        case "$f" in $pat) is_forbidden=1; break;; esac
    done
    [ "$is_forbidden" = 0 ] && continue
    is_allowed=0
    for pat in "${allowed[@]}"; do
        case "$f" in $pat) is_allowed=1; break;; esac
    done
    [ "$is_allowed" = 0 ] && violations+=("$f")
done <<< "$CHANGED"

if [ "${#violations[@]}" -gt 0 ]; then
    echo "P0 sealed guard violation: multi-agent implementation paths added during P0 period"
    printf '  %s\n' "${violations[@]}"
    exit 1
fi
echo "P0 sealed guard passed."
```

migration prefix の規約: P0.1 から始まる migration は `00NN_p0_1_<feature>.py`、CI は migration ファイル名で P0.1 開始を識別.

P0.1 解除 gate: ADR-00014/15/18/19 が accepted + SP-013 kickoff migration `00NN_p0_1_multi_agent_foundation.py` 投入直前に `TASKHUB_P0_1_OPENED=1` を CI env で設定.

---

## 2. C-2 — エージェント間会話場 (Inter-Agent Communication)

### 2.1 設計選択 (R1 確定: 案 2 採用、案 1/3 reject、不変)

### 2.2 inter_agent_messages 12 fields + project boundary 強制 (R2 PD-R2-F-001/007 fix)

```sql
create table inter_agent_messages (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid not null,
    parent_run_id uuid not null,
    child_run_id uuid,
    sender_actor_id uuid not null,
    sender_run_id uuid not null,
    receiver_kind text not null
        check (receiver_kind in ('agent_run', 'role', 'broadcast')),
    receiver_ref text,
    data_class text not null
        check (data_class in ('public','internal','confidential','pii')),
    trust_level text not null default 'untrusted_content'
        check (trust_level in ('untrusted_content','validated_artifact','trusted_instruction')),
    -- trusted_instruction の server-owned refs (S-24 / R2 PD-R2-F-007 fix):
    approval_request_id uuid,
    source_artifact_id uuid,
    artifact_hash text,
    policy_version text,
    provider_request_fingerprint text,
    action_class text,
    -- payload + replay defense:
    payload_hash text not null,
    artifact_ref text not null,
    seq_no bigint not null,
    previous_hash text,
    schema_version text not null,
    idempotency_key text not null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    consumed_at timestamptz,
    consumed_by_run_id uuid,
    -- S-19: project boundary 複合 FK (R2 PD-R2-F-001 CRITICAL fix):
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, project_id, parent_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, child_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, sender_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, consumed_by_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, sender_actor_id) references actors(tenant_id, id),
    foreign key (tenant_id, approval_request_id) references approval_requests(tenant_id, id),
    foreign key (tenant_id, source_artifact_id) references artifacts(tenant_id, id),
    unique (tenant_id, parent_run_id, seq_no),
    unique (tenant_id, parent_run_id, idempotency_key),
    -- self-consume 禁止
    check (sender_run_id <> consumed_by_run_id or consumed_by_run_id is null),
    -- trusted_instruction の必須 refs + action_class enum 部分集合 (S-24 / R2 PD-R2-F-007 fail-open fix):
    check (
        trust_level <> 'trusted_instruction'
        or (approval_request_id is not null
            and source_artifact_id is not null
            and artifact_hash is not null
            and policy_version is not null
            and provider_request_fingerprint is not null
            and action_class is not null
            and action_class in ('task_write','repo_write','pr_open','secret_access','provider_call'))
    )
);

create index ix_inter_agent_messages_unconsumed
    on inter_agent_messages (tenant_id, project_id, parent_run_id, seq_no)
    where consumed_at is null;
```

R2 PD-R2-F-001 mitigation: parent_run_id / child_run_id / sender_run_id / consumed_by_run_id すべて `(tenant_id, project_id, id)` 複合 FK で project boundary 強制。これは agent_runs に `unique (tenant_id, project_id, id)` 制約追加 (§1.4 で記述済) が前提.

### 2.3 trusted_instruction の approval target 整合 FK/CHECK (S-24 / R1 PD-F-020 partial fix)

trusted_instruction message の `approval_request_id` が指す approval_requests の `artifact_hash` / `policy_version` / `provider_request_fingerprint` / `action_class` と message 側の同名 fields が **完全一致** することを service layer + Pydantic + contract test で 4 重防御:

- service layer: message validate 時に approval_request_id を resolve、4 fields を compare、不一致は reject
- Pydantic validator: same approval target 整合性を schema validate
- DB CHECK は cross-table 比較不可のため、application 層で enforce
- contract test: 6 negative case (approval_id substitution / artifact_hash substitution / policy_version drift / fingerprint substitution / action_class substitution / 期限切れ approval reuse)

### 2.4 3 trust_level handling (R1 確定、不変)

| trust_level | server-owned refs | 受信側 prompt template |
|---|---|---|
| `untrusted_content` (default) | 不要 | UNTRUSTED INPUT で囲む、content として扱う |
| `validated_artifact` | 不要 (artifact_ref から payload_hash 検証) | typed object として渡す |
| `trusted_instruction` | 必須 (approval_request_id 等 6 fields + action_class enum 部分集合) | approval ID 添付、message self-claim 無視、server-owned refs を信頼源 |

### 2.5 atomic consume + replay/hijack defense (R1 確定、不変)

### 2.6 audit_events 必須 payload schema (S-27 / R2 PD-R2-F-011 fix)

`audit_events` table の inter-agent 関連 3 種に **必須 payload schema 固定**:

| event_type | 必須 payload (NULL 不可、各 field の DB CHECK or service guard) | 禁止 payload |
|---|---|---|
| `inter_agent_message_sent` | tenant_id, project_id, parent_run_id, sender_run_id, sender_actor_id, receiver_kind, receiver_ref, seq_no, payload_hash, data_class, trust_level, schema_version, redaction_status | message body / artifact 本体 / secret / capability token |
| `inter_agent_message_consumed` | tenant_id, project_id, parent_run_id, consumed_by_run_id, message_id (hash), seq_no, previous_hash_match, payload_hash, redaction_status | 同上 |
| `inter_agent_message_denied` | tenant_id, project_id, parent_run_id, attempted_message_id (hash), seq_no, denial_reason (`already_consumed` / `expired` / `cross_parent` / `cross_tenant` / `cross_project` / `previous_hash_mismatch` / `replay_detected` / `untrusted_promotion_attempt` / `approval_target_mismatch`), redaction_status | 同上 |

`tests/audit/test_inter_agent_no_raw_payload.py` で `assert_no_raw_secret_and_no_raw_message_body(audit_event)` を SP-015 must_ship.

### 2.7 AgentRunEvent ref 連動 (R1 確定、不変)

各 run の timeline には `inter_agent_message_sent_ref` / `inter_agent_message_consumed_ref` の AgentRunEvent を append (raw payload なし、message_id + payload_hash + seq_no + sender_run_id + receiver_run_id + redaction_status のみ).

---

## 3. C-3 — 完全自律性の境界

### 3.1〜3.2 (R1 確定の通り)

### 3.3 review_artifacts table (S-21 / R2 PD-R2-F-003 fix: verdict 語彙変更)

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
    -- S-21: verdict 語彙を Approval (approved/rejected) と分離 (R2 PD-R2-F-003 fix):
    review_verdict text not null check (review_verdict in ('pass','fail','needs_revision')),
    findings_count int not null default 0,
    created_at timestamptz not null default now(),
    -- S-19: project boundary 複合 FK
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, project_id, parent_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, requester_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, reviewer_run_id)
        references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, review_target_artifact_id) references artifacts(tenant_id, id),
    foreign key (tenant_id, review_artifact_id) references artifacts(tenant_id, id),
    -- 4 重防御 layer 1: DB 直接 enforce
    check (reviewer_run_id <> requester_run_id)
);

-- 4 重防御 layer 2/3/4 (R1 PD-F-006 partial fix):
-- service layer: reviewer_run_id の role_id='reviewer' を service guard で確認
-- Pydantic validator: reviewer_run と requester_run が同 parent_run_id 配下を validate
-- contract test: tests/multi_agent/test_review_artifact_4_defense.py で reviewer != requester / role=reviewer / parent 同一 / project 同一 を全 negative case 確認
```

`review_verdict` は **agent が出す値**、Approval (`approved/rejected`) と semantic 分離。Policy Engine は review_artifact を `validated_artifact` (trust_level) として input.

### 3.4 orchestrator lease 拡張 (S-26 / R2 PD-R2-F-012 fix)

§1.4 の `agent_runs.orchestrator_lease_expires_at timestamptz` 列追加で完全保証。lease renew は同一 transaction で:

```sql
update agent_runs
   set orchestrator_lease_token = :new_token_uuid,
       lease_renewed_at = now(),
       orchestrator_lease_expires_at = now() + interval '5 minutes'
 where tenant_id = :tenant_id
   and id = :orchestrator_run_id
   and orchestrator_lease_token = :current_token_uuid           -- atomic claim
   and orchestrator_lease_expires_at > now()
returning id;

-- 同一 transaction で AgentRunEvent append:
insert into agent_run_events (..., event_type, payload)
values (..., 'orchestrator_lease_renewed',
        jsonb_build_object(
            'lease_token_hash', :token_hash,
            'renewed_at', now(),
            'expires_at', now() + interval '5 minutes'
        ));
```

lease expiry 検出 = `orchestrator_lease_expires_at < now()` を DB row + AgentRunEvent payload 両方から説明可能.

kill-switch guard 明確化:
- `orchestrator_kill_at IS NOT NULL` のとき、active children を `cancel_requested -> cancelled` で graceful suspend (default)
- ユーザー指示 (UI/CLI) で `force_kill=true` なら `blocked + runtime_blocked` (既存 blocked_reason)
- terminal child は変更不可 (DB CHECK + service guard)

### 3.5 remote_agent_gateway P0/P0.1 整合 (S-18 / R2 PD-R2-F-010 fix)

ADR-00013 の「P0 中は `backend/app/services/remote_agent_gateway.py` 作成禁止」と Phase C の「P0.1 accepted まで deny-only stub」を **整合**:

| 期間 | remote_agent_gateway 状態 |
|---|---|
| P0 (Sprint 1-12) | 実装 path **完全になし** (P0 sealed guard で `backend/app/services/remote_agent_gateway.py` を禁止)、Phase C / ADR-00014 spec 内で「remote child は本仕様時点では未実装、deny されるべき経路」と宣言 |
| P0.1 開始時 (Sprint 13 着手時) | P0 sealed guard 解除と同時に `remote_agent_gateway.py` deny-only stub を作成 (orchestrator_dispatched が remote child 作成試行 → 全件 deny + audit) |
| P0.1〜P1 (SP-014/SP-018+) | deny-only stub から徐々に Codex app-server / Claude Agent SDK を ADR-00013 の段階的承認で許可 (各承認時に stub 拡張) |

P0 中 orchestrator_dispatched event は spec 上は許容されるが、remote child 作成経路がないため local child のみ生成される.

### 3.6 read_only_research = Tool Registry operation (S-28 / R2 PD-R2-F-006 fix)

Tool Registry 現行 schema (`network_access boolean`) と Phase C の TOML (`network_access = "allowlist"` enum + `domain_allowlist` 等) が不一致.

**Phase F 前提 task**: Tool Registry network_access ADR を P0.1 開始前に起票:
- 現行 boolean `network_access` を enum (`none`, `allowlist`, `internet`) に変更
- 別 table `tool_network_policies` に `domain_allowlist text[]`, `payload_data_class_max text`, `provider_required boolean`, `provider_request_preflight_required boolean`, `audit_event_type text` を保存
- 新 table `tool_network_policies` の DDL は P0.1 migration で投入
- P0 中は既存 `network_access=false` を維持 (web_fetch / docs_search を deny-only)

P0 期間中 read_only_research の Tool Registry tool は **未登録 = deny**、P0.1 SP-014 で Tool Registry network policies + tool 登録.

### 3.7 event_type 22 → 31 exact set + payload schema (S-22 / R2 PD-R2-F-004 fix)

ADR-00004 update の差分として、追加 9 event_type を以下に固定 (exact set + payload schema + state transition + audit_events 責務分担):

| # | event_type (新 9 種) | 発火 state transition | 必須 payload (raw secret なし) | audit_events 責務分担 | status update 同一 transaction |
|---:|---|---|---|---|---|
| 23 | `orchestrator_dispatched` | running | child_run_id, role_id, role_scope, dispatch_reason, recommended_provider | (audit_events に重複なし、AgentRunEvent のみ) | 必要 (新 child run の status='queued' と同一 transaction) |
| 24 | `orchestrator_lease_renewed` | running | lease_token_hash, renewed_at, expires_at | (AgentRunEvent のみ) | 必要 (lease UPDATE と同一) |
| 25 | `orchestrator_lease_expired` | running -> blocked or running | old_lease_hash, expired_at, reason_code | (AgentRunEvent のみ) | 必要 (status update があれば同一) |
| 26 | `orchestrator_failover_triggered` | running | old_lease_hash, new_orchestrator_run_id, new_lease_hash, reason_code | audit_events `orchestrator_failover` (cross-run) | 必要 |
| 27 | `orchestrator_kill_engaged` | running -> blocked (runtime_blocked) | engaged_by_actor_id (human only via UI/CLI), reason | audit_events `orchestrator_kill_engaged` | 必要 |
| 28 | `inter_agent_message_sent_ref` | (status 変化なし) | message_id, payload_hash, seq_no, sender_run_id, receiver_run_id, redaction_status | audit_events `inter_agent_message_sent` (cross-run) | 必要 (message INSERT と同一) |
| 29 | `inter_agent_message_consumed_ref` | (status 変化なし) | 同上 + previous_hash_match | audit_events `inter_agent_message_consumed` | 必要 (consume UPDATE と同一) |
| 30 | `tool_web_fetch_executed` | running | tool_name, domain, provider, payload_data_class, redaction_status | (AgentRunEvent のみ、SP-014 で audit_events 拡張検討) | 不要 (tool 実行後の record) |
| 31 | `tool_docs_search_executed` | running | 同上 | 同上 | 不要 |

**5+ source 更新先 (cross-source-enum-integrity §1)**:
- DB CHECK: `migrations/versions/00NN_p0_1_event_type_31.py` で `agent_run_events.event_type` CHECK 拡張
- ORM CheckConstraint: `backend/app/db/models/agent_run_event.py`
- Python Literal: `backend/app/domain/agent_run/event_types.py` の `EVENT_TYPES: frozenset` (22+9=31)
- Pydantic: `agent_run_event/schemas.py`
- pytest: `tests/agent_runtime/test_event_type_enum.py` の `EXPECTED_EVENT_TYPES` (31)
- frontend: `frontend/lib/domain/agent-run-event.ts` (Sprint 17 で TypeScript enum)

`existing 22 -> 23` の数字揺れ表記は完全削除 (R2 PD-R2-F-004 fix).

### 3.8 orchestrator_kpi_rollup 仕様 (S-25 + S-34 / R3 PD-R3-F-004 で source を既存正本に合わせる)

各 KPI の source は **既存正本** に固定。存在しない source 名は削除。`is_final_adopted` 等の存在しない column は ADR-00004 update で artifacts に追加または adopted_artifact_id 経由で resolve するかを Phase F で確定 (現時点では既存 source で読める形に絞る):

| KPI | source (既存正本) | query 概要 | dedupe key | parent/child attribution | excluded runs | test fixture |
|---|---|---|---|---|---|---|
| `acceptance_pass_rate` | `eval_runs` + `eval_scores` (既存、DD-02 §eval) | eval_score per run / fixture を pass/total で集計、parent ticket 単位で aggregate | (run_id, fixture_id) | child eval の評価を parent ticket に attribute | cancelled / blocked terminal | `tests/metrics/test_acceptance_pass_rate_rollup.py` (SP-011 / SP-014 拡張) |
| `time_to_merge` | **current source**: `agent_run_events.event_type='repo_pr_opened'` (既存 22 event_type 内、ADR-00004 既存)。**future source** (Phase F で要 ADR-00004 update): `repo_pr_merged` event_type 追加 + 5+ source 同期 + migration + fixture (現時点では未定義のため source として使えない)。**現時点の計測**: `repo_pr_opened` から `agent_runs.completed_at` (terminal completed) までの elapsed を proxy として使用、Phase F の ADR-00004 update で `repo_pr_merged` 正式追加後に切替 (R4 PD-R4-F-001 fix) | parent ticket の最初の PR open から完了までの elapsed | parent_ticket_id | RepoProxy 経由のみ (P0 では mock merge、P0.1 以降は本実装) | non-PR run / cancelled | `tests/metrics/test_time_to_merge.py` (Sprint 11 起点 + SP-014 multi-agent 拡張) |
| `approval_wait_ms` | `approval_requests.requested_at` + `approval_requests.decided_at` (既存 DD-02) | approval ごとに 1 度 elapsed | `approval_requests.id` (1 度のみ計測、parent/child 重複なし) | approval per measurement、dedupe key で重複排除 | invalidated / expired | 既存 + `tests/metrics/test_approval_wait_dedupe_multi_agent.py` (SP-014) |
| `citation_coverage` | `claims` + `evidence_items` (既存 DD-02) + adopted artifact 識別 (Phase F の DD-02 update で artifacts に `adopted_for_ticket_id uuid` または `is_final_adopted boolean` 追加、または専用 link table `adopted_artifacts` 新設の 2 案を Phase F で確定) | adopted artifact ごとの claim/evidence 充足率 | (claim_id, source_id) | parent run の adopted artifact のみ、child draft 除外 | non-adopted | `tests/metrics/test_citation_coverage_final_only.py` (SP-014) |
| `cost_per_completed_task` | `agent_run_events.event_type='provider_responded'` の usage payload (既存) | parent + 全 descendant child の token cost / wall-clock を sum | parent_ticket_id | parent + 全 descendant child を sum | cancelled / blocked terminal / non-completed | `tests/metrics/test_cost_per_task_rollup.py` (SP-014) |

各 KPI の test fixture は SP-014 (orchestrator) と SP-018 (memory) で must_ship (S-30 / R2 PD-R2-F-013 fix).

### 3.9 policy_profile schema (S-33 / R3 PD-R3-F-003 + R4 PD-R4-F-005 fix)

**R4 で発覚した前提 task (R4 PD-R4-F-005)**: 現行 DD-02 の `policy_rules` / `approval_requests` / `policy_decisions` の `action_class` CHECK は legacy `read/search` を含み `provider_call` を含まない (ADR-00009 accepted enum 7 種と drift)。**policy_profile migration 投入前に DD-02 3 table の action_class CHECK を ADR-00009 7 種同期** (`read/search` 削除 + `provider_call` 追加)。同期手順:

```text
Step 1: DD-02 update で policy_rules / approval_requests / policy_decisions の action_class CHECK 改訂 (read/search 削除 + provider_call 追加)
Step 2: 既存 row で `action_class='read/search'` を持つ row を Tool Registry `allowed_actions` 経由 (Sprint 4.5 の boundary) に migration、または非該当として archive
Step 3: ADR-00009 update を accepted、CHECK 同期 migration を P0.1 着手前に投入
Step 4: policy_profile_action_effects は 7 種同期完了後に追加可
```

P0 では `task_write` 等の require_approval を ADR-00009 で定義済。P0.1 で `auto_approve_low_risk` を導入するため policy_profile を新規定義:

```sql
-- P0.1 migration で追加
create table policy_profiles (
    tenant_id bigint not null default 1 references tenants(id),
    profile_id text not null check (profile_id in ('default','low_risk_auto_allow')),
    description text not null,
    created_at timestamptz not null default now(),
    primary key (tenant_id, profile_id)
);

-- profile ごとの action_class effect matrix
create table policy_profile_action_effects (
    tenant_id bigint not null default 1 references tenants(id),
    profile_id text not null,
    action_class text not null
        check (action_class in ('task_write','repo_write','pr_open','secret_access','merge','deploy','provider_call')),
    effect text not null check (effect in ('allow','deny','require_approval')),
    require_review_artifact boolean not null default false,
    primary key (tenant_id, profile_id, action_class),
    foreign key (tenant_id, profile_id) references policy_profiles(tenant_id, profile_id)
);
```

**初期 seed (P0.1)**:

| profile_id | action_class | effect | require_review_artifact |
|---|---|---|---|
| `default` | task_write | require_approval | false (既存 ADR-00009) |
| `default` | repo_write/pr_open/secret_access/merge/deploy/provider_call | (既存通り) | false |
| `low_risk_auto_allow` | task_write | **allow** (artifact のみ、kind allowlist で限定) | **true** (review_artifact verdict='pass' 必須) |
| `low_risk_auto_allow` | provider_call | **allow** (zdr_eligible=yes only、payload_data_class<=internal) | true |
| `low_risk_auto_allow` | repo_write/pr_open/secret_access/merge/deploy | **deny** | - |

**unknown profile deny**: `projects.policy_profile` (既存 default text) が `policy_profiles` 未登録なら全 action deny。

**policy_decisions payload に追加**: `policy_profile text not null`、`profile_resolved_effect text not null`、`required_review_artifact_id uuid null`.

**AC-HARD-01 fixture 追加**: `eval/security/policy_block/p0_1_low_risk_auto_allow_unknown_profile_deny/manifest.json` で unknown profile を deny する fixture を SP-014 で must_ship.

### 3.10 trusted_instruction approval target storage (S-32 / R3 PD-R3-F-002 fix)

trusted_instruction message の `approval_request_id` が指す approval の 4 整合 (artifact_hash / policy_version / provider_request_fingerprint / action_class) を比較するため、**approval_requests に該当列を追加**:

```sql
-- Phase F の DD-02/ADR-00009 update + P0.1 migration
alter table approval_requests
    add column artifact_hash text,
    add column policy_version text,
    add column provider_request_fingerprint text;
-- (action_class は既存 column)
```

**現状代替 (P0.1 migration 投入前まで)**: artifact_hash 等は `policy_decisions.input_hash` + `context_snapshots.provider_request_fingerprint` 経由で resolve。inter_agent_messages 側の `artifact_hash` / `policy_version` / `provider_request_fingerprint` を以下 query で verify:

```sql
-- trusted_instruction message validation query (current approach)
select pd.input_hash as artifact_hash,
       pd.policy_version,
       cs.provider_request_fingerprint,
       ar.action_class
  from approval_requests ar
  join policy_decisions pd on pd.tenant_id = ar.tenant_id and pd.approval_request_id = ar.id
  join agent_runs ru on ru.tenant_id = ar.tenant_id and ru.id = ar.run_id
  join context_snapshots cs on cs.tenant_id = ru.tenant_id and cs.id = ru.current_snapshot_id
 where ar.tenant_id = :tenant_id and ar.id = :approval_request_id and ar.status = 'approved';
```

P0.1 migration 投入後は approval_requests 直接 column 比較に切替。**negative test 4 cases**: artifact_hash / policy_version / fingerprint / action_class 各 substitution → 全件 deny.

### 3.11 artifact project boundary strategy (S-31 / R3 PD-R3-F-001 fix)

artifacts は現状 project_id を持たない。multi-agent 文脈で trusted_instruction / review_artifact / memory_records が cross-project artifact を参照できる余地を防ぐため:

**Phase F で確定する 2 案**:

| 案 | 概要 | 利点 | 欠点 |
|---|---|---|---|
| **A: artifacts に project_id 列を materialize** | artifacts に `project_id uuid not null` 追加 + `(tenant_id, project_id, id)` unique 追加 | 全参照側で複合 FK 一発、最も clean | 既存 artifacts の backfill migration 必要 |
| B: composite proof (artifact_id + run_id) 必須 | 各参照 table で `artifact_id` + `run_id` を持ち、run の project と一致を service layer で確認 | migration 不要 | service layer 依存、DB level 強制不可 |

**default**: 案 A を Phase F の DD-02 update で採用、SP-013 の must_ship に **backfill migration 6 段階手順** (R4 PD-R4-F-003 fix):

```text
Step 1: artifacts に project_id uuid NULL ADD (nullable で追加)
Step 2: run_id non-null artifacts は agent_runs.project_id から JOIN backfill
        UPDATE artifacts a SET project_id = r.project_id
          FROM agent_runs r
         WHERE a.tenant_id = r.tenant_id AND a.run_id = r.id AND a.project_id IS NULL;
Step 3: run_id NULL artifacts (global artifacts) の扱いを明文化:
        - 案 A1: 削除 (P0 期間中に作られた評価固有 artifact が該当する場合は eval domain owner と確認)
        - 案 A2: 専用 global_artifacts table に分離 (artifacts は project-scoped only に集約)
        - 案 A3: tenant の system project (`tenant_default_project_id`) を作って backfill
        SP-013 では A2 を default 案として採用 (運用判断、ADR-00014 update で確定)
Step 4: project_id NULL が 0 件であることを assert (`SELECT count(*) FROM artifacts WHERE project_id IS NULL` = 0)
Step 5: ALTER TABLE artifacts ALTER COLUMN project_id SET NOT NULL;
Step 6: ALTER TABLE artifacts ADD UNIQUE (tenant_id, project_id, id);
        全参照側 table の FK を `(tenant_id, project_id, source_artifact_id) references artifacts(tenant_id, project_id, id)` に切替
```

**案 B 採用条件**: Step 3 の global artifact が技術的に分離不可 (eval / 統計 用途で project 横断必須) と判明した場合のみ。その場合は service layer + Pydantic + contract test の 3 重防御で cross-project artifact reference を reject (DB level FK は使わず service-only).

**現状代替 (P0.1 migration 投入前)**: cross-project artifact negative test を inter_agent_messages / review_artifacts / memory_records 全 must_ship に追加 (試行 → service layer reject)、`tests/multi_agent/test_artifact_cross_project_negative.py` を SP-013/015/018 で実行.

---

## 4. C-4 — UI ↔ CLI Parity 仕様 (R1 + R2 確定の通り、変更なし)

(R1 既定通り。CLI 短命 capability token TTL 5-30 分、refresh credential のみ profile 保存、`tm` 13 capability + memory 除外、parity contract test).

---

## 5. C-5 — メモリー記録 (R1 + R2 強化)

### 5.1〜5.2 memory_records (R2 PD-R2-F-001 / R1 PD-F-003 fix で project boundary 強化)

```sql
create table memory_records (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid not null,
    record_kind text not null check (record_kind in
        ('manual_user', 'manual_agent', 'auto_completion', 'auto_failure', 'auto_review_finding')),
    source_run_id uuid,                                      -- auto record kind は service guard で NOT NULL 強制
    source_ticket_id uuid,
    source_artifact_id uuid,
    title text not null,
    content_artifact_ref text not null,
    content_hash text not null,
    tags text[] not null default '{}',
    data_class text not null default 'internal'
        check (data_class in ('public','internal','confidential','pii')),
    redaction_status text not null default 'redacted'
        check (redaction_status in ('redacted','raw_with_canary_scan_passed')),
    sanitizer_version text not null,
    created_by_actor_id uuid not null,
    created_at timestamptz not null default now(),
    archived_at timestamptz,
    -- S-19: project boundary 複合 FK (R2 PD-R2-F-001 / R1 PD-F-003 fix):
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, project_id, source_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, source_ticket_id) references tickets(tenant_id, project_id, id),
    foreign key (tenant_id, source_artifact_id) references artifacts(tenant_id, id),  -- §3.11 案 A 採用後は (tenant_id, project_id, source_artifact_id)
    foreign key (tenant_id, created_by_actor_id) references actors(tenant_id, id),
    -- S-36 / R3 PD-R3-F-006 fix: parent unique を CREATE TABLE 内で先に定義
    unique (tenant_id, project_id, id),
    -- auto record の source_run NOT NULL 強制 (R1 PD-F-003 partial fix):
    check (
        record_kind not in ('auto_completion', 'auto_failure', 'auto_review_finding')
        or source_run_id is not null
    )
);
-- (index と tsvector + GIN は R1 通り、不変)
```

R2 で追加: tickets parent table に `unique (tenant_id, project_id, id)` 制約が必要 (Phase F の DD-02 update)。artifacts は project_id を持たないため、artifact の project boundary は run_id 経由で証明 (`source_run_id` の project と memory_records.project_id 一致を service guard で確認).

### 5.3 memory_retrieval_artifacts (R2 PD-R2-F-001 fix)

```sql
create table memory_retrieval_artifacts (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid not null,
    run_id uuid not null,
    snapshot_id uuid,
    memory_record_id uuid not null,
    relevance_score numeric(4,3) not null check (relevance_score between 0.000 and 1.000),
    snippet_artifact_ref text not null,
    snippet_hash text not null,
    payload_data_class text not null
        check (payload_data_class in ('public','internal','confidential','pii')),
    redaction_status text not null
        check (redaction_status in ('redacted','raw_with_canary_scan_passed')),
    sanitizer_version text not null,
    trust_level text not null default 'untrusted_content'
        check (trust_level = 'untrusted_content'),
    created_at timestamptz not null default now(),
    -- S-19: project boundary 複合 FK
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, project_id, run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, memory_record_id) references memory_records(tenant_id, project_id, id)
);
-- memory_records の unique は §5.2 CREATE TABLE 内で定義済 (S-36 / R3 PD-R3-F-006 fix)、別 migration ALTER 不要
```

### 5.4〜5.7 (R1 確定の通り)

---

## 6. 既存 Invariant 整合 chart (R2 強化)

| 既存 invariant | C-1 | C-2 | C-3 | C-4 | C-5 |
|---|---|---|---|---|---|
| 全 invariant | (R1 通り、不変) | (R1 通り) | ○ R2 強化 (review_verdict pass/fail/needs_revision、policy_profile semantics ADR、event_type 31 exact、kpi_rollup 本文化、Tool Registry enum 化、remote_agent P0/P0.1 整合) | (R1 通り) | ○ R2 強化 (project boundary 複合 FK、auto record source_run NOT NULL CHECK) |
| project boundary 複合 FK (S-19) | ○ project_agent_roles + agent_runs unique | ○ inter_agent_messages 全 FK | ○ review_artifacts 全 FK | - | ○ memory_records / memory_retrieval_artifacts 全 FK |

**全 invariant は不変または additive extension のみ**。breaking change なし.

---

## 7. ADR mapping (Phase F で proposed → accepted、R2 強化)

| ADR | 主題 | 関連既存 ADR update |
|---|---|---|
| ADR-00014 | Multi-Agent Orchestration Foundation | ADR-00004 (event_type 22→31 exact set + payload schema、parent/child semantics) / ADR-00009 (action_class 不変、operation_kind/event_type/Tool Registry/policy_profile 分散明記、policy_profile schema + semantics) |
| ADR-00015 | UI ↔ CLI Parity Boundary | ADR-00007 (network boundary 拡張、CLI 認証 path 追加) |
| ADR-00016 | Hermes-Agent Integration Strategy | (新規 standalone) |
| ADR-00017 | AI Society Visualization (P2) | (新規 standalone) |
| ADR-00018 | Inter-Agent Communication Protocol | ADR-00004 (event_type 28/29 ref 追加) / audit_events payload schema 固定 (R2 PD-R2-F-011) |
| ADR-00019 | Role Taxonomy + Custom Role Extension | (新規 standalone、ADR-00009 と独立性明示) |
| ADR-00020 | Framework Intake Checklist | ADR-00010 (Provider intake checklist と並列) |
| **新 (Phase F 追加 R2 由来)**: Tool Registry network_access enum 化 ADR | network_access boolean → enum + 別 table tool_network_policies | DD-02 Tool Registry section update |
| **既存 ADR-00009 update (R2 PD-R2-F-005/014 fix)** | policy_profile schema + DD-02/03/04 ↔ ADR-00009 enum 同期 | DD-02/03/04 で `read/search` 除去 + `provider_call` 追加 |

---

## 8. Sprint Pack mapping (P0.1 / P1 / P2、S-30 / R2 PD-R2-F-013 fix で SP 個別小節)

各 SP に **target_days/max_days, must_ship, acceptance, verification_commands, rollback, audit_events, hard_gate_kpi_trace, adr_refs** を実カラム/箇条書きで埋める scaffold.

### SP-013: Multi-Agent Orchestration Foundation

- **target/max**: 5/7 days
- **C 対応**: C-1 (foundation)
- **must_ship**:
  - project_agent_roles table + agent_runs.role_id + role_scope + parent/child relationship + role taxonomy 5+ source 整合
  - constraint trigger (or link table) で project custom role の DB 防御 (S-20)
  - agent_runs に `unique (tenant_id, project_id, id)` 制約追加 + `orchestrator_lease_expires_at` 列追加 (S-26)
  - **backup_restore_multi_agent_drill** must_ship (S-12 / R2 PD-R2-F-013): restore 後 5 検証項目
- **acceptance**: 全 contract test pass、5+ source 整合 verify、cross-tenant + cross-project negative test pass、project custom role の DB level reject 確認
- **verification_commands**: `uv run pytest tests/multi_agent/test_role_taxonomy_enum.py tests/multi_agent/test_role_orthogonal_to_capability.py tests/multi_agent/test_project_custom_role_db_defense.py tests/db/test_schema_introspection.py tests/security/test_tenant_isolation_negative.py -q` + `uv run alembic check`
- **rollback**: §rollback (運用 + migration)
- **audit_events**: `agent_role_created` / `agent_role_deprecated` / `orchestrator_dispatched` (Sprint 14 で本格)
- **hard_gate_kpi_trace**: AC-HARD-04 (backup/restore drill list に新 table 追加)
- **adr_refs**: ADR-00014 (proposed → accepted gate at SP-013 kickoff) + ADR-00019 + 既存 ADR-00002 / 00004

### SP-014: Orchestrator Agent

- **target/max**: 4/6 days
- **C 対応**: C-3 (orchestrator)
- **must_ship**:
  - orchestrator actor type + lease/heartbeat/failover/kill-switch + max_* limits
  - remote_agent_gateway deny-only stub (S-18 / R2 PD-R2-F-010)
  - 3 階層 operation 分散 + policy_profile semantics ADR (S-15 / R2 PD-R2-F-005)
  - **secretbroker_multi_agent_negative test 6 cases** (S-7 / R1 PD-F-009 partial → R2 で SP-015 inter-agent + SP-016 CLI まで拡張)
  - KPI metric contract test (cost_per_task_rollup / approval_wait_dedupe / citation_final_only / time_to_merge_pr_only) (S-25)
  - Tool Registry network_access enum 化 ADR 起票 + tool_network_policies table + web_fetch/docs_search 登録 (S-28)
- **acceptance**: lease 60s renew + 失敗 failover、max_* 違反 reject、Tier 2 Policy Engine allow + agent decider 不可、remote_agent deny-only、6 SecretBroker negative 全件 deny
- **verification_commands**: `uv run pytest tests/multi_agent/test_orchestrator_lease_failover.py tests/multi_agent/test_max_limits.py tests/multi_agent/test_action_class_3tier.py tests/multi_agent/test_orchestrator_requester_only.py tests/security/test_secretbroker_multi_agent_negative.py tests/metrics/test_*_rollup*.py -q`
- **rollback**: kill-switch engage、lease 全 revoke、policy_profile を default に戻す
- **audit_events**: `orchestrator_dispatched`, `orchestrator_lease_renewed`, `orchestrator_lease_expired`, `orchestrator_failover_triggered`, `orchestrator_kill_engaged`, `secret_capability_redeemed_multi_agent_blocked`
- **hard_gate_kpi_trace**: AC-HARD-01 (policy_block_recall multi-agent), AC-KPI-05 (cost rollup), AC-KPI-03 (approval_wait_ms dedupe)
- **adr_refs**: ADR-00014 + ADR-00009 update (policy_profile) + Tool Registry network ADR + 既存 ADR-00006 / 00010

### SP-015: Inter-Agent Communication

- **target/max**: 3/5 days
- **C 対応**: C-2
- **must_ship**:
  - inter_agent_messages 12 fields + 全 FK は `(tenant_id, project_id, foreign_id)` 複合 FK (S-19)
  - atomic consume + replay/hijack defense + sanitizer pipeline + 3 trust_level + trusted_instruction CHECK (S-24)
  - 3 audit_events 必須 payload schema 固定 + raw payload 非保存 test (S-27)
  - AgentRunEvent ref event 28/29 追加 (event_type 31 exact set 内、S-22)
  - SecretBroker negative 6 cases のうち inter-agent message token payload を SP-015 で must_ship (R1 PD-F-009 + R2 拡張)
  - **backup_restore drill 拡張** (5 検証項目: parent/child AgentRun FK + inter_agent_messages seq/hash/consume state + agent_roles soft-deleted reference + memory_records source FK + audit_events correlation、R2 PD-R2-F-013)
- **acceptance**: 100 並行 atomic consume → 1 件のみ成功、replay/hijack 全件 deny、3 audit event payload schema 完全揃い、raw payload 非保存 assert pass
- **verification_commands**: `uv run pytest tests/inter_agent/* tests/audit/test_inter_agent_no_raw_payload.py tests/security/test_secretbroker_inter_agent_token.py tests/db/test_backup_restore_inter_agent.py -q`
- **rollback**: tenant_config で `inter_agent_enabled=false`、in-flight messages を強制 expire
- **audit_events**: `inter_agent_message_sent`, `inter_agent_message_consumed`, `inter_agent_message_denied`
- **hard_gate_kpi_trace**: AC-HARD-02 (secret canary in inter-agent), AC-HARD-04 (backup/restore inter_agent_messages)
- **adr_refs**: ADR-00018 + ADR-00014 + ADR-00004 update (event_type 31)

### SP-016: UI ↔ CLI Parity (CLI tool 実装)

- **target/max**: 4/6 days
- **C 対応**: C-4
- **must_ship**:
  - `tm` CLI 13 capability (memory 除外、PD-F-019)
  - REST API client + 短命 capability token (TTL 5-30 分) + refresh credential のみ profile 保存
  - multi-profile config + parity contract test
  - SecretBroker CLI token misuse negative test (R1 PD-F-009 + R2 拡張、SP-016 で must_ship)
- **acceptance**: 13 capability の UI 経路 vs CLI 経路で結果 + DB row + audit event 完全一致、CLI dev token leak / scope escape negative 全件 deny
- **verification_commands**: `uv run pytest tests/parity/test_ui_cli_parity.py tests/cli/* -q`
- **rollback**: profile config 削除、capability token 全 revoke、API path 503
- **audit_events**: 既存 + `cli_session_established` / `cli_capability_token_issued` / `cli_capability_token_expired`
- **hard_gate_kpi_trace**: AC-KPI-02 (time_to_merge from CLI 経路), AC-KPI-03 (approval_wait_ms)
- **adr_refs**: ADR-00015 + ADR-00007 update (network boundary)

### SP-017: AI Society Visualization (P1)

- **target/max**: 3/4 days
- **must_ship**: Web UI 拡張 (board / role visualization / progress dashboard) + role icon (default、character は P2)
- **acceptance/verification/rollback/audit/trace/adr_refs**: SP-017 詳細は P0.1 完了後に確定

### SP-018: Hermes Memory Integration

- **target/max**: 5/7 days
- **C 対応**: C-5 (memory backend)
- **must_ship**:
  - memory_records table + memory_retrieval_artifacts table + 全 FK 複合 (S-19)
  - hermes memory_manager 取り込み (Wave 19)
  - tsvector + GIN search (P1 初期、S-16)
  - sanitizer pipeline + redaction_status + sanitizer_version (S-17)
  - ContextSnapshot 10 列 invariant test
  - **backup_restore drill** 拡張
- **acceptance**: 12+ 列 enforcement、cross-project memory reject、tsvector + GIN search の tenant scope、ContextSnapshot 10 列完全一致 assert
- **verification_commands**: `uv run pytest tests/memory/* tests/context/test_contextsnapshot_unchanged.py tests/db/test_backup_restore_memory.py -q`
- **rollback**: tenant_config で `memory_enabled=false`
- **audit_events**: `memory_record_created` / `memory_retrieval_executed` / `memory_archive_engaged`
- **hard_gate_kpi_trace**: AC-KPI-04 (citation_coverage), AC-HARD-04
- **adr_refs**: ADR-00016 + ADR-00018 update (memory_retrieval) + 既存 ADR-00004

### SP-019: Project Scope Auto-Discovery (P1)

(既存通り)

### SP-020: Curator + Insights Integration

- **target/max**: 3/5 days
- **must_ship**: hermes curator + insights 取り込み (Wave 22) + 自動 archive + insight 抽出 + KPI metric contract test
- **acceptance/verification/rollback/audit/trace/adr_refs**: SP-018 完了後に確定

### SP-021: AI Character Generation (P2)

(既存通り、target 1/2 days)

### SP-022: Framework Intake / Multi-Agent Acceptance Hardening (R1 PD-F-012 / R2 PD-R2-F-013 fix で正式追加)

- **target/max**: 3/5 days
- **C 対応**: framework intake / Phase E adversarial closure
- **must_ship**:
  - ADR-00020 framework intake checklist accepted 化
  - Phase E adversarial review 結果反映 (TaskManagedAI でまだ未対応の 14 risks fix)
  - multi-agent contract test 強化 (Hard Gate / KPI 全件 multi-agent 文脈で再 verify)
  - SP-013-021 で defer された残リスクの整理
- **acceptance**: ADR-00020 accepted + Hard Gate 7 件全 PASS (multi-agent 文脈) + Phase E findings 全 closed
- **verification_commands**: `uv run pytest tests/multi_agent/* tests/eval/*` + Phase E adversarial review re-run
- **rollback**: SP-022 自体は読書 + ADR/test 整理が中心、destructive operation なし
- **audit_events**: framework_intake_accepted / adversarial_review_closed
- **hard_gate_kpi_trace**: 全 Hard Gate 7 件 (multi-agent 文脈)
- **adr_refs**: ADR-00020 + 全 ADR-00014〜19 (final review)

---

## 9. P0 → P0.1 移行 Gate (R2 強化)

### 9.1 Hard Gates / KPI / backup drill (R1 通り)

### 9.2 R2 で追加された Phase F 前提 task (R2 PD-R2-F-014 / S-29)

P0.1 着手前に **DD-02/03/04 ↔ ADR-00009 accepted enum 同期** が必須:

- DD-02 / DD-03 / DD-04 / server-owned-boundary / PRD references で `read/search` を action_class enum から **完全削除** (Tool Registry `allowed_actions` 側へ移動明記)
- 同 source で `provider_call` を action_class enum に追加 (ADR-00009 accepted 通り)
- 7 種 action_class enum: `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` で全 source 同期
- 5+ source 更新先: DD-02 line 469 (approval_requests CHECK constraint で確認、`read/search` を除去 + `provider_call` 追加) + DD-03 / DD-04 / server-owned-boundary §5 + ADR-00009 + tests/policy/test_action_class_enum.py の `EXPECTED_ACTION_CLASSES`

### 9.3 P0 sealed CI guard 解除手順 (R2 PD-R2-F-009 fix)

- ADR-00014 / 00015 / 00018 / 00019 が accepted (Phase F 完了)
- SP-013 kickoff migration `00NN_p0_1_multi_agent_foundation.py` 投入直前
- CI env で `TASKHUB_P0_1_OPENED=1` 設定
- `scripts/ci/check_p0_sealed_guard.sh` が pass → migration / implementation path 追加可

---

## 10. Open Questions (R2 fix 後の残)

- [x] OQ-6 FTS5 vs pgvector → tsvector + GIN 採用 (R1 PD-F-016 fix)
- [x] OQ-7 Tool Registry network_access enum 化 (R2 PD-R2-F-006 で ADR 起票決定)
- [x] OQ-8 P0/P0.1 remote_agent_gateway 整合 (R2 PD-R2-F-010 で確定)
- [ ] CLI tool 名 (`tm` 候補、Phase E 後 SP-016 で確定)
- [ ] role icon storage (P2)
- [ ] broadcast 宛先範囲
- [ ] max_depth=3 の妥当性
- [ ] inter_agent_messages TTL default
- [ ] SP-017 UI 仕様
- [ ] observer role read-only 完全性
- [ ] researcher web access 持続可能性
- [ ] independent reviewer rotation rule

---

## 11. Phase E (codex-adversarial-review) への引き継ぎ (R2 強化)

R2 で発覚した 14 件 + R1 partial 14 件すべて反映済み。Phase E では:

1. role hijack / broadcast hijack / orchestrator self-approval / infinite loop / memory poisoning / CLI token theft / multi-tenant cross-talk / observer write / character image injection / framework intake (R1 stress test 10 項目)
2. action_class 既存 7 種を新 operation_kind / event_type / policy_profile 経路で迂回できないか (R1 stress 11)
3. project_agent_roles の cross-project reference を constraint trigger だけで防げるか、bypass 可能経路があるか (R2 強化)
4. remote_agent_gateway P0/P0.1 境界の deny-only stub が orchestrator_dispatched event を受けて完全に deny を audit するか (R2 強化)
5. SecretBroker multi-agent negative 6 cases 完全 deny verify (R2 強化)
6. orchestrator_kpi_rollup の dedupe / attribution が parent/child で正しいか (R2 強化)
7. event_type 31 exact set の payload schema が AgentRunEvent と audit_events で重複なし (R2 強化)
8. **(新規 R2)** trusted_instruction CHECK の `action_class is not null` が PostgreSQL UNKNOWN truth-value で fail-open しないか
9. **(新規 R2)** review_artifacts.review_verdict が approval target.status と semantic 衝突しない経路で agent から approval bypass されないか
10. **(新規 R2)** Tool Registry network_access enum 化前 (P0 中) に web_fetch / docs_search が deny-only であることを CI / contract test で完全保証
11. **(新規 R2)** policy_profile=low_risk_auto_allow が ADR-00009 update accepted 後に approval bypass の経路にならないか (audit に policy_profile が記録される、unknown profile deny、profile ごとの action_class effect の境界)

---

## 11.3 Phase E Strengthening Catalog (defense-in-depth 候補、Phase F で各 ADR / SP / rules に反映)

Phase E (codex-adversarial-review) で 16 review item 全件で gap_found、HIGH 12 + MEDIUM 4 = 16 findings。CRITICAL 0、設計の根幹は健在、以下は **追加 strengthening 候補** として Phase F で各 ADR / SP / rules に反映する.

| # | id | RV | severity | strengthening (Phase F の adopt 先) |
|---|---|---|---|---|
| 1 | PE-F-001 | RV-001 | HIGH | **STANDARD_ROLE_IDS は custom role_id として禁止 (reserved namespace)**、または `custom:` prefix 等で namespace 分離。reviewer 判定は `role_scope=global + role_id=reviewer` で scope 含める。`receiver_kind=role` は server-owned role resolver で parent_run 配下 eligible child のみ展開、untrusted self-claim 無視 → ADR-00019 + ADR-00018 |
| 2 | PE-F-002 | RV-002 | HIGH | **atomic consume SQL を Phase C/ADR-00018 に明記**: WHERE は tenant_id, project_id, parent_run_id, id, consumed_at is null, expires_at > now, eligible receiver を必須化、receiver_kind ごとに direct child membership 検証、cross-parent same-project consume negative を must_ship → ADR-00018 + SP-015 |
| 3 | PE-F-003 | RV-003 | HIGH | **policy_decisions.required_review_artifact_id を review_artifacts へ FK**、review target hash + policy_version + provider_request_fingerprint + action_class を policy decision input と一致、reviewer_run_id は requester/orchestrator と異なる standard reviewer を service/Pydantic/contract test 4 重防御 → ADR-00009 update + ADR-00014 + SP-014 |
| 4 | PE-F-004 | RV-004 | HIGH | **orchestrator progress lease に last_progress_at + progress_seq**、N 分 no-progress で `blocked + runtime_blocked`、inter_agent_messages に parent_run turn counter + pairwise repeated payload hash detector、max_turns/TTL/depth は tenant_config + DB CHECK で絶対上限固定 → ADR-00014 + ADR-00018 |
| 5 | PE-F-005 | RV-005 | HIGH | **sanitizer_policy_versions table または config hash 正本化**、retrieval 時に current version 不一致は stale_sanitizer deny or re-sanitize、provider prompt の memory snippet は redaction_status=redacted 原則、raw_with_canary_scan_passed は明示例外に閉じる → ADR-00016 + SP-018 |
| 6 | PE-F-006 | RV-006 | HIGH | **CLI capability token を principal-bound API capability として DDL 化**: token_hash only, actor_id, principal_id/device_id, tenant_id/project_id, allowed_actions, audience=taskmanagedai-api, expires_at, jti, revoked_at。mutating API では policy decision / approval target fingerprint と照合、scope mismatch は deny audit → ADR-00015 + SP-016 |
| 7 | PE-F-007 | RV-007 | HIGH | **SP-013 migration order を hard gate**: artifacts.project_id NOT NULL + unique を inter_agent_messages/review_artifacts/memory_records FK 追加前に完了。global artifacts は別 table に分離、multi-agent path から参照不可 → SP-013 must_ship |
| 8 | PE-F-008 | RV-008 | MEDIUM | observer role の child run が write 要求した場合、role が authorization ではないため observer 固有の Tool Registry allowed_actions enforcement で deny → ADR-00019 + Tool Registry ADR |
| 9 | PE-F-009 | RV-009 | MEDIUM | P2 character image generation の prompt sanitizer (secret pattern / system instruction overwrite / internal context redact)、Provider Compliance Matrix で image generation provider を明示登録 → ADR-00017 |
| 10 | PE-F-010 | RV-010 | MEDIUM | Framework intake CI 機械検査: license string scan / external API endpoint denylist / 独自 SQLite import denylist / telemetry endpoint denylist を `scripts/ci/check_framework_intake.sh` で実装 → ADR-00020 |
| 11 | PE-F-011 | RV-011 | HIGH | **Phase F の最初に ADR-00014/00018/00019 を Phase C R4 方針へ patch**、action_class は ADR-00009 7 種以外を許さない strict CI、operation_kind/event_type/Tool Registry/policy_profile の各 enum と action_class enum の交差禁止 test → Phase F 着手 order |
| 12 | PE-F-012 | RV-012 | HIGH | **trigger 対象列を `before insert or update of tenant_id, project_id, role_id, role_scope`** に拡張、より堅い案: `agent_run_project_roles` link table に (tenant_id, project_id, role_id) FK、role_scope=global は STANDARD_ROLE_IDS mirror table または CHECK generated from migration seed で DB level → ADR-00014 + ADR-00019 |
| 13 | PE-F-013 | RV-013 | HIGH | **sealed guard に追加 path**: `backend/app/adapters/remote_agent/**` / `backend/app/api/remote_agent_router.py` / `frontend/app/remote-agent/**` / `config/remote_agent_compliance.toml` / `tests/**/remote_agent/**`。P0.1 stub は `remote_agent_dispatch_denied` audit payload schema 定義 → ADR-00013 update + ADR-00014 + §1.6 P0 sealed guard |
| 14 | PE-F-014 | RV-014 | MEDIUM | **SecretBroker multi-agent 6 negative case の reason_code 個別表**: parent_token_used_by_child / child_token_used_by_parent / inter_agent_message_token_payload / approval_id_substitution / payload_hash_substitution / run_id_substitution → SP-014 must_ship test fixture |
| 15 | PE-F-015 | RV-015 | HIGH | **Phase F で metrics ADR (or SP-014 appendix) に exact query**: agent_runs lineage は recursive CTE、cost は provider_responded event idempotency_key で dedupe、time_to_merge は PRD Ticket.created_at 起点と proxy 表示名を分ける、citation_coverage は adopted_artifacts link table を先に決める → SP-014 + Phase F metrics ADR |
| 16 | PE-F-016 | RV-016 | HIGH | **policy_profile migration に policy_decisions 追加列 + required_review_artifact_id FK + profile_resolved_effect CHECK**、seed は default/low_risk_auto_allow × 7 action_class = 14 rows exact、AC-HARD-01 multi-agent fixture で unknown profile / missing seed row / secret_access allow drift / provider_call without ZDR / task_write without review_artifact を捕捉 → ADR-00009 update + SP-014 |

## 11.4 Phase F 着手 order (Phase E PE-F-011 fix で確定)

Phase F は以下順序で実施 (drift 防止):

1. **Phase F-0 (前提 task)**: DD-02 policy 3 table の `read/search` 削除 + `provider_call` 追加同期 (R4 PD-R4-F-005 / S-29) → ADR-00009 update + migration
2. **Phase F-1**: ADR-00014/15/16/17/18/19/20 を Phase C R4 + Phase E catalog 反映で正式化 (proposed)。strict CI で action_class 7 種以外 reject (Phase E PE-F-011)
3. **Phase F-2**: SP-013/014/015/016/017/018/019/020/021/022 heavy Sprint Pack
4. **Phase F-3**: 既存 ADR-00004 (event_type 22→31) / ADR-00009 (policy_profile + DD-02/03/04 enum 同期) / ADR-00013 (orchestrator vs remote_agent) update
5. **Phase F-4**: PRD-00 (vision section) + PRD-01 (新 F-NNN: multi-agent / autonomous / parity / memory) update
6. **Phase F-5**: rules update + 新 `multi-agent-orchestration.md` (`.draft` 外し finalize)
7. **Phase F-6**: ハーネス v5 Wave 19-23 ロードマップ ✅ 完了

## 12. 改訂履歴

| 日付 | 内容 | 改訂者 |
|---|---|---|
| 2026-05-10 | Phase A + B 完了後 Claude orchestration で初版 draft 作成 | Claude main agent |
| 2026-05-10 | **Phase D R1 codex-plan-review 完了 (20 findings 全件 adopt)、全 DDL ID=uuid + Tier 2 human-only invariant 準拠 + action_class 5 種追加を 4 boundary 分散 + memory_retrieval_artifacts 別 table + tsvector+GIN + P0 sealed guard + SP-022 追加** | Claude main agent |
| 2026-05-10 | **Phase D R2 codex-plan-review 完了 (R1 14 件 partial + 14 new findings = 28 件全件 adopt)、project boundary 複合 FK 全新 table 適用 + role_scope DB 防御 (constraint trigger) + review_verdict pass/fail/needs_revision + event_type 31 exact set + payload schema + policy_profile semantics ADR 起票 + Tool Registry enum 化 ADR 起票 + trusted_instruction CHECK fail-open fix + orchestrator_kpi_rollup 本文化 + lease_expires_at 列追加 + audit_events payload schema 固定 + DD-02/03/04 ↔ ADR-00009 同期 task + Sprint Pack DoD scaffold + P0 sealed CI guard 擬似コード + remote_agent P0/P0.1 整合** | Claude main agent |
| 2026-05-10 | **Phase D R3 codex-plan-review 完了 (R2 14 partial 詳細化 + 7 new HIGH 5 + MEDIUM 2 = 計 21 件 adopt)、artifact project boundary strategy 案 A (§3.11) + approval_requests 列追加で trusted_instruction 4 整合 (§3.10) + policy_profile table + effect matrix + AC-HARD-01 fixture (§3.9) + KPI source 既存正本 fix (§3.8) + P0 sealed guard recursive glob + self-test (§1.6) + memory_records unique CREATE TABLE 内移動 (§5.2) + role_scope CHECK fail-closed (§1.4) + S-31〜S-37 7 件 safeguard 追加** | Claude main agent |
| 2026-05-10 | **Phase D R4 codex-plan-review 完了 (R3 4 fixed / 3 partial + 5 new HIGH 4 + MEDIUM 1 = 計 8 件 adopt、CRITICAL 0)、time_to_merge を repo_pr_opened のみ current source 化 (§3.8) + role_scope CHECK strict fail-closed (§1.4) + artifacts backfill migration 6 段階 + 案 A2 (§3.11) + P0 sealed guard bash 固定 (§1.6) + DD-02 policy 3 table の read/search → provider_call 同期 task 明記 (§3.9)** | Claude main agent |
| 2026-05-10 | **Phase E codex-adversarial-review (defensive review) 完了 (16 review item 全 gap_found、HIGH 12 + MEDIUM 4、CRITICAL 0)、§11.3 Strengthening Catalog として 16 件全件 adopt、§11.4 で Phase F 着手 order (PE-F-011 fix) 確定。累計 56 finding 全件 adopt (Phase D 40 + Phase E 16)** | Claude main agent |

---

**End of Phase C draft (Phase D R2 rewrite-v2 完了)**

次: Phase D R3 (verify clean) → Phase E (codex-adversarial-review) → Phase F
