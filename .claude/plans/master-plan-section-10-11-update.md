---
id: PLAN-MASTER-PLAN-S10-S11-UPDATE
title: "master plan §10 / §11 + §1.3 / §5 acceptance path drift fix (post Sprint 12 merge、SP-022 prereq)"
status: draft
date: 2026-05-19
authors:
  - "claude (post Sprint 12)"
related_documents:
  - "../../docs/設計検討/2026-05-13_p0_exit_master_plan.md"
  - "../../docs/sprints/SP-012_p0_acceptance.md"
  - "../../docs/sprints/SP-022_framework_intake_hardening.md"
  - "../../docs/sprints/SP-001-5_host_portable_amendment.md"
  - "../../docs/adr/00007_external_exposure.md"
  - "../../docs/adr/00020_framework_intake_checklist.md"
  - "../../docs/adr/00021_host_portable_deployment.md"
  - "../../.claude/rules/sprint-pack-adr-gate.md"
review_history:
  - "R1 (codex-review-loop / target_kind=spec): 8 findings (HIGH 1 / MEDIUM 5 / LOW 2、CRITICAL=0)、全件 adopt"
  - "R2 (codex-review-loop / HIGH+ 限定): 3 findings (HIGH 3、CRITICAL=0)、全件 adopt — F-PLAN-R2-001 ADR-00020 frontmatter 循環依存 + F-PLAN-R2-002 SP022-T05 post-P0.1 reroute との T00〜T09 全件含意の循環 + F-PLAN-R2-003 verification grep historical quote false fail"
  - "R3 (codex-review-loop / CRITICAL のみ): 1 finding (CRITICAL 1)、全件 adopt — F-PLAN-R3-001 SP-022 must_ship Phase E 16 finding closure が SP-013〜020 contract test PASS 依存で P0 Exit gate から物理的不達 (T05 と同種の future-sprint 循環)、audit-only gate への split を §10.C-2 / §4 / §7 で明記"
  - "R4 (codex-review-loop / long-loop regression check): 3 findings (MEDIUM 3、CRITICAL=0 / HIGH=0 で critical_zero criteria 達成済)、全件 adopt — F-PLAN-R4-001 SP-001-5 本文/受け入れ条件の旧 drill PASS 文言 + F-PLAN-R4-002 Phase E carry-over inventory §1.2/§10.C-4/Q8 同期漏れ + F-PLAN-R4-003 negative grep ADR-00021 §1.3 1 row のみで他 3 active row 不在 verify 漏れ"
  - "R5 (codex-review-loop / long-loop final clean verify): 2 findings (HIGH 1 / MEDIUM 1、CRITICAL=0 / HIGH≤2 で critical_zero criteria 維持)、全件 adopt — F-PLAN-R5-001 SP-022 Phase E follow-up scope が must_ship 表のみで受け入れ条件 (L104) / task list (L74) / 検証手順 (L124-126) 等の active line を含めず + F-PLAN-R5-002 SP-001-5 drift fix inventory が L38/L97 のみで L11/52/72/92/130/148 の active text 残存"
  - "R6 (codex-review-loop / final clean verify): 0 findings、Phase 1 review-loop terminate signal (readiness_gate=READY、cumulative 17 findings 100% adopt)"
  - "Phase 2 R1 (codex-adversarial-loop / 7 攻撃観点): 7 findings (CRITICAL 1 / HIGH 3 / MEDIUM 3)、全件 adopt — F-ADV-R1-001 CRITICAL Phase G PGA-F-009 SP-015 依存の future-sprint 循環 (Phase E と同種) + F-ADV-R1-002 HIGH SP022-T00 atomic checklist Sprint Pack frontmatter 移動明示なし + F-ADV-R1-003 HIGH §6.1 verification §10/§11 active text drift 未カバー + F-ADV-R1-004 HIGH §6.2 baseline gate head -200 人手確認縮退で polling contract 未準拠 + F-ADV-R1-005 MEDIUM 本 PR merge と SP022-T00 PR base-SHA race + F-ADV-R1-006 MEDIUM SP-022 L162 ADR-00014〜00019 accepted 済 stale text + F-ADV-R1-007 MEDIUM SP022-T07 production checklist scope leak"
  - "Phase 2 R2 (codex-adversarial-loop / HIGH+ 限定): 6 findings (HIGH 6、CRITICAL=0、HIGH>2 で critical_zero criteria 未達)、全件 adopt — F-ADV-R2-001 §4 critical path 二重 truth (Sprint 12 → P0 Exit active text 残存) + F-ADV-R2-002 §10.D branch → main 直接 ff merge が branch-and-pr-workflow.md invariant 違反 + F-ADV-R2-003 §6.2 polling contract LATEST_SHA bind 未移植 + F-ADV-R2-004 SP022-T00 step 1 updated_at 同期更新欠落 + F-ADV-R2-005 planned_adr_refs verification display only で fail-closed なし + F-ADV-R2-006 step 6 verification が SP-022 carry over / contract test PASS / PGA-F-009 active phrase 未網羅"
  - "Phase 2 R3 (codex-adversarial-loop / CRITICAL のみ最終 verify): 2 findings (CRITICAL 2、HIGH=0)、全件 adopt — F-ADV-R3-001 CRITICAL SP022-T00 verification が display grep のみで accepted exact value / 3 ADR count / updated_at exact equality / adr_refs exact set / planned_adr_refs absent を fail-closed assert しない (ADR proposed のままでも通る fail-open path) + F-ADV-R3-002 CRITICAL SP022-T00 = ADR accepted promotion 自体、`.claude/rules/sprint-pack-adr-gate.md §12.4` + `.claude/rules/codex-usage-policy.md §14` 「ADR proposed→accepted 昇格 = codex-plan-review R1 minimum + 採否判定」mandatory hard gate を SP022-T00 checklist 先頭に明示していない (本 PR §6.2 は post-PR auto-review baseline であって §12.4 promotion gate ではない、別 gate)"
  - "Phase 2 R4 (codex-adversarial-loop / CRITICAL + regression final verify): 1 finding (CRITICAL 1 regression)、全件 adopt — F-ADV-R4-001 CRITICAL regression R3 adopt の yq parse が SP-022 (YAML frontmatter 付き Markdown) に対し fail-open (yq direct parse で partial stdout + rc=1、pipeline rg で parser failure 隠蔽)、frontmatter awk 抽出 + yq -e + set -euo pipefail で fix"
  - "Phase 2 R5 (codex-adversarial-loop / CRITICAL + regression final clean verify): 1 finding (CRITICAL 1)、全件 adopt — F-ADV-R5-001 CRITICAL SP022-T00 verification coverage が atomic checklist step 2 (ADR-00020 blocker 再解釈) + step 5 (SP-022 Review accepted_at 記録) を覆っていない、ADR-00020 frontmatter awk 抽出 + acceptance_blocked_by 旧 cyclic 削除 + SP022-T00 independent accept marker 存在 + SP-022 Review 3 ADR accepted_at 行 grep を verification (11)(12) に追加"
---

# master plan §10 / §11 update + §1.3 / §5 drift fix

## 0. Executive Summary

PR #67 (Sprint 12 Exit Review) で F-PR67-010/013/031/032 P2 adopt として `docs/設計検討/2026-05-13_p0_exit_master_plan.md` §1.3 / §5 / §10 / §11 の **acceptance path drift** が確認されたが、SP-012 PR の scope (Sprint Exit Review) 範囲外として **「SP-022 開始時に別 PR で master plan §10-§11 update を提出予定」** に carry-over 決定された (SP-012 frontmatter / ADR-00021 frontmatter / SP-022 frontmatter / SP-001-5 amendment 参照)。本 PR は当該 carry-over を実行する。

**update する 4 area** (`feedback_codex_pr_review_baseline_check.md` 教訓 + `feedback_codex_r2_reemission_reject_trap.md` 教訓に基づき、対象 line を grep-verify 済み):

1. **§1.3 ADR 状態** (line 106-107): ADR-00021 / ADR-00007 acceptance path を「Sprint 12 で host migration drill PASS 後」→「SP022-T00 pre-implementation gate + SP022-T09 post-acceptance verification」へ
2. **§5 ADR Acceptance Path table** (line 556-557): 同様の更新 + acceptance_blocked_by mutual cycle 解消反映
3. **§10 Next Action** (line 659-689): Sprint 10-12 完了反映 + SP-022 が単一次アクション + main ff merge timing を SP-022 P0.1 unblock declaration に更新。**SP-022 sub-task spec は T00/T08/T09 概要のみに圧縮 (F-PLAN-R1-002 adopt)**、T01-T07 詳細は SP-022 Sprint Pack 正本参照
4. **§11 Open Decisions** (line 690-714): Q1-Q5 を **accepted decision** として close + SP-022 開始に伴う新規 open decisions (Q6 のみ、Q7/Q8 は accepted 化、F-PLAN-R1-006 adopt) を起票

scope creep 回避のため、§3 (Sprint 10/11/11.5/12 詳細) / §6 (Round Budget 集計) / §7 (Verification Gate) / §8 (Risk + Rollback) / §9 (Schedule) は historical record として **本 PR では編集しない** (SP-022 完了時に別 PR で「P0 Exit declaration 確定 + 累計 round actuals」を反映予定)。代わりに §1.1 完了 Sprint table に **Sprint 10/11/11.5/12 行を追加**して current status を明示する。

**SP-012 carry-over の正本 (F-PLAN-R1-001 adopt)**: SP022-T08 must_ship は `docs/sprints/SP-012_p0_acceptance.md §Sprint 12 Deferred` (line 290-301) を正本とする。**batch 6.1 (Pydantic schema for input JSON) + AC-HARD-01/02/05/06/07 real corpus + programmatic SUT (Policy Engine / SecretBroker / Input Trust Layer / runner_mutation_gateway → Mapping[str, bool] adapter) + hard_gates_rollup.py real corpus loading + SUT wiring** を含む全 9 件 (master plan update を除く)。

## 1. Background

### 1.1 R4 master plan grep mistake (drift detection trigger)

PR #67 R3 で Codex finding F-PR67-010 (ADR-00021 premature acceptance) を Claude が partial reject した。R4 で再 review した結果、master plan line 106 「ADR-00021 (Host-Portable Deployment) | proposed | Sprint 12 で host migration drill PASS 後」と PRD-01 §523 「host migration drill PASS が ADR-00021 acceptance 必須」明示が確認され、Claude の reject 判定は **誤り** だった (memory: `feedback_codex_r2_reemission_reject_trap.md` 教訓に該当 = R3 で false positive 短絡判定 → R4 で実 grep verify により revert 必要)。

R4 以降、SP-012 / SP-001.5 / SP-022 / ADR-00021 / ADR-00007 で acceptance lifecycle metadata 5 doc を整合 update し:

