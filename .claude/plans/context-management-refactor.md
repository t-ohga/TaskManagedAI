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
calendar_wait_stage1_to_stage2_days: 7   # 1 週間運用試験 (Sprint 1 batch 1 件分の commit + Codex review 完走 + drift 観測の最低期間)
calendar_wait_max_days: 14
max_days_session_total: 4   # = phase A+B+C+D+E の sum (session 内累計、calendar wait は別)
estimated_token_savings: "115.8k → stage1 (Phase A-C): 74k (-42k, 36%), stage2 (Phase D-E): 41k (-75k, 65%)"   # F-CRA-201 fix 後の正確値、§2.0 統一 ledger と §3.1 完全同期
risks_unmitigated:
  - "R1-CRITICAL-invariant-trace-bug"   # §6 R1: 圧縮中に CRITICAL invariant 文言を意図せず削除
  - "R2-path-scoped-miss"               # §6 R2: paths 漏れによる無関係 session で必要 rule load 漏れ
  - "R6-paths-version-dep"              # §6 R6: paths frontmatter 仕様が Claude Code version 依存
implementation_strategy: "段階適用 (stage 1 = Phase A-C conservative → calendar wait 7-14 day 運用試験 → stage 2 = Phase D-E aggressive)"
implementation_executor: "Claude 自身 (Codex 委譲なし、CRITICAL invariant を含むため)"
review_executor: "codex-all-loops --mode=plan (plan polish のみ Codex skill 使用)"
scope: "project (.claude/) + user-global (~/.claude/、dotfiles 連動 PR 別、Phase E 着手時)"
related_rules:
  - ".claude/rules/core.md"
  - ".claude/rules/codex-usage-policy.md"
  - ".claude/rules/instincts.md"
---

# Context Management Refactor 計画

## 0. TL;DR

Claude Code session 開始時点で **115.8k token (= context window の 11.6%) が memory files** に消費されている。内訳の大部分は **CLAUDE.md (project) 29k + 20 個の `.claude/rules/*.md` が全件常時 inline で 67k** + `~/.claude/CLAUDE.md` 15.3k + MEMORY.md 7k。Claude Code 公式の (1) **CLAUDE.md ≤ 200 行推奨**、(2) **subdirectory rules の `paths` frontmatter による条件付き load**、(3) **Skill `disable-model-invocation: true` の on-demand load** を組み合わせて **2 stage で段階適用** する。

**stage 1 (Phase A-C, conservative)**: 重複削除 + path-scoped + L4 reference 化のみ、目標 **115.8k → 80k (30% 削減)**。**calendar wait 7-14 日** (default 7 日) の運用試験で違反 commit / drift / Codex review finding 不在を観測。

**stage 2 (Phase D-E, aggressive)**: L3 skill/agent 統合 + L1 圧縮 + user-global 整理、目標 **80k → 35-50k (累計 55-70% 削減)**。

**安全性**: TaskManagedAI 不変条件群 (= **8 重要原則** + **Hard Gates 7** + **Quality KPIs 5** = 計 20 項目、CLAUDE.md §2 全体) は **§3.1.1 invariant trace matrix** で L1 rule への保持を機械的に検証。実装フェーズは **Codex 委譲せず Claude 自身が手作業で慎重に** 実施。plan の polish のみ codex-all-loops --mode=plan で multi-round review。各 Phase 前に **preflight gate** (paths 実測 / skill 起動 / @import 解決確認) を必須通過、失敗時は該当 Phase を延期。

---

## 1. 背景・現状

### 1.1 context 配分の現状 (2026-05-17 計測、`/context` より)

| 区分 | token | % | 備考 |
|---|---:|---:|---|
| **Memory files (合計)** | **115.8k** | **11.6%** | 全件常時 load |
| └ `~/.claude/CLAUDE.md` (user-global) | 15.3k | 1.5% | Neovim 設定詳細・nb・MoltBot 等が TaskManagedAI session に無関係 |
| └ `<repo>/CLAUDE.md` (root) | 1.0k | 0.1% | 27 行 / 公式推奨 ≤200 行を遵守 |
| └ `<repo>/.claude/CLAUDE.md` | 29.0k | 2.9% | 865 行 / 推奨の 4 倍超 |
| └ `.claude/rules/*.md` (20 files) | ~67k | ~6.7% | **全件常時 inline** (frontmatter `paths` 未設定) |
| └ `MEMORY.md` (auto-memory) | 7.0k | 0.7% | 公式推奨 ≤25KB を若干超過の懸念 |
| Skills (description のみ) | 10.9k | 1.1% | 120 skill description が常時 load |
| System prompt + System tools | 20.1k | 2.0% | Claude Code 標準 |
| MCP tools (deferred) | 66.1k | 6.6% | ToolSearch 経由で実体 load |
| Custom agents (description) | 5.6k | 0.6% | 35 agent description |
| **合計使用 (Free space 除く)** | **152.5k** | **15.2%** | |

### 1.2 問題

- **重複**: `.claude/CLAUDE.md §6.5.0-§6.5.9` (約 600 行 / 18k token) と rules/{codex-usage-policy, branch-and-pr-workflow, user-preferences, codex-pr-review-checklist}.md の内容が **70-90% 重複**。
- **conditional load 未活用**: `.claude/rules/*.md` 20 件には frontmatter `paths` が**一切設定されていない**ため全件常時 inline。`rendering.md` (frontend 専用) も backend session で load される。
- **user-global の TaskManagedAI 無関係情報**: `~/.claude/CLAUDE.md` 612 行のうち 70-80% は Neovim プラグイン詳細・nb 使い方・MoltBot・Discord・Draw.io 等。
- **draft / 非 active rule の常時 load**: `multi-agent-orchestration.md` は P0.1+ 向け Phase F draft 明記、現在は不要。

### 1.3 公式仕様 (Claude Code、claude-code-guide subagent 経由で確認、構造的整合のみ判定)

出典: https://code.claude.com/docs/en/memory.md / https://code.claude.com/docs/en/skills.md (Codex 側からの URL 中身検証は不可、本 plan 内では構造的整合のみ前提)

| 公式仕様 | 内容 |
|---|---|
| CLAUDE.md 階層 | user-global (`~/.claude/`) → project root (`<repo>/CLAUDE.md`) → project (`<repo>/.claude/CLAUDE.md`) → local (`.claude.local.md`) の全て常時 load |
| 推奨 size | `CLAUDE.md ≤ 200 行`、`MEMORY.md ≤ 200 行 or 25KB` |
| **subdirectory rules** | `.claude/rules/*.md` は `paths: [...]` frontmatter で **path-scoped conditional load**。frontmatter なしは全件常時 load (本 repo の現状) |
| **@import 構文** | `@relative/path.md` で他 file 参照、**import 内容も常時 load** (token 削減効果は薄い、整理目的)。max depth 5 |
| **Skill (on-demand)** | `disable-model-invocation: true` で description も context から除外 = **manual skill** (明示 `/skill-name` でのみ起動)。`disable-model-invocation: false` (default) で description が常時 load = **auto-invokable skill** (Claude が description match で auto invoke) |
| Subagent | 完全独立 context、親 session の conversation 非継承、但し CLAUDE.md は subagent にも load (現時点 plan §9 で未確認、Phase E 前 preflight で実測必須) |
| auto-compaction | 旧 tool output 削除 → 必要時 conversation summarize、CLAUDE.md は compaction 後も disk から re-read & re-inject |

**重要結論**: token 削減の主要ハンドルは (a) **CLAUDE.md 本文の圧縮**、(b) **`paths` frontmatter で rules/ を path-scoped 化**、(c) **rule の manual skill 化 (`disable-model-invocation: true`)** の 3 つ。`@import` は整理にはなるが token 削減効果は薄い。

---

## 2. 目標 (段階適用、F-CRA-101 fix: 統一 token ledger)

### 2.0 統一 token ledger (本 plan 全 § で参照する正本、F-CRA-201 fix: §3.1 を正本に再計算)

(A) は §3.1 「stage 1 後は L1 圧縮なし / stage 2 後 (= Phase E) で L1 一括圧縮 -9.2k」を正本として再計算。

