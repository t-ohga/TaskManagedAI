---
id: "SP-013_multi_agent_orchestration"
type: "heavy"
status: "completed"
sprint_no: 13
created_at: "2026-05-10"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 5
max_days: 7
adr_refs:
  - "[ADR-00014](../adr/00014_multi_agent_orchestration.md) # accepted 2026-05-22 (PR #109)、SP-013 kickoff prerequisite satisfied"
  - "[ADR-00019](../adr/00019_role_taxonomy.md) # accepted 2026-05-22 (PR #109)、同上"
planned_adr_refs: []
related_sprints:
  - "SP-014_orchestrator_agent"
  - "SP-015_inter_agent_communication"
  - "SP-016_ui_cli_parity"
risks:
  - "PE-F-001 (custom role が standard role_id を再利用)"
  - "PE-F-012 (constraint trigger だけで cross-project role reference を防げない可能性)"
kickoff_readiness:
  prerequisite_p0_exit: "✅ satisfied (PR #103、2026-05-22)"
  prerequisite_phase_f0: "✅ satisfied (SP-012-7 PR #106/#107/#108、action_class enum + artifacts.project_id materialize + AC-HARD-03 artifact-domain test)"
  prerequisite_pe_f007_artifacts_project_id: "✅ satisfied (PR #107 migration 0019_artifacts_project_id apply 済)"
  prerequisite_adr_00014_accepted: "✅ satisfied (PR #109、2026-05-22)"
  prerequisite_adr_00019_accepted: "✅ satisfied (PR #109、2026-05-22)"
  kickoff_blocker: "なし"
  recommended_execution: "codex-all-loops mode=code 委譲 (heavy Sprint Pack、Claude orchestrator + Codex 実装 + adopt/reject/defer 判定 + 品質ゲート)"
---

最終更新: 2026-05-22 (kickoff readiness attestation、prerequisite 全件 satisfied、draft → ready 昇格)

## 目的

P0.1 multi-agent orchestration の **foundation table 群** を導入し、後続 SP-014 (orchestrator) / SP-015 (inter-agent) / SP-016 (UI/CLI parity) の DDL 前提を確立する。具体的には agent_roles taxonomy + project_agent_roles + agent_runs.role_id/role_scope + parent/child 関係 + project boundary 強制 (`unique (tenant_id, project_id, id)` 追加) + standard role mirror + sanitizer_policy_versions.

## 背景

- Phase A-E (research + plan-review + adversarial) で 56 finding 全件 adopt 済 (Phase C draft `docs/設計検討/phase-c-multi-agent-spec-draft.md`)
- ADR-00014 + ADR-00019 を本 Sprint 着手時に proposed → accepted 化
- 既存 invariant (AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance / SecretBroker / Approval 4 整合 + decider human-only / 既存 action_class 7 種 / id=uuid + tenant_id=bigint / 3 gateway) すべて不変
- Phase F-0 (DD-02 policy 3 table の `read/search` 削除 + `provider_call` 追加) を **本 Sprint 着手前に完了** が前提

## 対象外

- orchestrator agent 本体実装 (SP-014)
- inter_agent_messages table (SP-015)
- CLI 実装 (SP-016)
- memory backend (SP-018)
- Tool Registry network_access enum 化 (P0.1 別 ADR、SP-014 で実装)

## 設計判断

- **role_scope DB 防御**: 案 A (constraint trigger) を default、SP-013 着手時に link table 案 B も並行検討、PoC 比較で最終決定 (PE-F-012)
- **STANDARD_ROLE_IDS reserved namespace**: custom role_id として reject (PE-F-001、DB unique 違反 + service guard)
- **artifact project boundary**: Phase F-0 で artifacts.project_id materialize migration を投入後に SP-013 着手 (PE-F-007 strict prerequisite)
- **multi-agent backup drill**: 5 検証項目 (parent/child AgentRun FK / agent_roles soft-delete reference / standard mirror / sanitizer_policy_versions / audit_events correlation) を SP-013 must_ship

## 実装チケット

- SP013-T01: project_agent_roles + standard_role_ids_mirror table + migration
- SP013-T02: agent_runs に role_id / role_scope / orchestrator_lease_* / progress_lease columns 追加 + `unique (tenant_id, project_id, id)` 追加
- SP013-T03: check_project_role_link() trigger 関数 + agent_runs 拡張 trigger
- SP013-T04: standard_role_ids_mirror seed migration (10 standard roles immutable)
- SP013-T05: sanitizer_policy_versions table + initial seed (`v1.0.0`)
- SP013-T06: artifacts backfill migration 6 段階 (Phase F-0 続き or SP-013 内、PE-F-007 fix)
- SP013-T07: domain layer (taxonomy.py + extension.py) + 5+ source 整合 enforce
- SP013-T08: contract test 群 + 5 検証項目 backup drill

