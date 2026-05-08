---
name: quality-type-safety
description: "TaskManagedAI の TS/Python 型安全を監査する。Triggers: type safety, strict, mypy"
when_to_use: |
  frontend TypeScript、backend Python、FastAPI/Pydantic boundary の型安全性を commit 前、PR 前、quality-suite 実行中に確認する時。
  トリガーフレーズ: 'type safety', 'strict 確認', 'mypy', 'as any 検出', 'Pydantic 境界'
argument-hint: "[--target=backend|frontend|both] [--scope=changed|all] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# quality-type-safety — TypeScript strict + Python typing 監査

## 目的

TaskManagedAI の `frontend/**/*.{ts,tsx}` と `backend/**/*.py` が、TypeScript strict、Python typing、FastAPI/Pydantic boundary の型安全 invariant を満たすか監査する。

この skill は監査だけを行う。修正は行わず、違反箇所と修正方針を返す。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/core.md` §2-§4
- `.claude/rules/code-search.md`
- `.claude/rules/testing.md` §3
- `.claude/reference/dev-commands.md`
- `.claude/reference/frontend-strategy.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`

## 対象

- `frontend/**/*.{ts,tsx}`
- `frontend/tsconfig*.json`
- `backend/**/*.py`
- `pyproject.toml`
- `backend/app/api/`
- `backend/app/**/models*.py`
- `backend/app/**/schemas*.py`

## 検査手順

1. 対象ファイルを絞る。

```bash
git diff --name-only --cached
git diff --name-only
rg --files frontend backend pyproject.toml | rg '(\.tsx?$|\.py$|tsconfig.*\.json$|pyproject\.toml$)'
```

2. TypeScript strict 設定を確認する。

```bash
rg -n '"strict"|"noImplicitAny"|"strictNullChecks"|"exactOptionalPropertyTypes"|"noUncheckedIndexedAccess"' frontend/tsconfig*.json tsconfig*.json
```

BLOCK:

- `strict: false`
- `noImplicitAny: false`
- `strictNullChecks: false`
- 新規ファイルが strict 対象外の include / exclude に入る
- OpenAPI 由来でない手書き DTO が API contract と drift している

3. TypeScript の unsafe pattern を検出する。

```bash
rg -n "\bas\s+any\b|:\s*any\b|<any>|@ts-ignore|@ts-expect-error|//\s*type:\s*ignore" frontend
rg -n "allowed_data_class|payload_data_class|ProviderAdapter|secret_ref|capability" frontend
```

BLOCK:

- `as any` / `: any` の新規混入
- `@ts-ignore` による抑制
- `allowed_data_class` を UI / caller 入力として扱う
- Client Component に secret / provider key / capability token 生値を渡す

4. Python typing と mypy strict を確認する。

```bash
rg -n "\[tool\.mypy\]|strict|disallow_untyped_defs|warn_return_any|no_implicit_optional" pyproject.toml
rg -n "def .*\(|async def .*\(|Any|#\s*type:\s*ignore|cast\(" backend
```

BLOCK:

- public function / method の引数または戻り値 annotation 欠落
- `Any` が API / provider / secret / repository boundary に出る
- `# type: ignore` の理由なし使用
- mypy strict 相当の設定が新規 module に適用されない

5. FastAPI/Pydantic boundary を確認する。

```bash
rg -n "APIRouter|@router\.|Depends|response_model|BaseModel|pydantic|tenant_id|actor_id|principal_id" backend/app/api backend/app
```

BLOCK:

- request body が Pydantic model ではない
- response model がなく dict を直接返す
- mutation endpoint に `tenant_id` / `actor_id` / `principal_id` dependency がない
- provider structured output boundary に Pydantic model がない
- raw request dict を service 層へ渡す

## 出力 contract

Markdown で返す。

```markdown
## Type Safety Audit Result
Verdict: PASS|WARN|BLOCK
Scope: backend|frontend|both

## Violations
| severity | file:line | rule | evidence | fix |
|---|---|---|---|---|

## Config Baseline
| area | current | expected | verdict |
|---|---|---|---|

## Fix Plan
1. ...
```

`file:line` は実際に確認した行だけを書く。推測の場合は `file` までに留め、`line` を書かない。

## 失敗時の挙動

- `frontend/` または `backend/` が未作成なら WARN とし、対象未作成を明記する。
- `pnpm typecheck` / `uv run mypy backend` が未整備なら WARN とし、静的検索の結果を返す。
- secret、Provider、API、DB boundary の型安全違反は BLOCK。
- 外部仕様に依存する型生成の可否は断定せず、生成元と確認コマンドを提示する。

## TaskManagedAI 不変条件 trace

- TypeScript strict / Python typing: `.claude/rules/core.md` §2-§4
- FastAPI request / response Pydantic model: `.claude/rules/core.md` §11
- `payload_data_class` / `allowed_data_class` 分離: Provider Compliance invariant
- Secret 値非露出: SecretBroker boundary / AC-HARD-02
- AgentRun 16 状態と ContextSnapshot 10 カラムの型 drift 防止

