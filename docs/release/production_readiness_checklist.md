# Production Readiness Checklist (skeleton)

最終更新: 2026-05-20 (SP022-T07 skeleton draft)

> **本 file は P3+ SP-023+ production release Sprint Pack 着手時の前提整理 skeleton**
> (`docs/sprints/SP-022_framework_intake_hardening.md` line 116-117 通り)。
>
> SP022-T07 では本 file の **file existence のみ** を P0.1 unblock 判定として使用、
> checklist の checked/unchecked 状態は **evaluated されない**。
> 本 file 内 checklist 各項目の **本実装は P3+ SP-023+** で実施
> (F-ADV-R1-007 + F-R2-005 adopt: 本 T07 内で本実装は禁止)。
>
> 本 T07 内で禁止される P3+ 実作業 6 項目:
> 1. Container image build pipeline 本実装
> 2. DNS 設定 本実装
> 3. public ingress 有効化 (Tailscale Funnel / Cloudflare Tunnel / public bind、ADR-00007 deny-by-default invariant)
> 4. external publication 有効化 (container registry / package registry / repo publish)
> 5. release deploy config 本実装
> 6. license / 公開 docs 本実装 (LICENSE / NOTICE / SECURITY.md / public README polish)
>
> 本 file は **抽象 skeleton + P3+ ADR で判断する項目** のみ列挙、具体 tool 名 / 戦略名は
> 含めない (R1-F-003 adopt)。

## §1. Goal and scope

本 file は SP022-T07 の docs-only checklist skeleton であり、`docs/sprints/SP-022_framework_intake_hardening.md`
line 116-117 に基づく **1 file 成果物**。

- **P0.1 unblock 判定**: 本 file の **file existence のみ**。checklist の checked/unchecked 状態は evaluated **されない** (R1-F-006 adopt)。
- **P3+ SP-023+ 着手時**: 本 file の各 § を本実装に展開する起点として使用。具体方針は P3+ ADR で判断 (R1-F-003 adopt)。
- 本 file は実コマンド / 具体 tool 名 / 戦略名を含めない (R1-F-002 adopt)。

## §2. Pre-condition (P3+ 着手時の確認項目)

本 § の checkbox は **P3+ 着手時に確認する未実施項目**。SP022-T07 unblock 判定では evaluated **されない** (R1-F-006 adopt)。

- [ ] P0.1 完了 (SP-013/SP-014/SP-015/SP-016/SP-018/SP-020 closure verified)
- [ ] host-portable deployment ADR-00021 accepted + 実機 host migration drill PASS (SP022-T09)
- [ ] SecretBroker boundary 不変 (`.claude/rules/secretbroker-boundary.md`)
- [ ] Tenant/project boundary 不変 (`.claude/rules/core.md §8`)
- [ ] AgentRun state machine 16 状態 + blocked_reason 3 種 + ContextSnapshot 10 列 (`.claude/rules/agentrun-state-machine.md`)
- [ ] Provider Compliance Matrix v2 13 reason_code (`.claude/rules/provider-compliance.md`)
- [ ] Hard Gates 7 全件 PASS + Quality KPIs 5 件中 4 件以上達成 (`.claude/reference/hard-gates-and-kpis.md`)

## §3. Container image build pipeline (P3+、抽象 skeleton)

P3+ で ADR 判断 (具体 tool 名 / 戦略名は本 file に記載しない、R1-F-003 adopt)。

- [ ] container image build pipeline の **要否** を P3+ ADR で判断
- [ ] multi-arch (multi-platform) build の **要否** を P3+ ADR で判断
- [ ] image signing (artifact attestation) の **要否** を P3+ ADR で判断
- [ ] vulnerability scanning (image / SBOM) の **要否** を P3+ ADR で判断

P3+ 移送先: SP-023+ production release Sprint Pack + ADR (新規)

## §4. Private networking (Tailscale 閉域維持、ADR-00007 invariant)

