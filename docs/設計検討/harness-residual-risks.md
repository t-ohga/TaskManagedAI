# Harness Phase 4 残リスク（Sprint 7 へ defer）

最終更新: 2026-05-07

## 目的

Phase 4 で `.claude/hooks/` ハーネスを整備した結果、Codex 多重レビューで 2 件の CRITICAL が **Claude Code 標準の hook 配置由来の構造的問題** として残存した。これらは Phase 4 内では解消できないため、Sprint 7 (`runner_mutation_gateway` 本実装) で `repo 外 trusted wrapper` を ADR 込みで設計する前提で defer する。本文書は defer の根拠と将来の解決方針を記録する。

## 背景

Claude Code の hook 仕様では `.claude/settings.json` の `hooks.*.command` から `$CLAUDE_PROJECT_DIR/.claude/hooks/...` を直接実行する。**hook 実行コードと state が同一 repo 内にある**ため、Bash tool 経由で hook 自身を改ざんされた場合、改ざん検出ロジックが先に実行されない限り bypass できる。

この構造的制約は、harness 構築時の Codex R7→R8 連続レビューで継続して指摘された。R8 までに以下を実装したが、bypass 余地は残った:

- child hook の存在 / executable bit の事前 integrity check
- `.claude/hooks/**` / `.claude/settings.json` / `.claude/.hook-state/**` の同一 Bash 実行内変更を fail-closed で BLOCK
- Pre snapshot 欠落時の `SNAPSHOT_FALLBACK="1"` による全 dirty file dispatch
- atomic write (`tmp + mv`) による Pre snapshot の半端書き込み防止

## 残リスク 2 件

### PH4-F-001 (CRITICAL): dispatcher 自己改ざん耐性

- **症状**: `.claude/settings.json` が repo 内 `.claude/hooks/system/posttool-bash-file-dispatcher.sh` を直接実行する。Bash で dispatcher 自身を `exit 0` 化 / `chmod -x` / 削除されると、追加した integrity check も control-plane 検出も走らない。
- **根本原因**: 改ざん検出ロジックが改ざん対象（repo 内 dispatcher）の中にある。
- **将来の解決方針**: PostToolUse Bash の entrypoint を **repo 外 trusted wrapper** (例: `~/.claude-trusted/taskmanagedai-hook-wrapper.sh`) に移し、wrapper が repo dispatcher と child hooks の存在 / 実行権限 / sha256 manifest を検証してから exec する。dotfiles 管理 + ADR 必須。

### PH4-F-002 (CRITICAL): snapshot state 改ざん耐性

- **症状**: snapshot state を repo 内 `.claude/.hook-state/bash/` に保存。Bash で state ディレクトリごと削除可能 (`SNAPSHOT_FALLBACK` で fallback はあるが、post snapshot write 失敗 / meta 欠落は未 fail-closed)。
- **根本原因**: 差分判定の信頼境界が攻撃対象と同じ repo 内 mutable / ignored state に依存。
- **将来の解決方針**: snapshot state を repo 外 (例: `~/.claude-trusted-state/taskmanagedai/`) に移し、wrapper 管理 + 署名 / hash 検証付きにする。dispatcher 側でも `mkdir -p` 失敗 / post snapshot 作成失敗 / meta 欠落をすべて fail-closed BLOCK にする。

## 現状の防御強度

Phase 4 hooks は以下の attack surface には有効:

- **悪意のない実装ミス**: rules / agents / skills 違反の検出 (frontmatter / DDL / payload_data_class / state enum / tenant boundary 等) → 通常の Edit / Write / Bash 経由で発火
- **Bash 経由の意図しない destructive 操作**: Pre/Post snapshot diff で「この Bash で変更されたファイル」だけを dispatch し、対応 hook を発火
- **child hook の silent skip**: 事前 integrity check で fail-closed BLOCK
- **control-plane file の同一 Bash 実行内変更**: fail-closed BLOCK

Phase 4 hooks が **守らない**範囲 (Sprint 7 まで):

- Bash tool で **dispatcher 自身**を `exit 0` 化 / `chmod -x` / 削除
- Bash tool で **state directory ごと削除** + post snapshot write を妨害
- snapshot 内容を post 状態に合わせて改ざんして dirty diff を消す

## P0 における容認根拠

- **個人専用 + Tailscale 閉域 + 単一 VPS**: P0 scope は商用化前提なし、外部からの悪意ある Bash 注入経路なし
- **AI 出力直結禁止**: AI 出力を直接 Bash に流す経路を rules で禁止 (`.claude/rules/ai-output-boundary.md`)
- **ADR Gate**: control-plane 変更は ADR Gate Criteria 該当 (`#5: MCP / tool 権限`、`#9: 広範囲リファクタ`) で人手承認が要る

## Sprint 7 で対応する内容

`runner_mutation_gateway` 本実装と並行して以下を行う:

1. **新規 ADR-00012 (Hook Trust Boundary)** を draft → proposed → accepted
   - 採用案: repo 外 trusted wrapper (`~/.claude-trusted/taskmanagedai/`)
   - 却下案: 現状維持 / SELinux / git pre-commit でしか対応しない
   - リスク / rollback: dotfiles 管理失敗時の hook 実行不能化
2. wrapper script 実装と sha256 manifest 生成 / 検証
3. snapshot state を repo 外に移動
4. `.claude/settings.json` を wrapper 呼び出しに書き換え
5. 既存 dispatcher / child hook の挙動は維持
6. 移行 Sprint Pack に rollback 手順 (元 settings.json への戻し方) を明記

## 追加: Phase 5 Skills 残リスク (LOW)

R3 で指摘された **PH5-F-004 (LOW)**: Suite 5 件 (`dev-suite` / `quality-suite` / `review-suite` / `security-suite` / `release-suite`) で「Main Agent への指示」明記はあるが、`skill-lint` が要求する Suite 例外 PASS 条件 (DRY_RUN モードで child を実行しない / Codex chain 逐次実行 / 採否判定 `adopt|reject|defer` の明記) は dev-suite のみ完全。他 4 suite は WARN 相当。

**defer 理由**: Phase 5 全体 34 件の整合性は確保済。Suite 共通 boilerplate の標準化はリリース前ではなく **Sprint 0-1 の運用試験フェーズ**で得られる実フィードバック後に行う方が効率的。

**Sprint 0 / 1 で対応する内容**:

1. `dev-suite` の orchestration boilerplate (`DRY_RUN_MODE` 解釈 / child Skill/Agent dry-run 挙動 / Codex chain 逐次 + 採否判定) を template として抽出
2. 残 4 suite (`quality-suite` / `review-suite` / `security-suite` / `release-suite`) に同 template を適用
3. skill-lint の Suite 例外 PASS 条件チェックを 5 suite すべてが通ること

**現状の防御**: skill-lint は WARN を出すが BLOCK ではないので Phase 5 完了の妨げにはならない。

## 参照

- `/Users/tohga/.claude/local/codex-tasks/2026-05-07/harness-phase4-hooks-r7/result.md` (R7 CRITICAL 発見)
- `/Users/tohga/.claude/local/codex-tasks/2026-05-07/harness-phase4-hooks-r8/result.md` (R8 fix 検証 / CRITICAL 残存)
- `.claude/hooks/system/posttool-bash-file-dispatcher.sh` (現状実装)
- `.claude/hooks/system/pretool-bash-snapshot.sh` (現状実装)
- `.claude/rules/ai-output-boundary.md` (AI 出力直結禁止の正本)
- `docs/設計検討/harness-phase0-mapping.md` (Phase 4 hooks 一覧の正本)
