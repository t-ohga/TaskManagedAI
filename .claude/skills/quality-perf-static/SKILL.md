---
name: quality-perf-static
description: "TaskManagedAI の FastAPI/Next.js Server Component 性能リスクを静的監査する。Triggers: perf, N+1"
when_to_use: |
  FastAPI endpoint、repository query、Next.js Server Component の性能リスクを PR 前または quality-suite 実行中に静的確認する時。
  トリガーフレーズ: 'perf static', 'N+1', 'unbounded list', 'Server Component perf', 'bundle 増加'
argument-hint: "[--target=backend|frontend|both] [--scope=changed|all] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# quality-perf-static — FastAPI + Next.js Server Component 性能監査

## 目的

TaskManagedAI の FastAPI API と Next.js UI が、N+1、unbounded list、unindexed WHERE、重い同期処理、過剰な Client Component、bundle 増加要因を持っていないか静的に監査する。

この skill は監査だけを行う。性能改善 patch は作成しない。

## 必読資料

- `.claude/rules/rendering.md`
- `.claude/rules/core.md` §11
- `.claude/rules/code-search.md`
- `.claude/reference/frontend-strategy.md`
- `.claude/reference/db-schema-notes.md`
- `.claude/reference/dev-commands.md`
- `.claude/agents/taskmanagedai/postgres-specialist.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`

## 対象

- `backend/app/api/`
- `backend/app/repositories/`
- `backend/app/services/`
- `frontend/app/`
- `frontend/components/`
- `migrations/`

## 検査手順

1. API endpoint と repository query を抽出する。

```bash
rg -n "APIRouter|@router\.|Depends|select\(|session\.execute|query\(|joinedload|selectinload|relationship|lazy=|limit\(|offset\(|WHERE|where\(" backend/app migrations
```

2. N+1 / lazy load suspect を検出する。

```bash
rg -n "for .* in .*:|relationship\(|lazy=['\"]select|\.children|\.tickets|\.agent_runs|session\.execute|select\(" backend/app/repositories backend/app/services backend/app/api
```

WARN/BLOCK:

- request handler 内 loop で repository / DB call
- SQLAlchemy relationship が lazy load default のまま list endpoint で使用される
- `selectinload` / explicit join / batching の根拠がない
- AgentRunEvent / AuditEvent の一覧で pagination がない

3. unbounded list を検出する。

```bash
rg -n "list|search|history|events|logs|audit|agent_runs|limit|offset|cursor|page_size|created_at" backend/app/api backend/app/repositories
```

BLOCK:

- list endpoint に `limit` / cursor / max page size がない
- audit / event / artifact / evidence を全件返す
- frontend が initial render で無制限 fetch する

4. unindexed WHERE / ORDER BY 候補を探す。

```bash
rg -n "where\(|WHERE|order_by|ORDER BY|tenant_id|project_id|run_id|ticket_id|created_at|correlation_id|trace_id" backend/app/repositories migrations
rg -n "create index|unique \(|foreign key|GIN|jsonb" migrations
```

WARN:

- `(tenant_id, project_id, id)` boundary query の index が見当たらない
- `run_id`, `ticket_id`, `created_at`, `correlation_id`, `trace_id` filter に index が見当たらない
- JSONB containment query があるが GIN index 候補が未検討

5. Server Component の重い同期処理を確認する。

```bash
rg -n "use client|fs\.|crypto\.|JSON\.parse|while\s*\(|for\s*\(|map\(|await .*await|Promise\.all|fetch\(" frontend/app frontend/components
```

WARN/BLOCK:

- Server Component で巨大 JSON parse / crypto / CPU heavy loop
- initial render で複数 await waterfall
- provider call / SecretBroker resolve を UI から直接起動
- audit raw payload をそのまま client へ渡す

6. Client Component 過剰と bundle 増加要因を確認する。

```bash
rg -n "^['\"]use client['\"]|from ['\"][^'\"]+['\"]|dynamic\(|lazy\(|window\.|document\.|localStorage" frontend/app frontend/components
```

WARN:

- page / layout 全体が Client Component
- browser API が leaf component に閉じていない
- large dependency を top-level static import
- chart / editor / diff viewer を常時 import

## 出力 contract

```markdown
## Performance Static Audit Result
Verdict: PASS|WARN|BLOCK

## Findings
| severity | file:line | category | evidence | recommendation |
|---|---|---|---|---|

## Index Candidates
| table_or_query | columns | reason | supporting evidence |
|---|---|---|---|

## Verification Gaps
| gap | follow-up command |
|---|---|
```

## 失敗時の挙動

- 実行 DB がなく EXPLAIN できない場合は WARN とし、静的 index 候補を出す。
- frontend が未作成なら frontend 部分は WARN skip。
- backend が未作成なら backend 部分は WARN skip。
- secret / provider / runner を UI から直接起動する導線は性能ではなく security BLOCK として扱う。
- 不確かな N+1 は WARN とし、確認すべき query / test を示す。

## TaskManagedAI 不変条件 trace

- FastAPI boundary: Pydantic / dependency / transaction
- PostgreSQL tenant/project invariant
- AgentRunEvent / AuditEvent append-only の pagination
- AC-KPI-02 `time_to_merge`
- AC-KPI-03 `approval_wait_ms`
- AC-KPI-05 `cost_per_completed_task`
- SecretBroker / ProviderAdapter / Runner は UI から直接操作しない

