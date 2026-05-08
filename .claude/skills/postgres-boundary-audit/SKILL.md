---
name: postgres-boundary-audit
description: "TaskManagedAI PostgreSQL の tenant/project isolation DDL と negative tests を監査する。Triggers: postgres boundary, tenant_id"
when_to_use: |
  migrations、models、repository、pytest DB tests、tenant_id、project_id、複合 FK、cross-project negative test を確認する時。
  トリガーフレーズ: 'postgres boundary', 'tenant_id', 'project isolation', 'AC-HARD-03'
argument-hint: "<migrations path> [models path] [pytest db tests path]"
allowed-tools: Read Bash Grep
---

# postgres-boundary-audit — tenant/project isolation DDL 監査

## 目的

TaskManagedAI の PostgreSQL schema が P0 個人運用でも tenant / project boundary を維持し、将来 multi-tenant-ready な DDL / repository contract / negative test を持つか監査する。

## 必読資料

- `.claude/rules/core.md` §8
- `.claude/rules/instincts.md` §8
- `.claude/reference/db-schema-notes.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/rules/testing.md` §6

## Main Agent への指示

この skill は監査だけを行う。migration や model の修正は行わず、PASS/WARN/BLOCK と違反 DDL list を出す。

## Step 1: migration / model の tenant invariant 確認

検索例:

```bash
rg -n "tenant_id|project_id|foreign key|ForeignKeyConstraint|UniqueConstraint|unique \\(|parent_run_id|ticket_relations|agent_runs|tickets|research_tasks|repositories" <paths>
```

必須:

- 全主要 table に `tenant_id bigint NOT NULL DEFAULT 1`。
- `unique (tenant_id, id)`。
- parent FK は `(tenant_id, parent_id)`。
- `repositories`, `tickets`, `research_tasks`, `agent_runs` は `unique (tenant_id, project_id, id)`。
- repository / service の SELECT / UPDATE / DELETE は tenant context を条件に持つ。
- P0 では RLS off でも repository contract test がある。

主要 table:

```text
tenants, users, actors, principals, workspaces, projects, repositories,
tickets, ticket_relations, acceptance_criteria, research_tasks,
evidence_sources, claims, claim_evidence, agent_runs, agent_run_events,
artifacts, context_snapshots, policy_decisions, approval_requests,
approval_events, dataset_versions, eval_runs, eval_cases, eval_scores,
audit_events, secret_refs, secret_capability_tokens, budgets
```

BLOCK patterns:

- 主要 table の `tenant_id` 欠落。
- `tenant_id` nullable。
- parent id 単体 FK。
- global slug / key unique。
- repository query に tenant context なし。
- UPDATE / DELETE に tenant context なし。

## Step 2: project boundary 確認

同一 tenant 内でも project を越えない。

必須:

```sql
unique (tenant_id, project_id, id)
```

代表 FK:

```sql
foreign key (tenant_id, project_id, ticket_id)
references tickets(tenant_id, project_id, id)
```

対象:

- `tickets.repository_id` は同一 project の repository。
- `research_tasks.ticket_id` は同一 project の ticket。
- `agent_runs.ticket_id` は同一 project の ticket。
- `agent_runs.research_task_id` は同一 project の research_task。
- `agent_runs.parent_run_id` は同一 project の run。
- `ticket_relations` は project boundary を越えない。

BLOCK patterns:

- `agent_runs.parent_run_id` が `id` だけを参照。
- `ticket_relations` が別 project の ticket を結べる。
- project_id を nullable にして境界を bypass。
- cross-project INSERT / UPDATE が DB constraint で失敗しない。

## Step 3: negative tests 確認

必須 test:

- 別 project の ticket を research_task に紐付ける INSERT が失敗。
- 別 project の run を `agent_runs.parent_run_id` に設定する INSERT / UPDATE が失敗。
- `ticket_relations` で別 project の ticket 同士を結ぶ INSERT が失敗。
- 別 project の repository を ticket に紐付ける INSERT / UPDATE が失敗。
- tenant context と異なる row を SELECT できない。
- tenant context 外 row を UPDATE / DELETE できない。
- Audit / AgentRunEvent / EvalResult が別 tenant の run に紐付かない。

検索例:

```bash
rg -n "cross.*project|tenant.*negative|parent_run_id|ticket_relations|isolation|AC-HARD-03|pytest.raises|IntegrityError|rowcount" <test paths>
```

WARN patterns:

- DB constraint はあるが repository negative test がない。
- repository test はあるが DB FK / unique で閉じていない。
- RLS-ready metadata が未記録。
- migration rollback が書かれていない。

## 出力 contract

```json
{
  "skill": "postgres-boundary-audit",
  "verdict": "PASS|WARN|BLOCK",
  "inputs": {
    "migrations": [],
    "models": [],
    "tests": []
  },
  "table_checks": [
    {
      "table": "agent_runs",
      "tenant_id": "PASS|WARN|BLOCK",
      "tenant_unique": "PASS|WARN|BLOCK",
      "project_unique": "PASS|WARN|BLOCK",
      "composite_fk": "PASS|WARN|BLOCK"
    }
  ],
  "violations": [
    {
      "severity": "BLOCK|WARN",
      "reason_code": "tenant_id_missing|tenant_nullable|single_column_fk|project_boundary_missing|negative_test_missing|repository_context_missing",
      "path": "<path>",
      "line": 0,
      "ddl": "<summary>",
      "message": "<summary>"
    }
  ],
  "required_negative_tests": [
    "cross-project research_task ticket insert fails",
    "cross-project agent_runs parent_run_id fails",
    "cross-project ticket_relations fails",
    "cross-tenant select/update/delete fails"
  ],
  "trace": ["AC-HARD-03"]
}
```

## 失敗時の挙動

- `tenant_id` 欠落は BLOCK。
- parent id 単体 FK は BLOCK。
- cross-project relation が DB で閉じていない場合は BLOCK。
- negative test 不足は WARN。DB schema 変更と同時なら BLOCK。
- migration rollback 不明は WARN。破壊的 migration では BLOCK。
- 対象 path が読めない場合は BLOCK。

## TaskManagedAI 不変条件 trace

- AC-HARD-03 `tenant_isolation_negative_pass` を DB / repository / eval に接続する。
- 全主要 table の `tenant_id bigint NOT NULL DEFAULT 1` を維持する。
- `(tenant_id, project_id, id)` の project boundary を維持する。
- `agent_runs.parent_run_id` を同一 project に閉じる。
- `ticket_relations` の project 越境を禁止する。
- AgentRunEvent、AuditEvent、PolicyDecision の append-only event 境界を tenant 内に閉じる。

