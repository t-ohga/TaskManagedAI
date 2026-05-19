---
id: PLAN-SP022-T00-PRE-IMPLEMENTATION-GATE
title: "SP022-T00 pre-implementation gate atomic 7 step (3 ADR proposed→accepted promotion + SP-022/SP-001-5 active text sync、12 段 fail-closed verification)"
status: draft
date: 2026-05-19
authors:
  - "claude (post master plan §10-§11 update merge、SP-022 着手 trigger)"
review_history:
  - "R1 (codex-plan-review / Phase A 構造レビュー): 15 findings (HIGH 3 / MEDIUM 7 / LOW 5、CRITICAL=0)、全件 adopt — F-001 file 数不一致 + F-002 ADR body 境界曖昧 + F-003 HARD GATE evidence 機械検査不在 + F-004 yq toolchain + F-005 accepted 後 acceptance_blocked_by 残存 + F-006 SP022_T00_DATE 日跨ぎ + F-007 adr_refs exact set 不厳 + F-008 SP-001-5 grep pattern 曖昧 + F-009 L92 ✗ 表記 + F-010 rollback merge strategy + F-011 allowlist + F-012 polling spec + F-013 regex プレースホルダ + F-014 line number drift + F-015 design accepted vs post-acceptance gate scope"
  - "R2 (codex-plan-review / Phase B 実装可能性、HIGH+ 限定): 5 findings (HIGH 5、CRITICAL=0、critical_zero criteria HIGH=5 で未達)、全件 adopt — F-R2-001 HIGH ADR-00020 verification 削除後 key 参照で必ず fail (has() check に変更 + acceptance_history で marker 検証) + F-R2-002 HIGH invariant ADR-00021/00007 も acceptance_blocked_by 削除必須 (metadata 二重真実化回避) + F-R2-003 HIGH SP-018/SP-020 Sprint Pack 不在 + Phase E trace 矛盾 (SP-022 内 trace matrix で local closure) + F-R2-004 HIGH PGA-F-009 SP-015 未 trace + allowlist 外で false-positive (SP-022 内 local closure + SP-015 trace は future) + F-R2-005 HIGH master plan §10.C-1 要求の SP022-T07 production boundary 未移植"
  - "R3 (codex-plan-review / CRITICAL のみ最終 verify): 1 finding (CRITICAL 1)、全件 adopt — F-R3-001 CRITICAL impossibility SP022-T00 verification self-fail: check (5) の SP-022 全体 negative grep が Review 追記の historical quote を hit + check (9) の `\\|` escape で alternation 不機能、check (5) を `## 関連 ADR` section 限定 awk extract に + check (9) を rg -qP + 真 alternation + Review 追記 quote を「旧文言例示」表現に変更"
related_documents:
  - "../../docs/設計検討/2026-05-13_p0_exit_master_plan.md"
  - "../../docs/sprints/SP-022_framework_intake_hardening.md"
  - "../../docs/sprints/SP-001-5_host_portable_amendment.md"
  - "../../docs/sprints/SP-012_p0_acceptance.md"
  - "../../docs/adr/00007_external_exposure.md"
  - "../../docs/adr/00020_framework_intake_checklist.md"
  - "../../docs/adr/00021_host_portable_deployment.md"
  - "../../docs/adr/00014_multi_agent_orchestration.md"
  - "../../docs/adr/00016_hermes_agent_integration_strategy.md"
  - "../../.claude/rules/sprint-pack-adr-gate.md"
  - "../../.claude/rules/codex-usage-policy.md"
  - "../../.claude/plans/master-plan-section-10-11-update.md"
---

# SP022-T00 pre-implementation gate atomic 7 step + 12 段 fail-closed verification

## 0. Executive Summary

