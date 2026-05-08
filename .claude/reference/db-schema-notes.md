# DB Schema Notes

PostgreSQL schema の TaskManagedAI 不変条件早見表。  
tenant / project boundary、actors / principals、AgentRun、ContextSnapshot 10 カラム、SecretBroker、Provider Matrix invariant を扱う。

## 1. データモデル原則

| 原則 | 内容 |
|---|---|
| tenant invariant | 全主要 table に `tenant_id bigint NOT NULL DEFAULT 1` |
| 複合 FK | 親子参照は `tenant_id` を含める |
| project invariant | 同一 tenant 内でも project boundary を越えない |
| actor / principal 分離 | 操作主体と credential を分ける |
| secret_ref 抽象化 | raw secret ではなく URI metadata |
| append-only event | AgentRunEvent / AuditEvent / PolicyDecision |
| RLS-ready | P0 は RLS off でも将来 ready |

## 2. Core Contexts

| context | tables |
|---|---|
| Tenant / Actor | `tenants`, `users`, `actors`, `principals` |
| Workspace / Project | `workspaces`, `projects`, `repositories` |
| Ticket | `tickets`, `ticket_relations`, `acceptance_criteria` |
| Research / Evidence | `research_tasks`, `evidence_sources`, `claims`, `claim_evidence` |
| Agent Runtime | `agent_runs`, `agent_run_events`, `artifacts` |
| Context | `context_snapshots` |
| Policy / Approval | `policy_decisions`, `approval_requests`, `approval_events` |
| Eval / Audit | `dataset_versions`, `eval_runs`, `eval_cases`, `eval_scores`, `audit_events` |
| Secrets | `secret_refs`, `secret_capability_tokens` |
| Budget | `budgets` |

## 3. Tenant Boundary

必須:

- `tenant_id bigint not null default 1`
- `unique (tenant_id, id)`
- FK は `(tenant_id, parent_id)`。
- app repository は WHERE `tenant_id = current_tenant_id`。
- UPDATE / DELETE は target row count で contract test。

禁止:

- parent id だけの FK。
- global slug unique。
- tenant context なし SELECT。
- tenant context 外 UPDATE。
- tenant context 外 DELETE。

## 4. Project Boundary

同一 tenant 内でも project を越えない。

必要な複合 unique:

```sql
unique (tenant_id, project_id, id)
```

対象:

- `repositories`
- `tickets`
- `research_tasks`
- `agent_runs`

代表 FK:

```sql
foreign key (tenant_id, project_id, ticket_id)
references tickets(tenant_id, project_id, id)
```

negative test:

- 別 project の ticket を research_task に紐付ける INSERT が失敗。
- 別 project の `agent_runs.parent_run_id` を参照する UPDATE が失敗。
- `ticket_relations` で別 project の ticket を結ぶ INSERT が失敗。

## 5. Actors / Principals

`actors.actor_type`:

- `human`
- `service`
- `agent`
- `provider`
- `github_app`

`principals.principal_type`:

- `session`
- `api_token`
- `capability_token`
- `installation`
- `worker`

ルール:

- actor は監査主体。
- principal は認証・credential。
- self-approval 禁止。
- GitHub App 操作は `github_app` actor。
- worker 操作は service / worker principal。
- impersonation は `impersonated_by` を残す。

## 6. AgentRun

Status enum 16:

- `queued`
- `gathering_context`
- `running`
- `generated_artifact`
- `schema_validated`
- `policy_linted`
- `diff_ready`
- `waiting_approval`
- `blocked`
- `provider_refused`
- `provider_incomplete`
- `validation_failed`
- `repair_exhausted`
- `completed`
- `failed`
- `cancelled`

`blocked_reason`:

- `policy_blocked`
- `budget_blocked`
- `runtime_blocked`

DB check:

```sql
(status = 'blocked' and blocked_reason is not null)
or (status <> 'blocked' and blocked_reason is null)
```

terminal state:

- `completed`
- `failed`
- `cancelled`
- `provider_refused`
- `repair_exhausted`

## 7. AgentRunEvent

必須:

- `tenant_id`
- `run_id`
- `seq_no`
- `event_type`
- `actor_id`
- `payload`
- `created_at`

