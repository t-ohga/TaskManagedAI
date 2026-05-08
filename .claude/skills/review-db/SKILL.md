---
name: review-db
description: "TaskManagedAI の PostgreSQL migration/model/repository 境界をレビューする。Triggers: review db, tenant_id, migration"
when_to_use: |
  PR diff、migration、SQLAlchemy model、repository 層、DB contract test を PostgreSQL boundary と AC-HARD-03 観点でレビューする時。
  postgres-boundary-audit より PR 指摘形式を優先する。別 Skill / Agent は起動しない。
  トリガーフレーズ: 'review db', 'DB レビュー', 'migration レビュー', 'tenant_id 確認'
argument-hint: "[--scope=current-branch|staged|specified-files] [--files=<comma-separated>] [--depth=fast|deep]"
allowed-tools: Read Bash Grep
---

# review-db — PostgreSQL boundary / migration review

## 目的

TaskManagedAI の `migrations/`, `backend/app/repositories/`, `backend/app/models/` を対象に、PostgreSQL tenant / project boundary、AgentRun、ContextSnapshot、SecretBroker DDL の不変条件を file:line 付きでレビューする。

この skill はレビュー専用であり、migration や model の修正は行わない。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/core.md` §8-§10
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/agentrun-state-machine.md`
- `.claude/reference/db-schema-notes.md`
- `.claude/agents/taskmanagedai/postgres-specialist.md`
- `.claude/agents/taskmanagedai/tenant-project-isolation-reviewer.md`

## 対象

- `migrations/**/*`
- `backend/app/repositories/**/*.py`
- `backend/app/models/**/*.py`
- `backend/app/**/models*.py`
- `backend/app/**/schemas*.py`
- DB contract tests
- AgentRun / ContextSnapshot / SecretBroker / Audit / Eval 関連 DDL

## 検査手順

1. DB 変更範囲を確定する。

```bash
git diff --name-only
git diff --cached --name-only
rg --files migrations backend/app tests eval 2>/dev/null | rg '(migration|models?|repositories|schema|db|postgres|tenant|agent_run|context_snapshot|secret)'
```

2. 主要 table の `tenant_id` と複合 FK を確認する。

```bash
rg -n "tenant_id|project_id|foreign key|ForeignKeyConstraint|UniqueConstraint|unique \\(|primary key|references " migrations backend/app 2>/dev/null
```

BLOCK:

- 主要 table に `tenant_id bigint NOT NULL DEFAULT 1` がない
- `tenant_id` が nullable
- parent id 単体 FK
- `unique (tenant_id, id)` がないため複合 FK の参照先にできない
- global slug / external key unique
- repository SELECT / UPDATE / DELETE に tenant context がない

主要 table:

```text
tenants, users, actors, principals, workspaces, projects, repositories,
tickets, ticket_relations, acceptance_criteria, research_tasks,
evidence_sources, claims, claim_evidence, agent_runs, agent_run_events,
artifacts, context_snapshots, policy_decisions, approval_requests,
approval_events, dataset_versions, eval_runs, eval_cases, eval_scores,
audit_events, secret_refs, secret_capability_tokens, budgets
```

3. project boundary を確認する。

```bash
rg -n "repositories|tickets|research_tasks|agent_runs|ticket_relations|parent_run_id|repository_id|ticket_id|research_task_id|project_id" migrations backend/app 2>/dev/null
```

必須:

- `repositories`, `tickets`, `research_tasks`, `agent_runs` は `unique (tenant_id, project_id, id)`
- `tickets.repository_id` は同一 project の repository に閉じる
- `research_tasks.ticket_id` は同一 project の ticket に閉じる
- `agent_runs.ticket_id` / `research_task_id` / `parent_run_id` は同一 project に閉じる
- `ticket_relations` は別 project の tickets を結べない

BLOCK:

- `agent_runs.parent_run_id` が `id` だけを参照
- `ticket_relations` が project_id なしで ticket id だけを結ぶ
- project_id nullable により boundary を bypass できる
- 同一 tenant・別 project 越境が DB constraint で防げない

4. RLS-ready metadata と repository contract を確認する。

```bash
rg -n "rls|row level|tenant context|current_tenant|tenant_id\s*==|where\(.*tenant|filter\(.*tenant|update|delete|rowcount" backend/app tests 2>/dev/null
```

WARN:

- P0 で RLS off の理由 / repository contract が docs に残っていない
- repository negative test がない
- UPDATE / DELETE の rowcount contract がない

BLOCK:

- repository が tenant context なしで query する
- raw SQL path が repository contract を bypass する
- background worker / job が tenant context を持たない

5. actors / principals / approval 境界を確認する。