- ADR-00021 status: `proposed` (restore)、`acceptance_target_sprint: "SP022-T00 pre-implementation gate"`、`post_acceptance_verification: ["SP022-T09 実機 host migration drill (Mac→VPS) RTO≤4h PASS", "SP022-T08 SP012-T01〜T10 carry-over 完了"]`
- ADR-00007 status: `proposed` (ADR-00021 同期 acceptance)、common `SP022-T00 simultaneous acceptance gate` で **mutual blocking cycle 解消** (旧 reciprocal blocker を共通 T00 trigger に置換、F-PR67-047 P2 adopt)
- SP-012 status: `partial_completed_with_carry_over`、`planned_adr_refs` に ADR-00021/00007 (SP022-T00 acceptance) を restore
- SP-022 reframed as **pre-P0.1 unblock sprint** (旧「P2 段階 公開準備 hardening」記述は撤回)、SP022-T00〜T09 で ADR-00021/00007/00020 accepted 化 + SP-012 carry-over 完成 + 実機 drill PASS + multi-agent fixture は post-P0.1 SP-022.1/SP-023 carry-over

これらの 5 doc update は **PR #67 内で完了** したが、master plan §1.3 / §5 / §10 / §11 は **同 PR scope 外** として残存し、現状 SP-022 / ADR / SP-012 と **drift 状態**。本 PR で同期する。

**残存 drift (本 PR では fix しない、SP022-T00 着手 PR で扱う)**:

- (F-PLAN-R1-004 adopt) ADR-00021 / ADR-00007 frontmatter `acceptance_history` の future entry (例: ADR-00021 line 44 「future: 実機 host migration drill PASS 後 SP-022 scope で再 accepted 化」) は SP022-T00 reinterpretation (design accepted + post-acceptance verification) と read mismatch する文言を持つ。本 PR は master plan のみ scope のため、ADR frontmatter history future entry の文言 update は SP022-T00 PR で同時実施する (本 plan §7 out-of-scope に明記)。
- **(F-PLAN-R2-001 adopt) ADR-00020 frontmatter `acceptance_blocked_by` の循環依存**: `docs/adr/00020_framework_intake_checklist.md:13-15` は `acceptance_blocked_by: ["ADR-00014/16 accepted", "P0 完了"]` のまま保持されているが、ADR-00014 (multi-agent orchestration、P0.1 SP-013 scope) / ADR-00016 (hermes integration、P0.1 SP-014 scope) 両方 proposed のうえ、ADR-00016 は ADR-00020 accepted を blocker に含む = 循環依存。`docs/sprints/SP-022_framework_intake_hardening.md` L16/L57/L70-72 で SP022-T00 同時 acceptance を固定済 (R1 Q7 accepted decision) だが、**ADR-00020 自身の frontmatter blocker 再解釈は SP022-T00 PR の precondition** として必須。framework intake checklist は P0 全体方針として独立に accept 可 (CI 機械検査の話、multi-agent への依存性なし)、ADR-00020 frontmatter `acceptance_blocked_by` を「SP022-T00 で multi-agent ADR-00014/00016 から独立 accept」に再解釈する update が SP022-T00 PR で同時実施。本 PR は master plan のみ scope のため §7 out-of-scope に明記。
- **(F-PLAN-R3-001 adopt) SP-022 must_ship 表 Phase E 16 finding closure の future-sprint 循環依存**: `docs/sprints/SP-022_framework_intake_hardening.md:94` は「Phase E 16 finding closure」を must_ship=○ にしているが、同 Sprint Pack L53 で「PE-F-001〜PE-F-016 が SP-013〜016/SP-018/SP-020 で must_ship 反映済」L104 で「各 finding の contract test PASS を verify」を要求。SP-013 着手は P0.1 unblock 後 (本 plan §10.C-3) のため、Phase E 16 finding の **実 contract test PASS は SP-013〜020 完了まで物理的不可達** = R2 F-PLAN-R2-002 (T05 含意循環) と同種の future-sprint 循環。修正: SP-022 must_ship 表の Phase E closure を **(a) "PE-F-001〜PE-F-016 が owning ADR/Sprint Pack に割り当て済みで各 sprint 受け入れ条件に trace されている" の audit-only gate** に分割 + **(b) 実 contract test PASS は post-P0.1 owning sprint exit gate に carry-over** = master plan §10.C-2 / §4 critical path で同除外を明記。SP-022 Sprint Pack 側の must_ship 表 split (audit-only gate / contract test PASS) は SP022-T00 着手 PR で実施 (本 PR は master plan のみ scope、§7 out-of-scope 明記)。
- **(F-ADV-R1-001 adopt) SP-022 Phase G PGA-F-009 SP-015 依存の future-sprint 循環**: `docs/sprints/SP-022_framework_intake_hardening.md:172` は Phase G 追加 must_ship に「inter_agent_messages consumed invariant fixture (PGA-F-009): SP-015 で実装されたものを SP-022 で追加 fixture (post-restore + post-migration 全 case) で再 verify」を含み、L187 で Phase G adversarial 14 finding 全件 closure evidence / contract test PASS を要求。SP-015 は P0.1 SP-014 の次 sprint = P0 Exit gate 前は物理的不可達。Phase E と同種の future-sprint 循環を Phase G で別名再発させる経路。修正: (a) plan §1.2 / §4 / §10.C-2 / §10.C-4 の P0 Exit gate exclude list に「Phase G PGA-F-009 / SP-015 依存 fixture」を追加、(b) SP-022 では audit-only trace gate のみ must_ship、(c) 実 contract test PASS は post-P0.1 SP-015 完了後 owning sprint exit gate carry-over。SP-022 Sprint Pack 側 L172 / L187 split は SP022-T00 着手 PR で実施 (本 PR は master plan のみ scope、§7 out-of-scope 明記)。
- **(F-ADV-R1-006 adopt) SP-022 L162 「ADR-00014〜00019 accepted 済」stale active text**: `docs/sprints/SP-022_framework_intake_hardening.md:162` の関連 ADR セクションに「ADR-00014/15/16/17/18/19 (P0.1+ で accepted 済、本 Sprint で運用 hardening)」記述あり。実際は ADR-00014 (`docs/adr/00014_multi_agent_orchestration.md:4`) + ADR-00016 (`docs/adr/00016_hermes_agent_integration_strategy.md:4`) 両方 `status: proposed`。SP022-T00 reviewer が本 stale 行を根拠に ADR-00020 frontmatter blocker (ADR-00014/00016 accepted 必須) を解消済と誤読する acceptance lifecycle trap 経路。修正: SP022-T00 PR 必須更新に L162 文言 update を追加 (「accepted 済」→「P0.1+ owning sprint で proposed→accepted 予定」)、SP022-T00 PR verification に `rg -n 'accepted 済' docs/sprints/SP-022_framework_intake_hardening.md` を追加し ADR-00014/00016 status と矛盾しないことを確認 (本 PR は master plan のみ scope、§7 out-of-scope 明記)。
- **(F-ADV-R1-007 adopt) SP022-T07 production checklist scope leak risk**: `docs/sprints/SP-022_framework_intake_hardening.md:43-46` で「対象外: 新機能追加 / production 公開」明示済だが、L64 で SP022-T07 を「production 公開準備 checklist draft」と定義 + L97 で must_ship=○。「draft」と「詳細実装は P3+」の境界が明文化されておらず、SP022-T07 実装者が draft 名目で Docker image build pipeline / DNS / 外部公開 / license/docs 整備 (P3+ 実作業) を mix する scope leak 経路。修正: SP022-T00 precondition checklist に T07 境界を明文化 (docs-only checklist skeleton まで、DNS / public ingress / Funnel / Cloudflare / release image build / production deploy config / external publication / license/docs 整備は明示禁止、必要なら P3+ Sprint Pack に分離)、P0.1 unblock 判定では T07 = production 実装完了ではなく checklist draft 存在確認に限定 (本 PR は master plan のみ scope、§7 out-of-scope 明記)。
- **(F-PLAN-R4-001 + F-PLAN-R5-002 adopt) SP-001-5 host portable amendment 全 active lines の旧 acceptance path 文言**: `docs/sprints/SP-001-5_host_portable_amendment.md` は frontmatter L18-19 で SP022-T00 acceptance + SP022-T09 post-acceptance verification を反映済だが、active text の以下 7 箇所で旧「SP-022 で実機 host migration drill PASS 後」「SP-022 carry over」表現を残しており、frontmatter と read mismatch (実 rg verify 済):
   - L38 (目的セクション本文)
   - L52 (背景 `taskhub` admin CLI prereq 説明)
   - L72 (実装チケット SP015-T07 注釈)
   - L92 (must_ship 対応表 「ADR-00021 + ADR-00007 update accepted | ✗ (SP-022 carry over)」)
   - L97 (受け入れ条件)
   - L130 (レビュー観点)
   - L148 (関連 ADR 注釈)
   - (L11 は frontmatter comment、historical context として許容可能)
   SP022-T00 PR で frontmatter 同期 update + SP022-T00 PR verification に SP-001-5 negative grep (historical comment 以外で旧文言残存なし) を追加 (本 PR は master plan のみ scope、§7 out-of-scope 明記)。

### 1.2 SP-012 → SP-022 → P0.1 路線図 (post-fix)

```
SP-012 partial_completed_with_carry_over  (PR #67 merged 2026-05-19)
  ├─ skeleton 実装着手済 (taskhub admin CLI / Hard Gates 7 evaluator pure path / Eval Dashboard / signed journal pure function / P0 Acceptance audit writer)
  └─ carry-over (SP022-T08): SP-012 §Sprint 12 Deferred 正本 (line 290-301) 全 9 件
     - batch 6.1: Pydantic schema for P0 Acceptance Report input JSON
     - 実 DB write integration: AuditEvent / signed journal session.add + commit + BL-0149 sign-off endpoint + frontend ↔ backend
     - signed journal verification CLI (audit_events 全件 fetch + recompute + final_hash verify)
     - AC-HARD-01/02/05/06/07 real corpus + programmatic SUT (Policy Engine / SecretBroker / Input Trust Layer / runner_mutation_gateway → Mapping[str, bool] adapter)
     - hard_gates_rollup.py の real corpus loading + SUT wiring
     - taskhub admin CLI real I/O (10 subcommands all)
     - frontend i18n constants + Playwright E2E (Sprint 11.5 BL-0109a/0110a 統合)
     - audit_events 内 previous_event_hash column + DB trigger (signed journal DB-side enforcement)
     - private staging CI/E2E 完成

SP-022 pre-P0.1 unblock sprint  (next)
  ├─ SP022-T00 (pre-implementation gate): ADR-00020 + ADR-00021 + ADR-00007 を proposed → accepted 同時昇格 (+ ADR-00021/00007 frontmatter history future entry の文言 update も同時)
  ├─ SP022-T01〜T07: SP-022 Sprint Pack 正本参照 (framework intake CI + taskhub migrate 自動化 + drill SOP + Phase E 16 finding closure + KPI baseline + 公開準備 checklist + Phase G strengthening hardening)
  ├─ SP022-T08 (must_ship): SP-012 §Sprint 12 Deferred 正本の全 9 件完了
  └─ SP022-T09 (must_ship): 実機 host migration drill (Mac→VPS) RTO≤4h PASS (post-acceptance verification、P0.1 unblock 必須 gate)

P0.1 unblock  (SP-022 must_ship 全件完了後、SP022-T05 + Phase E 実 contract test PASS + Phase G PGA-F-009 SP-015 依存 fixture は除外)
  ├─ TASKHUB_P0_1_OPENED=1 + P0 sealed CI guard 解除
  ├─ SP-013 multi-agent orchestration 着手
  ├─ SP-013〜016/SP-018/SP-020 の各 owning sprint exit gate で Phase E 16 finding (PE-F-001〜PE-F-016) の実 contract test PASS を検証 (F-PLAN-R3-001 + F-PLAN-R4-002 adopt、SP-022 では audit-only trace gate のみ)
  ├─ SP-015 完了後 owning sprint exit gate で Phase G PGA-F-009 inter_agent_messages consumed invariant fixture の post-restore + post-migration 全 case 実 verify (F-ADV-R1-001 adopt、SP-022 では audit-only trace gate のみ)
  └─ SP-022.1 / SP-023: AC-HARD-01〜07 multi-agent fixture (SP-013 skeleton 依存)
```

