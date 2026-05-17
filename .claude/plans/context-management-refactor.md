---
id: "PLAN-context-management-refactor"
type: "doc-refactor-plan"
status: "draft"
created_at: "2026-05-17"
updated_at: "2026-05-17"
target_artifact: "CLAUDE.md / .claude/rules/ / .claude/reference/ / ~/.claude/CLAUDE.md / MEMORY.md"
target_days_phase_a: 1
target_days_phase_b: 0.5
target_days_phase_c: 0.5
target_days_phase_d: 1
target_days_phase_e: 1
calendar_wait_stage1_to_stage2_days: 7
calendar_wait_max_days: 14
max_days_session_total: 4
estimated_token_savings: "115.8k → stage1 (Phase A-C): 74.0k (-42k, 36%), stage2 (Phase D-E): 40.65k (-75k, 65%)"
risks_unmitigated:
  - "R1-CRITICAL-invariant-trace-bug"
  - "R2-path-scoped-miss"
  - "R6-paths-version-dep"
implementation_strategy: "段階適用 (stage 1 = Phase A-C conservative → calendar wait 7-14 day 運用試験 → stage 2 = Phase D-E aggressive)"
implementation_executor: "Claude 自身 (Codex 委譲なし、CRITICAL invariant を含むため)"
review_executor: "codex-all-loops --mode=plan (plan polish のみ Codex skill 使用、Phase 1 R1-R3 clean + Phase 2 R1-R2 partial)"
scope: "project (.claude/) + user-global (~/.claude/、dotfiles 連動 PR 別、Phase E 着手時)"
related_rules:
  - ".claude/rules/core.md"
  - ".claude/rules/codex-usage-policy.md"
  - ".claude/rules/instincts.md"
---

# Context Management Refactor 計画

## 0. TL;DR

Claude Code session の memory files token (115.8k / 11.6%) を Claude Code 公式仕様 (CLAUDE.md ≤ 200 行 / subdirectory rules `paths` frontmatter / Skill on-demand load) で **2 stage 段階適用** する。

- **stage 1 (Phase A-C, conservative)**: 115.8k → **74.0k (-42k, 36%)** — 重複削除 + path-scoped + L4 reference 化
- **calendar wait 7-14 day** (運用試験で違反 commit / drift / rule 漏れを観測)
- **stage 2 (Phase D-E, aggressive)**: 115.8k → **40.65k (-75k, 65%)** — L3 skill 統合 + L1 圧縮 + user-global 整理

**安全性**: CLAUDE.md §2 全体 (= 8 重要原則 + Hard Gates 7 + Quality KPIs 5 = 計 20 項目) を §3.1.1 trace matrix で L1 rule への保持を機械検証 (`required_loaded_files` + `required_exact_patterns`、L1 file 単位 grep)。実装は **Codex 委譲せず Claude 自身が手作業**。plan の polish のみ codex-all-loops 使用。各 Phase 前に **preflight gate** (paths 実測 / skill 起動 / @import 解決 / scratch cleanup) を必須通過、失敗時は **preflight failure ledger に BLOCKED 記録 + 2 回連続で defer/reject 判定**。

---

## 1. 背景・現状

### 1.1 context 配分の現状 (2026-05-17 計測、`/context` より)

| 区分 | token | % | 備考 |
|---|---:|---:|---|
| **Memory files (合計)** | **115.8k** | **11.6%** | 全件常時 load |
| └ `~/.claude/CLAUDE.md` | 15.3k | 1.5% | TaskManagedAI 無関係情報多数 |
| └ `<repo>/CLAUDE.md` | 1.0k | 0.1% | 公式推奨遵守 |
| └ `<repo>/.claude/CLAUDE.md` | 29.0k | 2.9% | 865 行 / 推奨 4 倍超 |
| └ `.claude/rules/*.md` (20 files) | ~67k | ~6.7% | **全件常時 inline** (paths 未設定) |
| └ `MEMORY.md` | 7.0k | 0.7% | 公式推奨 ≤25KB 超過懸念 |
| Skills description | 10.9k | 1.1% | 120 skill |
| Custom agents | 5.6k | 0.6% | 35 agent |
| System prompt + tools | 20.1k | 2.0% | Claude Code 標準 |

### 1.2 問題

- **重複**: `.claude/CLAUDE.md §6.5.0-§6.5.9` と rules/{codex-usage-policy, branch-and-pr-workflow, user-preferences, codex-pr-review-checklist}.md が **70-90% 重複**
- **conditional load 未活用**: `.claude/rules/*.md` 20 件は `paths` 未設定で全件常時 inline、frontend 専用も backend session で load
- **user-global の 70-80% は TaskManagedAI 無関係** (Neovim / nb / MoltBot / Discord / Draw.io 等)
- **draft / 非 active rule の常時 load**: `multi-agent-orchestration.md` (Phase F draft)

### 1.3 公式仕様 (Claude Code、claude-code-guide subagent 確認、構造的整合のみ判定対象)

出典: https://code.claude.com/docs/en/memory.md / skills.md

| 仕様 | 内容 |
|---|---|
| CLAUDE.md 階層 | user-global → project root → project → local の全て常時 load |
| 推奨 size | `CLAUDE.md ≤ 200 行`、`MEMORY.md ≤ 200 行 or 25KB` |
| subdirectory rules | `paths: [...]` frontmatter で path-scoped conditional load |
| @import | `@relative/path.md`、import 内容も常時 load、max depth 5 |
| Skill on-demand | `disable-model-invocation: true` で manual skill (明示 `/skill-name` のみ)、`false` (default) で auto-invokable skill (description 常時 load) |
| Subagent | 独立 context、conversation 非継承、CLAUDE.md は inject (Phase E 前 preflight で実測必須) |
| auto-compaction | 旧 tool output 削除 → conversation summarize、CLAUDE.md は disk から re-inject |

---

## 2. 目標 (段階適用、F-ADV-208 fix: 完全統一 ledger)

### 2.0 統一 token ledger (本 plan 全 § で参照する正本)

| 区分 | 現状 | Phase A 後 | Phase B 後 | Phase C 後 (=stage 1) | Phase D 後 | Phase E 後 (=stage 2) |
|---|---:|---:|---:|---:|---:|---:|
| (A) rules/ 常時 load | 67.0k / 20 件 | 67.0k / 20 件 | 58.8k / 17 件 | **38.2k / 12 件** | **30.85k / 10 件 + skill desc 0.15k** | **21.65k / 10 件 圧縮版 + skill desc** |
| (B) `.claude/CLAUDE.md` | 29.0k | 18.0k (-11k) | 18.0k | 16.0k | 14.0k | 8.0k |
| (C) `<repo>/CLAUDE.md` | 1.0k | 1.0k | 1.0k | 1.0k | 1.0k | 1.0k |
| (D) `~/.claude/CLAUDE.md` | 15.3k | 15.3k | 15.3k | 15.3k | 15.3k | 8.0k |
| (E) MEMORY.md | 7.0k | 7.0k | 7.0k | 7.0k | 7.0k | 5.5k |
| **memory files 小計 (A+B+C+D+E)** | **119.3k** | **108.3k** | **100.1k** | **77.5k** | **68.15k** | **44.15k** |
| **memory files 合計 (/context 計測ベース、誤差 -3.5k)** | **115.8k** | **104.8k** | **96.6k** | **74.0k** | **64.65k** | **40.65k** |
| **削減量 (現状比)** | 0 | -11k (-10%) | -19k (-16%) | **-42k (-36%)** | -51k (-44%) | **-75k (-65%)** |