| 区分 | 現状 | Phase A 後 | Phase B 後 | Phase C 後 (=stage 1) | Phase D 後 | Phase E 後 (=stage 2) |
|---|---:|---:|---:|---:|---:|---:|
| **(A) `.claude/rules/*.md` 常時 load (no path-scope session)** | 67.0k / 20 件 | 67.0k / 20 件 | 58.8k / 17 件 (L2 3 件 path-scoped 除外、-8.2k) | **38.2k / 12 件** (L4 5 件削除 -17.3k + user-preferences 削除込み、§3.1 = 30.7k + plan-review 2.9k + branch-pr-workflow 4.6k = 38.2k) | **30.85k / 10 件 + skill description 0.15k** (Phase D で plan-review agent 統合 + branch-pr-workflow skill 化、-7.5k + skill description +0.15k) | **21.65k / 10 件** (Phase E で L1 一括圧縮 -9.2k、§3.1 stage 2 列計 21.5k + skill description 0.15k) |
| **(B) `<repo>/.claude/CLAUDE.md`** | 29.0k / 865 行 | 18.0k / ~500 行 (§6.5 重複削除 -11k) | 18.0k | 16.0k / ~450 行 (Phase C reference 整理 -2k) | 14.0k / ~380 行 (Phase D §6.5.8 統合 -2k) | 8.0k / ~250 行 (Phase E §6.5 残圧縮 -6k) |
| **(C) `<repo>/CLAUDE.md` (root)** | 1.0k / 27 行 | 1.0k | 1.0k | 1.0k | 1.0k | 1.0k |
| **(D) `~/.claude/CLAUDE.md` (user-global)** | 15.3k / 612 行 | 15.3k | 15.3k | 15.3k | 15.3k | 8.0k / ~250 行 (Phase E dotfiles 別 PR -7.3k) |
| **(E) MEMORY.md (auto-memory)** | 7.0k | 7.0k | 7.0k | 7.0k | 7.0k | 5.5k (Phase E 古 entry archive -1.5k) |
| **(F) Skills description (常時 load)** | 10.9k | 10.9k | 10.9k | 10.9k | 11.05k (L3-auto branch-pr-workflow +0.15k 含む、ただし (A) で計上済のため (F) では加算しない、ledger 上は (A) のみで管理) | 11.05k (同上、(A) で管理) |
| **(G) Custom agents description** | 5.6k | 5.6k | 5.6k | 5.6k | 5.6k | 5.6k |
| **(H) System prompt + tools** | 20.1k | 20.1k | 20.1k | 20.1k | 20.1k | 20.1k |
| **memory files 小計 (A+B+C+D+E)** | **119.3k** | **108.3k** | **100.1k** | **77.5k** | **68.15k** | **44.15k** |
| **memory files 合計 (system prompt 除く)** | **115.8k** ※ | **104.8k** | **96.6k** | **74.0k** | **64.65k** | **40.65k** |
| **削減量 (現状比、合計ベース)** | 0 | **-11k (-10%)** | **-19k (-16%)** | **-42k (-36%)** | **-51k (-44%)** | **-75k (-65%)** |

※ 現状の 115.8k は `/context` 計測値、§2.0 (A+B+C+D+E) の 119.3k との差 3.5k は description / agents の重複 / 切り上げ誤差 (誤差範囲)。

stage 1 = Phase A-C で **-42k (115.8k → 74k)**、stage 2 = Phase D-E で **-75k (115.8k → 41k)**。conservative 目標 80k クリア (実際 74k)、aggressive 目標 35-50k の範囲内 (実際 41k)。

### 2.1 stage 1 (conservative、Phase A-C、本 plan の初回 PR scope)

§2.0 統一 ledger より、stage 1 完了後 (= Phase C 後) は **memory files 77.3k (-38k、33% 削減)**。

stage 1 中の `.claude/rules/*.md` 常時 load 件数の推移:

| Phase | rules/ 常時 load 件数 | 内訳 |
|---|---:|---|
| 現状 | 20 件 | 全 20 件 frontmatter なし、全件 inline |
| A 後 | 20 件 | rules/ 構造変更なし、CLAUDE.md §6.5 重複削除のみ |
| B 後 | 17 件 | L2 3 件 (rendering / testing / code-search) に paths frontmatter、無関係 session で除外 |
| C 後 (= stage 1) | **12 件** | L4 5 件削除 (multi-agent / codex-multi-round / codex-output / codex-pr-review / user-preferences) |

stage 1 完了時の rules/ **常時 load L1 10 件 + path-scoped 候補 L2 3 件** 合計 13 件 (= 削除 5 件 + skill 化対象残 2 件 [plan-review / branch-and-pr-workflow])。

L1 常時 load 10 件の内訳 (Phase C 後、§3.1 で詳細):
- **CRITICAL invariant 8 件**: core / ai-output-boundary / instincts / secretbroker-boundary / provider-compliance / agentrun-state-machine / cross-source-enum-integrity / server-owned-boundary
- **Sprint Pack / ADR Gate 必須 1 件**: sprint-pack-adr-gate (F-CRA-002 fix: L1 維持)
- **Codex 連携 1 件**: codex-usage-policy (F-CRA-007 fix: 全 session 運用)

注: `user-preferences.md` (現 2.6k) は Phase C で内容を CLAUDE.md §2 / core.md / reference/ に分割移送し **rule 削除**、L1 にも残らない。`plan-review.md` (現 2.9k) と `branch-and-pr-workflow.md` (現 4.6k) は stage 1 では rules/ に残り常時 load (Phase D で skill 化)。よって stage 1 後の rules/ 常時 load = L1 10 件 + plan-review + branch-and-pr-workflow = **計 12 件 / 38.2k** (§2.0 統一 ledger と完全一致、F-CRA-201 + F-ADV-010 fix 後)。

### 2.2 stage 2 (aggressive、Phase D-E、calendar wait 7-14 day 後の追加 PR scope)

§2.0 統一 ledger より、stage 2 完了後 (= Phase E 後) は **memory files 48.5k (-67k、58% 削減)**。aggressive 目標 35-50k の上限内。

stage 2 中の `.claude/rules/*.md` 常時 load 件数の推移:

| Phase | rules/ 常時 load 件数 | 内訳 |
|---|---:|---|
| C 後 (= stage 1) | 12 件 | 上記 §2.1 末尾 |
| D 後 | **10 件 + L3-auto description 0.15k** | plan-review (agent body 統合) + branch-and-pr-workflow (skill 化) 削除 |
| E 後 (= stage 2) | **10 件 / 21.65k 圧縮版** | L1 10 件を §3.1 stage 2 列に従って圧縮 (-9.2k) + L3-auto description 0.15k |

### 2.3 stage 1 → stage 2 移行 gate (calendar wait 7-14 day、F-CRA-004 fix: 観測コマンド具体化)

stage 1 merge commit SHA を `<stage1_sha>` として記録 (PR merge 後に書き込み)。`<stage1_sha>` から `HEAD` までの期間で以下を観測:

- [ ] **path-scoped 化 rule が想定通り load される**: 新 session を 4 種類で開始 (frontend / backend / docs / migration)、各 `/context` 出力で L2 rule の load 状態を確認、accepted load pattern を `.claude/plans/context-management-refactor-stage1-evidence.md` に記録
- [ ] **不変条件違反 commit が発生していない** (F-ADV-003 fix: 監査対象を全変更 file に拡張): `git diff --name-only <stage1_sha>..HEAD` を正本に、**全変更 file** を `.claude/scripts/audit-invariant-violation.sh` (新規) に渡す。監査対象には **必ず**:
  - 実装系: `backend/**`, `frontend/**`, `migrations/**`, `eval/**`
  - **本 refactor の主要変更面**: `.claude/**` (rule / skill / agent / hook / scripts / plans / reference)、`docs/**`
  - **インフラ系**: `scripts/**`, `.github/**` (CI workflow)、Docker / Compose / config (`docker-compose*.yml`, `Dockerfile*`)
  - **root manifests**: `package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`, `Makefile`, `CLAUDE.md`
  - 上記以外も含めて violation 0 件、限定 path のみ監査で false-positive (drift なし = 安全) を防ぐ
- [ ] **rule ↔ CLAUDE.md drift なし**: `git diff <stage1_sha>..HEAD -- .claude/CLAUDE.md .claude/rules/` で diff line 数 < 50 (重大変更なし)、CLAUDE.md §2 と rules/ L1 10 件の内容を `diff` で確認
- [ ] **Codex PR review で「rule 違反検出漏れ」がない** (Codex F-PR42-005 fix: `gh pr list` の default `--limit 30` で取りこぼし防止、`--limit 1000` または `gh search prs` を使う): `<stage1_sha>` から `HEAD` までの全 PR (`gh pr list --base main --state merged --search "merged:>=<stage1_sha_date>" --limit 1000` または `gh search prs repo:t-ohga/TaskManagedAI base:main is:merged merged:>=<stage1_sha_date> --limit 1000`) について `.claude/scripts/codex_pr_full_review.sh <PR>` で全 finding を確認、rule 違反指摘で本来 stage 1 で load されるべき rule が漏れて発生した finding が 0 件

evidence artifact path:
- `.claude/plans/context-management-refactor-stage1-evidence.md`: gate 4 項目の観測結果集約
- `~/.claude/local/codex-reviews/<date>/TaskManagedAI/stage1-gate-evidence/`: Codex review finding 全文 archive

**いずれかに違反 / drift があれば stage 2 を保留**、まず該当 Phase の path 設定 / 移送先 / rule 内容を調整する fix PR を起票し、再度 7-14 day の calendar wait を開始。

### 2.4 不変条件群 (CLAUDE.md §2 全体、計 20 項目)

| # | 群 | 項目数 | 詳細 |
|---:|---|---:|---|
| A | **8 重要原則** (CLAUDE.md §2.1-§2.8、alwaysApply) | 8 | (1) AI 出力直結禁止、(2) deny-by-default、(3) Sprint Pack 必須ゲート / ADR Gate Criteria 11 種、(4) Provider Compliance Matrix v2 機械判定 invariant、(5) SecretBroker atomic claim / actor-run-fingerprint binding、(6) AgentRun 16 状態 + blocked サブ 3、(7) 用語不変条件、(8) ContextSnapshot 必須 10 カラム |
| B | **Hard Gates 7** (CLAUDE.md §2 末尾、P0 承認必須) | 7 | policy_block_recall / secret_canary_no_leak / tenant_isolation_negative_pass / backup_restore_rpo_rto / forbidden_path_block / dangerous_command_block / prompt_injection_resist |
| C | **Quality KPIs 5** (CLAUDE.md §2 末尾、改善対象、未達 1 個以下 P0 承認可) | 5 | acceptance_pass_rate / time_to_merge / approval_wait_ms / citation_coverage / cost_per_completed_task |
| | **合計** | **20** | |

