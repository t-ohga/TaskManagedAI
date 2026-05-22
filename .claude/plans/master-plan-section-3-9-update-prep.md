---
id: "master-plan-section-3-9-update-prep"
type: "draft-supplement"
status: "draft"
created_at: "2026-05-22"
updated_at: "2026-05-22"
parent_plan: "docs/設計検討/2026-05-13_p0_exit_master_plan.md"
related_plan: ".claude/plans/p0-exit-final-hardening-2026-05-22.md"
phase: "Phase 8 prep (P0 Exit declaration PR で master plan §3-§9 historical sections に merge する素材)"
---

# Master Plan §3-§9 Update Draft (Phase 8 P0 Exit declaration PR 用素材)

## 0. 目的

p0-exit-final-hardening-2026-05-22 plan §9.3.3 で固定した「master plan partial update を P0 Exit declaration PR で 1 回反映 (Q6 default 維持)」に基づき、Phase 8 PR で master plan `docs/設計検討/2026-05-13_p0_exit_master_plan.md` の §3-§9 historical sections に **本 plan の routing fix + Layer B/C smoke + 12 latent issues fix + 3 PR autonomous merge** を反映する素材を本 file で draft 整備。本 file は Phase 8 PR で master plan に merge 後、削除する。

## 1. 反映対象 (master plan §3-§9 update)

### 1.1 §1.1 完了 Sprint table 追加 (本 plan の追加 Hardening Gate を 1 行)