unique:

- `(tenant_id, run_id, seq_no)`
- `(tenant_id, run_id, idempotency_key)`

ルール:

- append-only。
- status update と同一 transaction。
- raw secret を payload に入れない。
- provider result、policy decision、approval、runner event を追えるようにする。

## 8. ContextSnapshot 必須 10 カラム

1. `prompt_pack_version`
2. `prompt_pack_lock`
3. `policy_version`
4. `policy_pack_lock`
5. `repo_state`
6. `tool_manifest`
7. `evidence_set_hash`
8. `provider_continuation_ref`
9. `provider_request_fingerprint`
10. `snapshot_kind`

`snapshot_kind`:

- `input`
- `pre_tool`
- `post_tool`
- `resume`
- `final`

禁止:

- raw secret。
- provider key。
- capability token 生値。
- unredacted provider response。
- actor boundary を無視した state。

## 9. Secret Refs

`secret_refs` 主要 column:

- `secret_uri`
- `scope`
- `name`
- `version`
- `status`
- `runner_injectable=false`
- `allowed_consumers`
- `allowed_operations`
- `owner_actor_id`
- `rotated_from_id`

`status`:

- `pending`
- `active`
- `deprecated`
- `revoked`

unique:

- `(tenant_id, secret_uri)`
- `(tenant_id, scope, name, version)`
- active per `(tenant_id, scope, name)` は最大 1。
- pending per `(tenant_id, scope, name)` は最大 1。

## 10. Capability Tokens

`secret_capability_tokens` 主要 column:

- `secret_ref_id`
- `token_hash`
- `allowed_operations`
- `scope_constraint`
- `issued_to_actor_id`
- `issued_run_id`
- `expires_at`
- `used_at`
- `request_fingerprint`
- `status`

`status`:

- `issued`
- `redeeming`
- `used`
- `expired`
- `revoked`

ルール:

- raw token 保存禁止。
- TTL 5-30 分。
- one-time redeem。
- atomic claim UPDATE。
- actor / run / request_fingerprint / operation binding。
- 0 rows RETURNING は deny。

## 11. Provider Matrix Invariant

DB table ではなく config / policy contract だが、audit と AgentRun に反映する。

必須:

- `payload_data_class`
- `allowed_data_class`
- `provider_compliance_matrix_version`
- `policy_version`
- `provider_request_fingerprint`

data class ordinal:

```text
public < internal < confidential < pii
```

ルール:

- `allowed_data_class` は caller 入力ではない。
- Matrix からのみ解決。
- `payload_data_class` 未設定 deny。
- `payload_data_class > allowed_data_class` deny。
- conditional ZDR は `condition_status=verified`。

## 12. Budget

`budgets.scope_type`:

- `user`
- `workspace`
- `project`
- `ticket`
- `agent_run`
- `provider`

ルール:

- scope ごとに対象 FK は 1 つだけ。
- over budget は `blocked` + `budget_blocked`。
- provider failure と混同しない。
- `cost_per_completed_task` の source になる。

## 13. Audit Events

必須:

- `tenant_id`
- `actor_id`
- `event_type`
- `resource_type`
- `resource_id`
- `run_id`
- `trace_id`
- `correlation_id`
- `payload`
- `created_at`

禁止:

- raw secret。
- capability token 生値。
- provider key。
- canary raw value。

推奨 index:

- `(tenant_id, trace_id)`
- `(tenant_id, correlation_id)`
- `(tenant_id, event_type, created_at desc)`

## 14. Migration Review Checklist

- [ ] 全主要 table に `tenant_id` がある。
- [ ] parent FK は `tenant_id` を含む。
- [ ] project boundary を複合 FK で閉じている。
- [ ] AgentRun status enum は 16 状態。
- [ ] `blocked_reason` consistency check がある。
- [ ] ContextSnapshot 10 カラムがある。
- [ ] `secret_refs` に raw secret column がない。
- [ ] `runner_injectable=false` が強制される。
- [ ] capability token は hash 保存のみ。
- [ ] atomic claim に必要な column がある。
- [ ] audit payload に raw secret がない。
- [ ] Alembic check と DB negative test がある。

