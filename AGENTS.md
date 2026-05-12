# TaskManagedAI Codex Project Guide

このファイルは `/Users/tohga/repo/TaskManagedAI` 配下の Codex プロジェクトスコープ指示です。
上位のユーザー指示を継承しつつ、このリポジトリでは以下を優先してください。

## Communication

- 思考は英語で行い、ユーザー向けの最終出力と通常の説明は日本語で行う。
- ユーザーの要望が実装前の相談、要件定義、設計確認、方針決定に関わる場合は、質問段階を軽く扱わない。
- 曖昧な要件、複数の妥当な設計案、高リスク変更、ユーザーの承認が必要な判断、後戻りしづらい選択がある場合は、作業前にしっかり確認する。
- 確認するときは、単なる短い質問で済ませず、前提、選択肢、推奨案、各案の影響、確認したい決定事項を明示する。
- すでに計画と実装方針が決まっている作業では、不要な確認で止めず、実装、検証、レビューまで自律的に進める。
- ユーザーの最新メッセージが過去の方針を修正している場合は、最新の内容を優先する。

## Project Goal

- このリポジトリは、AI 実装支援を組み込んだ自作タスク管理ツールを設計・実装するためのものとして扱う。
- 中核コンセプトは「Deep Research から実装 PR までを、証拠、判断、承認、実行ログ、コスト、レビュー結果とともに管理する AI-native な開発タスク管理ツール」とする。
- 初期構成は、単一 VPS、Docker Compose、PostgreSQL、Redis、FastAPI、Next.js、Tailscale Serve/SSH、GitHub App、AI Agent Adapter を現実的な基準線として検討する。
- 既存の設計検討文書は重要な前提資料として扱い、実装前に関連する `docs/設計検討/` 配下を確認する。

## Planning And Confirmation

- 実装前に、変更の目的、影響範囲、主要ファイル、検証方法、ロールバックしやすさを確認する。
- 高リスク領域では、実装前にユーザー確認を必須とする。高リスク領域には、認証・認可、DB スキーマ、API 契約、AI エージェント権限、MCP ツール権限、秘密情報、外部公開設定、破壊的操作、広範囲リファクタを含む。
- 質問が必要な場合は、推奨案を提示したうえで、ユーザーが判断しやすい粒度まで具体化する。
- 合理的な仮定で進められる低リスク作業は、仮定を明示して実装へ進む。
- 実装開始後に新しい不確実性やリスクが出た場合は、勝手に広げず、影響と選択肢を整理して確認する。

## Implementation Discipline

- 計画が決まって実装に入ったら、できるだけ完成まで進める。コード変更だけで終わらず、検証、自己レビュー、残リスクの記録まで行う。
- 既存の構造、命名、依存関係、設計方針を優先し、不必要な抽象化や大規模変更を避ける。
- 実装は小さなステップに分け、各ステップで壊れていないことを確認する。
- エラーを握りつぶさず、根本原因を直す。`@ts-ignore` や広すぎる `try/catch` は最終手段にし、使う場合は理由を明示する。
- セキュリティ境界では deny-by-default、最小権限、明示的な allowlist、監査ログ、短命トークン、秘密情報非露出を優先する。
- AI 出力を直接コマンド、SQL、ワークフロー、外部ツール操作へ接続しない。構造化検証、ポリシー判定、人間承認を挟む設計を優先する。

## Verification And Review

- 変更後は、該当するテスト、型チェック、lint、ビルド、または最小限の動作確認を実行する。
- テストや検証が未整備の場合は、実行可能な代替確認を行い、何を確認できて何が未確認かを記録する。
- UI を変更した場合は、可能な限りブラウザで主要フローとレスポンシブ表示を確認する。
- 実装完了時には、差分を自己レビューし、バグ、回帰、セキュリティ、保守性、テスト不足の観点で見直す。
- 最終報告には、変更内容、検証結果、未確認事項、残リスク、必要な次アクションを簡潔に含める。

## Repository Operations

- ファイル検索は `rg` / `rg --files` を優先する。
- JSON は巨大ファイルを丸読みせず、`jq` などで必要なキーを抽出する。YAML / TOML も構造化ツールやパーサを優先する。
- 既存のユーザー変更を勝手に戻さない。作業対象に未整理の差分がある場合は、それを読んで共存する。
- Git コミットはユーザーが依頼した場合に行う。コミットメッセージは Conventional Commits を使い、英語で書く。
- main / master への直接コミットは避ける。ブランチを作る場合は `codex/` prefix を基本とする。

## Documentation

