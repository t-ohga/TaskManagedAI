---
id: "ADR-00018"
title: "Inter-Agent Communication Protocol: inter_agent_messages 12 fields + project boundary 複合 FK + atomic consume + replay/hijack defense + 3 trust_level + sanitizer pipeline + audit_events 必須 payload"
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-015_inter_agent_communication"
related_research:
  - "docs/設計検討/phase-c-multi-agent-spec-draft.md §C-2 + §11.3 PE-F-002 strengthening"
supersedes: null
superseded_by: null
acceptance_blocked_by:
  - "ADR-00014 accepted"
  - "P0 (Sprint 1-12) 完了"
  - "Phase F-0 (artifacts.project_id materialize migration) 完了"
---

最終更新: 2026-05-10 (proposed 起票、Phase D R4 + Phase E PE-F-002 反映)

## 背景

- 決定対象: 専門 agent 同士が「レビュー / 話し合う」場を実装するため、inter-agent communication protocol を固定。本 ADR は (1) 通信 entity 選択 (3 案比較)、(2) `inter_agent_messages` 12 fields schema + project boundary 複合 FK、(3) atomic consume SQL + replay/hijack defense、(4) 3 trust_level + sanitizer pipeline、(5) audit_events 3 種必須 payload schema、(6) AgentRunEvent ref 連動 (raw payload なし) を担保.
- 関連 Sprint: SP-015。前提: SP-013 (parent_run_id 関係) + SP-014 (orchestrator).
- 前提 / 制約: 既存 invariant (AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance / SecretBroker / Approval 4 整合 + decider human-only / 3 gateway / id=uuid + tenant_id=bigint / 複合 FK pattern) すべて不変.
- ADR Gate Criteria #2 (DB schema) + #3 (event schema) 該当.

## 選択肢

| # | 案 | 採否 | 根拠 |
|---|---|---|---|
| 1 | AgentRunEvent 拡張のみ (`inter_run_messages` event_type 追加) | reject | run 内 event の正本 (rules/agentrun-state-machine §5) を流用すると seq_no/unique 衝突、replay 設計が破綻 |
| **2 (採用)** | **inter_agent_messages (本体) + audit_events (cross-run) + AgentRunEvent ref (各 run timeline)** | adopt | tenant/project boundary 強制、12 fields schema 適用、replay protection、layer 責務分離 |
| 3 | hermes plugins/kanban full embed | reject | Phase B-1 で `skip` 判定、R-008/R-014 該当、persistence 二重化 |

## 採用案

### §1: inter_agent_messages 12 fields schema (PD-F-002 / PD-R2-F-001 / PD-R2-F-007 / PD-R3-F-002 fix)

