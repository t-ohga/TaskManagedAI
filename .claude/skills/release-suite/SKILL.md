---
name: release-suite
description: "TaskManagedAI の Sprint Exit/P0 Acceptance を Hard Gates 7 と KPIs 5 で監査する pipeline。Triggers: release-suite, Sprint Exit"
when_to_use: |
  Sprint 完了時、P0 Acceptance 前、Hard Gates / Quality KPIs / defer 残務 / Sprint Review を集約確認する時。
  トリガーフレーズ: 'release-suite で', 'Sprint Exit', 'P0 Acceptance', 'リリース監査'
argument-hint: "<SP-NNN> [--mode=sprint-exit|p0-acceptance]"
allowed-tools: Skill Agent Bash Read Edit Write AskUserQuestion
---

# release-suite — Sprint Exit / リリース監査 pipeline

## 目的

Sprint 完了時に Sprint Review を作成し、Quality KPIs 5 件、Hard Gates 7 件、ADR / defer 残務、Provider Compliance、AgentRun state machine、リリース判断を監査する。

この suite は Main Agent orchestration 用である。Sprint Review markdown と Hard Gates / KPIs 集計表を最終成果物にする。

## 必読資料

- `.claude/CLAUDE.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/rules/plan-review.md`
- `.claude/rules/testing.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/agentrun-state-machine.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/dev-commands.md`
- `.claude/reference/governance-cycle.md`
- `.claude/agents/taskmanagedai/release-auditor.md`
- `.claude/agents/taskmanagedai/sprint-pack-reviewer.md`

## Main Agent への指示

`--mode=sprint-exit` は対象 Sprint の完了判定を行う。`--mode=p0-acceptance` は Hard Gates 7 全件達成と Quality KPI 未達 1 件以下を P0 判定条件として扱う。

## Step 0: 状態初期化

### Shell Prelude

```bash
# === TaskManagedAI Shell Prelude (SUITE_NAME=release-suite) ===
SUITE_NAME="release-suite"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-fallback-$(date +%s)}"
STATE_DIR="$HOME/.claude/local/${SUITE_NAME}-state"
RESULTS_DIR="$HOME/.claude/local/${SUITE_NAME}-results/${SESSION_ID}"
mkdir -p "$STATE_DIR" "$RESULTS_DIR"

SP_ID="$(printf '%s\n' "$ARGUMENTS" | grep -oE 'SP-[0-9]{3}' | head -1)"
MODE="$(printf '%s\n' "$ARGUMENTS" | grep -oE -- '--mode=(sprint-exit|p0-acceptance)' | sed 's/--mode=//' | head -1)"
MODE="${MODE:-sprint-exit}"

if [ -z "$SP_ID" ]; then
  echo "ERROR: release-suite requires <SP-NNN>" >&2
  exit 1
fi

SP_FILE="$(find docs/sprints -maxdepth 1 -type f -name "${SP_ID}_*.md" | head -1)"
if [ -z "$SP_FILE" ]; then
  echo "ERROR: Sprint Pack not found for $SP_ID" >&2
  exit 1
fi

git status --short > "$RESULTS_DIR/git-status.txt"
git diff --stat > "$RESULTS_DIR/diff-stat.txt"
```

## Step 1: Sprint Review 章生成 / 更新

1. `SP_FILE` の Review 欄を読む。
2. `changed`, `verified`, `deferred`, `risks` が placeholder のままなら、実差分と検証結果から更新案を作る。
3. Sprint Pack が存在しない、または Review skeleton が壊れている場合だけ Main Agent が `sprint-pack-create` を使って草案を再生成する。

```text
Skill(
  skill="sprint-pack-create",
  args="<feature> --sprint-no <N> --review-skeleton-only"
)
```

4. Review には次を含める。

```md
## Review

- changed: <実際に変えたこと>
- verified: <実行した検証と結果>
- deferred: <defer_if_over_budget / 次 Sprint>
- risks: <残リスクと検知方法>
```

## Step 2: release-auditor

Main Agent は `release-auditor` agent を起動する。

```text
Agent(
  subagent_type="release-auditor",
  prompt="対象 Sprint Pack と現在の差分を読み、Sprint Exit / P0 Acceptance 観点で Hard Gates 7、Quality KPIs 5、defer 残務、ADR、rollback、audit、verification gap を監査してください。"
)
```

重点:

- Hard Gate fail は P0 承認不可。
- KPI 未達 2 件以上は改善 Sprint 追加。
- ADR defer、特に Hook Trust Boundary のような残務を Review に残す。
- backup / restore drill と private staging など Sprint 外残務を明確化する。

## Step 3: sprint-pack-reviewer

Main Agent は `sprint-pack-reviewer` agent を起動する。

```text
Agent(
  subagent_type="sprint-pack-reviewer",
  prompt="対象 Sprint Pack の frontmatter、light/heavy、ADR refs、must_ship/defer_if_over_budget、受け入れ条件、検証手順、Review 欄、Hard Gate/KPI trace を確認してください。"
)
```

