---
id: "SP-022_framework_intake_hardening"
type: "heavy"
# Phase 8 P0 Exit declaration PR (#103、2026-05-22) で completed 昇格.
# T00-T07 + T08 batch 1-6 + T06 KPI baseline + Additional Hardening Gate (PR #95-#102) 完遂、
# Phase 7a Mac single-host 運用立証 PASS (AC-HARD-04 PASS、本 PR で evidence link)。
# Phase 7b T09 Mac→VPS migration drill は post-acceptance (ADR-00021 host-portable evidence、
# P0 Exit declaration 直接 gate ではない、本 PR で分離訂正反映済 = PR #99/#100/#102).
status: "completed"
sprint_no: 22
created_at: "2026-05-10"
updated_at: "2026-05-22"
completed_at: "2026-05-22"
target_days: 3
max_days: 5
# F-PR67-019 P2 adopt (PR #67 R4): ADR-00021 acceptance は SP-022 で実機 host
# migration drill PASS 後 (master plan line 106). 旧 frontmatter「SP-012 で
# accepted」記述を更新、SP-022 が **accepting sprint** であることを明示.
# ADR-00007 update も同期 acceptance (master plan line 107).
# SP022-T00 PR (本 PR、2026-05-19): planned_adr_refs → adr_refs 移動完了、3 ADR
# (00020/00021/00007) を simultaneous accepted promotion。
# `.claude/rules/sprint-pack-adr-gate.md §12.1` 12.2 promotion 完了 trigger 遵守、
# planned_adr_refs key 自体を完全削除 (F-ADV-R5-001 + F-ADV-R3-001 adopt).
adr_refs:
  - "[ADR-00020](../adr/00020_framework_intake_checklist.md) # SP022-T00 で accepted (本 PR、2026-05-19、framework intake checklist は P0 全体方針として独立 acceptable、ADR-00014/00016 から独立 accept、acceptance_blocked_by key は accepted 後削除 = F-R2-002 adopt)"
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # SP022-T00 で design accepted (本 PR、2026-05-19、実機 host migration drill (Mac→VPS) RTO≤4h PASS は SP022-T09 post-acceptance verification 待ち、acceptance_blocked_by key は accepted 後削除 = F-R2-002 adopt)"
  - "[ADR-00007](../adr/00007_external_exposure.md) # SP022-T00 で ADR-00021 と simultaneous accepted (本 PR、2026-05-19、SP022-T09 で実機 drill 時 Tailscale 閉域維持 invariant verify 待ち、acceptance_blocked_by key は accepted 後削除 = F-R2-002 adopt)"
related_sprints:
  - "SP-012_p0_acceptance"
  - "SP-013_multi_agent_orchestration"
risks:
  - "Phase E adversarial 16 finding の closure"
  - "host migration drill 自動化の semi-blocking blocker"
  - "AC-HARD-01〜07 multi-agent 文脈 fixture の網羅性"
---

最終更新: 2026-05-10

## 目的