```sql
create table inter_agent_messages (
    id uuid primary key default gen_random_uuid(),
    tenant_id bigint not null default 1 references tenants(id),
    project_id uuid not null,
    parent_run_id uuid not null,
    child_run_id uuid,
    sender_actor_id uuid not null,
    sender_run_id uuid not null,
    receiver_kind text not null check (receiver_kind in ('agent_run', 'role', 'broadcast')),
    receiver_ref text,
    data_class text not null check (data_class in ('public','internal','confidential','pii')),
    trust_level text not null default 'untrusted_content'
        check (trust_level in ('untrusted_content','validated_artifact','trusted_instruction')),
    -- trusted_instruction の server-owned refs (PD-F-020 / PD-R2-F-007 / PD-R3-F-002 fix):
    approval_request_id uuid,
    source_artifact_id uuid,
    artifact_hash text,
    policy_version text,
    provider_request_fingerprint text,
    action_class text,
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
    -- PD-R2-F-001 project boundary 複合 FK:
    foreign key (tenant_id, project_id) references projects(tenant_id, id),
    foreign key (tenant_id, project_id, parent_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, child_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, sender_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, project_id, consumed_by_run_id) references agent_runs(tenant_id, project_id, id),
    foreign key (tenant_id, sender_actor_id) references actors(tenant_id, id),
    foreign key (tenant_id, approval_request_id) references approval_requests(tenant_id, id),
    foreign key (tenant_id, source_artifact_id) references artifacts(tenant_id, id),
    -- Phase H PH-F-008 fix: SP-013 の artifacts.project_id materialize hard gate (ADR-00021 §11.5 + §3.11) 完了後に
    -- 上記 FK を `(tenant_id, project_id, source_artifact_id) references artifacts(tenant_id, project_id, id)` に変更
    -- それまで (P0.1 SP-013 着手前) は service layer guard で cross-project artifact reference を reject、
    -- DB CHECK / FK で完全防御は SP-013 hard gate 完了後に確立
    unique (tenant_id, parent_run_id, seq_no),
    unique (tenant_id, parent_run_id, idempotency_key),
    check (sender_run_id <> consumed_by_run_id or consumed_by_run_id is null),
    -- PD-R2-F-007 fail-open fix: action_class is not null + enum 部分集合
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

### §2: 3 trust_level (R-006 / S-3 / PD-F-020 fix)

| trust_level | 受信側 prompt template | server-owned refs |
|---|---|---|
| `untrusted_content` (default) | UNTRUSTED INPUT で囲む、content として扱う、instruction として実行しない | 不要 |
| `validated_artifact` | typed object として渡す、natural-language として展開しない | artifact_ref から payload_hash 検証 |
| `trusted_instruction` | approval ID 添付、message self-claim 無視、server-owned refs を信頼源 | 必須 (approval_request_id 等 6 fields + action_class enum 部分集合) |

### §3: atomic consume SQL (PE-F-002 strengthening、Phase C/ADR-00018 に明記)

```sql
update inter_agent_messages
   set consumed_at = now(),
       consumed_by_run_id = :child_run_id
 where tenant_id = :tenant_id
   and project_id = :project_id                           -- PE-F-002: project scope 必須
   and parent_run_id = :parent_run_id                     -- PE-F-002: parent_run scope 必須
   and id = :message_id
   and consumed_at is null
   and expires_at > now()
   -- receiver eligibility (receiver_kind ごとに):
   and (
       (receiver_kind = 'agent_run' and child_run_id = :child_run_id)
       or (receiver_kind = 'role'
           and exists (
               select 1 from agent_runs r
                where r.tenant_id = inter_agent_messages.tenant_id
                  and r.id = :child_run_id
                  and r.parent_run_id = inter_agent_messages.parent_run_id
                  and r.role_id = inter_agent_messages.receiver_ref))
       or (receiver_kind = 'broadcast'
           and exists (
               select 1 from agent_runs r
                where r.tenant_id = inter_agent_messages.tenant_id
                  and r.id = :child_run_id
                  and r.parent_run_id = inter_agent_messages.parent_run_id))
   )