stage 1 = Phase A-C で **74.0k 達成**、stage 2 = Phase D-E で **40.65k 達成**。conservative 80k クリア、aggressive 35-50k 範囲内。

### 2.1 stage 1 (Phase A-C、本 plan 初回 PR scope)

§2.0 ledger より、stage 1 完了後 = **memory files 74.0k (-42k, 36% 削減)**。

stage 1 中の rules/ 件数推移:

| Phase | rules/ 常時 load 件数 | 内訳 |
|---|---:|---|
| 現状 | 20 件 | frontmatter なし全件 inline |
| A 後 | 20 件 | rules/ 構造未変更、CLAUDE.md §6.5 重複削除 |
| B 後 | 17 件 | L2 3 件 (rendering / testing / code-search) path-scoped |
| C 後 (= stage 1) | **12 件** | L4 5 件削除 (multi-agent / codex-multi-round / codex-output / codex-pr-review / user-preferences) |

L1 常時 load 10 件 (Phase C 後、§3.1 で詳細):
- **CRITICAL invariant 8 件**: core / ai-output-boundary / instincts / secretbroker-boundary / provider-compliance / agentrun-state-machine / cross-source-enum-integrity / server-owned-boundary
- **Sprint Pack / ADR Gate 1 件**: sprint-pack-adr-gate (F-CRA-002 fix)
- **Codex 連携 1 件**: codex-usage-policy (F-CRA-007 fix)

注: `user-preferences.md` は Phase C で内容を CLAUDE.md §2 / core.md / reference/ に分割移送、rule 削除。`plan-review.md` (2.9k) と `branch-and-pr-workflow.md` (4.6k) は stage 1 では rules/ に残り常時 load (Phase D で skill 化)。stage 1 後の rules/ 常時 load = L1 10 件 + plan-review + branch-and-pr-workflow = **計 12 件 / 38.2k** (= §2.0 (A) Phase C 後と完全一致)。

### 2.2 stage 2 (Phase D-E、calendar wait 7-14 day 後の追加 PR)

§2.0 ledger より、stage 2 完了後 = **memory files 40.65k (-75k, 65% 削減)**。

stage 2 中の rules/ 件数推移:

| Phase | rules/ 常時 load 件数 | 内訳 |
|---|---:|---|
| C 後 (= stage 1) | 12 件 | 上記 §2.1 末尾 |
| D 後 | **10 件 + L3-auto description 0.15k** | plan-review (agent body 統合) + branch-and-pr-workflow (skill 化) 削除 |
| E 後 (= stage 2) | **10 件 / 21.65k 圧縮版** | L1 10 件を §3.1 stage 2 列で圧縮 (-9.2k) + skill description 0.15k |

### 2.3 stage 1 → stage 2 移行 gate (calendar wait 7-14 day、F-CRA-004 + F-ADV-003 fix)

stage 1 PR merge 時に `<stage1_sha>` を `.claude/plans/context-management-refactor-stage1-evidence.md` に記録。`<stage1_sha>` から `HEAD` までの期間で以下を観測:

- [ ] **path-scoped 化 rule が想定通り load される**: 新 session を 4 種類で開始 (frontend / backend / docs / migration)、各 `/context` 出力で L2 rule の load 状態を確認、accepted load pattern を evidence file に記録
- [ ] **不変条件違反 commit が発生していない** (F-ADV-003 fix: 全変更 file を監査): `git diff --name-only <stage1_sha>..HEAD` を正本に、**全変更 file** を `.claude/scripts/audit-invariant-violation.sh` に渡す。監査対象に **必ず**:
  - 実装系: `backend/**`, `frontend/**`, `migrations/**`, `eval/**`
  - 本 refactor 主要変更面: `.claude/**`, `docs/**`
  - インフラ系: `scripts/**`, `.github/**`, Docker / Compose / config (`docker-compose*.yml`, `Dockerfile*`)
  - root manifests: `package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`, `Makefile`, `CLAUDE.md`
- [ ] **rule ↔ CLAUDE.md drift なし**: `git diff <stage1_sha>..HEAD -- .claude/CLAUDE.md .claude/rules/` で diff line 数 < 50、CLAUDE.md §2 と rules/ L1 10 件の内容を `diff` 確認
- [ ] **Codex PR review で「rule 違反検出漏れ」がない** (Codex F-PR42-005 fix: `gh pr list --limit 1000` で取りこぼし防止): `gh pr list --base main --state merged --search "merged:>=<stage1_sha_date>" --limit 1000` または `gh search prs repo:t-ohga/TaskManagedAI base:main is:merged merged:>=<stage1_sha_date> --limit 1000` で全 PR を取得、`.claude/scripts/codex_pr_full_review.sh <PR>` で全 finding 確認、rule 違反指摘で本来 stage 1 で load されるべき rule が漏れて発生した finding が 0 件

**いずれかに違反 / drift があれば stage 2 を保留**、まず該当 Phase の path 設定 / 移送先 / rule 内容を調整する fix PR を起票し、再度 7-14 day calendar wait 開始。

### 2.4 不変条件群 (CLAUDE.md §2 全体、計 20 項目)

| # | 群 | 項目数 | 詳細 |
|---:|---|---:|---|
| A | 8 重要原則 (CLAUDE.md §2.1-§2.8) | 8 | (1) AI 出力直結禁止、(2) deny-by-default、(3) Sprint Pack 必須ゲート / ADR Gate 11 種、(4) Provider Compliance Matrix v2、(5) SecretBroker atomic claim / actor-run-fingerprint binding、(6) AgentRun 16 状態 + blocked サブ 3、(7) 用語不変条件、(8) ContextSnapshot 10 カラム |
| B | Hard Gates 7 | 7 | policy_block_recall / secret_canary_no_leak / tenant_isolation_negative_pass / backup_restore_rpo_rto / forbidden_path_block / dangerous_command_block / prompt_injection_resist |
| C | Quality KPIs 5 | 5 | acceptance_pass_rate / time_to_merge / approval_wait_ms / citation_coverage / cost_per_completed_task |
| | 合計 | **20** | |

L1 必須は A+B = **15 項目**。C は改善指標、reference でも可。

---

## 3. 設計方針: 4 層分類

