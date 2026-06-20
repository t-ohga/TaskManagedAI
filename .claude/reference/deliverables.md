# Deliverables

TaskManagedAI P0 の成果物一覧。  
`docs/sprints`, `docs/adr`, `docs/要件定義`, `docs/基本設計`, `docs/実装計画`, `eval` fixtures を正本として扱う。

## 1. Deliverable Map

| 分類 | path | 役割 |
|---|---|---|
| PRD | `docs/要件定義/` | product / P0 requirements |
| DD | `docs/基本設計/` | architecture / data / security design |
| Plan | `docs/実装計画/` | backlog / sprint 展開 |
| Sprint Pack | `docs/sprints/` | 実装前 gate |
| ADR | `docs/adr/` | high-risk decision |
| Eval | `eval/` | Hard Gates / KPIs |
| Config | `config/` | Provider Matrix / policy / runner |
| Migration | `migrations/` | PostgreSQL schema |
| Harness | `.claude/`, `.codex/` | AI 開発支援 harness |

## 2. Requirements Docs

| file | 内容 |
|---|---|
| `docs/要件定義/00_プロダクト要求定義.md` | product vision / users / principles |
| `docs/要件定義/01_P0要求定義.md` | F-001〜F-020+OPS、NF-001〜012、Hard Gates、KPIs |

DoD:

- P0 scope と out-of-scope が明確。
- Hard Gates 7 と Quality KPIs 5 が定義済み。
- Provider Compliance / SecretBroker / AgentRun への trace がある。
- 個人 P0 と将来 commercial readiness の境界が書かれている。

## 3. Basic Design Docs

| file | 内容 |
|---|---|
| `00_全体アーキテクチャ.md` | FastAPI / Next.js / PostgreSQL / Redis / Tailscale |
| `02_データモデル.md` | tenant / project invariant、actors、AgentRun、SecretBroker |
| `03_AIオーケストレーション設計.md` | AgentRun 16 状態、ContextSnapshot 10 カラム |
| `04_セキュリティ_権限_監査設計.md` | Provider Matrix、policy、approval、Hard Gates |
| `06_秘密管理設計.md` | secret backend (local/sops、ADR-00058)、SecretBroker、atomic claim |

DoD:

- DB invariant と API / service boundary が追える。
- SecretBroker は raw secret 非保存。
- Provider Matrix は data class ordinal を持つ。
- AgentRun / ContextSnapshot は再現性 contract を持つ。
- audit event が設計されている。

## 4. Sprint Packs

| file | 役割 |
|---|---|
| `docs/sprints/_template_light.md` | 低リスク Sprint template |
| `docs/sprints/_template_heavy.md` | ADR Gate 対象 Sprint template |
| `docs/sprints/SP-000_bootstrap.md` | bootstrap sprint |

Light Pack DoD:

- frontmatter が揃う。
- 目的、対象外、受け入れ条件、検証手順、残リスクがある。
- 最大 1 ページ程度で判断可能。
- ADR Gate Criteria に該当しない。

Heavy Pack DoD:

- frontmatter に `adr_refs` がある。
- 背景、設計判断、実装チケット、タスク一覧がある。
- must_ship / defer_if_over_budget がある。
- rollback / audit / verification がある。
- 関連 ADR がある。

## 5. ADR

| path | 役割 |
|---|---|
| `docs/adr/_template.md` | ADR template |
| `docs/adr/README.md` | ADR index |
| `docs/adr/000NN_<title>.md` | decision record (例: `00001_auth_rbac.md` / `00006_secrets_management.md` / `00007_external_exposure.md` / `00010_provider_change.md`、5 桁番号 + slug) |

ADR DoD:

- 背景。
- 選択肢。
- 採用案。
- 却下案。
- リスク。
- rollback 手順。
- related sprint。
- implementation target。
- test guidance。
- status は `proposed` から `accepted` へ更新可能。

## 6. ADR Gate Criteria Deliverables

