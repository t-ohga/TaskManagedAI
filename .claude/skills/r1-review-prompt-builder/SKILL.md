---
name: r1-review-prompt-builder
description: Batch 種別 (state machine / SecretBroker / fixture / artifact / cross_source / boundary) に応じた R1 review 観点 master list を組み込む prompt 生成
type: skill
source: reference_review_observations.md §R1 master list (Wave 18 移送)
---

# r1-review-prompt-builder

## 起動条件

- Sprint N Batch M 実装完了後、R1 review 開始時
- `Skill(skill="r1-review-prompt-builder", args="state_machine SP-005 BL-005")` 等で invocation

## Batch 種別 → R1 観点 mapping

| Batch 種別 | R1 観点 (key) |
|---|---|
| state machine / enum | 16 状態 / blocked_reason 3 種 / EVENT_TYPE_FOR_TRANSITION / BLOCKED_EVENT_TYPE_REASON_MAPPING / transition_with_event 三重 guard |
| SecretBroker / atomic claim | OperationContext canonical fingerprint / actor/run/operation binding / 0 rows reject / redeem 後再検証 / audit assert_no_raw_secret |
| fixture / Hard Gate | 23 invariant fixture loader / parametrized test / EXPECTED_* 5+ source / weak assertion 禁止 |
| artifact validator | payload_data_class enforcement / Provider Compliance Matrix / preflight gate / canary pattern |
| cross_source enum | DB CHECK / ORM / Python Literal / Pydantic / pytest fixture 5+ source 整合 / drift detection |
| caller-supplied boundary | signature レベル削除 / approval 4 整合 / self-approval 禁止 / action_class enum |
| migration / schema | tenant_id NOT NULL / 複合 FK / RLS-ready / negative test |
| API contract | Pydantic request/response / OpenAPI drift / actor/principal context / error_code |
| runner / dangerous command | forbidden path allowlist / dangerous command denylist / runner_mutation_gateway / fixture |

## 出力形式

```markdown
# 役割
Sprint N Batch M の R1 reviewer。

# 必読
- Sprint Pack: <path>
- 関連 rules: <list>
- 実装 commit: <sha>

# Batch 種別: <enum>

# R1 観点 (master list、本 batch 種別)
1. <観点 1>
2. <観点 2>
...
N. <観点 N>

# 出力形式 (JSON)
{
  "review_round": "R1",
  "findings": [...],
  "summary": {"total": N, "blocker": N, "high": N, "medium": N, "low": N},
  "verdict": "needs_fix" | "clean",
  "estimated_rounds_to_clean": N
}

# 制約
- evidence 必須 (file path + line)
- markdown fence ``` で出力全体を囲わない
```

## 関連

- skill: `sprint-batch-codex-prompt` (実装側 prompt)、`sprint-exit-review-generator` (Sprint Exit)
- agent: `code-reviewer` / `actor-binding-reviewer` / `agentrun-state-reviewer` / `provider-compliance-reviewer` / `runner-security-reviewer` / `tenant-project-isolation-reviewer` / `postgres-specialist`
- 実装フェーズ: 本 skeleton から content 充実は Wave 18 残実装 or Wave 19+ で扱う
