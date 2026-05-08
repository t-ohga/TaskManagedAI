---
name: db-performance-audit
description: "TaskManagedAI PostgreSQL index/EXPLAIN/slow query を監査する。Triggers: DB performance"
when_to_use: |
  migrations、repository、slow query、EXPLAIN、index 設計、N+1、unbounded SELECT を監査する時。
  トリガーフレーズ: 'DB performance', 'EXPLAIN', 'index', 'slow query', 'seq scan'
argument-hint: "[--scope=changed|all] [--migrations=migrations] [--repositories=backend/app/repositories] [--explain-log=<path>]"
allowed-tools: Read Bash Grep
---

# db-performance-audit — PostgreSQL EXPLAIN / index / slow query 監査

## 目的

TaskManagedAI の PostgreSQL schema と repository query が、tenant/project boundary を維持しながら、主要 filter に index を持ち、N+1、unbounded SELECT、不要な seq scan を避けているか監査する。

この skill は監査だけを行う。migration や index は作成しない。

## 必読資料

- `.claude/reference/db-schema-notes.md`
- `.claude/rules/core.md` §8
- `.claude/rules/instincts.md` §8
- `.claude/rules/sprint-pack-adr-gate.md` §4, §9
- `.claude/reference/dev-commands.md`
- `.claude/agents/taskmanagedai/postgres-specialist.md`
- `.claude/agents/taskmanagedai/tenant-project-isolation-reviewer.md`

## 対象

- `migrations/`
- `backend/app/repositories/`
- `backend/app/services/`
- `backend/tests/db/`
- slow query log / EXPLAIN output
- `docs/adr/`
- `docs/sprints/`

## 検査手順

1. DDL と index を確認する。

```bash
rg -n "create table|alter table|create index|unique \(|foreign key|tenant_id|project_id|jsonb|GIN|BTREE|agent_runs|agent_run_events|audit_events|context_snapshots|policy_decisions|approval_requests" migrations
```

必須 / 推奨:

- 全 main table の `tenant_id` index
- `(tenant_id, id)` unique
- project scoped table の `(tenant_id, project_id, id)` unique
- 複合 FK の参照列 index
- AgentRunEvent: `(tenant_id, run_id, seq_no)`
- AuditEvent: `(tenant_id, trace_id)`, `(tenant_id, correlation_id)`, `(tenant_id, event_type, created_at desc)`
- frequently filter 列の composite index
- JSONB containment query がある場合は GIN index 候補

2. repository query を確認する。

```bash
rg -n "select\(|session\.execute|where\(|filter\(|order_by|limit\(|offset\(|join\(|joinedload|selectinload|tenant_id|project_id|created_at|run_id|ticket_id|correlation_id|trace_id" backend/app/repositories backend/app/services
```

BLOCK:

- SELECT / UPDATE / DELETE に tenant context がない
- project scoped query に project boundary がない
- list query に limit / cursor がない
- event / audit / artifact を無制限取得する
- loop 内 DB query の N+1 suspect

3. WHERE / ORDER BY と index の対応を確認する。

```bash
rg -n "where\(|order_by|ORDER BY|WHERE|created_at|status|blocked_reason|run_id|ticket_id|repository_id|project_id|tenant_id" backend/app/repositories migrations
```

index 候補例:

- `(tenant_id, project_id, status, created_at desc)`
- `(tenant_id, project_id, ticket_id)`
- `(tenant_id, run_id, seq_no)`
- `(tenant_id, correlation_id)`
- `(tenant_id, trace_id)`
- `(tenant_id, event_type, created_at desc)`

4. EXPLAIN / slow query log を確認する。

```bash
rg -n "EXPLAIN|ANALYZE|Seq Scan|Index Scan|Bitmap|Nested Loop|rows=|actual time|slow query|duration" .
```

WARN/BLOCK:

- large table で Seq Scan
- tenant/project filter なしの Seq Scan
- sort spill / high rows removed by filter
- N+1 による repeated query
- EXPLAIN が Sprint Pack / ADR にないまま high-traffic query を追加

5. ADR Gate と rollback を確認する。

```bash
rg -n "DB schema|index|migration|rollback|ADR-[0-9]{5}|tenant_id|project boundary|EXPLAIN" docs/adr docs/sprints
```

DB schema / index 変更は ADR Gate Criteria 2。破壊的 migration は Criteria 8 も確認する。

## 出力 contract

```markdown
## DB Performance Audit Result
Verdict: PASS|WARN|BLOCK

## Index Candidates
| severity | table_or_query | columns | reason | evidence |
|---|---|---|---|---|

## Query Findings
| severity | file:line | category | evidence | recommendation |
|---|---|---|---|---|

## EXPLAIN Notes
| query | finding | action |
|---|---|---|
```

## 失敗時の挙動

- migrations / backend が未作成なら WARN。
- DB に接続できない場合は static audit のみで WARN。
- tenant context 欠落は performance ではなく correctness BLOCK。
- index 追加は DB schema 変更なので ADR Gate Criteria 2 として扱う。
- EXPLAIN 結果がない場合は、確認すべき代表 query とコマンドを出す。

## TaskManagedAI 不変条件 trace

- PostgreSQL tenant/project invariant
- `(tenant_id, project_id, id)` composite boundary
- AgentRunEvent / AuditEvent append-only query performance
- AC-HARD-03 `tenant_isolation_negative_pass`
- AC-KPI-02 `time_to_merge`
- AC-KPI-03 `approval_wait_ms`
- DB schema / index は ADR Gate Criteria 2

