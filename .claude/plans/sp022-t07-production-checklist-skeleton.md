# SP022-T07: production checklist skeleton (docs-only)

最終更新: 2026-05-20 (r2, R1 10 件全件 adopt: HIGH×2 / MEDIUM×5 / LOW×3)

## 1. 目的 (Goal)

SP-022 受け入れ条件 (`docs/sprints/SP-022_framework_intake_hardening.md` line 116-117):

> SP022-T07 production checklist draft は **docs-only checklist skeleton 1 file** (`docs/release/production_readiness_checklist.md`、F-R2-005 adopt) のみ作成、Docker image build pipeline / DNS 設定 / public ingress (Funnel / Cloudflare Tunnel) / external publication / release deploy config / license 整備の本実装は **本 T07 内で禁止** (P3+ SP-023+ Sprint Pack で実施)。
> P0.1 unblock 判定では SP022-T07 = production 実装完了ではなく **checklist draft skeleton 存在確認のみ** (F-ADV-R1-007 + F-R2-005 adopt)。

具体的に本 task で:
1. `docs/release/production_readiness_checklist.md` 新規 1 file 作成 (本 task scope は本 file の skeleton のみ、**T07 成果物カウントは本 file 1 件**)
2. 含めるべき 10 章 (P3+ 実装で実施項目の checklist 形式 skeleton)
3. **本 file は skeleton (各 section は `[ ]` checklist + 概要 + P3+ 実装移送先 reference のみ)**、P3+ 本実装は含めない
4. SP-022 Pack `## Review` に SP022-T07 完了記録 (**R1-F-001 adopt**: 本更新は acceptance metadata であり T07 成果物カウントには含めない、Sprint Pack の review log update は SP022-T01/T03/T04 同様の追跡用 update)

## 2. 背景 (Background)

- SP-022 受け入れ条件で T07 は **docs-only checklist skeleton 1 file** に限定 (line 116-117)
- F-ADV-R1-007 + F-R2-005 adopt: T07 内で禁止される P3+ 実作業:
  - (a) Docker image build pipeline
  - (b) DNS 設定
  - (c) public ingress (Funnel / Cloudflare Tunnel / public bind)
  - (d) external publication
  - (e) release deploy config
  - (f) license / docs 整備の本実装
- P0.1 unblock 判定では「production 実装完了」ではなく「checklist skeleton 存在確認」のみ
- 本 file は将来 (P3+ SP-023+ production release Sprint Pack) で各章を本実装に展開する起点となる

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `docs/release/production_readiness_checklist.md` (NEW) | docs-only checklist skeleton 1 file |
| 2 | `docs/sprints/SP-022_framework_intake_hardening.md` (MODIFY) | `## Review` に SP022-T07 完了記録追加 |
| 3 | `.claude/plans/sp022-t07-production-checklist-skeleton.md` (本計画、commit 含む) | - |

### 3.2 対象外 (本 task では実装しない、本 T07 内で禁止)

- **Docker image build pipeline 本実装** (Dockerfile.production / docker buildx / multi-arch 等)
- **DNS 設定** (CloudFlare DNS records / Tailscale MagicDNS exposure 等)
- **public ingress** (Tailscale Funnel / Cloudflare Tunnel / public bind の有効化 — ADR-00007 完全 deny 維持)
- **external publication** (DockerHub / GHCR / npm registry 等への publish pipeline)
- **release deploy config** (GitHub Releases / semantic-release / changelog auto-gen 本実装)
- **license / docs 整備** (LICENSE file / NOTICE / SECURITY.md / public README polish 本実装)
- **checklist 各項目の実 verify script** (現 P3+ scope、各章を将来 SP-023+ で展開)

## 4. checklist skeleton 構成

`docs/release/production_readiness_checklist.md` の章立て (P3+ 着手時の前提整理、R1-F-003 + R1-F-004 + R1-F-005 + R1-F-008 adopt: 具体ツール名は P3+ ADR 判断とし、抽象 skeleton に下げる + private/public network 境界分離 + external publication 独立 § + LICENSE/NOTICE/SECURITY/README は placeholder のみ):

