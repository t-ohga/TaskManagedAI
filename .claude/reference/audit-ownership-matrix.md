# Audit Ownership Matrix

Hard Gates、ADR Gate、OWASP LLM Top 10、NIST AI RMF の owner skill / agent / hook 対応表。  
P0 で誰が何を見るかを固定し、監査漏れを防ぐための参照資料。

## 1. Owner 種別

| owner 種別 | 例 | 役割 |
|---|---|---|
| skill | `provider-compliance-audit` | 手順化された audit |
| agent | `provider-compliance-reviewer` | 専門視点レビュー |
| hook | `provider/check-payload-data-class.sh` | 軽量自動検出 |
| fixture | `eval/security/*` | 再現可能な検証 |
| docs | Sprint Pack / ADR | 判断根拠 |
| test | pytest / Vitest / Playwright | 実行可能検証 |

## 2. Hard Gates 7

**注**: hook は軽量自動ガード（補助、ファイル変更時の fixture 更新促し / DDL 整合補助）。Hard Gate の最終判定は **fixture-based eval** が正本。

| AC | metric | owner skill | owner agent | hook (補助) | fixture path (判定の正本) |
|---|---|---|---|---|---|
| AC-HARD-01 | `policy_block_recall` | `security-suite` | `security-specialist` | none / eval-only | `eval/security/policy_block/*` |
| AC-HARD-02 | `secret_canary_no_leak` | `hard-gate-fixture-create` | `security-specialist` | `secretbroker/check-secretbroker-ddl.sh` | `eval/security/secret_canary/*` |
| AC-HARD-03 | `tenant_isolation_negative_pass` | `postgres-boundary-audit` | `tenant-project-isolation-reviewer` | `postgres/check-tenant-boundary-ddl.sh` | `eval/security/tenant_isolation/*` |
| AC-HARD-04 | `backup_restore_rpo_rto` | `release-suite` | `release-auditor` | none / eval-only | `eval/ops/backup_restore/*` |
| AC-HARD-05 | `forbidden_path_block` | `runner-gateway-audit` | `runner-security-reviewer` | `runner/check-dangerous-command-fixture.sh` | `eval/security/forbidden_path/*` |
| AC-HARD-06 | `dangerous_command_block` | `runner-gateway-audit` | `runner-security-reviewer` | `runner/check-dangerous-command-fixture.sh` | `eval/security/dangerous_command/*` |
| AC-HARD-07 | `prompt_injection_resist` | `security-suite` | `security-specialist` | none / eval-only | `eval/security/prompt_injection/*` |

## 3. Quality KPIs 5

| AC | metric | owner skill | owner agent | data source |
|---|---|---|---|---|
| AC-KPI-01 | `acceptance_pass_rate` | `quality-suite` | `release-auditor` | Acceptance Criteria / EvalResult |
| AC-KPI-02 | `time_to_merge` | `release-suite` | `release-auditor` | Ticket / Draft PR timestamps |
| AC-KPI-03 | `approval_wait_ms` | `quality-suite` | `actor-binding-reviewer` | approval_requests |
| AC-KPI-04 | `citation_coverage` | `quality-suite` | `code-reviewer` | claims / evidence / citations |
| AC-KPI-05 | `cost_per_completed_task` | `quality-suite` | `provider-compliance-reviewer` | AgentRun cost / BudgetGuard |

## 4. ADR Gate Criteria Owner

| Criteria | owner skill | owner agent | hook |
|---|---|---|---|
| 認証・認可 | `adr-create` | `actor-binding-reviewer` | `adr/check-adr-gate.sh` |
| DB schema | `postgres-boundary-audit` | `postgres-specialist` | `postgres/check-tenant-boundary-ddl.sh` |
| API 契約 / event schema | `review-suite` | `code-reviewer` | `adr/check-adr-gate.sh` |
| AI エージェント権限 | `security-suite` | `security-specialist` | `adr/check-adr-gate.sh` |
| MCP / tool 権限 | `runner-gateway-audit` | `runner-security-reviewer` | `adr/check-adr-gate.sh` |
| Secrets 管理方式 | `atomic-claim-validator` | `security-specialist` | `secretbroker/check-secretbroker-ddl.sh` |
| 外部公開設定 | `security-suite` | `release-auditor` | `tailscale/check-tailscale-grants.sh` |
| 破壊的操作 | `release-suite` | `release-auditor` | `adr/check-adr-gate.sh` |
| 広範囲リファクタ | `review-suite` | `plan-reviewer` | `adr/check-adr-gate.sh` |
| Provider 追加 / 切替 | `provider-compliance-audit` | `provider-compliance-reviewer` | `provider/check-payload-data-class.sh` |
| GitHub App permission | `security-suite` | `security-specialist` | `adr/check-adr-gate.sh` |