| 層 | 定義 | 例 | token 効果 |
|---|---|---|---|
| L1 常時 alwaysApply | 全 session で必須 | 8 invariant rules + sprint-pack-adr-gate + codex-usage-policy = 10 件 | 維持 (圧縮のみ) |
| L2 path-scoped | 特定領域編集時のみ | rendering / testing / code-search = 3 件 | 該当 session のみ load |
| L3-manual / L3-auto skill 化 | 特定 task | (L3-auto) `branch-pr-workflow` (description 常時 load + body invoke 時) | description 0.15k 常時 + body 0 |
| L4 reference 化 | 滅多に参照しない、draft / 完了 / 詳細 | multi-agent (draft) / codex-multi-round / codex-output / codex-pr-review-checklist | Read 時のみ |

### 3.1 L1 確定 10 件 (F-CRA-101 + F-ADV-010 + F-ADV-208 fix: ledger 完全整合)

stage 1 完了 (Phase C 後) は L1 圧縮なし、stage 2 完了 (Phase E 後) で L1 一括圧縮。

| rule file | 現状 | stage 1 後 (Phase C、圧縮なし) | stage 2 後 (Phase E、圧縮) | 採用理由 |
|---|---:|---:|---:|---|
| core.md | 3.2k | 3.2k | 2.5k | 全体基本制約、8 重要原則の Gateway |
| ai-output-boundary.md | 2.8k | 2.8k | 2.0k | AC-HARD-01/-05/-06/-07 直結 |
| instincts.md | 3.2k | 3.2k | 2.3k | 事故予防 17 種 |
| secretbroker-boundary.md | 4.7k | 4.7k | 3.0k | AC-HARD-02、raw secret 非保存 |
| provider-compliance.md | 3.6k | 3.6k | 2.5k | 越境 deny、13 reason_code |
| agentrun-state-machine.md | 4.6k | 4.6k | 2.5k | 16 状態 + blocked サブ 3 + terminal 5 |
| cross-source-enum-integrity.md | 1.7k | 1.7k | 1.5k | 5+ source 整合 + 4 重防御 |
| server-owned-boundary.md | 1.3k | 1.3k | 1.2k | caller-supplied 禁止 |
| sprint-pack-adr-gate.md (F-CRA-002 fix L1) | 3.0k | 3.0k | 2.0k | ADR Gate 11 種、backend / migration / API 必須 |
| codex-usage-policy.md (F-CRA-007 fix L1) | 2.6k | 2.6k | 1.5k | Codex 全 session 運用 |
| **L1 10 件合計** | **30.7k** | **30.7k** | **21.5k** (-9.2k 圧縮) | |

stage 1 後 rules/ 常時 load 内訳 = L1 10 件 (30.7k) + plan-review (2.9k) + branch-pr-workflow (4.6k) = **38.2k** (= §2.0 (A) Phase C 後と完全一致)。

stage 2 後 = L1 10 件圧縮 (21.5k) + L3-auto branch-pr-workflow description (0.15k) = **21.65k** (= §2.0 (A) Phase E 後と完全一致)。

### 3.1.1 invariant trace matrix (F-CRA-001 + F-ADV-001 + F-ADV-002 fix)

各項目は `required_loaded_files` (L1 file 単位、L2/L4 不可) + `required_exact_patterns` (file 単位 AND 条件) で構成。

| # | 群 | 項目 | required_loaded_files | required_exact_patterns (AND) | fallback reference |
|---:|---|---|---|---|---|
| A1 | 重要原則 | AI 出力直結禁止 | ai-output-boundary.md / core.md §5 | `AI 出力`, `artifact` | DD-04 |
| A2 | 重要原則 | deny-by-default | core.md §6 + instincts.md | `deny-by-default`, `tool_mutating_gateway_stub` | DD-05 |
| A3 | 重要原則 | Sprint Pack / ADR Gate 11 種 | sprint-pack-adr-gate.md §4 | `ADR Gate Criteria`, `11 種` | docs/sprints/README.md |
| A4 | 重要原則 | Provider Compliance v2 | provider-compliance.md / core.md §7 | `payload_data_class`, `allowed_data_class`, `13 reason_code\|13 種` | DD-04 |
| A5 | 重要原則 | SecretBroker atomic claim | secretbroker-boundary.md | `atomic claim` AND `actor` AND `run` AND `fingerprint` AND `capability` AND `raw secret` (F-ADV-002 fix: AND 全 6 要素) | DD-06 |
| A6 | 重要原則 | AgentRun 16 状態 + blocked サブ 3 | agentrun-state-machine.md / core.md §9 | `16 状態`, `blocked_reason`, `terminal` | DD-03 |
| A7 | 重要原則 | 用語不変条件 | core.md §7/§10 + provider-compliance.md §3 + ai-output-boundary.md §9 | `tool_mutating_gateway_stub`, `runner_mutation_gateway`, `public < internal < confidential < pii` | core.md |
| A8 | 重要原則 | ContextSnapshot 10 カラム | agentrun-state-machine.md §11 | `ContextSnapshot`, `10`, `prompt_pack_version`, `provider_request_fingerprint`, `snapshot_kind` | DD-03 |
| B1-B7 | Hard Gates 7 | (各 7 種、L1 10 件のうち最低 1 つで hit) | L1 10 件のいずれか | 各 Hard Gate 文字列 | reference/hard-gates-and-kpis.md |
| C1-C5 | Quality KPIs 5 | (rules + reference + CLAUDE.md で hit、WARN only) | (常時 load 不要) | 各 KPI 文字列 | reference/hard-gates-and-kpis.md |

**§3.1.1 検証手順** (Phase A-E 完了時に毎回実行、Codex F-PR42-003 fix: L1 file 単位 grep):