本 plan で「不変条件群 20」と書く場合は上記 A+B+C を指す。L1 常時 load の必須要件は **A (8 重要原則)** + **B (Hard Gates 7)** の **計 15 項目** を網羅すること。C (Quality KPIs 5) は改善指標で L1 必須ではないが、§3.1.1 trace matrix では 20 項目すべての保持先を明示する。

---

## 3. 設計方針: 4 層分類

| 層 | 定義 | 例 | token 効果 |
|---|---|---|---|
| **L1 常時 alwaysApply** | 全 session で必須。忘れたら CRITICAL 事故 | core / ai-output-boundary / instincts / secretbroker-boundary / provider-compliance / agentrun-state-machine / cross-source-enum-integrity / server-owned-boundary + sprint-pack-adr-gate + codex-usage-policy (+ user-preferences 統合先) | 維持 (圧縮のみ) |
| **L2 path-scoped (frontmatter `paths`)** | 特定領域編集時のみ必要 | rendering (frontend) / testing (backend+frontend+migration+test) / code-search (code 編集全般) | 該当 session のみ load |
| **L3 skill 化 (on-demand)** | 特定 task 開始時のみ必要、2 種類に細分 | (L3-manual) `disable-model-invocation: true`、明示 `/skill-name` でのみ起動 / (L3-auto) `disable-model-invocation: false`、description 常時 load で auto invoke | (manual) body も description も非 load、明示起動時のみ / (auto) description は常時 load、body は invoke 時のみ |
| **L4 reference 化 (manual Read)** | 滅多に参照しない、draft / 完了済み / 詳細手順 | multi-agent-orchestration (P0.1+ draft) / codex-multi-round-workflow / codex-output-contract / codex-pr-review-checklist (helper script README として) | Read 時のみ |

### 3.1 L1 (常時 load) 確定リスト 10 件 (F-CRA-101 fix: 11 → 10 件統一、§2.0 ledger 同期)

stage 1 完了 (Phase C 後) は **L1 圧縮なし** (Phase E で圧縮)、現状 token 値そのまま。stage 2 完了 (Phase E 後) は §3.1 stage 2 列の圧縮値。

| rule file | 現状 token | stage 1 後 (= Phase C 後、圧縮なし) | stage 2 後 (= Phase E 後、圧縮版) | L1 採用理由 |
|---|---:|---:|---:|---|
| `core.md` | 3.2k | 3.2k | 2.5k | TaskManagedAI 全体の基本制約 (型安全 / AI 出力境界 / deny-by-default / 8 重要原則) |
| `ai-output-boundary.md` | 2.8k | 2.8k | 2.0k | Hard Gate AC-HARD-01 / -05 / -06 / -07 直結 |
| `instincts.md` | 3.2k | 3.2k | 2.3k | 17 種の事故予防、CRITICAL invariant の暗黙 sanity check |
| `secretbroker-boundary.md` | 4.7k | 4.7k | 3.0k | Hard Gate AC-HARD-02 直結、raw secret 非保存 invariant |
| `provider-compliance.md` | 3.6k | 3.6k | 2.5k | Provider 越境 deny、13 reason_code 不変条件 |
| `agentrun-state-machine.md` | 4.6k | 4.6k | 2.5k | AgentRun 16 状態・blocked サブ 3・terminal 5 種不変条件 |
| `cross-source-enum-integrity.md` | 1.7k | 1.7k | 1.5k | 5+ source 整合 + 4 重防御 pattern |
| `server-owned-boundary.md` | 1.3k | 1.3k | 1.2k | caller-supplied 経路禁止 invariant |
| `sprint-pack-adr-gate.md` (F-CRA-002 fix: L1 確定) | 3.0k | 3.0k | 2.0k | ADR Gate 11 種 (認証/DB schema/API/AI 権限/MCP/Secrets/外部公開/破壊的操作/広範囲 refactor/Provider/GitHub App permission) は backend / migration / API / config 変更で必須 |
| `codex-usage-policy.md` (F-CRA-007 fix: L1 確定) | 2.6k | 2.6k | 2.0k | Codex 連携は全 session で運用、3 連続失敗保護 + 採否判定 3 分類 + workspace-write 承認要件 |
| **L1 10 件合計** | **30.7k** | **30.7k** (stage 1 圧縮なし) | **21.5k** (stage 2 圧縮 -9.2k) | |

stage 1 後 rules/ 常時 load 内訳 (= Phase C 後、L1 圧縮なし):
- L1 10 件: 30.7k
- plan-review.md (Phase D で skill 化、stage 1 末では rules/ に残る): 2.9k
- branch-and-pr-workflow.md (Phase D で skill 化、stage 1 末では rules/ に残る): 4.6k
- L2 3 件 (path-scoped、常時 load 0): 0k
- L4 5 件 + user-preferences (Phase C 削除/統合): 0k
- **stage 1 後 rules/ 常時 load = 30.7 + 2.9 + 4.6 = 38.2k** (= §2.0 ledger (A) Phase C 後と完全一致、F-CRA-201 fix 後)

stage 2 後 rules/ 常時 load 内訳 (= Phase E 後、L1 圧縮版):
- L1 10 件 (圧縮版): 21.5k
- L3-auto branch-pr-workflow description: 0.15k
- **stage 2 後 rules/ 常時 load = 21.5 + 0.15 = 21.65k** (= §2.0 ledger (A) Phase E 後と完全一致、F-CRA-201 fix 後)

注 1: `user-preferences.md` (2.6k) は Phase C で **削除統合** (内容を CLAUDE.md §2 / core.md に分割移送)、L1 にも残らない。
注 2: `codex-multi-round-workflow.md` (1.8k) / `codex-output-contract.md` (2.6k) / `codex-pr-review-checklist.md` (6.3k) は L4 reference 化、L1 から除外。

### 3.1.1 invariant trace matrix (F-CRA-001 fix: 20 項目 trace、Phase A-E 検証必須)

L1 rule への保持を機械的に検証する trace matrix。Phase A-E 各完了時に `必須 grep pattern` で残存確認、不在時は該当 Phase 着手保留。

| # | 群 | 項目 | 正式名称 | 主要保持先 (L1 rule) | 必須 grep pattern | fallback reference |
|---:|---|---|---|---|---|---|
| A1 | 8 重要原則 | AI 出力直結禁止 | (CLAUDE.md §2.1) | ai-output-boundary.md / core.md §5 | `AI 出力直結` または `artifact -> schema_validated -> policy_linted` | DD-04 §AI 境界 |
| A2 | 8 重要原則 | deny-by-default | (CLAUDE.md §2.2) | core.md §6 / instincts.md | `deny-by-default` または `tool_mutating_gateway_stub` | DD-05 §network |
| A3 | 8 重要原則 | Sprint Pack 必須 / ADR Gate 11 種 | (CLAUDE.md §2.3) | sprint-pack-adr-gate.md §4 | `ADR Gate Criteria 11 種` または `ADR Gate Criteria` | docs/sprints/README.md |
| A4 | 8 重要原則 | Provider Compliance v2 機械判定 | (CLAUDE.md §2.4) | provider-compliance.md §6, §9 / core.md §7 | `payload_data_class > allowed_data_class` または `13 reason_code` | DD-04 §Provider Compliance |
| A5 | 8 重要原則 | SecretBroker atomic claim | (CLAUDE.md §2.5) | secretbroker-boundary.md §8 / core.md §10 | `atomic claim` または `actor-run-fingerprint` | DD-06 §SecretBroker |
| A6 | 8 重要原則 | AgentRun 16 状態 + blocked サブ 3 | (CLAUDE.md §2.6) | agentrun-state-machine.md §1, §2 / core.md §9 | `AgentRun.*16 状態` または `blocked_reason.*3` | DD-03 §AgentRun |
| A7 | 8 重要原則 | 用語不変条件 (payload_data_class / allowed_data_class / tool_mutating_gateway_stub / runner_mutation_gateway / data class ordinal) | (CLAUDE.md §2.7) | core.md §7, §10 / provider-compliance.md §3 / ai-output-boundary.md §9 | `tool_mutating_gateway_stub.*runner_mutation_gateway` または `public < internal < confidential < pii` | core.md |
| A8 | 8 重要原則 | ContextSnapshot 必須 10 カラム | (CLAUDE.md §2.8) | agentrun-state-machine.md §11 / core.md §9 | `ContextSnapshot.*10` または `provider_request_fingerprint` | DD-03 §ContextSnapshot / PRD-01 F-009 |
| B1 | Hard Gates 7 | policy_block_recall | (CLAUDE.md §2 末尾) | ai-output-boundary.md §6 / core.md §6 | `policy_block_recall` | docs/設計検討/hard-gates.md |
| B2 | Hard Gates 7 | secret_canary_no_leak | 同上 | secretbroker-boundary.md §11 / provider-compliance.md §8 | `secret_canary` | 同上 |
| B3 | Hard Gates 7 | tenant_isolation_negative_pass | 同上 | core.md §8 / instincts.md §8 | `tenant_isolation_negative_pass` または `tenant_id` | 同上 |
| B4 | Hard Gates 7 | backup_restore_rpo_rto | 同上 | core.md §12 (実装前 checklist) / instincts.md §16 | `backup_restore_rpo_rto` または `RPO.*RTO` | 同上 |
| B5 | Hard Gates 7 | forbidden_path_block | 同上 | ai-output-boundary.md §7 / instincts.md §16 | `forbidden_path` または `forbidden path` | 同上 |
| B6 | Hard Gates 7 | dangerous_command_block | 同上 | ai-output-boundary.md §7 / instincts.md §16 | `dangerous_command` または `dangerous command` | 同上 |
| B7 | Hard Gates 7 | prompt_injection_resist | 同上 | ai-output-boundary.md §6 / instincts.md §1 | `prompt_injection` または `untrusted_content` | 同上 |
| C1 | Quality KPIs 5 | acceptance_pass_rate | (CLAUDE.md §2 末尾) | core.md §12 (KPI 関連、ガイダンスのみ) / reference/hard-gates-and-kpis.md | `acceptance_pass_rate` | reference/hard-gates-and-kpis.md |
| C2 | Quality KPIs 5 | time_to_merge | 同上 | 同上 | `time_to_merge` | 同上 |
| C3 | Quality KPIs 5 | approval_wait_ms | 同上 | 同上 | `approval_wait_ms` | 同上 |
| C4 | Quality KPIs 5 | citation_coverage | 同上 | 同上 | `citation_coverage` | 同上 |
| C5 | Quality KPIs 5 | cost_per_completed_task | 同上 | 同上 | `cost_per_completed_task` | 同上 |