```diff
 ### 1.1 完了 Sprint
 
 | Sprint Pack | status | merged | 備考 |
 |---|---|---|---|
 | `SP-010_research_evidence.md` (heavy) | completed | PR #19/21/22/24/26/27 | 10 BL (BL-0029c + BL-0113〜0121) 全件完了、ADR-00002 update accepted |
 | `SP-011_eval_harness.md` (heavy) | completed | PR #38/39 | 16 BL (本来 12 + carry-over 完遂 5)、AC-HARD 7 fixture registry + AC-KPI 5 計測 endpoint 完成 |
 | `SP-011-5_operational_hardening.md` (heavy) | completed (Sprint 11.5) | (SP-011 内に統合) | 14 BL (本来 11 + carry-over 3)、Codex R2 F-R2-002 adopt 反映済 |
-| `SP-012_p0_acceptance.md` (heavy) | **partial_completed_with_carry_over** | PR #59-#67 (9 PR) | skeleton 完了、SP-022 carry-over (T08): `docs/sprints/SP-012_p0_acceptance.md §Sprint 12 Deferred` 正本の全 9 件 |
+| `SP-012_p0_acceptance.md` (heavy) | **completed** (T09 drill PASS 後) | PR #59-#67 (skeleton) + PR #76-#88 (must_ship batch 1-D) | skeleton + must_ship 完遂、SP-022 で T08 carry-over 完了 |
-| `SP-022_framework_intake_hardening.md` (heavy) | **draft** (次着手) | — | pre-P0.1 unblock sprint、Sprint Pack 正本参照 (T00 + T01〜T07 + T08 carry-over + T09 実機 drill)、must_ship 全件で P0.1 unblock 達成 |
+| `SP-022_framework_intake_hardening.md` (heavy) | **completed** (T09 drill PASS 後) | T00 PR #69 / T01-T07 PR #70-#80 / T08 batch PR #76,#77,#78,#79,#90,#91 / T06 KPI PR #89 / Review #92 / Additional Hardening Gate PR #95+#96+#97 (p0-exit-final-hardening-2026-05-22 plan) | pre-P0.1 unblock sprint 完遂、T09 drill PASS + ADR-00021/00007 accepted (SP022-T00 で済) + Additional Hardening Gate 12 latent issues fix |
+| `p0-exit-final-hardening-2026-05-22.md` (supplement plan) | completed | PR #95 routing-build-hardening + PR #96 layer-b-c-smoke fix + PR #97 sop-polish = 3 PR autonomous merge | SP-022 must_ship 表変更なし、`## Review § Additional P0 Exit Hardening Gate` で記載 (本 SP-022 Sprint Pack 内) |
```

### 1.2 §1.3 ADR 状態 update

```diff
-| ADR-00007 (External Exposure) | proposed | SP-022 で Tailscale Serve invariant verify 後 |
+| ADR-00007 (External Exposure) | **accepted** at SP022-T00 (2026-05-19) | Tailscale Serve TLS 終端 invariant 維持確認、T09 drill 時に再 verify |
-| ADR-00020 (Framework Intake Checklist) | proposed | SP-022 で accepted |
+| ADR-00020 (Framework Intake Checklist) | **accepted** at SP022-T00 (2026-05-19) | ADR-00014/00016 から独立 accept、CI 機械検査完成 |
-| ADR-00021 (Host-Portable Deployment) | proposed | SP-012 で host migration drill PASS 後 |
+| ADR-00021 (Host-Portable Deployment) | **accepted** at SP022-T00 (2026-05-19) | design accepted、SP022-T09 で post-acceptance verification (実機 drill PASS) |
+| ADR-00022 (Dev Login Cookie Secure Attribute) | accepted (retro at 2026-05-10) | development HTTP loopback 動作、production HTTPS 強制 |
+| ADR-00026 (PITR WAL Archiving) | accepted | Sprint 11.5 batch 3a で実装 |
+| ADR-00027 (Tool Registry Security Boundary) | proposed | QL-A run で起票、accepted 化は P0.1 unblock 後 SP-013/014/015 着手時に評価 (F-PR98-002 adopt fix) |
+| ADR-00028 (Split-Brain Second Line) | accepted | SP-012 must_ship plan で起票 |
+| ADR-00029 (Approval Keyring Rotation) | accepted | SP-012 must_ship plan で起票 |
```

### 1.3 §10.C 実装着手順序 update (本 plan の Phase 1-8 を追加)

```diff
 ### C. 実装着手順序 (post Sprint 12、T00/T08/T09 概要のみ、T01-T07 詳細は SP-022 Sprint Pack 正本参照)
 
 1. **SP-022 着手** (... 既存 detail ...)
 
 2. **P0 Exit declaration**: SP-022 Sprint Pack must_ship 表で must_ship=○ の項目全件完了 + Additional P0 Exit Hardening Gate (p0-exit-final-hardening-2026-05-22 plan 経由、PR #95/#96/#97/#98/#99 で 12 latent issues + Phase 7 scope 訂正) + **Phase 7a Mac single-host 運用立証** (Mac UI smoke + Mac local backup/restore drill = AC-HARD-04 PASS、Mac single-host で完結) を満たす. ただし以下 3 件は SP-013〜020 future-sprint 依存のため post-P0.1 carry-over として P0 Exit gate から除外:
    - SP022-T05 AC-HARD multi-agent fixture: SP-013 skeleton 依存
    - Phase E 16 finding (PE-F-001〜PE-F-016) closure の "実 contract test PASS": SP-013〜016/SP-018/SP-020 contract test 依存. SP-022 must_ship では audit-only gate のみ要求.
    - Phase G PGA-F-009 inter_agent_messages consumed invariant fixture: SP-015 依存
    
    特に T08 + Phase 7a Mac 運用立証 + p0-exit-final-hardening Additional Hardening Gate が P0.1 unblock 直接 gate.

    **重要訂正 (PR #99 で適用)**: 旧記述「実機 host migration drill (Mac→VPS) RTO ≤ 4h PASS」を「**Phase 7a Mac single-host 運用立証 (Mac UI smoke + Mac local backup/restore drill PASS = AC-HARD-04 evidence)**」に変更。Mac→VPS migration drill (T09 = Phase 7b) は **ADR-00021 host-portable deployment post-acceptance verification** として位置付け直し、P0 Exit declaration の **直接 gate ではない** (post-P0.1 or 任意 timing で実施).

3. **P0.1 unblock**: TASKHUB_P0_1_OPENED=1 + P0 sealed CI guard 解除 + Phase F-0 (ADR-00009 update + DD-02 policy 3 table 同期 migration + artifacts.project_id materialize) 完了 + ADR-00014/00019 accepted promotion + Phase 7b T09 Mac→VPS migration drill 実施 (ADR-00021 post-acceptance verification) + SP-013 (multi-agent orchestration) 着手
```

### 1.4 §11 Open Decisions Q6 close (本 plan 完了で resolved)

```diff
-### 11.2 SP-022 開始に伴う新規 Open Decisions
-
-- **Q6**: SP-022 着手後の master plan §3 / §6 / §7 / §8 / §9 (historical record) 反映 timing を **P0 Exit declaration PR (SP-022 完了後)** で 1 回にまとめるか、**SP-022 中盤の intermediate PR** で partial reflect (drift 状態を短縮) するか?  
-  default: **P0 Exit declaration PR (SP-022 完了後)** で 1 回 (本 PR で master plan §10-§11 + §1.3 / §5 drift fix を済ませた前提、scope creep 防止のため historical record の partial update を増やさない)
+### 11.2 SP-022 開始に伴う Open Decisions (解決済)
+
+- **Q6 (解決済 2026-05-22、P0 Exit declaration PR 反映)**: master plan §3 / §6 / §7 / §8 / §9 (historical record) 反映 timing は **P0 Exit declaration PR で 1 回反映** で decided. 本 PR で §1.1 完了 Sprint table + §1.3 ADR 状態 + §10.C 実装着手順序 を update 反映済.
```

## 2. 本 file の使用方法

1. Phase 8 P0 Exit declaration PR の起票時、本 file の §1.1 / §1.2 / §1.3 / §1.4 diff を `docs/設計検討/2026-05-13_p0_exit_master_plan.md` の該当 section に **手動で apply** (sed や script は使わず、Edit Tool で 1 section ずつ)
2. apply 完了後、本 file (`.claude/plans/master-plan-section-3-9-update-prep.md`) を **同 PR 内で削除** (`git rm`、本 file は draft 素材で恒久 doc ではない)
3. P0 Exit declaration PR commit message で本 file の参照を明示 (Phase 8 prep PR `prep/phase8-sp013-2026-05-22` で起票、本 PR で完成版)

## 3. 関連

- parent plan: `docs/設計検討/2026-05-13_p0_exit_master_plan.md`
- supplement plan: `.claude/plans/p0-exit-final-hardening-2026-05-22.md` §9.3.3
- SP-022 Sprint Pack `## Review § Additional P0 Exit Hardening Gate` (本 PR で同 commit)
- SP-013 Sprint Pack `## Review § P0.1 Unblock 前提 prerequisite status` (本 PR で同 commit)