returning artifact_ref, payload_hash, schema_version, trust_level, seq_no, previous_hash;
```

0 rows RETURNING は deny。**Replay 防御**: seq_no monotonic + previous_hash chain + idempotency_key + expires_at。**Hijack 防御**: project/parent boundary FK + receiver eligibility + sender_run の child set 検証。

### §4: sanitizer pipeline (S-3 / S-9 / PE-F-005)

inter-agent message を child run が受信時に通す:

1. schema validation (Pydantic / Zod 通過、artifact が宣言済 type を満たすか)
2. payload_data_class 算出 (artifact metadata から事前算出、caller-supplied 禁止)
3. **sanitizer_version 整合 verification (PE-F-005)**: current `sanitizer_policy_versions` 不一致は stale_sanitizer deny or re-sanitize
4. secret canary scan (provider-compliance §8 と同等)
5. trust_level に応じた prompt template 適用 (§2)
6. ContextSnapshot.snapshot_kind=pre_tool に追記 (raw payload なし、message_id + payload_hash + schema_version のみ)

### §5: audit_events 3 種必須 payload schema (S-27 / PD-R2-F-011 fix)

| event_type | 必須 payload (NULL 不可) | 禁止 payload |
|---|---|---|
| `inter_agent_message_sent` | tenant_id, project_id, parent_run_id, sender_run_id, sender_actor_id, receiver_kind, receiver_ref, seq_no, payload_hash, data_class, trust_level, schema_version, redaction_status | message body / artifact 本体 / secret / capability token |
| `inter_agent_message_consumed` | tenant_id, project_id, parent_run_id, consumed_by_run_id, message_id (hash), seq_no, previous_hash_match, payload_hash, redaction_status | 同上 |
| `inter_agent_message_denied` | tenant_id, project_id, parent_run_id, attempted_message_id (hash), seq_no, denial_reason (`already_consumed/expired/cross_parent/cross_tenant/cross_project/previous_hash_mismatch/replay_detected/untrusted_promotion_attempt/approval_target_mismatch/receiver_ineligible`), redaction_status | 同上 |

`tests/audit/test_inter_agent_no_raw_payload.py` で `assert_no_raw_secret_and_no_raw_message_body(audit_event)` を SP-015 must_ship.

### §6: AgentRunEvent ref 連動 (S-22 / PD-R2-F-004 / PE-F-018)

各 run の timeline に `inter_agent_message_sent_ref` / `inter_agent_message_consumed_ref` の AgentRunEvent を append (raw payload なし、`message_id + payload_hash + seq_no + sender_run_id + receiver_run_id + redaction_status` のみ)。これは ADR-00004 update で event_type 22→31 拡張に含まれる.

### §7: 実装 Sprint と対象ファイル

- SP-015 (target 3/max 5 days)
- 実装対象: `backend/app/db/models/inter_agent_message.py` / `migrations/versions/0015_p0_1_inter_agent_messages.py` / `backend/app/services/inter_agent/{publisher,consumer,sanitizer,replay_guard,hijack_guard}.py` / `tests/inter_agent/*` / `tests/audit/test_inter_agent_no_raw_payload.py` / `eval/multi_agent/inter_agent_replay_attack/manifest.json` / `eval/multi_agent/inter_agent_hijack_attack/manifest.json`

### §8: テスト指針

- `test_12_fields_schema.py` (12 fields 強制 + R3 trust_level CHECK)
- `test_atomic_consume.py` (100 並行 → 1 件のみ成功)
- `test_replay_protection.py` (seq_no/previous_hash/idempotency/expires)
- `test_hijack_protection.py` (cross-parent/tenant/project/sender 偽装、receiver_kind ごと)
- `test_3_trust_level.py` (default/validated/trusted_instruction、approval target 4 整合 negative 6 case)
- `test_sanitizer_pipeline.py` (stale_sanitizer deny / secret canary)
- `test_audit_events.py` (3 event_type 必須 payload + raw 値なし)
- `eval/multi_agent/inter_agent_*` (AC-HARD 候補)

## 却下案

(§選択肢 1, 3 参照)

## リスク

| リスク | 検知 | 軽減 |
|---|---|---|
| 12 fields drift | 5+ source 整合 test + migration check | fields 追加は ADR 経由必須 |
| atomic consume race | `test_atomic_consume.py` 並行 | DB transaction + atomic UPDATE |
| replay/hijack | `test_replay_protection.py` + eval | seq_no monotonic + previous_hash + idempotency + expires + boundary FK + receiver eligibility |
| trust_level 自動昇格 | `test_3_trust_level.py` negative | DB CHECK + service guard + Pydantic + test 4 重防御 |
| audit raw 値混入 | `test_audit_events.py` | payload schema enforcement + assert_no_raw_secret_and_no_raw_message_body |

## rollback 手順

1. publish/consume 停止: tenant_config で `inter_agent_enabled=false`
2. in-flight messages を強制 expire (`update inter_agent_messages set expires_at = now()`)
3. 3 audit event verify (deny full 発火、raw 値なし)
4. single-agent run は無影響
5. migration rollback: `alembic downgrade -1` + 検証 SQL

## 関連

- ADR-00014 (Multi-Agent Orchestration Foundation)
- ADR-00004 update (event_type 22→31)
- ADR-00009 update (action_class 部分集合 enforcement)
- Phase C draft §C-2 + §11.3 PE-F-002 strengthening
