# Task Priority Matrix (Codex 3 日間用)

3 日間で着手する全 task の **優先順位 + 依存関係 + 並行可能性 + 想定 effort** を集約。

## 1. 優先順位 (P0 / P1 / P2)

| 優先 | task | sprint | scope | 計画必須 | self-review (§3) | 想定 effort |
|---|---|---|---|---|---|---|
| **P0** | task-01 | SP-014 batch 0 | orchestrator agent core (service + lease + 4 重防御 + policy_profile) | **必須** | Plan 2 round + Impl 1 round 必須 | 1.5-2 day |
| **P0** | task-02 | SP-012-8 batch 1-7 | UI 日本語化 (navigation + 7 page) | **必須** | Plan 1-2 round + Impl 1 round 必須 | 1-1.5 day |
| **P1** | task-03 | SP-022-1 | scripts hardening + Layer C SOP polish | 推奨 | Plan 1 round + Impl 1 round 推奨 | 0.7-1 day |
| **P1** | task-05 | SP-0045 | Tool Registry 本体 (tools + allowed_actions + trust_tier + lockfile) | **必須** | Plan 2 round + Impl 1 round 必須 | 1.5-2 day |
| **P2** | task-04 | SP-012-9 残 wiring | Approvals + Agent Runs + Audit + Settings page wiring | 推奨 | Plan 1 round + Impl 1 round 推奨 | 0.5-1 day |
| **P2** | task-06 | docs/adr drift | ADR + Sprint Pack frontmatter retroactive fix | 不要 | Plan 1 round + Impl 1 round 推奨 | 0.3-0.5 day |
| **P2** | task-07 | test coverage | Backend untested branch coverage 拡張 | 不要 | Plan 1 round + Impl 1 round 推奨 | 0.5-1 day |
| **P3** | task-08 | docs drift | rules + reference + Sprint Pack 用語 + cross-reference 整合 | 不要 | Plan 1 round + Impl 1 round 推奨 | 0.3-0.5 day |

合計想定: 6.4-9.5 day = 3 日間 (実労 24h × 3 = 72h) で task-01/05 直列 + 残 6 task 並行で完遂可能。

**3 日間 schedule 推奨 (8 task 並行 schedule)**:

```
Day 1 (土):
  09:00-12:00  task-01 Self-Plan-Review 2 round (CRITICAL=0/HIGH≤2 達成)
  09:00-13:00  task-02 Self-Plan-Review + glossary 確定 (並行)
  13:00-21:00  task-01 batch 0a 実装 + task-03 (並行) + task-06 (並行 light)

Day 2 (日):
  09:00-21:00  task-01 batch 0b-0e + task-02 batch 1-4 + task-07 (並行)

Day 3 (月):
  09:00-15:00  task-01 batch 0f + task-02 batch 5-7 + task-05 batch A-B (task-01 batch 0d 完遂後)
  15:00-21:00  task-04 残 wiring + task-05 batch C-D + task-08 + 完了報告
```

## 2. 依存関係 (DAG)

```
                ┌────────────────────────┐
                │ origin/main HEAD       │
                │ (PR #141 merge SHA)    │
                └────┬───────────────────┘
                     │
        ┌────────────┼────────────┬──────────────┐
        ▼            ▼            ▼              ▼
   task-01        task-02      task-03         task-04
   (SP-014       (SP-012-8    (SP-022-1       (SP-012-9
    batch 0)     i18n)         hardening)     残 wiring)
        │            │            │              │
        └────────────┼────────────┴──────────────┘
                     ▼
             Claude verification
             (return on 2026-05-25)
```

**全 task 並行起動可能** (依存なし)、ただし同一 file 編集衝突を回避 (§3 参照)。

## 3. 並行可能性 + 衝突回避

### 3.1 衝突可能性のある file