**§3.1.1 検証手順** (Phase A-E 完了時に毎回実行、F-ADV-001 + F-ADV-002 fix: required_loaded_files + required_exact_patterns 分解 + L1 file 単位 grep):

trace matrix の各項目は次の 2 要素で構成:

- `required_loaded_files`: 必ず**常時 load される L1 rule file** (path-scoped L2 や reference 移送先は不可、F-ADV-001 fix)
- `required_exact_patterns`: file 単位で AND 条件として全 pattern が hit すること (F-ADV-002 fix で SecretBroker は AND 条件)

```bash
# A1-A8 (8 重要原則) + B1-B7 (Hard Gates 7) = 計 15 必須項目
# 各 item は L1 rule file 単位で grep、AND 条件で全 pattern が hit すること

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

# A1 AI 出力直結禁止
verify_invariant "A1" .claude/rules/ai-output-boundary.md 'AI 出力' 'artifact'
# A2 deny-by-default
verify_invariant "A2" .claude/rules/core.md 'deny-by-default'
verify_invariant "A2-aux" .claude/rules/ai-output-boundary.md 'tool_mutating_gateway_stub'
# A3 Sprint Pack 必須 / ADR Gate 11 種
verify_invariant "A3" .claude/rules/sprint-pack-adr-gate.md 'ADR Gate Criteria' '11 種'
# A4 Provider Compliance v2 (F-ADV-002 fix: AND 条件)
verify_invariant "A4" .claude/rules/provider-compliance.md 'payload_data_class' 'allowed_data_class' '13 reason_code|13 種'
# A5 SecretBroker atomic claim (F-ADV-002 fix: AND 条件で 4 要素 binding 強制)
verify_invariant "A5" .claude/rules/secretbroker-boundary.md 'atomic claim' 'actor' 'run' 'fingerprint' 'capability' 'raw secret'
# A6 AgentRun 16 状態
verify_invariant "A6" .claude/rules/agentrun-state-machine.md '16 状態' 'blocked_reason' 'terminal'
# A7 用語不変条件
verify_invariant "A7" .claude/rules/core.md 'tool_mutating_gateway_stub' 'runner_mutation_gateway' 'public < internal < confidential < pii|public.*internal.*confidential.*pii'
# A8 ContextSnapshot 10 カラム
verify_invariant "A8" .claude/rules/agentrun-state-machine.md 'ContextSnapshot' '10' 'prompt_pack_version' 'provider_request_fingerprint' 'snapshot_kind'

# B1-B7 Hard Gates 7 (Codex F-PR42-003 fix: 検索対象を L1 10 件に明示限定、L2 path-scoped 除外、
# Phase C/D で削除予定の rule は除外、stage gate false green を防ぐ)
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

# 新 session の /context で L1 10 file が常時 load されることを別途確認
# (artifact: .claude/plans/context-management-refactor-l1-loaded-evidence.md に手動記録)

# Quality KPIs 5 (C1-C5、reference でも可、WARN only)
for pattern in 'acceptance_pass_rate' 'time_to_merge' 'approval_wait_ms' \
  'citation_coverage' 'cost_per_completed_task'; do
  count=$(grep -rE "$pattern" .claude/rules/ .claude/reference/ .claude/CLAUDE.md 2>/dev/null | wc -l)
  [ "$count" -eq 0 ] && echo "WARN: KPI $pattern が rules + reference + CLAUDE.md から消失"
done
```

### 3.2 L2 (path-scoped、F-CRA-008 + F-ADV-004 fix: paths 拡張、root config / CI / Docker / scripts / package-lock 含む)

| rule file | paths 候補 | 理由 |
|---|---|---|
| `rendering.md` (2.3k) | `["frontend/**", "docs/基本設計/UI*.md", "docs/sprints/SP-009_*.md", "docs/sprints/SP-010_*.md"]` | frontend / UI docs / Sprint 9-10 関連 session で必要 |
| `testing.md` (3.5k、F-CRA-008 + F-ADV-004 fix) | `["backend/**", "frontend/**", "migrations/**", "eval/**", "**/tests/**", "**/test_*.py", "**/*.spec.ts", "**/*.test.ts", "package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock", "Dockerfile*", "docker-compose*.yml", ".github/**", "scripts/**", "Makefile", "*.config.*"]` | **実装変更 + 設定変更 + CI / Docker / scripts 変更も load 対象** (F-ADV-004: テスト挙動を変える非 source file が path-scoped 外だった漏れを fix) |
| `code-search.md` (2.4k、F-ADV-004 fix) | `["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.go", "**/*.rs", "**/*.sh", "**/*.md", "**/*.json", "**/*.yml", "**/*.yaml", "**/*.toml", "Dockerfile*", "Makefile"]` | code 編集 + 設定 / docs 検索 session で必要、純粋な docs-only かつ検索操作なしの session のみ不要 |

注: `sprint-pack-adr-gate.md` は F-CRA-002 fix で **L1 維持** (path-scoped にすると backend / migration / API / config / .github 変更時に load 漏れリスク)。

### 3.3 L3 (skill 化、F-CRA-005 fix: manual / auto 2 種)

| L3 種別 | frontmatter | invocation | description token | body token |
|---|---|---|---:|---:|
| L3-manual | `disable-model-invocation: true` | 明示 `/skill-name` のみ、Claude auto invoke しない | 0 (context から除外) | 0 (invoke 時のみ) |
| L3-auto | `disable-model-invocation: false` (default) | description match で auto invoke | 常時 50-150 token | 0 (invoke 時のみ) |

| 現 rule | skill 名 | L3 種別 | 理由 |
|---|---|---|---|
| `branch-and-pr-workflow.md` (4.6k) | `branch-pr-workflow` | **L3-auto** | PR 起票 / worktree 操作前に Claude が忘れず invoke するため description 常時 load 必要 |
| `plan-review.md` (2.9k) | (既存 `plan-reviewer` agent body に統合) | (skill ではなく agent) | invocation: Agent tool 経由 |

注: `codex-pr-review-checklist.md` (6.3k) は skill ではなく **L4 reference 化** (`.claude/scripts/codex_pr_full_review.README.md` として helper script 同梱)。

### 3.4 L4 (reference 化、manual Read)

| 現 rule | reference 移動先 | 削除可否 |
|---|---|---|
| `multi-agent-orchestration.md` (4k、Phase F draft) | `.claude/reference/multi-agent-orchestration-draft.md` | P0.1+ 着手時に rule 化、現在は reference |
| `codex-multi-round-workflow.md` (1.8k) | `.claude/reference/codex-workflow-knowledge.md` (codex-output-contract.md と統合) | rule 削除 |
| `codex-output-contract.md` (2.6k) | `.claude/reference/codex-workflow-knowledge.md` (codex-multi-round-workflow.md と統合) | rule 削除 |
| `codex-pr-review-checklist.md` (6.3k) | `.claude/scripts/codex_pr_full_review.README.md` (helper script 同梱) | rule 削除 |

### 3.5 `~/.claude/CLAUDE.md` (user-global) の処理 (Phase E、dotfiles 連動 PR)

**aggressive 案 (本 plan 採用)**:
- TaskManagedAI に無関係な内容を `~/.claude/reference/{neovim, nb, moltbot, drawio, tmux, dotfiles, tailnet, paths}.md` 等に分離
- user-global は「全 project 共通の workflow 原則」(コード検索ルール、曖昧さ解消ルール、JSON 解析ルール、Codex 連携ルール、Worktree 判断ルール、Codex 失敗保護、主要 dotfiles パス) のみに絞り、**150 行 / 5k token** 程度に
- Neovim 詳細・nb 詳細・Tailnet 機械 table は `~/.claude/reference/` から必要時に Read