| Criteria | 必須成果物 |
|---|---|
| 認証・認可 | ADR、actor / principal test |
| DB schema | ADR、migration、rollback、negative test |
| API 契約 | ADR、OpenAPI / contract test |
| AI 権限 | ADR、policy / approval test |
| MCP / tool | ADR、Tool Registry / deny fixture |
| Secrets | ADR、SecretBroker contract test |
| 外部公開 | ADR、network rollback |
| 破壊的操作 | ADR、backup / restore plan |
| 広範囲リファクタ | ADR、migration path / compatibility |
| Provider | ADR、Matrix update、provider contract |
| GitHub App permission | ADR、permission matrix、RepoProxy test |

## 7. Eval Fixtures

| path | 目的 |
|---|---|
| `eval/security/policy_block/*` | AC-HARD-01 |
| `eval/security/secret_canary/*` | AC-HARD-02 |
| `eval/security/tenant_isolation/*` | AC-HARD-03 |
| `eval/ops/backup_restore/*` | AC-HARD-04 |
| `eval/security/forbidden_path/*` | AC-HARD-05 |
| `eval/security/dangerous_command/*` | AC-HARD-06 |
| `eval/security/prompt_injection/*` | AC-HARD-07 |
| `eval/quality/acceptance/*` | AC-KPI-01 |
| `eval/quality/citation/*` | AC-KPI-04 |
| `eval/quality/cost/*` | AC-KPI-05 |

Fixture DoD:

- fixture ID。
- dataset version。
- fixture kind。
- expected outcome。
- source / evidence reference。
- no secret / token / PII。
- append-only update。
- public / private / adversarial separation。

## 8. Config Deliverables

| file | 内容 |
|---|---|
| `config/provider_compliance.toml` | Provider Compliance Matrix |
| `config/policy/policy_pack.toml` | policy matrix |
| `config/prompts/prompt_pack.toml` | prompt pack |
| `config/runner/forbidden_paths.toml` | forbidden path |
| `config/runner/dangerous_commands.toml` | dangerous command |
| `config/tailscale/grants.example.json` | grants example |

DoD:

- TOML は schema validation できる。
- secret 値を含まない。
- `allowed_data_class` は Matrix のみ。
- data class ordinal は docs と一致。
- forbidden path は AC-HARD-05 と同期。
- dangerous command は AC-HARD-06 と同期。

## 9. Migration Deliverables

必須:

- migration file。
- rollback 手順。
- DB contract test。
- tenant / project negative test。
- SecretBroker / AgentRun / ContextSnapshot contract test。
- Alembic check。
- backup / restore consideration。

禁止:

- raw secret column。
- tenant_id なし主要 table。
- cross-project FK。
- AgentRun status enum drift。
- ContextSnapshot 10 カラム欠落。

## 10. Harness Deliverables

| path | 成果物 |
|---|---|
| `.claude/rules/` | 12 rules |
| `.claude/reference/` | 13 references |
| `.claude/agents/` | reviewer agents |
| `.claude/hooks/` | P0 hard gate hooks |
| `.claude/skills/` | suites / domain skills |
| `.codex/agents/` | necessary Codex mirrors |
| `.codex/hooks.json` | executable Codex hooks |

DoD:

- inventory 更新。
- routing 更新。
- owner matrix 更新。
- Claude-only 前提なし。
- shell hook 実行可能。
- read-only / workspace-write の差分を理解している。

## 11. Review Record

Sprint 完了後に Pack の Review を更新する。

```md
## Review

- changed: <実際に変えたこと>
- verified: <確認したこと>
- deferred: <後回しにしたこと>
- risks: <残ったリスク>
```

## 12. 完了条件

- [ ] 成果物が正しい path にある。
- [ ] PRD / DD / Sprint Pack / ADR の trace がある。
- [ ] Hard Gates / KPIs への trace がある。
- [ ] secret / token / 個人情報を含まない。
- [ ] Provider / Secret / AgentRun / DB invariant を壊していない。
- [ ] 実装後 Review が更新される。

