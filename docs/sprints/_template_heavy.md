---
id: "SP-000_<feature-name>"
type: "heavy"
status: "draft"
sprint_no: 0
created_at: "<date>"
updated_at: "<date>"
target_days: 0
max_days: 0
adr_refs:
  - "[ADR-00001](../adr/00001_auth_rbac.md) # accepted 化済 ADR を列挙。Sprint 着手時点で proposed 以上の ADR は planned_adr_refs に置き、accepted 化後にこちらへ移動"
planned_adr_refs:
  - "[ADR-NNNNN](../adr/NNNNN_<title>.md) # 当該 Sprint で proposed 化する ADR (実装前 proposed → 実装後 accepted)。Criteria #N (例: #2 DB schema) を明記"
related_sprints:
  - "SP-000_<related-feature>"
risks:
  - "<risk-id-or-summary>"
---

このテンプレの使い方: 権限 / 実行 / 外部連携など ADR Gate Criteria に該当する Sprint に使う。実装前に ADR を作成し、この Pack では実装範囲、検証、レビュー観点、defer 判断を管理する。

最終更新: <date>

## 目的

<!-- 記入ガイド: この Sprint で出荷する最小単位を書く。P0 Exit に直結する must_ship を優先する。 -->

- <この Sprint の目的>

## 背景

<!-- 記入ガイド: なぜ今この Sprint が必要かを書く。関連する設計文書や ADR があればリンクする。 -->

- <背景>

## 対象外

<!-- 記入ガイド: 今回やらないこと、target_days 超過時に P0.1 / P1 へ送る候補を書く。 -->

- <対象外 1>
- <対象外 2>

## 設計判断

<!-- 記入ガイド: 実装者が迷う判断だけを書く。ADR がある判断はここに要約し、詳細は ADR に寄せる。 -->

- <判断 1>: <理由>
- <判断 2>: <理由>

## 実装チケット

<!-- 記入ガイド: TaskManagedAI 上の ticket / issue / Gold Task への参照を置く。secret / token / 個人情報は含めない。 -->

- <ticket-id-or-title>: <概要>

## タスク一覧

<!-- 記入ガイド: 小さく検証可能な単位に分ける。高リスク作業は policy / validation / audit / rollback を分けて書く。 -->

- [ ] <task 1>
- [ ] <task 2>
- [ ] <task 3>

## must_ship / defer_if_over_budget 対応表

<!-- 記入ガイド: 対象 Sprint の行だけ残して使う。target_days を超過したら defer_if_over_budget を P0.1 または P1 へ送り、この Pack を更新する。 -->

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 0 | 4.7 | 6 | ネットワーク境界設計 (`tag:taskhub-ci` grants 含む) / secret_ref 仕様 + SecretBroker atomic claim contract / Worker 確定 / Gold Task Seed v0 (`payload_data_class` 必須) / Provider Compliance Matrix v2 (機械判定 enum) / Sprint Pack テンプレ / ADR 4 件 proposed | observability dashboard / PITR drill / private staging 本運用 |
| Sprint 1 | 4 | 6 | docker compose 起動 / CI smoke / dev login / 最小 admin UI | UI のスタイル本格化 |
| Sprint 2 | 5 | 7 | tenant_id invariant / 複合 FK / 越境 negative test / actors-principals schema | カスタムフィールド / テンプレート |
| Sprint 3 | 5 | 7 | action class 7 種 / 初期 policy matrix / Approval Inbox vertical slice / In-App Notification 最小 | analytics |
| Sprint 4 | 6 | 9 | AgentRun 16 状態 / blocked サブ 3 / ContextSnapshot 10 カラム / BudgetGuard hierarchy / state contract test | replay UI / span export |
| Sprint 4.5 | 3 | 5 | tool_registry / transport=local\|stdio 限定 / trust_tier 機械判定 / read-only gateway / `tool_mutating_gateway_stub` deny-only | 書込系 MCP / 外部 tool gateway 本格化（P1） |
| Sprint 5 | 4 | 6 | Mock + OpenAI + Claude + Gemini adapter の structured output / budget exceeded 試験 | bake-off 詳細比較 |
| Sprint 5.5 | 4 | 6 | Output Validator / Input Trust Layer / repair retry policy | dangerous intent classifier 高度化 |
| Sprint 6 | 3 | 5 | CLI artifact subprocess / stdout 追跡 | Codex App Server / Remote Control adapter |
| Sprint 7 | 5 | 7 | Docker isolated runner / forbidden path / resource cap / `runner_mutation_gateway` 完成 | runner orchestrator 高度化 |
| Sprint 8 | 5 | 7 | GitHub App / RepoProxy / Permission Matrix / Draft PR 作成 / CI 取得 | webhook UX 強化 |
| Sprint 9 | 6 | 9 | Ticket / Approval / Run / Audit / Settings の本実装 | アナリティクス drill-down |
| Sprint 10 | 5 | 7 | Claim/Evidence 正規化 / provenance_json | conflict_group_id / source trust registry |
| Sprint 11 | 4 | 6 | 6 領域 Eval / Quality KPI 計測 / Anti-Gaming Rules | 自動再分解 |
| Sprint 11.5 | 4 | 6 | OTel / Prom / Loki / Grafana dashboard / alerting / private staging 本運用 / secret rotation drill | SLO 自動化 |
| Sprint 12 | 4 | 6 | P0 Acceptance Test / Backup-Restore drill / 越境 negative / secret canary | shadow mode |

## 受け入れ条件

<!-- 記入ガイド: policy block、deny-by-default、監査ログ、短命 token、秘密情報非露出など、該当する境界条件を観測可能な形で書く。 -->

- [ ] <条件 1>
- [ ] <条件 2>
- [ ] <条件 3>

## 検証手順

<!-- 記入ガイド: test / typecheck / lint / migration check / negative test / smoke / 手動確認を書く。未確認が残る場合は理由を書く。 -->

- [ ] `<command-or-manual-check>`
- [ ] `<command-or-manual-check>`
- [ ] `<command-or-manual-check>`

## レビュー観点

<!-- 記入ガイド: 実装後の自己レビューと Claude レビューで見る観点を書く。高リスク領域は rollback と監査性も見る。 -->

- [ ] 権限境界が deny-by-default になっている
- [ ] 外部入力が検証され、AI 出力が直接 command / SQL / workflow / external tool 操作へ接続されていない
- [ ] 監査ログ、エラー、失敗時の状態遷移が確認できる
- [ ] 関連 ADR と実装が乖離していない

## 残リスク

<!-- 記入ガイド: Sprint 完了時点で残るリスクを書く。回避策、検知方法、次に扱う Sprint も添える。 -->

- <risk>: <mitigation-or-next-sprint>

## 次スプリント候補

<!-- 記入ガイド: defer した項目、今回の実装で見えた次の最小 Sprint 候補を書く。 -->

- <candidate>

## 関連 ADR

<!-- 記入ガイド: ADR Gate Criteria に該当する判断をリンクする。形式は [ADR-00001](../adr/00001_<title>.md)。不要な例は削除する。 -->

- [ADR-00001](../adr/00001_<title>.md): <判断の概要>

## Review

<!-- 記入ガイド: Sprint 完了後に追記する。各項目 1-3 行で十分。 -->

- changed: <実際に変えたこと>
- verified: <確認したこと>
- deferred: <後回しにしたこと>
- risks: <残ったリスク>
