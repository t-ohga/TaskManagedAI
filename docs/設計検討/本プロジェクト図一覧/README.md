# 本プロジェクト図一覧

TaskManagedAI を理解するための Draw.io 図面集です。1枚で全部を説明するのではなく、目的ごとに認知負荷を分けています。

## 読む順番

1. `01_product_overview.drawio` - このプロダクトが何を解決するか
2. `02_user_golden_flow.drawio` - ユーザーがどう使うか
3. `04_p0_architecture.drawio` - P0 のシステム構成
4. `05_ticket_to_pr_sequence.drawio` - Ticket から Draft PR までの時間順処理
5. `08_agentrun_state_machine.drawio` - AI 実行状態の正本
6. `06_data_flow_trust_boundaries.drawio` / `10_tool_mcp_boundary.drawio` - AI と外部接続の安全境界
7. `07_er_overview.drawio` - DB の大きな関係
8. `11_deployment_network.drawio` / `12_p0_sprint_roadmap.drawio` - 運用と実装順序
9. `09_agent_orchestration.drawio` - P0.1+ の multi-agent 構想

各図の灰色ノートには、必ず「この図でわかること」「誤解しないこと」「正本」を入れています。まず灰色ノートを読んでから、箱と矢印を追ってください。

## 凡例

| 表記 | 意味 |
|---|---|
| P0実装 | P0 完了に必要な実装範囲 |
| P0構造準備 | P0 で schema / interface / gate を準備し、フル機能は後続 |
| P0 deny | P0 では明示的に拒否する操作 |
| P0.1+ | P0 完了後に扱うロードマップ |
| P1以降 | 将来拡張 |
| 正本 | PRD / DD / ADR / roadmap の設計正本 |
| 補助 | 採用済みの設計検討資料。defer / reject 項目は P0 実装扱いしない |

## 図面一覧

| File | Scope | 目的 |
|---|---|---|
| `01_product_overview.drawio` | P0 overview | Deep Research から Draft PR / Eval / Audit までの全体像 |
| `02_user_golden_flow.drawio` | P0実装 | Ticket / Research 作成から承認、実行、評価まで |
| `03_use_case_and_roles.drawio` | P0実装 + P0構造準備 | Human / Service / Agent / Provider / GitHub App の責務 |
| `04_p0_architecture.drawio` | P0実装 | host-portable な P0 アーキテクチャ |
| `05_ticket_to_pr_sequence.drawio` | P0実装 | Ticket から Draft PR までの sequence |
| `06_data_flow_trust_boundaries.drawio` | P0実装 | trusted / untrusted / provider compliance / audit |
| `07_er_overview.drawio` | P0実装 + P0構造準備 | 主要 DB entity と関係 |
| `08_agentrun_state_machine.drawio` | P0実装 | AgentRun 16 状態 + blocked_reason 3 種 |
| `09_agent_orchestration.drawio` | P0.1+ roadmap | Multi-agent foundation と role/capability 分離 |
| `10_tool_mcp_boundary.drawio` | P0実装 + P0 deny + P0.1/P1 | Tool / MCP / Runner / Remote Agent の境界 |
| `11_deployment_network.drawio` | P0実装 | Tailscale 閉域、host-portable、backup/migration |
| `12_p0_sprint_roadmap.drawio` | P0 roadmap + P0.1/P1 | Sprint 0-12 と後続範囲 |

## 図ごとの読み方

| File | 先に見るポイント | 誤解しないポイント |
|---|---|---|
| `01_product_overview.drawio` | Deep Research から Draft PR / Eval / Audit までの全体 | AI は直接副作用へ進まない |
| `02_user_golden_flow.drawio` | ユーザー操作と承認の流れ | merge / deploy / workflow write は P0 deny |
| `03_use_case_and_roles.drawio` | actor と責務 | role は権限ではなく、承認は human-only |
| `04_p0_architecture.drawio` | host-portable P0 の構成 | Runner は secret / GitHub token を持たない |
| `05_ticket_to_pr_sequence.drawio` | 時間順の処理 | `schema_validated` 後も `policy_linted` / `diff_ready` / approval binding が必要 |
| `06_data_flow_trust_boundaries.drawio` | provider 送信前の data class gate | `allowed_data_class` は caller ではなく Matrix 由来、かつ effective 値で判定 |
| `07_er_overview.drawio` | 情報のまとまり | 最終DDLではなく、tenant/project invariant 理解用 |
| `08_agentrun_state_machine.drawio` | 16状態と停止理由 | status だけでなく AgentRunEvent / ContextSnapshot も正本 |
| `09_agent_orchestration.drawio` | P0.1+ の役割分担 | P0 実装ではなく、role は capability ではない |
| `10_tool_mcp_boundary.drawio` | outbound provider gate と inbound tool gate | provider output の tool call candidate は直接実行しない |
| `11_deployment_network.drawio` | Tailscale 閉域と host 移行 | 移行は暗号化backupだけでなく signed journal / active registry が必要 |
| `12_p0_sprint_roadmap.drawio` | 実装順序 | P0.1/P1 は P0 完了条件ではない |

