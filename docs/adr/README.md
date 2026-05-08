# Architecture Decision Records (ADR)

設計判断の記録。ADR Gate Criteria に該当する変更は ADR 必須。

## 構成

| ファイル | 内容 |
|----------|------|
| `_template.md` | ADR テンプレ（背景 / 選択肢 / 採用案 / 却下案 / リスク / rollback の 6 項目） |
| `00001_<title>.md` 〜 | 決定済み ADR（5 桁連番） |

## ADR Gate Criteria（計画 v2 §Documentation And Sprint System より）

以下に該当する変更は ADR 必須:

- 認証・認可、Auth/RBAC 変更
- DB schema（特に tenant_id / RLS / 複合 FK）の変更
- API 契約（versioned REST / event schema）の変更
- AI エージェント権限、tool registry の trust_tier 変更
- MCP / tool 権限、scope 変更
- Secrets 管理方式（SOPS → Vault 等）の変更
- 外部公開（Tailscale Serve → Funnel / Cloudflare 等）の変更
- 破壊的操作（migration、tenant データ移行）
- 広範囲リファクタ（5+ ファイル横断、API 契約変更を伴う）
- Provider 追加 / 切替
- GitHub App permission 変更

## 上位資料への参照

- 計画（v2 改訂版）: `../設計検討/計画(仮).md`
