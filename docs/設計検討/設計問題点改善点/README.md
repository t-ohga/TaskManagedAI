# 設計問題点・改善点レビュー

このディレクトリは、TaskManagedAI の現行設計を多角的に点検し、問題点、改善点、優先順位、再レビュー結果を残すための場所です。

## 2026-05-14 レビュー成果物

- [設計問題点・改善点 多角レビュー](./2026-05-14_設計問題点改善点_多角レビュー.md)
- [5方向深掘り計画](./2026-05-14_5方向深掘り計画.md)
- [改善アクションバックログ](./2026-05-14_改善アクションバックログ.md)
- [品質ループ再レビュー](./2026-05-14_品質ループ再レビュー.md)
- [第三回 UI/UX・自律ワークフロー整合レビュー](./2026-05-14_第三回_UIUX自律ワークフロー整合レビュー.md)

## レビュー観点

- 機能面、プロダクトとしての日常利用性
- UX/UI、承認、通知、実行ログ、ダッシュボード
- Deep Research から実装 PR までの AI ワークフロー
- より高い自律性を実現するための policy、approval、runner、provider、budget 境界
- ターミナル/CLI からの操作性
- 複数プロジェクト、複数リポジトリ、worktree をまたぐ操作性
- 設計文書間の traceability、status drift、受け入れ条件

## Quality Loop run

| 回 | Run | 扱い |
|---|---|---|
| 第1回 | `.codex/plans/QL-20260514-design-issues-improvements/` | 初回の多角レビューと再レビュー証跡 |
| 第2回 | `.codex/plans/QL-20260514-design-issues-deepening/` | 5方向深掘り、改善 backlog、validator clean 証跡 |
| 第3回 | `.codex/plans/QL-20260514-design-issues-third-uiux-factcheck/` | UI/UX、自律承認、orchestrator、品質ループ、CLI fact-check の最新証跡 |

CLI については、現時点の実装証拠上、user CLI の `cli/`、`docs/cli/`、`tests/cli/`、`tests/parity/` はまだ存在しない。SP-001.5 系の `taskhub` は admin/host CLI、SP-016 の user CLI は planned として分けて読む。

## 使い方

次の Sprint Pack や ADR を作る前に、次の順で読んでください。

1. [第三回 UI/UX・自律ワークフロー整合レビュー](./2026-05-14_第三回_UIUX自律ワークフロー整合レビュー.md): 最新のファクトチェック、UI/UX、初任者導線、自律承認、orchestrator、品質ループの追加論点を把握する。
2. [設計問題点・改善点 多角レビュー](./2026-05-14_設計問題点改善点_多角レビュー.md): 現行設計の問題構造、DI-01〜DI-40、Critical / High 論点を把握する。
3. [5方向深掘り計画](./2026-05-14_5方向深掘り計画.md): 5方向の問い、coverage matrix、BLOCK condition、第3回補強計画を確認する。
4. [改善アクションバックログ](./2026-05-14_改善アクションバックログ.md): 実際にどの ADR / Sprint Pack / 基本設計 / backlog をどの順で直すか確認する。
5. [品質ループ再レビュー](./2026-05-14_品質ループ再レビュー.md): 第1回〜第3回のレビュー結果、採用指摘、残リスクを確認する。

特に P0 の実装着手前には、action class drift、Deep Research E2E、Today/Inbox control plane、初任者ワークフロー、request revision、UI/CLI ContextResolver、P0 後半 Sprint Pack 欠落、runtime gate 未接続、P0 `tmai-lite` と P0.1 full parity の境界を先に解消する前提で扱います。
