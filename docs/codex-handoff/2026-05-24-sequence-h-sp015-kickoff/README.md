# Codex Handoff: Sequence H + SP-015 Kickoff (2026-05-24)

## 目的

前回の `2026-05-22-3day-autonomous` handoff で完了した 8 task を
次の P0.1 実装へ接続するための、新しい Codex 委譲セット。

本 handoff は、いきなり SP-015 の DB / service / migration 実装へ入らない。
まず Sequence H residual verification で前回成果物の品質を固定し、
次に SP-015 の Self-Plan-Review を通してから実装 batch へ進む。

## 正本

- base: `origin/main`
- base merge commit: `dac63d83f6546deab39234f6a090b6dff33e93f9`
- closeout source:
  `docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md`
- previous quality contract:
  `docs/codex-handoff/2026-05-22-3day-autonomous/00-codex-behavior-guide.md`
- next Sprint Pack:
  `docs/sprints/SP-015_inter_agent_communication.md`

## このディレクトリの読み方

| file | scope | 読む順序 |
|---|---|---|
| `README.md` | master index、全体方針 | 1 |
| `00-codex-behavior-guide.md` | Codex 側の品質規範 | 2 |
| `01-current-state.md` | 現状 snapshot | 3 |
| `02-task-priority-matrix.md` | task 優先順位、依存、停止条件 | 4 |
| `tasks/task-NN-*.md` | 個別 task 指示 | 5 |
| `03-claude-verification-checklist.md` | Claude 戻り時の検証手順 | Claude 用 |
| `04-codex-startup-prompt.md` | Codex 起動 prompt | 起動時 |

## task 概観

| task | 優先 | scope | 計画必須 | status |
|---|---|---|---|---|
| task-01 | P0 | Sequence H residual verification | 必須 | completed |
| task-02 | P0 | SP-015 Self-Plan-Review + ADR readiness | 必須 | completed |
| task-03 | P0 | SP-015 batch 0 inter-agent message core | 必須、task-02 後 | completed |
| task-04 | P1 | SP-016 inventory / plan-only | 推奨、docs-only | completed |

## 実行順序

1. task-01 で PR #145-#171 / #172 の residual closure を再検証する。
2. task-01 が `READY` なら task-02 で SP-015 計画を adversarial に磨く。
3. task-02 が `READY` なら task-03 の実装 batch に入る。
4. task-04 は SP-016 の下調べだけに限定し、SP-015 実装を先取りしない。

## 重要な補正

- SP-014 は `status: completed`。現 Sprint Pack 上に
  「SP-014 batch 1+」という実装 scope は定義されていない。
- SP-014 の次スプリント候補は SP-015。
  したがって本 handoff の実装本命は SP-015。
- SP-016 は `draft` で、SP-015 の message backend が固まってからが本実装順。
- SP-011-5 は `completed`。現時点の最優先追加作業ではない。

## 完了成果物

各 task は完了時に以下を残す。

- `completion/task-NN-completed.md`
- `reviews/task-NN-self-plan-review.md` または
  `reviews/task-NN-self-impl-review.md`
- PR description に Self-Review verdict、verification、invariant trace
- 必要な carry-over を本 handoff または Sprint Pack に明記

全 task 完了時は `COMPLETION_REPORT.md` を追加する。

現状態: 全 task completed。詳細は `COMPLETION_REPORT.md` を参照。

## 緊急停止条件

以下を検知したら `STOPPED.md` を起票して停止する。

- Sequence H で CRITICAL / HIGH の未解決 finding が残る
- SP-015 の計画 review で ADR / DB / API contract の矛盾が解消できない
- migration rollback 不能、tenant / project boundary 破壊、raw secret 露出リスク
- Codex / GitHub / local verify が同一原因で 3 連続失敗
- scope が SP-015 batch 0 を超えて SP-016 / SP-017 / SP-018 を侵食する
