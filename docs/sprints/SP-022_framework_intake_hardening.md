---
id: "SP-022_framework_intake_hardening"
type: "heavy"
status: "draft"
sprint_no: 22
created_at: "2026-05-10"
updated_at: "2026-05-18"
target_days: 3
max_days: 5
# F-PR67-019 P2 adopt (PR #67 R4): ADR-00021 acceptance は SP-022 で実機 host
# migration drill PASS 後 (master plan line 106). 旧 frontmatter「SP-012 で
# accepted」記述を更新、SP-022 が **accepting sprint** であることを明示.
# ADR-00007 update も同期 acceptance (master plan line 107).
adr_refs: []
planned_adr_refs:
  - "[ADR-00020](../adr/00020_framework_intake_checklist.md) # SP-022 で accepted at SP022-T00 (pre-implementation gate、§12 invariant、F-PR67-036/038 P2 adopt)"
  - "[ADR-00021](../adr/00021_host_portable_deployment.md) # SP-022 で accepted at SP022-T00 (design accepted、実機 host migration drill PASS は SP022-T09 post-acceptance verification、F-PR67-029/038 P2 adopt、master plan line 106 別 PR で update)"
  - "[ADR-00007](../adr/00007_external_exposure.md) # ADR-00021 同期 acceptance at SP022-T00、SP022-T09 で drill verification (F-PR67-038/042 P2 adopt、master plan line 107 別 PR で update)"
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
- SP022-T07: production 公開準備チェックリスト draft (P3+ 着手時の前提整理)
- SP022-T08: **SP-012 carry-over 完了** (F-PR67-025/027 P2 adopt): taskhub real I/O (10 subcommands all) + 実 DB write integration (BL-0149 sign-off endpoint + AuditEventRepository.append 経由 P0AcceptanceAudit write) + signed journal verification CLI (audit_events 全件 fetch + recompute + final_hash verify) + private staging CI/E2E 完成 + frontend dashboard backend API wiring
- SP022-T09: **実機 host migration drill (Mac→VPS) PASS** (RTO≤4h、F-PR67-022/029 P2 adopt: T00 accept 後の post-acceptance verification、P0.1 unblock 必須 gate)

## タスク一覧

- [ ] **SP022-T00** (ADR-00021/00007 accept、SP-022 開始 trigger) → SP022-T01〜T09 を順次実装
- [ ] ADR-00020 を proposed → accepted
- [ ] **ADR-00020 + ADR-00021 + ADR-00007 を proposed → accepted** (SP022-T00 pre-implementation gate、F-PR67-033/036 P2 adopt: T10 stale 撤回 + ADR-00020 を T00 に含める、§12 invariant 整合)
- [ ] `taskhub migrate` end-to-end を 3 host pair (Mac↔VPS、Linux↔VPS、VPS↔VPS) で drill 実施
- [ ] Phase E 16 finding が全件 closed (adopt 済 + test fixture 化済)
- [ ] AC-HARD multi-agent fixture 全件 PASS (**F-PR67-039 P2 adopt**: 本項目は SP-013 multi-agent skeleton 依存、SP-022 が pre-P0.1 reframe 後は SP-013 完了前に着手不可. SP-022 exit gate から除外、post-P0.1 carry-over として SP-022.1 / SP-023 等で実施)
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
| Phase E 16 finding closure | ○ | LOW 残存は P3+ で対応可 |
| AC-HARD multi-agent fixture | ✗ (post-P0.1 carry-over) | F-PR67-039 P2 adopt: SP-013 multi-agent skeleton 依存、SP-022.1 / SP-023 等の post-P0.1 sprint で実施 |
| KPI baseline (host 別) | ○ | Mac / Linux / VPS の 3 host で baseline 取得、特定 host のみは defer 可 |
| production 公開準備 checklist draft | ○ | 詳細実装は P3+ |

## 受け入れ条件

- ADR-00020 8 verify item が CI で機械検査されている (license / attribution / no embed / persistence / external network / telemetry / secret canary / tenant boundary 全て)
- `taskhub migrate --target <host>` が source backup → 転送 → target restore → smoke を 90 分以内に完了
- migration 中の rollback (age key 失敗 / pg_restore 失敗 / network 切断) が自動で source host 復旧
- Phase E 16 finding (PE-F-001〜PE-F-016) すべての closure evidence (各 finding に対応する test fixture / contract test PASS)
- AC-HARD-01〜07 fixture が multi-agent 文脈 (orchestrator / inter_agent_messages / memory_records / role authorization / policy_profile) で全件 PASS
- KPI baseline が host 別に確定、運用 SOP 化

## 検証手順

```bash
# framework intake CI
$ bash scripts/ci/check_framework_intake.sh   # 違反 dependency 追加で fail
$ uv run pytest tests/scripts/test_check_framework_intake.sh tests/citations/test_citation_completeness.py -q

# host migration drill 自動化
$ taskhub migrate --target t-ohga-linux --via tailscale --auto-rollback-on-failure
$ uv run pytest tests/deploy/test_host_migration_automation.py tests/deploy/test_split_brain_prevention.py -q

# Phase E 16 finding closure
$ uv run pytest eval/multi_agent/role_authorization_negative/ eval/multi_agent/inter_agent_replay_attack/ \
                eval/multi_agent/memory_secret_canary/ eval/multi_agent/framework_intake_violation/ -q

# AC-HARD multi-agent fixture
$ uv run pytest eval/security/policy_block/multi_agent/ eval/security/tenant_isolation/multi_agent/ \
                eval/security/secret_canary/multi_agent/ -q

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
- ADR-00014/15/16/17/18/19 (P0.1+ で accepted 済、本 Sprint で運用 hardening)
- 全 Hard Gate AC-HARD-01〜07

## Phase G adversarial strengthening (2026-05-10)

### 追加 must_ship (Phase G adversarial 14 finding の closure 担当 strengthening)

- **drill timer alert-only enforcement (PGA-F-013)**: `scripts/ci/check_drill_timer_alert_only.sh` 追加、systemd timer / cron entry の ExecStart が通知 command 以外 (例: `taskhub migrate ...`) なら CI fail
- **`taskhub migrate --approval-id` 必須化**: cron / systemd 環境変数検出時に default deny、`--from-automation` flag + signed approval record 必須
- **CI bypass scan 拡張 (PGA-F-014)**: `scripts/ci/check_host_portable_bypass.sh` を網羅化 (Funnel/0.0.0.0 publish/non-127 publish/age private key marker/raw key path/secret archive 検出)
- **inter_agent_messages consumed invariant fixture (PGA-F-009)**: SP-015 で実装されたものを SP-022 で 追加 fixture (post-restore + post-migration 全 case) で再 verify

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
- Phase G adversarial 14 finding (PGA-F-001〜PGA-F-014) すべての closure evidence (test fixture / contract test PASS) verify

## Review

(SP-022 完了時に追記)