master plan §10-§11 update PR (#68) merged 後の **SP-022 (pre-P0.1 unblock sprint) 着手 trigger**。SP-022 全 must_ship task (T01-T09) 実装着手前の pre-implementation gate として、`.claude/rules/sprint-pack-adr-gate.md §12.4` invariant 「ADR proposed→accepted 昇格 = codex-plan-review R1 minimum + 採否判定 経由必須」+ `.claude/rules/codex-usage-policy.md §14.1` mandatory Codex pre-commit gates 遵守の上、ADR-00020 + ADR-00021 + ADR-00007 の 3 ADR を **simultaneous accepted promotion** + SP-022 frontmatter (planned_adr_refs → adr_refs 移動 + Review accepted_at 記録) + SP-022/SP-001-5 active text 同期修正を **1 PR / 1 commit sequence (failure 時全件 rollback)** で atomic に実行する。

**本 PR で実施する 7 step + 12 段 fail-closed verification は `.claude/plans/master-plan-section-10-11-update.md §3.3 §10.C-1` で正本化済 (累計 34 finding adopt 反映済)。本計画書は master plan plan の hard gate precondition step 0 (codex-plan-review R1 minimum + 採否判定) を本 PR 自体に対し実行するための plan。**

### SP022_T00_DATE 正本定義 (F-006 adopt)

`SP022_T00_DATE` は **本 PR の first commit date (UTC)** を正本とする。PR 作成 / Codex review / user merge が日跨ぎした場合も、3 ADR の `updated_at` / `accepted_at` 記録は first commit date に統一する (`git show -s --format=%cd --date=format-local:%Y-%m-%d <first commit sha>`)。本 plan では `SP022_T00_DATE="2026-05-19"` を想定 (実 commit 直前に date 再確認、shell variable で expansion)。

### 許可ファイル allowlist (F-011 + F-001 adopt、本 PR の Changed files 正本)

本 PR で変更可能なファイルは以下 6 個に限定:

1. `docs/adr/00020_framework_intake_checklist.md` — frontmatter (status + updated_at + acceptance_blocked_by 削除 + acceptance_target_sprint + acceptance_history) + 本文「最終更新」行
2. `docs/adr/00021_host_portable_deployment.md` — frontmatter (status + updated_at + acceptance_history future entry 文言 update) + 本文「最終更新」行
3. `docs/adr/00007_external_exposure.md` — frontmatter (status + updated_at + acceptance_history future entry 文言 update) + 本文「最終更新」行
4. `docs/sprints/SP-022_framework_intake_hardening.md` — frontmatter (planned_adr_refs → adr_refs 移動 + key 削除 + updated_at) + 本文 L162 stale 修正 + Phase E section (L74/94/104/124-126 audit-only split) + Phase G PGA-F-009 section (L172/187 audit-only split) + `## Review` 追記
5. `docs/sprints/SP-001-5_host_portable_amendment.md` — active text 7 箇所 (L38/52/72/92/97/130/148) の旧 acceptance path 文言 update
6. `.claude/plans/sp022-t00-pre-implementation-gate.md` — 本計画書 (本 PR で新規作成)

**それ以外のファイル (master plan / 他 ADR / 他 Sprint Pack / code / config / migrations / tests / frontend / backend / .claude/rules / .claude/agents / .claude/hooks / .claude/skills / その他) は本 PR で変更禁止**。許可パス外への変更は scope creep として §2.3 で reject。

## 1. Background

### 1.1 SP022-T00 が pre-implementation gate である理由

- ADR-00020/00021/00007 はそれぞれ ADR Gate Criteria 11 種に該当 (#1 認証・認可 / #7 外部公開設定 / #11 GitHub App permission に直結する frontmatter promotion)
- `.claude/rules/sprint-pack-adr-gate.md §12.4` 「ADR Gate Criteria 直結の status promotion は codex-plan-review R1 minimum + 採否判定 経由必須」
- SP-022 全 must_ship task (T01-T09) は ADR-00020/00021/00007 accepted を前提とする (`.claude/rules/sprint-pack-adr-gate.md §12` invariant 「実装着手直前に planned ADR を accepted 化」)
- SP022-T00 を skip すると `acceptance_blocked_by` が解除されないため SP022-T01+ で blocker

### 1.2 mandatory Codex gate flow

```
本 plan draft (SP022-T00 atomic 7 step + 12 段 verification の計画書)
  ↓ Step 0 HARD GATE: codex-plan-review R1 minimum + 採否判定 (本 plan 自体に対し)
  ↓ adopt/reject/defer 記録 + clean signal
本 PR 起票 (SP022-T00 atomic 7 step を実 docs に適用)
  ↓ pre-commit verification (12 段 fail-closed)
  ↓ codex_pr_full_review.sh polling (LATEST_SHA bind、F-ADV-R2-003 polling contract)
  ↓ Codex auto-review baseline 採否判定 + multi-round polish
user merge
  ↓ SP-022 T01-T09 着手可能 (P0.1 unblock path 開通)
```

### 1.3 master plan §10.C-1 で正本化された SP022-T00 atomic 7 step

`.claude/plans/master-plan-section-10-11-update.md §3.3 §10.C-1` (master plan §10.C で正本化済) より引用、本 PR の execution checklist:

- **step 0 HARD GATE precondition** (F-ADV-R3-002 adopt): 本 plan に対し codex-plan-review R1 minimum + adopt/reject/defer 採否判定。PR description / Review 欄に review round 番号、finding 件数 (CRITICAL / HIGH / MEDIUM / LOW)、各 finding adopt/reject/defer 判定 + 理由、未解消 0 件 evidence を記録するまで PR merge 不可
- **step 1**: 3 ADR (00020/00021/00007) frontmatter `status: proposed → accepted` + `updated_at: <SP022-T00 implementation start date>` 同期更新 + 本文「最終更新」行も同日付に同期
- **step 2**: ADR-00020 frontmatter `acceptance_blocked_by` 再解釈 (旧 ["ADR-00014/16 accepted", "P0 完了"] 循環依存解消、新 「SP022-T00 simultaneous accepted (framework intake checklist は P0 全体方針として独立 acceptable、multi-agent ADR-00014/00016 への依存性なし)」)
- **step 3**: ADR-00021 / ADR-00007 frontmatter `acceptance_history` future entry 文言 update (SP022-T00 design accepted + SP022-T09 post-acceptance verification 表現に)
- **step 4**: SP-022 frontmatter `planned_adr_refs` → `adr_refs` 移動 (3 ADR)、**`planned_adr_refs` key 自体を完全削除**
- **step 5**: SP-022 `## Review` (実装後追記、3 ADR の `accepted_at: <SP022_T00_DATE>` 記録)
- **step 6**: SP-022 + SP-001-5 active text 同期 修正 (詳細 §3 で展開)

### 1.4 master plan §10.C-1 で正本化された 12 段 fail-closed verification

`.claude/plans/master-plan-section-10-11-update.md §3.3 §10.C-1` (master plan §10.C verification block) より引用、本 PR の pre-commit verify:

(1) 3 ADR status が exact "accepted" / (2) 3 ADR updated_at が SP022_T00_DATE と exact equality / (3) SP-022 adr_refs exact set {ADR-00020/00021/00007} / (4) SP-022 planned_adr_refs key absent / (5) SP-022 L162 stale "accepted 済" 不在 / (6) SP-001-5 active text 旧 acceptance path 不在 / (7) SP-022 Phase E active task list 不在 / (8) SP-022 Phase G PGA-F-009 SP-015 依存 active 不在 / (9) audit-only gate / post-P0.1 carry-over positive marker 存在 / (10) HARD GATE evidence (codex-plan-review R1 完了 record) / (11) ADR-00020 acceptance_blocked_by 旧 cyclic blocker 不在 + SP022-T00 independent accept marker 存在 / (12) SP-022 Review で 3 ADR `accepted_at: SP022_T00_DATE` 記録

## 2. Scope & Out-of-Scope

### 2.1 In-Scope (本 PR で update、計 6 files、F-001 + F-002 + F-011 adopt 反映)

§0「許可ファイル allowlist」を正本参照。具体的編集 area:

- `docs/adr/00020_framework_intake_checklist.md`: frontmatter (status + updated_at + acceptance_blocked_by **削除** + acceptance_target_sprint + acceptance_history、F-005 adopt: accepted 後は active blocker key を削除し acceptance_history に rationale 移送) + 本文「最終更新」行のみ metadata 同期 (§normative section 本体は不変)
- `docs/adr/00021_host_portable_deployment.md`: frontmatter (status + updated_at + acceptance_history future entry 文言 update = 実 accepted entry に置換) + 本文「最終更新」行のみ metadata 同期 (§11/§12/§14 後勝ち normative source 不変)
- `docs/adr/00007_external_exposure.md`: frontmatter (status + updated_at + acceptance_history future entry 文言 update) + 本文「最終更新」行のみ metadata 同期 (§normative section 本体不変)
- `docs/sprints/SP-022_framework_intake_hardening.md`:
  - frontmatter: `planned_adr_refs` → `adr_refs` 移動 + `planned_adr_refs` key 完全削除 + `updated_at` 更新
  - 本文 L162 stale text 修正 (「ADR-00014〜00019 accepted 済」→ proposed→accepted 予定、line number 参考扱い、見出し / 旧文言 / 新文言を正本識別、F-014 adopt)
  - Phase E section (旧 L74/94/104/124-126 周辺) audit-only split (line 参考、見出し「## タスク一覧」「## must_ship 対応表」「## 受け入れ条件」「## 検証手順」内の旧文言を正本識別)
  - Phase G PGA-F-009 section (旧 L172/187 周辺) audit-only split (line 参考、見出し「## Phase G adversarial strengthening」内の旧文言を正本識別)
  - `## Review` 追記 (3 ADR accepted_at 記録 + HARD GATE evidence、F-003 adopt: rg/yq で機械検査可能な fixed format)
- `docs/sprints/SP-001-5_host_portable_amendment.md`: 本文 active text 7 箇所 (旧 L38/52/72/92/97/130/148 周辺、line 参考、見出し「## 目的」「## 設計判断」「## 実装チケット」「## must_ship 対応表」「## 受け入れ条件」「## レビュー観点」「## 関連 ADR」内の旧文言を正本識別) の旧「SP-022 で実機 host migration drill PASS 後」「SP-022 carry over」文言 update
- `.claude/plans/sp022-t00-pre-implementation-gate.md`: 本計画書 (本 PR で新規作成)

### 2.2 Out-of-Scope (本 PR では触らない、後段別 PR、F-002 + F-001 adopt 反映)

- **ADR-00021 / ADR-00007 / ADR-00020 §normative section 本体 rewrite** (§normative section の SP-012/SP-022 timing 記述 update): 本 PR は (a) frontmatter (status / updated_at / acceptance_history / acceptance_blocked_by / acceptance_target_sprint / post_acceptance_verification) + (b) 本文「最終更新」行のみ metadata 同期、§normative section の本文 update は別 ADR review PR で実施 (本 PR の正本 source は ADR-00021 frontmatter L48-49 `§11/§12/§14` 後勝ち invariant、F-002 adopt: 「本文最終更新行は metadata 同期として in-scope、§normative section 本体は out-of-scope」を明確に分離)
- **SP-022 must_ship 表全体の rewrite** (T01-T09 詳細 + Phase G strengthening 全件): 本 PR は L74/94/104/124-126 (Phase E) + L172/187 (Phase G PGA-F-009) + L162 stale + `## Review` 追記 + frontmatter のみ、他 must_ship row + T01-T09 task list 本文は不変
- **master plan 全体** (§0/§1.1/§1.2/§3-§9): PR #68 で §1.1/§1.3/§4/§5/§10/§11 を update 済、本 PR では master plan を一切 touch しない (F-001 adopt: 本 PR rollback 対象から master plan を削除)。残 historical record actuals reflect は P0 Exit declaration PR で 1 回 (master plan §10-§11 update PR の Q6 default)
- **SP-022 着手 (T01-T07 + T08 + T09)**: 本 PR merge 後の SP-022 内 PR で別途実装

### 2.3 Scope creep 防止 trigger

以下が PR 内で発生したら **本 PR scope を逸脱**しているとみなし、別 PR に切り出す:

- ADR body section の本文 rewrite (frontmatter + history 以外)
- SP-022 must_ship 表全体 rewrite (Phase E/G audit-only split + L162 + planned→adr_refs 移動以外)
- master plan §3 / §6 / §7 / §8 / §9 編集
- SP-022 T01-T09 task list の actual 実装
- 新 ADR 起票 / 新 Sprint Pack 起票
- code change (本 PR は docs-only)

## 3. Changes to Apply

### 3.1 ADR-00020 frontmatter promotion (step 1 + step 2)

**現状 (drift)**:

```yaml
status: "proposed"
acceptance_blocked_by:
  - "ADR-00014/16 accepted"
  - "P0 完了"
```

**update 後 (step 1 status + updated_at 同時更新、step 2 blocker 完全削除 + rationale を acceptance_history に移送、F-005 adopt)**:

```yaml
status: "accepted"
updated_at: "2026-05-19"  # SP022_T00_DATE (本 PR first commit date)
# F-PLAN-R2-001 + F-ADV-R5-001 + F-005 (本 plan R1 adopt) (master plan §10-§11 update PR #68):
# 旧 cyclic blocker ["ADR-00014/16 accepted", "P0 完了"] を SP022-T00 で再解釈し削除。
# Framework Intake Checklist は P0 全体方針として独立 acceptable (CI 機械検査 + 8 verify
# item は multi-agent implementation に依存しない)、ADR-00014 (multi-agent orchestration) /
# ADR-00016 (hermes integration) の P0.1+ accepted を待たずに SP022-T00 pre-implementation
# gate で simultaneous accept. F-005 adopt: accepted 後は acceptance_blocked_by を
# 完全削除し、blocker 再解釈の rationale は acceptance_history と本 comment 内に残す
# (status: accepted と acceptance_blocked_by の同居による意味曖昧を回避).
# acceptance_blocked_by: 削除 (旧 ["ADR-00014/16 accepted", "P0 完了"] は SP022-T00 で
#                       blocker 解消、accepted 後 lifecycle metadata から削除)
acceptance_target_sprint: "SP022-T00 pre-implementation gate (本 PR で acceptance 完了、master plan §10-§11 update PR #68 で acceptance lifecycle 正本化済、§1.3 / §5 整合)"
acceptance_history:
  - "2026-05-10: proposed (Phase B-2 R-007 Polyform Shield + R-008 full embed scope creep + Phase E PE-F-010 起票)"
  - "2026-05-19: accepted at SP022-T00 pre-implementation gate. 旧 acceptance_blocked_by ['ADR-00014/16 accepted', 'P0 完了'] は SP022-T00 で blocker 再解釈し削除 (Framework Intake Checklist は P0 全体方針として独立 acceptable、multi-agent ADR-00014/00016 の P0.1+ accepted から独立、F-005 adopt: status accepted と active blocker key の同居を回避). ADR-00021/00007 と simultaneous acceptance、common SP022-T00 gate trigger で promotion 完了."
```

**本文「最終更新」行 update**:

```markdown
最終更新: 2026-05-19 (SP022-T00 pre-implementation gate で accepted promotion、blocker 再解釈完了、ADR-00021/00007 と simultaneous acceptance)
```

### 3.2 ADR-00021 frontmatter promotion (step 1 + step 3)

**現状 (acceptance_history future entry が SP022-T00 reinterpretation と read mismatch)**:

```yaml
status: "proposed"
acceptance_history:
  - "2026-05-10: proposed (...)"
  - "2026-05-18T00:30:00Z: tentative accepted (...)"
  - "2026-05-18T09:40:06Z: tentative acceptance 撤回 (...)"
  - "future: 実機 host migration drill PASS 後 SP-022 scope で再 accepted 化"
```

**update 後 (step 1 status + updated_at 同時更新、step 3 future entry 文言 update、F-R2-002 adopt: acceptance_blocked_by 削除、SP022-T00 gate 完了事実は acceptance_history に移送)**:

```yaml
status: "accepted"
updated_at: "2026-05-19"  # SP022_T00_DATE
# F-R2-002 adopt: 旧 acceptance_blocked_by ["SP022-T00 pre-implementation gate trigger
# (ADR-00007 と同時 accepted、F-PR67-047 P2 adopt: 旧 mutual blocking cycle 解消)"] は
# SP022-T00 で gate 完了したため accepted 後の lifecycle metadata から削除。完了事実は
# acceptance_history に移送。post_acceptance_verification (SP022-T09 実機 drill 等) は
# active verification として残す.
# acceptance_blocked_by: 削除 (旧 SP022-T00 gate trigger は本 PR で完了、accepted 後の
#                       active blocker key 同居を回避、F-005 R1 + F-R2-002 adopt 一貫)
acceptance_target_sprint: "SP022-T00 pre-implementation gate (本 PR で acceptance 完了)"
# post_acceptance_verification は不変 (SP022-T09 実機 drill verification、active verification として残す)
acceptance_history:
  - "2026-05-10: proposed (Phase G plan-review + adversarial-review clean + Phase H second-opinion で 94 finding closure verify 完了)"
  - "2026-05-18T00:30:00Z: tentative accepted (PR #67 F-PR67-002 P1 adopt として SP-012 で accepted 化試行、SP-012 batch 7 taskhub admin CLI + batch 10 audit_events 実装着手直前 timestamp)"
  - "2026-05-18T09:40:06Z: tentative acceptance 撤回 (Codex PR #67 R4 F-PR67-010/013 P2 valid 確認: master plan + PRD-01 で『Sprint 12 で host migration drill PASS 後』明示、acceptance 条件 unmet のため proposed に restore、`.claude/rules/sprint-pack-adr-gate.md §12` invariant 遵守)"
  - "2026-05-19: accepted at SP022-T00 pre-implementation gate (本 PR で design accepted、ADR-00007 と simultaneous acceptance、SP022-T09 で実機 host migration drill (Mac→VPS) RTO≤4h PASS による post-acceptance verification 必須、master plan §10-§11 update PR #68 で acceptance lifecycle 正本化済、F-PR67-047 common SP022-T00 simultaneous gate で旧 mutual blocking cycle 解消完了、acceptance_blocked_by key は accepted 後削除 = F-R2-002 adopt)"
```

**本文「最終更新」行 update**:

```markdown
最終更新: 2026-05-19 (SP022-T00 pre-implementation gate で design accepted、ADR-00007 と simultaneous、SP022-T09 で実機 host migration drill による post-acceptance verification 待ち。`§11/§12/§14` が後勝ち normative source の invariant 維持)
```

### 3.3 ADR-00007 frontmatter promotion (step 1 + step 3)

**update 後 (step 1 status + updated_at、step 3 history future entry update、F-R2-002 adopt: acceptance_blocked_by 削除、SP022-T00 gate 完了事実は acceptance_history に移送)**:

```yaml
status: "accepted"
updated_at: "2026-05-19"  # SP022_T00_DATE
# F-R2-002 adopt: 旧 acceptance_blocked_by ["SP022-T00 pre-implementation gate trigger
# (ADR-00021 と同時 accepted、F-PR67-047 P2 adopt: 旧 mutual blocking cycle 解消)"] は
# SP022-T00 で gate 完了したため accepted 後の lifecycle metadata から削除。完了事実は
# acceptance_history に移送。post_acceptance_verification (SP022-T09 Tailscale 閉域維持
# invariant verify) は active verification として残す.
# acceptance_blocked_by: 削除 (旧 SP022-T00 gate trigger は本 PR で完了、accepted 後の
#                       active blocker key 同居を回避、F-005 R1 + F-R2-002 adopt 一貫)
acceptance_target_sprint: "SP022-T00 (pre-implementation gate、ADR-00021 と同時、本 PR で acceptance 完了)"
# post_acceptance_verification は不変 (SP022-T09 Tailscale 閉域維持 invariant verify、active verification として残す)
acceptance_history:
  - "2026-05-07: proposed (SP-000_bootstrap で起票)"
  - "2026-05-18T00:30:00Z: tentative accepted (PR #67 F-PR67-002 P1 adopt として SP-012 で accepted 化試行、ADR-00021 と同時)"
  - "2026-05-18T09:40:06Z: tentative acceptance 撤回 (ADR-00021 が host migration drill PASS 未達のため proposed restore、ADR-00007 も同期 proposed 維持)"
  - "2026-05-19: accepted at SP022-T00 pre-implementation gate (本 PR で ADR-00021 と simultaneous acceptance、SP022-T09 で実機 host migration drill (Mac→VPS) における Tailscale 閉域維持 invariant verify による post-acceptance verification 必須、F-PR67-047 mutual blocking cycle 解消完了、acceptance_blocked_by key は accepted 後削除 = F-R2-002 adopt)"
```

**本文「最終更新」行 update**:

```markdown
最終更新: 2026-05-19 (SP022-T00 pre-implementation gate で ADR-00021 と simultaneous accepted、SP022-T09 で実機 drill 時 Tailscale 閉域維持 invariant verify 待ち)
```

### 3.4 SP-022 frontmatter (step 4)

**現状**:

```yaml
adr_refs: []
planned_adr_refs:
  - "[ADR-00020](...) # SP-022 で accepted at SP022-T00 (...)"
  - "[ADR-00021](...) # SP-022 で accepted at SP022-T00 (...)"
  - "[ADR-00007](...) # ADR-00021 同期 acceptance at SP022-T00 (...)"
```

**update 後 (step 4 planned_adr_refs → adr_refs 移動 + key 完全削除、updated_at 更新)**:

```yaml
updated_at: "2026-05-19"  # SP022_T00_DATE
adr_refs:
  - "[ADR-00020](../adr/00020_framework_intake_checklist.md) # SP022-T00 で accepted (本 PR、2026-05-19、framework intake checklist は P0 全体方針として独立 acceptable、ADR-00014/00016 から独立 accept)"
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # SP022-T00 で design accepted (本 PR、2026-05-19、実機 host migration drill (Mac→VPS) RTO≤4h PASS は SP022-T09 post-acceptance verification 待ち)"
  - "[ADR-00007](../adr/00007_external_exposure.md) # SP022-T00 で ADR-00021 と simultaneous accepted (本 PR、2026-05-19、SP022-T09 で実機 drill 時 Tailscale 閉域維持 invariant verify 待ち)"
# planned_adr_refs: key 完全削除 (F-ADV-R5-001 + F-ADV-R3-001 adopt: SP022-T00 で promotion 完了済、`.claude/rules/sprint-pack-adr-gate.md §12.1` 12.2 promotion 完了 trigger)
```

### 3.5 SP-022 `## Review` 追記 (step 5、F-003 + F-014 adopt: HARD GATE evidence machine-checkable + line number 参考)

**現状**:

```markdown
## Review

(SP-022 完了時に追記)
```

**update 後 (F-003 adopt: HARD GATE evidence を machine-checkable fixed format で記録、rg で機械検査可能。F-014 adopt: line number は参考、見出し / 旧文言 / 新文言を正本識別)**:

```markdown
## Review

### SP022-T00 pre-implementation gate completion (2026-05-19)

#### ADR accepted promotion completed (F-003 adopt: fixed format `<ADR-ID> accepted_at: <YYYY-MM-DD>` で rg 機械検査可能)

- ADR-00020 accepted_at: 2026-05-19 (framework intake checklist、blocker 完全削除完了、SP022-T01 framework intake CI 機械化着手 trigger)
- ADR-00021 accepted_at: 2026-05-19 (host-portable deployment design accepted、SP022-T09 実機 drill による post-acceptance verification 待ち)
- ADR-00007 accepted_at: 2026-05-19 (external exposure host-portable update、ADR-00021 simultaneous、SP022-T09 で Tailscale 閉域維持 invariant verify 待ち)

#### HARD GATE evidence (F-003 adopt: codex-plan-review R1 completion record、rg/grep で機械検査可能)

- codex-plan-review-round: R1 (本 PR PR description / Review 欄に対応する round-state.json path も記録)
- codex-plan-review-findings: 15 (CRITICAL: 0、HIGH: 3、MEDIUM: 7、LOW: 5)
- codex-plan-review-adopt: 15 / reject: 0 / defer: 0 (全 finding adopt 反映)
- codex-plan-review-readiness-gate: READY (CRITICAL=0、HIGH残存=0、F-001/002/003 + 全 HIGH を rewrite で消化)
- codex-plan-review-evidence-path: ~/.claude/local/codex-reviews/2026-05-19/sprint-SP-012-batch-7-taskhub-admin-cli/codex-plan-review-20260519-144046.raw.jsonl

#### Frontmatter promotion process

- `planned_adr_refs` → `adr_refs` 移動 + `planned_adr_refs` key 完全削除 (`.claude/rules/sprint-pack-adr-gate.md §12.1` 12.2 promotion 完了 trigger)
- 3 ADR 同一日付 (2026-05-19) で simultaneous accepted (F-PR67-047 mutual blocking cycle 解消、common SP022-T00 simultaneous acceptance gate に置換)
- ADR-00020 `acceptance_blocked_by` 完全削除 (F-005 adopt: accepted 後の active blocker key 同居を回避、rationale は acceptance_history に移送)

#### Active text sync update completed (F-014 adopt: line number は参考、見出し / 旧文言 / 新文言を正本識別。F-R3-001 adopt: 旧文言例示は historical quote として記録、§6.1 check (5) で `## 関連 ADR` active section 限定 grep に scope 済)

- SP-022 `## 関連 ADR` セクション内 stale text 修正 (旧文言の literal quote は本 Review 内では historical evidence として保持、active section の修正は L162 周辺の見出し「## 関連 ADR」内の旧 ADR-00014/15/16/17/18/19 行を「P0.1+ owning sprint で proposed→accepted 予定」表現に置換、§6.1 check (5) で active section のみ verify)
- SP-022 Phase E 16 finding closure audit-only gate split (`## タスク一覧` + `## must_ship 対応表` + `## 受け入れ条件` + `## 検証手順` セクションの旧 Phase E active requirement 文言を audit-only trace gate に変更、実 contract test PASS は post-P0.1 SP-013〜020 owning sprint exit gate carry-over)
- SP-022 Phase G PGA-F-009 audit-only gate split (`## Phase G adversarial strengthening` セクション内の旧 PGA-F-009 active requirement 文言を audit-only trace gate に変更、実 contract test PASS は post-P0.1 SP-015 完了後 owning sprint exit gate carry-over)
- SP-001-5 active text 7 箇所 (`## 目的` / `## 設計判断` / `## 実装チケット` / `## must_ship 対応表` / `## 受け入れ条件` / `## レビュー観点` / `## 関連 ADR` セクション内の旧「SP-022 で実機 host migration drill PASS 後」「SP-022 carry over」文言) の update

(後続: SP-022 完了時に T01-T09 全体 Review を追記)
```

### 3.6 SP-022 L162 stale text 修正 (step 6 (a))

**現状 (L162)**:

```markdown
- ADR-00014/15/16/17/18/19 (P0.1+ で accepted 済、本 Sprint で運用 hardening)
```

**update 後**:

```markdown
- ADR-00014/15/16/17/18/19 (P0.1+ owning sprint で proposed→accepted 予定、本 Sprint では運用 hardening のみ、F-ADV-R1-006 adopt: 旧「accepted 済」は ADR-00014/00016 が実際 `status: proposed` のため stale text、SP022-T00 PR で reviewer が ADR-00020 blocker 解消済と誤読する acceptance lifecycle trap 回避のため update)
```

### 3.7 SP-022 Phase E audit-only split (step 6 (b)、L74 / L94 / L104 / L124-126)

**L74 task list 現状**:

```markdown
- [ ] Phase E 16 finding が全件 closed (adopt 済 + test fixture 化済)
```

**update 後**:

```markdown
- [ ] Phase E 16 finding (PE-F-001〜PE-F-016) が owning ADR/Sprint Pack に割り当て済 + 受け入れ条件に trace されている (**audit-only gate**、F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 adopt: 実 contract test PASS は post-P0.1 SP-013〜016/SP-018/SP-020 owning sprint exit gate carry-over、SP-022 では trace 確認のみ)
```

**L94 must_ship 表 現状**:

```markdown
| Phase E 16 finding closure | ○ | LOW 残存は P3+ で対応可 |
```

**update 後**:

```markdown
| Phase E 16 finding audit-only trace gate (PE-F が owning ADR/Sprint Pack に割り当て済 + 受け入れ条件 trace) | ○ | LOW 残存は P3+ で対応可 |
| Phase E 16 finding 実 contract test PASS | ✗ (post-P0.1 owning sprint exit gate carry-over) | F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 adopt: SP-013〜016/SP-018/SP-020 contract test 依存 = future-sprint 循環、SP-022 must_ship では audit-only gate のみ |
```

**L104 受け入れ条件 現状**:

```markdown
- Phase E 16 finding (PE-F-001〜PE-F-016) すべての closure evidence (各 finding に対応する test fixture / contract test PASS)
```

**update 後**:

```markdown
- Phase E 16 finding (PE-F-001〜PE-F-016) すべてが owning ADR/Sprint Pack に trace 済 (**audit-only gate**: 各 finding の owning sprint への割り当て + 受け入れ条件への trace を文書確認、F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 adopt: 実 contract test PASS は post-P0.1 owning sprint exit gate で実施)
```

**L124-126 検証手順 現状**:

```bash
# Phase E 16 finding closure
$ uv run pytest eval/multi_agent/role_authorization_negative/ eval/multi_agent/inter_agent_replay_attack/ \
                eval/multi_agent/memory_secret_canary/ eval/multi_agent/framework_intake_violation/ -q
```

**update 後**:

```bash
# Phase E 16 finding audit-only trace verification (F-R2-003 adopt: future Sprint Pack 不在の false positive を回避、SP-022 内 trace matrix で local closure)
# SP-022 内に PE-F-001〜016 の owning ADR/Sprint Pack mapping table を追加し、SP-022 内で trace 完結
# 実 contract test PASS は post-P0.1 owning sprint exit gate (SP-013/014/015/016 + 将来 SP-018/SP-020) で実施
$ rg -nP 'PE-F-(00[1-9]|01[0-6])' docs/sprints/SP-022_framework_intake_hardening.md
# expected: PE-F-001〜PE-F-016 全 16 finding が SP-022 内 trace matrix で言及 (owning sprint 名 + must_ship 反映方針付き)
# Note: SP-018/SP-020 Sprint Pack は P0.1+ で起票予定 (現状不在)、SP-022 内 trace matrix で「SP-018 で実装予定」「SP-020 で実装予定」と marker
# (post-P0.1 owning sprint exit gate で実 pytest 実行) $ uv run pytest eval/multi_agent/... -q
```

**SP-022 内に追加する Phase E trace matrix** (本 PR で `## Phase E adversarial closure trace` 新 section として SP-022 末尾に追加):

```markdown
## Phase E adversarial closure trace (PE-F-001〜PE-F-016、F-R2-003 adopt: SP-022 内 audit-only trace matrix で local closure)

| Finding ID | Owning Sprint | trace status | post-P0.1 contract test PASS gate |
|---|---|---|---|
| PE-F-001 | SP-013 | (SP-013 着手時 must_ship 反映予定) | SP-013 exit gate |
| PE-F-002 | SP-013 | (SP-013 着手時 must_ship 反映予定) | SP-013 exit gate |
| PE-F-003 | SP-014 | (SP-014 着手時 must_ship 反映予定) | SP-014 exit gate |
| PE-F-004 | SP-014 | (SP-014 着手時 must_ship 反映予定) | SP-014 exit gate |
| PE-F-005 | SP-014 | (SP-014 着手時 must_ship 反映予定) | SP-014 exit gate |
| PE-F-006 | SP-015 | (SP-015 着手時 must_ship 反映予定) | SP-015 exit gate |
| PE-F-007 | SP-015 | (SP-015 着手時 must_ship 反映予定) | SP-015 exit gate |
| PE-F-008 | SP-016 | (SP-016 着手時 must_ship 反映予定) | SP-016 exit gate |
| PE-F-009 | SP-016 | (SP-016 着手時 must_ship 反映予定) | SP-016 exit gate |
| PE-F-010 | SP-016 | (SP-016 着手時 must_ship 反映予定) | SP-016 exit gate |
| PE-F-011 | SP-018 (P0.1+ 起票予定) | (SP-018 起票 PR で trace 追加予定) | SP-018 exit gate |
| PE-F-012 | SP-018 (P0.1+ 起票予定) | (SP-018 起票 PR で trace 追加予定) | SP-018 exit gate |
| PE-F-013 | SP-018 (P0.1+ 起票予定) | (SP-018 起票 PR で trace 追加予定) | SP-018 exit gate |
| PE-F-014 | SP-020 (P0.1+ 起票予定) | (SP-020 起票 PR で trace 追加予定) | SP-020 exit gate |
| PE-F-015 | SP-020 (P0.1+ 起票予定) | (SP-020 起票 PR で trace 追加予定) | SP-020 exit gate |
| PE-F-016 | SP-020 (P0.1+ 起票予定) | (SP-020 起票 PR で trace 追加予定) | SP-020 exit gate |

**audit-only gate**: SP-022 では本 trace matrix を文書として保持、実 contract test PASS は各 owning sprint exit gate (post-P0.1)。Owning Sprint Pack 不在 (SP-018/SP-020 未起票) の場合は「P0.1+ 起票予定」marker で保留、SP-018/SP-020 起票 PR で trace を実際に追加。SP022-T00 PR では SP-022 内 trace matrix の存在のみ verify。
```

### 3.8 SP-022 Phase G PGA-F-009 audit-only split (step 6 (c)、L172 / L187)

**L172 現状**:

```markdown
- **inter_agent_messages consumed invariant fixture (PGA-F-009)**: SP-015 で実装されたものを SP-022 で 追加 fixture (post-restore + post-migration 全 case) で再 verify
```

**update 後 (F-R2-004 adopt: SP-015 への直接 trace verify は allowlist 外で false-positive、SP-022 内 trace matrix で local closure + SP-015 trace は future PR)**:

```markdown
- **inter_agent_messages consumed invariant fixture (PGA-F-009)**: SP-022 内で audit-only trace 宣言 (F-ADV-R1-001 + F-R2-004 adopt: SP-015 owning sprint への実 trace 反映は SP-015 着手 PR で実施、SP-022 では本宣言を audit marker として保持、SP-015 完了後 owning sprint exit gate で post-restore + post-migration 全 case の実 contract test PASS verify = future-sprint 循環防止)。SP-022 内では PGA-F-009 trace status = `pending SP-015 起票 PR for owning sprint trace`、SP022-T00 PR では SP-022 内 audit marker のみ verify (SP-015 file は本 PR allowlist 外、SP-015 着手時に PR 起票)
```

**L187 現状**:

```markdown
- Phase G adversarial 14 finding (PGA-F-001〜PGA-F-014) すべての closure evidence (test fixture / contract test PASS) verify
```

**update 後**:

```markdown
- Phase G adversarial 14 finding (PGA-F-001〜PGA-F-014) のうち PGA-F-009 (SP-015 依存) は **audit-only gate** (SP-015 完了後 owning sprint exit gate で実 contract test PASS、F-ADV-R1-001 adopt)、残 13 finding (PGA-F-001〜008 + PGA-F-010〜014) は本 SP-022 内で closure evidence (test fixture / contract test PASS) verify
```

### 3.8.1 SP-022 SP022-T07 production checklist scope boundary 明文化 (F-R2-005 adopt: master plan §10.C-1 F-ADV-R1-007 requirement の移植)

`docs/sprints/SP-022_framework_intake_hardening.md` の SP022-T07 行 / must_ship row / 受け入れ条件 / レビュー観点を update して production scope leak を防ぐ:

**SP022-T07 task list 旧文言**:
```markdown
- SP022-T07: production 公開準備 checklist draft (P3+ 着手時の前提整理)
```

**SP022-T07 task list 新文言**:
```markdown
- SP022-T07: production 公開準備 checklist draft (P3+ 着手時の前提整理、F-ADV-R1-007 + F-R2-005 adopt: **本 task は docs-only checklist skeleton まで**、以下の P3+ 実作業は本 task 内で禁止: (a) Docker image build pipeline、(b) DNS 設定、(c) public ingress (Funnel / Cloudflare Tunnel / public bind)、(d) external publication、(e) release deploy config、(f) license / docs 整備の本実装。これらは P3+ で SP-023 以降の production release Sprint Pack で実施)
```

**SP022-T07 must_ship row 旧文言**:
```markdown
| production 公開準備 checklist draft | ○ | 詳細実装は P3+ |
```

**SP022-T07 must_ship row 新文言**:
```markdown
| production 公開準備 checklist draft (**docs-only skeleton まで、F-R2-005 adopt: Docker image build / DNS / public ingress / external publication / release deploy config / license 整備の本実装は禁止**) | ○ | 詳細実装は P3+ SP-023+ Sprint Pack で実施、本 T07 task では skeleton checklist 1 file (docs/release/production_readiness_checklist.md) のみ作成 |
```

**受け入れ条件 追加**:
```markdown
- SP022-T07 production checklist draft は **docs-only checklist skeleton 1 file** (`docs/release/production_readiness_checklist.md`、F-R2-005 adopt) のみ作成、Docker image build pipeline / DNS 設定 / public ingress (Funnel / Cloudflare Tunnel) / external publication / release deploy config / license 整備の本実装は **本 T07 内で禁止** (P3+ SP-023+ Sprint Pack で実施)
- P0.1 unblock 判定では SP022-T07 = production 実装完了ではなく **checklist draft skeleton 存在確認のみ** (F-ADV-R1-007 + F-R2-005 adopt)
```

### 3.9 SP-001-5 active text 7 箇所 update (step 6 (d)、L38 / L52 / L72 / L92 / L97 / L130 / L148)

**L38 目的セクション本文**:

旧:
```markdown
- ADR-00021 (host-portable) acceptance は SP-022 で実機 host migration drill PASS 後 (PR #67 R4 F-PR67-010/013/017 P2 adopt、本 SP-001.5 では skeleton 実装の参照 ADR として draft 状態で進行)
```

新:
```markdown
- ADR-00021 (host-portable) acceptance は SP-022 で SP022-T00 design accepted (本 SP-001.5 完了時の SP-022 着手 PR で実施済、2026-05-19) + SP022-T09 実機 host migration drill (Mac→VPS) RTO≤4h PASS による post-acceptance verification (本 SP-001.5 では skeleton 実装の参照 ADR として draft 状態で進行、F-PLAN-R4-001 + F-PLAN-R5-002 adopt)
```

**L52 背景 `taskhub` admin CLI prereq 説明**:

旧:
```markdown
- **`taskhub` admin CLI を P0 で導入**: P0 期間中の Mac 起動運用 + Sprint 12 host migration drill の prerequisite
```

新:
```markdown
- **`taskhub` admin CLI を P0 で導入**: P0 期間中の Mac 起動運用 + Sprint 12 skeleton 実装着手 + SP022-T09 実機 host migration drill (Mac→VPS) の prerequisite
```

**L72 SP015-T07 注釈**:

旧:
```markdown
- SP015-T07: ADR-00021 + ADR-00007 update accepted 化は **SP-022 carry over** (F-PR67-010/013/017 P2 adopt、acceptance 条件 = 実機 host migration drill PASS が SP-022 scope のため、SP-001.5 では skeleton 実装着手のみ進める)
```

新:
```markdown
- SP015-T07: ADR-00021 + ADR-00007 update accepted 化は **SP-022 で実施完了** (SP022-T00 で design accepted = 2026-05-19、SP022-T09 で実機 drill verification、本 SP-001.5 は skeleton 実装着手のみ進めて SP-022 で完了)
```

**L92 must_ship 対応表** (F-009 adopt: ✗ は「SP-001.5 内 must_ship 否」の意味、accepted 完了は別軸、`N/A` 表現で混同回避):

旧:
```markdown
| ADR-00021 + ADR-00007 update accepted | ✗ (SP-022 carry over) | F-PR67-010/013/017 P2 adopt: acceptance 条件 = 実機 host migration drill PASS が SP-022 scope、本 SP-001.5 は skeleton 実装着手のみ |
```

新:
```markdown
| ADR-00021 + ADR-00007 update accepted | N/A (SP-022 で実施完了、2026-05-19 SP022-T00 design accepted) | F-009 adopt: 旧 ✗ 表記は「SP-001.5 内 must_ship 否」と「accepted 未完了」を混同する余地、N/A 化で「SP-001.5 scope 外、別 sprint で完了済」を明示。SP022-T00 で design accepted + SP022-T09 で実機 drill による post-acceptance verification、本 SP-001.5 は skeleton 実装着手のみ |
```

**L97 受け入れ条件**:

旧:
```markdown
- ADR-00021 / ADR-00007 update は **proposed のまま** (SP-001.5 着手時 gate ではなく、acceptance は SP-022 で実機 drill PASS 後、F-PR67-017 P2 adopt)
```

新:
```markdown
- ADR-00021 / ADR-00007 update は **本 SP-001.5 着手時は proposed** (本 amendment 着手時は ADR は proposed 状態、SP-022 着手 PR (SP022-T00 = 2026-05-19) で simultaneous accepted、SP022-T09 で実機 drill による post-acceptance verification)
```

**L130 レビュー観点**:

旧:
```markdown
- ADR-00021 lifecycle (proposed → **SP-022 で実機 drill PASS 後 accepted**) が ADR Gate Criteria に沿う (F-PR67-010/017 P2 adopt、master plan line 106 整合)
```

新:
```markdown
- ADR-00021 lifecycle (proposed → **SP-022 で SP022-T00 design accepted + SP022-T09 実機 drill PASS による post-acceptance verification**) が ADR Gate Criteria に沿う (master plan §1.3 / §5 / §10 + ADR-00021 frontmatter 整合、F-PLAN-R4-001 + F-PLAN-R5-002 adopt)
```

**L148 関連 ADR**:

旧:
```markdown
- ADR-00021 (Host-Portable Deployment + Data Migration、SP-022 で実機 drill PASS 後 accepted、本 SP-001.5 は skeleton 実装着手の参照 ADR)
```

新:
```markdown
- ADR-00021 (Host-Portable Deployment + Data Migration、SP-022 で SP022-T00 design accepted = 2026-05-19 + SP022-T09 実機 drill post-acceptance verification、本 SP-001.5 は skeleton 実装着手の参照 ADR)
```

## 4. Invariant Trace Matrix

| invariant | 対応 rule | 本 PR 影響 | verification |
|---|---|---|---|
| ADR Gate Criteria 11 種 | `.claude/rules/sprint-pack-adr-gate.md §4` | **直接該当** (#1 認証 / #7 外部公開 / #11 GitHub App permission related): ADR-00020/00021/00007 promotion | §6.1 12 段 fail-closed assertion |
| ADR accepted promotion normal-flow | `.claude/rules/sprint-pack-adr-gate.md §12` | **強化** (atomic 7 step + 12 段 fail-closed verification + step 0 HARD GATE) | §6.1 verification |
| ADR accepted promotion codex-plan-review gate | `.claude/rules/sprint-pack-adr-gate.md §12.4` + `.claude/rules/codex-usage-policy.md §14.1` | **強化** (本 plan 自体に対し codex-plan-review R1 mandatory gate を §6.2 で実行) | PR description / Review 欄に round/finding/採否 evidence 記録 |
| Codex review hard gate (CRITICAL invariant) | `.claude/rules/codex-usage-policy.md §14` | **直接該当** (CRITICAL invariant 直結変更 + 3+ file 横断): codex-plan-review R1 minimum + 採否判定 + 累計 finding clean まで polish | §6.2 polling + multi-round adopt |
| AgentRun 16 状態 + blocked サブ 3 | `.claude/rules/agentrun-state-machine.md §1-2` | 影響なし | enum 不変 |
| ContextSnapshot 必須 10 列 | `.claude/CLAUDE.md §2.8` | 影響なし | enum 不変 |
| Provider Compliance 13 reason_code | `.claude/rules/provider-compliance.md §9` | 影響なし | enum 不変 |
| SecretBroker atomic claim | `.claude/rules/secretbroker-boundary.md §8` | 影響なし | code change なし |
| tenant/project boundary 複合 FK | `.claude/rules/core.md §8` | 影響なし | DDL 不変 |
| Hard Gates 7 + Quality KPIs 5 | `.claude/CLAUDE.md §2.Hard Gates` | 影響なし | enum 不変 |
| Tailscale 閉域 (Funnel 不使用) | `.claude/CLAUDE.md §2.2` + ADR-00007 | **間接該当** (ADR-00007 promotion 自体、Tailscale invariant は不変) | §6.1 verification (Tailscale 設定不変) |
| `git add -A` / `git add .` 禁止 | `.claude/CLAUDE.md §6.7` | 遵守 (本 PR は明示 file 指定) | commit 時 verify |
| PR workflow invariant | `.claude/rules/branch-and-pr-workflow.md` L9-13 | 遵守 (Claude が PR 起票、user が merge、main 直接 commit 禁止) | §6.3 PR workflow verify |

## 5. Rollback (F-001 + F-010 adopt: master plan 削除 + merge strategy 別 rollback 明示)

本 PR は docs-only、code 影響なし。rollback 手順 (atomic 7 step なので 1 commit revert で全件 rollback)。**本 PR は §0 allowlist 通り 6 files のみ変更、master plan は touch しないため rollback 対象外** (F-001 adopt):

### 5.1 Squash merge 後の rollback (default、TaskManagedAI プロジェクト標準)

本プロジェクト default は squash merge:

```bash
# 1. main 上の squash commit を特定
git log main --oneline | head -5  # SP022-T00 PR の squash commit SHA を確認
# 2. squash commit を revert (1 commit revert で全 6 file rollback)
git revert <squash-commit-sha>
# 3. revert commit を別 branch + PR で merge
```

### 5.2 Rebase merge / merge commit 後の rollback (本プロジェクトでは非標準、例外時)

```bash
# 複数 commit の場合は commit range 全体を revert
git revert <oldest-commit-sha>..<newest-commit-sha>
```

### 5.3 未 merge branch 上での rollback (PR 取り下げ)

```bash
# branch を local + remote で削除 (PR は close する)
git checkout main
git branch -D worktree-sp022-t00-pre-implementation-gate
git push origin --delete worktree-sp022-t00-pre-implementation-gate
gh pr close <PR-NUMBER>
```

### 5.4 Rollback 後の state + 影響

- SP-022 frontmatter の `planned_adr_refs` key が復活、3 ADR `status: proposed` に戻る
- ADR-00020 frontmatter `acceptance_blocked_by` の循環依存 ["ADR-00014/16 accepted", "P0 完了"] が復活
- SP-022 `## Review` の SP022-T00 entry + HARD GATE evidence が削除
- SP-022 + SP-001-5 active text が旧 acceptance path 文言に戻る
- 失敗時の影響: **機能的影響なし** (本 PR は docs-only metadata)、ただし **SP-022 T01-T09 着手不可** (acceptance_blocked_by が再 active になり P0.1 unblock 遅延)
- 別 PR で再 update 可能 (本 plan §3 atomic 7 step を再実行)

## 6. Verification

### 6.1 Pre-commit verification (`.claude/plans/master-plan-section-10-11-update.md §3.3 §10.C-1` で正本化された 12 段 fail-closed assertion、F-004 + F-007 + F-008 + F-013 adopt 強化)

```bash
set -euo pipefail
SP022_T00_DATE=$(git show -s --format=%cd --date=format-local:%Y-%m-%d HEAD)  # F-006 adopt: 本 PR first commit date を正本

# F-004 adopt: yq toolchain チェック (mikefarah yq v4+ 前提、kislyuk yq との互換性問題回避)
if ! command -v yq >/dev/null 2>&1; then
  echo "FAIL: yq not installed. Install mikefarah yq v4+ (https://github.com/mikefarah/yq)" >&2; exit 1
fi
yq_version=$(yq --version 2>&1 | grep -oE 'v[0-9]+\.[0-9]+' | head -1)
if [ -z "$yq_version" ] || [[ "$yq_version" < "v4" ]]; then
  echo "FAIL: yq version $yq_version not supported (require mikefarah yq v4+)" >&2; exit 1
fi
echo "yq version: $yq_version (mikefarah yq v4+ assumed)"

# SP-022 frontmatter 抽出 (YAML frontmatter 付き Markdown のため awk 抽出、F-ADV-R4-001 adopt)
SP022_FRONTMATTER=$(awk 'NR==1 && $0=="---" {in_fm=1; next} in_fm && $0=="---" {exit} in_fm {print}' docs/sprints/SP-022_framework_intake_hardening.md)

# (1) 3 ADR status が exact "accepted" であること fail-closed assert
for adr in 00020_framework_intake_checklist.md 00021_host_portable_deployment.md 00007_external_exposure.md; do
  if ! rg -q '^status:\s*"accepted"' "docs/adr/$adr"; then
    echo "FAIL: docs/adr/$adr status != \"accepted\"" >&2; exit 1
  fi
done

# (2) 3 ADR updated_at が SP022_T00_DATE と exact equality
for adr in 00020_framework_intake_checklist.md 00021_host_portable_deployment.md 00007_external_exposure.md; do
  actual=$(rg -m1 '^updated_at:' "docs/adr/$adr" | sed -E 's/^updated_at:\s*"?([^"\s]+)"?.*/\1/')
  if [ "$actual" != "$SP022_T00_DATE" ]; then
    echo "FAIL: docs/adr/$adr updated_at=$actual != $SP022_T00_DATE" >&2; exit 1
  fi
done

# (3) SP-022 adr_refs が exact set {ADR-00020, ADR-00021, ADR-00007} であること assert (F-007 + F-R4-fix adopt: sort + diff -u で重複 / 別 ADR 混入 / 順序を厳密検査。F-R4-fix: adr_refs entry の comment 部分に `ADR-00014/00016` 等が記載されると誤検出するため、`[ADR-XXXXX]` link header 限定で抽出)
adr_refs_count=$(printf '%s\n' "$SP022_FRONTMATTER" | yq -e '.adr_refs | length' -)
if [ "$adr_refs_count" != "3" ]; then
  echo "FAIL: SP-022 adr_refs count=$adr_refs_count != 3" >&2; exit 1
fi
# adr_refs から link header `[ADR-XXXXX]` のみ抽出 (entry の comment 部分の ADR-XXXXX 言及を除外)
adr_refs_actual=$(printf '%s\n' "$SP022_FRONTMATTER" | yq -e '.adr_refs[]' - | grep -oE '\[ADR-[0-9]{5}\]' | grep -oE 'ADR-[0-9]{5}' | sort -u)
adr_refs_expected=$(printf 'ADR-00007\nADR-00020\nADR-00021\n' | sort -u)
if ! diff -u <(echo "$adr_refs_expected") <(echo "$adr_refs_actual") >/dev/null 2>&1; then
  echo "FAIL: SP-022 adr_refs set mismatch:" >&2
  diff -u <(echo "$adr_refs_expected") <(echo "$adr_refs_actual") >&2 || true
  exit 1
fi

# (4) SP-022 planned_adr_refs key absent fail-closed
planned_check=$(printf '%s\n' "$SP022_FRONTMATTER" | yq -e '.planned_adr_refs // "absent"' -)
if [ "$planned_check" != "absent" ]; then
  echo "FAIL: SP-022 still has planned_adr_refs key (value=$planned_check)" >&2; exit 1
fi
if rg -q '^planned_adr_refs:' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 still has planned_adr_refs key line (raw rg check)" >&2; exit 1
fi

# (5) SP-022 `## 関連 ADR` section 内の L162 stale text 修正後 (F-R3-001 adopt: SP-022 全体 grep を `## 関連 ADR` section 限定の awk extract に scope、Review 追記の historical quote は許容)
related_adr_body=$(awk '/^## 関連 ADR$/ {in_sec=1; next} /^## / && in_sec {exit} in_sec {print}' docs/sprints/SP-022_framework_intake_hardening.md)
if printf '%s\n' "$related_adr_body" | rg -q '\(P0\.1\+ で accepted 済'; then
  echo "FAIL: SP-022 '## 関連 ADR' section still has '(P0.1+ で accepted 済' stale text" >&2; exit 1
fi

# (6) SP-001-5 active text 旧 acceptance path 修正後 (F-008 adopt: frontmatter / fenced code block 除外、active body のみ対象、historical comment は許容)
# frontmatter (--- ... ---) と fenced code block (``` ... ```) を除外して active body のみ抽出
sp001_5_active_body=$(awk '
  BEGIN { in_fm=0; in_code=0; lineno=0 }
  { lineno++ }
  NR==1 && $0=="---" { in_fm=1; next }
  in_fm && $0=="---" { in_fm=0; next }
  in_fm { next }
  /^```/ { in_code = !in_code; next }
  in_code { next }
  /^#/ { next }  # markdown comment (# で始まる行) は historical comment として除外
  { print lineno":"$0 }
' docs/sprints/SP-001-5_host_portable_amendment.md)
if echo "$sp001_5_active_body" | grep -qE 'SP-022 で実機 host migration drill PASS 後'; then
  echo "FAIL: SP-001-5 active body (frontmatter / code block / comment 除外後) still has 'SP-022 で実機 host migration drill PASS 後':" >&2
  echo "$sp001_5_active_body" | grep -E 'SP-022 で実機 host migration drill PASS 後' >&2
  exit 1
fi
if echo "$sp001_5_active_body" | grep -qE '\(SP-022 carry over\)'; then
  echo "FAIL: SP-001-5 active body still has '(SP-022 carry over)':" >&2
  echo "$sp001_5_active_body" | grep -E '\(SP-022 carry over\)' >&2
  exit 1
fi

# (7) SP-022 Phase E active requirement 不在 verify
if rg -qP '^- \[ \] Phase E 16 finding が全件 closed \(adopt 済' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 still has Phase E active task list (旧)" >&2; exit 1
fi
if rg -qP '\| Phase E 16 finding closure \| ○ \| LOW' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 still has Phase E must_ship=○ row (旧、audit-only split incomplete)" >&2; exit 1
fi

# (8) SP-022 Phase G PGA-F-009 SP-015 依存 active 不在 verify
if rg -qP 'SP-015 で実装されたものを SP-022 で\s*追加 fixture' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 still has Phase G PGA-F-009 SP-015 依存 active fixture (旧)" >&2; exit 1
fi

# (9) audit-only gate / post-P0.1 carry-over の positive 補助確認 (F-R3-001 adopt: -qP + 真 alternation で `|` escape 問題回避)
rg -qP 'audit-only.*trace gate|audit-only gate' docs/sprints/SP-022_framework_intake_hardening.md || { echo "FAIL: SP-022 missing 'audit-only trace gate' or 'audit-only gate' positive marker" >&2; exit 1; }
rg -qP 'post-P0\.1 .* owning sprint exit gate' docs/sprints/SP-022_framework_intake_hardening.md || { echo "FAIL: SP-022 missing 'post-P0.1 owning sprint exit gate' positive marker" >&2; exit 1; }

# (10) HARD GATE evidence: codex-plan-review R1 完了 record の機械検査 (F-003 adopt: SP-022 Review section の HARD GATE evidence block を rg/grep で fail-closed assert)
# SP-022 `## Review` の HARD GATE evidence section で codex-plan-review-round / -findings / -adopt / -readiness-gate / -evidence-path が記録されていること
for marker in "codex-plan-review-round:" "codex-plan-review-findings:" "codex-plan-review-adopt:" "codex-plan-review-readiness-gate: READY" "codex-plan-review-evidence-path:"; do
  if ! rg -qF "$marker" docs/sprints/SP-022_framework_intake_hardening.md; then
    echo "FAIL: SP-022 Review HARD GATE evidence missing '$marker'" >&2; exit 1
  fi
done

# (11) 3 ADR `acceptance_blocked_by` 削除 verify (F-R2-001 + F-R2-002 adopt: accepted 後の active blocker key 完全削除を全 3 ADR で確認、SP022-T00 gate 完了 rationale は acceptance_history で検証)
for adr in 00020_framework_intake_checklist.md 00021_host_portable_deployment.md 00007_external_exposure.md; do
  fm=$(awk 'NR==1 && $0=="---" {in_fm=1; next} in_fm && $0=="---" {exit} in_fm {print}' "docs/adr/$adr")
  # acceptance_blocked_by key 自体が削除されていること fail-closed assert (has() check)
  if printf '%s\n' "$fm" | yq -e 'has("acceptance_blocked_by")' - >/dev/null 2>&1; then
    echo "FAIL: docs/adr/$adr still has active acceptance_blocked_by after accepted promotion (F-R2-001 + F-R2-002 adopt: accepted 後は key 削除必須、SP022-T00 gate 完了事実は acceptance_history に移送)" >&2; exit 1
  fi
done
# ADR-00020 acceptance_history に SP022-T00 independent accept rationale が存在すること
ADR20_FRONTMATTER=$(awk 'NR==1 && $0=="---" {in_fm=1; next} in_fm && $0=="---" {exit} in_fm {print}' docs/adr/00020_framework_intake_checklist.md)
printf '%s\n' "$ADR20_FRONTMATTER" | yq -e '.acceptance_history[] | select(test("SP022-T00.*multi-agent ADR-00014/00016.*独立"))' - >/dev/null || {
  echo "FAIL: ADR-00020 acceptance_history missing 'SP022-T00 independent accept (multi-agent ADR-00014/00016 から独立)' rationale" >&2; exit 1
}
# ADR-00021/00007 acceptance_history に SP022-T00 simultaneous gate 完了 rationale が存在すること
for adr in 00021_host_portable_deployment.md 00007_external_exposure.md; do
  fm=$(awk 'NR==1 && $0=="---" {in_fm=1; next} in_fm && $0=="---" {exit} in_fm {print}' "docs/adr/$adr")
  printf '%s\n' "$fm" | yq -e '.acceptance_history[] | select(test("SP022-T00 pre-implementation gate.*acceptance_blocked_by key は accepted 後削除"))' - >/dev/null || {
    echo "FAIL: docs/adr/$adr acceptance_history missing 'SP022-T00 gate 完了 + acceptance_blocked_by 削除' rationale" >&2; exit 1
  }
done

# (12) SP-022 `## Review` で 3 ADR `accepted_at: $SP022_T00_DATE` 記録 verify
for adr_id in ADR-00020 ADR-00021 ADR-00007; do
  if ! rg -qP "$adr_id accepted_at: $SP022_T00_DATE" docs/sprints/SP-022_framework_intake_hardening.md; then
    echo "FAIL: SP-022 Review missing $adr_id accepted_at: $SP022_T00_DATE record" >&2; exit 1
  fi
done

# (13) SP022-T07 production scope boundary verify (F-R2-005 adopt: master plan §10.C-1 F-ADV-R1-007 要求)
# docs-only checklist skeleton 制約が SP-022 内で明示されていること
if ! rg -q 'docs-only checklist skeleton.*F-R2-005' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 SP022-T07 missing 'docs-only checklist skeleton' boundary marker (F-R2-005 adopt)" >&2; exit 1
fi
# 禁止対象キーワード (Docker image build pipeline / DNS / public ingress / Funnel / Cloudflare Tunnel / release deploy config) が SP022-T07 task の禁止 list に明記されていること
for keyword in 'Docker image build pipeline' 'public ingress' 'release deploy config'; do
  if ! rg -qF "$keyword" docs/sprints/SP-022_framework_intake_hardening.md; then
    echo "FAIL: SP-022 SP022-T07 boundary missing keyword '$keyword' (F-R2-005 adopt)" >&2; exit 1
  fi
done

# (14) Phase E PE-F-001〜016 trace matrix が SP-022 内に存在すること verify (F-R2-003 adopt)
if ! rg -q '## Phase E adversarial closure trace' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 missing '## Phase E adversarial closure trace' section (F-R2-003 adopt)" >&2; exit 1
fi
pe_f_count=$(rg -oP 'PE-F-(00[1-9]|01[0-6])' docs/sprints/SP-022_framework_intake_hardening.md | sort -u | wc -l | tr -d ' ')
if [ "$pe_f_count" -lt 16 ]; then
  echo "FAIL: SP-022 Phase E trace matrix has only $pe_f_count / 16 PE-F findings (F-R2-003 adopt)" >&2; exit 1
fi

# (15) PGA-F-009 audit marker が SP-022 内に存在すること verify (F-R2-004 adopt)
if ! rg -q 'PGA-F-009.*pending SP-015' docs/sprints/SP-022_framework_intake_hardening.md; then
  echo "FAIL: SP-022 missing PGA-F-009 audit marker 'pending SP-015 起票 PR' (F-R2-004 adopt)" >&2; exit 1
fi

echo "✅ All 15 fail-closed verifications PASS"
```

### 6.2 Codex auto-review baseline 確認義務 (LATEST_SHA bind polling contract、F-012 adopt: timeout / 再 polling 回数 / no review 扱い / record location 明示)

`.claude/plans/master-plan-section-10-11-update.md §3.3 §6.2.1` の polling contract 準拠 (F-ADV-R2-003 + F-ADV-R1-004 adopt) + F-012 adopt (本 plan で詳細追加):

#### 6.2.1 polling spec

| 項目 | spec |
|---|---|
| **initial polling** | 10 min (`sleep 600`) を 1 回目 |
| **再 polling 回数 max** | 2 回 (累計 30 min = initial 10 + retry 10 + retry 10) |
| **polling interval** | retry 毎に 10 min (`sleep 600`) |
| **timeout** | 累計 30 min 経過後 |
| **no review for HEAD 扱い** | reaction-only clean 可能性として user 明示確認必須 (silent merge 禁止)、user 確認 record location = PR comment thread + 本 PR Review log |
| **PR merge 禁止解除条件** | (a) PRE/CUR_REVIEW_FOR_HEAD count > 0 で 全 finding adopt/reject/defer 採否判定済、または (b) user 明示確認 record 残し reaction-only clean、または (c) CI billing infrastructure failure による admin merge bypass (Sprint 12 PR #59-#67 pattern、user 明示指示時のみ) |

#### 6.2.2 polling command sequence

```bash
PR_NUMBER=<本 PR 番号>
LATEST_SHA=$(gh pr view "$PR_NUMBER" --json headRefOid -q .headRefOid)

# initial polling (10 min)
PRE_INLINE=$(gh api "repos/t-ohga/TaskManagedAI/pulls/$PR_NUMBER/comments" --paginate \
  | jq "[.[] | select(.commit_id == \"$LATEST_SHA\") | select(.user.login | test(\"codex\"; \"i\"))] | length")
PRE_TOP=$(gh api "repos/t-ohga/TaskManagedAI/pulls/$PR_NUMBER/reviews" --paginate \
  | jq "[.[] | select(.commit_id == \"$LATEST_SHA\") | select(.user.login | test(\"codex\"; \"i\"))] | length")
echo "PRE inline=$PRE_INLINE, top=$PRE_TOP"

sleep 600  # 1st polling (10 min)
.claude/scripts/codex_pr_full_review.sh "$PR_NUMBER" | head -200  # baseline 内容確認必須

# CUR check
CUR_INLINE=$(gh api ... | jq "[.[] | select(.commit_id == \"$LATEST_SHA\") ...] | length")
CUR_TOP=$(gh api ... | jq ...)

# 0 件継続なら再 polling (最大 2 回)
if [ "$CUR_INLINE" -eq 0 ] && [ "$CUR_TOP" -eq 0 ]; then
  for retry in 1 2; do
    echo "Retry $retry/2: no Codex review for HEAD yet, additional 10 min polling"
    sleep 600
    CUR_INLINE=$(gh api ... | jq ...)
    CUR_TOP=$(gh api ... | jq ...)
    if [ "$CUR_INLINE" -gt 0 ] || [ "$CUR_TOP" -gt 0 ]; then break; fi
  done
fi

# 累計 30 min 経過後も 0 件 → reaction-only clean / user 明示確認 必須
if [ "$CUR_INLINE" -eq 0 ] && [ "$CUR_TOP" -eq 0 ]; then
  echo "WARN: 累計 30 min polling 後も Codex auto-review 0 件" >&2
  echo "Action: user 明示確認 (PR comment thread + 本 PR Review log に record) または admin merge bypass 判断" >&2
  # silent merge 禁止
fi
```

#### 6.2.3 fail-closed 条件

- script exit status != 0 → fail-closed、user 確認まで merge 不可
- baseline empty (`wc -l == 0`) → fail-closed、wait 10 min + re-run
- `PRE_INLINE + PRE_TOP == 0` (latest HEAD への Codex review 0 件) → reaction-only clean は user 明示確認 + record 必須、silent merge 禁止
- 累計 30 min polling 後 0 件 → reaction-only clean 判断は user に委ね、PR description / comment thread に明示確認 record
- delta +0 を「真の 0 件」と即断定禁止 (`feedback_codex_pr_review_baseline_check.md` 教訓): 必ず full output の content を head -200 で確認

### 6.3 No code change + PR workflow invariant verify (F-001 + F-011 adopt: allowlist 6 files 厳密 verify)

```bash
# (a) §0 allowlist 6 files のみ変更されていること fail-closed assert
EXPECTED_FILES=$(printf '%s\n' \
  '.claude/plans/sp022-t00-pre-implementation-gate.md' \
  'docs/adr/00007_external_exposure.md' \
  'docs/adr/00020_framework_intake_checklist.md' \
  'docs/adr/00021_host_portable_deployment.md' \
  'docs/sprints/SP-001-5_host_portable_amendment.md' \
  'docs/sprints/SP-022_framework_intake_hardening.md' | sort -u)
ACTUAL_FILES=$(git diff --name-only origin/main..HEAD | sort -u)
if ! diff -u <(echo "$EXPECTED_FILES") <(echo "$ACTUAL_FILES") >/dev/null 2>&1; then
  echo "FAIL: PR file set mismatch (allowlist violation):" >&2
  diff -u <(echo "$EXPECTED_FILES") <(echo "$ACTUAL_FILES") >&2 || true
  exit 1
fi

# (b) code change 不在 verify (補助確認)
if git diff --stat origin/main..HEAD --  ':!docs/' ':!.claude/plans/' | grep -q .; then
  echo "FAIL: PR contains code change outside docs/ / .claude/plans/" >&2; exit 1
fi
```

## 7. Out-of-Scope items (explicit list、本 PR で **やらない**、F-001 + F-002 + F-015 adopt 反映)

- **ADR-00021 / ADR-00007 / ADR-00020 §normative section 本体 rewrite** (F-002 adopt: 「§normative section 本体」と「本文最終更新行」の境界を明確化): 本 PR は (a) frontmatter (status / updated_at / acceptance_history / acceptance_blocked_by / acceptance_target_sprint / post_acceptance_verification) + (b) 本文「最終更新」行 metadata 同期のみ in-scope、§normative section 本体 (§1〜§10 等の設計 / 採用案 / 影響範囲 / 検証手順 / 関連 ADR 等) は別 ADR review PR で実施 (本 PR の正本 source は ADR-00021 frontmatter L48-49 `§11/§12/§14` 後勝ち invariant)
- **SP-022 must_ship 表全体 rewrite** (T01-T09 詳細 + Phase G strengthening 全件): 本 PR は L74/94/104/124-126 周辺 (Phase E) + L172/187 周辺 (Phase G PGA-F-009) + L162 stale + `## Review` 追記 + frontmatter のみ、他 must_ship row + T01-T09 task list 本文は不変
- **master plan 全体 (§0〜§11 すべて)** (F-001 adopt): PR #68 で §1.1/§1.3/§4/§5/§10/§11 を update 済、本 PR では master plan を一切 touch しない。残 historical record actuals reflect (§0/§1.2/§3/§6/§7/§8/§9) は P0 Exit declaration PR で 1 回 (master plan §10-§11 update PR の Q6 default)
- **SP-022 着手 (T01-T07 + T08 + T09)**: 本 PR merge 後の SP-022 内 PR で別途実装 (本 PR は SP-022 着手 trigger のみ、実装は次 PR 群)
- **新 ADR 起票 / 新 Sprint Pack 起票**: ADR-00014/00016 等の P0.1+ ADR は本 PR と独立、SP-013+ sprint で実施。SP-018/SP-020 Sprint Pack も P0.1+ で起票予定 (本 PR では SP-022 内 Phase E trace matrix で「P0.1+ 起票予定」marker のみ)
- **SP-015 / SP-013-016/018/020 owning sprint への直接 trace 反映**: F-R2-003 + F-R2-004 adopt: SP-022 内 trace matrix で local closure し、実 trace は各 owning sprint 起票 / 着手 PR で実施 (本 PR allowlist 外、SP-015 等の file は本 PR で touch しない)
- **SP022-T07 production 実作業** (F-R2-005 adopt): Docker image build pipeline / DNS 設定 / public ingress (Funnel / Cloudflare Tunnel) / external publication / release deploy config / license 整備の本実装は SP022-T07 task 内で禁止、P3+ SP-023+ Sprint Pack で実施
- **code change**: 本 PR は docs-only、§6.3 allowlist で fail-closed verify
- **master plan §10-§11 update**: PR #68 で実施済 (本 PR の前提)

### 7.1 design accepted vs post-acceptance verification の scope 明示 (F-015 adopt)

ADR-00021 / ADR-00007 は本 PR で `status: accepted` (design accepted = 設計 / lifecycle metadata として promote 完了) するが、**post_acceptance_verification field に SP022-T09 (実機 host migration drill (Mac→VPS) RTO≤4h PASS + Tailscale 閉域維持 invariant verify) が記載済**。後続 SP-022 task の依存解釈:

| Task | Status accepted で依存可能か |
|---|---|
| **SP-022 全 must_ship task (T01-T07)** | ○ accepted で依存可能 (framework intake CI / taskhub migrate / drill SOP / Phase E closure audit-only / KPI baseline / production checklist draft / Phase G hardening は ADR-00021/00007 の design = host-portable / Tailscale 閉域 invariant に依存、本 PR の design accepted で着手可能) |
| **SP022-T08 (SP-012 §Sprint 12 Deferred 全 9 件完了)** | ○ accepted で依存可能 (SP-012 deferred items は ADR-00021 design に依存、実機 drill は T09 まで未実施でも実装可能) |
| **SP022-T09 (実機 host migration drill (Mac→VPS) PASS)** | △ post-acceptance verification independent task。SP022-T00 accepted promotion 自体が prerequisite だが、T09 自身が verification として ADR-00021/00007 の design 正しさを試す test。T09 failure 時は ADR-00021/00007 frontmatter `post_acceptance_verification` field を `failed` に update し、原因 root cause 分析 → design 修正 PR で対応 (rollback 不要、frontmatter status は accepted 維持) |
| **P0.1 unblock (TASKHUB_P0_1_OPENED=1 + SP-013 着手)** | ✗ T09 PASS が必須 gate (本 plan §1.2 路線図 + master plan §10.C-2 正本) |

つまり「design accepted = T01-T08 着手許可」「post-acceptance verification PASS = T09 で実機 drill 成功 = P0.1 unblock 許可」の 2 段 gate。本 PR では design accepted まで完了、T09 verification は SP-022 内 PR で別途実施。
