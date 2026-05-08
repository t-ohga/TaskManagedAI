---
name: review-security
description: "TaskManagedAI の Provider/SecretBroker/Runner/OWASP LLM セキュリティをレビューする。Triggers: review security, secret"
when_to_use: |
  PR diff、current branch、指定ファイルで Provider、SecretBroker、Runner、AI Output Boundary、OWASP LLM / MCP リスクをレビューする時。
  review-suite の Security review として使う。security-suite や専門 agent は起動せず、file:line の findings を返す。
  トリガーフレーズ: 'review security', 'セキュリティレビュー', 'SecretBroker レビュー', 'prompt injection 確認'
argument-hint: "[--scope=current-branch|staged|specified-files] [--files=<comma-separated>] [--depth=fast|deep]"
allowed-tools: Read Bash Grep
---

# review-security — Provider / SecretBroker / Runner セキュリティレビュー

## 目的

TaskManagedAI の PR diff / 指定ファイルを対象に、AI 出力直結、Provider Compliance、SecretBroker、Runner / Tool gateway、OWASP LLM / MCP 系の重大リスクを severity 別にレビューする。

この skill はレビュー専用であり、修正は行わない。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/core.md` §5-§7, §10-§11
- `.claude/rules/instincts.md` §2-§5, §10-§13
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/secretbroker-contract.md`
- `.claude/agents/taskmanagedai/security-specialist.md`

## 対象

- `backend/**/*.py`
- `frontend/**/*.{ts,tsx}`
- `config/**/*.toml`
- `migrations/**/*`
- `eval/security/**/*`
- `.github/workflows/**/*`
- runner / tool registry / provider adapter / SecretBroker / audit event 関連 file
- PR diff / staged diff / 指定ファイル

## 検査手順

1. 対象ファイルと high-risk path を確認する。

```bash
git diff --name-only
git diff --cached --name-only
rg --files backend frontend config migrations eval .github 2>/dev/null
```

High-risk path:

- ProviderAdapter / Provider Matrix / `provider_request_preflight`
- SecretBroker / `secret_ref` / capability token
- runner / tool registry / gateway
- `.github/workflows/**`
- migration / DB DDL
- audit / AgentRunEvent / approval

2. AI 出力直結を検出する。

```bash
rg -n "ai_output|generated_artifact|trusted_instruction|schema_validated|policy_linted|diff_ready|waiting_approval|approval_required|subprocess|os\.system|exec\(|eval\(|shell=True|sqlalchemy\.text|\.execute\(" backend frontend 2>/dev/null
rg -n "workflow|\.github/workflows|runner_mutation_gateway|tool_mutating_gateway_stub|RepoProxy|Draft PR|approval" backend frontend .github 2>/dev/null
```

BLOCK:

- AI 出力 command を shell に直接渡す
- AI 出力 SQL を DB / migration に直接適用する
- AI 出力 workflow を直接書き込む
- AI 出力 tool call を external mutating tool に直接渡す
- AI 出力 patch を `runner_mutation_gateway` / approval なしで適用する
- `approval_required` を人間承認なしの自動承認として扱う

3. Provider Compliance を確認する。

```bash
rg -n "payload_data_class|allowed_data_class|ProviderAdapter|provider_request_preflight|condition_status|training_use|retention|region_or_data_transfer|provider_blocked" backend frontend config 2>/dev/null
```

BLOCK:

- `payload_data_class` 未設定の provider call
- `payload_data_class` が optional の request model
- `allowed_data_class` を request body / UI / caller 引数から受け取る
- ordinal を string 比較する
- Matrix 行なし / enum 不正時に allow
- `payload_data_class > allowed_data_class` 後も provider へ送信する
- `provider_request_preflight` が provider call 後に実行される
- audit payload に raw prompt / raw secret / capability token 生値が入る

WARN:

- denial / downgrade reason_code が不足
- Matrix version / policy version が audit に残らない
- `training_use != no` の internal 以上送信 path が test で覆われていない

4. SecretBroker 境界を確認する。

```bash
rg -n "SecretBroker|secret_ref|secret_uri|capability|token_hash|expected_request_fingerprint|request_fingerprint|used_at|expires_at|for update|redeem|secret_value|raw_secret|get_secret" backend migrations config 2>/dev/null
```

