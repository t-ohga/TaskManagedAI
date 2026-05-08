---
name: security-owasp-2025
description: "TaskManagedAI を OWASP Top 10 2025/LLM 2025/MCP 2025 に写像監査する。Triggers: OWASP, LLM01, MCP"
when_to_use: |
  backend、frontend、Provider、runner、tool registry、MCP 境界を OWASP Top 10 2025、OWASP LLM Top 10 2025、OWASP MCP Top 10 2025 で監査する時。
  security-suite の補助としても単独でも使う。別 Skill / Agent は起動しない。
  トリガーフレーズ: 'OWASP 2025', 'LLM01', 'MCP 監査', 'security-owasp-2025'
argument-hint: "[--scope=current-branch|staged|all|specified-files] [--files=<comma-separated>] [--depth=fast|deep]"
allowed-tools: Read Bash Grep
---

# security-owasp-2025 — OWASP Top 10 2025 + LLM + MCP 監査

## 目的

TaskManagedAI の backend / frontend / Provider / runner / tool registry / MCP 境界を、OWASP Top 10:2025、OWASP Top 10 for LLM Applications 2025、OWASP MCP Top 10 2025 に TaskManagedAI 文脈で再解釈して監査する。

この skill は監査専用であり、修正は行わない。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/core.md` §5-§7
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/hard-gates-and-kpis.md`
- OWASP Top 10:2025: https://owasp.org/Top10/2025/
- OWASP LLM Top 10 2025: https://genai.owasp.org/llm-top-10/
- OWASP MCP Top 10 2025: https://owasp.org/www-project-mcp-top-10/

## 対象

- `backend/**/*`
- `frontend/**/*`
- `config/**/*`
- `migrations/**/*`
- `eval/security/**/*`
- `runner` / `tool registry` / `MCP` / `ProviderAdapter` / `SecretBroker` 関連 file
- `.github/workflows/**/*`
- `docs/sprints/**/*`, `docs/adr/**/*`

## 検査手順

1. 対象ファイルを確定する。

```bash
git diff --name-only
git diff --cached --name-only
rg --files backend frontend config migrations eval .github docs 2>/dev/null
```

2. OWASP Top 10:2025 を TaskManagedAI に写像する。

| OWASP Web ID | TaskManagedAI で見る境界 | BLOCK 条件 |
|---|---|---|
| A01 Broken Access Control | actor / principal / approval / tenant / project | self-approval、tenant 越境、project 越境、permission bypass |
| A02 Security Misconfiguration | Docker / Tailscale / config / debug | public bind、Funnel、debug、secret hardcode |
| A03 Software Supply Chain Failures | lockfile / Docker base / GitHub App / tool registry | unpinned base、permission 拡張、CI secret injection |
| A04 Cryptographic Failures | secret storage / token / SOPS | raw secret 保存、長命 token、弱い secret handling |
| A05 Injection | SQL / command / redirect / SSRF / prompt context | raw SQL interpolation、command injection、server-side fetch allowlist なし |
| A06 Insecure Design | Sprint Pack / ADR / threat model | high-risk ADR 不在、deny-by-default 破壊 |
| A07 Authentication Failures | dev auth / principal / token lifecycle | broad principal、token reuse、session boundary 不明 |
| A08 Software or Data Integrity Failures | workflow / artifact / provider / eval | AI output workflow 直書き、artifact hash なし、fixture poisoning |
| A09 Security Logging and Alerting Failures | audit / AgentRunEvent / correlation | policy / approval / secret / runner event 不足 |
| A10 Mishandling of Exceptional Conditions | exception / retry / timeout / cancellation | exception 握りつぶし、raw error leak、retry 無制限 |

検索例:

```bash
rg -n "tenant_id|project_id|actor_id|principal_id|approval|self|0\.0\.0\.0|Funnel|debug|secret|token|private_key|sql|execute\(|subprocess|shell=True|redirect|httpx|requests|audit|trace_id|correlation_id|except|retry|timeout" backend frontend config migrations .github docs 2>/dev/null
```

3. OWASP LLM Top 10 2025 を TaskManagedAI に写像する。

| OWASP LLM ID | TaskManagedAI control | BLOCK 条件 |
|---|---|---|
| LLM01 Prompt Injection | Input Trust Layer / untrusted_content / AC-HARD-07 | untrusted context を trusted_instruction に昇格 |
| LLM02 Sensitive Information Disclosure | SecretBroker / redaction / Provider preflight / AC-HARD-02 | raw secret / PII / canary が prompt、log、artifact、provider request に出る |
| LLM03 Supply Chain | Provider Matrix / tool registry / dependency | untrusted provider / tool / package を検証なしに採用 |
| LLM04 Data and Model Poisoning | eval fixture / evidence provenance | private holdout 汚染、evidence hash なし |
| LLM05 Improper Output Handling | schema validation / Pydantic / Zod / policy lint | AI output を validation なしに command / SQL / workflow へ接続 |
| LLM06 Excessive Agency | action class / approval / deny-by-default | AI が repo write / tool write / runner patch を承認なしに実行 |
| LLM07 System Prompt Leakage | prompt pack lock / ContextSnapshot redaction | system prompt / policy pack / provider state を export する |
| LLM08 Vector and Embedding Weaknesses | evidence hash / retrieval provenance | retrieved context の provenance / trust tier がない |
| LLM09 Misinformation | claims / citations / evidence_set_hash | citation なし claim を accepted にする |
| LLM10 Unbounded Consumption | BudgetGuard / retry cap / cost KPI | retry / token / wall-clock / cost cap がない |