```bash
verify_invariant() {
  local item_id="$1"; local file="$2"; shift 2
  local patterns=("$@")
  if [ ! -f "$file" ]; then
    echo "VIOLATION [$item_id]: required file not found: $file"
    return 1
  fi
  for p in "${patterns[@]}"; do
    if ! grep -qE "$p" "$file"; then
      echo "VIOLATION [$item_id]: pattern '$p' missing in $file"
      return 1
    fi
  done
  echo "OK [$item_id]: $file all patterns present (${#patterns[@]} patterns)"
}

# A1-A8 (8 重要原則)
verify_invariant "A1" .claude/rules/ai-output-boundary.md 'AI 出力' 'artifact'
verify_invariant "A2" .claude/rules/core.md 'deny-by-default'
verify_invariant "A2-aux" .claude/rules/ai-output-boundary.md 'tool_mutating_gateway_stub'
verify_invariant "A3" .claude/rules/sprint-pack-adr-gate.md 'ADR Gate Criteria' '11 種'
verify_invariant "A4" .claude/rules/provider-compliance.md 'payload_data_class' 'allowed_data_class' '13 reason_code|13 種'
verify_invariant "A5" .claude/rules/secretbroker-boundary.md 'atomic claim' 'actor' 'run' 'fingerprint' 'capability' 'raw secret'
verify_invariant "A6" .claude/rules/agentrun-state-machine.md '16 状態' 'blocked_reason' 'terminal'
verify_invariant "A7" .claude/rules/core.md 'tool_mutating_gateway_stub' 'runner_mutation_gateway' 'public < internal < confidential < pii|public.*internal.*confidential.*pii'
verify_invariant "A8" .claude/rules/agentrun-state-machine.md 'ContextSnapshot' '10' 'prompt_pack_version' 'provider_request_fingerprint' 'snapshot_kind'

# B1-B7 Hard Gates (Codex F-PR42-003 fix: L1 10 file 限定 + file 単位 hit)
L1_FILES=(
  .claude/rules/core.md
  .claude/rules/ai-output-boundary.md
  .claude/rules/instincts.md
  .claude/rules/secretbroker-boundary.md
  .claude/rules/provider-compliance.md
  .claude/rules/agentrun-state-machine.md
  .claude/rules/cross-source-enum-integrity.md
  .claude/rules/server-owned-boundary.md
  .claude/rules/sprint-pack-adr-gate.md
  .claude/rules/codex-usage-policy.md
)
for gate in 'policy_block_recall' 'secret_canary_no_leak|secret canary' 'tenant_isolation_negative_pass|tenant_id' \
  'backup_restore_rpo_rto|RPO.*RTO' 'forbidden_path|forbidden path' 'dangerous_command|dangerous command' \
  'prompt_injection|untrusted_content'; do
  count=0
  for f in "${L1_FILES[@]}"; do
    [ ! -f "$f" ] && continue
    grep -qE "$gate" "$f" && count=$((count + 1))
  done
  echo "[$count] Hard Gate: $gate (L1 file 単位 hit)"
  [ "$count" -eq 0 ] && { echo "VIOLATION: Hard Gate '$gate' は L1 always-loaded rules のいずれにも hit せず"; exit 1; }
done

# Quality KPIs 5 (WARN only)
for pattern in 'acceptance_pass_rate' 'time_to_merge' 'approval_wait_ms' 'citation_coverage' 'cost_per_completed_task'; do
  count=$(grep -rE "$pattern" .claude/rules/ .claude/reference/ .claude/CLAUDE.md 2>/dev/null | wc -l)
  [ "$count" -eq 0 ] && echo "WARN: KPI $pattern が rules + reference + CLAUDE.md から消失"
done
```

### 3.2 L2 path-scoped (F-CRA-008 + F-ADV-004 fix)

| rule file | paths | 理由 |
|---|---|---|
| rendering.md | `["frontend/**", "docs/基本設計/UI*.md", "docs/sprints/SP-009_*.md", "docs/sprints/SP-010_*.md"]` | frontend / UI docs / Sprint 9-10 |
| testing.md | `["backend/**", "frontend/**", "migrations/**", "eval/**", "**/tests/**", "**/test_*.py", "**/*.spec.ts", "**/*.test.ts", "package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock", "Dockerfile*", "docker-compose*.yml", ".github/**", "scripts/**", "Makefile", "*.config.*"]` | テスト挙動を変える全 file (F-ADV-004 fix) |
| code-search.md | `["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.go", "**/*.rs", "**/*.sh", "**/*.md", "**/*.json", "**/*.yml", "**/*.yaml", "**/*.toml", "Dockerfile*", "Makefile"]` | code / 設定 / docs 検索 (F-ADV-004 fix) |

`sprint-pack-adr-gate.md` は L1 維持 (F-CRA-002 fix、paths 設定しない)。

### 3.3 L3 skill 化 (F-CRA-005 + F-ADV-205 fix: 2 種 + 移行期間 L1 reminder)

| L3 種別 | frontmatter | invocation | description token |
|---|---|---|---:|
| L3-manual | `disable-model-invocation: true` | 明示 `/skill-name` のみ | 0 (context 除外) |
| L3-auto | `disable-model-invocation: false` | description match で auto invoke | 50-150 token 常時 load |

| 現 rule | skill / agent | L3 種別 | 移行リスク軽減策 (F-ADV-205 fix) |
|---|---|---|---|
| plan-review.md (2.9k) | `plan-reviewer` agent body 統合 | (agent) | Agent tool invocation で常時利用可、移行リスク低 |
| branch-and-pr-workflow.md (4.6k) | `branch-pr-workflow` skill | L3-auto | (1) skill description で「PR / worktree 操作前に必ず invoke」明記、(2) **PR 前 hard gate**: `.github/PULL_REQUEST_TEMPLATE.md` または `gh pr create` wrapper に `branch-pr-workflow evidence marker` 必須化 (skill 起動 record + 内容確認 ✓ チェック)、(3) **移行期間 1 週間は最小 L1 reminder (30 行)** を `.claude/rules/branch-and-pr-workflow.md` として残す (skill body から重要 30 行抜粋)、(4) 1 週間 auto invoke 観測 clean まで L1 reminder 削除しない |

### 3.4 L4 reference 化 (manual Read)

| 現 rule | reference 移動先 |
|---|---|
| multi-agent-orchestration.md (4k draft) | `.claude/reference/multi-agent-orchestration-draft.md` |
| codex-multi-round-workflow.md (1.8k) | `.claude/reference/codex-workflow-knowledge.md` に統合 |
| codex-output-contract.md (2.6k) | 同上 |
| codex-pr-review-checklist.md (6.3k) | `.claude/scripts/codex_pr_full_review.README.md` |
| user-preferences.md (2.6k) | CLAUDE.md §2 + core.md + reference/ に分割移送、rule 削除 |

### 3.5 `~/.claude/CLAUDE.md` 整理 (Phase E、dotfiles 別 PR)

aggressive 案 (採用): TaskManagedAI 無関係内容を `~/.claude/reference/{neovim, nb, moltbot, drawio, tmux, dotfiles, tailnet, paths}.md` に分離、user-global は「全 project 共通 workflow 原則」(5 ルール + Codex 連携詳細 + 失敗保護) のみ 150 行 / 5-10k に。

### 3.6 `.claude/CLAUDE.md` 圧縮

§6.5 各 subsection を rules/ 側正本に統合 + 1-3 行 summary + link。

---

## 4. 各 rule の処遇 (全 20 件、Codex F-PR42-001 + F-PR42-002 fix: paths 同期 + stage 1 圧縮なし)

