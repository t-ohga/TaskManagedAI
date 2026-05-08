---
name: quality-test-coverage
description: "TaskManagedAI の pytest/Vitest/Playwright coverage と contract test を監査する。Triggers: test coverage"
when_to_use: |
  backend/frontend/e2e のテスト品質、coverage 下限、弱い assertion、AgentRun/Provider/SecretBroker contract test の不足を確認する時。
  トリガーフレーズ: 'test coverage', '弱い assertion', 'contract test', 'AgentRun test', 'coverage gate'
argument-hint: "[--target=backend|frontend|both|e2e] [--scope=changed|all] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# quality-test-coverage — pytest + Vitest + Playwright + contract 監査

## 目的

TaskManagedAI のテストが仕様ベースで、弱い assertion だけに依存せず、Hard Gates / Quality KPIs / AgentRun / Provider / SecretBroker の contract を検証できているか監査する。

この skill は監査だけを行う。修正や test skeleton 生成は行わない。

## 必読資料

- `.claude/rules/testing.md`
- `.claude/rules/agentrun-state-machine.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/agents/taskmanagedai/tdd-orchestrator.md`
- `.claude/agents/taskmanagedai/hard-gate-fixture-reviewer.md`

## 対象

- `backend/tests/`
- `frontend/**/__tests__/`
- `frontend/**/*.test.{ts,tsx}`
- `frontend/**/*.spec.{ts,tsx}`
- `tests/e2e/`
- `frontend/vitest.config.*`
- `frontend/playwright.config.*`
- `pyproject.toml`

## 検査手順

1. テスト配置を確認する。

```bash
rg --files backend/tests frontend tests/e2e | rg '(test|spec|playwright|vitest|pytest)'
```

2. 弱い assertion を検出する。

```bash
rg -n "toBeDefined\(\)|toBeTruthy\(\)|not\.toThrow\(\)|toContain\([\"']error|expect\([^)]*\)\s*;|assert\s+[^=]+$|as\s+any" backend/tests frontend tests/e2e
```

BLOCK:

- `toBeDefined` / `toBeTruthy` だけで成功判定する
- `expect(...)` 単独行
- snapshot だけ
- status code だけ
- `as any` で fixture を通す

3. coverage 設定を確認する。

```bash
rg -n "coverage|threshold|fail_under|--cov|pytest-cov|branches|lines|functions|statements" pyproject.toml frontend/vitest.config.* frontend/package.json package.json
```

WARN:

- coverage 下限が未定義
- backend/frontend の片方だけ coverage がある
- branch coverage が重要境界で未計測

4. AgentRun 16 状態 contract test を確認する。

```bash
rg -n "queued|gathering_context|generated_artifact|schema_validated|policy_linted|diff_ready|waiting_approval|provider_refused|provider_incomplete|validation_failed|repair_exhausted|blocked_reason|terminal" backend/tests frontend tests/e2e
```

不足 test:

- 16 状態 enum 完全一致
- terminal state immutability
- `blocked_reason` 3 種
- `provider_incomplete` が terminal ではない
- status update と AgentRunEvent append の同一 transaction
- ContextSnapshot 10 カラム

5. Provider / SecretBroker / tenant boundary negative test を確認する。

```bash
rg -n "payload_data_class|allowed_data_class|provider_request_preflight|policy_blocked|SecretBroker|atomic claim|secret_capability|tenant_id|project_id|cross.*project|forbidden path|dangerous command" backend/tests frontend tests/e2e
```

不足 test:

- `payload_data_class` 未設定 deny
- caller-provided `allowed_data_class` reject
- `payload_data_class > allowed_data_class` deny
- secret canary preflight deny
- SecretBroker atomic claim 0/1 rows
- actor/run/fingerprint/operation mismatch deny
- tenant / project 越境 negative
- forbidden path / dangerous command fixture

6. 代表コマンドの実行可否を確認する。

```bash
uv run pytest
pnpm test
pnpm test -- --coverage
pnpm test:e2e
```

実行できない場合は理由を出力する。

## 出力 contract

```markdown
## Test Coverage Audit Result
Verdict: PASS|WARN|BLOCK

## Weak Assertions
| severity | file:line | pattern | replacement |
|---|---|---|---|

## Missing Tests
| severity | contract | expected test | suggested path |
|---|---|---|---|

## Coverage Baseline
| area | command/config | current | expected | verdict |
|---|---|---|---|---|

## Verification
| command | result | note |
|---|---|---|
```

## 失敗時の挙動

- テストディレクトリが未作成なら WARN。ただし対象実装が存在して contract test がない場合は BLOCK。
- `backend/` / `frontend/` が未作成なら WARN。
- Hard Gate に関わる negative test 不足は BLOCK。
- coverage tool が未導入なら WARN とし、導入候補を提示する。
- テスト実行が環境未整備で失敗した場合は、静的検査結果と verification gap を分けて出す。

## TaskManagedAI 不変条件 trace

- Hard Gates 7: AC-HARD-01〜07
- Quality KPIs 5: AC-KPI-01〜05
- AgentRun 16 状態 / blocked サブ 3
- Provider Compliance negative test
- SecretBroker atomic claim test
- tenant / project boundary negative test
- Eval fixture anti-gaming

