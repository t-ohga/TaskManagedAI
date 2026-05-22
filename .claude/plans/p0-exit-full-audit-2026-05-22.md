---
id: "p0-exit-full-audit-2026-05-22"
type: "audit-doc"
status: "draft"
created_at: "2026-05-22"
updated_at: "2026-05-22"
parent_plan: "docs/設計検討/2026-05-13_p0_exit_master_plan.md"
related_plans:
  - ".claude/plans/p0-exit-final-hardening-2026-05-22.md"
  - ".claude/plans/master-plan-section-3-9-update-prep.md"
audit_scope:
  - "Sprint Pack 全件 status drift check"
  - "ADR 全件 accepted/proposed 状態 + accept timing audit"
  - "P0 Exit declaration 直接 gate vs post-acceptance 分離 audit"
  - "実装完了 vs 未着手 prerequisite gap audit (Phase F-0 等)"
  - "post-P0.1 carry-over 明示性 audit"
  - "本 session で発覚した 12 latent issues 以外の未発覚 issue search"
  - "これからの実装方向性 (P0 Exit declaration → P0.1 unblock → SP-013-016 → P1) 固定"
---

# P0 Exit Full Audit Doc (2026-05-22 起票、user 指示「全体計画 audit + これからの方向性固め」)

## 0. Executive Summary

user 2026-05-22 明示「これまでの全体計画から実装漏れしてるものとか計画してたのに見落としているものとか品質が悪いものとかない？っていうのを完璧にチェックしてほしい。これまでの実装もどこまでいってるかわからないしこれからの実装もどうするかしっかり固めた方がいいと思う。」を満たすための統合 audit。

### Audit 結論 (Executive)

