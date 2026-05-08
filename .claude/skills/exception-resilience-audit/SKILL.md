---
name: exception-resilience-audit
description: "TaskManagedAI の例外処理、timeout、retry、AgentRun error mapping を監査する。Triggers: exception audit"
when_to_use: |
  backend の provider / runner / repo / secret / worker / API 例外処理、timeout、cancel、retry、AgentRun status update を監査する時。
  トリガーフレーズ: 'exception audit', 'resilience', 'timeout', 'retry', 'error_code'
argument-hint: "[--scope=changed|all] [--paths=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# exception-resilience-audit — 例外処理と回復性監査

## 目的

TaskManagedAI の backend が例外を握りつぶさず、`error_code` / `error_summary`、AgentRun status、AgentRunEvent / audit event、timeout、cancel、retry / repair 上限、secret 非漏洩を正しく扱うか監査する。

この skill は監査だけを行う。修正は行わない。

## 必読資料

- `.claude/rules/core.md` §4
- `.claude/rules/agentrun-state-machine.md` §7-§10
- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/agents/taskmanagedai/agentrun-state-reviewer.md`
- `.claude/agents/taskmanagedai/runner-security-reviewer.md`
- `.claude/agents/taskmanagedai/provider-compliance-reviewer.md`

## 対象

- `backend/app/`
- `backend/app/api/`
- `backend/app/providers/`
- `backend/app/runners/`
- `backend/app/repositories/`
- `backend/app/secrets/`
- `backend/app/worker/`
- `backend/tests/`

## 検査手順

1. try/except と broad catch を抽出する。

```bash
rg -n "try:|except|raise|HTTPException|Exception|BaseException|pass$|return None|logger\.exception|traceback|error_code|error_summary" backend/app backend/tests
```

BLOCK:

- `except Exception: pass`
- broad catch 後に `return None` / success 扱い
- `error_code` / `error_summary` なし
- raw exception message を API / audit / artifact に出す
- rollback / transaction boundary なしで partial state を残す

2. AgentRun status update と event append を確認する。

```bash
rg -n "status|blocked_reason|AgentRunEvent|run_failed|run_cancelled|provider_refused|provider_incomplete|validation_failed|repair_exhausted|policy_blocked|budget_blocked|runtime_blocked" backend/app
```

BLOCK:

- provider refusal を generic failed に潰す
- provider incomplete を terminal にする
- validation failure に repair retry 上限がない
- timeout / cancel 時に AgentRunEvent がない
- status update と event append が別 transaction

3. timeout / cancel 境界を確認する。

```bash
rg -n "timeout|asyncio\.timeout|wait_for|cancel|CancelledError|signal|kill|terminate|resource cap|retry|backoff|max_retries|max_attempts" backend/app backend/tests
```

BLOCK:

- provider / runner / repo / secret 操作に timeout がない
- `CancelledError` を握りつぶす
- cancel 後に repo write / provider call を継続する
- retry 上限がない
- budget exceeded を provider failure と混同する

4. SecretBroker / provider / runner leak を確認する。

```bash
rg -n "secret|token|api_key|private_key|provider_key|capability|raw_response|stdout|stderr|logger|audit|redact|sanitize" backend/app backend/tests
```

BLOCK:

- secret 値を exception message / log / audit / runner env に出す
- provider raw response を retry prompt に入れる
- runner stdout / stderr の canary をそのまま保存する
- capability token 生値を DB / log に保存する

5. repo / migration / external IO resilience を確認する。

```bash
rg -n "httpx|requests|subprocess|docker|git|alembic|session\.commit|transaction|rollback|commit\(|flush\(" backend/app backend/tests
```

WARN/BLOCK:

- external IO に timeout がない
- subprocess error を exit code なしで握る
- DB commit 失敗時に audit がない
- idempotency key なしで retry する
- destructive operation に rollback 方針がない

## 出力 contract

```markdown
## Exception Resilience Audit Result
Verdict: PASS|WARN|BLOCK

## Findings
| severity | file:line | category | evidence | fix |
|---|---|---|---|---|

## Error Mapping Gaps
| flow | expected status/event | current evidence | action |
|---|---|---|---|

## Retry / Timeout Gaps
| file:line | operation | missing boundary | recommendation |
|---|---|---|---|
```

## 失敗時の挙動

- backend が未作成なら WARN。
- line number は直接確認した箇所だけ書く。
- secret leak risk は BLOCK。
- AgentRun terminal / retry / cancel mapping の誤りは BLOCK。
- timeout 未設定は provider / runner / repo / secret 操作では BLOCK、内部 pure function では対象外。
- 不明な exception policy は Sprint Pack / ADR の確認事項として返す。

## TaskManagedAI 不変条件 trace

- exception は `error_code` / `error_summary` として AgentRun / audit に残す
- AgentRun provider result mapping
- `repair_exhausted` retry upper bound
- cancel / timeout boundary
- SecretBroker raw secret 非露出
- runner forbidden path / dangerous command failure mapping
- Budget exceeded は `blocked` + `budget_blocked`