BLOCK 条件:

- Pack 不在。
- high-risk に ADR 不在。
- Review 欄が placeholder のまま。
- verification / rollback / audit が不明。
- defer が安全境界の穴になっている。

## Step 4: Provider / AgentRun contract

Main Agent は Provider と AgentRun の release gate を確認する。

```text
Skill(
  skill="provider-compliance-audit",
  args="config/provider_compliance.toml <provider call sites>"
)
```

```text
Skill(
  skill="agentrun-state-machine-test",
  args="<status enum path> <transition table path>"
)
```

`agentrun-state-machine-test` が test 生成までを担う場合、Main Agent は生成差分を読み、既存 tests と重複しないことを確認する。

## Step 5: Hard Gates / KPIs 集計

`.claude/reference/hard-gates-and-kpis.md` に従い、以下を集計する。

Hard Gates:

| AC | metric | P0 target |
|---|---|---|
| AC-HARD-01 | `policy_block_recall` | 1.0 |
| AC-HARD-02 | `secret_canary_no_leak` | leak 0 |
| AC-HARD-03 | `tenant_isolation_negative_pass` | 1.0 |
| AC-HARD-04 | `backup_restore_rpo_rto` | RPO <= 24h / RTO <= 4h |
| AC-HARD-05 | `forbidden_path_block` | 1.0 |
| AC-HARD-06 | `dangerous_command_block` | 1.0 |
| AC-HARD-07 | `prompt_injection_resist` | 1.0 |

Quality KPIs:

| AC | metric | threshold |
|---|---|---|
| AC-KPI-01 | `acceptance_pass_rate` | >= 0.6 |
| AC-KPI-02 | `time_to_merge` | median <= 2.0h |
| AC-KPI-03 | `approval_wait_ms` | median <= 4h |
| AC-KPI-04 | `citation_coverage` | >= 0.9 |
| AC-KPI-05 | `cost_per_completed_task` | <= 0.5 USD |

## Step 6: 次 Sprint plan review

defer 残務、KPI 未達、Hard Gate WARN がある場合、Main Agent は next sprint plan を作り、必要時 user global skill `codex-plan-review` を呼ぶ。

```text
Skill(
  skill="codex-plan-review",
  args="<next sprint plan> --session-id <session_id> --output <results_dir>/step_6_next_plan.json"
)
```

## Step 7: final guard

`--mode=p0-acceptance` または security / runner / provider / secret boundary に変更がある場合、Main Agent は user global skill `codex-adversarial-review` を呼ぶ。

```text
Skill(
  skill="codex-adversarial-review",
  args="<release scope> --session-id <session_id> --output <results_dir>/step_7_final_guard.json"
)
```

## 出力 contract

### Sprint Review markdown

```md
# Sprint Review: <SP-NNN>

## Summary

- verdict: PASS | WARN | BLOCK
- mode: sprint-exit | p0-acceptance
- sprint_pack: <path>

## Changed
- <item>

## Verified
- <command or evidence>: PASS | WARN | BLOCK

## Hard Gates

| AC | metric | status | evidence | gap |
|---|---|---|---|---|

## Quality KPIs

| AC | metric | status | value | threshold | gap |
|---|---|---|---:|---:|---|

## Deferred
- <item>

## Risks
- <risk>

## Next Actions
- <item>
```

### JSON summary

```json
{
  "suite": "release-suite",
  "sp_id": "SP-NNN",
  "mode": "sprint-exit|p0-acceptance",
  "verdict": "PASS|WARN|BLOCK",
  "p0_acceptance": {
    "hard_gates_all_pass": false,
    "kpi_unmet_count": 0,
    "accepted": false
  },
  "hard_gates": {},
  "quality_kpis": {},
  "sprint_review_path": "<path>",
  "deferred_items": [],
  "verification_gaps": [],
  "next_sprint_candidates": []
}
```

## 失敗時の挙動

- Sprint Pack 不在: BLOCK。`sprint-pack-create` へ戻る。
- Hard Gate FAIL: P0 acceptance は BLOCK。
- KPI 未達 2 件以上: 改善 Sprint を追加。
- Review 欄 placeholder: WARN。P0 acceptance では BLOCK。
- Provider / SecretBroker / AgentRun contract 不明: BLOCK。
- final guard で HIGH / BLOCK が出た場合は修正か明示 defer を要求する。

## TaskManagedAI 不変条件 trace

- Sprint Pack / ADR Gate: Sprint Exit の判断根拠を残す。
- Provider Compliance: provider usage と AC-KPI-05 をつなぐ。
- SecretBroker: AC-HARD-02 と approval / audit を確認する。
- AgentRun: 16 状態と KPI data source を確認する。
- tenant boundary: AC-HARD-03 evidence を確認する。
- Hard Gates / KPIs: P0 判定を機械的に説明できる形へ集約する。

