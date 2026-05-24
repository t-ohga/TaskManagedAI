# Codex Startup Prompt

## Full startup prompt

```text
あなたは TaskManagedAI の次 Sprint kickoff を担当する Codex agent です。
前回の 8 task autonomous handoff は PR #172 で closeout 済みです。
今回は Sequence H residual verification と SP-015 kickoff を進めます。

【必読】
1. docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/README.md
2. docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/00-codex-behavior-guide.md
3. docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/01-current-state.md
4. docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/02-task-priority-matrix.md
5. 着手 task の tasks/task-NN-*.md

【実行順序】
1. task-01 Sequence H residual verification
2. task-02 SP-015 Self-Plan-Review
3. task-03 SP-015 batch 0 implementation only if task-02 READY
4. task-04 SP-016 inventory plan-only, no code implementation

【品質 gate】
- task-01 / task-02 は Self-Plan-Review 2 round 必須。
- CRITICAL=0、HIGH<=2 まで plan を修正してから READY。
- task-03 は implementation batch ごと Self-Impl-Review 必須。
- code PR は codex_pr_full_review.sh <PR> actionable 0 を確認。
- hosted GitHub Actions は monthly quota block のため品質信号から除外。

【絶対禁止】
- root checkout の未コミット差分を混ぜない。
- SP-015 plan gate 前に migration / DB schema を実装しない。
- SP-016 code を SP-015 より先に実装しない。
- raw secret / raw message body を DB / log / audit / artifact に保存しない。
- caller-supplied tenant_id / project_id / actor_id を route signature に導入しない。

開始してください。
```

## task-01 prompt

```text
task-01 Sequence H residual verification を実行してください。
対象:
- docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md
- PR #145-#171 residual classes
- PR #172 closeout
- docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/tasks/task-01-sequence-h-residual-verification.md

完了条件:
- reviews/task-01-self-plan-review.md
- completion/task-01-completed.md
- unresolved CRITICAL/HIGH = 0 preferred
```

## task-02 prompt

```text
task-02 SP-015 Self-Plan-Review を実行してください。
対象:
- docs/sprints/SP-015_inter_agent_communication.md
- docs/adr/00018_inter_agent_communication.md
- docs/adr/00004_agentrun_state_machine.md
- docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/tasks/task-02-sp015-plan-review.md

完了条件:
- reviews/task-02-self-plan-review.md
- completion/task-02-completed.md
- CRITICAL=0 / HIGH<=2
- task-03 implementation batches が明確
```

## task-03 prompt

```text
task-03 SP-015 batch 0 implementation を実行してください。

前提:
- task-01 completed
- task-02 completed / READY
- docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/reviews/task-02-self-plan-review.md を読む
- docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff/tasks/
  task-03-sp015-batch-0-inter-agent-message-core.md を読む

最初に実装する batch:
- batch 0a: inter_agent_messages schema and migration

絶対遵守:
- ADR-00018 §1 の exact column set を使う。
- `12 fields` は歴史的 shorthand として扱い、literal column count にしない。
- `payload_data_class` を canonical name にする。
- unique constraints は tenant_id / project_id / parent_run_id を含める。
- receiver eligibility は project_id を含める。
- AgentRunEvent event_type は既存 34/35 を再利用し、新規 allocation しない。
- raw message body / raw secret を audit / AgentRunEvent / artifact export に出さない。

batch ごとに Self-Impl-Review と local verify を行い、
code PR は codex_pr_full_review.sh actionable 0 を確認してください。
```