### 3.6 `.claude/CLAUDE.md` (project) の圧縮

現状 865 行 / 29k → Phase A 後 18k、Phase C 後 16k、Phase E 後 **6-12k / 200-400 行**。

**§6.5 (workflow / 役割分担、約 600 行) の処理**:

| 現 § | 圧縮後 |
|---|---|
| §6.5.0 Codex-first ポリシー | 1 行 + `→ 正本: .claude/rules/codex-usage-policy.md` link、絶対教訓 1 段落のみ残す |
| §6.5.1 役割分担 | table 1 個に圧縮 |
| §6.5.2 Sprint 8 step | `→ 正本: .claude/skills/dev-suite/SKILL.md` に移送 |
| §6.5.3 Host-Portable | `→ 正本: ADR-00021` link、3 行 summary |
| §6.5.4 Codex multi-round | `→ 正本: .claude/rules/codex-usage-policy.md + .claude/reference/codex-workflow-knowledge.md` link |
| §6.5.5 Skill priority | `→ 正本: .claude/rules/codex-usage-policy.md` に統合 |
| §6.5.6 ADR Gate accepted 化 | `→ 正本: .claude/rules/sprint-pack-adr-gate.md` § に移送 |
| §6.5.7 Worktree | `→ 正本: user-global ~/.claude/CLAUDE.md` (Git Worktree 利用判断ルール) + 1 行 (TaskManagedAI 固有事情) |
| §6.5.8 PR/merge 責務分離 | `→ 正本: .claude/rules/branch-and-pr-workflow.md` § に統合、3 行 summary |
| §6.5.9 Codex auto-review 確認義務 | `→ 正本: .claude/scripts/codex_pr_full_review.README.md` (旧 codex-pr-review-checklist.md) に統合、3 行 summary |

**§2 重要原則 (8 重要原則 + Hard Gates 7 + Quality KPIs 5、約 80 行) は維持** (CRITICAL invariant 群、§3.1.1 trace matrix の正本)。

---

## 4. 各 rule の処遇 (確定 table、全 20 件列挙、F-CRA-007 + F-CRA-012 fix)

| # | rule file | 現 token | 層判定 | 移送先 / paths | Phase | stage 1 後 token | stage 2 後 token |
|---:|---|---:|---|---|---|---:|---:|
| 1 | `core.md` | 3.2k | L1 | 維持 | E (圧縮) | 3.2k (stage 1 圧縮なし) | 2.5k |
| 2 | `ai-output-boundary.md` | 2.8k | L1 | 維持 | E (圧縮) | 2.8k | 2.0k |
| 3 | `instincts.md` | 3.2k | L1 | 維持 | E (圧縮) | 3.2k | 2.3k |
| 4 | `secretbroker-boundary.md` | 4.7k | L1 | 維持 | E (圧縮) | 4.7k | 3.0k |
| 5 | `provider-compliance.md` | 3.6k | L1 | 維持 | E (圧縮) | 3.6k | 2.5k |
| 6 | `agentrun-state-machine.md` | 4.6k | L1 | 維持 | E (圧縮) | 4.6k | 2.5k |
| 7 | `cross-source-enum-integrity.md` | 1.7k | L1 | 維持 | - | 1.7k | 1.5k |
| 8 | `server-owned-boundary.md` | 1.3k | L1 | 維持 | - | 1.3k | 1.2k |
| 9 | `sprint-pack-adr-gate.md` | 3.0k | **L1 (F-CRA-002 fix)** | 維持 | E (圧縮) | 3.0k | 2.0k |
| 10 | `codex-usage-policy.md` | 2.6k | **L1 (F-CRA-007 fix)** | 維持 | E (圧縮) | 2.6k | 1.5k |
| 11 | `rendering.md` | 2.3k | L2 | `paths: ["frontend/**", "docs/基本設計/UI*.md", "docs/sprints/SP-009_*.md", "docs/sprints/SP-010_*.md"]` | B | 0 (条件 load) | 0 |
| 12 | `testing.md` | 3.5k | L2 | `paths: ["backend/**", "frontend/**", "migrations/**", "eval/**", "**/tests/**", "**/test_*.py", "**/*.spec.ts", "**/*.test.ts", "package.json", "pnpm-lock.yaml", "pyproject.toml", "uv.lock", "Dockerfile*", "docker-compose*.yml", ".github/**", "scripts/**", "Makefile", "*.config.*"]` (F-CRA-008 + F-ADV-004 fix) | B | 0 (条件 load) | 0 |
| 13 | `code-search.md` | 2.4k | L2 | `paths: ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.go", "**/*.rs", "**/*.sh", "**/*.md", "**/*.json", "**/*.yml", "**/*.yaml", "**/*.toml", "Dockerfile*", "Makefile"]` (F-ADV-004 fix) | B | 0 (条件 load) | 0 |
| 14 | `plan-review.md` | 2.9k | L3 (削除統合) | `plan-reviewer` agent body に統合 | D | 0 (skill) | 0 |
| 15 | `branch-and-pr-workflow.md` | 4.6k | L3-auto | new `.claude/skills/branch-pr-workflow/SKILL.md` (description 50 行 常時 load + body invoke 時) | D | 0 (skill body) | 0.15k (description) |
| 16 | `codex-pr-review-checklist.md` | 6.3k | L4 (削除) | `.claude/scripts/codex_pr_full_review.README.md` (helper script 同梱) | C | 0 | 0 |
| 17 | `codex-multi-round-workflow.md` | 1.8k | L4 (削除) | `.claude/reference/codex-workflow-knowledge.md` (codex-output-contract.md と統合) | C | 0 | 0 |
| 18 | `codex-output-contract.md` | 2.6k | L4 (削除) | `.claude/reference/codex-workflow-knowledge.md` (codex-multi-round-workflow.md と統合) | C | 0 | 0 |
| 19 | `user-preferences.md` | 2.6k | L1 (圧縮統合、最終削除) | 内容を CLAUDE.md §2 / core.md / reference/ に分割移送、rule 削除 | C | 0 | 0 |
| 20 | `multi-agent-orchestration.md` | 4.0k | L4 (削除) | `.claude/reference/multi-agent-orchestration-draft.md` (P0.1+ 着手時 rule 化) | C | 0 | 0 |

