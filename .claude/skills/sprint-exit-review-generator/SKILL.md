---
name: sprint-exit-review-generator
description: Sprint Pack `## Review` section の `changed/verified/deferred/risks` 4 項目 + Hard Gates / KPIs trace + commit message 構造を生成。Sprint N Exit 時に invocation。
type: skill
source: feedback_codex_multi_round_workflow.md §8 (Wave 18 移送)
---

# sprint-exit-review-generator

## 起動条件

- Sprint N の全 batch clean 達成、Sprint Exit 時
- `Skill(skill="sprint-exit-review-generator", args="SP-005")` 等で invocation

## 出力形式

### Sprint Pack `## Review` section

```markdown
## Review

### Changed
- `<file path>`: <change summary> (`<commit sha>`)
- ...

### Verified
- pytest <test path>: PASS
- ruff / mypy: PASS
- contract test: PASS
- Hard Gate fixture: AC-HARD-NN PASS / KPI fixture: AC-KPI-NN PASS

### Deferred
- BL-NNN: <ticket title> (defer reason)
- Wave NN BL-NNNN: <retro item> (Wave NN で扱う)
- ...

### Risks
- <residual risk 1>
- <residual risk 2>
- ...
```

### Commit message 構造

```
feat(sprint-N): <Sprint Pack title> + <key deliverables 3-4 items>

- <BL-NNN deliverable 1>
- <BL-NNN deliverable 2>
...

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Hard Gates / KPIs trace

Sprint Exit で必ず以下を確認:

- AC-HARD-01〜07 のうち本 Sprint で完成 / 進行 fixture を列挙
- AC-KPI-01〜05 のうち本 Sprint で完成 / 進行 fixture を列挙
- defer された Hard Gate / KPI は明示

## 関連

- skill: `sprint-batch-codex-prompt` (実装側)、`r1-review-prompt-builder` (R1 review)
- agent: `release-auditor` (Sprint Exit + Hard Gates / KPIs 集計)
- 実装フェーズ: 本 skeleton から content 充実は Wave 18 残実装 or Wave 19+ で扱う
