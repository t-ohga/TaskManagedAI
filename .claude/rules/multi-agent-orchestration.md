# Multi-Agent Orchestration Rules (Phase F draft、proposed)

> 本ファイルは Phase F で正式化される draft。Phase D R2 + Phase E 完了後に `.draft` 拡張子を外して `multi-agent-orchestration.md` として `accepted` 化。

multi-agent orchestration、role taxonomy、inter-agent communication、orchestrator 自律性の常時ルール。
既存 invariant (AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance 13 reason_code / SecretBroker atomic claim / Approval 4 整合 + decider human-only / 既存 action_class 7 種 / 3 gateway 分離 / 全 id=uuid + tenant_id=bigint) は不変。

## 1. 原則

- **AI 集合体 = 一つの会社** メタファー、orchestrator + 専門 agent 群 + 完全自律運営。
- **role ⊥ capability authorization**: role は metadata、capability は capability token + action_class で別軸 (R-009)。
- **orchestrator は requester only、decider 不可** (R-002)。
- **agent 間 secret pass-through 禁止** (R-005)。各 child run が独立に SecretBroker から token 取得。
- **inter-agent message は untrusted_content 扱い** (R-006)。trusted_instruction 昇格は human approval + server-owned refs 必須。
- **既存 action_class 7 種は不変**、新 operation は agent_run_event_type / Tool Registry allowed_actions / policy_profile に分散。
- **既存 16 状態は不変**、orchestrator lease/failover も既存 blocked_reason 3 種 (`policy_blocked` / `budget_blocked` / `runtime_blocked`) で表現。
- **framework full embed 禁止**、pattern adoption only (ADR-00016 / ADR-00020 の framework intake checklist 通過)。

## 2. 標準役職 10 種 (code enum、5+ source 整合)

`backend/app/domain/agent_role/taxonomy.py` の `STANDARD_ROLE_IDS: frozenset[str]` で固定:

```python
STANDARD_ROLE_IDS: Final[frozenset[str]] = frozenset({
    "orchestrator", "implementer", "reviewer", "tester", "security_agent",
    "researcher", "observer", "curator", "dispatcher", "repair_specialist",
})
```

5+ source: Python Literal + Pydantic Field validator + pytest EXPECTED constant + frontend TypeScript enum + (DB CHECK は不要、role_id は text 列)。

## 3. custom role = project-scoped

`project_agent_roles` table:
- (tenant_id, project_id, role_id) unique
- (tenant_id, project_id) references projects(tenant_id, id)
- soft-delete のみ (`deprecated_at`)、HARD DELETE は ADR Gate Criteria #8 (破壊的操作)
- `recommended_action_class` 列は **存在しない** (R-009 / S-2 mitigation)

## 4. 3 階層 operation 分散 (action_class 5 種追加禁止)

| 階層 | 旧 (rejected、AP-8) | 新 (採用、既存 invariant 不変) |
|---|---|---|
| Tier 1 | `orchestrator_dispatch` (action_class) | `agent_run_event_type='orchestrator_dispatched'` (既存 22 → 31 event_type) |
| Tier 1 | `inter_agent_message` (action_class) | `agent_run_event_type='inter_agent_message_sent_ref/consumed_ref'` + audit_events 独立 |
| Tier 2 | `auto_approve_low_risk` (action_class) | `policy_profile='low_risk_auto_allow'` (Policy Engine effect=allow、approval_requests 作らない) |
| Tier 1 | `read_only_research` (action_class) | Tool Registry `allowed_actions=['web_fetch','docs_search']` |
| Tier 1 | `read_only_audit` (action_class) | Tool Registry `allowed_actions=['trace_read','metric_read']` |

既存 7 種 (`task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call`) 不変.

## 5. orchestrator 制約

- `actors.actor_type` enum に追加なし、orchestrator は `actor_type='agent'` + `agent_runs.role_id='orchestrator'` で識別.
- orchestrator は **approval decider にならない** (DB CHECK + service guard + Pydantic validator + test 4 重防御).
- lease (UUID + expires_at) + heartbeat (60s) + failover (next-in-queue) + kill-switch (orchestrator_kill_at).
- max_children=8 (≤20) / max_depth=3 (≤5) / max_turns=100 (≤500) / budget=$5/90min (≤$50). 絶対上限は DB CHECK.
- child status は既存 16 状態のみ使用、`cancel_requested -> cancelled` または `blocked + runtime_blocked` で kill 表現.
- terminal child は変更不可.

## 6. inter_agent_messages 12 fields + atomic consume

