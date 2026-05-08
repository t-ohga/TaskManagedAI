---
name: observability-audit
description: "TaskManagedAI structured logs/correlation/audit redaction を監査する。Triggers: observability"
when_to_use: |
  backend log emission、AgentRunEvent、audit event、correlation_id、redaction、OTel trace binding、metrics 出力を監査する時。
  トリガーフレーズ: 'observability', 'structured logs', 'correlation_id', 'redaction', 'audit log'
argument-hint: "[--scope=changed|all] [--paths=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# observability-audit — structured logs / correlation / redaction 監査

## 目的

TaskManagedAI の backend observability が JSON Lines、correlation id、trace id、redaction、AgentRunEvent / audit event append-only、raw secret 非露出、OTel / Loki / Prometheus 連携前提を満たすか監査する。

この skill は監査だけを行う。ログ実装や設定は変更しない。

## 必読資料

- `.claude/rules/core.md` §11
- `.claude/rules/ai-output-boundary.md` §12
- `.claude/rules/secretbroker-boundary.md` §11
- `.claude/rules/agentrun-state-machine.md` §5-§6
- `.claude/reference/db-schema-notes.md` §13
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/dev-commands.md`
- `.claude/agents/taskmanagedai/release-auditor.md`
- `.claude/agents/taskmanagedai/security-specialist.md`

## 対象

- `backend/app/`
- `backend/app/core/`
- `backend/app/api/`
- `backend/app/services/`
- `backend/app/repositories/`
- `backend/app/providers/`
- `backend/app/secrets/`
- `backend/app/runners/`
- log / metrics / tracing 設定ファイル

## 検査手順

1. log emission point を抽出する。

```bash
rg -n "logging|getLogger|logger\.|structlog|print\(|trace_id|correlation_id|span|otel|OpenTelemetry|metrics|prometheus|loki|audit|AgentRunEvent" backend/app
```

BLOCK:

- `print()` による operational log
- raw exception をそのまま log
- secret / token / provider key / private key / capability token 生値を log
- audit event なしの critical mutation

2. JSON Lines 必須 field を確認する。

```bash
rg -n "event_type|tenant_id|actor_id|resource_type|resource_id|run_id|trace_id|correlation_id|payload|created_at|timestamp|level|message" backend/app
```

必須 field:

- `timestamp`
- `level`
- `event_type`
- `tenant_id`
- `actor_id`
- `run_id` または null 理由
- `trace_id`
- `correlation_id`
- `resource_type`
- `resource_id`
- `payload`
- `error_code` / `error_summary` (error 時)

3. correlation_id / trace_id 伝播を確認する。

```bash
rg -n "correlation_id|trace_id|request_id|Request|Middleware|Depends|contextvar|AgentRunEvent|audit" backend/app
```

WARN/BLOCK:

- request middleware で correlation_id を発行しない
- worker / runner / provider call に correlation_id が渡らない
- AgentRunEvent と audit event の trace が結べない
- OTel trace id と app trace id の対応がない

4. redaction policy を確認する。

```bash
rg -n "redact|sanitize|secret|token|api_key|private_key|provider_key|capability|canary|raw_response|payload_data_class|allowed_data_class" backend/app
```

BLOCK:

- raw secret / private key / provider key / token を payload に入れる
- canary raw value を保存する
- provider raw response を unredacted で保存する
- `payload_data_class` と `allowed_data_class` を単一 field に潰す

5. AgentRunEvent / audit event append-only を確認する。

```bash
rg -n "AgentRunEvent|audit_events|append|insert|update|delete|seq_no|idempotency_key|event_type" backend/app backend/tests migrations
```

BLOCK:

- event row を UPDATE / DELETE する通常 path
- `(tenant_id, run_id, seq_no)` unique がない
- status update と event append が別 transaction
- audit event に actor / run / correlation がない

6. metrics / dashboard source を確認する。

```bash
rg -n "acceptance_pass_rate|time_to_merge|approval_wait_ms|citation_coverage|cost_per_completed_task|prometheus|Counter|Histogram|Gauge" backend/app frontend eval
```

WARN:

- Quality KPI data source が log / metric / DB event に接続されていない
- AC-HARD failure が metric / audit から追えない

## 出力 contract

```markdown
## Observability Audit Result
Verdict: PASS|WARN|BLOCK

## Findings
| severity | file:line | category | evidence | fix |
|---|---|---|---|---|

## Redaction Risks
| severity | file:line | raw_value_type | sink | action |
|---|---|---|---|---|

## Trace Coverage
| flow | trace_id | correlation_id | audit_event | verdict |
|---|---|---|---|---|
```

## 失敗時の挙動

- backend が未作成なら WARN。
- log framework 未選定なら WARN とし、必須 payload contract だけを返す。
- raw secret / token / private key の漏洩可能性は BLOCK。
- OTel / Loki / Prometheus が未導入でも、trace_id / correlation_id / structured log contract は要求する。
- line number 付き finding は該当行を直接確認したものだけにする。

## TaskManagedAI 不変条件 trace

- AgentRunEvent append-only
- AuditEvent append-only
- `trace_id` / `correlation_id` binding
- raw secret / capability token / provider key 非露出
- SecretBroker audit payload
- Provider Compliance audit payload
- AC-HARD-02 `secret_canary_no_leak`
- AC-KPI-01〜05 data source

