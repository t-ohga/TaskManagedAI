---
name: api-contract-audit
description: "TaskManagedAI FastAPI OpenAPI/Pydantic 契約を監査する。Triggers: API contract, ADR-00003"
when_to_use: |
  FastAPI endpoint、OpenAPI generated spec、request/response schema、error_code、actor/tenant dependency、API 契約 ADR を監査する時。
  トリガーフレーズ: 'API contract', 'OpenAPI', 'Pydantic response', 'ADR-00003', 'FastAPI endpoint'
argument-hint: "[--scope=changed|all] [--api-path=backend/app/api] [--openapi=<path>]"
allowed-tools: Read Bash Grep
---

# api-contract-audit — FastAPI OpenAPI contract 監査

## 目的

TaskManagedAI の FastAPI API が Pydantic request / response model、tenant / actor / principal dependency、structured error、provider raw response 非漏洩、ADR-00003 trace を満たすか監査する。

この skill は監査だけを行う。API 契約や schema は変更しない。

## 必読資料

- `.claude/rules/core.md` §11
- `.claude/rules/testing.md` §2, §6
- `.claude/rules/sprint-pack-adr-gate.md` §4 Criteria 3
- `.claude/rules/ai-output-boundary.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/deliverables.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`
- `.claude/agents/taskmanagedai/actor-binding-reviewer.md`

## 対象

- `backend/app/api/`
- `backend/app/**/schemas*.py`
- `backend/app/**/models*.py`
- OpenAPI generated spec
- `backend/tests/contract/`
- `docs/adr/`
- `docs/sprints/`

## 検査手順

1. API router と endpoint を抽出する。

```bash
rg -n "APIRouter|@router\.(get|post|put|patch|delete)|response_model|Depends|Body|Query|Path" backend/app/api backend/app
```

2. Pydantic request / response model を確認する。

```bash
rg -n "BaseModel|pydantic|response_model|Annotated|Body\(|dict\[|Dict|Any|return \{" backend/app/api backend/app
```

BLOCK:

- mutation endpoint の request body が Pydantic model ではない
- `response_model` がない
- raw dict を response として返し、schema がない
- provider raw response / internal exception を response に含める
- `Any` が API contract に露出する

3. tenant / actor / principal dependency を確認する。

```bash
rg -n "tenant_id|actor_id|principal_id|Depends|get_current|request_context|Actor|Principal|Tenant" backend/app/api backend/app
```

BLOCK:

- mutation endpoint に actor / principal / tenant context がない
- read endpoint が tenant context なしで repository を呼ぶ
- self-approval 禁止に必要な actor binding が取れない
- API key / capability token と actor が混同される

4. structured error を確認する。

```bash
rg -n "HTTPException|error_code|error_summary|detail=|Exception|provider|raw_response|traceback" backend/app/api backend/app
```

BLOCK:

- `detail=str(exc)` で内部情報を出す
- `error_code` がない
- `error_summary` がない
- raw secret / provider raw response / stack trace を response に出す

5. OpenAPI drift と contract test を確認する。

```bash
rg --files | rg '(openapi|schema).*\.json$'
rg -n "openapi|schema|contract|httpx|response_model|error_code|ADR-00003" backend/tests docs/adr docs/sprints
```

WARN/BLOCK:

- generated OpenAPI spec がない
- contract test がない
- API 契約変更が ADR-00003 または現行 API contract ADR に trace されない
- API contract 変更が Sprint Pack heavy になっていない

6. AgentRunEvent / audit event schema への影響を確認する。

```bash
rg -n "AgentRunEvent|audit|event_type|payload|correlation_id|trace_id|run_id|actor_id" backend/app/api backend/app docs/adr docs/sprints
```

API 契約が event schema を変える場合は ADR Gate Criteria 3 として扱う。

## 出力 contract

```markdown
## API Contract Audit Result
Verdict: PASS|WARN|BLOCK

## Contract Violations
| severity | file:line | rule | evidence | fix |
|---|---|---|---|---|

## ADR Requirements
| change | criterion | required_adr | evidence |
|---|---|---|---|

## Contract Test Gaps
| endpoint | missing test | suggested path |
|---|---|---|
```

## 失敗時の挙動

- backend が未作成なら WARN。
- OpenAPI spec 生成が未整備なら WARN。ただし API 実装があるのに contract test がない場合は BLOCK 寄り。
- security boundary の response leak は BLOCK。
- ADR-00003 が未作成なら、必要な契約判断を `ADR-NNNNN` として作成すべき旨を出す。
- 公式 FastAPI 仕様の断定が必要な場合は、ローカル実装または公式資料確認の必要性を明記する。

## TaskManagedAI 不変条件 trace

- FastAPI request / response Pydantic model
- `tenant_id` / `actor_id` / `principal_id` dependency
- structured `error_code` / `error_summary`
- raw secret / provider raw response 非露出
- API 契約 / event schema は ADR Gate Criteria 3
- AgentRunEvent / audit event append-only