- 全 ID = uuid (project_id / parent_run_id / child_run_id / sender_actor_id / sender_run_id / consumed_by_run_id / approval_request_id / source_artifact_id).
- `(tenant_id, parent_run_id, seq_no)` unique + `(tenant_id, parent_run_id, idempotency_key)` unique.
- atomic consume SQL (UPDATE + WHERE + RETURNING、SecretBroker と同等 pattern).
- replay 防御: monotonic seq_no + previous_hash chain + idempotency_key + expires_at (default 24h、tenant_config で 1h-72h、絶対上限 72h).
- hijack 防御: parent_run / tenant / project boundary FK + sender_run の child set 検証.
- 3 trust_level: `untrusted_content` (default) / `validated_artifact` (schema 通過) / `trusted_instruction` (human approval 必須 + server-owned refs 6 件).
- 3 audit_events: `inter_agent_message_sent` / `consumed` / `denied` (audit_events table).
- 各 run timeline: AgentRunEvent に `inter_agent_message_sent_ref` / `consumed_ref` (raw payload なし、message_id + payload_hash + seq_no + sender_run_id + receiver_run_id + redaction_status のみ).

## 7. memory layer (Sprint 18 / Wave 19-22 以降)

- ContextSnapshot 10 列は不変 (R-013).
- memory retrieval = `memory_retrieval_artifacts` 別 table、AgentRun column に直接埋め込まない.
- ContextSnapshot.tool_manifest または evidence_set_hash 経由で参照.
- 全 memory-derived prompt input は `untrusted_content` (DB CHECK で trust_level enforce).
- P1 初期は PostgreSQL `tsvector + GIN` を search 正本、pgvector / FTS5 は ADR update 経由のみ.

## 8. P0 sealed CI guard

P0 (Sprint 1-12) 期間中、CI が `rg` denylist で以下 path 追加を fail:
- `backend/app/db/models/project_agent_role.py`
- `backend/app/db/models/inter_agent_message.py`
- `backend/app/db/models/memory_record.py`
- `backend/app/db/models/memory_retrieval_artifact.py`
- `backend/app/db/models/review_artifact.py`
- `backend/app/services/orchestrator/`
- `backend/app/services/inter_agent/`
- `backend/app/services/memory/`
- `frontend/app/(admin)/agent-roles/`
- `frontend/app/(admin)/orchestrator/`
- `migrations/versions/*multi_agent*`
- `migrations/versions/*orchestrator*`
- `migrations/versions/*memory*`

例外: `docs/adr/00014_*.md` 〜 `00020_*.md` / `docs/設計検討/phase-c-*.md` / `docs/sprints/SP-013_*.md` 〜 `SP-022_*.md` (draft).

P0.1 着手時 (Sprint 13 開始) に CI guard を解除 (config flag).

## 9. SecretBroker multi-agent negative 6 cases

`tests/security/test_secretbroker_multi_agent_negative.py` で:

1. concurrent redeem (parent と child が同 token を同時 redeem → 1 件のみ成功)
2. parent token used by child (parent run 用 token を child run が使用 → run_id mismatch deny)
3. child token used by parent (逆方向 → 同上)
4. inter_agent_message token payload (message に raw token を含めようとする経路 → schema validation reject)
5. approval_id substitution (別 approval の token で別 operation を redeem → fingerprint mismatch deny)
6. payload_hash substitution (approved diff と異なる diff を push → payload_hash mismatch deny)

## 10. orchestrator_kpi_rollup

- `cost_per_completed_task` = parent + 全 children の token cost / wall-clock を sum、parent ticket 単位
- `approval_wait_ms` = approval_request 単位で 1 度のみ (parent / child の重複計測なし)
- `citation_coverage` = final adopted artifact のみ対象
- `time_to_merge` = PR flow source のみ (RepoProxy 経由)
- `acceptance_pass_rate` = 既存仕様

SP-014/017/020 に metric contract test を入れる.

## 11. framework intake checklist (ADR-00020 連動)

新 framework / library 取り込み時に必須 verify:
1. License (Polyform Shield 等の embed 禁止 license 検出)
2. Attribution (citation 義務化)
3. No code embed (from-scratch 再実装、CI で `import <framework>` denylist)
4. Persistence 二重化なし (PostgreSQL 一本化)
5. External network deny (Tailscale-only enforcement)
6. Telemetry off (TaskManagedAI audit_events に統合)
7. Secret canary scan (memory store / retrieve)
8. tenant/project boundary (DB FK + service layer 4 重防御)

## 12. Review Checklist

- [ ] 全 ID = uuid、tenant_id = bigint NOT NULL DEFAULT 1.
- [ ] 複合 FK pattern `(tenant_id, foreign_id) references <table>(tenant_id, id)`.
- [ ] role が capability を授与する経路がない (recommended_action_class 列なし).
- [ ] orchestrator が approval decider にならない (4 重防御).
- [ ] action_class 既存 7 種に新規追加していない (Tier 1/2/3 は別 boundary に分散).
- [ ] AgentRun 16 状態 / ContextSnapshot 10 列を破壊していない.
- [ ] inter_agent_messages 12 fields + 3 trust_level + atomic consume.
- [ ] memory_retrieval_artifacts 別 table、ContextSnapshot に直接埋め込まない.
- [ ] P0 sealed CI guard が有効.
- [ ] framework full embed なし、pattern adoption only.