## タスク一覧

- [ ] SP013-T01-T08 を順次実装
- [ ] migration `00NN_p0_1_multi_agent_foundation.py` の `alembic check` PASS
- [ ] cross-tenant + cross-project negative test 全件 deny verify
- [ ] Phase E PE-F-001/007/012 mitigation contract test PASS
- [ ] 5 検証項目 backup/restore drill staging 実施

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| project_agent_roles + agent_runs 拡張 | ○ | - |
| constraint trigger (案 A) | ○ | 案 B link table は SP-014 まで defer 可 |
| STANDARD reserved namespace | ○ | - |
| sanitizer_policy_versions | ○ | seed のみ、Wave 19 で本格化 |
| artifacts backfill migration | ○ | Phase F-0 で投入済の場合は本 Sprint 不要 |
| 5 項目 backup drill | ○ | - |
| frontend agent-roles viewer | × | SP-017 で実装 |

## 受け入れ条件

- agent_roles taxonomy 5+ source (Python Literal + Pydantic + pytest + frontend + DB mirror) で完全一致
- STANDARD_ROLE_IDS と同名 custom role 作成試行 → 全件 reject
- agent_runs.role_scope='project' で role_id が project_agent_roles に存在しない場合 → trigger reject
- agent_runs.role_scope='global' で role_id が STANDARD_ROLE_IDS_MIRROR に存在しない場合 → application layer reject
- cross-tenant role reference 全件 deny
- cross-project role reference 全件 deny (PE-F-012 mitigation)
- artifacts に project_id NOT NULL + unique (tenant_id, project_id, id) 完了
- backup/restore drill 5 項目 verify

## 検証手順

```bash
# Phase F-0 完了確認
uv run pytest tests/db/test_action_class_enum.py tests/policy/test_initial_policy_matrix.py -q

# SP-013 contract test
uv run pytest tests/multi_agent/test_role_taxonomy_enum.py \
              tests/multi_agent/test_role_orthogonal_to_capability.py \
              tests/multi_agent/test_project_custom_role_db_defense.py \
              tests/multi_agent/test_artifact_cross_project_negative.py \
              tests/db/test_schema_introspection.py \
              tests/security/test_tenant_isolation_negative.py \
              tests/db/test_backup_restore_multi_agent_foundation.py -q

# migration check
uv run alembic check
uv run alembic upgrade head
uv run alembic downgrade -1 && uv run alembic upgrade head  # rollback round-trip
```

## レビュー観点

- DDL の複合 FK pattern が DD-02 と完全整合 (`(tenant_id, project_id, foreign_id) references <table>(tenant_id, project_id, id)`)
- standard_role_ids_mirror が immutable (HARD DELETE 不可 trigger) で seed
- constraint trigger が tenant_id / project_id 更新でも発火 (PE-F-012)
- artifacts backfill 6 段階の各 Step assert (NULL=0 件 確認)
- `eval/multi_agent/role_authorization_negative/` AC-HARD 候補 fixture 投入

## 残リスク

- PE-F-012 (constraint trigger 案 A) の edge case: agent_run の row_locked update で trigger 二重発火 → SP-014 で link table 案 B に切替判断
- artifacts backfill の global artifact 扱い (案 A2 = 別 table 分離) の implementation cost
- 5 項目 backup drill の RTO ≤ 4h 達成性 (multi-agent table 増加の影響)

## 次スプリント候補

- SP-014 orchestrator agent (lease/dispatch/failover)
- (defer 時) SP-013-extra: link table 案 B PoC

## 関連 ADR

- ADR-00014 (Multi-Agent Orchestration Foundation) — proposed → accepted at SP-013 kickoff
- ADR-00019 (Role Taxonomy) — proposed → accepted at SP-013 kickoff
- ADR-00009 update (DD-02 enum 同期) — Phase F-0 で前提

## Review

(SP-013 完了時に追記: changed / verified / deferred / risks)

## P0.1 Unblock 前提 prerequisite status (2026-05-22 prep、prep/phase8-sp013-2026-05-22 PR)

SP-013 着手前に **以下 prerequisite が全件 accepted / completed であること**。本表は p0-exit-final-hardening-2026-05-22 plan の Phase 8 P0 Exit declaration 完了後、SP-013 kickoff 直前に再 verify。

### 1. P0 完了 prerequisite (SP-022 完遂)