1. **§1. Goal and scope**: 本 file の位置付け (P3+ SP-023+ 着手時の前提整理 skeleton、P0.1 unblock では **file existence 確認のみ**、checklist の checked/unchecked 状態は評価しない、R1-F-006 adopt)
2. **§2. Pre-condition (P3+ 着手時の確認用 checklist)**: P0.1 完了 invariant (host-portable deployment / SecretBroker / Tenant boundary / AgentRun state machine / Provider Compliance 等の正本 reference)。本 § の checkbox は **P3+ 着手時に確認する未実施項目**、T07 unblock 判定では evaluated されない (R1-F-006 adopt)
3. **§3. Container image build pipeline** (P3+ 実装、抽象 skeleton): build pipeline 方針決定 / multi-arch / image signing / vulnerability scanning の **要否を P3+ ADR で判断**。具体 tool 名 (例) は P3+ reference 側へ移送、本 § は判断項目のみ
4. **§4. Private networking (Tailscale 閉域維持、ADR-00007 invariant)**: Tailscale 閉域維持 invariant + MagicDNS は private-only として skeleton 化。**public exposure (Tailscale Funnel / Cloudflare Tunnel / public bind / public DNS records) は本 § から完全除外**、§4-public で独立扱い (R1-F-004 adopt)
5. **§4-public. Public exposure (P3+、ADR-00007 update + ADR Gate Criteria #7 経由必須)**: public ingress / public DNS records は本 T07 では future item placeholder のみ、本実装は ADR-00007 update + ADR Gate Criteria #7 経由必須。Tailscale Funnel / Cloudflare Tunnel / public bind / CloudFlare DNS records 等の具体検討は P3+ ADR 判断 (R1-F-004 adopt)
6. **§5. Release deploy config** (P3+ 実装、抽象 skeleton): release strategy 方針決定 / rollback / 段階 deploy 戦略の **要否を P3+ ADR で判断**。具体 tool 名 / 戦略名 (例) は P3+ reference 側へ移送 (R1-F-003 adopt)
7. **§5-external. External publication** (P3+、独立 §、R1-F-005 adopt): registry publish (container registry / package registry / repo publish) は P3+ で separate approval、本 T07 では skeleton reference のみ。具体 registry 名は P3+ ADR で判断
8. **§6. License and public docs** (P3+ 実装、**本 T07 では作成・編集しない**、R1-F-008 adopt): LICENSE / NOTICE / SECURITY.md / public README は P3+ で作成するべき文書名の **placeholder のみ列挙**、本 task では実 file の作成 / 編集はしない (framework intake ADR-00020 attribution との整合は P3+ で確認)
9. **§7. KPI baseline reference** (T06 link、R1-F-009 adopt): production baseline 取得 (3 host: Mac/Linux/VPS) の **正本は SP-022 Pack §SP022-T06 section**、本 T07 では skeleton link のみ、実 baseline 取得は T06 で実施
10. **§8. Migration drill reference** (T09 link、R1-F-009 adopt): 実機 host migration drill PASS (RTO≤4h) の **正本は SP-022 Pack §SP022-T09 section**、本 T07 では skeleton link のみ、実 drill は T09 で実施
11. **§9. Audit and observability** (P3+ 実装、抽象 skeleton): production audit sinking / metrics / log aggregation / tracing の **要否と方針は P3+ ADR で判断**。具体 tool 名 (例) は P3+ reference 側へ移送、raw secret leakage 0 invariant は本 § で明示
12. **§10. SecretBroker rotation cadence** (P3+ 実装、抽象 skeleton): rotation cadence は P3+ ADR で判断、各 secret kind (SOPS age / provider key / GitHub App / Tailscale auth) の skeleton link のみ

各 §3 / §4-public / §5 / §5-external / §6 / §9 / §10 は本 T07 scope **以外** の P3+ 実装、本 task では skeleton (1-3 行 checklist + 移送先 reference) のみ。具体ツール名 / 戦略名は P3+ ADR で判断 (本 plan / template には記載しない、R1-F-003 adopt)。

## 5. file template

本節は plan 内 reference であり、`docs/release/production_readiness_checklist.md` 実 file の
構造を示す。実コマンド文字列 (具体ツール名、live build/release/deploy CLI 表現) は本 plan
にも file template にも記載しない (R1-F-002 + R1-F-003 adopt)。本実 file 内では各 §
について「P3+ で ADR 判断する項目」と「正本 reference」のみ skeleton 化する。

実 file (`docs/release/production_readiness_checklist.md`) の章立て (`§1`-`§10`、§4 と §5
に subsection、§6 は placeholder のみ) は本 plan §4 に詳細を記載済 (R1-F-003 + R1-F-004 +
R1-F-005 + R1-F-008 adopt)。具体 placeholder 命名 / 並び順は実装時に本 plan §4 を正本として
反映する。

実 file 各 § の内容方針 (具体ツール名は記載しない):

- **§1 Goal and scope**: 2-3 文の位置付け + SP-022 line 116-117 reference + 「P0.1 unblock 判定は file existence のみ、checklist の checked/unchecked 状態は evaluated しない」明記 (R1-F-006 adopt)
- **§2 Pre-condition**: P0.1 完了 invariant の正本 reference (host-portable deployment / SecretBroker / Tenant boundary / AgentRun state machine / Provider Compliance) を箇条書き reference。本 § の checkbox は P3+ 着手時の確認項目 (R1-F-006 adopt)
- **§3 Container image build pipeline (P3+)**: build pipeline 方針 / multi-arch 要否 / image signing 要否 / vulnerability scanning 要否を P3+ ADR で判断する旨の 1-2 行 skeleton (具体ツール名なし、R1-F-003 adopt)
- **§4 Private networking (Tailscale 閉域維持)**: Tailscale 閉域維持 invariant + MagicDNS は private-only としての 1-2 行 skeleton。public 関連項目は §4-public に分離 (R1-F-004 adopt)
- **§4-public Public exposure (P3+、ADR Gate Criteria #7)**: public ingress / public DNS records は P3+ で ADR-00007 update + ADR Gate Criteria #7 経由必須、本 T07 では future item placeholder のみ。具体経路 (Funnel / Tunnel / public bind / public DNS records) は ADR 判断 (R1-F-004 adopt)
- **§5 Release deploy config (P3+)**: release strategy / rollback / 段階 deploy 戦略の要否を P3+ ADR で判断する 1-2 行 skeleton (具体 tool 名 / 戦略名なし、R1-F-003 adopt)
- **§5-external External publication (P3+)**: registry publish (container / package / repo) は P3+ で separate approval、本 T07 では skeleton reference のみ、具体 registry 名は P3+ ADR 判断 (R1-F-005 adopt)
- **§6 License and public docs (P3+、本 T07 では作成・編集しない)**: P3+ で作るべき文書名の placeholder (LICENSE / NOTICE / SECURITY / public README polish) のみ列挙、本 task では実 file の作成・編集はしない (R1-F-008 adopt)。framework intake ADR-00020 attribution との整合は P3+ で確認
- **§7 KPI baseline reference (T06 link)**: 「正本は SP-022 Pack §SP022-T06 section」「実 baseline 取得は SP022-T06 で実施」明記、本 T07 では skeleton link のみ (R1-F-009 adopt)
- **§8 Migration drill reference (T09 link)**: 「正本は SP-022 Pack §SP022-T09 section」「実 drill は SP022-T09 で実施」明記、本 T07 では skeleton link のみ (R1-F-009 adopt)
- **§9 Audit and observability (P3+)**: production audit sinking / metrics / log aggregation / tracing の要否と方針を P3+ ADR で判断する 1-2 行 skeleton。raw secret leakage 0 invariant は本 § で明示 (R1-F-003 adopt)
- **§10 SecretBroker rotation cadence (P3+)**: rotation cadence は P3+ ADR で判断、各 secret kind (SOPS age / provider key / GitHub App / Tailscale auth) を skeleton link のみ列挙 (R1-F-003 adopt)
- **関連**: SP-022 line 116-117 / ADR-00007 / ADR-00020 / ADR-00021 / SP022-T06 / SP022-T09 + SP-022 Pack 内の正本 section reference (R1-F-009 adopt)

## 6. 検証手順

R1-F-002 + R1-F-010 adopt: 検証は (a) live release/build/deploy command pattern が本 file にも plan にも記述されていないこと、(b) 禁止 6 項目が P3+ reference 以外で本実装として記述されていないこと、の 2 段。keyword check は補助に留め、最終的に plan-review 採否判定で scope を確認する。

具体ツール名 (build CLI / container registry CLI / signing CLI / IaC CLI / cloud CLI 等の名称) は本 plan / 本 file には記述しない (R1-F-002 adopt)。検証時に「live command pattern」と「P3+ scope language の有無」は **read-only manual review** で確認する。

```bash
# 1. file 存在確認
test -f docs/release/production_readiness_checklist.md && echo "PASS: file exists"

# 2. file 構造確認 (§1 / §2 / §3 / §4 / §4-public / §5 / §5-external / §6 / §7 / §8 / §9 / §10 全 section 存在)
for s in "## §1" "## §2" "## §3" "## §4 " "## §4-public" "## §5 " "## §5-external" "## §6" "## §7" "## §8" "## §9" "## §10"; do
  grep -F "$s" docs/release/production_readiness_checklist.md || echo "MISSING: $s"
done

# 3. live command pattern 抽出 (manual review 補助、R1-F-010 adopt)
# fenced code block 内の `$ ` 始まり / shell 風 1 行コマンド を抽出
# 抽出結果は manual review で「P3+ 本実装に直結する command か否か」を判定
awk '/^```bash|^```sh/,/^```$/' docs/release/production_readiness_checklist.md | grep -E '^\$ |^[a-z]+ +(build|push|sign|install|apply|publish|deploy) ' | head -20 || echo "PASS: no fenced live command blocks"

# 4. P3+ 移送先 reference の存在確認 (R1-F-009 adopt)
grep -E "P3\+ 移送先|正本は SP-022 Pack" docs/release/production_readiness_checklist.md | head -10

# 5. SP-022 Review section update 確認 (acceptance metadata、R1-F-001 adopt)
grep -A 2 "SP022-T07 production checklist" docs/sprints/SP-022_framework_intake_hardening.md | head -5
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (`.claude/rules/codex-usage-policy.md §14.1`、Sprint Pack 関連 docs-only でも SP-022 must_ship 直結):
- `codex-plan-review R1 minimum + 採否判定` 経路 (本 T07 は docs-only checklist skeleton、CRITICAL invariant 直結ではない)

### 7.1 期待される review focus

1. **scope boundary**: F-R2-005 / F-ADV-R1-007 で禁止された 6 項目 (Docker build pipeline / DNS / public ingress / external publication / release deploy / license 本実装) が本 file に含まれていないこと
2. **skeleton 体裁**: 各 § は checklist (`[ ]`) + 概要 + P3+ 移送先 reference のみ、実コマンド (docker build / helm install 等) を含まないこと
3. **Tailscale invariant**: §4 で Tailscale 閉域維持 (ADR-00007) を skeleton 段階で明示、Funnel / Cloudflare Tunnel は ADR Gate Criteria #7 経由必須と記載されているか
4. **SP022-T06/T09 reference**: §7 / §8 が T06 / T09 への正しい link、本 T07 では skeleton link のみで実 baseline / drill は含まないこと
5. **P0.1 unblock 判定**: 「checklist 存在確認のみ」と明示されているか (本実装完了 != T07 完了)

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| skeleton 内に P3+ 本実装を混入 | scope boundary 違反、F-R2-005 違反 | §3.2 で 6 項目を明示禁止 + §6 検証手順 #3 で禁止 keyword check |
| Tailscale invariant 緩み | ADR-00007 violation 経路の skeleton 化 | §4 を「public ingress は ADR Gate Criteria #7 経由必須」明記 |
| T06/T09 と scope 衝突 | KPI baseline / 実機 drill を T07 で開始 | §7/§8 は skeleton link のみ、実施は T06/T09 |
| Codex review が delayed | merge 遅延 | 30 min max polling、admin merge bypass (CI billing failure 継続) |

### Rollback (3 階層、SP022-T01/T03/T04 と同)

- Tier 1 (pre-merge local): `git restore` 対象 file
- Tier 2 (post-merge): `docs/release/production_readiness_checklist.md` 削除 (skeleton のみ、影響範囲限定)
- Tier 3 (break-glass): SP-022 `## Review` の T07 記録から削除 + revert PR

## 9. commit 戦略

single commit。SP022-T01/T03/T04 pattern 踏襲。

## 10. PR workflow

SP022-T01/T03/T04 pattern 踏襲: plan draft → codex-plan-review R1 minimum + 採否判定 → 実装 → pre-commit verify → commit/push/PR → Codex auto-review polling + multi-round adopt + admin merge bypass。

## 11. DoD (R1-F-007 adopt: docs-only skeleton scope に絞る、本 task 必須項目のみ)

### 11.1 必須 DoD

- [ ] `docs/release/production_readiness_checklist.md` 新規 1 file 作成 (§1 / §2 / §3 / §4 / §4-public / §5 / §5-external / §6 / §7 / §8 / §9 / §10 全 section 存在、R1-F-003 + R1-F-004 + R1-F-005 adopt)
- [ ] 各 § は checklist (`[ ]`) + 概要 + P3+ 移送先 reference のみ、live release/build/deploy command が含まれない (R1-F-002 adopt)
- [ ] §3.2 禁止 6 項目 (Docker build pipeline 本実装 / DNS 本実装 / public ingress 有効化 / external publication 有効化 / release deploy config 本実装 / license file 作成・編集) が file 内に **本実装** として混入していない (skeleton reference は OK、R1-F-008 adopt)
- [ ] §4 で Tailscale 閉域維持 + ADR-00007 invariant、§4-public で ADR Gate Criteria #7 経路明記 (R1-F-004 adopt)
- [ ] §1 / §2 で「P0.1 unblock 判定は file existence のみ、checklist の checked/unchecked 状態は evaluated しない」明記 (R1-F-006 adopt)
- [ ] §6 で「本 T07 では LICENSE / NOTICE / SECURITY / README を作成・編集しない、placeholder のみ列挙」明記 (R1-F-008 adopt)
- [ ] §7 / §8 が T06 / T09 link のみ + 正本 SP-022 Pack §section reference (R1-F-009 adopt)
- [ ] SP-022 Pack `## Review` に SP022-T07 完了記録 (acceptance metadata、T07 成果物カウントには含めない、R1-F-001 adopt)
- [ ] codex-plan-review R{N} findings are triaged adopt/defer/reject, and all adopted CRITICAL/HIGH are resolved before implementation

### 11.2 任意 DoD (回帰確認、R1-F-007 adopt: 触れた場合のみ実施)

- [ ] SP022-T01/T03/T04 既存 fixture (触れた場合のみ regression 確認、本 T07 は docs-only のため触らない予定)
- [ ] PR Codex auto-review R{N} clean (採否判定 3 分類 + multi-round polish、本 task の標準フロー)

## 13. R1 plan-review findings adoption log

R1 (2026-05-20, codex-plan-review): 10 findings, **全件 adopt** (HIGH×2 / MEDIUM×5 / LOW×3).

| ID | severity | category | summary | adopted location |
|---|---|---|---|---|
| F-001 | HIGH | inconsistency | SP-022 Pack `## Review` update は acceptance metadata、T07 成果物カウントには含めない | §1 #4, §11.1 DoD |
| F-002 | HIGH | inconsistency | plan/template 内に live build/release/deploy command 文字列を含めない、検証は manual review 主体 | §5, §6 #3, §11.1 DoD |
| F-003 | MEDIUM | inconsistency | §3-§6 / §9-§10 で具体ツール名 (Dockerfile.production / docker buildx / cosign / trivy / semantic-release / blue-green / canary 等) を削除、P3+ ADR 判断の skeleton に下げる | §4 (構成), §5 (内容方針), §11.1 DoD |
| F-004 | MEDIUM | risk | §4 を private networking (MagicDNS / Tailscale 閉域) と §4-public public exposure (Funnel / Tunnel / public bind / public DNS) に分離 | §4, §5, §6 #2, §11.1 DoD |
| F-005 | MEDIUM | missing | external publication を独立 §5-external として追加 (P3+ で separate approval) | §4, §5, §6 #2, §11.1 DoD |
| F-006 | MEDIUM | ambiguity | §1 / §2 で「P0.1 unblock 判定は file existence のみ、checkbox 状態は evaluated しない」明記 | §4 #1-#2, §5, §11.1 DoD |
| F-007 | MEDIUM | planning | DoD を必須 (docs-only scope) と任意 (回帰確認) に分離、T01/T03/T04 fixture regression は触れた場合のみ | §11.1 / §11.2 DoD |
| F-008 | LOW | ambiguity | §6 で「本 T07 では LICENSE / NOTICE / SECURITY / README を作成・編集しない、placeholder のみ列挙」明記 | §4, §5, §11.1 DoD |
| F-009 | LOW | missing | T06/T09 reference を「正本は SP-022 Pack §SP022-T06/T09 section」明示 | §4, §5, §6 #4, §11.1 DoD |
| F-010 | LOW | planning | 検証は live command pattern + 禁止 6 項目記述の 2 段、keyword check は補助、最終的に plan-review 採否判定で scope 確認 | §6 (intro + #3) |

## 12. 関連

- SP-022 (Framework Intake Hardening) line 67 / 101 / 116-117 / Phase G section
- F-ADV-R1-007 + F-R2-005 (T07 docs-only checklist skeleton 限定の根拠)
- ADR-00007 (External Exposure invariant)
- ADR-00020 (Framework Intake Checklist)
- ADR-00021 (Host-Portable Deployment)
- SP022-T06 (KPI baseline)
- SP022-T09 (実機 host migration drill)
- SP022-T01/T03/T04 (確立 pattern: plan-review + impl + PR + Codex multi-round + admin merge bypass)