## Source trace

各図は、下記の正本資料から目的を分けて作成しています。`Must not imply` は、図が誤って示してはいけない境界です。

| File | Source docs / sections | Must not imply |
|---|---|---|
| `01_product_overview.drawio` | PRD-00/01、DD-00、DD-01、DD-04、ロードマップ | AI が command / SQL / secret / merge / deploy に直接つながる |
| `02_user_golden_flow.drawio` | PRD-01 F-001/F-005/F-007/F-008/F-011/F-012、DD-04 | 承認なしで Runner / RepoProxy が副作用を起こす |
| `03_use_case_and_roles.drawio` | PRD-01 Actors、DD-04、ADR-00013/00014 | role 名だけで capability や secret access が付与される |
| `04_p0_architecture.drawio` | PRD-01 P0-SCOPE、DD-00/01/05/06、ADR-00021 | Runner が raw secret / GitHub installation token / direct repo write を持つ |
| `05_ticket_to_pr_sequence.drawio` | PRD-01 F-005/F-008/F-011/F-012、ADR-00004、DD-04 | schema validation だけで実行できる |
| `06_data_flow_trust_boundaries.drawio` | DD-01、DD-04、Provider Compliance Matrix | caller の allowed_data_class をそのまま信用する |
| `07_er_overview.drawio` | DD-02、PRD-01 Data Objects、ADR-00004 | 最終 DDL や全カラム定義として読む |
| `08_agentrun_state_machine.drawio` | ADR-00004、PRD-01 F-008/F-009、DD-03 | waiting_approval から直接 completed へ進む |
| `09_agent_orchestration.drawio` | ADR-00014、ADR-00013、PRD-01 P0.1 scope | P0 で multi-agent 実装が必須になる |
| `10_tool_mcp_boundary.drawio` | PRD-01 F-011/F-012/F-015、DD-01、ADR-00010/00013 | provider の tool-call candidate を直接実行する |
| `11_deployment_network.drawio` | PRD-01 P0-SCOPE-002/010、DD-05、ADR-00007/00021、Sprint 11.5 private staging CI/E2E: tag:taskhub-ci / ephemeral key / TCP:443 only / log mask | public ingress、Funnel、public SSH、永続 CI 参加を許す |
| `12_p0_sprint_roadmap.drawio` | docs/実装計画/00_ロードマップ.md、PRD-01 Scope Decision | P0.1/P1 を P0 完了条件に含める |

## 正本資料

- `docs/要件定義/00_プロダクト要求定義.md`
- `docs/要件定義/01_P0要求定義.md`
- `docs/基本設計/00_全体アーキテクチャ.md`
- `docs/基本設計/01_拡張境界とAdapter設計.md`
- `docs/基本設計/02_データモデル.md`
- `docs/基本設計/03_AIオーケストレーション設計.md`
- `docs/基本設計/04_セキュリティ_権限_監査設計.md`
- `docs/基本設計/05_ネットワーク境界設計.md`
- `docs/基本設計/06_秘密管理設計.md`
- `docs/基本設計/07_可観測性設計.md`
- `docs/実装計画/00_ロードマップ.md`
- `docs/adr/00004_agentrun_state_machine.md`
- `docs/adr/00010_provider_change.md`
- `docs/adr/00014_multi_agent_orchestration.md`
- `docs/adr/00021_host_portable_deployment.md`

## 注意

P0 は host-portable です。Mac / Linux / VPS のいずれか 1 箇所を active host として選べます。古い単一 VPS 前提の記述は、運用フェーズで VPS を推奨する文脈として扱います。

AI 出力は、command / SQL / workflow / repo write / external tool write / secret 解決へ直接つなぎません。必ず artifact、validation、policy、approval、sandbox、audit の境界を通します。
