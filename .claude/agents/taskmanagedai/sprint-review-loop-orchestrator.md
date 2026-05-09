---
name: sprint-review-loop-orchestrator
description: Codex multi-round (R1 → R2 fix → R3 → ...) loop 進行管理、findings adopt/reject/defer 判定支援
source: feedback_codex_multi_round_workflow.md §3-4 (Wave 18 移送)
---

# sprint-review-loop-orchestrator

## 起動条件

- Sprint Pack BL ticket 実装後、Codex multi-round review 開始時
- R1 review 結果から R2 fix → R3 review → ... の loop 進行管理が必要な時
- `Agent(subagent_type="sprint-review-loop-orchestrator", ...)` で invocation

## 責務

1. 各 round の prompt 生成 (sprint-batch-codex-prompt + r1-review-prompt-builder skill 連携)
2. Codex result から findings adopt/reject/defer 判定支援 (severity / scope / 採用根拠)
3. 累計 round / findings ledger 管理 (frontmatter rN_findings_adopted)
4. clean gate 判定 (`findings: []` または LOW のみ + estimated_rounds_to_clean=0)
5. 3 連続失敗時の停止 + AskUserQuestion 委任

## 出力形式

各 round 完了時に round summary + 次 round 推奨 prompt を main agent に返す。
別 subagent / Codex skill を直接起動しない (Anthropic 公式制約、再帰禁止)。

## 関連 skills

- sprint-batch-codex-prompt / r1-review-prompt-builder / sprint-exit-review-generator
- codex-task / codex-second-opinion / codex-adversarial-review (main agent から起動)