- 重要な設計判断は `docs/` に残す。将来の実装者が判断の背景を追えるよう、理由、代替案、採用しなかった案、リスクを記録する。
- README、セットアップ手順、環境変数、ローカル実行方法、テスト方法はコードと同期させる。
- 外部仕様や公式ドキュメントに依存する内容は、古くなる可能性を明示し、必要なら最新情報を確認する。

## .claude / .codex Harness Reference

- `.claude/CLAUDE.md` は Claude Code 側のプロジェクトスコープ指示として扱う。Codex では内容を参照するが、Claude 固有の hook / Skill / AskUserQuestion 記法は Codex の実行環境に合わせて読み替える。
- `.claude/rules/` は AI 出力境界、Sprint Pack / ADR Gate、Provider Compliance、SecretBroker、AgentRun 状態機械を正本化する場所とする。実装・レビュー・外部エージェント出力の採否判断では、該当 rule を優先して確認する。
- `.claude/reference/` は ad-hoc 参照用とする。harness inventory、agent routing、audit ownership、dev commands、directory structure、Provider Compliance Matrix、Hard Gates / KPIs、SecretBroker contract、AgentRun state machine、ADR Gate Criteria などを置く想定。
- `.claude/agents/` と `.codex/agents/` は reviewer 群を管理する場所とする。Claude agent を先に確定し、Codex toml は必要なものだけ mirror して手動確認する。
- `.claude/hooks/` と `.codex/hooks.json` は gate 自動化を管理する場所とする。P0 では P0 Hard Gates、SecretBroker、Provider Compliance、Sprint Pack、ADR Gate、AgentRun、PostgreSQL boundary、Runner boundary に直結する軽量 hook から始める。
- `.claude/skills/` は suite と TaskManagedAI 固有 skill を提供する場所とする。`dev-suite` / `quality-suite` / `review-suite` / `security-suite` / `release-suite` と、Sprint Pack、ADR、Hard Gate fixture、atomic claim、Provider Compliance、AgentRun state machine、runner gateway、PostgreSQL boundary の固有 skill を想定する。
- `.codex/config.toml` は Codex 実行設定、`.codex/hooks.json` は Codex で実行可能な shell hook のみを扱う。Claude 専用 env や `$CLAUDE_PROJECT_DIR` 前提の hook を持ち込まない。

## Worktree 利用 (TaskManagedAI 固有事情、2026-05-12 追記)

判断フロー / 使う・使わない判断軸は **user-global `~/.claude/CLAUDE.md` §「Git Worktree 利用判断ルール」を正本** として参照。本節は TaskManagedAI 固有事情のみ。

- code (backend / frontend) を触る場合は worktree 作成直後に `bash scripts/worktree_setup.sh` で setup 自動化 (pnpm install + uv sync + SOPS 復号、約 10 分)。doc-only なら skip 可。
- `.worktreeinclude` で gitignored 個人設定 (`settings.local.json` / SOPS / age key pointer) を worktree に自動 copy。DD-06 SecretBroker 原則で `.env.local` は意図的に copy 禁止、各 worktree で SOPS 経由 (setup script 内) で生成。
- 並列 bg job は scope 分割で conflict 防止: backend / frontend / docs / read-only 調査の 4 軸。Codex 並列起動禁止 (`.claude/rules/codex-usage-policy.md`)。
- 詳細運用: `docs/設計検討/bg-job-worktree-workflow.md`。

## Codex 専用補足

- Codex からさらに Codex chain を並列起動しない。Claude 側の `codex-task` / `codex-second-opinion` / `codex-plan-review` / `codex-adversarial-review` / `codex-rescue` は Claude 側 Skill 経由の運用として扱い、Codex 自身の作業では同等観点を通常レビューに読み替える。
- 外部エージェント連携やレビューが 3 連続で失敗した場合は自動停止し、原因、失敗回数、継続案、停止案を整理してユーザー確認に戻す。
- `workspace-write` が有効な Codex 設定でも、高リスク領域、既存差分への上書き、秘密情報、DB、API 契約、外部公開、破壊的操作、広範囲リファクタは本ファイルの Planning And Confirmation に従い、実装前に承認条件を明確にする。
- 現在の sandbox が read-only の場合はファイルを書き換えず、生成内容または patch 案として提示する。
- `.codex/agents/*.toml` を作成・更新する場合は、Claude-only field、Claude-only tool 名、`$CLAUDE_PROJECT_DIR`、AskUserQuestion 前提、Skill 再帰起動前提、存在しない path が残っていないか手動確認する。
- Codex hook は実際に shell command として実行できることを重視する。生成できたことではなく、`codex hooks` / 実 hook 実行時に `hook exited with code 127` のような実害が出ないことを確認する。