BLOCK:

- DB column / model に raw secret 値保存用の列がある
- SecretBroker が secret 値を返す API になっている
- capability token 生値を DB / log / audit / artifact に保存する
- redeem が `check -> execute -> mark used` の逐次処理
- actor / run / expected_request_fingerprint / operation を同一 atomic claim で binding していない
- OperationContext fingerprint が caller-supplied
- canary / token / private key pattern を raw 値つきで出力する

WARN:

- TTL 5-30 分の enforcement が確認できない
- `secret_refs for update` 再検証がない
- substitution negative test がない

5. Runner / tool gateway の混同を確認する。

```bash
rg -n "tool_mutating_gateway_stub|runner_mutation_gateway|gateway_kind|forbidden_path|dangerous_command|resource_cap|runner_blocked|policy_blocked|runtime_blocked" backend config eval 2>/dev/null
```

BLOCK:

- `tool_mutating_gateway_stub` が書込を allow する
- `runner_mutation_gateway` を理由に external tool write を allow する
- gateway_kind がなく tool / runner を audit で区別できない
- forbidden path / dangerous command / resource cap を runner 前に確認しない
- `.env`, `.git/config`, secret material, workflow path への write を止めない
- runner stdout / stderr に raw secret / canary raw value が残る

6. Injection / redirection / SSRF / prompt injection を確認する。

```bash
rg -n "redirect|next=|return_url|urlparse|requests\.|httpx\.|fetch\(|openai|anthropic|gemini|prompt|untrusted_content|system_prompt|SQL|select .*\\+|format\\(|f\".*select|raw SQL" backend frontend 2>/dev/null
```

BLOCK:

- allowlist なしの redirect target
- user / AI 入力由来 URL への server-side fetch
- raw SQL string interpolation
- untrusted content を system / trusted instruction として扱う
- prompt injection fixture が権限昇格できる path
- MCP / tool context を trust tier なしで命令として扱う

WARN:

- URL allowlist が config 化されていない
- prompt / context の provenance が audit に残らない
- SSRF negative test がない

## 出力 contract

Markdown で返す。Findings は severity 別に BLOCK, WARN, INFO の順に並べる。

```markdown
## Security Review Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|specified-files
Depth: fast|deep

## BLOCK Findings
| file:line | boundary | issue | impact | required_fix | trace |
|---|---|---|---|---|---|

## WARN Findings
| file:line | boundary | issue | impact | suggested_fix | trace |
|---|---|---|---|---|---|

## Passed Controls
| control | evidence |
|---|---|

## Required Verification
- <negative test / fixture / audit check>
```

`boundary` は `AI Output`, `Provider`, `SecretBroker`, `Runner`, `Tool`, `Repo`, `DB`, `Audit`, `Injection`, `MCP` のいずれかを使う。

## 失敗時の挙動

- secret / token / private key / canary raw value を発見しても、値を再出力しない。`redacted pattern hit` と reason_code だけ書く。
- 対象 path が未作成なら WARN とし、未作成範囲を明記する。
- line 特定ができない grep hit は、Read で周辺を確認してから finding にする。
- AI 出力直結、raw secret 漏洩、approval bypass、provider preflight bypass、atomic claim 不備、gateway 混同は BLOCK。
- 外部仕様確認が必要な provider / MCP の項目は、未確認として WARN または BLOCK に倒す。

## TaskManagedAI 不変条件 trace

- AI Output Boundary: artifact -> schema_validated -> policy_linted -> diff_ready -> waiting_approval
- Provider Compliance: `payload_data_class` 必須、`allowed_data_class` Matrix 由来、ordinal 固定
- SecretBroker: raw secret 非保存、atomic claim、actor-run-fingerprint binding
- Gateway: `tool_mutating_gateway_stub` と `runner_mutation_gateway` の分離
- AC-HARD-01 `policy_block_recall`
- AC-HARD-02 `secret_canary_no_leak`
- AC-HARD-05 `forbidden_path_block`
- AC-HARD-06 `dangerous_command_block`
- AC-HARD-07 `prompt_injection_resist`