## 5. OWASP LLM Top 10 Mapping

| OWASP LLM category | TaskManagedAI control | owner |
|---|---|---|
| Prompt Injection | Input Trust Layer、untrusted_content、AC-HARD-07 | `security-specialist` |
| Sensitive Information Disclosure | SecretBroker、`secret_ref`、canary、ZDR | `security-specialist` |
| Supply Chain | Provider Matrix、Tool Registry、dependency audit | `provider-compliance-reviewer` |
| Data and Model Poisoning | Eval fixture separation、Anti-Gaming | `hard-gate-fixture-reviewer` |
| Improper Output Handling | Output Validator、schema validation、AI direct 禁止 | `code-reviewer` |
| Excessive Agency | action class、approval、tool deny-by-default | `security-specialist` |
| System Prompt Leakage | prompt pack lock、ContextSnapshot redaction | `agentrun-state-reviewer` |
| Vector / Embedding Weakness | P0 defer、evidence hash 管理 | `code-reviewer` |
| Misinformation | Claim / Evidence、citation coverage | `release-auditor` |
| Unbounded Consumption | BudgetGuard、max retries、cost KPI | `provider-compliance-reviewer` |

## 6. NIST AI RMF Mapping

| Function | TaskManagedAI practice | owner |
|---|---|---|
| Govern | Sprint Pack、ADR、Provider Matrix | `plan-reviewer` |
| Map | data class ordinal、threat model、action class | `security-specialist` |
| Measure | Eval Harness、Hard Gates、KPIs | `release-auditor` |
| Manage | policy decision、approval、rollback、audit | `release-auditor` |

## 7. SSDF / Secure Design Mapping

| Practice | TaskManagedAI control | owner |
|---|---|---|
| secure design | deny-by-default、ADR Gate | `security-specialist` |
| implementation review | code-reviewer、typecheck、lint | `code-reviewer` |
| verification | pytest / Vitest / Playwright / Eval | `tdd-orchestrator` |
| supply chain | dependency review、Provider docs | `provider-compliance-reviewer` |
| vulnerability response | audit event、rollback、Sprint Review | `release-auditor` |

## 8. Audit Event Owner

| event_type | owner | verification |
|---|---|---|
| `policy_decision_created` | `security-specialist` | policy contract test |
| `approval_requested` | `actor-binding-reviewer` | approval flow test |
| `approval_decided` | `actor-binding-reviewer` | self-approval negative |
| `provider_requested` | `provider-compliance-reviewer` | provider contract |
| `provider_blocked` | `provider-compliance-reviewer` | preflight negative |
| `secret_capability_issued` | `security-specialist` | SecretBroker test |
| `secret_capability_redeemed` | `security-specialist` | atomic claim test |
| `secret_capability_denied` | `security-specialist` | mismatch tests |
| `runner_blocked` | `runner-security-reviewer` | forbidden / dangerous fixtures |
| `run_completed` | `agentrun-state-reviewer` | state contract |
| `run_failed` | `agentrun-state-reviewer` | failure mapping |
| `run_cancelled` | `agentrun-state-reviewer` | cancellation test |

## 9. Fixture Ownership

| fixture kind | owner | anti-gaming rule |
|---|---|---|
| `public_regression` | `quality-suite` | 開発中に参照可 |
| `private_holdout` | `release-suite` | 期待値を見て prompt / policy 調整しない |
| `adversarial_new` | `security-suite` | 月次 append-only |
| `private_gold_task` | `release-auditor` | P0 Exit 30-50 件 |
| `provider_bakeoff` | `provider-compliance-reviewer` | provider matrix version を保存 |

## 10. Review Checklist

- [ ] Hard Gate に owner skill / agent / hook / fixture がある。
- [ ] KPI に data source と dashboard metric がある。
- [ ] ADR Criteria 11 種の owner がある。
- [ ] Provider / Secret / AgentRun / DB boundary の owner が明確。
- [ ] fixture が public / private / adversarial に分離されている。
- [ ] audit event payload に raw secret がない。
- [ ] owner が不明な領域は Sprint Pack の残リスクに記録する。

