---
name: privacy-pii-audit
description: "TaskManagedAI の PII 検出、retention、redaction、Provider 送信前処理を監査する。Triggers: PII, redaction"
when_to_use: |
  backend logs、artifact、audit event、Provider request body、Eval fixture、frontend 表示で PII / redaction / retention を監査する時。
  security-suite や release 前確認で使う。別 Skill / Agent は起動しない。
  トリガーフレーズ: 'PII 監査', 'privacy-pii-audit', 'redaction 確認', 'payload_data_class=pii'
argument-hint: "[--scope=current-branch|staged|all|specified-files] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# privacy-pii-audit — PII detection + retention + redaction

## 目的

TaskManagedAI の backend logs / artifact / audit event / Provider request body / Eval fixture / UI 表示を対象に、PII pattern、`payload_data_class=pii`、retention policy、redaction policy、Provider 送信前 redaction を監査する。

この skill は監査専用であり、修正は行わない。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/provider-compliance.md` §4-§7
- `.claude/rules/ai-output-boundary.md` §4, §10-§12
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/core.md` §7, §10-§11
- `.claude/reference/provider-compliance-matrix.md`
- `.claude/reference/audit-ownership-matrix.md`

## 対象

- `backend/**/*.py`
- `frontend/**/*.{ts,tsx}`
- `config/**/*`
- `eval/**/*`
- `docs/**/*fixture*`
- artifact / audit / log / provider request body / eval fixture 関連 code
- PII detection / redaction / retention 関連 docs

## 検査手順

1. 対象ファイルを確定する。

```bash
git diff --name-only
git diff --cached --name-only
rg --files backend frontend config eval docs 2>/dev/null
```

2. PII pattern と PII っぽい identifier を検出する。

```bash
rg -n "email|mail_address|phone|tel|address|postal|zip|name|full_name|display_name|user_name|id_number|personal|pii|birth|dob|ip_address|user_agent" backend frontend config eval docs 2>/dev/null
rg -n "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|[0-9]{2,4}[- ][0-9]{2,4}[- ][0-9]{3,4}" backend frontend config eval docs 2>/dev/null
```

BLOCK:

- eval fixture / docs / test data に実在に見える PII がある
- log / audit / artifact に email / phone / address / name などを raw で保存
- provider request body に PII を送る path がある
- `payload_data_class=pii` の扱いが deny-by-default でない

WARN:

- synthetic data である根拠がない
- PII identifier があるが classification / redaction の test がない
- retention owner / expiry がない

3. `payload_data_class=pii` と Provider deny を確認する。

```bash
rg -n "payload_data_class|allowed_data_class|pii|ProviderAdapter|provider_request_preflight|redact|sanitize|mask|classification|data_class" backend frontend config 2>/dev/null
```

BLOCK:

- PII を `internal` / `confidential` として送信できる
- `payload_data_class` が未設定の provider request
- `allowed_data_class` を caller 入力として PII 送信可否に使う
- Provider Matrix の `pii` deny-by-default を迂回する
- preflight / redaction より先に provider call する
- denial audit に `payload_data_class` / `allowed_data_class` が残らない

WARN:

- PII detection が pattern / schema の片方だけ
- redaction 後 artifact hash / provenance がない
- PII downgrade / exclusion の理由が audit に残らない

4. log / audit event / error handling を確認する。

```bash
rg -n "logger\.|log\.|print\(|console\.|audit_events|AuditEvent|error_summary|error_code|trace_id|correlation_id|request_body|response_body|stack|exception" backend frontend 2>/dev/null
rg -n "sanitize|redact|mask|hash|reason_code|pattern_hit|raw" backend frontend 2>/dev/null
```

BLOCK:

- request body / response body を unredacted で log
- exception / stack trace に PII / raw provider response を含める
- audit payload に unredacted PII / raw prompt / provider request body を保存
- console / client error report に PII を送る
- secret canary / token pattern と PII pattern を raw 値で記録

WARN:

- structured redaction reason_code がない
- trace_id / correlation_id と redaction event が結びつかない
- retention / deletion policy が audit event にない

5. artifact / ContextSnapshot / provider continuation を確認する。

```bash
rg -n "artifact|ContextSnapshot|context_snapshots|provider_continuation_ref|provider_request_fingerprint|exportable|evidence_set_hash|request_body|prompt|completion|raw_response" backend frontend migrations docs 2>/dev/null
```

BLOCK:

- artifact export に PII が残るのに `exportable=false` でない
- ContextSnapshot に raw provider request / raw response / PII を保存
- provider continuation ref の本体を audit export に出す
- redaction 済み artifact と raw artifact の境界がない
- evidence_set_hash に PII raw 値を正当化なく含める

WARN:

- retention period / deletion job がない
- redaction 後の hash / provenance が曖昧
- PII を含む fixture の public / private 分離がない

6. Eval fixture / private holdout を確認する。

```bash
rg -n "fixture|dataset_version|private_holdout|public_regression|adversarial_new|expected|email|phone|name|address|pii|redacted" eval docs 2>/dev/null
```

BLOCK:

- private fixture の PII が redaction なしに repo / report に出る
- private holdout の期待値を public docs に転載
- fixture 由来 PII を provider に送る test path がある
- dataset version に `payload_data_class` がない

WARN:

- synthetic PII の生成ルールがない
- fixture retention / refresh policy がない
- redacted sample と raw fixture の保管境界がない

## 出力 contract

Markdown で返す。

```markdown
## Privacy / PII Audit Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|all|specified-files

## PII Pattern Hits
| severity | file:line | pattern_type | storage_or_flow | redaction_status | required_fix |
|---|---|---|---|---|---|

## Redaction / Retention Gaps
| severity | file:line | issue | impact | required_fix | trace |
|---|---|---|---|---|---|

## Provider Data Class Checks
| flow | payload_data_class | provider_action | verdict | note |
|---|---|---|---|---|

## Required Verification
- <test / fixture / audit check>
```

pattern_type は `email`, `phone`, `address`, `name`, `id`, `network`, `free-text`, `unknown` から選ぶ。raw 値は出力しない。

## 失敗時の挙動

- PII らしき値を発見しても、値を再出力しない。`redacted pattern hit` と file:line のみ書く。
- PII provider 送信、unredacted audit / log / artifact、ContextSnapshot PII raw 保存は BLOCK。
- synthetic data と判断する場合は、根拠 file / naming / generator を示す。根拠がなければ WARN。
- `payload_data_class=pii` を P0 で allow する path は BLOCK。例外がある場合は ADR と Provider Matrix の根拠を要求する。
- 対象 path が未作成なら WARN とし、dormant 状態を明記する。

## TaskManagedAI 不変条件 trace

- Provider Compliance: `pii` deny-by-default
- `payload_data_class` 必須 / `allowed_data_class` Matrix 由来
- `provider_request_preflight` secret / PII pattern block
- AI Output Boundary: artifact exportable flag / untrusted content separation
- SecretBroker raw secret 非露出と同じ redaction discipline
- AC-HARD-02 `secret_canary_no_leak`
- AC-HARD-07 prompt injection 経由の context over-sharing 防止
- Eval anti-gaming / private fixture 非露出