| file | task |
|---|---|
| `frontend/components/navigation.tsx` | task-02 (i18n) |
| `frontend/app/(admin)/tickets/*.tsx` | task-02 (i18n) |
| `frontend/app/(admin)/approvals/*.tsx` | task-02 (i18n) / task-04 (wiring) |
| `frontend/app/(admin)/agent-runs/*.tsx` | task-02 (i18n) / task-04 (wiring) |
| `frontend/app/(admin)/audit/*.tsx` | task-02 (i18n) / task-04 (wiring) |
| `frontend/app/(admin)/settings/*.tsx` | task-02 (i18n) / task-04 (wiring) |
| `backend/app/api/agent_runs.py` | task-01 (orchestrator state field 追加) / task-04 (wiring 用 read endpoint 追加) |
| `backend/app/db/models/agent_run.py` | task-01 (orchestrator lease fields binding) |
| `backend/app/services/policy/` | task-01 (policy_profile 拡張) |
| `scripts/backup_orchestrator.py` | task-03 (hardening) |

### 3.2 衝突回避戦略

**推奨実行順序** (3 日間スケジュール、衝突最小化):

```
Day 1 (2026-05-23 土):
  09:00-12:00  task-01 Self-Plan-Review 2 round (§3.1、CRITICAL=0/HIGH≤2 達成)
  13:00-21:00  task-01 batch 0a 実装 (SP014-T01: orchestrator service + lease_manager)
                + 各 batch 末で Self-Impl-Review (§3.2 Step 2-3)
                + 並行: task-03 (scripts hardening、独立 file 多い)

Day 2 (2026-05-24 日):
  09:00-21:00  task-01 batch 0b-0e 実装 (T02-T09 順次、batch ごと PR merge)
                + 並行: task-02 Self-Plan-Review (navigation + 1-2 page、翻訳 glossary 確定)

Day 3 (2026-05-25 月):
  09:00-15:00  task-02 batch 1-7 実装 (i18n、全 page)
  15:00-21:00  task-04 残 wiring (Approvals / AgentRuns / Audit / Settings)
                + 完了報告 + handoff memory 起票
```

各 phase で **§3 Self-Review Protocol** を遵守 (`codex-all-loops` は Claude 専用 skill のため Codex 側で呼べない)。

### 3.3 衝突発生時の対処

1. **task-02 と task-04 が同 page を触る場合**: task-02 (i18n) を **task-04 wiring 完了後** に実施 (i18n は wiring 後の方が翻訳対象が確定)
2. **task-01 と task-04 が agent_runs.py を触る場合**: task-01 の orchestrator state 追加を **先に merge**、task-04 は base を rebase してから wiring 追加
3. **同時 push 衝突**: `git pull --rebase origin main` で linear history 維持

## 4. 計画必須判定 (`00-codex-behavior-guide.md` §2)

### 4.1 計画必須 (§3.1 Self-Plan-Review CRITICAL=0/HIGH≤2 達成後着手)

- **task-01 (SP-014)**: heavy Sprint Pack + 新規 ADR (ADR-00009 update + Tool Registry network ADR) + 新規 migration (00NN_p0_1_orchestrator.py + 00NN_p0_1_policy_profile.py) + CRITICAL invariant 直結 (lease atomic claim + Tier 2 human-only invariant + AgentRun status 拡張) → **Round 2 (敵対視点) 必須**
- **task-02 (SP-012-8)**: 25 frontend file 横断、deep translation 規律必要 (existing pattern との一貫性、accessible-name 維持) → **Round 1 (構造) + glossary 確定後 Round 2 (敵対視点)**

### 4.2 計画推奨 (短時間 Self-Plan-Review で着手可能)

- **task-03 (SP-022-1)**: scope 中、deviation 7 件で散らばっているが各々独立、§3.1 Round 1 (構造) のみで着手可能 (Round 2 敵対視点は scope 内変更で発見される adversarial 観点が少ない)
- **task-04 (SP-012-9 残 wiring)**: 既存 pattern (tickets page) 流用、§3.1 Round 1 (構造) のみで着手可能

### 4.3 計画不要

- なし (本 handoff の全 task が一定 scope を持つ)

## 5. 各 task の must_ship / defer_if_over_budget