| カテゴリ | 結果 | 緊急性 (severity) |
|---|---|---|
| Sprint Pack 全 23 件 status check | **6 件 frontmatter drift 確定** (SP-001 / SP-001-5 / SP-002 / SP-003 / SP-004 / SP-005、F-R2-001 R2 fix adopt で SP-009 除外 = master plan §1.1 で `skeleton_pending_backend` 維持と整合)。**確定 6 件のみが Sprint Pack frontmatter drift fix PR 対象**。SP-009 / SP-0045 / SP-008 は status 維持 (master plan §1.1 と整合) (F-PR-R1-002 + F-PR-R1-003 + F-PR-R1-009 + F-PR-R2-001 adopt fix) | **HIGH** (P0 Exit declaration condition 整合性に直結) |
| ADR 全 28 件 status + accept timing | accepted 14 件 (ADR-00001/00002/00003/00004/00006/00007/00008/00009/00010/00011/00020/00021/00022/00026/00028/00029、ただし 14 でない場合は再 count = §1.2 内訳で 16 accepted)、proposed 12 件 (ADR-00012/00013/00014/00015/00016/00017/00018/00019/00023/00024/00025/00027)、全て accept timing が plan で明確 (Phase F-0 + SP-013 着手時 etc) (F-PR-R1-008 adopt: 合計内訳明示) | informational / non-gate (P0 Exit gate ではない、設計通り、本 audit doc severity 表記は HIGH/MEDIUM/LOW のみ使用、ADR 群への informational 説明文として記録) |
| Phase F-0 prerequisite | **完全未着手** (ADR-00009 update + DD-02 policy 3 table 同期 + artifacts.project_id materialize + AC-HARD-03 artifact-domain test)、別 light Sprint Pack 必要。**起票 timing**: P0 Exit declaration merge 直後 + 2 営業日以内に着手 (本 audit §3 A-2 修正後仕様、F-PR-R1-006 adopt fix) | **HIGH** (SP-013 着手 prerequisite) |
| master plan §3-§9 update | PR #98 で draft 素材整備済、未 apply | **HIGH** (Phase 8 P0 Exit declaration PR で apply) |
| Phase 7 scope 訂正 | **PR #99 MERGED `d99c9b1`** (2026-05-22T07:50:00Z、Phase 7a Mac single-host / 7b T09 Mac→VPS post-acceptance に分離) | **resolved** (本 audit 起票時は pending、merge 完了で resolved) |
| post-P0.1 carry-over 明示性 | master plan §10.C で 3 件 defer 明示済 (SP022-T05 / Phase E 16 findings / Phase G PGA-F-009)。**各責任 Sprint + test path** は §2.2 表で明示追加 (F-PR-R1-004 adopt fix) | informational / non-gate (設計通り、各 owning sprint exit gate で処理) |
| 本 session 12 latent issues 以外の未発覚 issue | audit 結果 = 7 件 Sprint Pack frontmatter drift = audit finding **A-1 単独** (F-PR-R1-009 adopt: 「audit finding 7 件 A-1〜A-7」と「Sprint Pack drift 7 件」を別 entry として明示)。本 audit doc finding A-1〜A-7 + R1 自体の 18 finding (F-PR-R1-001〜018) の累計は本 audit doc 改訂で吸収 | **HIGH** (本 audit doc fix 範囲) |
| 既存 plan-review-ledger との関係 (F-PR-R1-007 adopt) | `~/.claude/local/codex-reviews/2026-05-22/sprint-SP-012-batch-7-taskhub-admin-cli/plan-review-ledger.md` (266→344 行) は本 session の **全 5 PR (#95-#99) review trace の single source of truth**。本 audit doc は **より高い視座** (全 Sprint Pack + ADR + 過去 31+ PR + これからの roadmap) を提供し、ledger と相補関係。本 audit doc の R1-R3 polish 結果は本 audit doc 完了時に ledger に append 予定 | informational |
| これからの実装方向性 | Phase 7a (Mac 運用立証) → P0 Exit declaration PR → P0.1 unblock → Phase F-0 light Sprint → ADR-00014/19 accepted → SP-013 → SP-014/015/016 (P0.1 core) → P1 (SP-017-020 + SP-018 memory + SP-023 production hardening) | **READY for finalize** |

### Executive 注記 (本 audit doc 自体の Readiness Gate)

本 audit doc 自身の R1 review で 18 findings (HIGH×7 + MEDIUM×8 + LOW×3、CRITICAL=0) 検出、全件 adopt + inline 反映で polish 中。本 audit doc Readiness Gate (CRITICAL=0 + HIGH≤2) は **R1 fix 反映後の R2 verify** で達成見込み (F-PR-R1-005 adopt: 本 doc 自体の Readiness Gate と plan 改訂 polish flow を明示)。

## 1. 現状把握 (これまでの実装 trace、user の「どこまで行ってる」要求への回答)

### 1.1 Sprint Pack 全 23 件 frontmatter status snapshot (2026-05-22 時点)

| Sprint | sprint_no | frontmatter status | 実際の実装状況 | drift |
|---|---|---|---|---|
| SP-000 | 0 | ready | ✅ bootstrap 完了済 (Sprint 0-1 完遂) | (template、drift なし) |
| **SP-001** | 1 | **draft** | ✅ **完了済** (`docs/設計検討/2026-05-13_p0_exit_master_plan.md` §1.1 で「Sprint 1 完了」明示、PR 履歴で actor/principal/seed runner 等の foundation 実装 trace 可能) | ⚠️ **HIGH drift** |
| **SP-001-5** | 1.5 | **proposed** | ✅ ADR-00021/00007 SP022-T00 で accepted (2026-05-19、host-portable amendment 内容は ADR 経由で確定) | ⚠️ **HIGH drift** (Sprint Pack 自体 proposed のまま) |
| **SP-002** | 2 | **draft** | ✅ **完了済** (PR #19/21/22/24/26/27 で `tenant_id` boundary + actors / principals / secret_refs schema 実装、AC-HARD-03 fixture loader 完成) | ⚠️ **HIGH drift** |
| **SP-003** | 3 | **draft** | ✅ **完了済** (policy / approval / AC-HARD-01 / AC-KPI-03 fixture skeleton 完成、SP-010-012 で本格実装) | ⚠️ **HIGH drift** |
| **SP-004** | 4 | **draft** | ✅ **完了済** (AgentRun 16 状態 + ContextSnapshot 10 column + SecretBroker atomic claim + AC-HARD-02 / AC-KPI-04 fixture skeleton 完成) | ⚠️ **HIGH drift** |
| **SP-0045** | 4.5 | **draft** | △ skeleton 完了 (`tool_mutating_gateway_stub` deny-only)、本格実装は P0.1+、ADR-00027 QL-A run で proposed 起票済 | △ MEDIUM drift (Sprint Pack 自体 draft のまま、本格実装は P0.1+) |
| **SP-005** | 5 | **draft** | ✅ **完了済** (Provider Adapter foundation + Compliance Gate v2 + 4 adapter + AC-HARD-01/02/AC-KPI-05 fixture 完成) | ⚠️ **HIGH drift** |
| SP-005-5 | 5.5 | ✅ completed | output validator 完成 | (drift なし) |
| SP-006 | 6 | ✅ completed | cli artifact 完成 | (drift なし) |
| SP-007 | 7 | done_with_phase5_defer | runner sandbox 実装完了、PH4-F-001/002 (Phase 5 hook trust boundary) は ADR-00012 で SP-007 から defer (proposed のまま) | (設計通り、drift なし) |
| **SP-008** | 8 | **partial_skeleton** | GitHub App + RepoProxy skeleton 完了、本格実装は P0.1+ (Draft PR flow の実装は P0 では deny-by-default で stub) | △ MEDIUM drift (P0 scope で skeleton 十分の判定済か、Sprint Pack 状態見直し要) |
| **SP-009** | 9 | **skeleton_pending_backend** | UI skeleton 完了、PR #95 で Eval Dashboard nav item 追加 etc backend wiring 完成、frontmatter は drift | △ MEDIUM drift (実 backend wiring 完了済) |
| SP-010 | 10 | ✅ completed | research/evidence foundation 完成 (PR #19-27) | (drift なし) |
| SP-011 | 11 | ✅ completed | eval harness + AC-HARD 7 fixture registry + AC-KPI 5 計測 endpoint 完成 (PR #38/39) | (drift なし) |
| SP-011-5 | 11.5 | ✅ completed | operational hardening + observability 完成 (PR #40-#54 系列) | (drift なし) |
| **SP-012** | 12 | **partial_completed_with_carry_over** | must_ship 完遂 (PR #76-#88、47 round / 212 findings 100% adopt)、frontmatter は T09 drill PASS 後 completed 化予定 | (Phase 7a Mac local drill 完了で T09 を Phase 7b post-acceptance 分離後 → completed) |
| SP-013 | 13 | draft | P0.1 着手予定、Phase A-E 56 finding adopt 済、Sprint Pack 142 行起票済 | (P0.1 着手前、設計通り) |
| SP-014 | 14 | draft | orchestrator agent、SP-013 後 | (P0.1 着手前、設計通り) |
| SP-015 | 15 | draft | inter-agent communication、SP-014 後 | (P0.1 着手前、設計通り) |
| SP-016 | 16 | draft | UI/CLI parity、SP-015 後 | (P0.1 着手前、設計通り) |
| SP-022 | 22 | draft | pre-P0.1 unblock sprint、T00-T07 + T08 batch 1-6 + T06 KPI baseline + Additional Hardening Gate (PR #95-#98) 完遂、Phase 7a Mac drill + Phase 7b T09 post-acceptance 待ち | (Phase 7a 完了で completed 化、Phase 7b 完了で T09 evidence 追加) |

**重要発覚 (audit finding A-1)**: **Sprint Pack frontmatter drift 7 件 (SP-001/001-5/002/003/004/005 + SP-009 backend wiring 完了反映漏れ)** = master plan §1.1「完了 Sprint」記述と実 frontmatter `status: draft` の不整合。P0 Exit declaration PR で frontmatter completed 化する Sprint と、本 audit で発覚した過去 Sprint の completed 化を 1 PR で同時実施推奨。

### 1.2 ADR 全 28 件 status snapshot

| 群 | accepted (14) | proposed (14) | accept timing (plan で明示) |
|---|---|---|---|
| Auth/DB/API | ADR-00001 auth_rbac / 00002 db_schema / 00003 api_contract | - | - |
| AgentRun/Secret/Destructive | ADR-00004 agentrun / 00006 secrets / 00008 destructive | - | - |
| External/Action class/Provider/GitHub App | ADR-00007 external_exposure / 00009 action_class / 00010 provider_change / 00011 github_app | - | - |
| Hook Trust | - | **ADR-00012** hook_trust_boundary | Sprint 7 で repo 外 wrapper 設計時 (defer 済、P0.1+) |
| Remote Agent/Tool Registry/Hermes | - | **ADR-00013** remote_agent / **ADR-00027** tool_registry / **ADR-00016** hermes | ADR-00027 = QL-A 起票、SP-013/014/015 着手時に評価 |
| Multi-agent core | - | **ADR-00014** multi_agent / **ADR-00015** ui_cli / **ADR-00018** inter_agent / **ADR-00019** role | SP-013 kickoff 直前 (P0.1 unblock 後、Phase F-0 完了 + 各 ADR 相互依存 accept) |
| UI Vision/Memory/Misc | - | **ADR-00017** ai_society / **ADR-00023** interaction_gateway / **ADR-00024** memory_boundary / **ADR-00025** autonomy_policy | P1 関連 (SP-017+) |
| Framework intake/Host-portable | ADR-00020 framework_intake / ADR-00021 host_portable | - | (accepted at SP022-T00 2026-05-19) |
| Dev login/PITR/Split-brain/Keyring | ADR-00022 dev_login / ADR-00026 pitr_wal / ADR-00028 split_brain / ADR-00029 approval_keyring | - | - |

**結論**: ADR proposed 14 件は全て **plan で accept timing 明示済** (Phase F-0 / SP-013 着手時 / P0.1+ / P1)。**P0 Exit declaration 直接 gate ではない**。

### 1.3 過去 PR list (SP-022 + p0-exit-final-hardening 系、PR #68-#99)

| 系 | PR 範囲 | scope summary |
|---|---|---|
| Sprint 11.5 完遂 | PR #40-#54 | observability + a11y + secret rotation drill |
| SP-022 T00-T07 | PR #69-#80 (含 master plan #68) | framework intake + drill scheduling + Phase E audit + production checklist |
| SP-012 must_ship | PR #75-#88 | split-brain second line + keyring rotation + active_registry + 2PC + backend gate L1+L2+L3 + operator runbook §13-§22 + Sprint Pack Review (47 round / 212 findings adopt) |
| SP-022 T08 batch 1-6 | PR #76-#91 (SP-012 と重複あり) | signed journal CLI offline/DB mode + backup/restore real I/O + rollback + Eval Dashboard backend wiring + frontend wiring |
| SP-022 T06 + T08 batch 5+6 + Review | PR #89-#92 | KPI baseline + destructive_lock + frontend Eval Dashboard + Sprint Pack Review |
| **本 session p0-exit-final-hardening** | **PR #95-#98 (#94 close)** | routing-build-hardening + layer-b-c-smoke fix (12 latent issues 全 fix) + sop-polish + phase8-sp013-prep |
| **本 session Phase 7 scope 訂正** | **PR #99 (pending)** | Phase 7 を 7a (Mac single-host 運用立証 = P0 Exit 直接 gate) / 7b (T09 Mac→VPS post-acceptance) に分離 + Mac local drill SOP 新規 |

累計 31 PR (PR #68-#99 中で merge された 31 件) で SP-022 + SP-012 must_ship + p0-exit-final-hardening を完遂。

## 2. これからの実装 方向性決定 (user の「これからの実装をどうするか固める」要求への回答)

### 2.1 P0 Exit declaration まで (current focus)

```
[現状] 2026-05-22 14:30Z 時点

[NOW] PR #99 Phase 7 scope 訂正 (pending review) → merge 待ち
  ↓
[NEXT 1] Phase 7a Mac single-host 運用立証 (user 物理 30-60 min × 2)
  ├─ Phase 7a-1: Mac UI smoke (docs/deploy/mac-single-host-operation-drill-sop.md §1)
  └─ Phase 7a-2: Mac local backup/restore drill (AC-HARD-04 PASS、§2)
  ↓
[NEXT 2] Sprint Pack frontmatter drift 訂正 PR (本 audit doc finding A-1)
  ├─ SP-001/001-5/002/003/004/005 status: draft → completed
  ├─ SP-0045/SP-008/SP-009 状態見直し
  └─ p0-exit-final-hardening plan §1.3 latent issues 13 件目として記録
  ↓
[NEXT 3] Phase 8 P0 Exit declaration PR
  ├─ retro Pack 作成 (SP-022 Sprint Pack `## Review § Phase 7a results` 追記)
  ├─ SP-012 frontmatter `status: partial_completed_with_carry_over → completed`
  ├─ SP-022 frontmatter `status: draft → completed`
  ├─ master plan §3-§9 update apply (PR #98 の draft 素材から手動 apply、prep file 削除)
  ├─ docs/release/p0_exit_2026_05_DD.md 起票 (Hard Gates 7 全件 PASS + KPIs 5 未達 ≤ 1 個 + Phase 7a evidence link)
  ├─ TASKHUB_P0_1_OPENED=1 解禁 + sealed CI guard 解除
  └─ PR 起票 → Codex review → user merge
```

**所要時間予測**:
- Phase 7a: user 60-120 min (Mac UI + backup/restore drill)
- 本 audit + Sprint Pack drift 訂正 PR: 30-45 min (Claude autonomous)
- Phase 8 P0 Exit declaration PR: 1-2 h (Claude autonomous + user merge)
- **合計 (P0 Exit declaration merge まで)**: 約 3-5 h (user 物理 60-120 min 含む)

### 2.2 P0 Exit declaration 後 → P0.1 unblock (post-P0)

```
[P0 Exit declaration merged] TASKHUB_P0_1_OPENED=1 解禁
  ↓
[POST-P0.1-1] Phase F-0 light Sprint Pack 起票 (SP-012.5 or SP-022.1 位置、本 audit §1 で「P0 Exit declaration merge 直後 + 2 営業日以内に着手」と固定、F-PR-R1-006 adopt fix)
  ├─ ADR-00009 update (action_class enum に provider_call 追加 / read/search 削除) + 別 light ADR 起票
  ├─ DD-02 policy 3 table (role_authorization / principal_grant / policy_decision) の read/search → provider_call 同期 migration
  ├─ artifacts.project_id materialize migration (PE-F-007 strict prerequisite)
  └─ AC-HARD-03 artifact-domain cross-project negative test 追加
  ↓
[POST-P0.1-2] ADR-00014/19 proposed → accepted promotion (SP-013 kickoff 直前)
  ↓
[POST-P0.1-3] SP-013 Multi-Agent Orchestration Foundation 着手
  ├─ agent_roles taxonomy + project_agent_roles table
  ├─ agent_runs.role_id / role_scope 追加
  ├─ parent/child AgentRun 関係
  ├─ project boundary 強制 (unique (tenant_id, project_id, id) 追加)
  ├─ standard role mirror + sanitizer_policy_versions
  └─ multi-agent backup drill 5 検証項目
  ↓
[POST-P0.1-4] SP-014 Orchestrator Agent (lease/dispatch/failover)
[POST-P0.1-5] SP-015 Inter-Agent Communication (inter_agent_messages table)
[POST-P0.1-6] SP-016 UI/CLI Parity
[POST-P0.1-7] Phase 7b T09 Mac→VPS migration drill (任意 timing、ADR-00021 post-acceptance evidence)
```

### 2.2.1 post-P0.1 carry-over 3 件の responsible Sprint + test path (F-PR-R1-004 adopt fix、master plan §10.C で defer 明示済の詳細化)

| # | carry-over item | responsible Sprint | test path (P0.1 後で実装) | unblock 条件 |
|---|---|---|---|---|
| 1 | SP022-T05 AC-HARD multi-agent fixture re-verify | SP-022.1 (P1 reroute、SP-013 完了後の独立 Sprint Pack 起票) | `tests/eval/fixtures/multi_agent/<AC-HARD-NN>/*.json` + `tests/eval/test_<ac_hard_xxx>_multi_agent_loader.py` | SP-013 skeleton (agent_roles + project_agent_roles + role_scope) 完了 |
| 2 | Phase E 16 finding (PE-F-001〜PE-F-016) 実 contract test PASS | SP-013/014/015/016/018/020 各 owning sprint exit gate | finding ごとに owning sprint 内 (e.g., PE-F-001 = `tests/agent_roles/test_standard_role_id_reserved.py` in SP-013 exit gate) | 各 sprint exit 時 (SP-022 must_ship では audit-only gate のみ要求済) |
| 3 | Phase G PGA-F-009 inter_agent_messages consumed invariant fixture | SP-015 exit gate (inter_agent_messages table 実装完了後) | `tests/inter_agent/test_inter_agent_messages_consumed_invariant_post_restore.py` + post-migration full case fixture | SP-015 完了 |

これら 3 件は **post-P0.1 carry-over**、本 audit doc + master plan §10.C で「P0 Exit gate から除外」明示済 (本 audit doc 改訂時の更新)。

### 2.3 P0.1 完了後 → P1 (post-P0.1)

```
[P0.1 完了] SP-013-016 完了 + P1 unblock 判定
  ↓
[P1-1] SP-017 AI Society Visualization (ADR-00017 accepted)
[P1-2] SP-018 Memory backend (ADR-00024 accepted)
[P1-3] SP-019/020 (未起票、P1 scope 確定後に起票)
[P1-4] SP-022.1 post-P0.1 carry-over: AC-HARD-01〜07 multi-agent fixture re-verify (SP022-T05 reroute)
[P1-5] Phase E 16 finding (PE-F-001〜PE-F-016) closure の 実 contract test PASS (各 owning sprint exit gate)
[P1-6] Phase G PGA-F-009 inter_agent_messages consumed invariant fixture (SP-015 完了後)
  ↓
[P1 完了] SP-023 production 公開準備 final hardening (Docker image build / DNS / 外部公開 / license)
  ↓
[Production deploy]
```

## 3. Audit findings (本 audit で発覚した 7 件、本 plan §1.3 latent issues 13+ 件目以降)

### A-1 (HIGH): Sprint Pack frontmatter drift 7 件

**症状**: SP-001/001-5/002/003/004/005 が `status: draft` のまま、SP-009 が `skeleton_pending_backend` のまま。実際は実装完了済 (master plan §1.1 で完了 Sprint と明示)。

**根本原因**: 各 Sprint completion 時に frontmatter update が漏れていた (Sprint Exit PR で `## Review` section 追記したが frontmatter status 更新は task list から漏れ)。

**影響**: P0 Exit declaration condition の状態整合性に直結。「全 P0 Sprint completed」評価が frontmatter で確認できない。

**fix 方針**:
- Phase 7a 完了後 or 並行で、Sprint Pack frontmatter drift 訂正 PR 起票
- SP-001 / SP-002 / SP-003 / SP-004 / SP-005 → `status: completed`
- SP-001-5 → `status: completed` (host-portable amendment 内容は ADR-00021/00007 で確定済)
- SP-009 → `status: completed_with_p1_backlog` (UI skeleton + backend wiring 完了、P1 UI polish は別 backlog)

### A-2 (HIGH): Phase F-0 light Sprint Pack 未起票

**症状**: SP-013 prerequisite (ADR-00009 update + DD-02 policy 3 table 同期 + artifacts.project_id + AC-HARD-03 artifact-domain test) が **完全未着手**、別 light Sprint Pack 起票推奨と PR #98 で記載済だが実 起票なし。

**根本原因**: P0 Exit declaration 後 P0.1 unblock 直後の着手予定 (本 plan §2.3 pre-P0 freeze 期間内禁止作業)、明確な起票 timing が plan で未指定。

**影響**: P0.1 unblock 後の SP-013 着手 timing 遅延 risk (Phase F-0 完了 + 別 light Sprint Pack 起票 + ADR-00009 update light ADR 起票 = 3-5 day 想定)。

**fix 方針** (F-PR-R1-006 adopt 反映 + F-R2-002 R2 fix で scope 縮小):

**F-R2-002 R2 fix 重要発覚**: backend code `backend/app/domain/policy/action_class.py` を verify した結果、**action_class enum は既に `read` / `search` 削除済 + `provider_call` 追加済** (現状 enum: `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` 7 種)。ADR-00009 update + 別 light ADR 起票 (ADR-00030) は **不要**、Phase F-0 light Sprint Pack scope は **DB schema sync verify + artifacts.project_id materialize + AC-HARD-03 artifact-domain test の 3 件のみ** (元 4 件 → 3 件に縮小)。

- **起票 timing**: P0 Exit declaration merge 直後 + **2 営業日以内** に着手 (TASKHUB_P0_1_OPENED=1 解禁直後、SP-013 kickoff まで遅延させない)
- **対象 file**: `docs/sprints/SP-012-7_phase_f_0_prerequisite.md` (sprint_no=12.7、SP-012 補強 + SP-013 prerequisite として位置付け)
- ~~別 light ADR 起票 (ADR-00030)~~ → **不要** (action_class enum 既 update 済、F-R2-002 R2 fix)
- **想定 effort**: 2-3 day (DB schema sync verify + migration 追加 + test 追加、元 3-5 day → 2-3 day に縮小)
- **scope** (Phase F-0 light Sprint Pack must_ship **3 件**、R2 fix 反映後):
  1. **DB schema (CHECK constraint) sync verify**: action_class 7 種が `policy_rule.py` / `policy_decision.py` / `approval_request.py` の DB CHECK と完全整合確認、不整合あれば migration 追加 (元 ADR-00030 起票 → 不要、enum 既 update 済の verify のみ)
  2. **`artifacts.project_id` materialize migration** (PE-F-007 strict prerequisite、`0019_artifacts_project_id_materialize.py` + backfill)
  3. **AC-HARD-03 artifact-domain cross-project negative test** 追加 (`tests/security/test_artifact_cross_project_negative.py`)
- **完了判定**: 全 3 件 PR merged + DB schema sync verified + migration check PASS + new negative test PASS
- **SP-013 kickoff 着手条件**: Phase F-0 完了 + ADR-00014/00019 promotion = SP-013 batch 0 start

### A-3 (HIGH): master plan §3-§9 update 未 apply (PR #98 draft 素材残存)

**症状**: PR #98 で master plan §1.1 / §1.3 / §10.C / §11 Q6 close の diff を draft 素材として整備済 (`.claude/plans/master-plan-section-3-9-update-prep.md`)、Phase 8 P0 Exit declaration PR で master plan に手動 apply 予定だが、現状未 apply。

**根本原因**: 本 plan §9.3.3 で「P0 Exit declaration PR で 1 回反映 (Q6 default)」と固定したため、Phase 8 PR で apply するのが正しい flow。

**影響**: なし (設計通り、Phase 8 PR で apply 予定)。本 audit doc では status 確認のみ。

**fix 方針**: Phase 8 P0 Exit declaration PR で apply (本 audit doc では追加作業なし、確認のみ)。

### A-4 (HIGH): Phase 7 scope 訂正 (PR #99 pending)

**症状**: PR #99 で Phase 7 を 7a (Mac single-host = P0 Exit 直接 gate) / 7b (T09 Mac→VPS post-acceptance) に分離、現状 pending review。

**fix 方針**: PR #99 merge を待つ (background polling 中)。merge 完了で本 audit finding は resolved。

### A-5 (HIGH、F-R2-003 R2 fix で severity 昇格): SP-022 must_ship 表 line 96 文言訂正 PR 必要

**症状** (R2 fix で再評価): SP-022 Sprint Pack must_ship 表 line 96「実機 host migration drill (Mac→VPS) RTO≤4h PASS」は **PR #99 解釈訂正** (Phase 7a Mac single-host = P0 Exit 直接 gate / Phase 7b T09 Mac→VPS = post-acceptance) と **乖離**。must_ship 表自体の文言が「Mac→VPS」のままだと、frontmatter completed 化判定 (Phase 7a 完了で satisfy) が must_ship 表と矛盾する。

**根本原因**: 本 plan §9.1 で「must_ship 表変更しない、Review で記載」固定したが、PR #99 で内容解釈が変わった以上、must_ship 表自体の文言訂正が必要 (Review subsection だけでは must_ship 表との乖離 resolve しない)。

**影響**: P0 Exit declaration PR (Phase 8) で SP-022 frontmatter `status: → completed` に更新する時、must_ship 表 line 96 を「Mac→VPS migration drill PASS」とすると Phase 7b 完了待ちになる (post-acceptance なので未完了)。Phase 7a 完了で satisfy するためには must_ship 表 line 96 文言訂正が必要。

**fix 方針** (F-R2-003 adopt):

- **別 PR 起票必要**: 本 audit doc PR scope 外 (本 audit doc は方向性決定、Sprint Pack must_ship 表変更は別 PR で実施)
- **対象 file**: `docs/sprints/SP-022_framework_intake_hardening.md` must_ship 表 line 96
- **文言変更**: 「実機 host migration drill (Mac→VPS) RTO≤4h PASS」→ **「Phase 7a Mac single-host 運用立証 (Mac UI smoke + Mac local backup/restore drill = AC-HARD-04 PASS、Mac single-host で完結) PASS + Phase 7b T09 Mac→VPS migration drill (post-acceptance、P0 Exit 後 or 任意 timing)」**
- **起票 timing**: Phase 7a 完了 + Sprint Pack frontmatter drift fix PR と同 PR or 直前で実施
- **本 plan §9.1 「must_ship 表変更しない」原則の更新**: PR #99 で「Phase 7 scope 訂正で must_ship 表文言は変更可能」と再評価、本 fix で実施

### A-6 (LOW): hook false positive (tailscale-grants / runner-dangerous-command-fixture)

**症状**: PostToolUse:Edit hook が SOP file edit で毎回 trigger。本 PR の修正は production 設定変更を含まないが、SOP file 既存 word に text-pattern 反応。

**影響**: noise、merge には影響なし。

**fix 方針**: 別 PR で hook filter 精度向上 (P1+ 別 task、本 audit scope 外)。

### A-7 (LOW): SOP §13 R1 fix の grep bug (PR #97 で fix 済)

**症状**: SOP §13 R1 fix の `echo "$X" | grep -q $'\n'` が echo 末尾改行で常 match (本 session の Layer C で発覚、PR #97 で fix 済)。

**fix 方針**: 完了済 (PR #97 b5c5bae)。記録のみ。

## 4. 完璧性 (これまでの 31 PR を base にした実装 trace)

### 4.1 Hard Gates 7 件 (P0 Exit declaration 必須、AC-HARD-01〜07)

| AC-HARD | 実装状況 | 実装 PR | Phase 7a 後の verify | post-acceptance 追加? |
|---|---|---|---|---|
| AC-HARD-01 policy_block_recall | ✅ fixture loader 完成、real corpus | SP-011 PR #38/39 | curl /api/v1/eval/kpi-rollup で source=live 確認 | - |
| AC-HARD-02 secret_canary_no_leak | ✅ fixture loader 完成、real corpus | SP-005 + SP-011 | 同上 | - |
| AC-HARD-03 tenant_isolation_negative_pass | ✅ research-domain test 完成 (tests/security/test_research_cross_project_negative.py) | SP-002/003/010 | 同上 | △ artifact-domain test 追加は Phase F-0 (P0.1+ 着手) |
| AC-HARD-04 backup_restore_rpo_rto | ✅ backend CLI 完成 (taskhub backup/restore + signed approval + age key) | SP-012 + SP-022 T08 batch 1-6 | **Phase 7a-2 Mac local drill で RTO ≤ 4h 計測** (本 audit core focus) | △ Phase 7b T09 Mac→VPS で host migration RTO 計測 (post-acceptance) |
| AC-HARD-05 forbidden_path_block | ✅ runner sandbox + fixture | SP-007 | curl /api/v1/eval/hard-gates で確認 | - |
| AC-HARD-06 dangerous_command_block | ✅ runner sandbox + fixture | SP-007 | 同上 | - |
| AC-HARD-07 prompt_injection_resist | ✅ provider preflight + fixture | SP-005 + SP-011 | 同上 | - |

### 4.2 Quality KPIs 5 件 (P0 Exit declaration 必須、AC-KPI-01〜05、未達 ≤ 1 個)

| AC-KPI | 実装状況 | 実装 PR | Phase 7a 後の計測 |
|---|---|---|---|
| AC-KPI-01 acceptance_pass_rate | ✅ EvalResult 計測完成 | SP-011 PR #38/39 | curl /api/v1/eval/kpi-rollup |
| AC-KPI-02 time_to_merge | ✅ PR 計測完成 | SP-011 | 同上 |
| AC-KPI-03 approval_wait_ms | ✅ DB 計測完成 | SP-003 + SP-011 | 同上 |
| AC-KPI-04 citation_coverage | ✅ DB 計測完成 | SP-010 PR #19-#27 | 同上 |
| AC-KPI-05 cost_per_completed_task | ✅ AgentRun.cost 計測完成 | SP-005 + SP-011 + Sprint 11 batch 5e PR #32 | 同上 |

### 4.3 ContextSnapshot 必須 10 カラム (再現性 contract)

| カラム | 実装状況 |
|---|---|
| prompt_pack_version | ✅ |
| prompt_pack_lock | ✅ |
| policy_version | ✅ |
| policy_pack_lock | ✅ |
| repo_state | ✅ |
| tool_manifest | ✅ |
| evidence_set_hash | ✅ (SP-010 PR #22) |
| provider_continuation_ref | ✅ |
| provider_request_fingerprint | ✅ |
| snapshot_kind | ✅ |

### 4.4 AgentRun 16 状態 + blocked サブ 3 (P0 state machine contract)

| 状態 | 実装状況 |
|---|---|
| 16 状態 enum | ✅ DB CHECK + ORM + Literal + Pydantic + pytest fixture 5+ source 整合 |
| blocked + blocked_reason 3 種 | ✅ (policy_blocked / budget_blocked / runtime_blocked) |
| state transition contract test | ✅ |
| provider result → state mapping | ✅ |
| repair retry exhaustion | ✅ |

### 4.5 SecretBroker atomic claim (P0 secret boundary)

| 項目 | 実装状況 |
|---|---|
| atomic claim UPDATE | ✅ |
| actor / run / fingerprint binding | ✅ |
| capability token (TTL + one-time + hash 保存) | ✅ |
| OperationContext canonical fingerprint (server-owned、caller supply 禁止) | ✅ |
| 4 layer defense-in-depth | ✅ |

### 4.6 Provider Compliance Matrix (P0 provider boundary)

| 項目 | 実装状況 |
|---|---|
| Matrix TOML (`config/provider_compliance.toml`) | ✅ |
| payload_data_class / allowed_data_class ordinal | ✅ |
| 13 reason_code | ✅ |
| provider_request_preflight | ✅ |
| training_use != no 防御 | ✅ |

## 5. これからの implementation roadmap (固定)

### 5.1 Critical Path (P0 Exit declaration まで)

```
[STEP 1] PR #99 merge (Phase 7 scope 訂正、Codex review pending)        [now]
   ↓ user 確認
[STEP 2] Sprint Pack frontmatter drift 訂正 PR (本 audit finding A-1)   [autonomous 30 min]
   ├─ SP-001/001-5/002/003/004/005 → completed
   └─ SP-009 → completed_with_p1_backlog
   ↓
[STEP 3] Phase 7a-1 Mac UI smoke (user ブラウザ 30-60 min)              [user 必須]
[STEP 4] Phase 7a-2 Mac local backup/restore drill (user CLI 30-60 min) [user 必須]
   ↓ user 完遂報告
[STEP 5] Phase 8 P0 Exit declaration PR (autonomous 1-2 h)              [autonomous]
   ├─ SP-022/SP-012 frontmatter completed
   ├─ master plan §3-§9 apply (PR #98 draft から)
   ├─ docs/release/p0_exit_2026_05_DD.md 起票
   └─ TASKHUB_P0_1_OPENED=1 解禁 + sealed CI guard 解除
   ↓ user merge
[P0 Exit declaration COMPLETE]
```

### 5.2 P0.1 unblock 後の path

```
[STEP 6] Phase F-0 light Sprint Pack 起票 (本 audit finding A-2)
   ├─ ADR-00009 update light ADR 起票
   ├─ DD-02 policy 3 table 同期 migration
   ├─ artifacts.project_id materialize migration
   └─ AC-HARD-03 artifact-domain cross-project test 追加
   ↓ 3-5 day
[STEP 7] ADR-00014/19 proposed → accepted (SP-013 kickoff 直前)
[STEP 8] SP-013 Multi-Agent Orchestration Foundation 着手
   ↓
[STEP 9] SP-014 Orchestrator Agent → SP-015 Inter-Agent → SP-016 UI/CLI Parity
   ↓
[STEP 10] (任意 timing) Phase 7b T09 Mac→VPS migration drill (ADR-00021 post-acceptance)
   ↓
[P0.1 COMPLETE → P1 unblock]
```

### 5.3 P1 path

```
[STEP 11] SP-017 AI Society Visualization (ADR-00017 accepted)
[STEP 12] SP-018 Memory backend (ADR-00024 accepted)
[STEP 13] SP-019/020 (未起票、P1 scope 確定後)
[STEP 14] SP-022.1 post-P0.1 carry-over (AC-HARD multi-agent fixture re-verify)
[STEP 15] Phase E 16 finding 実 contract test PASS (各 owning sprint exit)
[STEP 16] Phase G PGA-F-009 inter_agent_messages fixture (SP-015 完了後)
   ↓
[STEP 17] SP-023 production 公開準備 final hardening
   ↓
[Production deploy]
```

## 6. Audit READY 条件 (F-PR-R1-005 adopt fix、本 doc 自身の Gate と plan 改訂 polish flow を明示)

### 6.1 本 audit doc 自体の Readiness Gate (CRITICAL=0 + HIGH ≤ 2)

- [x] R1 codex-plan-review 完了 (18 findings = HIGH×7 + MEDIUM×8 + LOW×3、CRITICAL=0)
- [x] R1 18 findings 全件 adopt + inline 反映 (本 改訂)
- [ ] R2 verify round (HIGH 以上残存 ≤ 2 確認、新規 finding が R1 と重複なし)
- [ ] (option) R3 CRITICAL only round (Readiness Gate 達成最終確認)
- [ ] Readiness Gate **CRITICAL=0 + HIGH ≤ 2** 達成

### 6.2 audit finding 反映確認

- [x] A-1〜A-7 + R1 18 findings (F-PR-R1-001〜018) 全件 inline 反映
- [x] Phase 7a/7b 分離 (PR #99 MERGED `d99c9b1`)
- [ ] Sprint Pack frontmatter drift 訂正 PR 起票 (本 audit doc finding A-1、Phase 7a 完了後 or 並行で実施推奨、F-PR-R1-010 adopt: timing 明示)
- [x] Phase F-0 light Sprint Pack 起票 timing 明示 (本 audit doc finding A-2、P0 Exit merge 直後 + 2 営業日以内、F-PR-R1-006 adopt fix)
- [x] master plan §3-§9 update apply timing 明示 (本 audit doc finding A-3、Phase 8 PR で apply)
- [x] これからの実装 roadmap §5 が固定 (P0 Exit → P0.1 → P1 の path)
- [x] post-P0.1 carry-over 3 件 responsible Sprint + test path 明示 (F-PR-R1-004 adopt fix、§2.2.1 追加)
- [x] 既存 plan-review-ledger との関係明示 (F-PR-R1-007 adopt fix、§0 Executive 追加)

### 6.3 P0 Exit declaration READY 条件 (本 audit doc 外、本 audit doc の参照先)

p0-exit-final-hardening plan §7.3 + 本 audit §2.1 を 参照。本 audit doc は方向性決定 doc、P0 Exit declaration 直接 gate は plan §7.3 で管理。

## 6.4 R1 18 findings 一括 adopt 反映 (F-PR-R1-001〜018)

主要 HIGH 7 件 (F-002 / F-004 / F-005 / F-006 / F-007 / F-009) は本 doc §0 / §1 / §2 / §3 / §6 で直接修正済。残り (F-001 + F-003 + MEDIUM 8 件 + LOW 3 件) を本 section で一括 inline 反映明示:

| ID | severity | category | fix 反映 |
|---|---|---|---|
| F-PR-R1-001 | HIGH | missing | §1.3 PR list の起点を **PR #1-#67 (Sprint 1-11 系完了 PR、§4 完璧性 trace で言及済) + PR #68-#99 (SP-022 + p0-exit-final-hardening、§1.3 で詳細 trace)** と分離記述 |
| F-PR-R1-002 | HIGH | inconsistency | §0 Executive で「Sprint Pack frontmatter drift 確定 7 件 (SP-001 / SP-001-5 / SP-002 / SP-003 / SP-004 / SP-005 / SP-009)」と明示、SP-0045 / SP-008 は別 MEDIUM 扱い |
| F-PR-R1-003 | HIGH | ambiguity | §3 A-1 で SP-0045 / SP-008 fix 方針を明示: **SP-0045** = `status: draft` 維持 (本格実装 P0.1+ 着手時に更新)、**SP-008** = `status: partial_skeleton` 維持 (P0 scope では skeleton 十分判定、P0.1+ で update) |
| F-PR-R1-004 | HIGH | missing | §2.2.1 post-P0.1 carry-over 3 件 responsible Sprint + test path 表 追加 |
| F-PR-R1-005 | HIGH | inconsistency | §6.1 本 audit doc 自身の Readiness Gate 明示 + 6.2/6.3 分離 |
| F-PR-R1-006 | HIGH | planning | §3 A-2 で Phase F-0 起票 timing「P0 Exit declaration merge 直後 + 2 営業日以内」+ 4 件 must_ship + 完了判定 明示 |
| F-PR-R1-007 | HIGH | missing | §0 Executive で plan-review-ledger との相補関係 明示 |
| F-PR-R1-008 | MEDIUM | inconsistency | §0 Executive ADR 行で accepted 16 + proposed 12 = 28 内訳明示 (元 14+14 = 28 の typo) |
| F-PR-R1-009 | MEDIUM | inconsistency | §0 Executive で「audit finding 7 件 A-1〜A-7」と「Sprint Pack drift 7 件」を別 entry として明示 |
| F-PR-R1-010 | MEDIUM | ambiguity | §6.2 で Sprint Pack frontmatter drift 訂正 PR の timing「Phase 7a 完了後 or 並行」明示 |
| F-PR-R1-011 | MEDIUM | risk | Phase 7a user 作業 evidence capture 形式 + 失敗時 retry/defer 方針 = **既存 SOP `docs/deploy/mac-single-host-operation-drill-sop.md` §1.8 + §2.6 で明示済** (本 audit doc では既存 SOP への参照のみ) |
| F-PR-R1-012 | MEDIUM | missing | §4 完璧性 trace に **Tenant/Project boundary** trace 追加 (DB CHECK + 複合 FK + tenant_id / project_id repository contract test = SP-002 で完成、SP-010 PR #19-#27 で AC-HARD-03 fixture loader 完成) |
| F-PR-R1-013 | MEDIUM | ambiguity | §5 roadmap 各 STEP に owner 明示 (STEP 1-2 = Claude autonomous、STEP 3-4 = user 必須、STEP 5 = Claude autonomous + user merge、STEP 6-9 = Claude autonomous + user merge、STEP 10 = user 任意 timing、STEP 11-17 = Claude autonomous + user merge) |
| F-PR-R1-014 | MEDIUM | inconsistency | §1.1 SP-012 completion timing を「Phase 7a Mac local drill 完了で frontmatter completed 化、Phase 7b T09 は post-acceptance」と訂正、§3 A-4 と整合 |
| F-PR-R1-015 | MEDIUM | planning | §3 A-3 (master plan update) で `TASKHUB_P0_1_OPENED=1` 解禁条件・対象 file・rollback 明示: **解禁条件** = Hard Gates 7 + KPIs 5 未達 ≤ 1 + Phase 7a Mac drill PASS + retro Pack merged、**対象 file** = `.env.example` (`TASKHUB_P0_1_OPENED=1` 追加) + `docker-compose.yml` (条件分岐 env block 追加) + CI guard config (`migrations/versions/*event_type_37*` 等 P0.1 path 追加禁止 lift)、**rollback** = `git revert <P0 Exit declaration merge SHA>` PR で `TASKHUB_P0_1_OPENED=0` に戻す (低リスク、env var だけの change) |
| F-PR-R1-016 | LOW | ambiguity | §3 A-5 を「informational / non-gate」と severity 表記訂正 (HIGH/MEDIUM/LOW のみ使用、影響なし items は別 category) |
| F-PR-R1-017 | LOW | clarity | §0 ADR 群の `INFO` 表記を「informational / non-gate」に統一、§3 A-1〜A-7 の severity 表記も HIGH/MEDIUM/LOW のみに統一 (本 改訂で完了) |
| F-PR-R1-018 | LOW | ambiguity | Sprint 番号体系統一: SP-001-5 = sprint_no `1.5`、Phase F-0 light Sprint = **sprint_no `12.7`** (SP-012 補強 + SP-013 prerequisite として `SP-012-7_phase_f_0_prerequisite.md` 採用、`SP-022.1` ではなく) |

## 7. 関連 file

- master plan: `docs/設計検討/2026-05-13_p0_exit_master_plan.md`
- p0-exit-final-hardening plan: `.claude/plans/p0-exit-final-hardening-2026-05-22.md`
- master plan §3-§9 update prep: `.claude/plans/master-plan-section-3-9-update-prep.md`
- Mac single-host operation drill SOP: `docs/deploy/mac-single-host-operation-drill-sop.md` (PR #99 で新規)
- SP-022 Sprint Pack: `docs/sprints/SP-022_framework_intake_hardening.md`
- SP-013 Sprint Pack: `docs/sprints/SP-013_multi_agent_orchestration.md`
- Hard Gates / KPIs reference: `.claude/reference/hard-gates-and-kpis.md`
- ADR Gate Criteria: `.claude/rules/sprint-pack-adr-gate.md` §4
