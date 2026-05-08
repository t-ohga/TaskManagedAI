---
name: secure-design-threat-model-audit
description: "TaskManagedAI の設計 threat model と AI boundary を監査する。Triggers: threat model"
when_to_use: |
  新規機能の Sprint Pack heavy、設計 docs、AI output boundary、Provider/Secret/Runner/tenant 境界の threat model を確認する時。
  トリガーフレーズ: 'threat model', 'secure design', 'STRIDE', 'OWASP LLM', 'AI output boundary'
argument-hint: "[--sprint=SP-NNN] [--docs=<comma-separated>] [--feature=<name>]"
allowed-tools: Read Bash Grep
---

# secure-design-threat-model-audit — 設計時 threat model 監査

## 目的

TaskManagedAI の新規機能が、実装前に STRIDE / OWASP LLM 観点、AI 出力直結禁止、deny-by-default、Provider Compliance、SecretBroker、Runner sandbox、tenant boundary、ADR Gate 該当判定を Sprint Pack / 設計 docs に明記しているか監査する。

この skill は監査と追記提案だけを行う。docs は変更しない。

## 必読資料

- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/instincts.md`
- `.claude/rules/core.md` §6
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/agents/taskmanagedai/security-specialist.md`
- `.claude/agents/taskmanagedai/runner-security-reviewer.md`

## 対象

- `docs/sprints/SP-*.md`
- `docs/adr/*.md`
- `docs/基本設計/`
- `docs/実装計画/`
- 新規機能の設計 docs
- Provider / SecretBroker / Runner / Tool / Repo / API / DB boundary に触る計画

## 検査手順

1. 対象 Sprint Pack / docs を確認する。

```bash
rg -n "SP-[0-9]{3}|type: heavy|threat|STRIDE|OWASP|AI output|deny-by-default|Provider|SecretBroker|runner|tenant|ADR-[0-9]{5}|AC-HARD|AC-KPI" docs/sprints docs/adr docs/基本設計 docs/実装計画
```

2. STRIDE 観点の有無を確認する。

```text
Spoofing:
- actor / principal / capability token / GitHub App identity

Tampering:
- artifact / diff / workflow / migration / policy pack / prompt pack

Repudiation:
- audit event / AgentRunEvent / approval event / correlation_id

Information disclosure:
- raw secret / provider key / private repo / ContextSnapshot export

Denial of service:
- provider retry / runner resource cap / budget / queue exhaustion

Elevation of privilege:
- AI output direct execution / tool permission / runner bypass / self-approval
```

3. OWASP LLM 観点を確認する。

```bash
rg -n "prompt injection|untrusted_content|secret|sensitive|supply chain|output handling|excessive agency|system prompt|citation|budget|eval|private_holdout" docs/sprints docs/adr docs/基本設計 docs/実装計画
```

最低限含めるべき項目:

- prompt injection / untrusted content
- sensitive information disclosure
- improper output handling
- excessive agency
- supply chain / provider trust
- unbounded consumption
- eval anti-gaming

4. AI output boundary と gateway 境界を確認する。

```bash
rg -n "artifact|schema_validated|policy_linted|diff_ready|waiting_approval|tool_mutating_gateway_stub|runner_mutation_gateway|trusted_instruction|approval|forbidden path|dangerous command" docs/sprints docs/adr docs/基本設計 docs/実装計画
```

BLOCK:

- AI 出力を command / SQL / workflow / external tool に直結
- approval なしに runner / repo write
- `tool_mutating_gateway_stub` と `runner_mutation_gateway` の混同
- forbidden path / dangerous command の検証なし

5. Provider / Secret / tenant / Runner boundary を確認する。

```bash
rg -n "payload_data_class|allowed_data_class|provider_request_preflight|SecretBroker|secret_ref|atomic claim|tenant_id|project_id|runner|sandbox|resource cap|AC-HARD" docs/sprints docs/adr docs/基本設計 docs/実装計画
```

BLOCK:

- `payload_data_class` / `allowed_data_class` の信頼境界不明
- SecretBroker が raw secret を返す設計
- atomic claim がない
- tenant / project boundary が DB と test に trace しない
- runner resource cap / cancel / timeout がない

6. ADR Gate 該当判定を確認する。

```bash
rg -n "Criteria|ADR Gate|認証|DB schema|API 契約|AI エージェント権限|tool 権限|Secrets|外部公開|破壊的操作|広範囲リファクタ|Provider|GitHub App" docs/sprints docs/adr
```

Criteria 11 種に該当する場合は heavy Pack + ADR が必須。

## 出力 contract

```markdown
## Threat Model Audit Result
Verdict: PASS|WARN|BLOCK

## Threat Model Section Proposal
### Assets
...
### Trust Boundaries
...
### STRIDE
...
### OWASP LLM
...
### Required Controls
...

## Findings
| severity | category | evidence | required addition |
|---|---|---|---|

## Sprint Pack Additions
| section | proposed text |
|---|---|
```

## 失敗時の挙動

- Sprint Pack がない場合は BLOCK。
- heavy が必要なのに light の場合は BLOCK。
- threat model section がない場合は WARN。ただし AI output / Secret / Runner / Provider / DB boundary に触るなら BLOCK。
- secret 値や private key を例示に含めない。
- security control が実装詳細未確定の場合は、must_ship / defer / residual risk に分けて提案する。

## TaskManagedAI 不変条件 trace

- AI 出力直結禁止
- deny-by-default
- Provider Compliance Matrix
- SecretBroker atomic claim / raw secret 非露出
- Runner sandbox / gateway 分離
- tenant / project boundary
- ADR Gate Criteria 11 種
- AC-HARD-01 / 02 / 03 / 05 / 06 / 07