**stage 1 完了後の always-loaded files** (§2.0 + §3.1 と完全一致):
- L1 10 件 (#1-#10、現状 token 30.7k) + plan-review.md (#14、2.9k) + branch-and-pr-workflow.md (#15、4.6k) + L2 3 件 (path 条件で 0) = **38.2k**
- Phase D 着手前の rules/ 常時 load = 38.2k、Phase C 後の rules/ 削減量 = 67.0 - 38.2 = -28.8k

**stage 2 完了後の always-loaded files** (§2.0 + §3.1 と完全一致):
- L1 10 件 (#1-#10、圧縮版、計 21.5k) + L3-auto 1 件 description (#15、0.15k) = **21.65k**
- Phase E 後の rules/ 常時 load = 21.65k、stage 2 削減量 = 67.0 - 21.65 = -45.35k

---

## 5. 移行計画 (2 stage / 5 Phase、F-CRA-006 fix: preflight gate 各 Phase 前必須)

各 Phase は **独立 PR**、stage 1 / stage 2 間に **calendar wait 7-14 day の運用試験 gate** を挟む。**全 Phase は Claude 自身が実装** (Codex 委譲なし)。

### 全 Phase 共通: 着手前 preflight gate (F-CRA-006 fix)

各 Phase 着手前に以下を必須通過、失敗時は該当 Phase を延期:

```bash
# (1) Claude Code version 記録
claude --version > .claude/plans/context-management-refactor-claude-version-phase<X>.txt

# (2) scratch rule で paths frontmatter 実測 (Phase B 前必須)
# scratch: .claude/rules/_scratch_paths_test.md に paths: ["backend/test-only-marker/**"] を設定、
# backend/test-only-marker/dummy.py を Read する session を新規起動して /context で load を確認、
# 逆に frontend/page.tsx を編集する session で _scratch_paths_test.md が load されないことを確認
# 不可なら Phase B 延期 (paths 仕様未対応か version 依存)

# (3) L1 常時 load 確認 (Phase A-E 各前)
# 新 session を `cd ~/repo/TaskManagedAI && claude` で起動、/context 出力に L1 10 件 (Phase D 後は L1 圧縮版) が含まれることを確認

# (4) skill 起動実測 (Phase D 前必須)
# scratch: `.claude/skills/_scratch_test/SKILL.md` を作成、`disable-model-invocation: true` で /scratch-test 起動可否を確認
# 失敗なら Phase D 延期 (skill 仕様未対応か version 依存)

# (5) @import 解決 + subagent CLAUDE.md inject 実測 (Phase E 前必須)
# scratch: `.claude/CLAUDE.md` 内に `@.claude/_scratch_import_test.md` を追加、新 session で /context に reflect されるか確認
# subagent (Agent tool で claude-code-guide 起動) 内で「親 session の CLAUDE.md 内容を読んで」と指示して inject 範囲を確認
# 失敗なら Phase E 延期 (公式仕様未対応か version 依存)
```

### Stage 1 (conservative、目標 80k、PR 単独)

#### Phase A: 重複削除 (CLAUDE.md §6.5 ↔ rules/ 統合) [1 day、Claude 自身]

- CLAUDE.md §6.5.0-§6.5.9 と `.claude/rules/{codex-usage-policy, branch-and-pr-workflow, user-preferences, codex-pr-review-checklist}.md` の重複を機械的に diff、**rules/ 側を正本**として CLAUDE.md は summary + `→ 正本: .claude/rules/<name>.md` link のみに圧縮
- 効果: CLAUDE.md 29k → 18k (-11k)
- 手順: (1) 重複箇所を grep で列挙 → (2) 各箇所について「rules/ 側に網羅されているか」を Read で逐次確認 → (3) CLAUDE.md 側を 3-5 行 summary + link に置換 → (4) §3.1.1 trace matrix verification を実行
- 検証: §3.1.1 invariant trace matrix の全 20 項目 grep が pass、CLAUDE.md §2 と §6.5 summary との内容整合
- リスク (R1 緩和策): §6.5 内の「絶対教訓」「品質 vs 速度」「PR 責務分離」等の user 明示語彙を Edit 前後で抜粋 diff 確認、Phase A 完了時に Codex adversarial review (`codex-adversarial-loop` 単独起動) で「invariant 削除漏れ」探索

#### Phase B: rules/ frontmatter `paths` 設定 (L2 化) [0.5 day、Claude 自身]

- 着手前 preflight gate (2)(3) 必須通過
- §3.2 L2 候補 (`rendering`, `testing`, `code-search`) に frontmatter 追加
- **`sprint-pack-adr-gate.md` は L1 維持** (F-CRA-002 fix、paths 設定しない)
- 検証: 各 rule の `head -10` で frontmatter syntax 確認、4 種類 session 起動 (frontend / backend / docs / migration) で `/context` 計測、想定通り load される rule を `.claude/plans/context-management-refactor-stage1-evidence.md` に記録
- リスク (R2 緩和策): paths を **広めに設定** (例: `testing.md` は backend / frontend / migrations / eval / tests を含める)、初回 7-14 day 運用試験で rule load 漏れ commit 観測

#### Phase C: L4 reference 化 (5 件、削除) [0.5 day、Claude 自身]

- `codex-multi-round-workflow.md` + `codex-output-contract.md` → `.claude/reference/codex-workflow-knowledge.md` (統合 file)
- `multi-agent-orchestration.md` → `.claude/reference/multi-agent-orchestration-draft.md`
- `codex-pr-review-checklist.md` → `.claude/scripts/codex_pr_full_review.README.md` (helper script 同梱)
- `user-preferences.md` → CLAUDE.md §2 / core.md / reference/ に**内容統合** (F-CRA-010 fix: 単なる file move ではない、内容整合とリンク修正含む、後述 §7 rollback で 2 PR 分割 or 詳細手順)
- 検証: `grep -r "rules/codex-multi-round\|rules/codex-output\|rules/multi-agent\|rules/codex-pr-review\|rules/user-preferences" .claude/ docs/` で全参照リンクが reference/ / scripts/ / 統合先に書き換わっていることを確認、`.claude/reference/README.md` (index file) を作成

### Stage 1 → Stage 2 移行 gate (calendar wait 7-14 day 運用試験、§2.3 詳細)

stage 1 PR merge 時点で `<stage1_sha>` を記録、`.claude/plans/context-management-refactor-stage1-evidence.md` に gate 4 項目の観測結果を記録。**いずれかに違反 / drift があれば stage 2 を保留**。

### Stage 2 (aggressive、目標 35-50k、stage 1 から 7-14 day 後の追加 PR)

#### Phase D: L3 skill / agent 統合 [1 day、Claude 自身]

- 着手前 preflight gate (1)(3)(4) 必須通過
- `plan-review.md` → `plan-reviewer` agent body に統合、rule 削除
- `branch-and-pr-workflow.md` → new `.claude/skills/branch-pr-workflow/SKILL.md` (**L3-auto**: `disable-model-invocation: false`、description 50 行常時 load + body invoke 時、F-CRA-005 fix)
- 検証: agent / skill 起動 dry-run、frontmatter syntax 確認、`/branch-pr-workflow` 明示起動で body load 確認、PR 起票 session で auto invoke trigger 観測
- リスク (R4 緩和策): skill 化 rule の invocation 忘れ → skill description で「PR / worktree 操作前に必ず invoke」明記、CLAUDE.md §作業ルールから link、PR 起票時の Phase D 完了直後 1 週間は「auto invoke 発火しなかった PR」を `gh pr list` から監査

#### Phase E: L1 圧縮 + `~/.claude/CLAUDE.md` 整理 [1 day、Claude 自身]

- 着手前 preflight gate (1)(3)(5) 必須通過
- L1 10 件を §3.1 stage 2 列に従って圧縮 (合計 25k → 21k、-4k)。**重複削除 / 例示縮減 / 冗長な「禁止」リスト統合のみ**、§3.1.1 trace matrix の必須 grep pattern を残す
- `~/.claude/CLAUDE.md` の Neovim 詳細・nb 詳細・MoltBot 詳細・Discord 詳細・Tailnet 機械 table・主要パス table を `~/.claude/reference/{neovim, nb, moltbot, discord, tailnet, paths}.md` に分離
- user-global CLAUDE.md は「全 project 共通の workflow 原則」(コード検索 / 曖昧さ / JSON / Codex / Worktree の 5 ルール + Codex 連携詳細 + 失敗保護) のみに絞り、150 行 / 5k token 程度に
- **dotfiles 連動の別 PR** (`/Users/tohga/dotfiles/editor/claude-code/claude/CLAUDE.md` + `.../reference/` 群)
- 検証: 新 session で `/context` 計測、Memory files 合計 35-50k 達成確認、§3.1.1 trace matrix 全 20 項目再 verify
- リスク: user-global から削除した内容が他 project session で必要だが load されない → reference/ に明確な index (`~/.claude/reference/README.md`) を置き、`~/.claude/CLAUDE.md` 冒頭から「TaskManagedAI 等で Neovim を使う場合は `~/.claude/reference/neovim.md` を Read」と明記

---

### Phase 2 R1 で adopted、R2 で完全反映予定の 7 件 (F-ADV-005/006/007/008/009/011/012)

本 plan v5 では HIGH 4 件 (F-ADV-001/002/003/004) + 構造完全整合 (F-ADV-010) を反映。以下 7 件は Phase 2 R2 で plan 本文に完全反映予定:

| # | 由来 | severity | symptom | R2 で plan に反映する suggested_fix |
|---:|---|---|---|---|
| 1 | F-ADV-005 | MEDIUM | preflight gate 失敗時の扱いが「延期」のみ、BLOCKED / 再試行 / 責任者 / 代替設計未定義 | `.claude/plans/context-management-refactor-preflight-failures.md` ledger を新規作成、各失敗を [failed Phase / 実測結果 / 原因仮説 / owner / 修正 PR / 再実行条件] で記録、2 回連続失敗で defer/reject 判定に戻す。§5 全 Phase 共通 preflight gate § に追加。 |
| 2 | F-ADV-006 | MEDIUM | Phase 独立 PR で同じ .claude/CLAUDE.md と rules/reference を連続編集、並列 PR で衝突リスク | 各 Phase PR に `required_base_sha` と `depends_on_phase` を持たせ、CI または pre-merge checklist で `git merge-base HEAD main` が直前 Phase merge SHA と一致を確認。`.claude/**` を触る作業は single writer lock を evidence file (`.claude/plans/context-management-refactor-writer-lock.md`) に記録。§5 全 Phase 共通 preflight gate に追加。 |
| 3 | F-ADV-007 | MEDIUM | Phase D archived copy が `.claude/archived/2026-05-17-pre-phase-d/` 固定 path、並列 worktree で上書きリスク | archive path を `.claude/archived/<phase-d-base-sha>-<utc-timestamp>/` に変更、対象 file の sha256 manifest と復元元 commit を同梱、restore 時は manifest 検証後に copy back。§7 Phase D rollback § に追加。 |
| 4 | F-ADV-008 | MEDIUM | subagent CLAUDE.md inject 実測で inherit memory vs disk read 区別不能 | subagent 起動直後、Read 禁止条件で `/context` 相当 loaded memory list か既知 sentinel (例: plan §5.5 末尾の specific marker phrase) 有無を確認。Read 許可検証は分離し transcript に tool 使用有無記録。§5 全 Phase 共通 preflight gate (5) に追加。 |
| 5 | F-ADV-009 | MEDIUM | branch-pr-workflow skill 化後、auto invoke は事後監査のみで PR 前 hard gate なし | `gh pr create` wrapper または PR checklist (`.github/PULL_REQUEST_TEMPLATE.md`) に `branch-pr-workflow evidence marker` 必須化。1 週間 auto invoke 観測 clean まで `branch-and-pr-workflow.md` の最小 L1 reminder (要点 30 行) を残す。§3.3 + §5 Phase D に追加。 |
| 6 | F-ADV-011 | MEDIUM | Phase E で `~/.claude/CLAUDE.md` 分離時に secret / private endpoint / machine path redaction gate なし | Phase E 前に user-global split 用 security checklist を追加: gitleaks/trufflehog 相当 scan、private hostname / IP / path redaction review、git tracked 対象 list の明示承認。機密 reference は dotfiles 管理外 `~/.claude/local/` に置く。§5 Phase E に追加。 |
| 7 | F-ADV-012 | LOW | preflight scratch file の cleanup / git status guard なし、`_scratch` files が context / PR 混入リスク | 各 preflight 手順に cleanup trap (bash `trap`)、rm 対象 list、`git status -sb` が clean であること、scratch 名が `git diff --name-only` に残らないことを確認。失敗時 artifact は専用 `.claude/local/preflight-artifacts/` に限定 (untracked / .gitignore 済)。§5 全 Phase 共通 preflight gate § に追加。 |

これら 7 件は Phase 2 R2 で plan 本文に完全反映、その後 R3 で Readiness Gate 再判定。本 session では HIGH 4 件 + F-ADV-010 を反映し、Phase 2 R1 finished、Phase 2 R2 は **別 session で続行** (context 状況のため)。

---

## 6. リスク (unmitigated true/false 列追加、F-CRA-013 fix)

| # | リスク | severity | unmitigated | 緩和策 |
|---:|---|---|---:|---|
| **R1** | **CRITICAL invariant 喪失**: 圧縮中に AgentRun 16 状態 / SecretBroker atomic claim 等の文言を意図せず削除 | CRITICAL | **true** | §3.1.1 trace matrix の全 20 項目 grep verification を各 Phase 後実行、Phase A 完了時に codex-adversarial-loop 単独起動で「invariant 削除漏れ」探索 |
| **R2** | **path-scoped 漏れによる事故**: `testing.md` を tests/eval だけにすると実装 session で load されない | HIGH | **true** | paths を **広めに設定** (testing.md は backend / frontend / migrations / eval / tests / spec / test を含める、F-CRA-008 fix)、stage 1→2 gate で 4 種 session の load 観測必須 |
| R3 | rule ↔ CLAUDE.md drift: §6.5 を rules/ 側正本にして CLAUDE.md は summary だけにしたが、Sprint 進行で CLAUDE.md だけ update | MEDIUM | false | CLAUDE.md §6.5 summary 部分に **`正本: .claude/rules/<name>.md`** を明示、Codex PR review で drift 検出 |
| R4 | skill 化した rule の invocation 忘れ: `branch-pr-workflow` を skill 化したが PR 起票時に Claude が忘れ | MEDIUM | false | skill description で「PR 操作前に必ず invoke」明記、L3-auto 採用 (description 常時 load で auto invoke trigger 残す、F-CRA-005 fix) |
| R5 | 削減効果が限定的: `@import` は token 削減効果が薄い、`paths` も対応 session でしか効かない | LOW | false | conservative 80k 最低保証、aggressive 35k は L1 圧縮 + user-global 整理 + MEMORY.md archive で達成 |
| **R6** | **新 session で rule が load されない問題**: subdirectory rules の `paths` 仕様が想定と異なり、CRITICAL session で L1 すら load されない | HIGH | **true** | Phase B 前 preflight gate (2)(3) で scratch rule + 新 session 実測必須 (F-CRA-006 fix)、L1 10 件は **絶対に paths を設定しない** (常時 load 維持) |

**unmitigated=true の 3 件 (R1 / R2 / R6)** は frontmatter `risks_unmitigated` に列挙。stage 1 着手前に preflight gate 通過 + Phase A 後 codex-adversarial-loop で再 verify が **mitigation 不十分時の BLOCKER**。

---

## 7. rollback 計画 (F-CRA-010 + F-CRA-011 fix: Phase C / D 具体化)

各 Phase 独立 PR にすることで、Phase 単位で revert 可能。**git revert を第一選択**、手動 rollback は副次手段。

| Phase | rollback 手順 (第一選択) | 手動 rollback (第二選択) |
|---|---|---|
| Phase A | `git revert <PR-A-merge-commit>` で CLAUDE.md §6.5 を復元 | (不要、rules/ 削除はないので消失リスクなし) |
| Phase B | `git revert <PR-B-merge-commit>` で frontmatter `paths` を削除 | 各 rule の frontmatter を手動削除 + `head -5` 確認 |
| Phase C (F-CRA-010 fix) | **`git revert <PR-C-merge-commit>` を第一選択**、ただし内容統合済の場合は **2 段階 PR 分割** で対応: PR-C1 = `git mv` only (file 移動のみ) / PR-C2 = content merge + 参照 link 修正。PR-C1 だけ revert すれば file は rules/ に戻る、PR-C2 は内容修正なので手動 rollback | 復元元 commit から `git show <commit>:.claude/rules/<name>.md > .claude/rules/<name>.md` で file 復元、CLAUDE.md / core.md からの統合差分を手動削除、参照 link を `.claude/scripts/audit-link-update.sh` (新規) で再書き換え |
| Phase D (F-CRA-011 fix) | **`git revert <PR-D-merge-commit>` を第一選択**、Phase D 前に `rules/plan-review.md` と `rules/branch-and-pr-workflow.md` の **archived copy を `.claude/archived/2026-05-17-pre-phase-d/` に保存**、revert 失敗時はこれを `.claude/rules/` に手動 copy back | 復元先: `.claude/rules/`、agent/skill から削る範囲を `.claude/archived/2026-05-17-pre-phase-d/diff.patch` に記録、frontmatter 再検証 (`head -5`) + `/context` 再計測 |
| Phase E | `git revert` (dotfiles 側) で `~/.claude/CLAUDE.md` を復元、user-global は project repo の context には影響しないが、新 session で他 project (例: ieshima-edu) を開いた時の影響を確認 | dotfiles symlink 経由なので `/Users/tohga/dotfiles/editor/claude-code/claude/CLAUDE.md` を git checkout で復元 |

---

## 8. 検証 (F-CRA-003 fix: 数値 ledger 整合、F-CRA-009 fix: invariant trace grep 拡張)

### 8.1 各 Phase 完了時の `/context` 計測 (token 削減目標)

| 指標 | Phase A 後 | Phase B 後 | Phase C 後 (= stage 1 完了) | Phase D 後 | Phase E 後 (= stage 2 完了) |
|---|---:|---:|---:|---:|---:|
| Memory files 合計 (§2.0 と同期) | 104.8k (-11k) | 96.6k (-19k) | **74.0k (-42k、stage 1 目標達成)** | 64.65k (-51k) | **40.65k (-75k、stage 2 目標達成)** |
| `.claude/CLAUDE.md` | 18k | 18k | 16k | 14k | 8k |
| rules/ 常時 load (= §2.0 (A)) | 67.0k | 58.8k | **38.2k** | **30.85k** | **21.65k** |
| `~/.claude/CLAUDE.md` | 15.3k | 15.3k | 15.3k | 15.3k | 8.0k |

### 8.2 §3.1.1 invariant trace matrix verification (F-CRA-009 fix: grep 拡張)

各 Phase 完了時に **必須 grep 15 + 推奨 grep 5 + 拡張 grep 8 = 計 28 grep** を全件 pass で検証:

```bash
# 必須 15 (8 重要原則 + Hard Gates 7、§3.1.1 表 A1-A8 + B1-B7)
# 推奨 5 (Quality KPIs 5、§3.1.1 表 C1-C5)
# 拡張 8 (F-CRA-009 fix: §3.1.1 表で個別 grep に分解されない invariant 関連語彙)
for pattern in \
  'AI 出力直結' 'tool_mutating_gateway_stub' 'ADR Gate Criteria' \
  'payload_data_class > allowed_data_class' 'atomic claim' 'AgentRun.*16 状態' \
  'public < internal < confidential < pii' 'ContextSnapshot.*10' \
  'policy_block_recall' 'secret_canary' 'tenant_isolation_negative_pass' \
  'backup_restore_rpo_rto' 'forbidden_path' 'dangerous_command' 'prompt_injection' \
  'ContextSnapshot.*10' 'reason_code.*13' 'caller-supplied' 'server-owned' \
  'blocked_reason' 'terminal' 'payload_data_class' 'raw secret'; do
  count=$(grep -rE "$pattern" .claude/rules/ .claude/CLAUDE.md 2>/dev/null | wc -l)
  echo "[$count] $pattern"
  [ "$count" -eq 0 ] && { echo "VIOLATION"; exit 1; }
done
```

### 8.3 ファイル存在 / frontmatter / リンク更新確認

- L1 10 件の file 存在: `ls .claude/rules/{core,ai-output-boundary,instincts,secretbroker-boundary,provider-compliance,agentrun-state-machine,cross-source-enum-integrity,server-owned-boundary,sprint-pack-adr-gate,codex-usage-policy}.md` で全件 exists
- L2 3 件 frontmatter: `head -10 .claude/rules/{rendering,testing,code-search}.md` で `paths: [...]` 存在
- L4 移送 file 存在 (Phase C 後): `ls .claude/reference/{codex-workflow-knowledge,multi-agent-orchestration-draft}.md .claude/scripts/codex_pr_full_review.README.md`
- 旧 rule への dead link 不在 (Codex F-PR42-004 fix: 本 plan file 自身への self-match を防ぐため exclude): `grep -rE "rules/codex-multi-round\|rules/codex-output\|rules/multi-agent\|rules/codex-pr-review\|rules/user-preferences" .claude/ docs/ --exclude="context-management-refactor.md" --exclude-dir="archived" 2>/dev/null` で **0 件** (または `find .claude/ docs/ -type f ! -path "*plans/context-management-refactor*.md" ! -path "*/archived/*" -print0 | xargs -0 grep -lE "rules/codex-multi-round|rules/codex-output|rules/multi-agent|rules/codex-pr-review|rules/user-preferences" 2>/dev/null` で **0 件**)

### 8.4 機能 verification (Phase D / E 後)

- skill auto invoke 観測 (Phase D 後): PR 起票 session で `branch-pr-workflow` skill が description match で auto invoke される (1 週間監査)
- @import / subagent CLAUDE.md inject 実測 (Phase E 後): `.claude/CLAUDE.md` に test import を追加して新 session で context 反映確認、Agent tool で subagent 起動して CLAUDE.md 内容を引用できるか確認

---

## 9. 想定外の落とし穴 (preflight gate 必須通過事項、§5 全 Phase 共通から再掲)

- **`paths` frontmatter の version 依存**: Claude Code バージョンによって挙動異なる可能性 → Phase B 前 preflight gate (2) 必須実測、失敗時 Phase B 延期
- **`@import` 構文の相対パス解決基準**: `<repo>/.claude/CLAUDE.md` から `@.claude/rules/foo.md` か `@rules/foo.md` か未確認 → Phase E 前 preflight gate (5) 必須実測、失敗時は `@import` 使わず Phase E 進行 (実質 token 削減効果ゼロなので Phase E 必達条件ではない)
- **subagent への CLAUDE.md inject 範囲**: subagent 用に縮小される or 全文 inject される or 全く inject されない、3 可能性 → Phase E 前 preflight gate (5) 必須実測、subagent context が想定と異なる場合は subagent prompt で明示 inject

---

## 10. 確定事項 (2026-05-17 user 確認結果反映、R1 review F-CRA-NNN findings 全 13 件 adopt 反映)

| # | 項目 | 確定内容 |
|---:|---|---|
| 1 | **削減目標 / 方向性** | **段階適用 (Claude 判断)**。stage 1 = conservative 80k 目標 (Phase C 後達成) → calendar wait 7-14 day 運用試験 → stage 2 = aggressive 35-50k 目標 (Phase E 後達成)。 |
| 2 | **適用範囲** | **project (`.claude/`) + user-global (`~/.claude/`) 両方**。user-global は dotfiles 連動の別 PR、stage 2 Phase E 着手時。 |
| 3 | **codex-all-loops 起動** | **本 plan draft の polish にのみ使用** (codex-all-loops --mode=plan で codex-review-loop + codex-adversarial-loop)。R{N} clean まで polish → PR 起票 → user merge。 |
| 4 | **実装フェーズの executor** | **Phase A-E 全フェーズで Claude 自身が手作業実施**。Codex 委譲なし。 |
| 5 | **dotfiles 連動 PR タイミング** | stage 2 Phase E (calendar wait 後) で別 PR として起票。TaskManagedAI repo PR とは独立。 |
| 6 | **L3 skill 化の塩梅** | `branch-and-pr-workflow` は **L3-auto** (`disable-model-invocation: false`、F-CRA-005 fix)、stage 1 では触らない (Phase D で実施)。`plan-review` は `plan-reviewer` agent body 統合。 |
| 7 | **sprint-pack-adr-gate 層判定** | **L1 確定** (F-CRA-002 fix、backend / migration / API / config 変更で常時 load 必要)。 |
| 8 | **codex-usage-policy 層判定** | **L1 確定** (F-CRA-007 fix、Codex 連携は全 session で運用)。 |
| 9 | **calendar wait 期間** | default 7 day、最大 14 day (`calendar_wait_stage1_to_stage2_days: 7` / `calendar_wait_max_days: 14`)。Sprint 1 batch 1 件分の commit + Codex review 完走 + drift 観測の最低期間 |

---

## 11. 関連参照 (F-CRA-012 fix: 全 20 rules を L1/L2/L3/L4 別列挙)

### 公式 doc (構造的整合のみ判定対象、URL fetch 不可)

- https://code.claude.com/docs/en/memory.md (CLAUDE.md hierarchy / size 推奨 / @import)
- https://code.claude.com/docs/en/skills.md (Skill frontmatter / disable-model-invocation / on-demand load)
- https://code.claude.com/docs/en/how-claude-code-works.md (auto-compaction / subagent context)

### 移行対象 rules 全 20 件 (層別、移送先 / 主要保持先 / 公式仕様依存点)

#### L1 常時 alwaysApply (10 件、stage 1 完了後 / stage 2 では 11 件目に user-preferences 統合分が含まれる扱い → 実質 10 件)
- `core.md` (L1、維持、TaskManagedAI 全体制約、§3.1.1 trace matrix A2/A4/A5/A6/A7/A8 主要保持)
- `ai-output-boundary.md` (L1、維持、§3.1.1 A1/B1/B5/B6/B7 主要保持)
- `instincts.md` (L1、維持、事故予防 17 種、§3.1.1 B3/B4/B5/B6 補助保持)
- `secretbroker-boundary.md` (L1、維持、§3.1.1 A5/B2 主要保持)
- `provider-compliance.md` (L1、維持、§3.1.1 A4/A7 主要保持、reason_code 13 enum 整合性)
- `agentrun-state-machine.md` (L1、維持、§3.1.1 A6/A8 主要保持、16 状態 + blocked サブ 3 enum 整合性)
- `cross-source-enum-integrity.md` (L1、維持、5+ source 整合 + 4 重防御 pattern)
- `server-owned-boundary.md` (L1、維持、caller-supplied 禁止 invariant)
- `sprint-pack-adr-gate.md` (L1、維持、F-CRA-002 fix、§3.1.1 A3 主要保持、ADR Gate 11 種)
- `codex-usage-policy.md` (L1、維持、F-CRA-007 fix、Codex 全 session 運用)

#### L2 path-scoped (3 件、stage 1 Phase B で frontmatter `paths` 設定)
- `rendering.md` (L2、`paths: ["frontend/**", "docs/基本設計/UI*.md", "docs/sprints/SP-009_*.md", "docs/sprints/SP-010_*.md"]`、Next.js 16 / Server Component 規律)
- `testing.md` (L2、F-CRA-008 fix paths 拡張、テスト規律 / 弱い assertion 検出)
- `code-search.md` (L2、code 編集全般、LSP / rg 使い分け)

#### L3 skill 化 (2 件、stage 2 Phase D で実施)
- `plan-review.md` (L3、`plan-reviewer` agent body に統合、rule 削除、計画 review DoD 11 種 + ADR Gate Criteria)
- `branch-and-pr-workflow.md` (L3-auto、F-CRA-005 fix、`branch-pr-workflow` skill、`disable-model-invocation: false`、PR 起票 / worktree 操作前 auto invoke)

#### L4 reference 化 (5 件、stage 1 Phase C で移送)
- `multi-agent-orchestration.md` (L4、`.claude/reference/multi-agent-orchestration-draft.md`、P0.1+ Phase F draft)
- `codex-multi-round-workflow.md` (L4、`.claude/reference/codex-workflow-knowledge.md` に統合、Sprint 1-4 知見)
- `codex-output-contract.md` (L4、`.claude/reference/codex-workflow-knowledge.md` に統合、200 KB 出力上限)
- `codex-pr-review-checklist.md` (L4、`.claude/scripts/codex_pr_full_review.README.md`、helper script 同梱)
- `user-preferences.md` (L4 + L1 統合、内容を CLAUDE.md §2 + core.md + reference/ に分割移送、rule 削除)

### 関連 reference / scripts (新規 / update)

- `.claude/reference/codex-workflow-knowledge.md` (Phase C で codex-multi-round-workflow + codex-output-contract 統合)
- `.claude/reference/multi-agent-orchestration-draft.md` (Phase C で multi-agent-orchestration 移送)
- `.claude/reference/README.md` (Phase C で index file 新規作成、L1/L2/L3/L4 全 20 件への navigation)
- `.claude/scripts/codex_pr_full_review.README.md` (Phase C で codex-pr-review-checklist 内容移送、既存 helper script 同梱)
- `.claude/scripts/audit-invariant-violation.sh` (Phase B 完了時新規、§3.1.1 trace matrix grep verification 自動化)
- `.claude/scripts/audit-link-update.sh` (Phase C 完了時新規、参照リンク書き換え一括処理)
- `.claude/plans/context-management-refactor-stage1-evidence.md` (stage 1 完了時新規、gate 4 項目観測結果)
- `.claude/archived/2026-05-17-pre-phase-d/` (Phase D 前新規、rules/plan-review.md と rules/branch-and-pr-workflow.md の archived copy + diff.patch)

### 関連 repo file

- `.claude/CLAUDE.md` (project、現状 865 行 / 29k token、Phase A 後 18k、Phase C 後 16k、Phase E 後 6-12k)
- `~/.claude/CLAUDE.md` (user-global、現状 612 行 / 15.3k token、Phase E 後 150 行 / 5-10k token、dotfiles 管理)
- `CLAUDE.md` (root、27 行 / 1k token、変更なし)
- `MEMORY.md` (`~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/MEMORY.md`、現状 7k token、Phase E で古い session entry archive 化、5-6k token 目標)
