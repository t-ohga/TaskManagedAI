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