| # | rule file | 現状 | 層 | 移送先 / paths | Phase | stage 1 後 | stage 2 後 |
|---:|---|---:|---|---|---|---:|---:|
| 1 | core.md | 3.2k | L1 | 維持 | E | 3.2k | 2.5k |
| 2 | ai-output-boundary.md | 2.8k | L1 | 維持 | E | 2.8k | 2.0k |
| 3 | instincts.md | 3.2k | L1 | 維持 | E | 3.2k | 2.3k |
| 4 | secretbroker-boundary.md | 4.7k | L1 | 維持 | E | 4.7k | 3.0k |
| 5 | provider-compliance.md | 3.6k | L1 | 維持 | E | 3.6k | 2.5k |
| 6 | agentrun-state-machine.md | 4.6k | L1 | 維持 | E | 4.6k | 2.5k |
| 7 | cross-source-enum-integrity.md | 1.7k | L1 | 維持 | - | 1.7k | 1.5k |
| 8 | server-owned-boundary.md | 1.3k | L1 | 維持 | - | 1.3k | 1.2k |
| 9 | sprint-pack-adr-gate.md | 3.0k | L1 | 維持 | E | 3.0k | 2.0k |
| 10 | codex-usage-policy.md | 2.6k | L1 | 維持 | E | 2.6k | 1.5k |
| 11 | rendering.md | 2.3k | L2 | `paths: ["frontend/**", "docs/基本設計/UI*.md", "docs/sprints/SP-009_*.md", "docs/sprints/SP-010_*.md"]` | B | 0 (条件 load) | 0 |
| 12 | testing.md | 3.5k | L2 | §3.2 参照 (F-CRA-008 + F-ADV-004 fix で root config / CI / Docker / scripts / lockfile 含む) | B | 0 (条件 load) | 0 |
| 13 | code-search.md | 2.4k | L2 | §3.2 参照 (F-ADV-004 fix で MD / JSON / YAML / TOML / Docker / Makefile 含む) | B | 0 (条件 load) | 0 |
| 14 | plan-review.md | 2.9k | L3 (agent 統合) | `plan-reviewer` agent body 統合 | D | 0 | 0 |
| 15 | branch-and-pr-workflow.md | 4.6k | L3-auto + 移行期間 L1 reminder | `.claude/skills/branch-pr-workflow/SKILL.md` (description 0.15k 常時 + body invoke 時) + 1 週間 L1 reminder 30 行 (F-ADV-205 fix) | D | 0 (skill body) | 0.15k (description) + 0.6k (1 週間 L1 reminder、移行後削除) |
| 16 | codex-pr-review-checklist.md | 6.3k | L4 | `.claude/scripts/codex_pr_full_review.README.md` | C | 0 | 0 |
| 17 | codex-multi-round-workflow.md | 1.8k | L4 | `.claude/reference/codex-workflow-knowledge.md` | C | 0 | 0 |
| 18 | codex-output-contract.md | 2.6k | L4 | 同上 | C | 0 | 0 |
| 19 | user-preferences.md | 2.6k | L1 統合削除 | CLAUDE.md §2 + core.md + reference/ 分割移送 | C | 0 | 0 |
| 20 | multi-agent-orchestration.md | 4.0k | L4 | `.claude/reference/multi-agent-orchestration-draft.md` | C | 0 | 0 |

---

## 5. 移行計画 (2 stage / 5 Phase、Codex Phase 2 R2 finding 全 8 件本文反映)

各 Phase は独立 PR、stage 1 / stage 2 間に calendar wait 7-14 day。**全 Phase Claude 自身が手作業実施** (Codex 委譲なし)。

### 全 Phase 共通: 着手前 preflight gate (F-CRA-006 fix + F-ADV-201/202/204/207 fix)

#### Preflight scratch cleanup contract (F-ADV-207 fix)

各 preflight scratch step (paths 実測 / skill 起動 / @import 解決) は **共通 cleanup contract** を使う:

```bash
# 共通 scratch cleanup trap
SCRATCH_FILES=()
cleanup_scratches() {
  for f in "${SCRATCH_FILES[@]}"; do
    [ -e "$f" ] && rm -rf "$f"
  done
  # git status guard: scratch が tracked / staged / untracked のいずれにも残らないこと
  STATUS=$(git status -sb 2>/dev/null | tail -n +2)
  if [ -n "$STATUS" ]; then
    echo "VIOLATION: git status -sb not clean after preflight, scratch files leaked:"
    echo "$STATUS"
    exit 1
  fi
  # scratch 名が git diff --name-only に残らない (commit / stage 経由 leak 検出)
  LEAKED=$(git diff --name-only HEAD -- 2>/dev/null | grep -E '_scratch_|_scratch_test|scratch_import_test' || true)
  [ -n "$LEAKED" ] && { echo "VIOLATION: scratch leaked to diff: $LEAKED"; exit 1; }
}
trap cleanup_scratches EXIT
# 各 scratch step で SCRATCH_FILES に追加: SCRATCH_FILES+=( "$NEW_SCRATCH" )
# 失敗時 artifact は専用 untracked path に: .claude/local/preflight-artifacts/ (.gitignore 済)
```

#### Preflight failure ledger + BLOCKED 判定 (F-ADV-201 fix)

各 preflight 失敗を **`.claude/plans/context-management-refactor-preflight-failures.md` ledger** に記録:

```markdown
## YYYY-MM-DD HH:MM Phase X preflight failed
- failed step: (1) / (2) / (3) / (4) / (5)
- 実測結果: <observed>
- 原因仮説: <hypothesis>
- owner: @<github-username>
- 修正 PR: #NNN (or draft)
- 再実行条件: <conditions>
- attempt #: 1 / 2
```

判定:
- 1 回目失敗: 上記 ledger 記録、原因解明 → 修正 PR → 再 preflight
- **2 回連続失敗**: 該当 Phase を **defer / reject** に戻し、`.claude/plans/context-management-refactor.md` §10 確定事項 + リスクを再評価。

#### Phase metadata + single writer lock (F-ADV-202 fix)

各 Phase PR の頭に metadata を持たせる:

```yaml
# PR description 末尾 or commit trailer
required_base_sha: <previous-phase-merge-commit>
depends_on_phase: A | B | C | D | E | none
writer_lock_evidence: .claude/plans/context-management-refactor-writer-lock.md
```

各 Phase merge 前 checklist:
- [ ] `git merge-base HEAD main` が `required_base_sha` と一致 (1 commit ahead / 0 ahead で sequential merge)
- [ ] `.claude/plans/context-management-refactor-writer-lock.md` に「Phase X writer = <agent-id>、acquired_at = ISO timestamp、released_at = (after merge)」記録
- [ ] 同 plan が他 PR で並走編集されていない (`git log origin/* --all --grep="context-management-refactor"` で確認)

`.claude/**` を触る作業は single writer lock 必須、複数 worktree / session で同時編集禁止。

#### preflight gate (1)-(5)