| 項目 | 状態 (2026-05-22 prep 時点) | unblock 条件 |
|---|---|---|
| SP-022 T01-T07 完了 | ✅ PR #69-#80 全 merged | - |
| SP-022 T08 batch 1-6 完了 | ✅ PR #76,#77,#78,#79,#90,#91 全 merged | - |
| SP-022 T06 Mac KPI baseline | ✅ PR #89 merged | - |
| Additional Hardening Gate (p0-exit-final-hardening 12 latent fix) | ✅ PR #95+#96+#97 全 merged | - |
| SP-022 T09 host migration drill (Mac→VPS、RTO≤4h) PASS | ⏳ user 物理作業待ち | 物理 host 2 台 + Tailscale 閉域 + age key + signed approval |
| SP-022 frontmatter `status: → completed` | ⏳ T09 drill 完了後 | T09 completion evidence |
| SP-012 frontmatter `status: → completed` (partial_completed_with_carry_over から昇格) | ⏳ T09 drill 完了後 | T09 completion evidence |

### 2. ADR acceptance prerequisite (SP-013 kickoff 直前に proposed → accepted 化)

ADR-00014 frontmatter `acceptance_blocked_by` の全件解消条件:

| ADR | 現状 status | acceptance_blocked_by | 解消方法 |
|---|---|---|---|
| ADR-00014 (Multi-Agent Orchestration Foundation) | proposed | P0 完了 + Phase F-0 完了 + ADR-00018/19/20 + 00004/00009/00013 update accepted | SP-013 kickoff 直前 |
| ADR-00019 (Role Taxonomy) | proposed | ADR-00014 accepted + P0 完了 | ADR-00014 と同 timing |
| ADR-00018 (Inter-Agent Communication) | proposed | (要確認、SP-015 prerequisite) | SP-015 着手時 |
| ADR-00009 (Action Class Taxonomy) | accepted ✅ | - (update 要、Phase F-0 で) | Phase F-0 で update |
| ADR-00020 (Framework Intake Checklist) | accepted ✅ | - | - (SP022-T00 で accepted 済) |
| ADR-00016 (Hermes Agent Integration) | proposed | (要確認、SP-013 直結ではない) | - |

### 3. Phase F-0 prerequisite (SP-013 kickoff 前 must_ship)

ADR-00014 acceptance_blocked_by #2「Phase F-0 (ADR-00009 update + DD-02 policy 3 table の read/search → provider_call 同期 migration) 完了」:

| 項目 | 状態 (2026-05-22 prep 時点) | 着手予定 |
|---|---|---|
| ADR-00009 update (action_class enum に provider_call 追加 / read/search 削除) | ❌ 未着手 (`rg "Phase F-0\|phase-f-0"` で実装 file 0 件) | SP-013 kickoff 直前 (separate light ADR + migration PR) |
| DD-02 policy 3 table (`role_authorization` / `principal_grant` / `policy_decision`) の `read/search` → `provider_call` 同期 migration | ❌ 未着手 | 同上 |
| artifacts.project_id materialize migration (PE-F-007 strict prerequisite) | ❌ 未着手 (`migrations/versions/*project*` 0 件) | 同上 |
| AC-HARD-03 cross-project negative test (research domain) | ✅ 既存 (`tests/security/test_research_cross_project_negative.py` 存在、SP-010 で起票) | - (本 test は research domain で完結、Phase F-0 で artifacts.project_id 追加後の **artifact-domain cross-project test** を別途 追加必要) |
| AC-HARD-03 cross-project negative test (artifacts.project_id 追加後の artifact-domain) | ❌ 未着手 (artifacts.project_id materialize migration 完了後、`tests/security/test_artifact_cross_project_negative.py` 等の追加 test が必要) | Phase F-0 migration 後 |

Phase F-0 は **SP-013 着手前の separate light Sprint Pack** として起票推奨 (SP-012.5 や SP-022.1 系の position)。本 prep では state 確認のみ、着手は本 plan §2.3 pre-P0 freeze 期間内禁止作業に該当のため P0 Exit declaration merge 後。

### 4. P0.1 unblock 完了判定 (TASKHUB_P0_1_OPENED=1 解禁条件)

P0 Exit declaration PR 起票時 (Phase 8) に以下を verify:

- [ ] Hard Gates 7 全件 PASS (AC-HARD-01〜07)
- [ ] Quality KPIs 5 未達 ≤ 1 個 (AC-KPI-01〜05)
- [ ] backup/restore drill PASS (AC-HARD-04、T09 drill 7 mandatory checklist 経由)
- [ ] 実機 host migration drill (Mac→VPS) RTO ≤ 4h PASS (T09)
- [ ] SP-022 frontmatter `status: completed`
- [ ] SP-012 frontmatter `status: completed` (partial_completed_with_carry_over から昇格)
- [ ] `docs/release/p0_exit_2026_MM_DD.md` commit + master plan §3-§9 update + TASKHUB_P0_1_OPENED=1 env 解禁
- [ ] sealed CI guard 解除 (P0.1 path 追加禁止 lift = migration `*event_type_37*` 等)