### 5.1 task-01 (SP-014 batch 0)

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| orchestrator service module + lease/heartbeat/failover/kill | ○ | - |
| policy_profile + 14 rows seed | ○ | - |
| review_artifacts 4 重防御 | ○ | - |
| Tool Registry network enum + tool_network_policies | ○ | tool 登録は SP-018 |
| remote_agent_gateway deny-only stub | ○ | - |
| KPI rollup query + contract test | ○ | adopted_artifacts link は SP-018 |
| SecretBroker 6 negative case | ○ | - |
| event_type 28→37 拡張 | ○ | - |
| progress lease | ○ | tenant_config tuning は SP-022 |

→ 9 must_ship 全件、3 defer_if_over_budget 候補。

### 5.2 task-02 (SP-012-8)

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| navigation.tsx 日本語化 | ○ | - |
| tickets/*.tsx 日本語化 | ○ | - |
| approvals/*.tsx 日本語化 | ○ | wiring 未完なら skip 可 |
| agent-runs/*.tsx 日本語化 | ○ | wiring 未完なら skip 可 |
| audit/*.tsx 日本語化 | ○ | - |
| settings/*.tsx 日本語化 | ○ | - |
| common UI 文言 (error / loading) | ○ | - |
| accessible-name 維持確認 | ○ | - |

→ 8 must_ship、3 defer_if_over_budget 候補。

### 5.3 task-03 (SP-022-1)

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| `--mac-mode` flag 実装 | ○ | - |
| `--remote` 引数バリデーション強化 | ○ | - |
| Layer C operator runbook §1-§9 | ○ | §10 以降は SP-022-2 |
| sanitizer ruleset 強化 (dogfooding_seed.py) | △ | scope 外、SP-018 |
| compose healthcheck timeout 調整 | ○ | - |
| Dockerfile.eval COPY 順序 | ○ | - |
| §13 grep coverage SOP polish | ○ | - |

→ 6 must_ship、1 defer 候補。

### 5.4 task-04 (SP-012-9 残 wiring)

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| Approvals page wiring (list + detail) | ○ | mutation (approve/reject) は SP-018 |
| Agent Runs page wiring (list + detail) | ○ | resume/cancel mutation は SP-018 |
| Audit page wiring (list + filter) | ○ | export は SP-018 |
| Settings page wiring (project 切替 + provider) | △ | provider config は SP-018 |
| BL-TCU-007 (ApprovalRequest auto trigger) | × | **multi-user 化後** (P0.1+) |

→ 3 must_ship、2 defer。

## 6. 各 task の DoD checklist

各 task の DoD checklist は **`tasks/task-NN-*.md` の §DoD checklist** に詳細を記述。本 matrix では abbreviated form のみ。

### 6.1 共通 DoD (全 task 共通)

- [ ] ruff check + mypy backend clean (backend 変更時)
- [ ] pnpm typecheck + lint + vitest clean (frontend 変更時)
- [ ] uv run pytest 該当 test PASS
- [ ] migration 含む場合: alembic check + Mac local upgrade head 確認
- [ ] PR description に invariant trace + verification 結果
- [ ] Codex auto-review baseline 確認 (`codex_pr_full_review.sh <PR>`)
- [ ] Codex finding 採否判定 (adopt/reject/defer) で clean 達成
- [ ] Sprint Pack frontmatter status 更新 (`completed` 化 + Review 章追加)

## 7. blocker / 緊急停止 trigger (`00-codex-behavior-guide.md` §12)

各 task で以下を検知したら **`STOPPED.md` 起票** + 即停止:

- Codex 3 連続失敗
- spec 衝突 (本 handoff file 同士、または既存 rules / Sprint Pack)
- ADR Gate Criteria 11 種該当変更が必要 (本 handoff scope 外)
- Mac local stack 不可逆破壊 (DB schema rollback 不能等)
- 想定 effort 大幅超過 (3 day 内に完遂不可能 pattern が確実)

## 8. 完了報告 format (`00-codex-behavior-guide.md` §11)

各 task 完了時に:

- `docs/codex-handoff/2026-05-22-3day-autonomous/completion/task-NN-completed.md` 起票
- PR list / Codex finding 採否 / defer / blocker / Claude verification 依頼項目

3 日間終了時に:

- `docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md` 起票
- handoff memory `project_session_2026_05_25_codex_3day_complete.md` 起票
- MEMORY.md index 1 行追加