```bash
# (1) Claude Code version 記録
claude --version > .claude/plans/context-management-refactor-claude-version-phase<X>.txt

# (2) scratch rule で paths frontmatter 実測 (Phase B 前必須)
SCRATCH_FILES+=( .claude/rules/_scratch_paths_test.md backend/test-only-marker/dummy.py )
mkdir -p backend/test-only-marker
cat > backend/test-only-marker/dummy.py <<'EOF'
# scratch dummy for paths preflight, removed by trap
EOF
cat > .claude/rules/_scratch_paths_test.md <<'EOF'
---
paths: ["backend/test-only-marker/**"]
---
# Scratch rule for paths frontmatter preflight (removed by trap)
sentinel: SCRATCH_PATHS_PREFLIGHT_MARKER_v1
EOF
# 新 session を起動して /context 出力に sentinel 文字列があるかを別 process で観測
# (`backend/test-only-marker/dummy.py` 編集 context で sentinel あり、`frontend/page.tsx` 編集 context で sentinel なし、を確認)
# 観測結果を .claude/plans/context-management-refactor-stage1-evidence.md に記録

# (3) L1 常時 load 確認
# 新 session を `cd ~/repo/TaskManagedAI && claude` で起動、/context で L1 10 件 (Phase D 後は L1 圧縮版) が含まれることを確認

# (4) skill 起動実測 (Phase D 前必須)
SCRATCH_FILES+=( .claude/skills/_scratch_test )
mkdir -p .claude/skills/_scratch_test
cat > .claude/skills/_scratch_test/SKILL.md <<'EOF'
---
name: scratch-test
description: Scratch skill for preflight (removed by trap)
disable-model-invocation: true
---
# Scratch skill body
sentinel: SCRATCH_SKILL_PREFLIGHT_MARKER_v1
EOF
# `/scratch-test` で skill が起動できるか + sentinel が body から取得できるかを新 session で確認

# (5) subagent + @import 実測 (Phase E 前必須、F-ADV-204 fix: 2 段階 sentinel + Read 禁止 / 許可分離)

# (5a) sentinel inject test (Read 禁止条件、inherit vs disk Read を区別)
SCRATCH_FILES+=( .claude/_scratch_import_test.md )
cat > .claude/_scratch_import_test.md <<'EOF'
SUBAGENT_INJECT_SENTINEL_v1=PRESENT_IF_CLAUDE_MD_LOADED
EOF
# .claude/CLAUDE.md に一時的に @.claude/_scratch_import_test.md import を追加 (cleanup 必須)
# 新 session で claude-code-guide subagent を起動、prompt 内で:
# 「Read tool は禁止。あなたの memory / context に SUBAGENT_INJECT_SENTINEL_v1 という文字列があれば echo してください、なければ NOT_PRESENT と返してください」と指示
# Response = "PRESENT_IF_CLAUDE_MD_LOADED" なら inherit success (= CLAUDE.md / @import が subagent に inject される)
# Response = "NOT_PRESENT" or "Read tool 使えませんでした" なら inherit fail (= subagent inject なし、または @import 解決失敗)
# transcript を保存 (tool 使用有無 / Read 試行有無 を ledger 化)

# (5b) Read 許可検証 (実 file read で同 sentinel を取得できるか、別 test として実施)
# 5a の transcript と 5b の transcript を比較、5a で sentinel 出力なら inherit、5a なし 5b ありなら inherit failure (要 Phase E 延期)
```

各 step で SCRATCH_FILES 配列に追加、trap で cleanup。

### Stage 1 (conservative、目標 74.0k)

#### Phase A: 重複削除 (CLAUDE.md §6.5 ↔ rules/ 統合) [1 day]

- §6.5.0-§6.5.9 と rules/{codex-usage-policy, branch-and-pr-workflow, user-preferences, codex-pr-review-checklist}.md の重複を **rules/ 側正本**化、CLAUDE.md は 3-5 行 summary + link
- 効果: CLAUDE.md 29k → 18k (-11k)
- 検証: §3.1.1 trace matrix 20 項目 grep pass、Phase A 後 codex-adversarial-loop で「invariant 削除漏れ」探索
- Phase metadata: `required_base_sha = <main commit>`, `depends_on_phase = none`

#### Phase B: rules/ frontmatter `paths` 設定 [0.5 day]

- preflight gate (2)(3) 必須通過、failure 時は ledger 記録 + 修正 PR
- L2 候補 3 件 (rendering / testing / code-search) に frontmatter 追加 (§3.2 paths)
- 検証: 4 種 session (frontend / backend / docs / migration) で `/context` 計測、evidence file 記録
- Phase metadata: `required_base_sha = <Phase A merge SHA>`, `depends_on_phase = A`

#### Phase C: L4 reference 化 (5 件削除) [0.5 day]

- preflight gate (1)(3) 必須通過
- `codex-multi-round-workflow.md` + `codex-output-contract.md` → `.claude/reference/codex-workflow-knowledge.md` (統合)
- `multi-agent-orchestration.md` → `.claude/reference/multi-agent-orchestration-draft.md`
- `codex-pr-review-checklist.md` → `.claude/scripts/codex_pr_full_review.README.md` (helper script 同梱)
- `user-preferences.md` → CLAUDE.md §2 / core.md / reference/ に**内容統合 + rule 削除**
- 検証: dead-link grep 0 件 (Codex F-PR42-004 fix で plan self-exclude)、reference index 作成
- Phase metadata: `required_base_sha = <Phase B merge SHA>`, `depends_on_phase = B`

### Stage 1 → Stage 2 移行 gate (calendar wait 7-14 day、§2.3 詳細)

stage 1 PR merge 時に `<stage1_sha>` 記録、evidence file に gate 4 項目観測結果記録。違反 / drift があれば stage 2 保留。

### Stage 2 (aggressive、目標 40.65k)

#### Phase D: L3 skill / agent 統合 [1 day]

- preflight gate (1)(3)(4) 必須通過、failure 時 ledger
- `plan-review.md` → `plan-reviewer` agent body 統合、rule 削除
- `branch-and-pr-workflow.md` → `.claude/skills/branch-pr-workflow/SKILL.md` (L3-auto、`disable-model-invocation: false`)
- **F-ADV-205 fix**: PR 前 hard gate marker を `.github/PULL_REQUEST_TEMPLATE.md` に追加 (`[ ] branch-pr-workflow skill invoked, evidence: <session-id>`)、移行期間 1 週間は L1 reminder (30 行) を `.claude/rules/branch-and-pr-workflow.md` として残す
- **F-ADV-203 fix**: Phase D 前 archive copy を `.claude/archived/<phase-d-base-sha>-<utc-timestamp>/` (base SHA + UTC timestamp 一意 dir) に作成、sha256 manifest 同梱:
  ```bash
  PHASE_D_BASE_SHA=$(git rev-parse HEAD)
  ARCHIVE_DIR=".claude/archived/${PHASE_D_BASE_SHA}-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$ARCHIVE_DIR"
  cp .claude/rules/plan-review.md "$ARCHIVE_DIR/"
  cp .claude/rules/branch-and-pr-workflow.md "$ARCHIVE_DIR/"
  shasum -a 256 "$ARCHIVE_DIR/"*.md > "$ARCHIVE_DIR/manifest.sha256"
  echo "base_sha: $PHASE_D_BASE_SHA" > "$ARCHIVE_DIR/restore-source.txt"
  ```
- 検証: agent / skill 起動 dry-run、PR 前 hard gate marker が PR template に存在
- Phase metadata: `required_base_sha = <Phase C merge SHA + calendar wait 完了 SHA>`, `depends_on_phase = C`

