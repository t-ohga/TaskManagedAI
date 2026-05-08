# Plan Review Rules

実装前計画のレビュー基準。  
Sprint Pack DoD、ADR Gate Criteria 11 種、Hard Gates 7、Quality KPIs 5、rollback / audit / Provider Matrix を必須確認する。

## 1. 入口条件

- すべての機能単位 Sprint は `docs/sprints/` の Sprint Pack を持つ。
- Sprint Pack がない場合は実装に入らず、light / heavy のどちらが必要か判断する。
- ADR Gate Criteria に該当する場合は heavy Pack と ADR を先に用意する。
- 緊急修正で先行した場合も 24h 以内に retro Pack / ADR を作成する。**ADR Gate Criteria 11 種は break-glass 対象外**で、緊急時でも先行不可（詳細は `sprint-pack-adr-gate.md` §10）。
- 計画レビューは「やること」だけでなく「やらないこと」と rollback を確認する。

## 2. Sprint Pack DoD

| 項目 | light | heavy |
|---|---:|---:|
| frontmatter `id` | 必須 | 必須 |
| frontmatter `type` | `light` | `heavy` |
| `status` | 必須 | 必須 |
| `sprint_no` | 必須 | 必須 |
| `target_days` / `max_days` | 必須 | 必須 |
| 目的 | 必須 | 必須 |
| 対象外 | 必須 | 必須 |
| 受け入れ条件 | 必須 | 必須 |
| 検証手順 | 必須 | 必須 |
| 残リスク | 必須 | 必須 |
| 背景 | 任意 | 必須 |
| 設計判断 | 任意 | 必須 |
| 実装チケット | 任意 | 必須 |
| must_ship / defer_if_over_budget | 任意 | 必須 |
| レビュー観点 | 任意 | 必須 |
| `adr_refs` | 原則不要 | 該当時必須 |
| rollback | 簡潔に記載 | 具体的に必須 |
| audit | 該当時記載 | 必須 |

## 3. ADR Gate Criteria 11 種

次に該当する変更は実装前 ADR が必須。

1. 認証・認可
2. DB schema
3. API 契約 / event schema
4. AI エージェント権限
5. MCP / tool 権限
6. Secrets 管理方式
7. 外部公開設定
8. 破壊的操作 / migration / tenant data 移行
9. 広範囲リファクタ
10. Provider 追加 / 切替 / Matrix 上限変更
11. GitHub App permission 変更

## 4. High-Risk 判定

- `tenant_id`、project boundary、複合 FK を触る。
- AgentRun 16 状態、`blocked_reason`、AgentRunEvent を触る。
- ContextSnapshot 必須 10 カラムを触る。
- ProviderAdapter、`payload_data_class`、`allowed_data_class`、data class ordinal を触る。
- `provider_request_preflight`、secret canary、ZDR 条件を触る。
- SecretBroker、`secret_ref`、capability token、atomic claim を触る。
- `tool_mutating_gateway_stub` または `runner_mutation_gateway` を触る。
- Tailscale Serve / SSH / grants / Funnel を触る。
- GitHub App permission、RepoProxy、Draft PR flow を触る。
- `.github/workflows/**`、migrations、backup / restore を触る。
- public ingress または external exposure を追加する。

## 5. Hard Gates 7

| ID | metric | 計画レビューで確認すること |
|---|---|---|
| AC-HARD-01 | `policy_block_recall` | 危険 action が 100% deny される fixture がある |
| AC-HARD-02 | `secret_canary_no_leak` | fake API key が provider / artifact / runner に漏れない |
| AC-HARD-03 | `tenant_isolation_negative_pass` | DB / app_role / 複合 FK の越境 negative test がある |
| AC-HARD-04 | `backup_restore_rpo_rto` | RPO <= 24h、RTO <= 4h、PITR drill を計画する |
| AC-HARD-05 | `forbidden_path_block` | `.env`, `.git/config`, secrets, migrations などを拒否する |
| AC-HARD-06 | `dangerous_command_block` | dangerous command を Runner が拒否する |
| AC-HARD-07 | `prompt_injection_resist` | untrusted_content の権限昇格を拒否する |

## 6. Quality KPIs 5

| ID | metric | 閾値 | 計画レビューで確認すること |
|---|---|---:|---|
| AC-KPI-01 | `acceptance_pass_rate` | >= 0.6 | Acceptance Criteria と EvalResult が接続される |
| AC-KPI-02 | `time_to_merge` | median <= 2.0h | mock merge / Draft PR flow の timestamp がある |
| AC-KPI-03 | `approval_wait_ms` | median <= 4h | requested_at / decided_at が記録される |
| AC-KPI-04 | `citation_coverage` | >= 0.9 | claim / evidence / citation が保存される |
| AC-KPI-05 | `cost_per_completed_task` | <= $0.5 | BudgetGuard と provider usage が接続される |

## 7. 計画レビュー Checklist

### Scope

- [ ] P0 scope / out-of-scope と矛盾しない。
- [ ] must_ship と defer_if_over_budget が明確。
- [ ] target_days / max_days を超えた時の切り分けがある。
- [ ] 変更対象ファイルと影響範囲が書かれている。

### Data / API

- [ ] PostgreSQL tenant / project invariant を壊さない。
- [ ] actor / principal / self-approval 禁止を確認した。
- [ ] API 契約変更は ADR と OpenAPI 更新がある。
- [ ] migration rollback と backup 方針がある。

### AI Boundary

- [ ] AI 出力が command / SQL / workflow / external tool へ直結しない。
- [ ] artifact -> schema validation -> policy lint -> diff_ready -> approval の流れがある。
- [ ] `tool_mutating_gateway_stub` と `runner_mutation_gateway` を区別している。
- [ ] AgentRun 16 状態と terminal state が維持される。
- [ ] ContextSnapshot 10 カラムが維持される。

### Provider / Secret

- [ ] `payload_data_class` は必須、`allowed_data_class` は Matrix からのみ解決。
- [ ] data class ordinal `public < internal < confidential < pii` を使う。
- [ ] conditional ZDR は `condition_status=verified` が条件。
- [ ] `provider_request_preflight` が provider call 前にある。
- [ ] `secret_ref`、capability token、atomic claim を壊さない。
- [ ] raw secret が DB / prompt / runner / artifact / log に出ない。

### Verification / Audit

- [ ] unit / contract / E2E / Eval の検証コマンドがある。
- [ ] Hard Gate fixture と Quality KPI の trace がある。
- [ ] audit event の event_type / actor / run / correlation が定義されている。
- [ ] failure / retry / cancel / resume の扱いがある。
- [ ] rollback 後の検証手順がある。

## 8. Readiness 判定

| 判定 | 条件 | 次アクション |
|---|---|---|
| READY | ADR 不要、または ADR / Pack / 検証が揃う | 実装可 |
| NEEDS_PACK | Sprint Pack がない / 不足 | Pack 作成 |
| NEEDS_ADR | Criteria 11 種に該当 | ADR 作成 |
| BLOCKED | rollback / audit / Provider / Secret 不明 | ユーザー確認 |
| DEFER | P0 must_ship ではない、max_days 超過 | P0.1 / P1 へ移送 |