## 2. Scope & Out-of-Scope

### 2.1 In-Scope (本 PR で update)

- §1.3 ADR 状態 table (line 106-107): ADR-00021 / ADR-00007 行を update
- §5 ADR Acceptance Path (line 556-557、`### ADR-00011 acceptance timing 詳細` の前まで): 同 acceptance path 反映 + acceptance_blocked_by mutual cycle 解消反映
- §10 Next Action (line 659-689): A/B/C/D 全 subsection rewrite。**§10.C 実装着手順序は T00/T08/T09 概要のみ (F-PLAN-R1-002 adopt)**、T01-T07/T05 reroute 詳細は SP-022 Sprint Pack 参照
- §11 Open Decisions (line 690-714): Q1-Q5 + Q7 + Q8 を **accepted decision** として §11.1 に統合 (F-PLAN-R1-006 adopt)。新規 Open Decisions は Q6 (P0 Exit reflect timing) のみ §11.2 に残す
- §1.1 完了 Sprint table: **新規 block 追加** で Sprint 10/11/11.5/12 status + Sprint 12 partial_completed_with_carry_over 反映、既存累計 row を `**累計 (Sprint 7-9 historical)**` rename + Post Sprint 12 累計を別 block (F-PLAN-R1-008 adopt)
- §4 Critical Path (line 528-548): 1 行注釈追加 (Sprint 12 partial → SP-022 → P0.1 unblock、**SP-022 must_ship 全件 (特に T08+T09)** が P0.1 unblock 必須、F-PLAN-R1-005 adopt)

### 2.2 Out-of-Scope (本 PR では触らない、SP-022 完了時に別 PR)

- §0 Executive Summary の P0 Exit declaration reflect (F-PLAN-R1-007 adopt): SP-022 完了後の P0 Exit declaration PR で扱う
- §1 のうち §1.1/§1.3 以外 (line 50-119 のうち §1.2 P0 Hard Gates / KPIs trace の actuals reflect / §1.4 不足 Sprint Pack 等、F-PLAN-R1-007 adopt): 同 P0 Exit declaration PR で扱う
- §3 各 Sprint 詳細 (Sprint 10/11/11.5/12 individual sections、line 131-527): historical record として残す
- §6 Codex Multi-Round Budget 集計 (line 567-583): 累計 actuals 反映は SP-022 完了時の P0 Exit declaration PR で実施
- §7 Verification Gate (line 584-619): SP-022 verification は SP-022 Sprint Pack 側で正本管理、master plan §7 は historical
- §8 Risk + Rollback (line 620-643): SP-022 specific risks は SP-022 Sprint Pack 側で管理
- §9 Schedule (line 644-657): session 数 actuals は SP-022 完了時に反映
- ADR-00021 / ADR-00007 frontmatter `acceptance_history` future entry の文言 update (F-PLAN-R1-004 adopt): SP022-T00 PR で frontmatter 更新と同時実施
- ADR-00021 / ADR-00007 / ADR-00020 body section update: SP022-T00 PR で本体 update、本 PR は master plan の整合のみ
- SP-022 Sprint Pack 本体 rewrite: 本 PR は draft 維持、SP-022 着手時に別 PR で sprint scope re-allocation
- `docs/release/p0_exit_2026_MM_DD.md` 起票: SP-022 完了後
- TASKHUB_P0_1_OPENED=1 環境変数解禁: P0 Exit declaration PR で実施
- multi-agent fixture (AC-HARD-01〜07 multi-agent 文脈) verification: SP-013 skeleton 依存、SP-022.1 / SP-023 carry-over
- code change: 本 PR は docs-only

### 2.3 Scope creep 防止 trigger

以下が plan 内で発生したら **本 PR scope を逸脱**しているとみなし、別 PR に切り出す:

- §3 個別 Sprint section の本文 rewrite (新規 BL 追加 / target_days 変更等)
- §6 round budget 数値の更新 (P0 Exit declaration まで保留)
- §10 / §11 で SP-022 sub-task spec を **詳細列挙** (command / file name / sub-step、F-PLAN-R1-002 adopt: T00/T08/T09 概要 + Sprint Pack 参照のみ許可、T01-T07 詳細列挙は禁止)
- 新 ADR 起票 (P0.1+ で本 plan 別 PR)
- ADR body / frontmatter history 文言 update (SP022-T00 PR scope)
- frontend / backend code 変更 (本 PR は docs-only)

## 3. Changes to Apply

### 3.1 §1.3 ADR 状態 table update (line 106-107)

**現状 (drift)**:

```markdown
| ADR-00021 (Host-Portable Deployment) | proposed | Sprint 12 で host migration drill PASS 後 |
| ADR-00007 (External Exposure) update | proposed (host 中立 invariant) | Sprint 12 で ADR-00021 同期 accepted |
```

**update 後**:

```markdown
| ADR-00021 (Host-Portable Deployment) | proposed | **SP022-T00 pre-implementation gate** で ADR-00007 と同時 accepted (design accepted、実機 host migration drill PASS は SP022-T09 post-acceptance verification). 旧記述「Sprint 12 で host migration drill PASS 後」は PR #67 F-PR67-010/013 P2 adopt (R4 master plan grep verify) で **SP-022 carry-over** に決定済 |
| ADR-00007 (External Exposure) update | proposed (host 中立 invariant) | **SP022-T00 pre-implementation gate** で ADR-00021 と同時 accepted (F-PR67-042/047 P2 adopt: 旧 mutual blocking cycle (ADR-00021 ↔ ADR-00007 の reciprocal blocker) を common T00 simultaneous acceptance gate に置換し解消) |
```

### 3.2 §5 ADR Acceptance Path table update (line 556-557)

**現状 (drift)**:

```markdown
| ADR-00021 (Host-Portable Deployment) | proposed | Sprint 12 | host migration drill (Mac→VPS) RTO≤4h PASS + SP012-T01〜T10 完了。ADR-00021 frontmatter の accepted target を SP-012 で正式 update (Codex R1 F-R1-005 adopt: 既存 frontmatter の target Sprint 整合 verify が必要) |
| ADR-00007 update (External Exposure host 中立) | proposed | Sprint 12 | ADR-00021 と同期 accepted |
```

**update 後**:

```markdown
| ADR-00021 (Host-Portable Deployment) | proposed | **SP022-T00 pre-implementation gate** (PR #67 F-PR67-010/013/040/043/046/047 P2 adopt: R8 reinterpretation で「design accepted + post-acceptance drill verification」に整合、acceptance_blocked_by から実機 drill PASS を削除し SP022-T00 common simultaneous gate に置換) | (a) SP022-T00 で ADR-00007 と同時 design accepted (`.claude/rules/sprint-pack-adr-gate.md §12` 「実装着手直前に planned ADR を accepted 化」invariant 遵守、SP-022 実装着手 trigger)、(b) SP022-T08 で SP-012 §Sprint 12 Deferred 正本の全 9 件完了 (batch 6.1 / 実 DB write integration / signed journal CLI / AC-HARD real corpus + programmatic SUT / hard_gates_rollup real corpus + SUT wiring / taskhub real I/O / frontend i18n + Playwright E2E / audit_events DB trigger / private staging E2E)、(c) SP022-T09 で実機 host migration drill (Mac→VPS) RTO≤4h PASS = post-acceptance verification (旧「acceptance 必須条件」記述は撤回、design ADR 性質上 post-acceptance verification 方式を採用) |
| ADR-00007 update (External Exposure host 中立) | proposed | **SP022-T00 pre-implementation gate** | ADR-00021 と同期 accepted (F-PR67-047 P2 adopt: 旧「ADR-00021 同期 accepted」blocker は ADR-00021 側「ADR-00007 同期 accepted」を要求しており mutual deadlock になっていた、common SP022-T00 simultaneous acceptance gate を共通 blocker に置換し cycle 解消)。SP022-T09 で実機 drill 時に Tailscale 閉域維持 invariant verify |
```

### 3.3 §10 Next Action full rewrite (line 659-689)

**rewrite 理由**:

- subsection A (本 master plan accepted 化): 既に master plan は accepted (Codex plan-review R1-R2 を経て、F-R1-001〜F-R2-005 反映 + 累計 Sprint 10-12 完了で実証済)
- subsection B (不足 Sprint Pack 起票): SP-010 / SP-011 / SP-011.5 / SP-012 すべて完了済、Phase 5 plan 起票済。新 entry は SP-022 のみ
- subsection C (実装着手順序): Sprint 10-12 / Phase 5 すべて完了済。新 entry は SP-022 → P0.1 unblock。**T00/T08/T09 概要のみ、T01-T07/T05 詳細は SP-022 Sprint Pack 正本参照 (F-PLAN-R1-002 adopt)**
- subsection D (main ff merge timing): Sprint 12 完了 = `P0 Exit declaration` 記述は **誤り**。Sprint 12 は `partial_completed_with_carry_over` 状態、P0 Exit declaration は SP-022 must_ship 全件完了後 (T08 + T09 PASS 含む) に commit

**update 後 §10 (新版全文)**:

```markdown
## 10. Next Action (本 master plan accepted 化後の post-fix path)

### A. 本 master plan の status

- 2026-05-13 起票、Codex plan-review R1-R2 (F-R1-001〜F-R2-005 累計 36 finding 反映) で **accepted**
- Sprint 10/11/11.5/12 実装フェーズで累計 50+ Codex round / 200+ findings を吸収、本 plan の predictions (BL 数 / round budget / dependency graph) は実証済
- 残作業は **SP-022 (pre-P0.1 unblock sprint)** 1 件 → SP-022 must_ship 全件完了で P0 Exit declaration + P0.1 unblock

### B. 起票済 Sprint Pack + 完了状況

| Sprint Pack | status | merged | 備考 |
|---|---|---|---|
| `SP-010_research_evidence.md` (heavy) | completed | PR #19/21/22/24/26/27 | 10 BL (BL-0029c + BL-0113〜0121) 全件完了、ADR-00002 update accepted |
| `SP-011_eval_harness.md` (heavy) | completed | PR #38/39 | 16 BL (本来 12 + carry-over 完遂 5)、AC-HARD 7 fixture registry + AC-KPI 5 計測 endpoint 完成 |
| `SP-011-5_operational_hardening.md` (heavy) | completed (Sprint 11.5) | (SP-011 内に統合) | 14 BL (本来 11 + carry-over 3)、Codex R2 F-R2-002 adopt 反映済 |
| `SP-012_p0_acceptance.md` (heavy) | **partial_completed_with_carry_over** | PR #59-#67 (9 PR) | skeleton 完了、SP-022 carry-over (T08): `docs/sprints/SP-012_p0_acceptance.md §Sprint 12 Deferred` 正本の全 9 件 |
| `SP-022_framework_intake_hardening.md` (heavy) | **draft** (次着手) | — | pre-P0.1 unblock sprint、Sprint Pack 正本参照 (T00 + T01〜T07 + T08 carry-over + T09 実機 drill)、must_ship 全件で P0.1 unblock 達成 |
| `2026-05-13_phase5_hook_trust_boundary_plan.md` (Phase plan) | completed | — | 3 BL (BL-0082/0083/0084) + ADR-00012 accepted、SP-007 status `done_with_phase5_defer` → audit 一貫性確保 |

### C. 実装着手順序 (post Sprint 12、T00/T08/T09 概要のみ、T01-T07 詳細は SP-022 Sprint Pack 正本参照)

1. **SP-022 着手** (本 PR merge 後、F-ADV-R1-005 adopt: SP022-T00 PR の `base_sha` は本 PR merge commit 以降であること必須。既存 SP022-T00 branch がある場合は本 PR merge 後に merge/rebase + §6.1 + SP022-T00 専用 grep を再実行、PR description に base SHA + rerun evidence を貼ること):
   - **SP022-T00** (pre-implementation gate、F-ADV-R1-002 + F-ADV-R2-004 + F-ADV-R2-005 + F-ADV-R2-006 + F-ADV-R3-001 + F-ADV-R3-002 adopt atomic checklist、1 PR / 1 commit sequence、失敗時は全件 rollback):
     **0. (HARD GATE precondition、F-ADV-R3-002 adopt)** SP022-T00 PR diff (3 ADR status 変更 + ADR-00020 frontmatter blocker 再解釈 + ADR-00021/00007 frontmatter history 更新 + SP-022 `planned_adr_refs` → `adr_refs` 移動 + SP-022 Review 追記 + SP-022/SP-001-5 active text 同期 修正) に対し **`codex-plan-review` R1 minimum + adopt/reject/defer 採否判定** を実施 (`.claude/rules/sprint-pack-adr-gate.md §12.4` invariant 「ADR proposed→accepted 昇格 = codex-plan-review R1 minimum + 採否判定 経由必須」+ `.claude/rules/codex-usage-policy.md §14.1` mandatory Codex pre-commit gates、本 PR §6.2 post-PR auto-review baseline とは別の hard gate)。PR description / Review 欄に review round 番号、finding 件数 (CRITICAL / HIGH / MEDIUM / LOW)、各 finding の adopt / reject / defer 判定 + 理由、未解消 0 件の evidence を記録するまで PR merge 不可。
     1. **ADR status + updated_at + 最終更新行 同時更新 (F-ADV-R2-004 adopt)**: ADR-00020 + ADR-00021 + ADR-00007 frontmatter `status: proposed → accepted` + frontmatter `updated_at: <SP022-T00 implementation start date>` 同期更新 + 本文「最終更新」行も同日付に同期 (`.claude/rules/sprint-pack-adr-gate.md §12.1` invariant 「status 変更 + updated_at 更新」遵守)
     2. ADR-00020 frontmatter `acceptance_blocked_by` 再解釈 (「ADR-00014/16 accepted」「P0 完了」の循環依存解消、「multi-agent ADR-00014/00016 から独立 accept」へ、F-PLAN-R2-001 adopt)
     3. ADR-00021 / ADR-00007 frontmatter `acceptance_history` future entry 文言 update (SP022-T00 design accepted + SP022-T09 post-acceptance verification 表現に、F-PLAN-R1-004 adopt)
     4. SP-022 frontmatter `planned_adr_refs` → `adr_refs` 移動 (3 ADR: ADR-00020/00021/00007)、**`planned_adr_refs` key 自体を完全削除** (`.claude/rules/sprint-pack-adr-gate.md §12.1` 12.2 promotion 完了 trigger)
     5. SP-022 `## Review` (実装後追記、accepted 化日時記録、`.claude/rules/sprint-pack-adr-gate.md §12.1` 12.3 promotion 完了 trigger)
     6. SP-022 + SP-001-5 active text 同期 修正:
        - SP-022 L162 「ADR-00014〜00019 accepted 済」→「P0.1+ owning sprint で proposed→accepted 予定」(F-ADV-R1-006 adopt)
        - SP-001-5 active text 7 箇所 (L38/52/72/92/97/130/148) の旧 acceptance path 文言 update (F-PLAN-R4-001 + F-PLAN-R5-002 adopt)
        - SP-022 must_ship 表 Phase E 16 finding closure (L74 task list / L94 must_ship 表 / L104 受け入れ条件 / L124-126 検証手順) を audit-only gate / post-P0.1 contract test PASS split (F-PLAN-R3-001 + F-PLAN-R5-001 adopt)
        - SP-022 Phase G must_ship PGA-F-009 (L172 / L187) を audit-only gate / post-P0.1 SP-015 完了後 contract test PASS split (F-ADV-R1-001 adopt)
     
     **verification (fail-closed exact assertion、F-ADV-R2-005 + F-ADV-R2-006 + F-ADV-R3-001 + F-ADV-R4-001 adopt: display grep を exact value/count/equality assertion に置換、ADR proposed のままで通る fail-open path 排除、yq は frontmatter 抽出後に `-e` で適用 + `set -euo pipefail` で parser failure を必ず hard fail)**:
     ```bash
     set -euo pipefail  # F-ADV-R4-001 adopt: parser failure / undefined var を必ず hard fail
     SP022_T00_DATE=$(date -u +%Y-%m-%d)  # SP022-T00 implementation start date
     
     # SP-022 Sprint Pack frontmatter 抽出 (YAML frontmatter 付き Markdown のため yq direct parse は不可、F-ADV-R4-001 adopt)
     SP022_FRONTMATTER=$(awk 'NR==1 && $0=="---" {in_fm=1; next} in_fm && $0=="---" {exit} in_fm {print}' docs/sprints/SP-022_framework_intake_hardening.md)
     
     # (1) 3 ADR status が exact "accepted" であること fail-closed assert (F-ADV-R3-001)
     for adr in 00020_framework_intake_checklist.md 00021_host_portable_deployment.md 00007_external_exposure.md; do
       if ! rg -q '^status:\s*"accepted"' "docs/adr/$adr"; then
         echo "FAIL: docs/adr/$adr status != \"accepted\"" >&2; exit 1
       fi
     done
     
     # (2) 3 ADR updated_at が SP022_T00_DATE と exact equality (F-ADV-R3-001 + F-ADV-R2-004)
     for adr in 00020_framework_intake_checklist.md 00021_host_portable_deployment.md 00007_external_exposure.md; do
       actual=$(rg -m1 '^updated_at:' "docs/adr/$adr" | sed -E 's/^updated_at:\s*"?([^"\s]+)"?.*/\1/')
       if [ "$actual" != "$SP022_T00_DATE" ]; then
         echo "FAIL: docs/adr/$adr updated_at=$actual != $SP022_T00_DATE" >&2; exit 1
       fi
     done
     
     # (3) SP-022 adr_refs が exact set {ADR-00020, ADR-00021, ADR-00007} であること assert (F-ADV-R3-001 + F-ADV-R2-005 + F-ADV-R4-001)
     # frontmatter を yq -e に渡す (yq -e は entry 不在 / parse error 時 exit non-zero)
     adr_refs_count=$(printf '%s\n' "$SP022_FRONTMATTER" | yq -e '.adr_refs | length' -)
     if [ "$adr_refs_count" != "3" ]; then
       echo "FAIL: SP-022 adr_refs count=$adr_refs_count != 3" >&2; exit 1
     fi
     adr_refs_list=$(printf '%s\n' "$SP022_FRONTMATTER" | yq -e '.adr_refs[]' -)
     for adr_id in ADR-00020 ADR-00021 ADR-00007; do
       if ! echo "$adr_refs_list" | rg -q "$adr_id"; then
         echo "FAIL: SP-022 adr_refs does not include $adr_id" >&2; exit 1
       fi
     done
     
     # (4) SP-022 planned_adr_refs key absent fail-closed (F-ADV-R3-001 + F-ADV-R2-005 + F-ADV-R4-001)
     # yq -e '.planned_adr_refs // "absent"' は key 不在時 "absent" を返す。null literal を含む key は "null" を返すので別途 hard fail
     planned_check=$(printf '%s\n' "$SP022_FRONTMATTER" | yq -e '.planned_adr_refs // "absent"' -)
     if [ "$planned_check" != "absent" ]; then
       echo "FAIL: SP-022 still has planned_adr_refs key (value=$planned_check、should be removed after promotion)" >&2; exit 1
     fi
     # 二重防御: rg でも planned_adr_refs key 行不在を確認 (yq normalize で key 消失する pathological case 防止)
     if rg -q '^planned_adr_refs:' docs/sprints/SP-022_framework_intake_hardening.md; then
       echo "FAIL: SP-022 still has planned_adr_refs key line (raw rg check)" >&2; exit 1
     fi
     
     # (5) SP-022 L162 stale text 修正後 (F-ADV-R1-006)
     if rg -q 'accepted 済' docs/sprints/SP-022_framework_intake_hardening.md; then
       echo "FAIL: SP-022 still has 'accepted 済' stale text" >&2; exit 1
     fi
     
     # (6) SP-001-5 active text 旧 acceptance path 修正後 (F-PLAN-R4-001 + F-PLAN-R5-002 + F-ADV-R2-006)
     if rg -qP '^[^#].*SP-022 で実機 host migration drill PASS 後' docs/sprints/SP-001-5_host_portable_amendment.md; then
       echo "FAIL: SP-001-5 active text still has 'SP-022 で実機 host migration drill PASS 後'" >&2; exit 1
     fi
     if rg -qP '^[^#].*SP-022 carry over' docs/sprints/SP-001-5_host_portable_amendment.md; then
       echo "FAIL: SP-001-5 active text still has 'SP-022 carry over'" >&2; exit 1
     fi
     
     # (7) SP-022 Phase E active requirement 不在 verify (audit-only split 完了、F-ADV-R2-006)
     if rg -qP '^- \[ \].*Phase E 16 finding が全件 closed' docs/sprints/SP-022_framework_intake_hardening.md; then
       echo "FAIL: SP-022 still has Phase E active task list (audit-only split incomplete)" >&2; exit 1
     fi
     if rg -qP 'Phase E 16 finding closure\s*\|\s*○\s*\|\s*LOW' docs/sprints/SP-022_framework_intake_hardening.md; then
       echo "FAIL: SP-022 still has Phase E must_ship=○ row (audit-only split incomplete)" >&2; exit 1
     fi
     
     # (8) SP-022 Phase G PGA-F-009 SP-015 依存 active requirement 不在 verify (audit-only split 完了、F-ADV-R2-006 + F-ADV-R1-001)
     if rg -qP 'SP-015 で実装されたものを SP-022 で\s*追加 fixture' docs/sprints/SP-022_framework_intake_hardening.md; then
       echo "FAIL: SP-022 still has Phase G PGA-F-009 SP-015 依存 active fixture (audit-only split incomplete)" >&2; exit 1
     fi
     
     # (9) audit-only gate / post-P0.1 carry-over の positive 補助確認
     rg -q 'audit-only.*trace gate' docs/sprints/SP-022_framework_intake_hardening.md || { echo "FAIL: SP-022 missing 'audit-only trace gate' positive marker" >&2; exit 1; }
     rg -q 'post-P0\.1 owning sprint exit gate' docs/sprints/SP-022_framework_intake_hardening.md || { echo "FAIL: SP-022 missing 'post-P0.1 owning sprint exit gate' positive marker" >&2; exit 1; }
     
     # (10) HARD GATE evidence: codex-plan-review R1 完了 record (F-ADV-R3-002)
     # PR description / Review 欄に review round 番号、finding 件数 (CRITICAL/HIGH/MEDIUM/LOW)、各 finding の adopt/reject/defer 判定 + 理由、未解消 0 件 evidence が記録されていること
     # (機械検査は PR meta data scrape または手動 reviewer 確認に委ねる)
     
     # (11) ADR-00020 frontmatter `acceptance_blocked_by` 再解釈 verify (F-ADV-R5-001 adopt: 旧 cyclic blocker 削除 + SP022-T00 independent accept marker 存在)
     ADR20_FRONTMATTER=$(awk 'NR==1 && $0=="---" {in_fm=1; next} in_fm && $0=="---" {exit} in_fm {print}' docs/adr/00020_framework_intake_checklist.md)
     # 旧 cyclic blocker ("ADR-00014/16 accepted" / "P0 完了") が削除されていること fail-closed assert
     if printf '%s\n' "$ADR20_FRONTMATTER" | yq -e '.acceptance_blocked_by[]?' - 2>/dev/null | rg -q 'ADR-00014/16 accepted|P0 完了'; then
       echo "FAIL: ADR-00020 still has cyclic acceptance_blocked_by (ADR-00014/16 accepted or P0 完了)" >&2; exit 1
     fi
     # SP022-T00 independent accept marker が存在すること fail-closed assert (multi-agent ADR-00014/00016 から独立 accept への再解釈)
     printf '%s\n' "$ADR20_FRONTMATTER" | yq -e '.acceptance_blocked_by[]? | select(test("SP022-T00|multi-agent ADR-00014/00016 から独立 accept"))' - >/dev/null || {
       echo "FAIL: ADR-00020 acceptance_blocked_by missing SP022-T00 independent accept marker" >&2; exit 1
     }
     
     # (12) SP-022 `## Review` で 3 ADR `accepted_at: $SP022_T00_DATE` 記録 verify (F-ADV-R5-001 adopt: step 5 promotion completion record の機械検査)
     for adr_id in ADR-00020 ADR-00021 ADR-00007; do
       if ! rg -qP "$adr_id\s+accepted_at:\s*$SP022_T00_DATE" docs/sprints/SP-022_framework_intake_hardening.md; then
         echo "FAIL: SP-022 Review missing $adr_id accepted_at: $SP022_T00_DATE record" >&2; exit 1
       fi
     done
     ```
   - **SP022-T01〜T07**: framework intake CI + taskhub migrate 自動化 + drill SOP + Phase E 16 finding closure + KPI baseline + production checklist + Phase G strengthening hardening (詳細は `docs/sprints/SP-022_framework_intake_hardening.md` 正本参照)
   - **SP022-T08** (must_ship): SP-012 §Sprint 12 Deferred 正本の全 9 件完了 (batch 6.1 Pydantic schema / 実 DB write integration / signed journal verification CLI / AC-HARD-01/02/05/06/07 real corpus + programmatic SUT / hard_gates_rollup real corpus + SUT wiring / taskhub real I/O 10 subcommands / frontend i18n + Playwright E2E / audit_events DB trigger / private staging CI/E2E)
   - **SP022-T09** (must_ship): 実機 host migration drill (Mac→VPS) PASS、RTO≤4h verify (post-acceptance verification、P0.1 unblock 必須 gate)
2. **P0 Exit declaration**: SP-022 Sprint Pack must_ship 表で must_ship=○ の項目全件完了。**ただし以下 3 件は SP-013〜020 future-sprint 依存のため post-P0.1 carry-over として P0 Exit gate から除外 (F-PR67-037/039 + F-PLAN-R2-002 + F-PLAN-R3-001 + F-ADV-R1-001 adopt 既決定)**:
   - **SP022-T05 AC-HARD multi-agent fixture**: SP-013 skeleton 依存
   - **Phase E 16 finding (PE-F-001〜PE-F-016) closure の "実 contract test PASS"**: SP-013〜016/SP-018/SP-020 contract test 依存。SP-022 must_ship では **audit-only gate** (PE-F が各 owning ADR/Sprint Pack の must_ship に反映済で受け入れ条件に trace されている) のみ要求、実 contract test PASS は post-P0.1 owning sprint exit gate
   - **Phase G PGA-F-009 inter_agent_messages consumed invariant fixture**: SP-015 完了後の fixture (post-restore + post-migration 全 case) で再 verify 要求 = SP-015 依存。SP-022 must_ship では **audit-only gate** (PGA-F-009 が SP-015 owning sprint must_ship に反映済) のみ要求、実 contract test PASS は post-P0.1 SP-015 完了後 owning sprint exit gate
   
   特に T08 + T09 が P0.1 unblock 直接 gate = Hard Gates 7 全件 PASS + Quality KPIs 5 未達 1 個以下 + backup/restore drill + 実機 host migration drill PASS 達成、`docs/release/p0_exit_2026_MM_DD.md` commit
3. **P0.1 unblock**: TASKHUB_P0_1_OPENED=1 + P0 sealed CI guard 解除 + SP-013 (multi-agent orchestration) 着手
4. **post-P0.1 carry-over** (SP-022.1 / SP-023 + owning sprint 内処理):
   - SP-022.1: AC-HARD-01〜07 fixture を multi-agent 文脈で再 verify (SP-013 skeleton 依存)、SP022-T05 post-P0.1 reroute (F-PR67-037/039 P2 adopt、本 P0 Exit gate から除外済)
   - SP-013〜016/SP-018/SP-020 各 owning sprint exit gate: **Phase E 16 finding (PE-F-001〜PE-F-016) の実 contract test PASS を verify** (F-PLAN-R3-001 + F-PLAN-R4-002 adopt、SP-022 では audit-only trace gate のみ must_ship、実 test PASS は各 owning sprint 内処理で独立 carry-over Sprint Pack は不要)
   - SP-015 完了後 owning sprint exit gate: **Phase G PGA-F-009 inter_agent_messages consumed invariant fixture (post-restore + post-migration 全 case) の実 contract test PASS を verify** (F-ADV-R1-001 adopt、SP-022 では audit-only trace gate のみ must_ship、実 test PASS は SP-015 owning sprint 内処理)
   - SP-023: production 公開準備 final hardening (`docs/sprints/SP-022_framework_intake_hardening.md` 次スプリント候補参照、F-ADV-R1-007 adopt: SP022-T07 では docs-only checklist skeleton まで、production 実作業 = Docker image build / DNS / 外部公開 / license/docs 整備は SP-023 以降に分離)

### D. main merge timing (F-ADV-R2-002 adopt 反映、PR 経由のみ、main 直接 commit / push 禁止)

- 各 Sprint Exit (`uv run pytest -q` + `frontend` PASS + Sprint Pack `## Review` 記載) 後に **worktree branch から PR 起票 → Codex baseline 確認 + multi-round adopt/reject/defer 採否判定 → user が PR merge** (CLAUDE.md §6.5.8 PR 起票・merge 責務分離 + `.claude/rules/branch-and-pr-workflow.md` L9-13 invariant)
- **local main への直接 commit / push / ff merge は禁止** (`branch-and-pr-workflow.md` 「main / master への直接 commit / push 禁止 (PR 経由のみ)」絶対遵守)
- **SP-022 must_ship 全件完了**で **P0 Exit declaration** を `docs/release/p0_exit_2026_MM_DD.md` に commit + master plan §0/§1/§3-§9 を P0 Exit declaration PR で reflect (本 PR と別)
- P0 Exit declaration commit 後に **TASKHUB_P0_1_OPENED=1** 環境変数を `.env.example` / docker-compose / CI guard で解禁
```

### 3.4 §11 Open Decisions full rewrite (line 690-714)

**rewrite 理由**: Q1-Q5 はすべて Sprint 10/11/12 着手前の open decision、現在は実装で実証済の accepted decision として close 可能。F-PLAN-R1-006 adopt により、Q7 (ADR-00020 SP022-T00 同時 acceptance) は SP-022 frontmatter L16 で既に固定済、Q8 (SP-022.1 / SP-023 独立 Sprint Pack 起票) は plan §1.2 / §2.2 で default 採用済のため、両方 §11.1 accepted decisions に移動。残る Open Decision は Q6 (本 PR と P0 Exit reflect PR の分離) のみ。

**update 後 §11 (新版全文)**:

```markdown
## 11. Open Decisions (本 plan accepted 後の status + SP-022 開始に伴う新規 decisions)