本 § は **private-only networking** scope。public 関連は §4-public に分離 (R1-F-004 adopt)。

- [ ] Tailscale 閉域維持 invariant (ADR-00007、本 invariant は P3+ でも保持)
- [ ] MagicDNS は private-only として動作確認
- [ ] internal service mesh / private subnet の方針は P3+ ADR で判断

P3+ 移送先: SP-023+ production release Sprint Pack (ADR-00007 invariant は維持)

## §4-public. Public exposure (P3+、ADR-00007 update + ADR Gate Criteria #7 経由必須)

本 § は **future item placeholder**、本 T07 では skeleton reference のみ (R1-F-004 + R1-F-005 adopt)。

public exposure 経路 (本 T07 内では **本実装禁止**、P3+ で ADR-00007 update + ADR Gate Criteria #7 経由必須):

- [ ] public ingress 経路の **要否** を P3+ で ADR-00007 update + ADR Gate Criteria #7 経由で判断
- [ ] public DNS records (外部 DNS provider 経由) の **要否** を P3+ ADR で判断
- [ ] reverse proxy / WAF / DDoS 防御の **要否** を P3+ ADR で判断
- [ ] TLS 証明書 (公的 CA 経由) の **要否と運用** を P3+ ADR で判断

P3+ 移送先: SP-023+ production release Sprint Pack + ADR-00007 update + ADR Gate Criteria #7 (`.claude/rules/sprint-pack-adr-gate.md §4`)

## §5. Release deploy config (P3+、抽象 skeleton)

P3+ で ADR 判断 (具体 tool 名 / 戦略名は本 file に記載しない、R1-F-003 adopt)。

- [ ] release strategy (リリース方針) の決定方法を P3+ ADR で判断
- [ ] rollback strategy (DB schema migration / app version) の **要否と方針** を P3+ ADR で判断
- [ ] 段階 deploy 戦略 (canary / blue-green / rolling 等の選定) を P3+ ADR で判断
- [ ] changelog / release notes 自動生成の **要否** を P3+ ADR で判断

P3+ 移送先: SP-023+ production release Sprint Pack + ADR (新規)

## §5-external. External publication (P3+、独立 §、separate approval)

本 § は **独立 §**、P3+ で **separate approval** が必要 (R1-F-005 adopt)。本 T07 では skeleton reference のみ。

- [ ] container registry publish の **要否** を P3+ で separate approval ADR で判断
- [ ] package registry publish の **要否** を P3+ で separate approval ADR で判断
- [ ] repository public 公開の **要否** を P3+ で separate approval ADR で判断
- [ ] external attestation / supply chain assurance の **要否** を P3+ ADR で判断

P3+ 移送先: SP-023+ production release Sprint Pack + ADR (新規、separate approval gate)

## §6. License and public docs (P3+、本 T07 では作成・編集しない)

本 T07 では LICENSE / NOTICE / SECURITY.md / public README を **作成・編集しない**。
P3+ で作るべき文書名の **placeholder のみ列挙** (R1-F-008 adopt)。

P3+ で作成すべき文書 (placeholder):

- [ ] LICENSE file (P3+ で license 選定 + 作成、本 T07 では作成しない)
- [ ] NOTICE file (third-party attribution、ADR-00020 framework intake と整合、本 T07 では作成しない)
- [ ] SECURITY.md (vulnerability disclosure / responsible disclosure policy、本 T07 では作成しない)
- [ ] public README polish (本 T07 では編集しない、現 README は internal docs として維持)

P3+ 移送先: SP-023+ production release Sprint Pack + ADR-00020 framework intake との整合 (P3+ 時点で確認)

## §7. KPI baseline reference (SP022-T06 link)

**正本は SP-022 Pack §SP022-T06 section** (R1-F-009 adopt)。本 T07 では skeleton link のみ、実 baseline 取得は SP022-T06 で実施。

- [ ] host 別 baseline (Mac / Linux / VPS) 取得 → 実施は SP022-T06
- [ ] acceptance_pass_rate / time_to_merge / approval_wait_ms / citation_coverage / cost_per_completed_task median → 計測は SP022-T06

正本 reference: `docs/sprints/SP-022_framework_intake_hardening.md` SP022-T06 section + `.claude/reference/hard-gates-and-kpis.md`

## §8. Migration drill reference (SP022-T09 link)

**正本は SP-022 Pack §SP022-T09 section** (R1-F-009 adopt)。本 T07 では skeleton link のみ、実 drill は SP022-T09 で実施。

- [ ] 実機 host migration drill (Mac → VPS) PASS (RTO ≤ 4h) → 実施は SP022-T09
- [ ] `taskhub migrate` rollback / split-brain prevention verify → 実装は SP022-T02、drill 実施は SP022-T09

正本 reference: `docs/sprints/SP-022_framework_intake_hardening.md` SP022-T09 section + `docs/deploy/half-yearly-drill-sop.md` (SP022-T03 で確立)

## §9. Audit and observability (P3+、抽象 skeleton)

P3+ で ADR 判断 (具体 tool 名 / 戦略名は本 file に記載しない、R1-F-003 adopt)。

- [ ] production audit sinking (audit_events long-term storage) の **要否と方針** を P3+ ADR で判断
- [ ] metrics collection (KPI / SLO 監視) の **要否と方針** を P3+ ADR で判断
- [ ] log aggregation の **要否と方針** を P3+ ADR で判断
- [ ] distributed tracing の **要否と方針** を P3+ ADR で判断
- [ ] **raw secret leakage 0 invariant (SecretBroker + canary scan)** は本 § で必須維持 (P3+ でも不変、ADR-00006 + `.claude/rules/secretbroker-boundary.md` §11)

P3+ 移送先: SP-023+ production release Sprint Pack + Sprint 11.5 (observability) 拡張

## §10. SecretBroker rotation cadence (P3+、抽象 skeleton)

P3+ で ADR 判断 (具体 cadence / 戦略は本 file に記載しない、R1-F-003 adopt)。

各 secret kind の rotation cadence を P3+ ADR で判断:

- [ ] SOPS age key rotation cadence (P3+ で ADR 判断)
- [ ] provider API key rotation (各 provider) cadence (P3+ で ADR 判断)
- [ ] GitHub App private key rotation cadence (P3+ で ADR 判断)
- [ ] Tailscale auth key rotation cadence (P3+ で ADR 判断)
- [ ] DB credential rotation cadence (P3+ で ADR 判断)

P3+ 移送先: SP-023+ production release Sprint Pack + `.claude/rules/secretbroker-boundary.md` rotation 章拡張

## 関連 (R1-F-009 adopt: 正本 reference の SP-022 Pack §section も併記)

- `docs/sprints/SP-022_framework_intake_hardening.md` line 116-117 (本 T07 受け入れ条件正本)
- `docs/sprints/SP-022_framework_intake_hardening.md` SP022-T06 section (KPI baseline 正本)
- `docs/sprints/SP-022_framework_intake_hardening.md` SP022-T09 section (実機 drill 正本)
- `docs/adr/00007_external_exposure.md` (External Exposure invariant、Tailscale 閉域維持、host-portable update を含む)
- `docs/adr/00020_framework_intake_checklist.md` (Framework Intake Checklist)
- `docs/adr/00021_host_portable_deployment.md` (Host-Portable Deployment)
- `docs/deploy/half-yearly-drill-sop.md` (SP022-T03 で確立した drill scheduling SOP)
- `.claude/rules/sprint-pack-adr-gate.md §4` (ADR Gate Criteria 11 種、#7 external exposure)
- `.claude/reference/hard-gates-and-kpis.md` (Hard Gates 7 + Quality KPIs 5)
- `.claude/rules/secretbroker-boundary.md` (raw secret leakage 0 invariant)
- SP022-T01 PR #70 / SP022-T03 PR #71 / SP022-T04 PR #72 (確立 pattern)
