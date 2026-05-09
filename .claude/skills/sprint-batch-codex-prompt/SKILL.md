---
name: sprint-batch-codex-prompt
description: Sprint Pack BL ticket から Codex 用 prompt を生成 (markdown fence 禁止 + 必読 docs 列挙 + 検証セクション + 制約 template)。Sprint N Batch M 実装着手時に invocation。
type: skill
source: feedback_codex_multi_round_workflow.md §2 (Wave 18 移送)
---

# sprint-batch-codex-prompt

## 起動条件

- Sprint Pack の BL-NNNN ticket を Codex 経由で実装する場面
- `Skill(skill="sprint-batch-codex-prompt", args="SP-005 BL-005")` 等で invocation

## 出力形式

Codex 用 prompt template (markdown):

```
# 役割
Sprint N Batch M の実装者。

# 必読 docs (絶対パス)
- /Users/tohga/repo/TaskManagedAI/docs/sprints/<Sprint Pack>.md
- /Users/tohga/repo/TaskManagedAI/.claude/rules/<related rules>.md
- (該当 ADR / harness rule)

# 実装内容
<BL ticket 主成果物 から自動抽出>

# 出力形式
- ===FILE: <absolute path>===
- (file content)
- ===END FILE===
- markdown fence 禁止 (line 1 が ```python 等は BLOCK)
- 末尾解説禁止

# 検証
- pytest <test path> -v
- 期待: PASS / FAIL pattern

# 制約
- sandbox: read-only (default)
- 100 bytes 未満 reject
- stdin redirection (codex exec - < prompt)
```

## 必須要素 checklist

- [ ] 役割明示 (Sprint N Batch M)
- [ ] 必読 docs 絶対パス列挙
- [ ] 実装内容 (BL ticket 抽出)
- [ ] `===FILE:` 区切り出力指示
- [ ] markdown fence 禁止明示
- [ ] 検証コマンド + 期待 pattern
- [ ] sandbox / 100 bytes / stdin 制約

## 関連

- rules: `codex-multi-round-workflow.md`、`codex-usage-policy.md`
- agents: `sprint-review-loop-orchestrator` (Codex round 進行)、`stale-test-detector` (test drift 検知)
- hooks: `markdown-fence-detector.sh` (fence 混入 BLOCK)
- 実装フェーズ: 本 skeleton から content 充実は Wave 18 残実装 or Wave 19+ で扱う