検索例:

```bash
rg -n "prompt|untrusted_content|trusted_instruction|system_prompt|payload_data_class|provider_request_preflight|secret_ref|schema_validated|policy_linted|approval|BudgetGuard|max_retry|max_tokens|cost|evidence_set_hash|citation|fixture|private_holdout" backend frontend config eval docs 2>/dev/null
```

4. OWASP MCP Top 10 2025 を TaskManagedAI の tool / MCP 境界に写像する。

| OWASP MCP ID | TaskManagedAI control | BLOCK 条件 |
|---|---|---|
| MCP01 Token Mismanagement & Secret Exposure | SecretBroker / short-lived capability | tool / MCP context に raw token |
| MCP02 Privilege Escalation via Scope Creep | tool allowlist / trust tier / ADR | tool scope が broad で expiry なし |
| MCP03 Tool Poisoning | tool manifest / schema pinning | tool definition の provenance / hash なし |
| MCP04 Supply Chain Attacks & Dependency Tampering | signed deps / lockfile / mirror policy | tool server dependency 未固定 |
| MCP05 Command Injection & Execution | structured command plan / runner gate | untrusted input 由来 command 実行 |
| MCP06 Intent Flow Subversion | untrusted_content separation | context payload が user intent を上書き |
| MCP07 Insufficient Authentication & Authorization | actor / principal / tool auth | tool call に actor / principal binding なし |
| MCP08 Lack of Audit and Telemetry | immutable audit / tool invocation log | gateway audit 不足 |
| MCP09 Shadow MCP Servers | registered tool registry only | unknown MCP server / local rogue server |
| MCP10 Context Injection & Over-Sharing | context scope / data class | unrelated run / tenant / project context を共有 |

検索例:

```bash
rg -n "mcp|tool_registry|tool_manifest|tool_mutating_gateway_stub|runner_mutation_gateway|gateway_kind|transport|stdio|http|trust_tier|scope|allowlist|capability|context|tool call|audit" backend config docs 2>/dev/null
```

5. AC-HARD-NN trace を付ける。

| リスク | Hard Gate trace |
|---|---|
| policy bypass / excessive agency | AC-HARD-01 |
| secret / PII / token leak | AC-HARD-02 |
| tenant / project access control | AC-HARD-03 |
| forbidden path | AC-HARD-05 |
| dangerous command / command injection | AC-HARD-06 |
| prompt injection / intent subversion | AC-HARD-07 |

## 出力 contract

Markdown で返す。

```markdown
## OWASP 2025 Audit Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|all|specified-files
Sources:
- OWASP Top 10:2025: https://owasp.org/Top10/2025/
- OWASP LLM Top 10 2025: https://genai.owasp.org/llm-top-10/
- OWASP MCP Top 10 2025: https://owasp.org/www-project-mcp-top-10/

## OWASP Web Top 10
| id | status | file:line | TaskManagedAI control | finding | trace |
|---|---|---|---|---|---|

## OWASP LLM Top 10
| id | status | file:line | TaskManagedAI control | finding | trace |
|---|---|---|---|---|---|

## OWASP MCP Top 10
| id | status | file:line | TaskManagedAI control | finding | trace |
|---|---|---|---|---|---|

## Required Actions
| severity | action | owner_area | verification |
|---|---|---|---|
```

status は `PASS`, `WARN`, `BLOCK`, `NOT_APPLICABLE` のみ。BLOCK が 1 件でもあれば全体 verdict は BLOCK。

## 失敗時の挙動

- OWASP ID に完全に該当する file がなくても、TaskManagedAI control が未実装なら WARN として dormant / not implemented を記録する。
- raw secret / token / PII らしき値は再出力しない。
- OWASP LLM / MCP は更新される可能性があるため、外部リンクの version / date が不明な場合は WARN とし、公式ページ確認を要求する。
- prompt injection、secret leak、AI output direct execution、command injection、tenant bypass は BLOCK。
- MCP 実装が未作成なら `NOT_APPLICABLE` だが、tool registry docs がある場合は scope / audit だけ確認する。

## TaskManagedAI 不変条件 trace

- AC-HARD-01 `policy_block_recall`
- AC-HARD-02 `secret_canary_no_leak`
- AC-HARD-03 `tenant_isolation_negative_pass`
- AC-HARD-05 `forbidden_path_block`
- AC-HARD-06 `dangerous_command_block`
- AC-HARD-07 `prompt_injection_resist`
- `payload_data_class` / `allowed_data_class` 分離
- `tool_mutating_gateway_stub` / `runner_mutation_gateway` 分離
- AgentRunEvent / AuditEvent append-only
- ContextSnapshot 10 カラム / evidence provenance