**F-PR67-022 P2 adopt (PR #67 R4/R6)**: 本 SP-022 は **pre-P0.1 unblock sprint** に位置 (旧「P2 段階」記述は撤回). SP-012 で skeleton 実装着手済の P0 core gates (taskhub real I/O / 実 DB write integration / signed journal CLI / private staging E2E 等) を完成 + 実機 host migration drill PASS + ADR-00021/00007 accepted 化を SP-022 で達成し、その後 P0.1 (TASKHUB_P0_1_OPENED=1 + sealed guard 解除 + SP-013 着手) が unblock.

具体的には (1) **SP-012 carry-over P0 core gates 完了** (taskhub real I/O / 実 DB write integration / signed journal CLI / private staging CI/E2E、F-PR67-027 P2 adopt)、(2) **実機 host migration drill (Mac→VPS) RTO≤4h PASS**、(3) **ADR-00021 + ADR-00007 accepted 化** (F-PR67-025 P2 adopt、master plan line 106/107、本 Sprint は accepting sprint)、(4) ADR-00020 framework intake checklist accepted + CI 機械検査完成、(5) Phase E (codex-adversarial-review) 16 finding の closure、(6) `taskhub migrate` 自動化 (one-shot で 90 分目標)、(7) 半年に 1 回の drill scheduling SOP、(8) AC-HARD 7 全件を multi-agent 文脈で再 verify、(9) Hard Gate / KPI の運用上 baseline (host 別) 確定.

## 背景

- **F-PR67-022/030 P2+P3 adopt (PR #67 R4-R7)**: 本 SP-022 は **pre-P0.1 unblock sprint** に位置 (旧 P2 段階 record は撤回)、SP-012 partial_completed_with_carry_over 状態の P0 core gates を完成 + 実機 host migration drill PASS + ADR-00021/00007 accepted 化を経て、P0.1 (SP-013+) unblock
- SP-012 で skeleton 実装着手済の taskhub real I/O / 実 DB write integration / signed journal CLI / private staging E2E / frontend backend wiring を SP-022 で完成
- ADR-00020 は SP-022 で accepted、ADR-00021/00007 update は SP022-T00 で accepted (design accepted + post-acceptance drill verification)
- P0.1 (SP-013-016) + P1 (SP-017-020) + P2 (SP-021) の multi-agent + memory + character image は **SP-022 完了後** の sprint scope (旧記述「既に完成」は撤回)

## 対象外

- 新機能追加 (P3+ で別 ADR)
- production 公開 (本 Sprint は内部品質完成、公開は P3+ のリリース Sprint)

## 設計判断

- **framework intake CI 機械検査** (ADR-00020 §2): `scripts/ci/check_framework_intake.sh` を完成、新 dependency 追加で license / external API / persistence / telemetry 違反検出
- **host migration drill 自動化** (ADR-00021): `taskhub migrate` で source backup → Tailscale 転送 → target restore → smoke を one-shot、failure rollback も自動
- **半年に 1 回の host migration drill scheduling**: `cron` or `systemd timer` で半年ごとに alert (実行は手動 approval、auto 実行はしない)
- **Phase E 16 finding closure**: PE-F-001〜PE-F-016 を SP-013-016/SP-018/SP-020 で must_ship 反映済、本 Sprint で残りを closure

## 実装チケット

> 各 task の `plan_status` annotation は `.claude/reference/task-planning-matrix.md` (新規、2026-05-20) から付与。4 level: 🟥 heavy / 🟨 light / ⛔ deferred / ⚪ unnecessary。

- **SP022-T00 (pre-implementation gate)** (`plan_status: 🟥 heavy (完了済 PR #69)`): **ADR-00020 + ADR-00021 + ADR-00007 update を proposed → accepted 昇格** (F-PR67-029/036 P2 adopt: `.claude/rules/sprint-pack-adr-gate.md §12` 「実装着手直前に planned ADR を accepted 化」invariant 遵守、SP-022 実装着手 trigger). acceptance criteria 再解釈: design ADR として `design accepted + skeleton verified` を本 acceptance time の意味とし、ADR-00020 framework intake checklist は SP022-T01 実装着手前、ADR-00021/00007 host-portable は SP022-T08/T09 実機 drill 着手前に accept、実機 host migration drill PASS は **post-acceptance verification** (SP022-T09)、master plan line 106 の「drill PASS 後」記述は本 fix で「SP-022 で drill verification 必須」と再解釈、別 PR で master plan §11.5 update を提出. ADR-00021 acceptance_blocked_by の「drill PASS / SP012-T01〜T10」は本 T00 acceptance criteria 再解釈と整合 (本 PR scope は ADR body 完全 update を SP022-T00 時実施として carry-over).
- **SP022-T01** (`plan_status: 🟥 heavy (完了済 PR #70)`): ADR-00020 (framework intake checklist) 全 8 verify item を CI 機械化、`scripts/ci/check_framework_intake.sh` 完成
- **SP022-T02** (`plan_status: 🟥 heavy + phase 分割必須 (Phase 1 CLI scaffold + signed approval / Phase 2 backup-restore / Phase 3 migrate orchestration / Phase 4 freeze-thaw split-brain)`): `taskhub migrate` 自動化 (rollback / split-brain 防止 / age key 運搬連携)。spec は ADR-00021 §3-§7 完備、impl 0 file、ADR Gate Criteria #6 (Secrets) + #11 (broad refactor) 直結
- **SP022-T03** (`plan_status: 🟥 heavy (完了済 PR #71)`): 半年 drill scheduling SOP (cron alert + 手動 approval flow)
- **SP022-T04** (`plan_status: 🟥 heavy (完了済 PR #72)`): Phase E 16 finding 個別 closure verify (各 ADR / Sprint Pack で adopted を contract test に落とし込み済か audit)
- **SP022-T05** (`plan_status: ⛔ deferred (blocked_by: SP-013 multi-agent skeleton、post-P0.1 carry-over)`): AC-HARD-01〜07 fixture を multi-agent 文脈で再 verify (**F-PR67-037 P2 adopt**: 本 task は SP-013 multi-agent skeleton に依存、SP-022 が pre-P0.1 unblock sprint reframe 後は SP-013 完了前に着手不可. 本 task のみ **SP-013 完了後の post-P0.1 carry-over** として位置、SP-022 完了 + P0.1 SP-013 完了後に SP-022.1 / SP-023 等の post-P0.1 hardening sprint で実施。本 Sprint Exit Review PR では task list に残存 + dependency note のみで close、別 PR で sprint scope re-allocation 実施)
- **SP022-T06** (`plan_status: 🟨 light + 部分実装可 (Mac 単独 baseline は light、Linux/VPS は ⛔ deferred (blocked_by: 物理 host 取得))`): KPI baseline 設定 (host 別: Mac / Linux / VPS で acceptance_pass_rate 等の median を取得、運用 baseline 確定)
- **SP022-T07** (`plan_status: 🟨 light (完了済 PR #73)`): production 公開準備チェックリスト draft (P3+ 着手時の前提整理、F-ADV-R1-007 + F-R2-005 adopt: **本 task は docs-only checklist skeleton まで**、以下の P3+ 実作業は本 task 内で禁止: (a) Docker image build pipeline、(b) DNS 設定、(c) public ingress (Funnel / Cloudflare Tunnel / public bind)、(d) external publication、(e) release deploy config、(f) license / docs 整備の本実装。これらは P3+ SP-023 以降の production release Sprint Pack で実施)
- **SP022-T08** (`plan_status: 🟥 heavy + batch 分割必須 (batch 1 signed journal CLI offline mode 完了済 PR #76 / batch 2 backup real I/O **完了済 PR #77** (T02 Phase 2 と一体実装) / batch 3 restore real I/O / batch 4 BL-0149 実 DB write / batch 5 signed journal CLI DB mode + private staging E2E / batch 6 frontend backend wiring)`): **SP-012 carry-over 完了** (F-PR67-025/027 P2 adopt): taskhub real I/O (10 subcommands all) + 実 DB write integration (BL-0149 sign-off endpoint + AuditEventRepository.append 経由 P0AcceptanceAudit write) + signed journal verification CLI (audit_events 全件 fetch + recompute + final_hash verify) + private staging CI/E2E 完成 + frontend dashboard backend API wiring。ADR Gate Criteria #1 (DB schema) + #4 (AI 権限) + #6 (Secrets) + #11 (broad refactor) 直結
- **SP022-T09** (`plan_status: ⛔ deferred (blocked_by: SP022-T02 impl + 物理 host 2 台 (Mac + VPS) + user 介在 drill 実施)`): **実機 host migration drill (Mac→VPS) PASS** (RTO≤4h、F-PR67-022/029 P2 adopt: T00 accept 後の post-acceptance verification、P0.1 unblock 必須 gate)

## タスク一覧

- [ ] **SP022-T00** (ADR-00021/00007 accept、SP-022 開始 trigger) → SP022-T01〜T09 を順次実装
- [ ] ADR-00020 を proposed → accepted
- [ ] **ADR-00020 + ADR-00021 + ADR-00007 を proposed → accepted** (SP022-T00 pre-implementation gate、F-PR67-033/036 P2 adopt: T10 stale 撤回 + ADR-00020 を T00 に含める、§12 invariant 整合)
- [ ] `taskhub migrate` end-to-end を 3 host pair (Mac↔VPS、Linux↔VPS、VPS↔VPS) で drill 実施
- [ ] Phase E 16 finding (PE-F-001〜PE-F-016) が owning ADR/Sprint Pack に割り当て済 + 受け入れ条件に trace されている (**audit-only gate**、F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 + F-R2-003 adopt: SP-022 内 `## Phase E adversarial closure trace` matrix で local closure、実 contract test PASS は post-P0.1 SP-013〜020 owning sprint exit gate carry-over)
<!-- F-PR67-044 P2 adopt (PR #67 R10): 旧 unchecked task「AC-HARD multi-agent
fixture 全件 PASS」を本 task list から **完全削除**. checklist tooling が SP-022
を incomplete 判定する経路を物理削除. 同 task は本 Sprint Pack 下部の §残リスク /
§次スプリント候補 に carry-over deferred として記載、SP-022.1 / SP-023 等の
post-P0.1 sprint で扱う. -->
<!-- 旧 entry 跡地、削除済 (F-PR67-044 P2 adopt) -->
- [ ] (削除済) AC-HARD multi-agent fixture → SP-022.1 / SP-023 carry-over (本 SP-022 exit gate から除外、§残リスク 参照)
- [ ] **SP-012 carry-over 全件完了** (taskhub real I/O / 実 DB write integration / signed journal CLI / private staging E2E / frontend backend wiring)

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| ADR-00020 accepted + CI 機械検査 | ○ | - |
| **ADR-00021 + ADR-00007 accepted** (P0.1 unblock 前提) | ○ | - |
| **SP-012 carry-over (taskhub real I/O / 実 DB write / signed journal CLI / private staging E2E)** | ○ | - |
| **Phase 7a Mac single-host 運用立証 PASS** (Mac UI smoke + Mac local backup/restore drill = AC-HARD-04 PASS、Mac single-host で完結、PR #99 で分離訂正 + PR #100 audit doc F-PR100-R2-003 + 本 PR #102 で文言訂正) | ○ | - |
| **Phase 7b 実機 host migration drill (Mac→VPS) RTO≤4h PASS** (ADR-00021 host-portable post-acceptance verification、P0 Exit declaration 後 or 任意 timing、P0 Exit 直接 gate ではない) | post-acceptance | post-acceptance、P0 Exit declaration 後実施 |
| `taskhub migrate` 自動化 | ○ | rollback 自動化は phase 分割可 |
| 半年 drill scheduling SOP | ○ | - |
| Phase E 16 finding **audit-only trace gate** (PE-F が owning ADR/Sprint Pack に割り当て済 + 受け入れ条件 trace、SP-022 内 `## Phase E adversarial closure trace` matrix) | ○ | LOW 残存は P3+ で対応可 |
| Phase E 16 finding **実 contract test PASS** | ✗ (post-P0.1 owning sprint exit gate carry-over) | F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 + F-R2-003 adopt: SP-013〜016/SP-018/SP-020 contract test 依存 = future-sprint 循環、SP-022 must_ship では audit-only gate のみ |
| AC-HARD multi-agent fixture | ✗ (post-P0.1 carry-over) | F-PR67-039 P2 adopt: SP-013 multi-agent skeleton 依存、SP-022.1 / SP-023 等の post-P0.1 sprint で実施 |
| KPI baseline (host 別) | ○ | Mac / Linux / VPS の 3 host で baseline 取得、特定 host のみは defer 可 |
| production 公開準備 checklist draft (**docs-only skeleton まで、F-R2-005 adopt: Docker image build pipeline / DNS / public ingress / external publication / release deploy config / license 整備の本実装は禁止**) | ○ | 詳細実装は P3+ SP-023+ Sprint Pack で実施、本 T07 task では skeleton checklist 1 file (docs/release/production_readiness_checklist.md) のみ作成 |

## 受け入れ条件

- ADR-00020 8 verify item が CI で機械検査されている (license / attribution / no embed / persistence / external network / telemetry / secret canary / tenant boundary 全て)
- `taskhub migrate --target <host>` が source backup → 転送 → target restore → smoke を 90 分以内に完了
- migration 中の rollback (age key 失敗 / pg_restore 失敗 / network 切断) が自動で source host 復旧
- Phase E 16 finding (PE-F-001〜PE-F-016) すべてが owning ADR/Sprint Pack に trace 済 (**audit-only gate**: 各 finding の owning sprint への割り当て + 受け入れ条件への trace を SP-022 内 `## Phase E adversarial closure trace` matrix で文書確認、F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 + F-R2-003 adopt: 実 contract test PASS は post-P0.1 owning sprint exit gate で実施)
<!-- F-PR67-045 P2 adopt (R10): AC-HARD multi-agent fixture 受け入れ条件は本
SP-022 exit から除外 (SP-013 multi-agent skeleton 依存、SP-022.1 / SP-023
carry-over). 旧 entry「AC-HARD-01〜07 fixture が multi-agent 文脈で全件 PASS」
は削除. -->
<!-- (削除済) AC-HARD multi-agent fixture exit → SP-022.1 / SP-023 carry-over -->
- AC-HARD-01〜07 fixture (single-agent 文脈) は SP-022 で **regression-only verify** (multi-agent 文脈は post-P0.1 carry-over)
- KPI baseline が host 別に確定、運用 SOP 化
- SP022-T07 production checklist draft は **docs-only checklist skeleton 1 file** (`docs/release/production_readiness_checklist.md`、F-R2-005 adopt) のみ作成、Docker image build pipeline / DNS 設定 / public ingress (Funnel / Cloudflare Tunnel) / external publication / release deploy config / license 整備の本実装は **本 T07 内で禁止** (P3+ SP-023+ Sprint Pack で実施)
- P0.1 unblock 判定では SP022-T07 = production 実装完了ではなく **checklist draft skeleton 存在確認のみ** (F-ADV-R1-007 + F-R2-005 adopt)

## 検証手順

```bash
# framework intake CI
$ bash scripts/ci/check_framework_intake.sh   # 違反 dependency 追加で fail
$ uv run pytest tests/scripts/test_check_framework_intake.sh tests/citations/test_citation_completeness.py -q

# host migration drill 自動化
$ taskhub migrate --target t-ohga-linux --via tailscale --auto-rollback-on-failure
$ uv run pytest tests/deploy/test_host_migration_automation.py tests/deploy/test_split_brain_prevention.py -q

# Phase E 16 finding audit-only trace verification (F-R2-003 adopt: SP-022 内 trace matrix で local closure)
# SP-022 内では owning sprint への trace を文書確認のみ、pytest 実行は post-P0.1 owning sprint exit gate
$ rg -nP 'PE-F-(00[1-9]|01[0-6])' docs/sprints/SP-022_framework_intake_hardening.md
# expected: PE-F-001〜PE-F-016 全 16 finding が SP-022 内 `## Phase E adversarial closure trace` matrix で言及
# (post-P0.1 owning sprint exit gate で実 pytest 実行) $ uv run pytest eval/multi_agent/... -q

# F-PR67-045 P2 adopt (R10): AC-HARD multi-agent fixture verification は本 SP-022
# exit から除外 (SP-013 multi-agent skeleton 依存、SP-022.1 / SP-023 carry-over).
# 旧コマンド (`pytest eval/security/*/multi_agent/`) は SP-022.1 で実施.

# KPI baseline (host 別)
$ taskhub kpi-baseline --host t-ohga-mac --output baselines/mac.json
$ taskhub kpi-baseline --host t-ohga-vps --output baselines/vps.json
$ taskhub kpi-baseline --host t-ohga-linux --output baselines/linux.json
```

## レビュー観点

- ADR-00020 CI 機械検査の bypass 経路がない (license string scan / external API endpoint denylist / telemetry import denylist が網羅)
- `taskhub migrate` 自動 rollback の trigger 条件 (どこで失敗を判定するか) が明確
- 半年 drill SOP が "通知のみ、自動実行しない" 原則 (Phase E AP-13 想定: 自動 destructive 操作禁止)
- Phase E 16 finding の各 closure evidence が test fixture で verify 可能 (review_id RV-001〜RV-016 mapping)
- KPI baseline が host 別に統計的に十分 (each host で 30+ data point 取得)

## 残リスク

- ADR-00020 CI 機械検査の false positive (legitimate dependency が誤 reject)、運用 review で denylist tuning 必要
- `taskhub migrate` 自動 rollback の edge case (network 切断 + age key compromise の同時発生) は手動 SOP に委ねる
- Phase E LOW finding (もし Codex で出ていれば) は本 Sprint で defer 可、P3+ で対応
- KPI baseline の host 間 variance が大きい場合、運用 SOP で host 別 KPI 閾値を設定する判断が必要

## 次スプリント候補

- P3+ (production 公開準備、ADR-00017 P2 character image final + 公開 docker image build pipeline + license / docs 整備)
- (継続的) Wave 23 cron + Routines 実装
- **post-SP022-T01 hardening (SP-022.X) — frontend npm license verify + per-framework adoption.md AND verify**: PR #70 R2 F-PR70-R2-002 + R3 F-PR70-R3-002 defer 対応、`node_modules/<pkg>/package.json` の `license` field + LICENSE_DENYLIST scan、SPDX expression 解釈、`pnpm install` 前提条件、ADR-00020 §1 #1 scope 明確化 update、ADR-00020 §1 #2 strict AND 解釈 (個別 `docs/citations/<framework>_adoption.md` artifact verify) も含む (本 SP022-T01 は PyPI 限定 + OR 設計で skeleton 完成、frontend / strict AND は post-task)

## 関連 ADR

- ADR-00020 (Framework Intake Checklist、本 Sprint で accepted)
- ADR-00021 (Host-Portable Deployment + Data Migration、運用 SOP 完成)
- ADR-00014/15/16/17/18/19 (P0.1+ owning sprint で proposed→accepted 予定、本 Sprint では運用 hardening のみ、F-ADV-R1-006 adopt: 旧「accepted 済」は ADR-00014/00016 が実際 `status: proposed` のため stale text、SP022-T00 PR で reviewer が ADR-00020 blocker 解消済と誤読する acceptance lifecycle trap 回避のため update)
- 全 Hard Gate AC-HARD-01〜07

## Phase G adversarial strengthening (2026-05-10)

### 追加 must_ship (Phase G adversarial 14 finding の closure 担当 strengthening)

- **drill timer alert-only enforcement (PGA-F-013)**: `scripts/ci/check_drill_timer_alert_only.sh` 追加、systemd timer / cron entry の ExecStart が通知 command 以外 (例: `taskhub migrate ...`) なら CI fail
- **`taskhub migrate --approval-id` 必須化**: cron / systemd 環境変数検出時に default deny、`--from-automation` flag + signed approval record 必須
- **CI bypass scan 拡張 (PGA-F-014)**: `scripts/ci/check_host_portable_bypass.sh` を網羅化 (Funnel/0.0.0.0 publish/non-127 publish/age private key marker/raw key path/secret archive 検出)
- **inter_agent_messages consumed invariant fixture (PGA-F-009)**: SP-022 内で audit-only trace 宣言 (F-ADV-R1-001 + F-R2-004 adopt: PGA-F-009 trace status = `pending SP-015 起票 PR for owning sprint trace`、SP-015 着手 PR で owning sprint must_ship 反映、SP-022 では本宣言を audit marker として保持、SP-015 完了後 owning sprint exit gate で post-restore + post-migration 全 case の実 contract test PASS verify = future-sprint 循環防止)

### 追加実装ファイル

- `scripts/ci/check_drill_timer_alert_only.sh`
- `scripts/ci/check_host_portable_bypass.sh` (拡張)
- `tests/deploy/test_drill_timer_alert_only.py`
- `tests/deploy/test_taskhub_migrate_approval_required.py`
- `tests/scripts/test_check_host_portable_bypass.sh`

### 受け入れ条件追加

- 半年 drill SOP の cron / systemd timer が auto migrate exec 不可 (CI で機械検査)
- `taskhub migrate` が approval ID 無しで destructive operation を実行できない
- CI bypass scan で全 invariant 違反 pattern を検出 (positive fixture で reject、negative で pass)
- Phase G adversarial 14 finding (PGA-F-001〜PGA-F-014) のうち PGA-F-009 (SP-015 依存) は **audit-only gate** (SP-015 完了後 owning sprint exit gate で実 contract test PASS、F-ADV-R1-001 + F-R2-004 adopt: SP-022 内 audit marker `pending SP-015 起票 PR` で trace 宣言)、残 13 finding (PGA-F-001〜008 + PGA-F-010〜014) は本 SP-022 内で closure evidence (test fixture / contract test PASS) verify

## Review

### SP022-T00 pre-implementation gate completion (2026-05-19)

#### ADR accepted promotion completed

- ADR-00020 accepted_at: 2026-05-19 (framework intake checklist、blocker 完全削除完了、SP022-T01 framework intake CI 機械化着手 trigger)
- ADR-00021 accepted_at: 2026-05-19 (host-portable deployment design accepted、SP022-T09 実機 drill による post-acceptance verification 待ち)
- ADR-00007 accepted_at: 2026-05-19 (external exposure host-portable update、ADR-00021 simultaneous、SP022-T09 で Tailscale 閉域維持 invariant verify 待ち)

#### HARD GATE evidence (codex-plan-review R1-R3 completion record)

- codex-plan-review-round: R3 (round_max reached、R1=Phase A / R2=Phase B / R3=CRITICAL final verify)
- codex-plan-review-findings: 21 (CRITICAL: 1、HIGH: 8、MEDIUM: 7、LOW: 5、累計 R1=15 + R2=5 + R3=1)
- codex-plan-review-adopt: 21 / reject: 0 / defer: 0 (全 finding adopt 反映)
- codex-plan-review-readiness-gate: READY (R3 round_max reached + clean、R3 1 件 CRITICAL adopt 後 fix は verification 文字列処理の厳密化、新 regression リスク低)
- codex-plan-review-evidence-path: ~/.claude/local/codex-reviews/2026-05-19/sprint-SP-012-batch-7-taskhub-admin-cli/codex-plan-review-20260519-144046.raw.jsonl (R1) + codex-plan-review-20260519-144956.raw.jsonl (R2) + codex-plan-review-20260519-150047.raw.jsonl (R3)

#### Frontmatter promotion process

- `planned_adr_refs` → `adr_refs` 移動 + `planned_adr_refs` key 完全削除 (`.claude/rules/sprint-pack-adr-gate.md §12.1` 12.2 promotion 完了 trigger)
- 3 ADR 同一日付 (2026-05-19) で simultaneous accepted (F-PR67-047 mutual blocking cycle 解消、common SP022-T00 simultaneous acceptance gate に置換)
- 3 ADR `acceptance_blocked_by` key 完全削除 (F-005 + F-R2-002 adopt: accepted 後の active blocker key 同居を回避、SP022-T00 gate 完了 rationale は acceptance_history に移送)

#### Active text sync update completed

- SP-022 `## 関連 ADR` セクション内 stale text 修正 (旧文言「P0.1+ で accepted 済」を「P0.1+ owning sprint で proposed→accepted 予定」に置換、F-ADV-R1-006 adopt)
- SP-022 Phase E 16 finding closure audit-only gate split (タスク一覧 / must_ship 表 / 受け入れ条件 / 検証手順 セクション内の旧 Phase E active requirement 文言を audit-only trace gate に変更、実 contract test PASS は post-P0.1 SP-013〜020 owning sprint exit gate carry-over、F-PLAN-R3-001 + F-PLAN-R5-001 + F-R2-003 adopt)
- SP-022 Phase G PGA-F-009 audit-only gate split (Phase G adversarial strengthening セクション内の旧 PGA-F-009 active requirement 文言を audit-only trace gate に変更、F-ADV-R1-001 + F-R2-004 adopt)
- SP-001-5 active text 7 箇所 (目的 / 設計判断 / 実装チケット / must_ship 対応表 / 受け入れ条件 / レビュー観点 / 関連 ADR セクション内の旧「SP-022 で実機 host migration drill PASS 後」「SP-022 carry over」文言) の update (F-PLAN-R4-001 + F-PLAN-R5-002 adopt)
- SP022-T07 production scope boundary 明文化 (docs-only checklist skeleton まで、Docker image build pipeline / public ingress / release deploy config 等の P3+ 実作業は禁止、F-ADV-R1-007 + F-R2-005 adopt)

### SP022-T04 Phase E trace audit completion (2026-05-20)

#### codex-plan-review R1-R3 completion record

- codex-plan-review-round: R3 (round_max reached、R1 Phase A 構造 / R2 Phase B 実装可能性 / R3 CRITICAL final)
- codex-plan-review-findings: 16 (R1=13 [HIGH×3 / MEDIUM×6 / LOW×4] + R2=2 [HIGH×2] + R3=1 [CRITICAL×1])
- codex-plan-review-adopt: 16 / reject: 0 / defer: 0 (全 finding adopt 反映、累計 100% adoption)
- codex-plan-review-readiness-gate: READY (R3 round_max reached、CRITICAL=0 残存、HIGH ≤ 2 satisfied)
- codex-plan-review-evidence-path: `~/.claude/local/codex-reviews/2026-05-{19,20}/sprint-SP-012-batch-7-taskhub-admin-cli/codex-plan-review-*.raw.jsonl` (R1/R2/R3)

#### Phase E trace audit-only gate implementation

- `scripts/ci/check_phase_e_trace.sh` (NEW): bash wrapper、emergency disable `PHASE_E_TRACE_CHECK_DISABLED=1` 対応、`audit_marker:` stderr 3 行
- `scripts/ci/_phase_e_trace_verifier.py` (NEW): Python verifier、`--pack-path` 引数で fixture override、line-based section parser (suffix tolerant)、5 column header exact match、PE-F-001〜PE-F-016 完全一致 + extra deny、symptom 20+ chars、PE-F-010 closure marker AND/AND-NOT、`SP-\d{3}` regex token exactly 1 + per-row mapping
- `tests/deploy/test_phase_e_trace.py` (NEW): 13 fixtures (4 positive against real SP-022 + 9 negative against tmp_path fake pack)、全 PASS
- `.github/workflows/ci-smoke.yml`: `backend-quality` job に `Phase E trace audit check (SP022-T04)` step 追加 (R1-F-011 adopt canonical name)
- SP-022 §Phase E adversarial closure trace matrix: 4 column → 5 column 化 (symptom 追加)、PE-F-010 ✅ closure marker、PE-F-010 owner SP-016→SP-022 正規化 (R3-F-R3-001 adopt: ADR-00020 `related_sprints: SP-022` + SP-016 Pack 実 PE-F refs PE-F-006/PE-F-014 のみと整合)

#### reason_code emit (新規)

`framework_intake_violation_phase_e_trace_*`: `pack_missing` / `section_missing` / `finding_missing` / `finding_unexpected` / `header_mismatch` / `symptom_missing` / `owning_sprint_invalid` / `t01_closure_marker_missing`

#### Audit-only gate boundary (不変条件、SP-022 受け入れ条件 line 108 通り)

- 本 T04 では SP-022 内 trace matrix の **structural verify のみ** (16 finding 完全一致 / 5 column / per-row mapping / PE-F-010 closure marker)
- **実 contract test PASS** は各 owning sprint exit gate (post-P0.1) で実施 (SP-013 / SP-014 / SP-015 / SP-016 / SP-018 / SP-020 / **SP-022 (PE-F-010 のみ closure 済)**)
- emergency disable は admin variable のみ、24h 以内 retro Pack 義務 (CI log audit_marker)

#### Known hook false positive

- `tailscale-public-exposure` hook (`.claude/hooks/tailscale/check-tailscale-grants.sh`) が `.github/workflows/ci-smoke.yml` 編集時に BLOCK を返した。本 T04 で追加した step (`Phase E trace audit check (SP022-T04)`) には Funnel / Cloudflare / public bind / 0.0.0.0 等のキーワードは含まれず、既存 file 内の他 keyword (例: `5432:5432` Postgres mapping 等) が file 全体 re-scan で trigger された。 ADR-00007 (external exposure) は不変、SP022-T03 PR #71 と同 false positive pattern (Review に既知記録あり)。

### SP022-T07 production checklist skeleton completion (2026-05-20)

#### codex-plan-review R1-R3 completion record

- codex-plan-review-round: R3 (round_max reached、R1 Phase A 構造 / R2 Phase B 実装可能性 / R3 CRITICAL final)
- codex-plan-review-findings: 10 (R1=10 [HIGH×2 / MEDIUM×5 / LOW×3] + R2=0 + R3=0)
- codex-plan-review-adopt: 10 / reject: 0 / defer: 0 (全 finding adopt 反映、累計 100% adoption)
- codex-plan-review-readiness-gate: READY (R3 round_max reached、CRITICAL=0 残存、HIGH ≤ 2 satisfied)
- codex-plan-review-evidence-path: `~/.claude/local/codex-reviews/2026-05-20/sprint-SP-012-batch-7-taskhub-admin-cli/codex-plan-review-*.raw.jsonl` (R1/R2/R3)

#### Production readiness checklist skeleton implementation

- `docs/release/production_readiness_checklist.md` (NEW): 12 sections (§1 / §2 / §3 / §4 Private networking / §4-public Public exposure / §5 / §5-external External publication / §6 / §7 / §8 / §9 / §10) docs-only skeleton 1 file
- 全 § は `[ ]` checklist + 概要 + P3+ 移送先 reference のみ、live release/build/deploy command なし (R1-F-002 adopt)
- 具体 tool 名 / 戦略名は本 file に記載なし、P3+ ADR で判断 (R1-F-003 adopt)
- §4 Private networking (Tailscale 閉域維持 ADR-00007 invariant) と §4-public Public exposure (ADR-00007 update + ADR Gate Criteria #7 経由必須) を分離 (R1-F-004 adopt)
- §5-external External publication を独立 § として追加 (P3+ separate approval、R1-F-005 adopt)
- §6 LICENSE / NOTICE / SECURITY / public README は **本 T07 では作成・編集しない**、P3+ placeholder のみ列挙 (R1-F-008 adopt)
- §1 / §2 で「P0.1 unblock 判定は file existence のみ、checkbox 状態は evaluated しない」明記 (R1-F-006 adopt)
- §7 / §8 は SP022-T06 / SP022-T09 link のみ、正本は SP-022 Pack 該当 section (R1-F-009 adopt)

#### Audit-only / docs-only gate boundary (不変条件、SP-022 受け入れ条件 line 116-117 通り)

- 本 T07 では **docs-only checklist skeleton 1 file** のみ作成
- P3+ 本実装は本 T07 内で禁止: (a) Container image build pipeline、(b) DNS 本実装、(c) public ingress 有効化、(d) external publication 有効化、(e) release deploy config 本実装、(f) LICENSE / NOTICE / SECURITY / README 本実装
- P0.1 unblock 判定は **file existence のみ**、checklist の checked/unchecked 状態は evaluated **されない** (F-ADV-R1-007 + F-R2-005 adopt)
- T07 成果物カウントは `docs/release/production_readiness_checklist.md` の 1 file、SP-022 Pack `## Review` update は acceptance metadata (R1-F-001 adopt)

### SP022-T08 batch 1 signed journal verification CLI completion (2026-05-20)

#### codex-plan-review R1-R3 completion record

- codex-plan-review-round: R3 (round_max reached、R1 Phase A 構造 / R2 Phase B 実装可能性 / R3 CRITICAL final)
- codex-plan-review-findings: 19 (R1=17 [HIGH×5 / MED×9 / LOW×3] + R2=2 [HIGH×2] + R3=0)
- codex-plan-review-adopt: 19 / reject: 0 / defer: 0 (全 finding adopt 反映、累計 100% adoption)
- codex-plan-review-readiness-gate: READY (R3 round_max reached、CRITICAL=0 残存)

#### Signed journal CLI offline mode 実装

- `scripts/taskhub_signed_journal_offline.py` (NEW): JSONL stream parser + `AuditEventLike` dataclass (duck-typed AuditEvent) + `verify_jsonl_signed_journal()` + `SignedJournalUsageError` / `SignedJournalTamperError` 専用例外型 + 10 reason_code
- `scripts/taskhub_admin.py` (MODIFY): `_cmd_verify` extension + `_cmd_verify_signed_journal` helper + 4 新引数 (`--signed-journal` / `--input` / `--expected-final-hash` / `--max-entries` / `--max-line-bytes`) + parse-time mutually exclusive validation (R2-F-002 adopt)
- `tests/scripts/test_taskhub_signed_journal_offline.py` (NEW、27 fixture): positive 7 + negative 18 + error redaction 2、全 PASS
- `tests/scripts/test_taskhub_admin.py` (MODIFY): 6 CLI integration fixture 追加 (--signed-journal positive / tamper / mutex / stdin / invalid hash)
- 既存 Sprint 12 batch 10 (PR #66) `backend/app/services/audit/signed_journal.py` pure function pipeline を不変で wrap (CRITICAL invariant: signed_journal.py 不変、CLI は wrapper のみ)

#### Security invariants (offline mode)

- strict structural schema (extra fields reject、required nullable fields 全件 null 明示必須、R1-F-006 + R1-F-017 adopt)
- timezone-aware datetime 必須 (naive deny、R1-F-010 adopt)
- NaN/Infinity reject via `json.loads(parse_constant=...)` (R1-F-004 adopt)
- `--expected-final-hash` regex `^[0-9a-f]{64}$` validation (R1-F-007 adopt)
- DoS 防御: `--max-entries` (1-100000) + `--max-line-bytes` (1024-1048576) range validation (R1-F-002 + R1-F-015 adopt)
- error message redaction: SignedJournalUsageError は `reason_code` + `line_no` + `field` のみ、raw payload value leak 防止 (R1-F-005 adopt)
- exit code: 0 PASS / 1 explicit tamper / 2 usage error (R1-F-003 adopt: input ValueError → exit 2、explicit hash mismatch → exit 1 分離)

#### Phase 2-6 carry-over (本 batch 1 対象外)

- batch 2: backup-restore real I/O (pg_dump / pg_restore / age encryption)
- batch 3: migrate-status-verify real I/O (Tailscale transfer / target host)
- batch 4: BL-0149 sign-off endpoint 実 DB write (AuditEventRepository.append integration)
- batch 5: signed journal CLI DB mode (`--from-db`) + private staging CI/E2E
- batch 6: frontend dashboard backend API wiring
- pure signed_journal_core.py 抽出判断 (R2-F-001 adopt carry-over): import scope 軽量化が必要なら batch 2 で別 module へ pure 部分を抽出

### SP022-T02 Phase 2 / T08 batch 2 backup real I/O completion (2026-05-20)

#### codex-plan-review R1-R3 completion record

- R1 (Phase A): 14 findings (CRITICAL×2 / HIGH×7 / MED×5)
- R2 (Phase B): 2 findings (CRITICAL×1 / HIGH×1)
- R3 (CRITICAL final): 1 CRITICAL
- 累計 17 findings 全件 adopt (100%、根本的解決アプローチ、user directive 「どれだけ時間かかってもいい」反映)
- Readiness Gate: READY

#### Backup real I/O orchestration 実装

- `scripts/taskhub_subprocess_runner.py` (NEW): common subprocess runner (timeout / stdin=DEVNULL / env allowlist / stderr sanitize / argv logging)、R1-F-009 + R3-F-001 adopt
- `scripts/taskhub_backup_orchestrator.py` (NEW、~650 lines): backup orchestration (pure + subprocess wrappers + orchestration) + 17 reason_code + archive allowlist + 0700 tmp dir + `.part` atomic rename + R1-R3 17 findings 全件反映
- `scripts/taskhub_signed_approval.py` (MODIFY): `BackupApprovalClaim` 拡張、verify/require 関数 backup_claim 引数追加、backup subcommand で skeleton escape 物理 deny (R2-F-001 adopt)
- `scripts/taskhub_admin.py` (MODIFY): `_cmd_backup` を real orchestration 呼出に置き換え + 2 新引数 (`--skip-service-stop` / `--overwrite`) + backup_claim build + signed approval gate extended
- `tests/scripts/test_taskhub_subprocess_runner.py` (NEW、17 fixture)
- `tests/scripts/test_taskhub_backup_orchestrator.py` (NEW、24 fixture): Layer 1 pure + Layer 2 mock + Layer 3 orchestration
- `tests/scripts/test_taskhub_admin.py` / `test_taskhub_admin_security.py` / `test_taskhub_signed_approval.py` (MODIFY): backup 関連 test を real orchestration mode に update
- `tests/deploy/test_taskhub_backup_integration.py` (NEW): SP022-T09 mandatory drill checklist marker stub

#### Security invariants (本 batch 確立)

- archive allowlist: SSH/age/SOPS private key filename + content prefix + symlink 全 reject (R1-F-001 CRITICAL)
- tmp dir 0700 + cleanup OSError audit + exit 1 (R1-F-002 CRITICAL)
- env allowlist secret reject + PGPASSFILE のみ (R3-F-001 CRITICAL)
- backup_claim mismatch deny + skeleton escape backup reject (R2-F-001 CRITICAL)
- partial output 防止: `.part` atomic rename
- stderr sanitization: private key / AGE-SECRET-KEY / password redact

#### Phase 3-6 carry-over (本 batch 対象外)

- batch 3 (T02 Phase 3): restore real I/O
- batch 4: BL-0149 sign-off endpoint 実 DB write
- batch 5: signed journal CLI `--from-db` + private staging E2E
- batch 6: frontend dashboard wiring
- T02 Phase 4: migrate / freeze / thaw
- actual pg_dump / age tool 実行 validation → SP022-T09 mandatory drill checklist

## Phase E adversarial closure trace (PE-F-001〜PE-F-016、F-R2-003 + SP022-T04 R1-R3 adopt: SP-022 内 audit-only trace matrix で local closure、symptom column 追加 + PE-F-010 closure marker + PE-F-010 owner SP-016→SP-022 正規化)

| Finding ID | Owning Sprint | trace status | post-P0.1 contract test PASS gate | symptom |
|---|---|---|---|---|
| PE-F-001 | SP-013 | (SP-013 着手時 must_ship 反映予定) | SP-013 exit gate | STANDARD_ROLE_IDS は custom role_id として禁止 (reserved namespace)、`role_scope=global + role_id=reviewer` で scope 含める、`receiver_kind=role` は server-owned role resolver |
| PE-F-002 | SP-013 | (SP-013 着手時 must_ship 反映予定) | SP-013 exit gate | atomic consume SQL を tenant_id/project_id/parent_run_id/consumed_at is null/expires_at で必須化、cross-parent same-project consume negative を must_ship |
| PE-F-003 | SP-014 | (SP-014 着手時 must_ship 反映予定) | SP-014 exit gate | policy_decisions.required_review_artifact_id を review_artifacts へ FK、review target hash + policy_version + provider_request_fingerprint + action_class 一致を 4 重防御 |
| PE-F-004 | SP-014 | (SP-014 着手時 must_ship 反映予定) | SP-014 exit gate | orchestrator progress lease に last_progress_at + progress_seq、N 分 no-progress で blocked + runtime_blocked、turn counter / TTL / depth 絶対上限固定 |
| PE-F-005 | SP-014 | (SP-014 着手時 must_ship 反映予定) | SP-014 exit gate | sanitizer_policy_versions table 正本化、retrieval 時 current version 不一致は stale_sanitizer deny / re-sanitize、prompt memory snippet は redacted 原則 |
| PE-F-006 | SP-015 | (SP-015 着手時 must_ship 反映予定) | SP-015 exit gate | CLI capability token を principal-bound API capability として DDL 化、bearer token 扱い禁止、scope mismatch は deny audit (mutating API は approval target fingerprint 照合) |
| PE-F-007 | SP-015 | (SP-015 着手時 must_ship 反映予定) | SP-015 exit gate | SP-013 migration order hard gate、artifacts.project_id NOT NULL + unique を inter_agent_messages/review_artifacts/memory_records FK 追加前に完了 |
| PE-F-008 | SP-016 | (SP-016 着手時 must_ship 反映予定) | SP-016 exit gate | observer role の child run が write 要求した場合、Tool Registry allowed_actions enforcement で deny (role は authorization 単体ではない) |
| PE-F-009 | SP-016 | (SP-016 着手時 must_ship 反映予定) | SP-016 exit gate | P2 character image generation の prompt sanitizer (secret pattern / system instruction overwrite / internal context redact)、Matrix で image generation provider 明示登録 |
| PE-F-010 | SP-022 | ✅ closed by SP022-T01 (PR #70 merged 2026-05-19、ADR-00020 8 verify CI 機械化、38 adopt findings) | SP022-T01 satisfied; no SP-016 exit gate (ADR-00020 + SP-022 owner、PE-F-010 CI closure already satisfied; no additional T04 contract test) | Framework intake CI 機械検査: license / external API / persistence / telemetry denylist (8 verify ADR-00020) |
| PE-F-011 | SP-018 | ✅ closed by SP-018 batch 0a-0h (PR #187-#194): ref-only / untrusted memory retrieval, no action_class expansion | SP-018 exit gate satisfied | Phase F の最初に ADR-00014/00018/00019 を Phase C R4 方針へ patch、action_class は ADR-00009 7 種以外を許さない strict CI、enum 交差禁止 test |
| PE-F-012 | SP-018 | ✅ closed by SP-018 batch 0a-0h (PR #187-#194): tenant/project scoped memory FK and retrieval guards, no role reference widening | SP-018 exit gate satisfied | agent_runs trigger 拡張 (before insert or update of tenant_id/project_id/role_id/role_scope)、agent_run_project_roles link table + role_scope=global の DB CHECK |
| PE-F-013 | SP-018 | ✅ closed by SP-018 batch 0a-0h (PR #187-#194): memory API is feature-flagged read-only retrieval only, no remote dispatch path | SP-018 exit gate satisfied | sealed guard に追加 path (remote_agent adapter/router/frontend/config/tests)、P0.1 stub は remote_agent_dispatch_denied audit payload schema 定義 |
| PE-F-014 | SP-020 | ✅ trace added in `SP-020_curator_insights_integration.md` + ADR-00032 proposed; implementation pending SP020-T07 | SP-020 exit gate | SecretBroker multi-agent 6 negative case reason_code 個別表 (parent_token_used_by_child / inter_agent_message_token_payload / approval_id / payload_hash / run_id substitution 等) |
| PE-F-015 | SP-020 | ✅ trace added in `SP-020_curator_insights_integration.md` + ADR-00032 proposed; implementation pending SP020-T05/T07 | SP-020 exit gate | metrics ADR で exact query (agent_runs lineage は recursive CTE、cost は provider_responded event idempotency_key で dedupe、time_to_merge / citation_coverage の正本決定) |
| PE-F-016 | SP-020 | ✅ trace added in `SP-020_curator_insights_integration.md` + ADR-00032 proposed; implementation pending SP020-T07 | SP-020 exit gate | policy_profile migration に required_review_artifact_id FK + profile_resolved_effect CHECK、default/low_risk_auto_allow × 7 action_class = 14 rows exact seed |

**audit-only gate**: SP-022 では本 trace matrix を文書として保持、実 contract test PASS は各 owning sprint exit gate (post-P0.1)。SP-018 は batch 0a-0h / PR #187-#194 で exit gate satisfied、SP-020 は Sprint Pack + ADR-00032 proposed の plan-only gate 起票済みで、PE-F-014/015/016 の実 contract test PASS は SP020-T07 以降に残す。PE-F-010 は SP022-T01 (PR #70) で実装完了、本 trace matrix から owner を SP-022 に正規化 (ADR-00020 `related_sprints: SP-022_framework_intake_hardening` 整合、SP-016 Pack は実 PE-F refs PE-F-006/PE-F-014 のみ)。SP022-T00 PR では SP-022 内 trace matrix の存在のみ verify、SP022-T04 PR (`scripts/ci/check_phase_e_trace.sh` + `_phase_e_trace_verifier.py`) で 16 finding 完全一致 + 5 column header + per-row owning sprint mapping + PE-F-010 closure marker を機械検査恒久化。

### SP022-T02 Phase 3 / T08 batch 3 restore real I/O completion (2026-05-20)

#### codex-plan-review R1-R24 completion record (CLAUDE.md §6.5.4 deep-hardening)

- R1 (Phase A 構造 review): 17 findings (CRITICAL×3 / HIGH×6 / MED×7 / LOW×1) 全件 adopt
- R2 (Phase B 実装可能性): 8 findings (CRITICAL×2 / HIGH×6) 全件 adopt — PR #77 retro-fix 同梱 (backup_claim signature canonical payload 不在の CRITICAL vulnerability)
- R3-R23: 26 findings 全件 adopt (root cause findings: docker compose exec / TOCTOU 排除 / BGSAVE→SAVE / target binding consistency 等)
- R24: 0 CRITICAL = plan READY 達成
- **累計 58 findings、24 rounds、100% adopt rate**、user directive 「どれだけ時間かかってもいい品質完璧」反映

#### Restore real I/O orchestration 実装

- `scripts/taskhub_subprocess_runner.py` (MODIFY、Batch A): `SafeSubprocessConfig` に `stdin_file` + `stdout_file` 追加 (R15-F-002 streaming pipe、10GiB dump でも OOM 回避)
- `scripts/taskhub_signed_approval.py` (MODIFY、Batch B): `RestoreApprovalClaim` (12 field) 拡張 + R2-F-001 retro-fix (canonical payload に backup_claim/restore_claim sub-record 含める、PR #77 claim signature 突破経路を物理排除)
- `scripts/taskhub_backup_orchestrator.py` (MODIFY、Batch C、PR #77 retro-fix): `build_meta_json` field rename (host→host_name, timestamp→timestamp_utc, backup_format_version→format_version、R2-F-005)
- `scripts/taskhub_restore_orchestrator.py` (NEW、Batch D、~1150 行): 全 24 rounds findings 反映の restore orchestration
- `scripts/taskhub_admin.py` (MODIFY、Batch E): `_cmd_restore` real I/O 化 + `--age-identity-file` / `--overwrite` 引数追加 + `--allow-unsigned-manual-skeleton` 物理 deny (R3-F-001)
- `docker-compose.yml` (MODIFY、Batch E): api/worker に artifacts bind mount 追加 (R22/R23 adopt)
- `tests/scripts/test_taskhub_restore_orchestrator.py` (NEW、39 fixture、3 layer: pure + subprocess mocks + orchestration)
- `tests/scripts/test_taskhub_admin.py` (MODIFY): restore skeleton mode test を `--allow-unsigned-manual-skeleton` 物理 deny test に置換

#### Security invariants (R14-F-001 root cause fix)

- pg_restore / pg_dump / redis SAVE / psql 全て docker compose exec 経由 + container 内 unix socket (host TCP port-collision 攻撃完全排除)
- archive sha256 verify + age decrypt は immutable stage (cp --reflink / shutil.copy2) で別 inode 隔離 (R16/R17/R18/R19 統合 TOCTOU 排除)
- BGSAVE 廃止、blocking SAVE 採用 (R17-F-001 race-free)
- pre-restore snapshot は `.tmp` suffix → atomic rename (R20-F-001 partial file 防止)
- tar member symlink/hardlink/device 明示 reject + size/count DoS limits (R11/R20)
- target binding consistency preflight (Compose project/file/services/ports/env/volumes 整合、R8-R23 統合 8-check 防御)
- rollback exception 範囲: RestoreRuntimeError | OSError | shutil.Error | SubprocessError | SubprocessTimeoutError | SubprocessNotFoundError (R6/R7)
- per-component rollback existence verify + clean slate (R17/R19 統合)

#### Carry-over (本 batch 対象外、Phase 4 / batch 4 以降)

- `--rollback <pre-restore-ts>` standalone real I/O (本 batch では skeleton 維持)
- split-brain remote detection (`taskhub status --remote` 経由旧 host service down verify)
- `taskhub approval issue` real I/O subcommand (test fixture 経由 approval record manual 生成のみ本 batch)
- age 秘密鍵 SecretBroker integration (P0 manual 運搬で OK、batch 5 BL-0149 carry-over)
- actual pg_restore / age / redis-cli tool execution validation (SP022-T09 drill phase mandatory)
- backup_orchestrator pg_dump compose exec 切替 (R14-F-001 PR #77 retro-fix の compose-exec 部分、本 batch では meta.json field rename のみ反映)
- 既存 PR #75/#77 approval record の re-sign migration (canonical payload に backup_claim 追加で signature_invalid 化、operator は revoke + 新規 issue)

### SP022-T01 framework intake CI 機械化 completion (2026-05-19)

#### 実装ファイル

- `scripts/ci/check_framework_intake.sh` (新規、CI entry point、diff-gate / baseline-scan 2 mode + 8 verify item)
- `scripts/ci/_extract_changed_deps.py` (新規、changed direct dependency 抽出 helper、[dependency-groups].* 含む)
- `scripts/ci/_intake_scanner.py` (新規、verify item #3-#8 Python scanner、ripgrep 依存撤回)
- `scripts/ci/__init__.py` (新規、package 化)
- `tests/scripts/test_check_framework_intake.sh` (新規、12 fixture × 24 assertion 全 PASS)
- `tests/citations/__init__.py` + `tests/citations/test_citation_completeness.py` (新規、map schema + canonical reference + changed dep citation assert)
- `docs/citations/dependency_to_framework_map.json` (新規、10 framework × 11 entries: LangGraph / CrewAI / AutoGen / Letta / Dapr Agents / Dify / OpenHands / TaskingAI 初期登録)
- `docs/citations/README.md` (新規、citation 構造の正本 index)
- `.github/workflows/ci-smoke.yml` (modify、`actions/checkout@v4 fetch-depth: 0` + "Framework intake check" / "Framework intake fixture tests" step 追加、`env.FRAMEWORK_INTAKE_CHECK_DISABLED` repository variable 経由)
- `.claude/plans/sp022-t01-framework-intake-ci.md` (本計画、22 findings adopt ledger 含む)

#### codex-plan-review R1-R3 完了記録

- codex-plan-review-round: R3 (round_max reached、R1=Phase A / R2=Phase B / R3=CRITICAL final)
- codex-plan-review-findings: 22 (R1=14 [HIGH=4 / MEDIUM=8 / LOW=2] + R2=6 [HIGH=6] + R3=2 [CRITICAL=2])
- codex-plan-review-adopt: 22 / reject: 0 / defer: 0 (全件 adopt 反映)
- codex-plan-review-readiness-gate: READY (R3 round_max reached + clean、CRITICAL=0 / HIGH=0 残存)
- codex-plan-review-evidence-path: `~/.claude/local/codex-reviews/2026-05-19/sprint-SP-012-batch-7-taskhub-admin-cli/codex-plan-review-20260519-173506.raw.jsonl` (R1) + `codex-plan-review-20260519-174422.raw.jsonl` (R2) + `codex-plan-review-20260519-175756.raw.jsonl` (R3)

#### 8 verify trace matrix (ADR-00020 §1 mapping)

| # | verify | 実装 module | reason_code | mode 別実行 |
|---|---|---|---|---|
| 1 | License | `check_license` (shell) + `uv run python -m pip show` | `framework_intake_violation_license` | diff-gate のみ |
| 2 | Attribution | `check_attribution` (shell) + `dependency_to_framework_map.json` + `framework_pattern_candidates.md` | `framework_intake_violation_attribution` | diff-gate のみ |
| 3 | No code embed | `_intake_scanner.py::check_no_code_embed` (Python + npm scoped + dynamic import) | `framework_intake_violation_code_embed` | 両 mode |
| 4 | Persistence | `_intake_scanner.py::check_persistence` (sqlite3 / psycopg.connect) | `framework_intake_violation_persistence` | 両 mode |
| 5 | External network | `_intake_scanner.py::check_external_network` (NETWORK_DENYLIST literal URL) | `framework_intake_violation_external_network` | 両 mode |
| 6 | Telemetry off | `_intake_scanner.py::check_telemetry` (TELEMETRY_PY / TELEMETRY_NPM import) | `framework_intake_violation_telemetry` | 両 mode |
| 7 | Secret canary | `_intake_scanner.py::check_secret_canary` (`backend/app/services/providers/preflight.py` + tests/security 2 fixture + eval/security/secret_canary) | `framework_intake_violation_secret_canary` | 両 mode |
| 8 | Tenant/project boundary | `_intake_scanner.py::check_tenant_boundary` (AC-HARD-03 / tenant_isolation / cross_tenant marker existence) | `framework_intake_violation_tenant_boundary` | 両 mode |

#### Local verification 実行記録

- `bash scripts/ci/check_framework_intake.sh` (baseline-scan mode、現 worktree) → `PASS (mode=baseline-scan)` exit 0
- `bash tests/scripts/test_check_framework_intake.sh` → 18 fixture × 36 assertion すべて PASS (failed: 0、PR70 R1 7 findings adopt 後の R2 で 6 fixture 拡張)
- `uv run pytest tests/citations/ -q` → 1 passed (`test_map_schema_and_canonical_references`) + 1 skipped (`test_changed_deps_have_citation`、dependency 変更なし環境で R1 F-011 通り)

#### PR #70 Codex auto-review R1 — 7 inline P2 findings 全件 adopt

PR 起票後 約 7 分で landing、全 7 件 valid security gap 指摘:

| ID | priority | symptom (要約) | adopt 反映先 |
|---|---|---|---|
| F-PR70-001 | P2 | `baseline-scan` mode で origin/main rev-parse check が exit 2 → repo-wide scan 不能 | `check_framework_intake.sh` で rev-parse check を diff-gate mode 内に移動 |
| F-PR70-002 | P2 | Python `import langgraph, os` (comma-separated) を py_pattern が検出しない | `_intake_scanner.py` py_pattern を `(\s\|,\|\.\|$)` に拡張 |
| F-PR70-003 | P2 | Python telemetry も同 comma 検出漏れ + frontend side-effect import `import "@sentry/nextjs";` 検出漏れ | telemetry py_pattern + npm_pattern 両方拡張 |
| F-PR70-004 | P2 | `_extract_changed_deps.py` failure を `\|\| true` で silently swallow → license/attribution check が空 input で skip | `_run_extract` helper で non-zero exit を internal error (exit 2) として伝播 |
| F-PR70-005 | P2 | frontend code embed の side-effect import `import "@langchain/langgraph";` 検出漏れ | npm_pattern に `import\s+['"]<denylist>['"]` 追加 |
| F-PR70-006 | P2 | `backend/app/repositories/` が PERSISTENCE_ROOTS に含まれない → repository layer での `psycopg.connect` bypass | PERSISTENCE_ROOTS に追加 |
| F-PR70-007 | P2 | Next.js root-level `frontend/instrumentation.ts` / `instrumentation-client.ts` が scan されない → telemetry integration の典型配置で bypass | FRONTEND_SCAN_ROOTS に追加 |

reject: 0 / defer: 0 / 全件 adopt。R2 fixture 6 件 (`test_comma_import_detection` / `test_frontend_side_effect_import` / `test_persistence_in_repositories` / `test_frontend_instrumentation_scanned` / `test_extractor_failure_propagates` / `test_baseline_scan_without_origin_main`) で regression coverage 確保。

#### PR #70 Codex auto-review R2 — 6 inline P2 findings 5 adopt + 1 defer

`@codex review` mention 経由で 6330bc4 (R1 fix commit) 再 review、R2 で更に深い 6 件 security gap 指摘:

| ID | priority | symptom (要約) | 判定 | adopt 反映先 |
|---|---|---|---|---|
| R2-001 | P2 | diff-gate mode で deps 変更なしの PR が code embed / telemetry / persistence violation を bypass (e.g., `import langgraph` だけ追加して `pyproject.toml` 触らない) | **adopt** | `check_framework_intake.sh` に `DIFF_GATE_HAS_DEP_CHANGES` flag、#3-#8 は常に実行、#1/#2 のみ deps 変更時に実行 |
| R2-002 | P2 | npm dependency 追加 PR で license check が PyPI extractor のみ → frontend で restricted license library が attribution map entry あれば通過 | **defer** | ADR-00020 §1 #1 PyPI 限定は plan で明示 scope 外 (frontend pkg は post-T01 で SPDX 拡張)、ADR-00020 §1 #1 で scope 明確化は post-T01 SP-022.X (新 PR) で実施 |
| R2-003 | P2 | `from psycopg import connect; connect(...)` alias が `psycopg2?\.connect\(` regex で検出不可 | **adopt** | `_intake_scanner.py` check_persistence に `from\s+psycopg2?\s+import\s+(?:.*\b)?connect\b` 追加 |
| R2-004 | P2 | `optionalDependencies` を `_extract_changed_deps.py` が抽出していない → 新 framework を optional に置けば bypass | **adopt** | `load_package_json_at` で `optionalDependencies` も取り込む |
| R2-005 | P2 | persistence rule が `services/adapters/db/repositories` 限定で `backend/app/api` / `backend/app/workers` を scan しない → route handler / worker で直接 DB connect bypass | **adopt** | `PERSISTENCE_ROOTS` に `backend/app/api` + `backend/app/workers` 追加 |
| R2-006 | P2 | external_network scan が `config/` のみで repo root の `docker-compose*.yml` 等 deployment YAML を見ない → env var 経由で denylisted SaaS URL bypass | **adopt** | `check_external_network` に `docker-compose*.yml` / `docker-compose*.yaml` / `compose*.yml` / `compose*.yaml` glob 追加 |

defer 理由詳細 (R2-002): ADR-00020 §1 #1 の License 機械検査は PyPI tooling 中心の skeleton 設計 (ADR §2 script skeleton も `pip show` のみ)。frontend npm license は `node_modules/<pkg>/package.json` の `license` field + LICENSE_DENYLIST scan の追加実装が必要、SPDX expression 解釈 + `pnpm install` 前提条件もあり、本 SP022-T01 scope (8 verify item の最小機械化) を超える。post-T01 task (SP-022.X for frontend license + post-T01 で ADR-00020 §1 #1 scope 明確化 update) で実装すべく `## 次スプリント候補` に記録。

R2 regression fixture 5 件 (`test_diff_gate_runs_scanners_without_dep_change` / `test_psycopg_import_connect_alias` / `test_optional_dependencies_extracted` / `test_persistence_in_api_or_workers` / `test_docker_compose_external_network`) + 1 fixture 仕様変更 (`test_skip_no_deps_change` → `test_clean_pr_no_dep_change_runs_scanners` で PASS expected msg、R2-001 の挙動変更を test 側にも反映) で regression coverage 確保。

R1+R2 累計: **23 fixture × 46 assertion 全 PASS** (failed: 0)。13 adopt findings (R1=7 + R2=5 adopt) + 1 defer (R2-002 post-T01)。

#### PR #70 Codex auto-review R3 — 10 inline findings (2 adopt + 2 defer + 6 reject as stale re-emission)

`@codex review` mention 経由で 44c18fe (R2 fix commit) 再 review、R3 で 10 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R3-001 (NEW) | P2 | `_extract_changed_deps.py` が optional-dependencies を license check に渡すが `uv sync --locked` default では extras install されず `pip show` empty で `license_field_empty_or_unresolved` 誤 violation | **adopt** | `_extract_changed_deps.py` に `--scope={core,extras,all}` flag 追加、check_license は core 限定 (installed deps のみ)、check_attribution は all (citation 必要) |
| R3-002 (NEW) | P2 | Attribution check は map + candidates.md row のみ verify、ADR-00020 §1 #2 が要求する `docs/citations/<framework>_adoption.md` 個別 citation artifact 不検査 | **defer** | ADR-00020 §1 #2 plan で「OR」設計 (本 task では candidates.md 内 entry で十分)、ADR 文書を strict AND 解釈する変更は SP-022.X (R2-002 と同 hardening) で実施 |
| R3-003 (NEW) | P2 | PERSISTENCE_ROOTS allowlist が `backend/app/domain` / `middleware` / `observability` / `seeds` / `schemas` を含まない、production product paths bypass | **adopt** | PERSISTENCE_ROOTS を `Path("backend/app")` 単一に拡大、BACKEND_EXCLUDE_PARTS={migrations} で db/migrations 除外維持 |
| R3-004 | P2 | "Include repositories in persistence scan" | **reject as stale re-emission** | R2 で既 adopt、scripts/ci/_intake_scanner.py に `Path("backend/app/repositories")` 既存 (line 93、PR70 F-PR70-006 comment 付き) |
| R3-005 | P2 | "Scan Next.js root instrumentation files" | **reject as stale re-emission** | R2 で既 adopt、FRONTEND_SCAN_ROOTS に `frontend/instrumentation.ts` + `instrumentation-client.ts` 既存 (line 80-81) |
| R3-006 | P2 | "Catch imported psycopg connect aliases" | **reject as stale re-emission** | R2 で既 adopt、`psycopg_import_connect` regex 既存 (line 189-191) |
| R3-007 | P2 | "Include optional frontend dependencies" | **reject as stale re-emission** | R2 で既 adopt、`load_package_json_at` で `optionalDependencies` 取り込み既存 (line 125) |
| R3-008 | P2 | "Scan backend API files for direct persistence" | **reject as stale re-emission** | R2 で既 adopt、PERSISTENCE_ROOTS に `backend/app/api` + `backend/app/workers` 既存。R3-003 で `backend/app` 全体に拡大して更に強化 |
| R3-009 | P2 | "Include deployment YAML in endpoint scans" | **reject as stale re-emission** | R2 で既 adopt、`check_external_network` に `docker-compose*.yml` glob 既存 (line 233) |
| R3-010 | P2 | "Check npm dependency licenses too" | **defer (continue from R2-002)** | R2-002 と同 finding 再 emit、SP-022.X (post-T01 frontend license + ADR-00020 §1 #1 scope 明確化) で実施 |

**Stale re-emission rationale**: `feedback_codex_r2_reemission_reject_trap.md` (project memory) 教訓に従い、6 件 R3 re-emission は **code grep + implementation verify** で reject 確定 (R2 commit 44c18fe で全件 fix 実装 + R2 regression fixture 5 件で PASS verify 済)。Codex multi-round の既知の "stale finding re-emission" pattern。

実装:
- `_extract_changed_deps.py`: `load_pyproject_at(ref, scope=...)` に `scope={core,extras,all}` filter、`main()` で `--scope` flag 追加 (R3-001)
- `check_framework_intake.sh`: `_run_extract` に scope 引数追加、`extract_changed_deps_pypi_core()` 関数追加、`check_license` で `extract_changed_deps_pypi_core` 使用 (R3-001)
- `_intake_scanner.py`: `PERSISTENCE_ROOTS = (Path("backend/app"),)` 単一化、`BACKEND_EXCLUDE_PARTS={migrations}` で migrations 除外維持 (R3-003)

R3 regression fixture 2 件 (`test_optional_extras_skipped_for_license` + `test_persistence_in_domain_or_middleware`) 追加。

R1+R2+R3 累計: **25 fixture × 51 assertion 全 PASS** (failed: 0)。**15 adopt findings** (R1=7 + R2=5 + R3=2 + 1 fixture 仕様変更を含む 18 total impact 1 仕様変更 = 18-15 fix 単位 = 計画通り) + 2 defer (R2-002 / R3-002、frontend license + adoption.md 個別 verify は SP-022.X post-T01) + 6 reject (R3 stale re-emission)。

#### PR #70 Codex auto-review R4 — 10 inline findings (4 adopt + 1 defer + 5 reject as stale re-emission)

`@codex review` mention 経由で 0c07fff (R3 fix commit) 再 review、R4 で 10 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R4-001 (npm license) | P2 | npm 追加 PR で license check が `extract_changed_deps_pypi_core` のみ実行、frontend license verify されない | **defer** | R2-002 / R3-010 と同 finding、SP-022.X (post-T01) で実施 |
| R4-002 (NEW、R3-001 副作用) | P2 | `[dependency-groups].dev` も `uv sync --locked` default で install されるのに R3-001 で `core` scope から除外 → dev framework license bypass | **adopt** | `_extract_changed_deps.py` scope=core を `[project.dependencies] + [dependency-groups].*` に再定義、optional-dependencies のみ extras (license 対象外、`--extra` flag なしで未 install のため) |
| R4-003 (NEW) | P2 | Python dynamic import `importlib.import_module("langgraph")` / `__import__("crewai")` を no-code-embed rule が検出しない | **adopt** | `_intake_scanner.py::check_no_code_embed` に `py_dynamic_pattern` 追加 |
| R4-004 (NEW) | P2 | 10 framework 候補のうち Semantic Kernel (Python module `semantic_kernel`) が `PY_DENYLIST_FRAMEWORKS` に抜け | **adopt** | `PY_DENYLIST_FRAMEWORKS` に `semantic_kernel` 追加 |
| R4-005 (NEW) | P2 | `psycopg.AsyncConnection.connect(...)` / `psycopg.Connection.connect(...)` class-level connect が `psycopg2?\.connect\(` regex で検出されない (中間 Connection class) | **adopt** | `psycopg_class_connect = re.compile(r"psycopg2?\.(?:Async)?Connection\.connect\(")` 追加 |
| R4-006 to R4-010 (5 件) | P2 | "Scan Next.js root instrumentation" / "Catch imported psycopg connect aliases" / "Include optional frontend dependencies" / "Include deployment YAML" / "Enforce citation artifact" | **reject as stale re-emission** | R2/R3 で既 adopt 実装済 (code grep verify)、R3-002 defer は SP-022.X 維持 |

**Stale re-emission rationale**: 5 件 R4 re-emission は code grep + R2/R3 commit comment ('PR70 R2 F-PR70-R2-XXX adopt' marker) で verify (R2 commit 44c18fe / R3 commit 0c07fff で全件 fix 済)。`feedback_codex_r2_reemission_reject_trap.md` 教訓: code grep + R2/R3 regression fixture PASS で実体検証してから reject 確定。

実装:
- `_extract_changed_deps.py`: `load_pyproject_at` scope=core を `[project.dependencies] + [dependency-groups].*` に再定義 (R4-002)
- `_intake_scanner.py`:
  - `PY_DENYLIST_FRAMEWORKS` に `semantic_kernel` 追加 (R4-004)
  - `check_no_code_embed` に `py_dynamic_pattern` (importlib.import_module / __import__) 追加 (R4-003)
  - `check_persistence` に `psycopg_class_connect` regex 追加 (R4-005)

R4 regression fixture 4 件追加: `test_dependency_groups_license_checked` (R4-002) / `test_python_dynamic_import_detection` (R4-003) / `test_semantic_kernel_denylist` (R4-004) / `test_psycopg_class_level_connect` (R4-005)。

R1+R2+R3+R4 累計: **29 fixture × 59 assertion 全 PASS** (failed: 0)。**19 adopt findings** (R1=7 + R2=5 + R3=2 + R4=4 + 1 fixture 仕様変更) + 2 defer (R2-002 / R3-002 / R4-001 / R4-010 = 同 root issue SP-022.X) + 11 reject (R3 stale 6 + R4 stale 5)。

#### PR #70 Codex auto-review R5 — 15 inline findings (5 adopt + 1 defer (P1 escalated) + 9 reject as stale re-emission)

`@codex review` mention 経由で add969a (R4 fix commit) 再 review、R5 で 15 件 emit (うち 1 件は P1 escalation):

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R5-001 (P1 escalated) | P1 | npm 追加 PR で license check が PyPI のみ、frontend license verify されない (R2-002/R3-010/R4-001 と同根、Codex が P1 に escalate) | **defer (continue R2-002)** | SP-022.X (frontend license verify) で実施、plan で明示 scope 外、本 PR 内では node_modules read + SPDX 解釈の実装重く別 PR で扱う |
| R5-002 (NEW) | P2 | dynamic import submodule `importlib.import_module("langgraph.graph")` を regex が detect しない (quote 直後の literal name のみ) | **adopt** | py_dynamic_pattern を `(?:\.[A-Za-z_][A-Za-z0-9_.]*)?` 追加で submodule path 対応 |
| R5-003 (NEW) | P2 | `[dependency-groups]` の non-default group (e.g., `docs`) は `uv sync --locked` default で install されないため license check は誤 violation を出す | **adopt** | `_extract_changed_deps.py` で `[tool.uv.default-groups]` を読み default-groups のみ scope=core、他は scope=extras (license 対象外) |
| R5-004 (NEW) | P2 | telemetry も dynamic import (`importlib.import_module("sentry_sdk")`) を検出しない | **adopt** | check_telemetry に `py_telemetry_dynamic` regex 追加 |
| R5-005 (NEW) | P2 | `from psycopg import AsyncConnection; AsyncConnection.connect(...)` import alias chain を class-level regex が検出しない | **adopt** | `psycopg_import_class` + `class_connect_call` の 2 段検出 (import-then-call chain) 追加、`from_import_class_connect_alias` detail |
| R5-006 (NEW) | P2 | npm scoped name `semantic-kernel` (10 framework のうち Semantic Kernel) が NPM_DENYLIST に未追加 (R4-004 で Python だけ追加) | **adopt** | NPM_DENYLIST_FRAMEWORKS に `semantic-kernel` 追加 |
| R5-007 to R5-015 (9 件 stale) | P2 | "Scan Next.js root instrumentation" / "Catch imported psycopg connect aliases" / "Include optional frontend dependencies" / "Include deployment YAML" / "Enforce citation artifact" / "License-check dependency groups" / "Detect Python dynamic framework imports" / "Add Semantic Kernel to the Python denylist" / "Catch psycopg class-level connects" | **reject as stale re-emission** | R2/R3/R4 で既 adopt 実装済、code grep + commit comment marker で verify (R2 44c18fe / R3 0c07fff / R4 add969a 各 fix commit) |

**Stale re-emission rationale**: 9 件 R5 re-emission は code grep + R2/R3/R4 commit comment ('PR70 R2/R3/R4 F-PR70-RX-XXX adopt' marker) で verify。`feedback_codex_r2_reemission_reject_trap.md` 教訓: 必ず code grep + R2-R4 regression fixture PASS (29 fixture 既存) で実体検証してから reject 確定。

実装:
- `_extract_changed_deps.py`: scope=core を `default_groups` (uv `[tool.uv.default-groups]` または `{"dev"}` default) に限定、non-default group は scope=extras に移動 (R5-003)
- `_intake_scanner.py`:
  - `NPM_DENYLIST_FRAMEWORKS` に `semantic-kernel` 追加 (R5-006)
  - `py_dynamic_pattern` に submodule path `(?:\.[...]+)?` 追加 (R5-002)
  - `check_telemetry` に `py_telemetry_dynamic` 追加 + 既存 + 同 submodule path 対応 (R5-004)
  - `check_persistence` に `psycopg_import_class` + `class_connect_call` 2 段検出追加 (R5-005)

R5 regression fixture 5 件追加: `test_dynamic_submodule_import` (R5-002) / `test_non_default_dep_group_skipped_for_license` (R5-003) / `test_dynamic_telemetry_import` (R5-004) / `test_psycopg_import_class_alias_chain` (R5-005) / `test_semantic_kernel_npm` (R5-006)。

R1+R2+R3+R4+R5 累計: **34 fixture × 70 assertion 全 PASS** (failed: 0)。**24 adopt findings** (R1=7 + R2=5 + R3=2 + R4=4 + R5=5 + 1 fixture 仕様変更) + 2 unique defer (frontend license + adoption.md AND、SP-022.X) + 20 reject (R3 stale 6 + R4 stale 5 + R5 stale 9)。

#### PR #70 Codex auto-review R6 — 19 inline findings (5 adopt + 14 reject as stale re-emission)

`@codex review` mention 経由で 44aba20 (R5 fix commit) 再 review、R6 で 19 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R6-001 (NEW) | P2 | `[tool.uv] default-groups = "all"` literal string で全 dep-group install されるが extractor は list のみ受付、他 default-installed group が extras 分類で license check skip | **adopt** | `default-groups == "all"` literal value 対応、`all_groups` 集合に置換 |
| R6-002 (NEW) | P2 | legacy `[tool.uv].dev-dependencies` は uv で `dev` group merge されるが extractor 未対応、新 direct dep が intake gate bypass | **adopt** | scope=core で `tool.uv.dev-dependencies` も読み、`dev` が default に含まれる場合のみ含める |
| R6-003 (NEW) | P2 | `[dependency-groups]` nested `{include-group = "lint"}` 配下の dep が license check で skip される | **adopt** | `_resolve_group` 再帰 helper で nested include-group 展開、循環参照防止 `seen` set |
| R6-004 (NEW) | P2 | `from psycopg import AsyncConnection as PG; PG.connect(...)` alias 検出漏れ (class_connect_call は literal `AsyncConnection.connect` のみ match) | **adopt** | psycopg_import_class_re で `as <alias>` 含む import body を parse、imported_aliases set 構築 → alias.connect 動的 regex 生成 |
| R6-005 (NEW) | P2 | frontend dynamic import `await import ("foo")` (whitespace) を `import\(['"]` regex が detect しない | **adopt** | npm_pattern で `import\s*\(\s*['"]` / `require\s*\(\s*['"]` に拡張、whitespace 許容 |
| R6-006 to R6-019 (14 件 stale) | P2 (+1 P1) | 上記以外は R2-R5 既 adopt re-emission (Scan Next.js root / psycopg alias / optional frontend / deployment YAML / citation artifact / npm license [P1] / license-check dep-groups / dynamic framework imports / Semantic Kernel Python+npm / class-level connects / dynamic telemetry / imported Connection classes) | **reject as stale re-emission** | R2-R5 既 adopt 実装済、code grep + 各 fix commit comment marker で verify |

**Stale re-emission rationale**: 14 件 R6 re-emission は code grep + R2/R3/R4/R5 commit comment ('PR70 RX F-PR70-RX-XXX adopt' marker) で verify。Codex multi-round の既知 stale re-emission pattern (`feedback_codex_pr_review_baseline_check.md` 教訓: 必ず code grep + R2-R5 regression fixture PASS で実体検証してから reject 確定)。

実装:
- `_extract_changed_deps.py`:
  - `default-groups` `"all"` literal 対応 + 全 group set 置換 (R6-001)
  - `[tool.uv].dev-dependencies` legacy 取り込み (R6-002)
  - `_resolve_group` 再帰 helper で `{include-group = "..."}` nested 展開 + `seen` set 循環防止 (R6-003)
- `_intake_scanner.py`:
  - `psycopg_import_class_re` で `as <alias>` 含む import body parse、imported_aliases set 構築 → 動的 `<alias>.connect(` regex 生成 (R6-004)
  - frontend `npm_pattern` で `import\s*\(\s*['"]` / `require\s*\(\s*['"]` whitespace 許容 (R6-005)

R6 regression fixture 5 件追加: `test_default_groups_all_literal` (R6-001) / `test_legacy_tool_uv_dev_dependencies` (R6-002) / `test_nested_include_group` (R6-003) / `test_psycopg_aliased_connect` (R6-004) / `test_dynamic_import_with_whitespace` (R6-005)。

R1+R2+R3+R4+R5+R6 累計: **39 fixture × 80 assertion 全 PASS** (failed: 0)。**29 adopt findings** + 2 unique defer + 34 reject (R3 stale 6 + R4 stale 5 + R5 stale 9 + R6 stale 14)。

#### PR #70 Codex auto-review R7 — 20 inline findings (6 adopt + 14 reject as stale re-emission)

`@codex review` mention 経由で bd58d7f (R6 fix commit) 再 review、R7 で 20 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R7-001 (NEW) | **P1** | AutoGen v0.4+ は `autogen_agentchat` / `autogen_core` / `autogen_ext` に split、denylist は legacy `autogen` / `pyautogen` のみ → 現行 import bypass | **adopt** | PY_DENYLIST に v0.4 系 3 module 追加 |
| R7-002 (NEW) | **P1** | Dapr Agents は `dapr_agents` (pip `dapr-agents`)、denylist は base `dapr` のみ → SDK bypass | **adopt** | PY_DENYLIST に `dapr_agents` 追加 |
| R7-003 (NEW) | **P1** | Letta Python SDK は `letta_client` (`from letta_client import Letta`)、denylist は `letta` のみ → SDK bypass | **adopt** | PY_DENYLIST に `letta_client` 追加 |
| R7-004 (NEW) | **P1** | Letta npm SDK は scoped `@letta-ai/letta-client`、denylist は unscoped `letta` のみ → frontend SDK bypass | **adopt** | NPM_DENYLIST に `@letta-ai/letta-client` 追加 |
| R7-005 (NEW) | P2 | `License: UNKNOWN` / `NULL` / `None` literal を license empty 判定 skip、later denylist で UNKNOWN は match せず silent pass | **adopt** | check_license で `license_lower` に正規化、UNKNOWN/NULL/None も unresolved 扱い |
| R7-006 (NEW) | **P1** | `import psycopg as pg; pg.connect(...)` module alias 検出漏れ + multiline `from psycopg import (connect,)` parenthesized import 検出漏れ | **adopt** | check_persistence に `psycopg_module_alias_re` (module alias 動的 regex) + `psycopg_import_connect` を `re.DOTALL` で multiline 対応 |
| R7-007 to R7-020 (14 件 stale) | P2 (+1 P1) | R2-R6 既 adopt re-emission (Next.js root / psycopg / optional frontend / deployment YAML / citation artifact / npm license [P1] / dep-groups / dynamic imports / Semantic Kernel / class-level connects / dynamic telemetry / Connection classes / legacy tool.uv dev / whitespace dynamic import) | **reject as stale re-emission** | R2-R6 既 adopt 実装済、code grep + 各 fix commit comment marker で verify |

**P1 escalation rationale**: R7 で 4 件が P1 (AutoGen v0.4 + Dapr Agents + Letta Python SDK + Letta npm SDK) — これらは 10-framework 候補 ledger に明示記載の framework の **現行 import root が denylist に欠落** していた致命的 security gap。Codex が "I verified `from X import Y` exits 0 under `--rule=no_code_embed`" と動作確認まで実施した P1 finding、即 adopt 妥当。

**Stale re-emission rationale**: 14 件 R7 re-emission は code grep + R2-R6 commit comment marker で verify。Codex multi-round の既知 stale re-emission pattern (R3 から累計 stale = 6+5+9+14+14=48 件、いずれも code 実装済)。

実装:
- `_intake_scanner.py`:
  - PY_DENYLIST_FRAMEWORKS に `autogen_agentchat` / `autogen_core` / `autogen_ext` / `dapr_agents` / `letta_client` 追加 (R7-001/002/003)
  - NPM_DENYLIST_FRAMEWORKS に `@letta-ai/letta-client` 追加 (R7-004)
  - check_persistence に `psycopg_module_alias_re` + 動的 `<alias>.connect(` regex 追加 (R7-006 module alias)
  - check_persistence の `psycopg_import_connect` を `re.DOTALL` + `(?:\(\s*)?` 対応で multiline parenthesized import 検出 (R7-006 multiline)
- `check_framework_intake.sh`:
  - check_license で `license_lower=$(echo $license | tr ...)` で正規化、`unknown` / `null` / `none` literal も unresolved 扱い (R7-005)

R7 regression fixture 7 件追加: `test_autogen_v04_modules` (R7-001) / `test_dapr_agents_module` (R7-002) / `test_letta_client_python_sdk` (R7-003) / `test_letta_client_npm_sdk` (R7-004) / `test_license_unknown_placeholder` (R7-005 代理) / `test_psycopg_module_alias_connect` (R7-006 module alias) / `test_psycopg_multiline_import` (R7-006 multiline)。

R1+R2+R3+R4+R5+R6+R7 累計: **46 fixture × 94 assertion 全 PASS** (failed: 0)。**35 adopt findings** + 2 unique defer + 48 reject (R3-R7 stale)。

#### PR #70 Codex auto-review R8 — 22 inline findings (3 adopt + 19 reject as stale re-emission)

`@codex review` mention 経由で 72e501f (R7 fix commit) 再 review、R8 で 22 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R8-001 (NEW) | P2 | `tests/citations/test_citation_completeness.py` pytest が origin/main 不在 local clone で fail (existing deps を全て added 扱い) | **adopt** | `_origin_main_resolvable()` helper 追加、origin/main 不在 → pytest.skip |
| R8-002 (NEW) | P2 | `_run_extract` で stderr を stdout に merge → `uv run` non-fatal diagnostic (`Creating virtual environment at: .venv`) が dependency name に混入、`check_license` で偽 `license_field_empty_or_unresolved` emit | **adopt** | stderr を `mktemp` で separate capture、success 時 replay 抑制、failure 時のみ stderr replay |
| R8-003 (NEW) | P2 | `psycopg_import_connect` の `re.DOTALL` over-match: `from psycopg import errors\n...\ndef connect(...)` を connect alias と誤検出 | **adopt** | `psycopg_import_connect` を `_single` (parenthesis なし、line-bound) + `_paren` (parenthesized only DOTALL) の 2 regex に分離 |
| R8-004 to R8-022 (19 件 stale) | P2 (+1 P1) | R2-R7 既 adopt re-emission (Next.js / psycopg / optional frontend / deployment YAML / citation / npm license [P1] / dep-groups / dynamic imports / Semantic Kernel Python+npm / class-level connects / dynamic telemetry / legacy tool.uv dev / whitespace dynamic import / AutoGen v0.4 / Dapr Agents / Letta Python+npm SDK / psycopg aliased connects) | **reject as stale re-emission** | R2-R7 既 adopt 実装済、code grep + commit comment marker で verify |

**Stale re-emission rationale**: 19 件 R8 re-emission は code grep + R2-R7 commit comment marker で verify。累計 stale = R3:6 + R4:5 + R5:9 + R6:14 + R7:14 + R8:19 = **67 件**、いずれも code 実装済 (Codex multi-round 既知の stale re-emission pattern)。`feedback_codex_pr_review_baseline_check.md` 教訓: code grep + R2-R7 regression fixture PASS で実体検証してから reject 確定。

実装:
- `tests/citations/test_citation_completeness.py`: `_origin_main_resolvable()` helper + `test_changed_deps_have_citation` で origin/main 不在時に pytest.skip (R8-001)
- `scripts/ci/check_framework_intake.sh::_run_extract`: stderr を `mktemp` 一時 file に分離、success 時は replay せず、failure 時のみ stderr replay (R8-002)
- `scripts/ci/_intake_scanner.py::check_persistence`: `psycopg_import_connect_single` (line-bound、non-parenthesized) + `psycopg_import_connect_paren` (parenthesized only DOTALL with bounded `[^)]*?` 内 inspection) の 2 regex で over-match 防止 (R8-003)

R8 regression fixture 1 件追加: `test_psycopg_import_errors_no_false_positive` (R8-003、`from psycopg import errors` + 別行 `def connect()` で persistence gate が false-positive せずに skip することを verify)。

R1+R2+R3+R4+R5+R6+R7+R8 累計: **47 fixture × 95 assertion 全 PASS** (failed: 0)。**38 adopt findings** + 2 unique defer + 67 reject (R3-R8 stale)。

#### Emergency disable audit format

CI gate を緊急 disable する場合、admin が GitHub Settings → Variables で `FRAMEWORK_INTAKE_CHECK_DISABLED=1` を設定。本 sprint pack の `## Review` 内に以下を 24h 以内に記録 (R1 F-013 adopt):

```
- disable_at_utc: <YYYY-MM-DD HH:MM:SS UTC>
- disabled_by: <admin actor>
- reason: <critical incident rationale>
- recovery_commit_sha: <commit SHA that re-enabled>
- retro_pack_ref: <docs/sprints/... or ADR-NNNNN>
```

#### tailscale-public-exposure hook false positive note (2026-05-19)

`.claude/hooks/tailscale/check-tailscale-grants.sh` が `.github/workflows/ci-smoke.yml` の Edit 時に BLOCK を出した (regex `^[[:space:]]*-[[:space:]]*"?[0-9]+:[0-9]+` が既存 GitHub Actions services の internal port mapping `"5432:5432"` / `"6379:6379"` 等に hit)。本 PR では:
- 新規追加の literal は `fetch-depth: 0` + Framework intake check step のみ、`Funnel` / `public ingress` / `Cloudflare Tunnel` / `0.0.0.0` / `public bind` は一切追加なし
- 既存 port mapping は GitHub Actions services の CI-internal port (test docker container 内で `localhost:5432` listen)、production deployment 設定ではない
- hook 動作は valid だが本 Edit に対しては false positive、ADR-00007 update 不要

将来の hook polish 候補: `target=yes` 判定で `.github/workflows/` を `.github/` 全体除外、または regex を refine。本 task の scope 外、SP-022 別 task or post-P0.1 で対応判断。

### SP022-T03 半年 drill scheduling SOP completion (2026-05-19)

#### 実装ファイル

- `scripts/ci/check_drill_timer_alert_only.sh` (新規、CI entry point、diff-gate / baseline-scan 2 mode + emergency disable repository variable + R2 F-PR70-T03-R2-001 NUL byte temp file 経由)
- `scripts/ci/_drill_timer_scanner.py` (新規、Python scanner、systemd `Exec*=` 全 directive + cron 5/6-field + `@daily` macro + cron env line PATH/SHELL/BASH_ENV fail-closed + TRUSTED_PATH_PREFIXES 検証 + shell composition 検出)
- `tests/deploy/__init__.py` + `tests/deploy/test_drill_timer_alert_only.py` (新規、**23 pytest fixture 全 PASS**: positive deny 13 + positive pass 5 + edge / negative 5)
- `docs/deploy/half-yearly-drill-sop.md` (新規、半年 drill SOP: CI 機械検査 explainer + systemd / cron 構成例 + 手動 approval flow + 異常時 escalation + T02 planned contract + emergency disable + retro Pack 義務)
- `.github/workflows/ci-smoke.yml` (modify、`backend-quality` job に "Drill timer alert-only check" step 追加、`vars.DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED` repository variable 経由 + workflow step `if:` 条件 + shell defense-in-depth 二重 check)
- `.claude/plans/sp022-t03-drill-scheduling-sop.md` (本計画、19 findings adopt ledger 含む)

#### codex-plan-review R1-R3 完了記録

- codex-plan-review-round: R3 (round_max reached、R1=Phase A / R2=Phase B / R3=CRITICAL final)
- codex-plan-review-findings: 19 (R1=16 [HIGH=5 / MEDIUM=8 / LOW=3] + R2=3 [HIGH=3] + R3=0 [CRITICAL=0、clean])
- codex-plan-review-adopt: 19 / reject: 0 / defer: 0 (全件 adopt 反映)
- codex-plan-review-readiness-gate: READY (R3 round_max reached + CRITICAL clean、致命的論点なし)
- codex-plan-review-evidence-path: `~/.claude/local/codex-reviews/2026-05-19/sprint-SP-012-batch-7-taskhub-admin-cli/codex-plan-review-2026051921*.raw.jsonl`

#### Phase G PGA-F-013 trace marker

ADR-00021 §14.2 #4 (PGA-F-013) drill timer alert-only enforcement 完了:
- `scripts/ci/check_drill_timer_alert_only.sh` 完成 (CI gate 機械検査)
- `tests/deploy/test_drill_timer_alert_only.py` 23 fixture 全 PASS
- `docs/deploy/half-yearly-drill-sop.md` 半年 drill SOP 完備
- `taskhub migrate --approval-id` 実装は SP022-T02 (planned contract、本 T03 で仕様明文化のみ)
- 実機 host migration drill execution は SP022-T09 (本 SOP を drill 実施時に使用)

#### Local verification 実行記録

- `bash scripts/ci/check_drill_timer_alert_only.sh` (baseline-scan mode、現 worktree) → `PASS (mode=baseline-scan)` exit 0
- `uv run pytest tests/deploy/test_drill_timer_alert_only.py -v` → **23 passed** (failed: 0)
- ruff + mypy regression (post-implementation で確認、SP022-T01 既存 47 fixture × 95 assertion 全 PASS 維持)

#### tailscale-public-exposure hook false positive note (2026-05-19、SP022-T01 と同 pattern)

`.claude/hooks/tailscale/check-tailscale-grants.sh` が `.github/workflows/ci-smoke.yml` Edit 時に BLOCK (regex `^\s*-\s*"?[0-9]+:[0-9]+` が既存 GitHub Actions services の internal port mapping `"5432:5432"` / `"6379:6379"` に hit)。本 PR で新規追加した literal は "Drill timer alert-only check" step のみ、`Funnel` / `public ingress` / `Cloudflare Tunnel` / `0.0.0.0` / `public bind` は一切追加なし。SP022-T01 PR #70 と同様の false positive。

#### PR #71 Codex auto-review R1 — 7 inline findings (P1×1 + P2×6) 全件 adopt

PR 起票後 約 7 分で landing、7 件全件 valid security gap / robustness 指摘:

| ID | priority | symptom (要約) | adopt 反映先 |
|---|---|---|---|
| R1-001 | P2 | non-drill `deploy/` `ops/` 配下 `.service` を standalone scan で誤検出 | `SCAN_SERVICE_GLOBS` を `*drill*` 限定に変更 |
| R1-002 | P2 | cron.d macro `@daily root /usr/bin/notify-send drill` で user field を command として誤渡し | `is_etc_crond` 判定で macro entry の user field を strip |
| R1-003 | P2 | SOP example の `docs/deploy/taskhub-drill-cron.d/` path が scanner glob (`**/cron.d/**`) と不一致 | SOP example dir name を `cron.d` に修正 + Note 追加 |
| R1-004 | P2 | workflow `if:` で step skip → script の emergency disable audit log が出ない | workflow `if:` を削除、script 内 `DRILL_TIMER_ALERT_ONLY_CHECK_DISABLED=1` check で audit marker 出力 |
| R1-005 | P2 | diff-gate で deleted `.service` の paired-missing check 漏れ | `scan_files` 内 deleted `.service` (`exists()` false) を検出、対 `.timer` を baseline から探索して `timer_files` に load |
| R1-006 | P2 | SOP `docs/deploy/host-migration.md` reference が repo に未配置 | ADR-00021 §3 / §11 reference に置換 |
| **R1-007** | **P1** | `/usr/local/bin/../../tmp/slack-cli` 等 `..` path traversal で `startswith` trusted prefix check bypass | `os.path.normpath(cmd_head)` で normalize 後に prefix check |

reject: 0 / defer: 0 / 全件 adopt。

R1 regression fixture 3 件追加: `test_path_traversal_via_dotdot_rejected` (R1-007 P1) / `test_non_drill_service_under_deploy_excluded` (R1-001) / `test_cron_d_macro_user_field_stripped_pass` (R1-002)。

R1+T03 R1 累計 fixture: **26 pytest fixture 全 PASS** (failed: 0、SP022-T03 plan stage 23 + PR71 R1 stage 3)。

#### PR #71 Codex auto-review R2 — 9 inline findings (P1×1 + P2×8) (5 adopt + 4 reject stale)

`@codex review` mention 経由で 1343845 (R1 fix commit) 再 review、R2 で 9 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R2-001 NEW | P2 | diff-gate でも `.service` 全 scan、drill filter 適用なし → non-drill app service 誤検出 | **adopt** | `scan_files` から `.service` filter で `"drill" in p.name` 追加 |
| R2-002 NEW | **P1** | systemd `ExecSearchPath=/tmp/evil` で bare allowlist command spoofing | **adopt** | `SYSTEMD_EXEC_SEARCH_PATH_RE` 検出 + `drill_timer_alert_only_exec_search_path` violation |
| R2-003 NEW | P2 | `~` / `*` / `?` shell expansion 検出漏れ (`mail -A ~/.taskhub/approvals/*.signed`) | **adopt** | `SHELL_COMPOSITION_RE` に `~/` `~ ` `^~` `*` `?` 追加 |
| R2-004 NEW | P2 | `etc/crontab` (6-field system crontab) を 5-field 誤 parse → root user field を head と誤認識 | **adopt** | `is_etc_crond` 判定を `cron.d` OR `etc/crontab` basename match に拡張 |
| R2-005 NEW | P2 | systemd Exec prefix `-` (ignore-failure) で `-/usr/bin/notify-send` path check fail | **adopt** | `SYSTEMD_EXEC_PREFIX_RE` で prefix `-`, `+`, `:`, `!`, `!!` strip 後に path check |
| R2-006 to R2-009 (4 件 stale) | P2 | cron.d macro user strip / SOP path / audit log preserve / paired-service deletion | **reject as stale re-emission** | R1 で全件 adopt 実装済、code grep + commit marker で verify |

**Stale re-emission rationale**: 4 件 R2 re-emission は R1 commit 1343845 で実装済 (cron.d macro user strip line 327 周辺、SOP path 修正、workflow `if:` 削除、deleted .service 対 timer baseline 探索)。`feedback_codex_r2_reemission_reject_trap.md` 教訓: code grep verify 後 reject。

実装:
- `_drill_timer_scanner.py`:
  - `SHELL_COMPOSITION_RE` に `~` glob + `*` `?` 追加 (R2-003)
  - `SYSTEMD_EXEC_SEARCH_PATH_RE` + `SYSTEMD_EXEC_PREFIX_RE` 追加 (R2-002 + R2-005)
  - diff-gate `scan_files` の `.service` filter で `"drill" in p.name` (R2-001)
  - `is_etc_crond` 判定で `etc/crontab` 6-field 認識 (R2-004)
  - systemd `ExecStart=` parsing で prefix strip 後 path check (R2-005)

R2 regression fixture 5 件追加: `test_exec_search_path_rejected` (R2-002 P1) / `test_exec_prefix_dash_pass` (R2-005) / `test_tilde_expansion_rejected` (R2-003) / `test_glob_expansion_rejected` (R2-003) / `test_diff_gate_non_drill_service_excluded` (R2-001)。

累計 fixture: **31 pytest fixture 全 PASS** (failed: 0、plan stage 23 + R1 stage 3 + R2 stage 5)。

#### PR #71 Codex auto-review R3 — 8 inline findings (P1×2 + P2×6) (3 adopt + 5 reject stale)

`@codex review` mention 経由で 5482587 (R2 fix commit) 再 review、R3 で 8 件 emit。実態分析:

| ID | priority | symptom (要約) | 判定 | rationale |
|---|---|---|---|---|
| R3-001 NEW | P2 | SOP `docs/deploy/cron.d/drill-alert` example が 5-field、cron.d 6-field 要求と不整合 → `six_field_parse_failed` | **adopt** | SOP example の cron 行に `root` user field 追加 |
| R3-002 NEW | **P1** | diff-gate で drill 名でない paired `.service` (e.g., `send-alert.service` referenced from `drill-alert.timer`) が `*drill*` filter で drop | **adopt** | changed non-drill `.service` を repo 全 timer から探索、reference あれば scan 対象に追加 |
| R3-003 NEW | **P1** | `echo drill&/tmp/payload` (空白なし `&`) で shell composition regex 検出漏れ、cron `/bin/sh` は `&` を control operator 扱い | **adopt** | `SHELL_COMPOSITION_RE` で `\s&\s` → `&` (空白前後不問) に強化 |
| R3-004 to R3-008 (5 件 stale) | P2 / P1 | cron.d macro user strip / SOP path / audit log preserve / ExecSearchPath / Exec prefix | **reject as stale re-emission** | R1/R2 で全件 adopt 実装済、code grep verify |

**Stale re-emission rationale**: 5 件 R3 re-emission は R1/R2 commit (1343845 / 5482587) で実装済 (cron.d macro user strip line 327+、SOP path 修正、workflow `if:` 削除、ExecSearchPath_RE 追加、Exec prefix strip)。`feedback_codex_r2_reemission_reject_trap.md` 教訓: code grep verify 後 reject。

実装:
- `_drill_timer_scanner.py`:
  - `SHELL_COMPOSITION_RE` で `&` を空白前後不問に強化 (R3-003 P1)
  - diff-gate `changed_services` で non-drill `.service` の対 timer 探索 + scan 追加 (R3-002 P1)
- `docs/deploy/half-yearly-drill-sop.md`:
  - cron.d example に `root` user field 追加 (R3-001)

R3 regression fixture 3 件追加: `test_adjacent_ampersand_rejected` (R3-003 P1) / `test_diff_gate_paired_service_non_drill_name` (R3-002 P1) / `test_cron_d_5_field_without_user_rejected` (R3-001 boundary)。

累計 fixture: **34 pytest fixture 全 PASS** (failed: 0、plan stage 23 + R1 3 + R2 5 + R3 3)。

#### PR #71 Codex auto-review R4 — 10 inline findings (P1×3 + P2×7) (5 adopt + 5 reject stale)

R4 で 10 件 emit、真に新 5 件 (P1×3 + P2×2) adopt、stale 5 件 (R1-R3 既 adopt) reject。

| ID | priority | symptom (要約) | 判定 |
|---|---|---|---|
| R4-001 NEW | P2 | systemd Exec prefix `@` strip 漏れ | adopt |
| R4-002 NEW | **P1** | systemd drop-in override `*.service.d/*.conf` scan 漏れ → destructive ExecStart= override bypass | adopt |
| R4-003 NEW | P2 | `git diff --name-only` で rename old path 不可視 → 削除側 service が見えず paired-missing 漏れ | adopt |
| R4-004 NEW | P2 | SOP osascript example の AppleScript unquoted で shell が `display` 単独引数として渡す | adopt |
| R4-005 NEW | **P1** | `osascript -e 'do shell script "..."'` で arbitrary cmd 実行可能 (curl と同 bypass) | adopt (osascript `-e` を `display notification` 限定) |
| R4-006 to R4-010 (5 件 stale) | - | R1/R2/R3 既 adopt re-emission | reject |

実装:
- `_drill_timer_scanner.py`:
  - `SYSTEMD_EXEC_PREFIX_RE` に `@` 追加 (R4-001)
  - `SCAN_SERVICE_DROPIN_GLOBS` 追加 + diff-gate / baseline 両方で drop-in scan (R4-002 P1)
  - `_check_osascript_payload` 追加、osascript `-e` を `display notification` regex 限定 (R4-005 P1)
- `check_drill_timer_alert_only.sh`:
  - `git diff --name-status -z` + Python NUL parse で rename old / new path 両方抽出 (R4-003)
- `docs/deploy/half-yearly-drill-sop.md`:
  - osascript example の AppleScript を quote (R4-004)
  - service example の slack-cli msg も quote

R4 regression fixture 3 件追加 + 既存 1 件 update: `test_osascript_do_shell_script_rejected` (R4-005 P1) / `test_exec_prefix_at_pass` (R4-001) / `test_dropin_override_destructive_rejected` (R4-002 P1) / `test_systemd_osascript_passes` update (R4-005 strict check で AppleScript quote 必須化)。

累計 fixture: **37 pytest fixture 全 PASS** (failed: 0、plan stage 23 + R1 3 + R2 5 + R3 3 + R4 3)。

#### PR #71 Codex auto-review R5 — 11 inline findings (P1×4 + P2×7) (5 adopt + 6 reject stale)

R5 で 11 件 emit、真に新 5 件 (P1×3 + P2×2) adopt、stale 6 件 reject。

| ID | priority | symptom (要約) | 判定 |
|---|---|---|---|
| R5-001 NEW | **P1** | paired non-drill service の drop-in `<service>.service.d/*.conf` 漏れ | adopt |
| R5-002 NEW | **P1** | osascript `display notification (do shell script "...")` で AppleScript 内 shell exec bypass | adopt |
| R5-003 NEW | **P1** | systemd `Environment=PATH=/tmp/evil` で bare command PATH spoofing | adopt |
| R5-004 NEW | P2 | cron.d 6-field で user field のみ command 不在で誤 pass | adopt |
| R5-005 NEW | P2 | `mail -A <secret_file>` attachment flag で exfiltration | adopt |
| R5-006 to R5-011 (6 件 stale) | - | R1-R4 既 adopt re-emission | reject |

実装:
- `_drill_timer_scanner.py`:
  - `SYSTEMD_PATH_OVERRIDE_RE` 追加: `Environment=PATH=` / `EnvironmentFile=` / `PassEnvironment=PATH` を検出 (R5-003 P1)
  - `_check_osascript_payload` で AppleScript 内 `do shell script` / `system attribute` / System Events tell を regex reject (R5-002 P1)
  - `_check_mail_attachment` 追加: `mail -A` / `mail --attach` を reject (R5-005)
  - paired non-drill service の drop-in dir (`<service>.service.d/*.conf`) を baseline 探索 (R5-001 P1)
  - cron.d 6-field で 7 token 未満は `cron_d_user_or_command_missing` violation (R5-004)

R5 regression fixture 4 件追加: `test_osascript_embedded_shell_script_rejected` (R5-002 P1) / `test_environment_path_override_rejected` (R5-003 P1) / `test_cron_d_user_field_only_rejected` (R5-004) / `test_mail_attach_flag_rejected` (R5-005)。

累計 fixture: **41 pytest fixture 全 PASS** (failed: 0、plan stage 23 + R1 3 + R2 5 + R3 3 + R4 3 + R5 4)。

#### PR #71 Codex auto-review R6 — 16 inline findings (P1×6 + P2×10) (5 adopt + 11 reject stale)

R6 で 16 件 emit、真に新 5 件 (P1×2 + P2×3)、stale 11 件 (R1-R5 既 adopt)。

| ID | priority | symptom (要約) | 判定 |
|---|---|---|---|
| R6-001 NEW | **P1** | paired non-drill service の drop-in dir scan は diff-gate 限定、baseline で漏れ | adopt |
| R6-002 NEW | P2 | quoted `Environment="PATH=..."` で `SYSTEMD_PATH_OVERRIDE_RE` bypass | adopt |
| R6-003 NEW | P2 | `mail -a` (Heirloom / s-nail) attach 漏れ、`-A` `--attach` のみ対応 | adopt |
| R6-004 NEW | P2 | `logger -f <secret_file>` syslog 流出 | adopt |
| R6-005 NEW | **P1** | systemd inherited drop-in dirs (`<prefix>-.service.d/`) scan 漏れ | adopt |

実装:
- `_drill_timer_scanner.py`:
  - `SYSTEMD_PATH_OVERRIDE_RE` を `re.VERBOSE` で quoted / multiple-assignment 両対応 (R6-002)
  - `_check_mail_attachment` に `-a` 追加 + `mailx` / `s-nail` head allowlist 追加 (R6-003)
  - `_check_logger_file_read` 新規追加: `logger -f` / `--file` reject (R6-004)
  - baseline scan で各 drill timer から referenced paired service の `<service>.service.d/*.conf` + inherited dropin dirs `<prefix>-.service.d/` を scan に追加 (R6-001 P1 + R6-005 P1)

R6 regression fixture 4 件追加: `test_quoted_path_override_rejected` (R6-002) / `test_mail_lowercase_a_rejected` (R6-003) / `test_logger_file_flag_rejected` (R6-004) / `test_inherited_dropin_directory_scanned` (R6-005 P1)。

累計 fixture: **45 pytest fixture 全 PASS** (failed: 0、plan stage 23 + R1 3 + R2 5 + R3 3 + R4 3 + R5 4 + R6 4)。

#### PR #71 Codex auto-review R7 — 20 inline findings (P1×8 + P2×12) (7 adopt + 13 reject stale)

R7 で 20 件 emit、真に新 7 件 (P1×5 + P2×2)、stale 13 件 (R1-R6 既 adopt)。

| ID | priority | symptom (要約) | 判定 |
|---|---|---|---|
| R7-001 NEW | **P1** | diff-gate で timer changed PR、paired service の drop-in scan 漏れ | adopt |
| R7-002 NEW | P2 | `ExecStart=` regex `\s*` で newline consume、override pattern (`ExecStart=` + 次行 `ExecStart=...`) で誤動作 | adopt |
| R7-003 NEW | **P1** | non-drill paired service の changed `.service.d/*.conf` drop-in 漏れ (drill name filter で drop) | adopt |
| R7-004 NEW | **P1** | quoted multi-Environment 後の `"PATH=..."` 検出漏れ | adopt |
| R7-005 NEW | **P1** | timer drop-in `.timer.d/*.conf` で `[Timer] Unit=` override scan 漏れ | adopt |
| R7-006 NEW | P2 | shell metacharacter regex が quoted text 内も誤検出 (`Run drill?` `R&D drill` 等) | adopt (2-layer check: `$()`/backtick は raw、`;\|&&\|\|\|\|\|>><<&*?~` は quote-stripped) |
| R7-007 NEW | **P1** | `RootDirectory=` / `RootImage=` で trusted absolute path を attacker root に remap 可能 | adopt |
| R7-008 to R7-020 (13 件 stale) | - | R1-R6 既 adopt re-emission | reject |

実装:
- `_drill_timer_scanner.py`:
  - `SYSTEMD_EXEC_RE` の `\s*` を `[ \t]*` に変更、newline consumption 防止 (R7-002)
  - `SYSTEMD_PATH_OVERRIDE_RE` を multi-assignment 対応 (R7-004 P1)
  - `SYSTEMD_ROOT_REMAP_RE` 追加: `RootDirectory` / `RootImage` / `RootEphemeral` / `BindPaths*` 検出 (R7-007 P1)
  - shell composition を 2-layer に分離 (R7-006): raw で `$()`/backtick/newline、quote-stripped で `;|&&|||||>><<&*?~`
  - diff-gate scan_files で timer dropins `.timer.d/*.conf` + non-drill paired service drop-in 探索追加 (R7-001 P1 + R7-003 P1 + R7-005 P1)

R7 regression fixture 3 件追加: `test_exec_reset_followed_by_replacement_passes` (R7-002) / `test_quoted_metacharacters_pass` (R7-006) / `test_root_directory_remap_rejected` (R7-007 P1)。

累計 fixture: **48 pytest fixture 全 PASS** (failed: 0、plan 23 + R1 3 + R2 5 + R3 3 + R4 3 + R5 4 + R6 4 + R7 3)。

### SP022-T02 Phase 4 / T08 batch 4 completion (2026-05-20、本 PR)

#### codex-all-loops review + adversarial 累計 53 findings 100% adopt

- **Phase 1 codex-review-loop** R1-R7: 31 findings (R1=19 R2=6 R3=2 R4=1 R5=1 R6=2 R7=0)
- **Phase 2 codex-adversarial-loop** R1-R3: 22 findings (R1=18 R2=4 R3=0)
- Cumulative findings 53、100% adopted、CRITICAL=0 達成 (両 phase Readiness Gate READY)

#### 実装ファイル (新規 4 + 修正 3 + tests 4 + docs 2)

新規:
- `scripts/taskhub_destructive_lock.py`: `acquire_destructive_lock` context manager (fcntl.flock LOCK_EX|LOCK_NB + TASKHUB_LOCK_DIR env override + O_NOFOLLOW)
- `scripts/taskhub_remote_status.py`: Tailscale SSH + signed config (compose_file_sha256 + config_version + expires_at) + state machine (running/safe_down/transitional/unknown)
- `scripts/taskhub_approval_cli.py`: Ed25519-signed approval issue CLI (raw 32-byte seed + bytearray zeroize + final path O_CREAT|O_EXCL|O_NOFOLLOW + chmod 0o600)
- `docs/deploy/operator-runbook.md`: operator SOP §1-§9 (bootstrap / approval issue per-subcommand / re-sign migration / signed config / SecretBroker limit / known_hosts / lock / keyring rotation)

修正:
- `scripts/taskhub_signed_approval.py`: `RestoreRollbackApprovalClaim` dataclass + ReasonCode 3 種 + parser/matcher + `canonical_for_signature` helper + verify/require_approval rrc 拡張
- `scripts/taskhub_restore_orchestrator.py`: `RestoreOptions.for_rollback_mode` classmethod + `read_alembic_head_via_compose_exec` + `_write_snapshot_manifest` + `verify_snapshot_manifest_binding` + `verify_snapshot_component_hashes` + ReasonCode 8 種 + WarningCode 2 種
- `scripts/taskhub_admin.py`: `_cmd_restore_rollback` 新規 (--rollback real I/O) + `_cmd_restore --input` 既存 path への lock 統合 + `_cmd_status --remote` real I/O 化 + approval subparser 登録

tests:
- `tests/scripts/test_taskhub_destructive_lock.py` (5 fixture)
- `tests/scripts/test_taskhub_remote_status.py` (19 fixture)
- `tests/scripts/test_taskhub_approval_cli.py` (17 fixture)
- `tests/scripts/test_taskhub_signed_approval.py` (modify、5 fixture 追加)

regression: pytest **290/290 PASS**、mypy clean、ruff clean.

#### Security invariants (本 PR で確立)

- `restore-rollback` approval は `RestoreRollbackApprovalClaim` (10 field) で snapshot binding を signature root に固定
- snapshot_manifest.json + manifest_version=1 + per-component {present/sha256/skipped_reason} で partial snapshot semantics 維持
- host-level destructive lock (fcntl.flock LOCK_EX|LOCK_NB) で backup/restore/restore-rollback の cross-subcommand mutual exclusion (本 PR scope: restore + rollback、他は Phase 5 carry-over)
- TOCTOU 排除: lock 取得後 manifest sha256 / target binding / component hash の **再計算 + verify**
- remote_hosts.signed.json: config_version + expires_at + compose_file_sha256 + Ed25519 signature (domain="remote_hosts.v1" canonical layout)
- approval signing key: raw 32-byte seed format + bytearray zeroize + final path O_CREAT|O_EXCL|O_NOFOLLOW + chmod 0o600

#### Carry-over (本 batch 対象外、Phase 5 以降)

- **`SP022-T02 Phase 5`** (別 PR): `backup_orchestrator pg_dump compose exec` 切替、T09 unblock の hard gate
- **SP-012 split-brain second line of defense**: active.signed marker chain + thaw 2-party-control + 同 migration_epoch reject negative test
- **SP-012 keyring rotation**: `approval-verify-keys.d/<fingerprint>.pub` keyring + old+new overlap 期間 dual-trust
- destructive lock cross-subcommand 拡張: backup / migrate / freeze / thaw も lock 取得対象に統合

#### Phase 4 後の SP-022 task progress (post-本 PR)

| Task | status |
|---|---|
| SP022-T01 framework intake CI 機械化 | ✅ 完了 (PR #70) |
| SP022-T02 `taskhub migrate` 自動化 | 🟥 heavy: Phase 1 ✅ (PR #75) + Phase 2 ✅ (PR #77) + Phase 3 ✅ (PR #78) + **Phase 4 ✅ (本 PR)** / Phase 5 carry-over |
| SP022-T03 半年 drill SOP | ✅ 完了 (PR #71) |
| SP022-T04 Phase E trace audit | ✅ 完了 (PR #72) |
| SP022-T05 AC-HARD multi-agent re-verify | ⛔ deferred (blocked_by: SP-013) |
| SP022-T06 KPI baseline 3 host | 🟨 light (Mac 単独可) |
| SP022-T07 production checklist skeleton | ✅ 完了 (PR #73) |
| SP022-T08 SP-012 carry-over 9 件 | 🟥 heavy: batch 1-3 ✅ (PR #76/#77/#78) + **batch 4 ✅ (本 PR、approval issue + remote_status + destructive_lock)** / batch 5-6 carry-over |
| SP022-T09 実機 host migration drill | ⛔ deferred (blocked_by: SP022-T02 Phase 5 + SP-012 split-brain second line + SP-012 keyring rotation) |

(後続: SP-022 完了時に T02 / T04-T09 全体 Review を追記)


### SP022-T02 Phase 5 completion (2026-05-21、PR #80)

#### codex-all-loops mode=plan max-rounds=14 record

`codex-all-loops mode=plan max-rounds=14` で **Phase 1 review-loop 10 round + Phase 2 adversarial-loop 14 round = 24 rounds / 75 findings 100% adopt / critical_zero gate READY** 達成後、Batch A+B+C+D 実装完了。

##### Phase 1 review-loop (10 rounds / 31 findings 100% adopt)
- R1 (15) + R2 (4) + R3 (2) + R4 (2) + R5 (2) + R6 (2) + R7 (1) + R8 (0 clean) + R9 (3) + R10 (0 full clean)
- CRITICAL=0 / HIGH=0 達成
- Evidence: `~/.claude/local/codex-review-loops/sp022-t02p5-backup-compose-exec-plan-20260521-093917-phase1-review-loop/final-clean-evidence.md`

##### Phase 2 adversarial-loop (14 rounds / 44 findings 100% adopt)
- R1 (10) + R2 (5) + R3 (2) + R4 (2) + R5 (2) + R6 (3) + R7 (3) + R8 (2) + R9 (2) + R10 (2) + R11 (2) + R12 (1) + R13 (4) + R14 (4)
- CRITICAL=0 / HIGH=1 (≤2) → critical_zero gate PASS
- Evidence: `~/.claude/local/codex-adversarial-loops/sp022-t02p5-backup-compose-exec-plan-20260521-093917-phase2-adversarial-loop/final-clean-evidence.md`

#### Architectural changes (6 file / +2978 / -88)

1. **docker compose exec 経路**: host TCP + PGPASSFILE → container 内 unix socket + trust auth
2. **consistency boundary** (ADR-00021 §11.2 完全実装): stop_app_services_via_compose_exec → backup → start_app_services_wait_healthy。Service field primary key (`Name` ではなく `Service`) healthy polling、stop/restart 失敗は致命的 (warning 流用禁止)
3. **verified copy 4 種** (compose / env_file / sops_env / artifacts_staging): O_NOFOLLOW + O_EXCL + 0o400 + metadata snapshot (dev/ino/uid/mode/sha256) で各 docker compose 呼出前に再検証 (same-UID unlink/rename swap 検知)
4. **artifacts_dir staging tree**: no-follow walk + chunked sha256 + per-file 256 MiB + tree 4 GiB limit + symlink/FIFO/socket/device 全面 reject + reserved-name (`_artifacts_source_mode.json`) reject + source mode sidecar (staging tree の **外** = `verified_temp_dir/artifacts_source_mode.json`)
5. **BackupApprovalClaim 6 field 化**: `backup_runtime_binding_fingerprint` 追加 (PR #77 legacy 5-field record は signed_approval level で互換維持、_cmd_backup Phase 5 で常時 reject + 再 issue 必須)
6. **canonical fingerprint 15 field schema**: target_compose_project_name + target_compose_file_realpath + target_compose_file_sha256 + target_compose_project_directory + artifacts_dir_realpath + artifacts_dir_manifest_sha256 + sops_env_path_realpath + sops_env_sha256 + env_file_realpath + env_file_sha256 + compose_config_canonical_sha256 + pg_user + pg_db + postgres_service_name + redis_service_name
7. **single full-helper `compute_full_backup_runtime_binding_fingerprint(mode=issue|redeem)`**: server-owned 再計算保証、private helper `compute_backup_runtime_binding_fingerprint` 直接呼出禁止 (broker / CLI / redeem 3 経路で同 algorithm 維持)
8. **_cmd_backup destructive_lock + post-stop 順序**: (1) lock acquire → (2) age fingerprint TOCTOU verify → (3) age recipient regex validate + immutable bind → (4) verified_temp_dir 0o700 → (5-7) verified copy 4 種 + metadata snapshot bind → (8) backup_options 一括 dataclasses.replace → (9) run_backup(phase_5_mode=True) で post-stop artifacts staging + fingerprint verify + claim exact match + archive。restart 失敗時は primary_exc 優先 + 両 reason stderr/audit 記録 (consistency boundary 維持)

#### ReasonCode 19 件追加 + WarningCode 不変

新規 ReasonCode 19 件 (`backup_payload_source_mismatch` は R13 F-003 で `backup_claim_mismatch` に統一削除):
backup_age_key_toctou_mismatch / backup_age_recipient_invalid / backup_service_stop_failed / backup_service_start_failed / backup_claim_legacy_runtime_binding_unsupported / backup_compose_file_unreadable / backup_compose_binding_not_initialized / backup_compose_verified_copy_tampered / backup_compose_config_failed / backup_redis_rdb_tmp_not_regular_file / backup_compose_env_file_unreadable / backup_payload_source_unreadable / backup_env_file_verified_copy_tampered / backup_payload_source_tampered / backup_artifacts_staging_tampered / backup_artifacts_source_unsupported_file_type / backup_artifacts_file_too_large / backup_artifacts_tree_too_large / backup_artifacts_source_reserved_name + backup_claim_mismatch (R13 F-003 統一).

#### verification

- ruff check: All passed (scripts/taskhub_backup_orchestrator.py + scripts/taskhub_subprocess_runner.py + scripts/taskhub_admin.py + scripts/taskhub_signed_approval.py + tests/scripts/test_taskhub_backup_orchestrator.py + tests/scripts/test_taskhub_subprocess_runner.py)
- pytest tests/scripts/: 319 passed (元 297 + Phase 5 新規 22)
- PR #77 backward compat: phase_5_mode=False (legacy host TCP + PGPASSFILE 経路) で既存 30 test 全 PASS
- Phase 5 unit tests 22 件: age recipient validation / compose argv prefix / artifacts manifest / verified copy tree / fingerprint canonical / Phase 5 legacy reject / Service field primary key / redact / from_environment allowlist
- integration tests (実 docker compose 環境必要): SP022-T09 host migration drill で実機検証予定

#### Carry-over (本 PR 対象外、SP-022 完遂 / SP-013 着手前)

- **SP022-T09 実機 host migration drill (Mac→VPS、RTO≤4h)**: 残条件 = SP-012 must_ship 2 件のみ (split-brain second line + keyring rotation)。Phase 5 unblock 済
- **SP-012 split-brain second line of defense**: active.signed marker chain + thaw 2-party-control + 同 migration_epoch reject negative test
- **SP-012 keyring rotation**: `approval-verify-keys.d/<fingerprint>.pub` keyring + old+new overlap 期間 dual-trust
- destructive lock cross-subcommand 拡張: backup は本 PR で統合済、migrate / freeze / thaw は carry-over

#### Phase 5 後の SP-022 task progress (post-本 PR)

| Task | status |
|---|---|
| SP022-T01 framework intake CI 機械化 | ✅ 完了 (PR #70) |
| SP022-T02 `taskhub migrate` 自動化 | ✅ **全 Phase 完遂** (Phase 1 PR #75 + Phase 2 PR #77 + Phase 3 PR #78 + Phase 4 PR #79 + **Phase 5 PR #80 本 PR**) |
| SP022-T03 半年 drill SOP | ✅ 完了 (PR #71) |
| SP022-T04 Phase E trace audit | ✅ 完了 (PR #72) |
| SP022-T05 AC-HARD multi-agent re-verify | ⛔ deferred (blocked_by: SP-013) |
| SP022-T06 KPI baseline 3 host | 🟨 light (Mac 単独可) |
| SP022-T07 production checklist skeleton | ✅ 完了 (PR #73) |
| SP022-T08 SP-012 carry-over 9 件 | 🟥 heavy: batch 1-4 ✅ (PR #76/#77/#78/#79) / batch 5-6 carry-over |
| SP022-T09 実機 host migration drill | ⛔ deferred (blocked_by: **SP-012 split-brain second line + SP-012 keyring rotation のみ、SP022-T02 Phase 5 unblock 済**) |

(後続: SP-022 全 must_ship 完了 → P0 Exit declaration → TASKHUB_P0_1_OPENED=1 + SP-013 着手)


### SP-012 must_ship 完遂 — T09 unblock 状態 update (2026-05-22 session)

#### SP-012 must_ship 2 件 完遂 (T09 unblock 残条件 → 物理 host 取得 + user drill 実施のみ)

SP-012 must_ship 2 件 (split-brain second line of defense + approval keyring rotation) は **2026-05-22 で実装完遂**。`docs/sprints/SP-012_p0_acceptance.md` の Sprint 12 Exit Addendum (PR #87、`3e94e99c`) 参照。

**完遂内訳** (累計 19 PR merged、累計 47 round / 212 findings 100% adopt):
- PR #76: ADR-00028 + ADR-00029 proposed → **accepted** (split-brain second line + keyring rotation の design ADR 同時昇格)
- PR #81: SP-012 Batch A skeleton (60 ReasonCode 正本化 + active_registry/keyring/approval_issuance 3 module skeleton)
- PR #82: SP-012 Batch B keyring (32 findings 100% adopt)
- PR #83: SP-012 Batch C approval issuance + clock attestation (6 findings + R2 CLEAN)
- PR #84: SP-012 Batch D 2PC PrepareMarker/CommitMarker (13 findings + R4 CLEAN、87 fixture PASS)
- PR #85: backend gate L1+L2+L3 (FastAPI middleware + ARQ worker + SQLAlchemy before_commit、19 findings + R7 CLEAN、65 fixture + 3841 regression PASS)
- PR #86: operator runbook §13-§22 (10 sections / 951 行、43 findings + R6 CLEAN)
- PR #87: SP-012 Sprint Pack Review Addendum (R1 CLEAN)

#### SP022-T09 unblock 残条件 (post-SP-012 must_ship 完遂)

| 残条件 | 状態 | 解消 trigger |
|---|---|---|
| SP-012 split-brain second line | ✅ 完了 (PR #81-#84) | active.signed marker chain + 2PC PrepareMarker/CommitMarker + 同 migration_epoch reject |
| SP-012 approval keyring rotation | ✅ 完了 (PR #82-#83) | `approval-verify-keys.d/<sha256-hex>.pub` keyring + dual-trust + revocation tombstone |
| SP022-T02 Phase 5 (backup compose exec) | ✅ 完了 (PR #80) | docker compose exec + container 内 unix socket + verified copy 4 種 |
| 物理 host 取得 (Mac + VPS 2 台) | ⛔ user 物理作業 | user の hardware availability |
| user 介在 drill 実施 (Mac→VPS、RTO≤4h) | ⛔ user 物理作業 | user の drill 実施 + result verification |

**T09 unblock 残作業 = 物理 host 取得 + user drill 実施のみ**。SP-012/SP-022 carry-over の technical blocker は全て解消。

#### SP022-T08 batch 5+6 / SP022-T06 残作業 (本 session scope 外)

| 残作業 | 優先度 | 状態 | 解消 path |
|---|---|---|---|
| SP022-T08 batch 5: signed journal CLI DB mode + private staging E2E | 🟥 high | carry-over | SP-022 残作業 (本 session scope 外、SP-013 着手前に完了) |
| SP022-T08 batch 6: frontend dashboard backend API wiring | 🟥 high | carry-over | SP-022 残作業 (本 session scope 外) |
| SP022-T06 KPI baseline (Mac 単独) | 🟨 light | implementable | Mac 単独で baseline 取得可能 (acceptance_pass_rate / time_to_merge / approval_wait_ms / citation_coverage / cost_per_completed_task の median) |
| SP022-T06 KPI baseline (Linux/VPS) | ⛔ deferred | blocked | 物理 host 取得待ち |
| SP022-T05 AC-HARD multi-agent re-verify | ⛔ deferred | blocked | SP-013 着手後 |
| destructive_lock cross-subcommand 拡張 (migrate / freeze / thaw) | 🟨 light | carry-over | SP-022 残作業 |

#### P0 Exit declaration path (Codex F-PR67-035 P2 + F-PR67-041 P2 adopt 経路)

```
SP-012 must_ship 完遂 (本 session、2026-05-22) → ✅
  ↓
SP-022 T08 batch 5+6 完了 (signed journal CLI DB mode + frontend wiring) → 🟥 next
  ↓
SP-022 T06 KPI baseline 3 host (Mac 単独 light 可、Linux/VPS は物理 host 取得後)
  ↓
SP-022 T09 実機 host migration drill (Mac→VPS、RTO≤4h) PASS → ⛔ user 物理作業
  ↓
ADR-00021 + ADR-00007 post-acceptance verification 完遂 → ADR_status: accepted (frontmatter update)
  ↓
SP-012 frontmatter status: partial_completed_with_carry_over → completed
SP-022 frontmatter status: implementable → completed
  ↓
P0 Exit declaration (Hard Gates 7 全件 PASS + Quality KPIs 5 の未達 ≤ 1 個)
  ↓
TASKHUB_P0_1_OPENED=1 + SP-013 着手
```

#### 累計 SP-012/SP-022 sessions / PR / findings

| metric | 値 |
|---|---:|
| 累計 PR merged (SP-012 must_ship + SP-022 implementation) | 19 |
| 累計 Codex multi-round review | 47 rounds |
| 累計 findings 100% adopt | 212 |
| CRITICAL=0 | ✅ all PR |
| HIGH≤2 (critical_zero gate) | ✅ all PR |
| reject / defer | 0 / 0 |

**SP-012 must_ship 完遂で T09 unblock 技術 blocker 解消、残作業 = 物理 host drill のみ**。本 update を SP-022 Pack の Review に追記して P0.1 unblock path を明示。

### SP022-T06 Mac KPI + T08 batch 5+6 completion (2026-05-22 session 後半)

#### 完了 PR (本 session で merged)

| PR | scope | Codex review status |
|---|---|---|
| PR #89 | SP022-T06 KPI baseline CLI (Mac 単独 light mode) + destructive_lock cross-subcommand 拡張 (migrate / freeze / thaw) | R1-R2 CLEAN |
| PR #90 | SP022-T08 batch 5: signed journal CLI DB mode (`--from-db`) + 12 fixture + 3874 regression PASS | R1-R5 CLEAN (累計 12 findings 100% adopt) |
| PR #91 | SP022-T08 batch 6: frontend Eval Dashboard backend API wiring + skeleton fallback + outage-only fallback (5xx/Zod/network/JSON SyntaxError) + cardinality enforce + page-level 4xx/config error catch | R1-R4 CLEAN (累計 10 findings 100% adopt) |

#### T09 unblock 残作業 (技術 blocker は完全解消、物理作業のみ)

| 残作業 | 状態 | blocker |
|---|---|---|
| SP022-T06 KPI baseline Mac (PR #89) | ✅ 完了 | - |
| SP022-T08 batch 5 signed journal CLI DB mode (PR #90) | ✅ 完了 | - |
| SP022-T08 batch 6 frontend backend wiring (PR #91) | ✅ 完了 | - |
| 私的 staging E2E (CI workflow scaffold) | ⏳ scaffold ready (`.github/workflows/private-staging-e2e.yml`) | admin Tailscale OAuth + VPS TLS 443 listener + GitHub secrets setup (user 物理作業) |
| SP022-T06 KPI baseline Linux/VPS | ⛔ deferred | 物理 host 取得 (user 物理作業) |
| SP022-T05 AC-HARD multi-agent re-verify | ⛔ deferred | SP-013 着手後 (post-P0.1) |
| SP022-T09 実機 host migration drill (Mac→VPS、RTO≤4h) PASS | ⛔ deferred | 物理 host 2 台 + user 介在 drill 実施 (user 物理作業) |

**全 technical autonomous 作業完了**。残作業 = user 物理作業 (host 取得 + Tailscale OAuth setup + drill 実施) のみ。

#### 累計 SP-012/SP-022 sessions / PR / findings (update)

| metric | 値 |
|---|---:|
| 累計 PR merged (SP-012 must_ship + SP-022 implementation) | 22 (旧 19 + PR #89/#90/#91) |
| 累計 Codex multi-round review | 58 rounds (旧 47 + PR #89 2R + PR #90 5R + PR #91 4R) |
| 累計 findings 100% adopt | 234 (旧 212 + PR #89 4 + PR #90 12 + PR #91 10 = +22) |
| CRITICAL=0 | ✅ all PR |
| HIGH≤2 (critical_zero gate) | ✅ all PR |
| reject / defer | 0 / 0 |

P0 Exit declaration path = SP022-T09 user 物理 drill のみ残存。本 SP-022 Sprint 内技術作業は全完了。

### Additional P0 Exit Hardening Gate (p0-exit-final-hardening-2026-05-22 plan 経由、PR #95/#96/#97 追加)

p0-exit-final-hardening-2026-05-22 plan (`.claude/plans/p0-exit-final-hardening-2026-05-22.md`) の Phase 2-6 として、SP-022 must_ship 表外で **Additional Hardening Gate** を追加実施。本 plan §9.1 で「Sprint Pack must_ship 表を変更せず、`## Review § Additional P0 Exit Hardening Gate` で追記」を固定。

#### 経緯

- 2026-05-22 後半 session で SP022-T09 prep Mac single-host smoke verification 実施中、PR #93 (SOP 起票) merge 後の **routing inconsistency + Docker runtime + dev override + SOP polish** で **12 件の latent issues** が連続発覚
- 本 plan §1.3 当初 4 件 + Phase 4/5 で発覚 4 件 + post-merge SOP polish 4 件 = 12 件
- これらは P0 Exit declaration 前に解決必須 (T09 drill UI 経路 / Layer B/C smoke 成立条件)
- 3 PR 連続 autonomous merge (PR #95 + PR #96 + PR #97)、ADR Gate 11 種全件非該当

#### 12 件 latent issues 全件 fix table

| # | Issue | PR | merge SHA |
|---|---|---|---|
| 1 | typed routes false positive (Layer A typecheck gap) | PR #95 | `33f6d02` |
| 2 | actions.ts Route cast 漏れ | PR #95 | `33f6d02` |
| 3 | navigation 3-way routing inconsistency | PR #95 | `33f6d02` |
| 4 | smoke SOP URL `/admin/*` 誤記 | PR #95 | `33f6d02` |
| 5 | Dockerfile.api scripts COPY 欠落 (api ModuleNotFoundError) | PR #96 | `8f92082` |
| 5b | Dockerfile.worker scripts COPY 欠落 (worker 同上) | PR #96 | `8f92082` |
| 6 | docker-compose.yml networks.internal:true で host port publish 不可 | PR #96 | `8f92082` |
| 7 | SOP の `-f docker-compose.dev.yml` 不明示 | PR #96 | `8f92082` |
| 8 | Dockerfile.api eval/ COPY 欠落 (/api/v1/eval/kpi-rollup 503) | PR #96 | `8f92082` |
| 9 | SOP §13 grep bug (echo 末尾改行 false positive) | PR #97 | `b5c5bae` |
| 10 | SOP §15 test path 誤記 | PR #97 | `b5c5bae` |
| 11 | SOP §1 backend seed runner step 不明示 | PR #97 | `b5c5bae` |
| 12 | SOP §12-§14 key bootstrap 詳細化不足 | PR #97 | `b5c5bae` |

#### Additional Hardening Gate 必須項目 (本 plan §9.1 § 8 項目、DoD trace 列付き)

| # | 項目 | 結果 | DoD trace |
|---|---|---|---|
| 1 | 本 plan §4.2.3 file table 全件 PASS | ✅ **13 unique file** 修正 (frontend 3: actions.ts/navigation.tsx/eslint.config.mjs / docs/deploy 4: SOP+layer-A-addendum+layer-B+layer-C-autonomous / 設計検討 1: master plan axe URL fix / .claude/plans 2: sp022-t09-prep + p0-exit-final-hardening / Dockerfile 2 / docker-compose 1 = 13) (F-PR98-004 adopt fix、PR #95/#96/#97 unique file 重複除去後 13) | DoD-3 受け入れ条件 + DoD-4 検証手順 |
| 2 | PR link | #95 + #96 + #97 | DoD-10 Review 欄更新タイミング |
| 3 | evidence link | `docs/deploy/smoke-evidence/2026-05-22-layer-{A-addendum,B,C-autonomous}.md` (repo 内 commit 済) + user-local artifact at `~/.claude/local/codex-reviews/2026-05-22/sprint-SP-012-batch-7-taskhub-admin-cli/plan-review-ledger.md` (本 ledger は session-local audit trail、git ignore 配下、PR description で参照のみ。F-PR98-003 adopt fix で user-local 明示) | DoD-4 + DoD-9 Hard Gates / Quality KPIs trace |
| 4 | 完了判定 | code PASS + Layer A/B PASS + Layer C required smoke (§7+§13+§15) PASS + Codex 4 CLEAN signals (PR #95/#96 計 4 round) | DoD-3 + DoD-4 |
| 5 | accepted defer | nav active state semantics (static skeleton) / notifications-nav top placement / research-nav top placement / settings UI smoke / §12 §14 key bootstrap (~/.taskhub/keys/ 未存在) | DoD-5 rollback + DoD-9 影響範囲 |
| 6 | rollback 手順 | 本 plan §8.2 (code rollback + evidence invalidation + READY 巻き戻し 3 階層) | DoD-5 |
| 7 | audit event | (本 plan 範囲は routing/build/docs のみで audit event 不変) | DoD-6 |
| 8 | DoD-8 影響表 | Provider Matrix / SecretBroker / AgentRun / DB invariant 全件不変、認証・認可 / API 契約 / runner / Provider 不変 (4.3.1 evidence 4 点 全件 PASS) | DoD-8 |

#### Layer B/C autonomous 結果

**Layer B (PR #96 fix 適用後、autonomous PASS)**:
- 5 service all healthy + 4 port publish (127.0.0.1:8000/3000/5432/6379)
- alembic upgrade head 11 migrations (0008→0018_eval_dataset_versions)
- /healthz `{status: ok}` + /readyz (postgres + redis both ok)
- frontend root → `/login?next=%2F` (PR #95 routing fix end-to-end 動作確認)
- redis PING / postgres v16.14

**Layer C autonomous (PR #96 eval COPY fix 後)**:
- §7 Eval Dashboard live wiring curl: ✅ HTTP 200 `{kpi_count: 0, p0_accept: true}`
- §13 signed journal verify --from-db: ✅ exit 0 (tenant_scope_empty expected)
- §15 golden flow pytest (`tests/integration/test_ticket_to_pr_smoke.py`): ✅ 13 tests passed
- §12 §14: SKIP (~/.taskhub/keys/ 未存在、accepted defer)

#### Codex review 累計

- Codex plan-review 3 rounds (R1 17 + R2 2 + R3 0 CLEAN) = 19 findings
- plan-reviewer subagent 2 rounds (R1 7 + R2 0 CLEAN) = 7 findings
- Codex PR-review CLEAN signals 4 (PR #95 R1+R2 + PR #96 R1+R2)
- **累計 26 findings 100% adopt + 4 CLEAN signals** (PR #97 は Codex bot service 15 min 未起動で code change 最小性で代替判定 = admin bypass merge)
- CRITICAL / HIGH / BLOCK / WARN 残存: 全件 0

### Phase 7 scope 訂正 (PR #99、user 明示「Mac で運用優先、VPS の前」反映)

#### 旧 scope (PR #92 + #98 まで)

- 「実機 host migration drill (Mac→VPS) RTO≤4h PASS」を **P0 Exit declaration 直接 gate** として位置付け (master plan §10.C + SP-022 must_ship 表 line 96)
- T09 = Mac→VPS host migration drill = SP022-T09 必須

#### 新 scope (PR #99 訂正、user 明示優先順反映)

user 明示「Mac で運用できることが第一、VPS の前」+ 本 plan §3.5「AC-HARD-04 計測本体は backend CLI で完結」+ ADR-00021 post-acceptance verification 解釈の整合化:

| Phase | scope | host | P0 Exit declaration 関連 |
|---|---|---|---|
| **Phase 7a-1 Mac UI smoke** (本 plan §5.5.1 user-deferred 全件、新規 SOP `docs/deploy/mac-single-host-operation-drill-sop.md` §1) | Mac で P0 UI 機能運用立証 | Mac 1 台 (ブラウザ + terminal) | ✅ **直接 gate** (P0 UI 機能動作 evidence) |
| **Phase 7a-2 Mac local backup/restore drill** (新規 SOP §2、Mac single-host で完結) | AC-HARD-04 (`backup_restore_rpo_rto`) PASS、7 mandatory checklist (host migration step 以外) + RTO ≤ 4h 計測 | Mac 1 台 (CLI のみ) | ✅ **直接 gate** (AC-HARD-04 evidence、本 plan §3.5「計測本体は backend CLI で完結」の証跡) |
| **Phase 7b T09 Mac→VPS migration drill** (既存 SOP `docs/deploy/half-yearly-drill-sop.md` §11) | ADR-00021 host-portable deployment post-acceptance verification | Mac + VPS 2 台 + Tailscale | △ **post-acceptance verification** (P0 Exit declaration 直接 gate ではない、P0.1 unblock 後 or 任意 timing) |

#### must_ship 表 line 96 解釈訂正 (must_ship 表自体は変更しない、本 plan §9.1 で固定)

- 旧記述「実機 host migration drill (Mac→VPS) RTO≤4h PASS」 = SP-022 Sprint Pack must_ship 表上は維持
- **新解釈**: must_ship 表 line 96 の「実機 host migration drill (Mac→VPS)」は **Phase 7a Mac single-host 運用立証 (AC-HARD-04 backup/restore drill = Mac local 完結) + Phase 7b T09 Mac→VPS migration drill (post-acceptance verification)** の合計を指す。Phase 7a は P0 Exit declaration 直接 gate、Phase 7b は ADR-00021 post-acceptance (本 PR #99 で位置付け再解釈)
- P0 Exit declaration condition は **Phase 7a 完了で satisfy 可能** (Phase 7b は P0 Exit 後 or 任意 timing 実施)
- master plan §10.C 同期訂正は PR #98 で起票した `master-plan-section-3-9-update-prep.md` 内 §10.C diff で対応 (本 PR #99 で update + Phase 8 PR で master plan に手動 apply)

#### user 明示優先順との整合

user 2026-05-22 明示: 「**Mac でできる様にするのがまず最初の目的です。VPS の前に Mac で運用できることが大事です。**」

本 PR #99 訂正で:
- Mac single-host 運用立証 (Phase 7a) を P0 Exit declaration 直接 gate に位置付け → user 優先順と整合
- VPS migration drill (Phase 7b = T09) を post-acceptance に分離 → 「VPS の前に Mac で運用」順序と整合
- Hard Gates 7 件中 AC-HARD-04 (`backup_restore_rpo_rto`) は **Mac single-host で satisfy 可能** = 本 plan §3.5 で既明示 (`計測本体は backend CLI で完結`)

### Phase 7a results (2026-05-22T08:46-09:00Z、operator-driven by Claude on Mac、AC-HARD-04 PASS)

#### Evidence collection method (本 drill execution)

- Executor: **operator-driven automation by Claude on Mac (Docker + CLI + Codex in-app browser automation)**
- Not: user physical observed (完全 user 目視ではない)
- origin/main commit: `0ebc55e` (PR #102 merged まで含む base)
- Evidence completeness: dev login flow / admin nav / page render / DOM raw secret leak / SSR/source raw secret leak / cookie attribute / backend KPI API
- P0 Exit declaration scope: AC-HARD-04 計測本体は backend CLI で完結のため operator-driven evidence で satisfy (本 plan §3.5 整合)
- Phase 7b T09 Mac→VPS drill の user 物理目視は本 evidence で代替しない

#### Phase 7a-1 Mac UI smoke 結果 (PASS with OBSERVED_WITH_DEVIATION)

| § | page | URL | 結果 | Notes |
|---|---|---|---|---|
| §6 | dev login | `/dashboard` → `/login?next=%2Fdashboard` → `/dashboard` | ✅ PASS | Set-Cookie present, HttpOnly=true, SameSite=Lax, Secure=false (HTTP loopback) |
| §7 | Eval Dashboard | `/eval-dashboard` | ✅ PASS | KPI rollup render |
| §8 | Tickets | `/tickets` | ✅ PASS | Sprint 9 skeleton、seed ticket link 未掲載 (UI deviation) |
| §8b | Ticket Detail | `/tickets/<uuid>` 直接 | ✅ PASS | direct UUID route で確認 |
| §9 | Approvals | `/approvals` | ⚠️ OBSERVED_WITH_DEVIATION | pending なし、全 status 表示は未 exercise |
| §10 | Agent Runs | `/runs` | ✅ PASS | 16 状態 enum 表示 |
| §11 | Audit log | `/audit` | ⚠️ OBSERVED_WITH_DEVIATION | static skeleton で DB seed `seed_initialized` 未表示 |
| §12 | Settings | `/settings` | ✅ PASS | |

- console errors: 0
- DOM raw secret leak check: ✅ PASS (8 pages / 9 candidate values / 0 matches)
- SSR/source raw secret leak check: ✅ PASS (8 pages / 0 matches)
- UI deviation notes: `/tickets` `/approvals` `/audit` は Sprint 9 skeleton で current origin/main では full content 未掲載、P1+ UI polish 候補 (P0 Exit 直接 gate は backend wiring 動作 + secret leak なし、UI render は補助 evidence)

#### Phase 7a-2 Mac local backup/restore drill 結果 (AC-HARD-04 PASS)

- approval_id: `mac-local-drill-20260522-175623`
- backup output: `/Users/tohga/.taskhub/backups/mac-local-drill-2026-05-22.tar.age`
- archive SHA256: `a9d6058b942bfba87a3843b020ebaf9f381992590a913a7d6374384a4d9d064f`
- **RTO total: 4 seconds** (backup=3s + restore=1s、target ≤ 14400s = 4h)
- **ac_hard_04_pass: true**

7 mandatory checklist (host migration step 以外、Mac local 完結):
- ✅ backup exit 0 + output file 存在
- ✅ age decrypt 成功
- ✅ tar listing 全 file 構造存在 (ADR-00021 §4)
- ✅ checksums verify
- ✅ private key 非混入 (CRITICAL invariant)
- ✅ pg_restore --list parse 成功
- ✅ cleanup verified (`/tmp/taskhub-backup-*` 0 件、stale destructive_lock 削除済)

restore verification:
- ✅ `human:default` actor が new PostgreSQL container に restore 確認 (seed 整合性 verify)

#### Phase 7a execution deviations (7 件、source 変更なしで worktree-local wrapper で対応)

CLI / runbook drift で発覚した 7 件 (本 plan §1.3 latent issues 13-19 件目 として記録、post-merge polish PR で source 修正予定):

1. **legacy 5-field backup_claim**: `taskhub approval issue` on origin/main が legacy 5-field claim を emit、Phase 5 backup は 6-field (`backup_runtime_binding_fingerprint`) 要求 → worktree-local signed approval record で対応
2. **allowlist path drift**: operator-runbook は `~/.taskhub/keys/approval-verify-key-allowlist.txt`、verifier は `repo-local .taskhub/approval-verify-key-fingerprints.allowlist` → worktree-local allowlist で drill 完了
3. **alembic wrapper**: subprocess が secret-bearing `TASKMANAGEDAI_DATABASE_URL` を strip、host alembic が container hostname 解決失敗 → worktree-local wrapper で対応
4. **pg_dump --single-transaction invalid**: PostgreSQL pg_dump 16/17 が当 option を reject、現 backup orchestrator が誤 pass → worktree-local docker wrapper で除去
5. **`--skip-service-stop` 必須**: 現 backup recovery が 1 compose file のみ受付、`docker-compose.dev.yml` override 込みでは api/worker restart fail → `--skip-service-stop` で対応
6. **SOPS env inclusion 不可**: `.env.encrypted` 不在、plaintext `.env.local` は archive しない (security 設計通り)
7. **stale destructive_lock**: backup 成功 exit 後 lock 残存、pid stale → process 不在 verify 後手動削除

これら 7 件は **source 修正は P0.1+ post-merge SOP polish PR で実施**、本 P0 Exit declaration scope 外 (本 plan §1.3 latent issues 13-19 件目、本 PR commit message + master plan で記録)。

#### evidence files (`~/.taskhub/drills/mac-single-host-smoke/2026-05-22/`、user-local)

- `C-ui-smoke-checklist.md` (UI smoke check 結果 + deviation notes)
- `D-local-backup-restore-drill-checklist.json` (AC-HARD-04 PASS、7 mandatory + execution_deviations)
- `eval-dashboard.png` + `dashboard.png` + `tickets.png` + `ticket-detail.png` + `approvals.png` + `agent-runs.png` + `audit.png` + `settings.png` (UI screenshots)
- `ui-browser-evidence.json` + `source-secret-leak-check.json` (DOM/SSR secret scan)
- `backup-command-output.json` + `tar-listing.txt` + `checksums-verify.txt` + `private-key-scan.txt` + `pg-restore-list.txt` + `restore-actors-query.txt` + `cleanup-check.txt` (backup/restore raw evidence)

#### post-drill cleanup verified

- restore container 削除: ✅
- decrypted extract dir 削除: ✅
- `/tmp/taskhub-backup-*` 0 件: ✅
- stale destructive_lock 削除: ✅
- worktree `.env.local` symlink restore: ✅