### 11.1 過去の Open Decisions (Sprint 10-12 + SP-022 設計時に決定済、実装または Sprint Pack で実証済)

- **Q1**: Sprint 10 と Sprint 11 を sequential or 並走?  
  決定: **sequential** (Sprint 10 → Sprint 11) を採用、scope creep 防止。Sprint 10 全 10 BL を Sprint 11 着手前に完了 (PR #19/21/22/24/26/27 で実証)

- **Q2**: ADR-00011 accepted 化 timing?  
  決定: **Sprint 11.5 末** で 8/8 unblock 達成後 accepted。Codex R1 F-R1-004 + R2 F-R2-001 反映済

- **Q3**: Phase 5 を Sprint 11 と並走 or Sprint 12 と並走?  
  決定: **Sprint 11 と並走**、SP-007 status 早期昇格で audit 一貫性確保 (Phase plan で実証済)

- **Q4**: Sprint 11 で carry-over 15 BL を 1 Sprint で扱う or Sprint 11a / 11b 分割?  
  決定: **1 Sprint** で扱う、batch 6-8 分割で慎重に。実 effort は 16 BL (本来 12 + carry-over 完遂 5)、PR #38/#39 で実証

- **Q5**: Sprint 11 で SP-008 / SP-009 status を `done` 昇格させるか、`done_with_carry_over_complete` 等 custom status か?  
  決定: **`done` 昇格** (carry-over BL は別 Sprint Pack で扱うため SP-008/009 自体は完了)、ただし PR #38/#39 R1 audit (`feedback_codex_pr_review_baseline_check.md` 教訓) で **SP-008/009 status 昇格撤回** が必要と判明 → 個別 BL repo grep verify 必須化、各 BL repo grep verify 教訓化

- **Q7 (旧 §11.2 提案を accepted decision に移動、F-PLAN-R1-006 adopt + F-PLAN-R2-001 reinterpretation)**: ADR-00020 (Framework Intake Checklist) acceptance を SP022-T00 で ADR-00021 / ADR-00007 と **同時** にするか、SP022-T01 (CI 機械化完成後) に **後段** で実施するか?  
  決定: **SP022-T00 同時** (`docs/sprints/SP-022_framework_intake_hardening.md` L16/L57/L70-72 で既に SP022-T00 同時 acceptance を固定済、`.claude/rules/sprint-pack-adr-gate.md §12` invariant 「実装着手直前に planned ADR を accepted 化」遵守)。**ただし precondition (F-PLAN-R2-001 adopt)**: ADR-00020 frontmatter `acceptance_blocked_by: ["ADR-00014/16 accepted", "P0 完了"]` は循環依存 (ADR-00014/00016 proposed + ADR-00016 が ADR-00020 accepted を blocker に含む) のため、SP022-T00 PR で ADR-00020 frontmatter blocker 再解釈 (multi-agent ADR-00014/00016 から独立 accept) を同時実施する必要がある。本 PR は master plan のみ scope のため §7 out-of-scope に明記、SP022-T00 PR で precondition として処理

- **Q8 (旧 §11.2 提案を accepted decision に移動、F-PLAN-R1-006 adopt + F-PLAN-R4-002 拡張)**: SP-022.1 / SP-023 (post-P0.1 carry-over) を独立 Sprint Pack として起票するか、SP-013 multi-agent skeleton sprint に **fixture verification** として包含するか?  
  決定: **独立 Sprint Pack 起票** (SP-022.1: AC-HARD-01〜07 multi-agent fixture verification、SP-023: production 公開準備 final hardening) で扱う、SP-013 scope は multi-agent core 実装のみに集中 (本 plan §1.2 / §2.2 + SP-022 frontmatter で default 採用済)。**Phase E 16 finding (PE-F-001〜PE-F-016) の実 contract test PASS は独立 Sprint Pack 化せず、SP-013〜016/SP-018/SP-020 の各 owning sprint exit gate 内で処理** (F-PLAN-R4-002 adopt、SP-022.1 / SP-023 とは別軸、SP-022 では audit-only trace gate のみ must_ship)

### 11.2 SP-022 開始に伴う新規 Open Decisions

- **Q6**: SP-022 着手後の master plan §3 / §6 / §7 / §8 / §9 (historical record) 反映 timing を **P0 Exit declaration PR (SP-022 完了後)** で 1 回にまとめるか、**SP-022 中盤の intermediate PR** で partial reflect (drift 状態を短縮) するか?  
  default: **P0 Exit declaration PR (SP-022 完了後)** で 1 回 (本 PR で master plan §10-§11 + §1.3 / §5 drift fix を済ませた前提、scope creep 防止のため historical record の partial update を増やさない)  
  代替: SP-022 中盤で intermediate PR を起票し、§0/§1.1/§1.2/§3-§9 actuals を partial reflect (drift 状態を SP-022 完了より早く解消、ただし PR 数増加 + 中間状態の管理コスト発生)

### 11.3 close 条件

- Q6 → SP-022 着手 PR (SP022-T00) で decide。本 PR では default 維持

---

(本 plan §10-§11 update は drift fix 目的、scope creep 回避のため §3-§9 historical sections は P0 Exit declaration PR で別 update 予定)
```

### 3.5 §1.1 完了 Sprint table 追加 row (F-PLAN-R1-008 adopt 反映)

**§1.1 完了 Sprint table** (line 50-66) の **既存 `**累計**` row (line 66) を `**累計 (Sprint 7-9 historical)**` に rename** + Sprint 10/11/11.5/12 + 新 `**累計 (Post Sprint 12)**` row を別 block で追加:

```markdown
| Sprint 9 (P0 UI Pack) | **skeleton_pending_backend** | 5/10 + 3 client draft | R1-R3 (3 round) | 6 (3 adopt + 3 既存 backlog) |
| **累計 (Sprint 7-9 historical)** | | **20/33 ≈ 60% (Sprint 7-9)** | **13 round** | **32 findings** |
| Sprint 10 (Research/Evidence) | done | 10/10 | R1-R6 (累計 47 round) | 107 findings (PR #19/21/22/24/26/27) |
| Sprint 11 (Eval Harness) | done | 16/16 (本来 12 + carry-over 完遂 5) | R1-R7 累計 | AC-HARD 7 + AC-KPI 5 fixture registry 完成 (PR #38/#39) |
| Sprint 11.5 (Operational Hardening) | done | 14/14 (本来 11 + carry-over 3) | R1-R10 累計 | (Sprint 11 内に統合)、Codex R2 F-R2-002 反映済 |
| Sprint 12 (P0 Acceptance) | **partial_completed_with_carry_over** | 23+ skeleton 完了 | R1-R11 (9 PR、累計 41+ round / 117+ findings) | SP-022 carry-over: SP-012 §Sprint 12 Deferred 正本の全 9 件 (PR #59-#67) |
| **累計 (Post Sprint 12)** | | **Sprint 10-12 完了 + Sprint 12 partial** | **累計 100+ round (Sprint 7-12)** | **300+ findings 100% adopt (Sprint 7-12)** |
```

### 3.6 §4 Critical Path 置換 + 1-line addition (F-PLAN-R1-005 + F-ADV-R2-001 adopt 反映、既存 active text 置換 + 注釈追加)

**現状 (drift active text)**:

```text
Sprint 10 (Research/Evidence)
  ↓ (AC-KPI-04 source ticket)
Sprint 11 (Eval Harness + Sprint 7-9 carry-over)
  ↓ (Hard Gates 7 fixture registry / SP-008 status done / SP-009 status done / ADR-00011 accepted)
Sprint 11.5 (Observability + a11y/responsive)
  ↓ (rotation drill / dashboard / Permission Matrix CLI)
Sprint 12 (P0 Acceptance + Phase G strengthening)
  → P0 Exit

[並走可能]
Phase 5 (Hook Trust Boundary)
  → SP-007 status done 昇格 (independent of Sprint 10-12)
  → ADR-00012 accepted
```

```markdown
**Critical path**: Sprint 10 → 11 → 11.5 → 12 (Sprint 12 が P0 Exit gate)。Phase 5 は SP-007 status 昇格にのみ影響 (Sprint 11/12 と並走可、ただし P0 Exit blocker ではない)。
```

**update 後 (F-ADV-R2-001 adopt、Sprint 12 partial → SP-022 → P0 Exit に置換)**:

```text
Sprint 10 (Research/Evidence)
  ↓ (AC-KPI-04 source ticket)
Sprint 11 (Eval Harness + Sprint 7-9 carry-over)
  ↓ (Hard Gates 7 fixture registry / SP-008 status done / SP-009 status done / ADR-00011 accepted)
Sprint 11.5 (Observability + a11y/responsive)
  ↓ (rotation drill / dashboard / Permission Matrix CLI)
Sprint 12 (P0 Acceptance、partial_completed_with_carry_over)
  ↓ (SP-012 skeleton 実装着手済、SP-012 §Sprint 12 Deferred 全 9 件 carry-over)
SP-022 (pre-P0.1 unblock sprint)
  ↓ (SP022-T00 ADR accept + T01-T04/T06-T07 + T08 carry-over + T09 実機 drill PASS、SP022-T05 + Phase E + Phase G post-P0.1 除外)
  → P0 Exit declaration + P0.1 unblock

[並走可能]
Phase 5 (Hook Trust Boundary)
  → SP-007 status done 昇格 (independent of Sprint 10-12)
  → ADR-00012 accepted
```

```markdown
**Critical path (Post-fix path、2026-05-19)**: Sprint 10 → 11 → 11.5 → 12 (partial) → **SP-022 (pre-P0.1 unblock sprint)** → P0 Exit declaration → P0.1 unblock。Sprint 12 は `partial_completed_with_carry_over`、`P0 Exit` 到達には **SP-022 Sprint Pack must_ship 表で must_ship=○ の項目全件完了** (ADR-00020/00021/00007 SP022-T00 accept + T01-T04/T06-T07 + T08 SP-012 §Sprint 12 Deferred 全 9 件 + T09 実機 host migration drill PASS) が必須、特に T08 + T09 が P0.1 unblock 直接 gate。以下 3 件は SP-013〜020 future-sprint 依存のため post-P0.1 carry-over として P0 Exit gate から除外: (a) SP022-T05 AC-HARD multi-agent fixture (SP-013 skeleton 依存)、(b) Phase E 16 finding (PE-F-001〜016) 実 contract test PASS (SP-013〜016/SP-018/SP-020 依存、SP-022 は audit-only gate のみ)、(c) Phase G PGA-F-009 inter_agent_messages consumed invariant fixture 実 contract test PASS (SP-015 依存、SP-022 は audit-only gate のみ)、F-PR67-037/039 + F-PLAN-R2-002 + F-PLAN-R3-001 + F-ADV-R1-001 + F-ADV-R2-001 adopt 既決定。Phase 5 は SP-007 status 昇格にのみ影響 (Sprint 11/12 と並走可、ただし P0 Exit blocker ではない)。詳細 §10.B-C 参照。
```

## 4. Invariant Trace Matrix

本 PR の change が各 invariant / cross-source contract に影響しないことを verify する trace。

| invariant | 対応 rule | 本 PR 影響 | verification |
|---|---|---|---|
| ADR Gate Criteria 11 種 | `.claude/rules/sprint-pack-adr-gate.md §4` | 影響なし (11 種 enum 維持) | grep "Gate Criteria 11" — table 行数不変 |
| ADR accepted promotion normal-flow | `.claude/rules/sprint-pack-adr-gate.md §12` | **強化** (SP022-T00 pre-implementation gate を明示) | §3.1 §1.3 / §3.2 §5 table で SP022-T00 trigger 明示 |
| Codex review hard gate (CRITICAL invariant) | `.claude/rules/codex-usage-policy.md §14` | 影響なし (本 PR は docs-only) | code change なし |
| AgentRun 16 状態 + blocked サブ 3 | `.claude/rules/agentrun-state-machine.md §1-2` | 影響なし | enum 不変 |
| ContextSnapshot 必須 10 列 | `.claude/CLAUDE.md §2.8` + `agentrun-state-machine.md §11` | 影響なし | enum 不変 |
| Provider Compliance 13 reason_code | `.claude/rules/provider-compliance.md §9` | 影響なし | enum 不変 |
| SecretBroker atomic claim | `.claude/rules/secretbroker-boundary.md §8` | 影響なし | code change なし |
| tenant/project boundary 複合 FK | `.claude/rules/core.md §8` | 影響なし | DDL 不変 |
| Hard Gates 7 + Quality KPIs 5 | `.claude/CLAUDE.md §2.Hard Gates` | 影響なし (SP-022 で fixture 充足) | enum 不変 |
| caller-supplied 経路禁止 | `.claude/rules/server-owned-boundary.md` | 影響なし | code change なし |
| cross-source enum integrity (5+ source) | `.claude/rules/cross-source-enum-integrity.md` | 影響なし | enum 不変 |
| Tailscale 閉域 (Funnel 不使用) | `.claude/CLAUDE.md §2.2` + ADR-00007 | 影響なし | network 設定不変 |
| `git add -A` / `git add .` 禁止 | `.claude/CLAUDE.md §6.7` | 遵守 (本 PR は明示 file 指定) | commit 時 verify |

## 5. Rollback

本 PR は docs-only。rollback 手順:

1. `git revert <merge commit>` で master plan / .claude/plans を pre-PR 状態に戻す (2 files revert で完結、code 影響なし)
2. SP-012 / SP-022 / ADR-00021 / ADR-00007 / SP-001-5 の current state は本 PR と独立 (PR #67 で確定済) のため、本 PR rollback は他 doc に影響しない
3. drift state は再発するが、PR #67 で carry-over 決定済の通り、別 PR で再 update 可能

## 6. Verification

### 6.1 Pre-commit verification (F-PLAN-R1-003 + F-PLAN-R2-003 adopt 反映、historical evidence + historical quote 許容)

```bash
# master plan target sections の line range が想定と一致
rg -n "^## 10\. Next Action|^## 11\. Open Decisions|^### 1\.3 ADR 状態|^## 5\. ADR Acceptance Path" docs/設計検討/2026-05-13_p0_exit_master_plan.md

# acceptance path drift 検出: master plan の **active table row** に旧文言が残っていないこと verify (F-PLAN-R2-003 + F-PLAN-R4-003 adopt 構造化 grep、4 active row 全件不在 verify、historical quote 許容)

# (1) ADR-00021 §1.3 旧 row: "| ADR-00021 ... | proposed | Sprint 12 で host migration drill PASS 後 |"
! rg -nP '^\|\s*ADR-00021[^|]*\|\s*proposed\s*\|\s*Sprint 12 で host migration drill PASS 後\s*\|' docs/設計検討/2026-05-13_p0_exit_master_plan.md

# (2) ADR-00007 §1.3 旧 row: "| ADR-00007 ... | proposed (host 中立 invariant) | Sprint 12 で ADR-00021 同期 accepted |"
! rg -nP '^\|\s*ADR-00007[^|]*\|\s*proposed[^|]*\|\s*Sprint 12 で ADR-00021 同期 accepted\s*\|' docs/設計検討/2026-05-13_p0_exit_master_plan.md

# (3) ADR-00021 §5 旧 row: "| ADR-00021 ... | proposed | Sprint 12 | host migration drill (Mac→VPS) RTO≤4h PASS ... |"
! rg -nP '^\|\s*ADR-00021[^|]*\|\s*proposed\s*\|\s*Sprint 12\s*\|\s*host migration drill' docs/設計検討/2026-05-13_p0_exit_master_plan.md

# (4) ADR-00007 §5 旧 row: "| ADR-00007 update ... | proposed | Sprint 12 | ADR-00021 と同期 accepted |"
! rg -nP '^\|\s*ADR-00007 update[^|]*\|\s*proposed\s*\|\s*Sprint 12\s*\|\s*ADR-00021 と同期 accepted\s*\|' docs/設計検討/2026-05-13_p0_exit_master_plan.md

# positive 補助確認: 新 row が SP022-T00 pre-implementation gate を含む (4 hit 想定: §1.3 ADR-00021 + ADR-00007、§5 ADR-00021 + ADR-00007)
rg -nP '^\|\s*ADR-000(21|07)[^|]*\|.*SP022-T00 pre-implementation gate' docs/設計検討/2026-05-13_p0_exit_master_plan.md  # expected: 4 行 hit

# Note: SP022-T00 update 後の active row は「accepted 化 path」列に "SP022-T00 pre-implementation gate" を含む。
#       historical quote (例: `旧記述「Sprint 12 で host migration drill PASS 後」は ... に決定済`) は drift trace として valuable + 許容。
#       docs/sprints/SP-012_p0_acceptance.md / docs/adr/00021_host_portable_deployment.md の同 phrase も
#       historical/diagnostic comment として残存許可 (本 PR scope 外、SP022-T00 PR で update)。

# §10 / §11 active text drift verify (F-ADV-R1-003 adopt、§1.3 / §5 だけ直して §10 / §11 旧状態が残る攻撃シナリオ防止)

# §10 旧 active text の不在 verify (Phase 1 R6 clean signal 反映後の master plan に旧 §10 行が active text として残らない、historical quote / "旧記述「...」" 表現は許容)
# (5) 旧 §10 「Sprint 10 batch 0 ... から開始」(line 677-679 周辺)
! rg -nP '^1\.\s+Sprint 10 batch 0\s*\(ADR-00002 update' docs/設計検討/2026-05-13_p0_exit_master_plan.md
# (6) 旧 §10.D 「Sprint 12 完了で **P0 Exit declaration**」
! rg -nP 'Sprint 12 完了で \*\*P0 Exit declaration\*\*' docs/設計検討/2026-05-13_p0_exit_master_plan.md

# §11 旧 active text の不在 verify (Q1〜Q5 が active text として残らない、historical quote 許容)
# (7) 旧 §11 「本 plan で未決定、Codex plan-review で決定したい項目」見出し
! rg -nP '^## 11\. Open Decisions \(本 plan で未決定' docs/設計検討/2026-05-13_p0_exit_master_plan.md
# (8) 旧 Q1-Q5 が §11 active decision として残らない (新 §11 では §11.1 accepted decisions に移動済)
! rg -nP '^- \*\*Q[1-5]\*\*: .* \?\s*$' docs/設計検討/2026-05-13_p0_exit_master_plan.md  # 旧 形式の active 未決定 prompt が残っていないこと

# §10 / §11 新 active text の positive 補助確認
rg -n "SP-022 \(pre-P0\.1 unblock sprint\)" docs/設計検討/2026-05-13_p0_exit_master_plan.md  # 新 §10.B で hit 必須
rg -nP '^### 11\.2 SP-022 開始に伴う新規 Open Decisions' docs/設計検討/2026-05-13_p0_exit_master_plan.md  # 新 §11.2 hit 必須
rg -nP '^- \*\*Q6\*\*:' docs/設計検討/2026-05-13_p0_exit_master_plan.md  # Q6 が残る唯一の active open decision

# SP022-T00 pre-implementation gate が master plan §1.3 / §5 / §10 / §11 で hit
rg -n "SP022-T00 pre-implementation gate" docs/設計検討/2026-05-13_p0_exit_master_plan.md  # §1.3 / §5 / §10 で複数 hit
rg -n "SP022-T00 pre-implementation gate" docs/  # master plan + SP-012/SP-022/ADR-00021/00007/SP-001-5 で複数 hit (drift fix 全体の整合)

# ADR-00021 / ADR-00007 frontmatter status 一致
rg -n "^status:" docs/adr/00021_host_portable_deployment.md docs/adr/00007_external_exposure.md  # 両方 "proposed"

# SP-022 frontmatter status (draft 維持、本 PR で変更しない)
rg -n "^status:" docs/sprints/SP-022_framework_intake_hardening.md  # "draft"

# mutual blocking cycle 解消の grep verify (acceptance_blocked_by から消失、説明 comment のみ残存)
rg -n "mutual blocking cycle|mutual deadlock" docs/adr/  # ADR-00021/00007 の F-PR67-047 説明 comment のみ hit (acceptance_blocked_by field に reciprocal blocker は無いこと)
rg -n "ADR-00021 同期 accepted\|ADR-00007 同期 accepted" docs/adr/00021_host_portable_deployment.md docs/adr/00007_external_exposure.md  # acceptance_blocked_by field 内には無いこと (説明 prose のみ許容)
```

### 6.2 Codex auto-review baseline 確認義務 (F-ADV-R1-004 adopt、polling contract 機械化)

PR 起票後、`.claude/scripts/codex_pr_full_review.sh <PR>` の full output + latest `headRefOid` + 10 分以上 polling を **機械的 gate** として実行 (`feedback_codex_pr_review_baseline_check.md` + `.claude/scripts/codex_pr_full_review.README.md` L113-119 / L168-176 + `.claude/rules/branch-and-pr-workflow.md` L28-30 教訓必須遵守、PR #42/#44/#47 で再発した「delta +0 を真の 0 件と誤判定」を回避)。

#### 6.2.1 polling contract (PR 作成後 + 各 fix push 後に必須実行、F-ADV-R2-003 adopt: LATEST_SHA bind を README polling loop 準拠で実装)

```bash
# (a) PR 作成 / fix push 後の latest commit SHA 取得 (`codex_pr_full_review.README.md` L117-119 / L140-158 polling loop 準拠)
PR_NUMBER=<本 PR 番号>
REPO_OWNER=<owner>; REPO_REPO=<repo>  # 通常 t-ohga/TaskManagedAI
LATEST_SHA=$(gh pr view "$PR_NUMBER" --json headRefOid -q .headRefOid)
echo "latest headRefOid: $LATEST_SHA"

# (b) PRE_REVIEW_FOR_HEAD: latest SHA に bind した Codex review/comment 件数を取得 (commit_id // commit.oid filter、README §polling loop 準拠)
PRE_INLINE=$(gh api "repos/$REPO_OWNER/$REPO_REPO/pulls/$PR_NUMBER/comments" --paginate \
  | jq "[.[] | select(.commit_id == \"$LATEST_SHA\") | select(.user.login | test(\"codex\"; \"i\"))] | length")
PRE_TOP=$(gh api "repos/$REPO_OWNER/$REPO_REPO/pulls/$PR_NUMBER/reviews" --paginate \
  | jq "[.[] | select(.commit_id == \"$LATEST_SHA\") | select(.user.login | test(\"codex\"; \"i\"))] | length")
echo "PRE inline for HEAD: $PRE_INLINE, PRE top-level for HEAD: $PRE_TOP"

# (c) 10 分以上 polling (新 fix push 後の Codex auto-review は 5-15 min 着信、README L168-176 polling duration 準拠)
# 5 min 間隔で 2-3 回 (a)+(b) を再実行し、CUR_REVIEW_FOR_HEAD を比較

# (d) baseline 内容 full review (3 endpoint × paginated × Codex bot filter、`| head -200` は補助表示限定、判定には使わない)
.claude/scripts/codex_pr_full_review.sh "$PR_NUMBER" > /tmp/codex_review_baseline.txt
echo "baseline size: $(wc -l < /tmp/codex_review_baseline.txt) lines"
.claude/scripts/codex_pr_full_review.sh "$PR_NUMBER" | head -200  # 補助表示限定

# (e) fail-closed 判定 (silent clean / delta +0 誤判定 防止、`feedback_codex_pr_review_baseline_check.md` 教訓)
if [ ! -s /tmp/codex_review_baseline.txt ]; then
  echo "FAIL: codex_pr_full_review.sh returned empty (script failure)" >&2
  echo "Action: wait 10 min, re-run; never silent clean" >&2
  exit 1  # fail-closed
fi
if [ "$PRE_INLINE" -eq 0 ] && [ "$PRE_TOP" -eq 0 ]; then
  echo "WARN: no Codex review for latest HEAD ($LATEST_SHA) yet" >&2
  echo "Action: wait 10 min, re-fetch; if still 0 → reaction-only clean possibility but user 明示確認 必須 (silent merge 禁止)" >&2
  # reaction-only clean record を PR description / review log に user 明示確認込みで記録するまで merge 不可
fi

# (f) 採否判定 3 分類記録 (adopt / reject / defer)
# 各 finding を本 PR description または review log に記録、reject 理由は明示
```

#### 6.2.2 PR description に記載必須

- 本 PR の latest `headRefOid` (各 fix push 後 update)
- Codex auto-review **PRE/CUR_REVIEW_FOR_HEAD counts** (LATEST_SHA に bind した inline + top-level の件数、stale commit にだけ review がある場合は HEAD に bind 0 件と区別)
- baseline 内容 full output 確認済の record (script size + 主要 finding の adopt/reject/defer 記録)
- 採否判定 3 分類 (adopt / reject / defer) の件数 + reject 理由
- reaction-only clean signal の場合の user 明示確認 record (silent merge 禁止)

#### 6.2.3 fail-closed 条件 (silent clean 判定禁止、F-ADV-R2-003 adopt LATEST_SHA bind 必須)

- script exit status != 0 → fail-closed、user 確認まで merge 不可
- baseline empty (`wc -l == 0`) → fail-closed、wait 10 min + re-run
- `PRE_INLINE + PRE_TOP == 0` (latest HEAD への Codex review 0 件) → reaction-only clean は user 明示確認 + record 必須、silent merge 禁止
- stale commit に Codex review がある状態 (`headRefOid != commit_id` の review が複数) で latest HEAD には 0 件 → `feedback_codex_pr_review_baseline_check.md` 教訓 (PR #42/#44/#47 で再発) 該当、user 明示確認まで merge 不可
- delta +0 を「真の 0 件」と即断定禁止: 必ず full output の content を head -200 で確認

### 6.3 No code change + PR workflow invariant verification (F-ADV-R2-002 adopt)

```bash
# (a) no code change verify
git diff --stat origin/main..HEAD --  ':!docs/' ':!.claude/plans/'
# expected: 出力なし (本 PR は docs-only)

git diff --stat origin/main..HEAD -- docs/ .claude/plans/
# expected: 2 files (master plan + .claude/plans/master-plan-section-10-11-update.md)

# (b) PR workflow invariant verify (F-ADV-R2-002 adopt: branch → main 直接 ff merge / push 経路の plan 内残存禁止)
! rg -nP 'worktree branch\s*→\s*main を user 直接 ff merge' .claude/plans/master-plan-section-10-11-update.md
! rg -nP 'main への直接 ff merge|main へ直接 ff merge|main 直接 push' .claude/plans/master-plan-section-10-11-update.md
# expected: 0 hit (plan 内に invariant 違反 path 記述なし、`branch-and-pr-workflow.md` L9-13 遵守)

# (c) plan / master plan の active text に F-ADV-R2-001/002 fix が反映されているか positive 補助確認
rg -nP 'Critical path \(Post-fix path' docs/設計検討/2026-05-13_p0_exit_master_plan.md  # §4 update 後 hit 必須
rg -nP 'SP-022 \(pre-P0\.1 unblock sprint\)' docs/設計検討/2026-05-13_p0_exit_master_plan.md  # §4 図 + §10 で複数 hit
```

## 7. Out-of-Scope items (explicit list、本 PR で **やらない**、F-PLAN-R1-004 + F-PLAN-R1-007 adopt 反映)

- §0 Executive Summary の P0 Exit declaration reflect (F-PLAN-R1-007 adopt)
- §1 のうち §1.1/§1.3 以外 (§1.2 P0 Hard Gates/KPIs trace actuals reflect / §1.4 不足 Sprint Pack 等、F-PLAN-R1-007 adopt)
- §3 (Sprint 10/11/11.5/12 詳細 section) の本文 rewrite
- §6 (Codex Multi-Round Budget 集計) の actuals 反映
- §7 (Verification Gate) の SP-022 verification command 追加
- §8 (Risk + Rollback) の SP-022 specific risk 反映
- §9 (Schedule) の session 数 actuals 反映
- **ADR-00021 / ADR-00007 frontmatter `acceptance_history` future entry の文言 update** (F-PLAN-R1-004 adopt、SP022-T00 PR で frontmatter 更新と同時実施、本 PR は master plan のみ scope)
- **ADR-00020 frontmatter `acceptance_blocked_by` の循環依存解消** (F-PLAN-R2-001 adopt、現状 `["ADR-00014/16 accepted", "P0 完了"]` で ADR-00014/00016 proposed + ADR-00016 が ADR-00020 accepted を blocker に含む循環、SP022-T00 PR で「multi-agent ADR-00014/00016 から独立 accept」に再解釈する update を同時実施)
- **SP-022 Sprint Pack の Phase E 16 finding closure 全 active lines の audit-only gate / contract test PASS への split** (F-PLAN-R3-001 + F-PLAN-R5-001 adopt、現状 `docs/sprints/SP-022_framework_intake_hardening.md` の以下 active lines が Phase E closure invariant を強制): (a) L74 task list 「Phase E 16 finding が全件 closed (adopt 済 + test fixture 化済)」、(b) L94 must_ship 表 「Phase E 16 finding closure | ○ | LOW 残存は P3+ で対応可」、(c) L104 受け入れ条件 「Phase E 16 finding (PE-F-001〜PE-F-016) すべての closure evidence (各 finding に対応する test fixture / contract test PASS)」、(d) L124-126 検証手順 `pytest eval/multi_agent/...` (Phase E fixture が SP-013〜020 完了前は run 不可)。L53 で「PE-F は SP-013〜016/SP-018/SP-020 must_ship 反映済」と明示済のため future-sprint 依存循環。SP-022 must_ship 表 + task list + 受け入れ条件 + 検証手順を **(a) "PE-F が owning ADR/Sprint Pack に割り当て済 + 受け入れ条件 trace" の audit-only gate (= SP-022 内で完結)** + **(b) "実 contract test PASS" の post-P0.1 owning sprint exit gate carry-over (= SP-013〜016/SP-018/SP-020 内で検証)** に split する Sprint Pack side update を SP022-T00 着手 PR で実施
- **SP-001-5 host portable amendment 全 active lines (L38 / L52 / L72 / L92 / L97 / L130 / L148) の旧「SP-022 で実機 host migration drill PASS 後」「SP-022 carry over」文言 update** (F-PLAN-R4-001 + F-PLAN-R5-002 adopt、frontmatter L18-19 では SP022-T00 acceptance + SP022-T09 post-acceptance verification 反映済だが active text 7 箇所で旧文言残存、SP022-T00 PR で frontmatter 同期 update + SP022-T00 PR verification に SP-001-5 negative grep 追加)
- **SP-022 Phase G PGA-F-009 inter_agent_messages consumed invariant fixture の audit-only gate / post-P0.1 SP-015 完了後 contract test PASS への split** (F-ADV-R1-001 adopt、`docs/sprints/SP-022_framework_intake_hardening.md:172` で「SP-015 で実装されたものを SP-022 で再 verify」 + L187 で「Phase G adversarial 14 finding 全件 closure evidence / contract test PASS」要求 = SP-015 依存 future-sprint 循環 = Phase E と同種、SP022-T00 PR で SP-022 Pack の Phase G PGA-F-009 entry を audit-only trace gate + post-P0.1 SP-015 owning sprint exit gate carry-over に split)
- **SP-022 L162 「ADR-00014/15/16/17/18/19 (P0.1+ で accepted 済 ...)」stale active text の修正** (F-ADV-R1-006 adopt、ADR-00014/00016 は実際 `status: proposed`、SP022-T00 reviewer が本 stale 行を根拠に ADR-00020 frontmatter blocker 解消済と誤読する acceptance lifecycle trap、SP022-T00 PR で「P0.1+ owning sprint で proposed→accepted 予定」へ update + verification に `rg -n 'accepted 済' docs/sprints/SP-022_framework_intake_hardening.md` 追加)
- **SP022-T07 production checklist scope 境界 明文化** (F-ADV-R1-007 adopt、SP-022 L64 で T07「production 公開準備 checklist draft」+ L97 must_ship=○ だが境界が明文化されておらず Docker image build / DNS / 外部公開 / license/docs 整備 (P3+ 実作業) を mix する scope leak 経路、SP022-T00 precondition checklist に「T07 = docs-only checklist skeleton まで、P3+ 実作業は禁止、必要なら P3+ Sprint Pack に分離」を明文化、P0.1 unblock 判定では T07 = checklist draft 存在確認のみ)
- ADR-00021 / ADR-00007 / ADR-00020 body section update (SP022-T00 着手 PR で本体 update)
- SP-022 Sprint Pack の本体 rewrite (本 PR は draft 維持、SP-022 着手時に別 PR で sprint scope re-allocation)
- `docs/release/p0_exit_2026_MM_DD.md` 起票 (SP-022 完了後)
- TASKHUB_P0_1_OPENED=1 環境変数の `.env.example` / docker-compose / CI guard 解禁 (P0 Exit declaration PR で実施)
- multi-agent fixture (AC-HARD-01〜07 multi-agent 文脈) verification (SP-013 skeleton 依存、SP-022.1 / SP-023 carry-over)
- code change (本 PR は docs-only)