#### Phase E: L1 圧縮 + `~/.claude/CLAUDE.md` 整理 [1 day]

- preflight gate (1)(3)(5) 必須通過、(5) は 5a + 5b 2 段階
- **F-ADV-206 fix**: 着手前 **user-global split security gate** (PASS 条件):
  - [ ] **secret scan**: `gitleaks detect --source ~/.claude/ --no-banner` (または trufflehog 相当) で secret 0 件
  - [ ] **private hostname / IP / path redaction review**: `grep -rE 'tailnet|tailscale|100\.[0-9]+\.[0-9]+\.[0-9]+|t-ohga-(mac|linux|vps|iphone)' ~/.claude/CLAUDE.md` の hit 行を `~/.claude/reference/tailnet.md` (機密) に移送 + 公開 reference からは抜く
  - [ ] **git tracked 対象 list の明示承認**: `git -C /Users/tohga/dotfiles status --porcelain --untracked-files=all` で対象 file 一覧、user 明示承認 (`AskUserQuestion`) 後に tracked / untracked / `~/.claude/local/` (untracked 強制) 振り分け
  - [ ] **機密 reference の local-only 退避**: `~/.claude/reference/{tailnet, paths, moltbot}.md` 等で machine-specific path / private endpoint を含む reference は **`~/.claude/local/reference/` (gitignored)** に置く、dotfiles 管理対象外
- L1 10 件圧縮 (§3.1 stage 2 列): 30.7k → 21.5k (-9.2k)
- `~/.claude/CLAUDE.md` を Neovim / nb / MoltBot / Discord / Tailnet / paths 詳細を分離、user-global は 150 行 / 5-10k に
- dotfiles 連動別 PR (`/Users/tohga/dotfiles/editor/claude-code/claude/CLAUDE.md` + `.../reference/` 群)
- 検証: 新 session で `/context` 40.65k 達成、§3.1.1 trace matrix 全 20 項目再 verify
- Phase metadata: `required_base_sha = <Phase D merge SHA>`, `depends_on_phase = D`

---

## 6. リスク (F-CRA-013 + F-ADV-205 fix)

| # | リスク | severity | unmitigated | 緩和策 |
|---:|---|---|---:|---|
| R1 | CRITICAL invariant 喪失 | CRITICAL | **true** | §3.1.1 trace matrix 全 20 項目 grep verification、Phase A 後 codex-adversarial-loop |
| R2 | path-scoped 漏れ | HIGH | **true** | paths 広め設定、stage 1→2 gate で 4 種 session 観測 |
| R3 | rule ↔ CLAUDE.md drift | MEDIUM | false | CLAUDE.md §6.5 summary に「正本: rules/<name>.md」明示、Codex PR review で drift 検出 |
| R4 | skill 化 rule の invocation 忘れ (F-ADV-205 fix) | MEDIUM | false | skill description で「PR / worktree 操作前に必ず invoke」、**PR 前 hard gate marker** を `.github/PULL_REQUEST_TEMPLATE.md` に追加、**1 週間 L1 reminder (30 行)** を `.claude/rules/branch-and-pr-workflow.md` として残す (1 週間 auto invoke 観測 clean まで削除しない)、L3-auto description 常時 load で trigger 残す |
| R5 | 削減効果限定 | LOW | false | conservative 80k 最低保証、aggressive 35k は L1 圧縮 + user-global 整理 + MEMORY archive |
| R6 | paths 仕様 version 依存 | HIGH | **true** | Phase B 前 preflight (2)(3) で scratch rule + 新 session 実測必須、L1 10 件は絶対に paths 設定しない |

**unmitigated=true の 3 件 (R1 / R2 / R6)** は frontmatter `risks_unmitigated`、stage 1 着手前 preflight gate 通過 + Phase A 後 codex-adversarial-loop で再 verify が mitigation 不十分時の BLOCKER。

---

## 7. rollback 計画 (F-CRA-010 + F-CRA-011 + F-ADV-203 fix)

| Phase | rollback 手順 (第一選択) | 手動 rollback (第二選択) |
|---|---|---|
| A | `git revert <PR-A-merge-commit>` | (不要、rules/ 削除なし) |
| B | `git revert <PR-B-merge-commit>` | frontmatter 手動削除 + `head -5` 確認 |
| C | `git revert <PR-C-merge-commit>` (内容統合は 2 段 PR 推奨: PR-C1 = `git mv` only、PR-C2 = content merge) | `git show <commit>:<file>` で復元、参照 link を `.claude/scripts/audit-link-update.sh` で書き換え |
| D (F-ADV-203 fix) | `git revert <PR-D-merge-commit>` + Phase D 前に作成済の **`.claude/archived/<phase-d-base-sha>-<utc-timestamp>/`** から restore。**restore 前に manifest.sha256 検証必須** (`shasum -a 256 -c $ARCHIVE_DIR/manifest.sha256`)、整合性 PASS なら `cp $ARCHIVE_DIR/*.md .claude/rules/` | manifest 検証後の手動 copy back + frontmatter 再検証 + `/context` 再計測 |
| E | `git revert` (dotfiles 側) | dotfiles symlink target を git checkout で復元、ただし user-global は他 project session への影響を確認 |

---

## 8. 検証 (Codex F-PR42-004 fix: plan self-exclude)

### 8.1 各 Phase 完了時の `/context` 計測 (§2.0 ledger と完全同期)

| 指標 | Phase A 後 | Phase B 後 | Phase C 後 (stage 1) | Phase D 後 | Phase E 後 (stage 2) |
|---|---:|---:|---:|---:|---:|
| Memory files 合計 (§2.0 ledger 同期) | 104.8k (-11k) | 96.6k (-19k) | **74.0k (-42k)** | 64.65k (-51k) | **40.65k (-75k)** |
| `.claude/CLAUDE.md` | 18.0k | 18.0k | 16.0k | 14.0k | 8.0k |
| rules/ 常時 load | 67.0k | 58.8k | 38.2k | 30.85k | 21.65k |
| `~/.claude/CLAUDE.md` | 15.3k | 15.3k | 15.3k | 15.3k | 8.0k |

### 8.2 §3.1.1 invariant trace matrix verification

各 Phase 完了時に `verify_invariant()` (A1-A8) + L1 file 単位 grep (B1-B7、Codex F-PR42-003 fix) + KPI WARN (C1-C5) を実行。全件 pass で次 Phase 着手可。

### 8.3 ファイル存在 / frontmatter / リンク更新 (Codex F-PR42-004 fix)

