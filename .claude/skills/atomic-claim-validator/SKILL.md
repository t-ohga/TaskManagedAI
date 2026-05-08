---
name: atomic-claim-validator
description: "TaskManagedAI SecretBroker redeem の atomic claim 設計を検証する。Triggers: atomic claim, SecretBroker, capability token"
when_to_use: |
  SecretBroker DDL、service code、migration、capability token redeem、OperationContext fingerprint、one-time claim を確認する時。
  トリガーフレーズ: 'atomic claim', 'SecretBroker', 'capability token', 'redeem 検証'
argument-hint: "<DDL file path> <service code path> [migration file path]"
allowed-tools: Read Bash Grep
---

# atomic-claim-validator — SecretBroker redeem 設計検証

## 目的

SecretBroker の redeem が one-time atomic claim として実装され、actor / run / fingerprint / operation binding を同一 SQL で満たしているかを検証する。check -> execute -> mark used の逐次処理は BLOCK とする。

## 必読資料

- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/instincts.md` §3
- `.claude/reference/secretbroker-contract.md`
- `.claude/reference/db-schema-notes.md`
- `.claude/rules/testing.md` §9

## Main Agent への指示

この skill は Read / Bash / Grep による検証だけを行う。修正は行わず、PASS/WARN/BLOCK と違反点を出す。

## Step 1: 対象ファイルの確認

対象:

- DDL / migration: `secret_refs`, `secret_capability_tokens`。
- service code: issue / redeem / broker-mediated operation。
- tests: atomic claim, mismatch, concurrent redeem。

検索例:

```bash
rg -n "secret_capability_tokens|secret_refs|expected_request_fingerprint|issued_to_actor_id|issued_run_id|requested_operation|token_hash|used_at|expires_at|redeem|OperationContext|for update" <paths>
```

## Step 2: atomic claim WHERE 節検証

必須条件:

| 条件 | 判定 |
|---|---|
| `tenant_id = :tenant_id` | 無ければ BLOCK |
| `token_hash = :token_hash` | 無ければ BLOCK |
| `status = 'issued'` | 無ければ BLOCK |
| `used_at is null` | 無ければ BLOCK |
| `expires_at > now()` | 無ければ BLOCK |
| `issued_to_actor_id = :actor_id` | 無ければ BLOCK |
| `issued_run_id is not distinct from :run_id` または同等の null-safe run binding | 無ければ BLOCK |
| `expected_request_fingerprint = :computed_fingerprint` | 無ければ BLOCK |
| requested operation allow check | 無ければ BLOCK |
| `returning id, secret_ref_id` など claim success 判定 | 無ければ BLOCK |

期待 SQL pattern:

```sql
update secret_capability_tokens
   set status = 'redeeming',
       used_at = now()
 where tenant_id = :tenant_id
   and token_hash = :token_hash
   and status = 'issued'
   and used_at is null
   and expires_at > now()
   and issued_to_actor_id = :actor_id
   and issued_run_id is not distinct from :run_id
   and expected_request_fingerprint = :computed_fingerprint
   and :requested_operation = any(<allowed_operations_check>)
returning id, secret_ref_id, allowed_operations, scope_constraint;
```

## Step 3: 逐次処理と binding 漏れ検出

BLOCK patterns:

- `select ... token_hash ...` で確認後、operation 実行後に `update ... used_at`。
- operation 実行の前に token row を claim していない。
- `expected_request_fingerprint` が caller-supplied 任意 hash。
- issue 時と redeem 時で OperationContext canonical schema が一致しない。
- `secret_refs` を claim 後に `for update` で再検証していない。
- operation 失敗時に同一 token を再利用可能。
- raw token / raw secret / canary raw value を DB / log / audit に保存。
- `get_secret_value`, `inject_runner_env`, `expand_secret_into_prompt`, `export_secret_artifact` のような禁止 operation。

WARN patterns:

- concurrent redeem test がない。
- substitution negative test が不足。
- TTL 5-30 分の test が不足。
- deny reason_code が coarse すぎる。
- audit event に `trace_id` / `correlation_id` がない。

## 出力 contract

```json
{
  "skill": "atomic-claim-validator",
  "verdict": "PASS|WARN|BLOCK",
  "inputs": {
    "ddl_paths": [],
    "service_paths": [],
    "migration_paths": []
  },
  "checks": [
    {
      "name": "status_issued_where",
      "status": "PASS|WARN|BLOCK",
      "evidence": "<file:line or snippet summary>"
    }
  ],
  "violations": [
    {
      "severity": "BLOCK|WARN",
      "reason_code": "missing_atomic_claim_where|sequential_redeem|fingerprint_caller_supplied|raw_secret_exposure|missing_negative_test",
      "path": "<path>",
      "line": 0,
      "message": "<summary>"
    }
  ],
  "required_negative_tests": [
    "operation substitution",
    "target substitution",
    "payload substitution",
    "approval substitution",
    "secret_ref substitution",
    "actor mismatch",
    "run mismatch",
    "concurrent redeem"
  ]
}
```

## 失敗時の挙動

- 必須 WHERE 条件欠落は BLOCK。
- check -> execute -> mark used は BLOCK。
- raw secret / token / canary raw value 露出は BLOCK。
- 対象ファイルが読めない場合は BLOCK。パスが曖昧な場合は AskUserQuestion 相当の確認を Main Agent に戻す。
- test 不足は WARN。ただし redeem 実装変更と同時なら BLOCK に引き上げる。

## TaskManagedAI 不変条件 trace

- SecretBroker atomic claim と one-time redeem を守る。
- actor / run / expected_request_fingerprint / requested_operation binding を守る。
- raw secret 非露出を AC-HARD-02 に trace する。
- AgentRun / audit event に `secret_capability_issued` / `redeemed` / `denied` を trace する。
- approval self-approval と operation substitution を防ぐ。

