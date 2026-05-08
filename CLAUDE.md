# TaskManagedAI プロジェクト CLAUDE.md

TaskManagedAI は、Deep Research から実装 PR までを、証拠、判断、承認、実行ログ、コスト、レビュー結果とともに管理する AI-native な開発タスク管理ツールです。P0 は個人専用、Tailscale 閉域、単一 VPS、Docker Compose を前提にしつつ、tenant 境界、actor / principal、secret_ref、Provider Compliance Matrix、policy / approval / audit、AgentRun 状態機械を将来の商用化に耐える形で初期から保持します。

## 必読ファイル

- `.claude/CLAUDE.md`: Claude Code 側の詳細なプロジェクトスコープ指示。
- `AGENTS.md`: Codex 側のプロジェクト方針。Claude でも Codex 連携や作業判断の補助として参照する。
- `docs/要件定義/01_P0要求定義.md`: P0 scope、機能要求、Acceptance Criteria、Provider Compliance Matrix 依存。
- `docs/設計検討/計画(仮).md`: v2 計画書、P0 Scope Decision、Hard Gates、Quality KPIs、Sprint 方針。

## 重要原則の最低線

- AI 出力を直接 command、SQL、workflow、外部 tool 操作へ接続しない。artifact、schema validation、policy、approval、runner sandbox、audit を挟む。
- 実装前に Sprint Pack を確認する。ADR Gate Criteria に該当する高リスク変更は ADR を作成してから進める。
- Tailscale、Tool、Repo、Secret、merge、deploy は deny-by-default。Funnel、外部公開、Secrets 管理、Provider 追加、GitHub App permission 変更は高リスク扱い。
- Provider 送信は `payload_data_class <= allowed_data_class` を Provider Compliance Matrix で機械判定し、未設定・未登録・Matrix 外・越境は送信前 deny。
- SecretBroker は `secret_ref` と短命 capability token を使い、atomic claim と actor / run / fingerprint binding を必須にする。secret 実値を AI / runner / artifact / log に出さない。

## ハーネス入り口

- `.claude/`: Claude 側の rules、agents、hooks、skills、reference、scripts の正本。
- `.codex/`: Codex 側 mirror。Claude 専用 env / AskUserQuestion / Skill 記法はそのまま移植しない。
- `docs/`: 要件定義、基本設計、実装計画、Sprint Pack、ADR、設計検討の正本。

詳細な作業フロー、重要パス、Codex 連携、検証ルールは `.claude/CLAUDE.md` を参照してください。

