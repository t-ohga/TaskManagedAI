---
name: review-type-safety
description: "TaskManagedAI の PR/指定ファイルで TS/Python/Pydantic 型安全をレビューする。Triggers: review type safety, as any, mypy"
when_to_use: |
  PR diff、current branch、指定ファイルの TypeScript strict、Python typing、FastAPI/Pydantic boundary をレビューする時。
  review-suite の Type Safety review として使う。quality-type-safety の観点を PR 指摘形式へ変換するが、別 skill は起動しない。
  トリガーフレーズ: 'review type safety', '型安全レビュー', 'as any 検出', 'Pydantic 境界レビュー'
argument-hint: "[--scope=current-branch|staged|specified-files] [--files=<comma-separated>] [--depth=fast|deep]"
allowed-tools: Read Bash Grep
---

# review-type-safety — PR 差分の型安全レビュー

## 目的

TaskManagedAI の PR diff / 指定ファイルを対象に、TypeScript strict、Python typing、FastAPI / Pydantic boundary の型安全違反を file:line 付きでレビューする。

この skill はレビュー専用であり、修正は行わない。別 Skill / Agent を再帰起動しない。`quality-type-safety` は監査 baseline として参照するだけに留める。

## 必読資料

- `.claude/rules/core.md` §2-§4
- `.claude/rules/core.md` §11
- `.claude/rules/code-search.md`
- `.claude/skills/quality-type-safety/SKILL.md`
- `.claude/reference/dev-commands.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`

## 対象

- PR diff / staged diff / current branch diff
- `frontend/**/*.{ts,tsx}`
- `backend/**/*.py`
- `backend/app/api/**/*.py`
- `backend/app/**/schemas*.py`
- `backend/app/**/models*.py`
- `frontend/tsconfig*.json`
- `pyproject.toml`

## 検査手順

1. 対象ファイルを確定する。

```bash
git diff --name-only
git diff --cached --name-only
rg --files frontend backend pyproject.toml | rg '(\.tsx?$|\.py$|tsconfig.*\.json$|pyproject\.toml$)'
```

`--files` が渡された場合は、その file list を優先する。存在しない path は WARN として記録する。

2. TypeScript strict baseline を確認する。

```bash
rg -n '"strict"|"noImplicitAny"|"strictNullChecks"|"exactOptionalPropertyTypes"|"noUncheckedIndexedAccess"' frontend/tsconfig*.json tsconfig*.json 2>/dev/null
```

BLOCK:

- `strict: false`
- `noImplicitAny: false`
- `strictNullChecks: false`
- 新規 TS file が strict 対象外になる include / exclude 変更
- API client 型が schema / OpenAPI 由来ではなく手書き DTO として drift している

3. TypeScript unsafe pattern を探す。

```bash
rg -n "\bas\s+any\b|:\s*any\b|<any>|@ts-ignore|@ts-expect-error|satisfies\s+any" frontend 2>/dev/null
rg -n "unknown|z\.|safeParse|payload_data_class|allowed_data_class|secret_ref|capability" frontend 2>/dev/null
```

BLOCK:

- `as any` / `: any` / `<any>` の新規混入
- `@ts-ignore` による型エラー抑制
- `unknown` を Zod / typed guard / discriminated union で narrowing しない
- `allowed_data_class` を UI / caller 入力として扱う
- secret / provider key / capability token 生値を client / DOM / cache に渡す

WARN:

- `@ts-expect-error` の理由がない
- 過剰な type assertion で validation を迂回している
- AgentRun status / `blocked_reason` を string literal の散在で扱う

4. Python typing baseline を確認する。

```bash
rg -n "\[tool\.mypy\]|strict|disallow_untyped_defs|warn_return_any|no_implicit_optional" pyproject.toml 2>/dev/null
rg -n "def .*\(|async def .*\(|Any|#\s*type:\s*ignore|cast\(|dict\[str,\s*Any\]" backend 2>/dev/null
```

BLOCK:

- public function / method の引数 annotation 欠落
- public function / method の return annotation 欠落
- API / provider / secret / repository boundary に `Any` が露出
- `# type: ignore` の理由なし使用
- `cast()` で validation 欠落を隠す

WARN:

- internal helper の annotation 欠落
- `dict[str, Any]` が boundary 内に閉じているが schema 化予定が不明
- mypy / pyright 対象外 module が増えている

5. FastAPI / Pydantic boundary を確認する。

```bash
rg -n "APIRouter|@router\.|Depends|response_model|BaseModel|pydantic|tenant_id|actor_id|principal_id" backend/app 2>/dev/null
rg -n "request:\s*Request|dict\[|Mapping\[|Json|Any|response_model=None" backend/app/api backend/app 2>/dev/null
```

BLOCK:

- request body が Pydantic model ではない
- response model がなく raw dict / raw provider response を返す
- mutation endpoint に `tenant_id` / `actor_id` / `principal_id` dependency がない
- provider structured output boundary に Pydantic model がない
- service 層へ raw request dict を渡す
- internal error / raw exception を API response に出す

6. 型 narrowing と enum drift を確認する。

```bash
rg -n "queued|gathering_context|running|generated_artifact|schema_validated|policy_linted|diff_ready|waiting_approval|blocked|provider_refused|provider_incomplete|validation_failed|repair_exhausted|completed|failed|cancelled" backend frontend 2>/dev/null
rg -n "blocked_reason|policy_blocked|budget_blocked|runtime_blocked|snapshot_kind" backend frontend 2>/dev/null
```

BLOCK:

- AgentRun 16 状態から外れた status が追加されている
- `blocked_reason` を status enum に混ぜている
- ContextSnapshot 10 カラムの名前を型定義で落としている

## 出力 contract

Markdown で返す。

```markdown
## Type Safety Review Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|specified-files
Depth: fast|deep

## Findings
| severity | file:line | rule | evidence | impact | fix |
|---|---|---|---|---|---|

## Positive Checks
| invariant | evidence |
|---|---|

## Required Verification
- <command or manual check>
```

severity は `BLOCK`, `WARN`, `INFO` のみ。`file:line` は実際に読んだ行だけを書く。推測の場合は file までに留め、line は空にする。

## 失敗時の挙動

- `frontend/` または `backend/` が未作成なら WARN とし、対象未作成を明記する。
- `pnpm typecheck` / `uv run mypy backend` が未整備なら WARN とし、静的検索結果を返す。
- secret、Provider、API、DB boundary の型安全違反は BLOCK。
- line 特定ができない grep hit は、該当 file を Read してから findings に入れる。
- 外部仕様に依存する型生成は断定せず、生成元と確認コマンドを提示する。

## TaskManagedAI 不変条件 trace

- TypeScript strict / Python typing: `.claude/rules/core.md` §2-§4
- FastAPI request / response Pydantic model: `.claude/rules/core.md` §11
- `payload_data_class` / `allowed_data_class` 分離: Provider Compliance invariant
- AgentRun 16 状態 / `blocked_reason` サブ 3: AgentRun state machine
- ContextSnapshot 10 カラム: reproducibility contract
- Secret 値非露出: AC-HARD-02

