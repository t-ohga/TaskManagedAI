---
name: type-safety-baseline-audit
description: "TaskManagedAI の TS strict/mypy strict baseline を監査し段階適用 plan を出す。Triggers: type baseline"
when_to_use: |
  TypeScript strict、mypy strict、ignore-list、baseline file の現状把握と段階適用方針を決める時。
  トリガーフレーズ: 'type baseline', 'strict baseline', 'mypy baseline', '段階適用', 'ignore list'
argument-hint: "[--target=backend|frontend|both] [--scope=all] [--propose-plan]"
allowed-tools: Read Bash Grep
---

# type-safety-baseline-audit — 型安全 baseline 監査

## 目的

新規導入時または既存 strict 化の途中で、TypeScript strict / mypy strict の現状、ignore-list の規模、新規ファイルへの strict 適用ポリシー、baseline file 管理方針を整理する。

この skill は設定変更しない。現状 baseline と段階適用 plan を返す。

## 必読資料

- `.claude/rules/core.md` §2-§4
- `.claude/rules/code-search.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/frontend-strategy.md`
- `.claude/reference/governance-cycle.md`
- `.claude/agents/taskmanagedai/code-reviewer.md`

## 対象

- `tsconfig.json`
- `frontend/tsconfig*.json`
- `pyproject.toml`
- `mypy.ini`
- `backend/**/*.py`
- `frontend/**/*.{ts,tsx}`
- type baseline / ignore-list files がある場合はそのファイル

## 検査手順

1. 設定ファイルを抽出する。

```bash
rg --files | rg '(^|/)(tsconfig.*\.json|pyproject\.toml|mypy\.ini|.*mypy.*baseline.*|.*type.*baseline.*)$'
```

2. TypeScript strict option の現状を確認する。

```bash
rg -n '"strict"|"noImplicitAny"|"strictNullChecks"|"strictFunctionTypes"|"exactOptionalPropertyTypes"|"noUncheckedIndexedAccess"|"skipLibCheck"' tsconfig*.json frontend/tsconfig*.json
```

baseline table に入れる項目:

- `strict`
- `noImplicitAny`
- `strictNullChecks`
- `exactOptionalPropertyTypes`
- `noUncheckedIndexedAccess`
- `skipLibCheck`
- include / exclude
- generated type の扱い

3. Python mypy strict の現状を確認する。

```bash
rg -n "\[tool\.mypy\]|\[mypy\]|strict|disallow_untyped_defs|disallow_any|warn_return_any|warn_unused_ignores|no_implicit_optional|ignore_missing_imports" pyproject.toml mypy.ini
```

baseline table に入れる項目:

- `strict`
- `disallow_untyped_defs`
- `disallow_incomplete_defs`
- `warn_return_any`
- `warn_unused_ignores`
- `no_implicit_optional`
- module override
- `ignore_missing_imports`

4. ignore-list / suppression 規模を確認する。

```bash
rg -n "@ts-ignore|@ts-expect-error|as any|:\s*any\b|#\s*type:\s*ignore|typing\.Any|cast\(" frontend backend
```

分類:

- `boundary_critical`: API / provider / secret / repo / runner / AgentRun
- `legacy_internal`: old helper / isolated util
- `test_fixture`: test helper
- `generated`: generated code

5. 新規ファイル strict policy を確認する。

```bash
rg -n "strict|baseline|ignore|type safety|mypy|tsconfig|new file|新規" docs/sprints docs/adr .claude docs/実装計画 docs/基本設計
```

推奨 policy:

- 新規 frontend file は strict を必須
- 新規 backend public function は annotation 必須
- 新規 API / Provider / SecretBroker / repository boundary は suppression 禁止
- baseline file は削減のみ許可
- suppression 追加時は理由、期限、owner、Sprint Pack 残リスクが必要

## 出力 contract

```markdown
## Type Safety Baseline
Verdict: PASS|WARN|BLOCK

## Current Baseline
| area | option | current | expected | risk |
|---|---|---|---|---|

## Suppression Inventory
| severity | file:line | pattern | classification | action |
|---|---|---|---|---|

## Adoption Plan
| phase | scope | action | verification | exit |
|---|---|---|---|---|
```

段階適用 plan は原則 3 段階にする。

1. 新規ファイル strict
2. boundary critical strict
3. legacy internal suppression の削減

## 失敗時の挙動

- 設定ファイルが未作成なら WARN とし、初期 baseline 推奨を出す。
- boundary critical に suppression がある場合は BLOCK。
- 既存 debt が大きい場合は一括修正を提案せず、段階適用 plan に分ける。
- `skipLibCheck` など妥当な暫定設定は理由と削減条件を記録する。

## TaskManagedAI 不変条件 trace

- TypeScript strict / Python public annotation
- FastAPI/Pydantic boundary 型安全
- Provider Compliance `payload_data_class` / `allowed_data_class` drift 防止
- SecretBroker raw secret 非露出
- AgentRun 16 状態 / ContextSnapshot 10 カラムの型同期
- ADR Gate Criteria 該当変更の事前判断