- L1 10 件 file 存在: `ls .claude/rules/{core,ai-output-boundary,instincts,secretbroker-boundary,provider-compliance,agentrun-state-machine,cross-source-enum-integrity,server-owned-boundary,sprint-pack-adr-gate,codex-usage-policy}.md`
- L2 3 件 frontmatter: `head -10 .claude/rules/{rendering,testing,code-search}.md` で `paths: [...]` 存在
- L4 移送 file 存在 (Phase C 後): `ls .claude/reference/{codex-workflow-knowledge,multi-agent-orchestration-draft}.md .claude/scripts/codex_pr_full_review.README.md`
- 旧 rule への dead link 不在 (Codex F-PR42-004 fix: plan self-exclude): `find .claude/ docs/ -type f ! -path "*plans/context-management-refactor*.md" ! -path "*/archived/*" -print0 | xargs -0 grep -lE "rules/codex-multi-round|rules/codex-output|rules/multi-agent|rules/codex-pr-review|rules/user-preferences" 2>/dev/null` で **0 件**

### 8.4 機能 verification (Phase D / E 後)

- skill auto invoke 観測 (Phase D 後): PR 起票 session で `branch-pr-workflow` skill auto invoke を 1 週間監査、PR template `branch-pr-workflow evidence marker` チェック (F-ADV-205 fix)
- @import + subagent inject 実測 (Phase E 後): preflight gate (5) の 2 段階 sentinel test を再実行

---

## 9. 想定外の落とし穴 (preflight gate 必須通過事項)

- **`paths` frontmatter version 依存**: Phase B 前 preflight (2) 実測必須、失敗時は failure ledger 記録 + Phase B 延期
- **`@import` 相対パス解決基準**: Phase E 前 preflight (5) 実測必須、失敗時は @import 使わず Phase E 進行 (token 削減効果薄いので必達ではない)
- **subagent inject 範囲**: Phase E 前 preflight (5) の 2 段階 sentinel test、失敗時 Phase E 延期 (F-ADV-204 fix)

---

## 10. 確定事項 (2026-05-17 user 確認 + Phase 1+2 R1-R2 finding 反映)

| # | 項目 | 確定内容 |
|---:|---|---|
| 1 | 削減目標 / 方向性 | **段階適用** (Claude 判断)。stage 1 = 74.0k 目標 → calendar wait 7-14 day → stage 2 = 40.65k 目標 |
| 2 | 適用範囲 | project (`.claude/`) + user-global (`~/.claude/`) 両方 (stage 2 Phase E で dotfiles 別 PR) |
| 3 | codex-all-loops 起動 | 本 plan polish にのみ使用、Phase 1 (review-loop R1-R3 / 15 finding adopt) + Phase 2 (adversarial-loop R1-R2 / 20 finding adopt) 完了 |
| 4 | 実装 executor | **Phase A-E 全フェーズ Claude 自身が手作業実施**、Codex 委譲なし |
| 5 | dotfiles 連動 PR | stage 2 Phase E で別 PR 起票 |
| 6 | L3 skill 化 | branch-and-pr-workflow を L3-auto + 移行期間 1 週間 L1 reminder (F-ADV-205 fix)、plan-review を agent body 統合 |
| 7 | sprint-pack-adr-gate 層 | L1 確定 (F-CRA-002 fix) |
| 8 | codex-usage-policy 層 | L1 確定 (F-CRA-007 fix) |
| 9 | calendar wait | default 7 day、最大 14 day |
| 10 | preflight failure ledger | `.claude/plans/context-management-refactor-preflight-failures.md` ledger 必須、2 回連続失敗で defer/reject (F-ADV-201 fix) |
| 11 | Phase metadata + writer lock | 各 Phase PR に `required_base_sha` + `depends_on_phase` + writer lock evidence (F-ADV-202 fix) |
| 12 | Phase D archive path | base SHA + UTC timestamp + sha256 manifest (F-ADV-203 fix) |
| 13 | subagent inject 実測 | sentinel + Read 禁止 / 許可分離 2 段階 (F-ADV-204 fix) |
| 14 | user-global split security gate | Phase E 前に secret scan + redaction + local-only 振り分け (F-ADV-206 fix) |
| 15 | preflight scratch cleanup | 共通 trap + git status guard (F-ADV-207 fix) |

---

## 11. 関連参照

### 公式 doc (構造的整合のみ判定)

- https://code.claude.com/docs/en/memory.md
- https://code.claude.com/docs/en/skills.md
- https://code.claude.com/docs/en/how-claude-code-works.md

### 移行対象 rules 全 20 件 (層別)

#### L1 常時 alwaysApply (10 件)
- `core.md` / `ai-output-boundary.md` / `instincts.md` / `secretbroker-boundary.md` / `provider-compliance.md` / `agentrun-state-machine.md` / `cross-source-enum-integrity.md` / `server-owned-boundary.md` / `sprint-pack-adr-gate.md` / `codex-usage-policy.md`

#### L2 path-scoped (3 件、Phase B)
- `rendering.md` / `testing.md` / `code-search.md`

#### L3 skill / agent 統合 (2 件、Phase D)
- `plan-review.md` (→ `plan-reviewer` agent body) / `branch-and-pr-workflow.md` (→ L3-auto skill + 1 週間 L1 reminder)

#### L4 reference 化 (5 件、Phase C)
- `multi-agent-orchestration.md` (→ `.claude/reference/multi-agent-orchestration-draft.md`)
- `codex-multi-round-workflow.md` + `codex-output-contract.md` (→ `.claude/reference/codex-workflow-knowledge.md`)
- `codex-pr-review-checklist.md` (→ `.claude/scripts/codex_pr_full_review.README.md`)
- `user-preferences.md` (→ CLAUDE.md §2 / core.md / reference/ 分割移送)

### 関連 reference / scripts (新規 / update)

- `.claude/reference/codex-workflow-knowledge.md` (Phase C)
- `.claude/reference/multi-agent-orchestration-draft.md` (Phase C)
- `.claude/reference/README.md` (Phase C index file)
- `.claude/scripts/codex_pr_full_review.README.md` (Phase C)
- `.claude/scripts/audit-invariant-violation.sh` (Phase B 完了時、§3.1.1 trace matrix grep verification 自動化)
- `.claude/scripts/audit-link-update.sh` (Phase C 完了時、参照リンク書き換え)
- `.claude/plans/context-management-refactor-stage1-evidence.md` (stage 1 完了時、gate 4 項目観測)
- `.claude/plans/context-management-refactor-preflight-failures.md` (preflight failure ledger、F-ADV-201)
- `.claude/plans/context-management-refactor-writer-lock.md` (Phase metadata writer lock、F-ADV-202)
- `.claude/archived/<phase-d-base-sha>-<utc-timestamp>/` (Phase D 前 archive、F-ADV-203)
- `.github/PULL_REQUEST_TEMPLATE.md` (PR template、`branch-pr-workflow evidence marker` 追加、F-ADV-205)

### 関連 repo file

- `.claude/CLAUDE.md` (project、現状 865 行 / 29k → Phase E 後 ~250 行 / 8k)
- `~/.claude/CLAUDE.md` (user-global、現状 612 行 / 15.3k → Phase E 後 ~150 行 / 8k、dotfiles 管理)
- `CLAUDE.md` (root、27 行 / 1k、変更なし)
- `MEMORY.md` (現状 7k → Phase E 後 5.5k)
