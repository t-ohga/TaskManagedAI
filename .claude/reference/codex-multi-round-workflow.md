
> **2026-05-27 Codex プラグイン移行**: Codex 呼び出しは公式プラグイン (`codex@openai-codex`) に移行。
> - `/codex:review` — コードレビュー (working tree / branch diff)
> - `/codex:adversarial-review` — 敵対レビュー (focus text 指定可能)
> - `/codex:rescue` — タスク委譲 (調査・修正・バックグラウンド)
> - `/codex:status` / `/codex:result` / `/codex:cancel` — ジョブ管理
> 旧 `codex exec` + `launch-codex.sh` は互換として残すが、新規利用は非推奨。

# Codex Multi-Round Workflow Rules

Sprint 1-4 で確立した Codex multi-round review の規律。`feedback_codex_multi_round_workflow.md` (project memory archived) からの恒久化。

## 1. Round 推定

Batch 種別ごとの想定 round 数:

| Batch 種別 | 想定 round | 例 |
|---|---:|---|
| state machine / enum DDL | 5-7 | AgentRun 16 状態 / blocked_reason 3 種 |
| SecretBroker / atomic claim | 6-8 | redeem SQL / OperationContext fingerprint |
| fixture / Hard Gate | 4-6 | AC-HARD-01〜07 fixture loader |
| artifact validator / preflight | 3-5 | Provider Compliance Gate / payload_data_class enforcement |
| migration / schema | 3-5 | tenant_id NOT NULL / 複合 FK |
| API contract / Pydantic | 3-4 | endpoint request/response model |

清浄判定: `findings: []` で 1 round 経過、または LOW のみ + estimated_rounds_to_clean=0。

## 2. Prompt 必須要素

Codex prompt に必ず含める:

1. 役割 (e.g., "Sprint X Batch Y の実装者 / R1 reviewer")
2. 必読 docs (絶対パス、self-contained)
3. 出力形式 (`===FILE: <path>===` 区切り、JSON 期待時は schema)
4. 検証セクション (pytest コマンド、期待 PASS / FAIL pattern)
5. 制約 (`markdown fence 禁止`、末尾解説禁止、stdin redirection、100 bytes 未満禁止)
6. sandbox: read-only default

## 3. Markdown fence 罠

Codex 出力は `===FILE: ` 区切りで書き出すが、**先頭に ` ```python ` / ` ```json ` などの markdown fence が混入**するケースが頻発 (Sprint 1-4 で 30+ 回)。

**対策**:
- prompt で `markdown fence は禁止` を明示
- `~/.claude/hooks/markdown-fence-detector.sh` (Wave 18 移送、未実装の場合は Wave 19+) で PostToolUse BLOCK
- Claude 側で fence 検出時に自動除去 (sed 1d で先頭行削除)

## 4. Stale test 対策

Code 変更時に既存 test の `EXPECTED_*` / `len == N` / count 期待値が **drift** するケースが頻発 (Sprint 1-4 で 20+ 回)。

**対策**:
- code 変更後に対応 test の expected 値を必ず confirm
- `~/.claude/agents/stale-test-detector` (Wave 18 移送) で agent invocation
- `~/.claude/hooks/stale-test-content-check.sh` (Wave 18 移送) で WARN

## 5. Codex vs Claude 直接 fix 判断

Round の進行中、Claude が直接 fix する方が efficient なケース:

- 1-2 file の typo / wording 変更
- frontmatter ledger 更新
- 単一 line の path 変更

Codex に再依頼する方が efficient なケース:

- 複数 file 横断の logic 変更
- 新規 schema body 作成
- multi-step 実装 (5+ ファイル)

判断基準: code 変更行数 > 30 → Codex、< 30 → Claude 直接 fix。

## 6. Clean gate 判定基準

`verdict: clean` 条件:
- `findings: []` または LOW のみ
- `estimated_rounds_to_clean: 0`
- `self_test_executable: true`
- frontmatter ledger と本文 divergence 0

LOW 残存時は user 判断 (Wave 19+ defer 可、または final round で fix)。

## 7. Failure protocol (3 連続失敗)

`~/.claude/hooks/track-codex-failures.sh` が 3 連続失敗で `exit 2` BLOCK。

成功時は `~/.claude/hooks/reset-codex-failures.sh` (PostToolUse) が auto reset。

カウンタファイル: `~/.claude/local/codex-failure-count.${CLAUDE_SESSION_ID}`、override: `~/.claude/local/codex-failure-threshold` (default 3)。

## 関連

- source memory: `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/feedback_codex_multi_round_workflow.md` (Wave 18 で archived 予定)
- 移送先 hooks: `markdown-fence-detector.sh` / `stale-test-content-check.sh` (Wave 18 移送、別 session で content 充実)
- 移送先 skill: `sprint-batch-codex-prompt` / `r1-review-prompt-builder` / `sprint-exit-review-generator` (Wave 18 移送)
- Wave 18 BL-WP018-004: harness consolidation 22 件移送