```bash
rg -n "actors|principals|actor_type|principal_type|impersonated_by|approval|requester|decider|self" migrations backend/app tests 2>/dev/null
```

BLOCK:

- actor と principal を同じ table / enum として混同
- `actors.actor_type` が `human`, `service`, `agent`, `provider`, `github_app` を扱えない
- `principals.principal_type` が `session`, `api_token`, `capability_token`, `installation`, `worker` を扱えない
- self-approval を DB / service で拒否できない
- actor / principal FK に tenant boundary がない

6. AgentRun 16 状態 enum と event consistency を確認する。

```bash
rg -n "agent_runs|agent_run_events|status|blocked_reason|seq_no|idempotency_key|provider_refused|provider_incomplete|repair_exhausted|waiting_approval" migrations backend/app tests 2>/dev/null
```

必須 AgentRun status:

```text
queued
gathering_context
running
generated_artifact
schema_validated
policy_linted
diff_ready
waiting_approval
blocked
provider_refused
provider_incomplete
validation_failed
repair_exhausted
completed
failed
cancelled
```

BLOCK:

- 16 状態から欠落 / 追加がある
- `blocked_reason` を status enum に混ぜている
- `blocked_reason` が `policy_blocked`, `budget_blocked`, `runtime_blocked` 以外を許す
- terminal state から resume できる設計
- status update と AgentRunEvent append が同一 transaction でない
- AgentRunEvent に `(tenant_id, run_id, seq_no)` unique がない

7. ContextSnapshot 10 カラムを確認する。

```bash
rg -n "context_snapshots|prompt_pack_version|prompt_pack_lock|policy_version|policy_pack_lock|repo_state|tool_manifest|evidence_set_hash|provider_continuation_ref|provider_request_fingerprint|snapshot_kind" migrations backend/app tests 2>/dev/null
```

必須 10 カラム:

- `prompt_pack_version`
- `prompt_pack_lock`
- `policy_version`
- `policy_pack_lock`
- `repo_state`
- `tool_manifest`
- `evidence_set_hash`
- `provider_continuation_ref`
- `provider_request_fingerprint`
- `snapshot_kind`

BLOCK:

- 必須カラム欠落
- `snapshot_kind` enum が `input`, `pre_tool`, `post_tool`, `resume`, `final` と一致しない
- provider continuation / request fingerprint に raw secret / provider key を保存する列設計

8. SecretBroker DDL を確認する。

```bash
rg -n "secret_refs|secret_capability_tokens|secret_uri|secret_ref|token_hash|token_value|raw_secret|secret_value|private_key|api_key|status|runner_injectable|expected_request_fingerprint|expires_at|used_at" migrations backend/app tests 2>/dev/null
```

BLOCK:

- raw secret / private key / token 生値保存用列
- `secret_refs` に `secret_uri`, `scope`, `name`, `version`, `status`, `runner_injectable=false`, `allowed_consumers`, `allowed_operations`, `owner_actor_id` がない
- active / pending per `(tenant_id, scope, name)` の partial unique がない
- `secret_capability_tokens` に token hash / actor / run / expected_request_fingerprint / operation binding がない
- token status が one-time redeem を表現できない

## 出力 contract

Markdown で返す。

```markdown
## DB Review Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|specified-files
Depth: fast|deep

## Findings
| severity | file:line | category | violation | required_migration_or_test | trace |
|---|---|---|---|---|---|

## Required Migration Additions
| table | addition | reason | trace |
|---|---|---|---|

## Required Negative Tests
- <test case>

## Passed Controls
| invariant | evidence |
|---|---|
```

category は `tenant`, `project`, `actor-principal`, `agentrun`, `context-snapshot`, `secretbroker`, `repository`, `migration-test` のいずれかを使う。

## 失敗時の挙動

- `migrations/` が未作成なら WARN。ただし DB schema 変更 diff がある場合は BLOCK。
- `tenant_id` 欠落、parent id 単体 FK、project boundary bypass、raw secret 列、AgentRun enum drift、ContextSnapshot 欠落は BLOCK。
- negative test 不足は WARN。該当 schema 変更と同時なら BLOCK。
- destructive migration に rollback / backup 方針がない場合は BLOCK。
- line 特定ができない grep hit は Read で確認してから findings に入れる。

## TaskManagedAI 不変条件 trace

- AC-HARD-03 `tenant_isolation_negative_pass`
- 全主要 table の `tenant_id bigint NOT NULL DEFAULT 1`
- `(tenant_id, project_id, id)` project boundary
- actors / principals 分離
- AgentRun 16 状態 + `blocked_reason` サブ 3
- ContextSnapshot 必須 10 カラム
- SecretBroker DDL の raw secret 列不在
- AgentRunEvent / AuditEvent / PolicyDecision append-only 境界