### 5. SP-013 着手後の sub-Sprint dependency tree

```
SP-013 (Multi-Agent Orchestration Foundation)
├─ SP-014 (Orchestrator Agent: lease/dispatch/failover)
├─ SP-015 (Inter-Agent Communication: inter_agent_messages table)
├─ SP-016 (UI/CLI Parity)
├─ SP-017 (AI Society Visualization、optional P1)
├─ SP-018 (Memory backend、ADR 別途)
└─ SP-019/020 (P1 後段、未起票)
```

SP-013 完了で SP-014/015/016 の DDL 前提 (agent_roles / project_agent_roles / agent_runs.role_id+role_scope / parent/child / project boundary) が確立。

### Related links

- p0-exit-final-hardening-2026-05-22 plan: `.claude/plans/p0-exit-final-hardening-2026-05-22.md`
- Phase 8 P0 Exit declaration prep: 本 PR (`prep/phase8-sp013-2026-05-22`)
- ADR-00014 Phase A-E research: `docs/設計検討/phase-c-multi-agent-spec-draft.md` (56 finding adopt 済)
- master plan §10.C: SP-022 完了 → P0 Exit declaration → P0.1 unblock (TASKHUB_P0_1_OPENED=1 + SP-013 着手)

---

## Review (2026-05-22 batch 0 完遂)

最終更新: 2026-05-22

### changed (batch 0 全 5 ステップ完遂)

| step | scope | PR |
|---|---|---|
| readiness 昇格 | Sprint Pack draft → ready | #132 |
| 0a | 10 standard role taxonomy enum + matrix validator (5+ source enum integrity) | #133 → #135 → #137 (Codex P1 cascade matrix-based fix) |
| 0b | project_agent_roles + standard_role_ids_mirror migration + immutable seed | #134 |
| 0c | agent_runs 8 columns 拡張 (role/lease/progress) + 2 CHECK + partial index | #136 |
| 0d | check_project_role_link trigger function (PE-F-012 DB-level defense) | #138 → #140 (Codex P1 regression fix) |
| 0e | sanitizer_policy_versions minimal table + v1.0.0 seed (ADR-00016 §5 PH-F-009 fix) | #139 → #140 (Codex P2 fix) |

### verified

- alembic head: `0024_multi_agent_foundation_e` (Mac local DB apply 確認済)
- pytest tests/multi_agent/: **30 PASS** (累計、role taxonomy 13 + standard role seed 3 + agent_runs role columns 4 + trigger 6 + sanitizer 4)
- 全 Codex finding close (P1×8 + P2×3、本 Sprint batch 0 関連 PR で発生した P1×4 + P2×1 全件 fix 完遂):
  - PR #133 P1 (role_scope invariant) → #135 → #137 matrix-based fix
  - PR #138 P1 (project + standard role regression) → #140 fix
  - PR #139 P2 (seed test no-op assertion) → #140 fix

### deferred (batch 1+、SP-014 移送、SP-018 連携)

- **orchestrator agent 本体実装** (lease/dispatch/failover/kill-switch): SP-014 で実装
- **memory_records / memory_retrieval_artifacts FK 接続** (sanitizer_policy_versions): SP-018 で hermes 取り込み後
- **5 検証項目 backup drill** (parent/child AgentRun FK / agent_roles soft-delete / standard mirror / sanitizer / audit_events correlation): SP-018 / SP-022 で backup 整備時に実装

### residual risks

- check_project_role_link trigger function は `CREATE OR REPLACE` で migration 0024 で更新済、Mac local DB apply 確認済。本番 deploy 時に migration 0022 → 0024 の順序保証必要 (linear migration history で自動保証)
- standard_role_ids_mirror の immutable seed は PostgreSQL DELETE で削除可能 = HARD DELETE 不可 trigger は P0.1+ で別途追加 (SP-018 hermes 取り込み時に検討)

### kickoff path SP-014

SP-013 batch 0 完遂で SP-014 prerequisite 満たす:
- agent_runs に `orchestrator_lease_token / orchestrator_lease_expires_at / lease_renewed_at / orchestrator_kill_at / last_progress_at / progress_seq` 完備
- check_project_role_link trigger で role reference の DB-level defense (PE-F-012 mitigation) 完備
- 10 standard role (orchestrator 含む) と standard_role_ids_mirror で global standard role 利用可能
- sanitizer_policy_versions v1.0.0 で memory layer の sanitizer integrity 基盤完備

SP-014 batch 0 着手可能 state (codex-all-loops mode=code 委譲推奨)。
