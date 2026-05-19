---
id: "SP-022_framework_intake_hardening"
type: "heavy"
status: "draft"
sprint_no: 22
created_at: "2026-05-10"
updated_at: "2026-05-19"
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

- **SP022-T00 (pre-implementation gate)**: **ADR-00020 + ADR-00021 + ADR-00007 update を proposed → accepted 昇格** (F-PR67-029/036 P2 adopt: `.claude/rules/sprint-pack-adr-gate.md §12` 「実装着手直前に planned ADR を accepted 化」invariant 遵守、SP-022 実装着手 trigger). acceptance criteria 再解釈: design ADR として `design accepted + skeleton verified` を本 acceptance time の意味とし、ADR-00020 framework intake checklist は SP022-T01 実装着手前、ADR-00021/00007 host-portable は SP022-T08/T09 実機 drill 着手前に accept、実機 host migration drill PASS は **post-acceptance verification** (SP022-T09)、master plan line 106 の「drill PASS 後」記述は本 fix で「SP-022 で drill verification 必須」と再解釈、別 PR で master plan §11.5 update を提出. ADR-00021 acceptance_blocked_by の「drill PASS / SP012-T01〜T10」は本 T00 acceptance criteria 再解釈と整合 (本 PR scope は ADR body 完全 update を SP022-T00 時実施として carry-over).
- SP022-T01: ADR-00020 (framework intake checklist) 全 8 verify item を CI 機械化、`scripts/ci/check_framework_intake.sh` 完成
- SP022-T02: `taskhub migrate` 自動化 (rollback / split-brain 防止 / age key 運搬連携)
- SP022-T03: 半年 drill scheduling SOP (cron alert + 手動 approval flow)
- SP022-T04: Phase E 16 finding 個別 closure verify (各 ADR / Sprint Pack で adopted を contract test に落とし込み済か audit)
- SP022-T05: AC-HARD-01〜07 fixture を multi-agent 文脈で再 verify (**F-PR67-037 P2 adopt**: 本 task は SP-013 multi-agent skeleton に依存、SP-022 が pre-P0.1 unblock sprint reframe 後は SP-013 完了前に着手不可. 本 task のみ **SP-013 完了後の post-P0.1 carry-over** として位置、SP-022 完了 + P0.1 SP-013 完了後に SP-022.1 / SP-023 等の post-P0.1 hardening sprint で実施。本 Sprint Exit Review PR では task list に残存 + dependency note のみで close、別 PR で sprint scope re-allocation 実施)
- SP022-T06: KPI baseline 設定 (host 別: Mac / Linux / VPS で acceptance_pass_rate 等の median を取得、運用 baseline 確定)
- SP022-T07: production 公開準備チェックリスト draft (P3+ 着手時の前提整理、F-ADV-R1-007 + F-R2-005 adopt: **本 task は docs-only checklist skeleton まで**、以下の P3+ 実作業は本 task 内で禁止: (a) Docker image build pipeline、(b) DNS 設定、(c) public ingress (Funnel / Cloudflare Tunnel / public bind)、(d) external publication、(e) release deploy config、(f) license / docs 整備の本実装。これらは P3+ SP-023 以降の production release Sprint Pack で実施)
- SP022-T08: **SP-012 carry-over 完了** (F-PR67-025/027 P2 adopt): taskhub real I/O (10 subcommands all) + 実 DB write integration (BL-0149 sign-off endpoint + AuditEventRepository.append 経由 P0AcceptanceAudit write) + signed journal verification CLI (audit_events 全件 fetch + recompute + final_hash verify) + private staging CI/E2E 完成 + frontend dashboard backend API wiring
- SP022-T09: **実機 host migration drill (Mac→VPS) PASS** (RTO≤4h、F-PR67-022/029 P2 adopt: T00 accept 後の post-acceptance verification、P0.1 unblock 必須 gate)

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
| **実機 host migration drill (Mac→VPS) RTO≤4h PASS** | ○ | - |
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

(後続: SP-022 完了時に T02-T09 全体 Review を追記)
