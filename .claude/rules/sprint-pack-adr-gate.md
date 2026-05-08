# Sprint Pack / ADR Gate

Sprint Pack と ADR Gate Criteria を実装前の必須ゲートとして扱うルール。  
light / heavy frontmatter、ADR Criteria 11 種、high-risk 判定、DoD を固定する。

## 1. 原則

- 機能単位 Sprint は実装前に Sprint Pack を持つ。
- Sprint Pack は `docs/sprints/` に置く。
- ADR Gate Criteria に該当する Sprint は heavy Pack を使う。
- ADR は `docs/adr/` に置く。
- Pack と ADR は機密情報、実 token、個人情報を含めない。
- 実装後は Review 欄を更新する。
- Sprint Pack はタスク管理の代替ではなく、実装前ゲートである。

## 2. Light Pack Frontmatter

```yaml
---
id: "SP-000_<feature-name>"
type: "light"
status: "draft"
sprint_no: 0
created_at: "YYYY-MM-DD"
updated_at: "YYYY-MM-DD"
target_days: 0
max_days: 0
---
```

必須本文:

- 目的
- 対象外
- 受け入れ条件
- 検証手順
- 残リスク
- Review

## 3. Heavy Pack Frontmatter

```yaml
---
id: "SP-000_<feature-name>"
type: "heavy"
status: "draft"
sprint_no: 0
created_at: "YYYY-MM-DD"
updated_at: "YYYY-MM-DD"
target_days: 0
max_days: 0
adr_refs:
  - "[ADR-00001](../adr/00001_example.md)"
related_sprints:
  - "SP-000_<related-feature>"
risks:
  - "<risk-id-or-summary>"
---
```

必須本文:

- 目的
- 背景
- 対象外
- 設計判断
- 実装チケット
- タスク一覧
- must_ship / defer_if_over_budget 対応表
- 受け入れ条件
- 検証手順
- レビュー観点
- 残リスク
- 次スプリント候補
- 関連 ADR
- Review

## 4. ADR Gate Criteria 11 種

| # | Criteria | 例 |
|---:|---|---|
| 1 | 認証・認可 | dev login、actor binding、RBAC |
| 2 | DB schema | table、FK、index、RLS-ready、migration |
| 3 | API 契約 / event schema | FastAPI endpoint、OpenAPI、AgentRunEvent |
| 4 | AI エージェント権限 | action class、approval、trusted_instruction |
| 5 | MCP / tool 権限 | Tool Registry、transport、trust_tier |
| 6 | Secrets 管理方式 | SecretBroker、`secret_ref`、capability token |
| 7 | 外部公開設定 | Tailscale Funnel、public bind、Cloudflare |
| 8 | 破壊的操作 | migration、data move、delete、rollback |
| 9 | 広範囲リファクタ | 複数 bounded context / shared contract |
| 10 | Provider 追加 / 切替 | ProviderAdapter、Matrix 上限変更 |
| 11 | GitHub App permission | installation permission、RepoProxy scope |

## 5. High-Risk 該当判定

以下を含む変更は high-risk として heavy Pack + ADR を要求する。

- `tenant_id`、project boundary、複合 FK。
- actors / principals / self-approval。
- `agent_runs.status`、`blocked_reason`、AgentRunEvent。
- ContextSnapshot 必須 10 カラム。
- Provider Compliance Matrix、data class ordinal。
- `payload_data_class` / `allowed_data_class`。
- `provider_request_preflight`。
- SecretBroker、`secret_ref`、atomic claim。
- `tool_mutating_gateway_stub`。
- `runner_mutation_gateway`。
- forbidden path / dangerous command。
- Tailscale grants / Funnel / public ingress。
- GitHub App permission。
- `.github/workflows/**`。
- backup / restore / PITR。
- Eval private holdout / anti-gaming。

## 6. ADR 必須内容

ADR は 1-2 ページを目安に、次を含める。

- 背景
- 決定対象
- 関連 Sprint
- 前提 / 制約
- 選択肢
- 採用案
- 却下案
- リスク
- rollback 手順
- 実装対象ファイル
- テスト指針

## 7. Sprint Pack Review DoD

- [ ] P0 scope と矛盾しない。
- [ ] must_ship と defer_if_over_budget がある。
- [ ] 受け入れ条件が観測可能。
- [ ] 検証手順が実行可能。
- [ ] rollback が現実的。
- [ ] audit event が定義されている。
- [ ] high-risk なら ADR がある。
- [ ] Provider Matrix / SecretBroker / AgentRun / DB invariant への影響が書かれている。
- [ ] Hard Gates / Quality KPIs への trace がある。
- [ ] Review 欄の更新タイミングが決まっている。

## 8. Provider / Secret 特則

- Provider 追加 / 切替は ADR-00010 系の判断を要求する。
- `allowed_data_class` 引き上げは ADR 必須。
- `condition_status=verified` への変更は根拠と `last_verified_at` を要求する。
- `store:false` を ZDR 相当に扱う例外は ADR 必須。
- SecretBroker の operation 追加は allowed_operations / allowed_consumers / audit を確認する。
- capability token TTL 変更は ADR 必須。
- raw secret を返す interface は reject。

## 9. DB / Runner 特則

- DB schema 変更は migration rollback と negative test が必須。
- tenant / project invariant を壊す変更は reject。
- migration に destructive operation がある場合は backup / restore 手順を書く。
- runner に command 実行を追加する場合は dangerous command fixture を追加する。
- forbidden path allowlist / denylist の変更は AC-HARD-05 に trace する。
- `runner_mutation_gateway` bypass は reject。

## 10. Break-Glass 例外運用

実装前 ADR は **原則必須**。緊急修正で先行する場合は、以下すべてを満たす場合のみ:

- ユーザー承認が事前に取れている。
- 最小 patch に限定する（影響範囲を 1-2 ファイルに絞る）。
- rollback 手順を patch 適用前に決めておく。
- 監査記録（actor / timestamp / scope / rationale）を確実に残す。
- 24h 以内に retro Pack / ADR を作成し、`proposed` で開始 → 通常レビューを経て `accepted` 化。
- retro docs に「なぜ先行したか」「何を検証したか」「残リスク」「次の rollback 条件」を書く。
- 例外を恒常化しない（同種の break-glass が 2 回続いた場合は仕組みを見直す）。

### Break-Glass の対象外 (常に実装前 ADR 必須、先行不可)

ADR Gate Criteria 11 種**すべて**が対象外。緊急時でも break-glass を許可しない:

1. 認証・認可、Auth/RBAC 変更
2. DB schema（特に tenant_id / RLS / 複合 FK / project 境界）の変更
3. API 契約（versioned REST / event schema）の変更
4. AI エージェント権限、tool registry の trust_tier 変更
5. MCP / tool 権限、scope 変更
6. Secrets 管理方式（SOPS → Vault 等）の変更
7. 外部公開（Tailscale Serve → Funnel / Cloudflare 等）の変更
8. 破壊的操作（migration、tenant データ移行）
9. 広範囲リファクタ（5+ ファイル横断、API 契約変更を伴う）
10. Provider 追加 / 切替
11. GitHub App permission 変更

事故時は **rollback を優先**、ADR は通常レビューで作成する。これらは P0 全体の安全性・データ整合性に直結する。

## 11. 完了条件

- [ ] Pack の区分が light / heavy として妥当。
- [ ] heavy で `adr_refs` が空ではない。
- [ ] Criteria 11 種の該当有無を明記した。
- [ ] rollback / audit / verification が揃う。
- [ ] P0 Hard Gates / KPIs と trace できる。
- [ ] 実装後 Review 欄を更新する。

