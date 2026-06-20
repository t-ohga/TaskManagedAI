# 基本設計

プロダクト全体のアーキテクチャ、Adapter 境界、データモデル、AI オーケストレーション、セキュリティ、ネットワーク、秘密管理、可観測性を文書化する。

## 構成

| ファイル | 内容 |
|----------|------|
| `00_全体アーキテクチャ.md` | コンテキスト分離、レイヤ構造、技術スタック |
| `01_拡張境界とAdapter設計.md` | ProviderAdapter / RepoAdapter / RunnerAdapter / ToolAdapter / NotificationAdapter / SecretAdapter |
| `02_データモデル.md` | 全テーブル定義、tenant_id invariant、actors/principals、複合 FK、越境 negative test |
| `03_AIオーケストレーション設計.md` | AgentRun / ContextSnapshot / Output Validator / Input Trust Layer / BudgetGuard |
| `04_セキュリティ_権限_監査設計.md` | Policy/Approval action class、Provider Compliance Matrix、ZDR enforcement、audit |
| `05_ネットワーク境界設計.md` | Tailscale Serve、device approval、CT log 対策、grants |
| `06_秘密管理設計.md` | SecretBroker (backend=local/sops、ADR-00058)、`secret_ref` URI、capability token |
| `07_可観測性設計.md` | OTel + Prom + Loki + Grafana、structured logs、error taxonomy、SLO |

## 上位資料への参照

- 計画（v2 改訂版）: `../設計検討/計画(仮).md`
- 要件定義: `../要件定義/`
