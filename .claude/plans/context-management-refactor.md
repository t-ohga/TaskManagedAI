---
id: "PLAN-context-management-refactor"
type: "doc-refactor-plan"
status: "draft"
created_at: "2026-05-17"
updated_at: "2026-05-17"
target_artifact: "CLAUDE.md / .claude/rules/ / .claude/reference/ / ~/.claude/CLAUDE.md / MEMORY.md"
target_days_polish: 0.5
target_days_implement_stage_1: 3
target_days_implement_stage_2: 5
max_days_total: 10
estimated_token_savings: "115.8k → stage1: 80k (30%), stage2: 35-50k (55-70%)"
risks_unmitigated: 3
implementation_strategy: "段階適用 (stage 1 = Phase A-C conservative → 1-2 週間運用試験 → stage 2 = Phase D-E aggressive)"
implementation_executor: "Claude 自身 (Codex 委譲なし、CRITICAL invariant を含むため)"
review_executor: "codex-all-loops --mode=plan (plan polish のみ Codex skill 使用)"
scope: "project (.claude/) + user-global (~/.claude/、dotfiles 連動 PR 別)"
related_rules:
  - ".claude/rules/core.md"
  - ".claude/rules/codex-usage-policy.md"
  - ".claude/rules/instincts.md"
---

# Context Management Refactor 計画

## 0. TL;DR

Claude Code session 開始時点で **115.8k token (= context window の 11.6%) が memory files** に消費されている。内訳の大部分は **CLAUDE.md (project) 29k + 20 個の `.claude/rules/*.md` が全件常時 inline で 67k** + `~/.claude/CLAUDE.md` 15.3k + MEMORY.md 7k。Claude Code 公式の (1) **CLAUDE.md ≤ 200 行推奨**、(2) **subdirectory rules の `paths` frontmatter による条件付き load**、(3) **Skill `disable-model-invocation: true` の on-demand load** を組み合わせて **2 stage で段階適用** する。

**stage 1 (Phase A-C, conservative)**: 重複削除 + path-scoped + L4 reference 化のみ、目標 **115.8k → 80k (30% 削減)**。1-2 週間運用試験で不変条件違反 commit が発生しないことを観測。

**stage 2 (Phase D-E, aggressive)**: L3 skill/agent 統合 + L1 圧縮 + user-global 整理、目標 **80k → 35-50k (累計 55-70% 削減)**。

**安全性**: CRITICAL invariant (AgentRun 16 状態 / SecretBroker atomic claim / Provider Compliance 13 reason_code / tenant boundary) は **L1 常時 load 層に集約**して保持。実装フェーズは **Codex 委譲せず Claude 自身が手作業で慎重に** 実施 (大事なものなので drift / 意図せぬ削除を避ける)。plan の polish のみ codex-all-loops --mode=plan で multi-round review にかける。

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
| MCP tools (deferred) | 66.1k | 6.6% | ToolSearch 経由で実体 load、description のみは index 化 |
| Custom agents (description) | 5.6k | 0.6% | 35 agent description |
| **合計使用 (Free space 除く)** | **152.5k** | **15.2%** | |

### 1.2 問題

- **重複**: `.claude/CLAUDE.md §6.5.0-§6.5.9` (約 600 行 / 18k token) と rules/{codex-usage-policy, branch-and-pr-workflow, user-preferences, codex-pr-review-checklist}.md の内容が **70-90% 重複**。Wave 14-18 で個別に確立した workflow を CLAUDE.md に集約しつつ rules/ にも残した結果、二重 inline 状態。
- **conditional load 未活用**: `.claude/rules/*.md` 20 件には frontmatter `paths` が**一切設定されていない**ため、Claude Code の自動 subdirectory rules 機能で全件常時 inline される。`rendering.md` (frontend 専用) も `rendering.md` (postgres 専用) も backend session で常時 load される。
- **user-global の TaskManagedAI 無関係情報**: `~/.claude/CLAUDE.md` 612 行のうち 70-80% は Neovim プラグイン詳細・nb 使い方・MoltBot・Discord・Draw.io 等。これらは TaskManagedAI session 中はほぼ参照されない。
- **draft / 非 active rule の常時 load**: `multi-agent-orchestration.md` は P0.1+ 向けで「Phase F で正式化される draft」明記、現在は不要。

### 1.3 公式仕様 (Claude Code、claude-code-guide subagent 経由で確認)

出典: https://code.claude.com/docs/en/memory.md / https://code.claude.com/docs/en/skills.md

| 公式仕様 | 内容 |
|---|---|
| CLAUDE.md 階層 | user-global (`~/.claude/`) → project root (`<repo>/CLAUDE.md`) → project (`<repo>/.claude/CLAUDE.md`) → local (`.claude.local.md`) の全て常時 load |
| 推奨 size | `CLAUDE.md ≤ 200 行`、`MEMORY.md ≤ 200 行 or 25KB` |
| **subdirectory rules** | `.claude/rules/*.md` は `paths: [...]` frontmatter で **path-scoped conditional load**。frontmatter なしは全件常時 load される |
| **@import 構文** | `@relative/path.md` で他 file 参照、**import 内容も常時 load** (token 削減効果は薄い、整理目的) |
| **Skill (on-demand)** | description は常時 load、body は `/skill-name` invoke 時のみ。`disable-model-invocation: true` で description も context から除外 |
| Subagent | 完全独立 context、親 session の conversation 非継承、但し CLAUDE.md は subagent にも load される |
| auto-compaction | 旧 tool output 削除 → 必要時 conversation summarize、CLAUDE.md は compaction 後も disk から re-read & re-inject |

**重要な結論**: token 削減の主要ハンドルは (a) **CLAUDE.md 本文の圧縮**、(b) **`paths` frontmatter で rules/ を path-scoped 化**、(c) **rule の skill 化 (`disable-model-invocation: true`)** の 3 つ。`@import` は整理にはなるが token 削減効果は薄い。

---

## 2. 目標 (段階適用)

### 2.1 stage 1 (conservative、Phase A-C、本 plan の初回 PR scope)

| 指標 | 現状 | stage 1 完了後 | 削減量 |
|---|---:|---:|---:|
| Memory files 合計 | 115.8k | **80k** | -35k (30%) |
| `<repo>/.claude/CLAUDE.md` | 29k / 865 行 | 18k / 500 行 | -11k (CLAUDE.md §6.5 重複削除) |
| `.claude/rules/*.md` 常時 load | 67k / 20 件 | 35k / 9 件 (path-scoped 3 件 + L4 移送 5 件 + 既存 L1 8 件 + 削除 0 件) | -32k |
| `~/.claude/CLAUDE.md` | 15.3k / 612 行 | 15.3k (未変更) | 0 |
| MEMORY.md | 7k | 7k (未変更) | 0 |

### 2.2 stage 2 (aggressive、Phase D-E、運用試験 1-2 週間後の追加 PR scope)

| 指標 | stage 1 完了後 | stage 2 完了後 | 累計削減量 |
|---|---:|---:|---:|
| Memory files 合計 | 80k | **35-50k** | -65 〜 -80k (55-70%) |
| `<repo>/.claude/CLAUDE.md` | 18k | 6-12k / 200-400 行 | -17 〜 -23k |
| `.claude/rules/*.md` 常時 load | 35k | 15-20k / 4-5 件 (skill 化 / L1 圧縮) | -47 〜 -52k |
| `~/.claude/CLAUDE.md` | 15.3k | 5-10k / 150-350 行 | -5 〜 -10k |
| MEMORY.md | 7k | 5-6k (古い session entry archive) | -1 〜 -2k |

### 2.3 安全性 (両 stage 共通)

- **CRITICAL invariant 保護**: Hard Gates 7 / 不変条件 18 (AgentRun 16 状態・ContextSnapshot 10 列・SecretBroker atomic claim・Provider Compliance 13 reason_code 等) は **L1 常時 load 層** に集約して保持。
- **stage 1 → stage 2 移行 gate**: stage 1 完了後 1-2 週間の運用試験で「path-scoped 化した rule が想定通り load される」「不変条件違反 commit が発生しない」「rule ↔ CLAUDE.md drift が起きていない」を確認。違反 / drift があれば stage 2 着手を保留し、まず path 設定や移送先を調整。
- **rollback 可能性**: 各 Phase 独立 PR、stage 1 / stage 2 も独立 PR。問題発生時は単独 revert で復旧可。

---

## 3. 設計方針: 4 層分類

各 rule / doc を以下 4 層に分類し、層ごとに扱いを変える。

| 層 | 定義 | 例 | token 効果 |
|---|---|---|---|
| **L1 常時 alwaysApply** | 全 session で必須。忘れたら CRITICAL 事故 (Hard Gate 違反、不変条件破壊) | `core.md` / `ai-output-boundary.md` / `instincts.md` / `secretbroker-boundary.md` / `provider-compliance.md` / `agentrun-state-machine.md` | 維持 (圧縮のみ) |
| **L2 path-scoped (frontmatter `paths`)** | 特定領域編集時のみ必要。無関係 session で load 不要 | `rendering.md` (`frontend/**`) / `postgres-boundary-audit` 相当 (`migrations/**` `backend/app/db/**`) / `runner-*` (`backend/app/services/runner/**`) | 該当 session のみ load |
| **L3 skill 化 (on-demand)** | 特定 task 開始時のみ必要、`/skill-name` で invoke | `codex-pr-review-checklist` (PR review 時) / `branch-and-pr-workflow` (worktree 操作時) / `plan-review` (計画レビュー時) | invocation 時のみ body load、description は残る |
| **L4 reference 化 (manual Read)** | 滅多に参照しない、draft / 完了済み / 詳細手順 | `multi-agent-orchestration.md` (P0.1+ draft) / `codex-multi-round-workflow.md` 等の詳細手順 | Read 時のみ |

### 3.1 L1 (常時 load) 候補 (合計 token 目標: 15k 以内)

| rule file | 現状 token | 圧縮後 | L1 採用理由 |
|---|---:|---:|---|
| `core.md` | 3.2k | 3.0k | TaskManagedAI 全体の基本制約 (型安全 / AI 出力境界 / deny-by-default / 8 不変条件群) |
| `ai-output-boundary.md` | 2.8k | 2.5k | Hard Gate AC-HARD-01 / -05 / -06 / -07 直結、忘れたら command 直結等 CRITICAL 事故 |
| `instincts.md` | 3.2k | 2.8k | 17 種の事故予防、CRITICAL invariant の暗黙 sanity check |
| `secretbroker-boundary.md` | 4.7k | 3.5k | Hard Gate AC-HARD-02 直結、raw secret 非保存 invariant |
| `provider-compliance.md` | 3.6k | 3.0k | Provider 越境 deny、13 reason_code 不変条件 |
| `agentrun-state-machine.md` | 4.6k | 3.0k | AgentRun 16 状態・blocked サブ 3・terminal 5 種不変条件 |
| `cross-source-enum-integrity.md` | 1.7k | 1.5k | 5+ source 整合 + 4 重防御 pattern |
| `server-owned-boundary.md` | 1.3k | 1.2k | caller-supplied 経路禁止 invariant |
| **L1 合計** | **25.1k** | **~20.5k** | (現状から 4.6k 圧縮) |

(注: 上記合計はあくまで rules/ 内のみ。CLAUDE.md (project) の圧縮は別途。)

### 3.2 L2 (path-scoped) 候補

`---` frontmatter で `paths: [...]` を設定。

| rule file | paths 候補 | 効果 |
|---|---|---|
| `rendering.md` | `["frontend/**", "docs/基本設計/UI*.md", "docs/sprints/SP-009_*.md"]` | backend / docs 専用 session で load 不要 |
| `testing.md` | `["**/tests/**", "**/test_*.py", "**/*.spec.ts", "**/*.test.ts", "eval/**"]` | 実装変更時のみ |
| `code-search.md` | `["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx", "**/*.go", "**/*.rs"]` | code 編集時のみ (docs-only session で不要) |

### 3.3 L3 (skill 化) 候補

`.claude/skills/<name>/SKILL.md` に移動、`disable-model-invocation: false` で auto-invoke 可能か、明示 `/skill-name` のみか選択。

| 現 rule | skill 名 | invoke trigger | 既存 skill との関係 |
|---|---|---|---|
| `codex-pr-review-checklist.md` (6.3k) | (既存 `.claude/scripts/codex_pr_full_review.sh` の補助 doc) → **reference 化** | helper script 起動時 user が `Read` | rule から外して L4 |
| `branch-and-pr-workflow.md` (4.6k) | new `skill/branch-pr-workflow` or **L4 reference** | worktree / PR 起票時 | 新 skill 化推奨 |
| `plan-review.md` (2.9k) | 既存 `plan-reviewer` agent が body | agent invoke 時 | agent body と統合、rule から削除 |
| `codex-pr-review-checklist.md` | **L4 reference** | PR review skill 内から参照 | helper script 内 doc link |

### 3.4 L4 (reference 化) 候補

`.claude/reference/` に移動 (既存 11 file あり、`.claude/CLAUDE.md` 文中で「必要時参照」明記済み)。

| 現 rule | reference 移動先 | 削除可否 |
|---|---|---|
| `multi-agent-orchestration.md` (4k、Phase F draft) | `.claude/reference/multi-agent-orchestration-draft.md` | P0.1+ 着手時に rule 化、現在は reference |
| `codex-multi-round-workflow.md` (1.8k、Sprint 1-4 知見) | `.claude/reference/codex-workflow-knowledge.md` | 内容を統合 |
| `codex-output-contract.md` (2.6k、200 KB 上限規約) | `.claude/reference/codex-output-contract.md` | Codex skill 起動時のみ参照 |
| `sprint-pack-adr-gate.md` (3.0k、ADR Gate 11 種) | (`core.md` § ADR Gate と統合 or 残す) | 統合検討 |

### 3.5 `~/.claude/CLAUDE.md` (user-global) の処理

**aggressive 案**:
- TaskManagedAI に無関係な内容を `~/.claude/reference/{neovim, nb, moltbot, drawio, tmux, dotfiles}.md` 等に分離
- user-global は「全 project 共通の workflow 原則」(コード検索ルール、曖昧さ解消ルール、JSON 解析ルール、Codex 連携ルール、Worktree 判断ルール、主要パス) のみに絞り、150 行 / 5k token 程度に
- Neovim 詳細・nb 詳細は `~/.claude/reference/`、user-global CLAUDE.md からは 1 行 summary + reference link

**conservative 案**:
- 既存 5 ルール (コード検索 / 曖昧さ / JSON / Codex / Worktree) と Codex 連携詳細を残し、技術スタック詳細・サンプルリポジトリ一覧・Neovim 詳細・nb 詳細・MoltBot 詳細・Discord 詳細を Reference 化
- 350 行 / 10k token 程度に

### 3.6 `.claude/CLAUDE.md` (project) の圧縮

現状 865 行 / 29k → 目標 400 行 / 12k (conservative) or 200 行 / 6k (aggressive)。

**§6.5 (workflow / 役割分担、約 600 行) の処理**:

| 現 § | 圧縮後 |
|---|---|
| §6.5.0 Codex-first ポリシー | 1 行 + `→ .claude/rules/codex-usage-policy.md` link、絶対教訓 1 段落のみ残す |
| §6.5.1 役割分担 | table 1 個に圧縮 |
| §6.5.2 Sprint 8 step | `→ .claude/skills/dev-suite/SKILL.md` に移送 |
| §6.5.3 Host-Portable | `→ ADR-00021` link、3 行 summary |
| §6.5.4 Codex multi-round | `→ rules/codex-usage-policy.md` + `rules/codex-multi-round-workflow.md` (or reference) link |
| §6.5.5 Skill priority | `→ rules/codex-usage-policy.md` に統合 |
| §6.5.6 ADR Gate accepted 化 | `→ rules/sprint-pack-adr-gate.md` § に移送 |
| §6.5.7 Worktree | `→ user-global CLAUDE.md` (Git Worktree 利用判断ルール) + 1 行 (TaskManagedAI 固有事情) |
| §6.5.8 PR/merge 責務分離 | `→ rules/branch-and-pr-workflow.md` § に統合、3 行 summary |
| §6.5.9 Codex auto-review 確認義務 | `→ rules/codex-pr-review-checklist.md` (or reference) に統合、3 行 summary |

**§2 重要原則 (Hard Gates 7 / Quality KPIs 5 / 不変条件 8 種、約 80 行) は維持** (CRITICAL invariant)。

---

## 4. 各 rule の処遇 (確定 table、Phase 0 で確定後 fix)

| # | rule file | 現 token | 層判定 | 移送先 | 圧縮目標 |
|---:|---|---:|---|---|---:|
| 1 | `core.md` | 3.2k | L1 | 維持 | 3.0k |
| 2 | `ai-output-boundary.md` | 2.8k | L1 | 維持 | 2.5k |
| 3 | `instincts.md` | 3.2k | L1 | 維持 | 2.8k |
| 4 | `secretbroker-boundary.md` | 4.7k | L1 | 維持 | 3.5k |
| 5 | `provider-compliance.md` | 3.6k | L1 | 維持 | 3.0k |
| 6 | `agentrun-state-machine.md` | 4.6k | L1 | 維持 | 3.0k |
| 7 | `cross-source-enum-integrity.md` | 1.7k | L1 | 維持 | 1.5k |
| 8 | `server-owned-boundary.md` | 1.3k | L1 | 維持 | 1.2k |
| 9 | `rendering.md` | 2.3k | L2 | `paths: ["frontend/**", ...]` | 2.3k (path-scoped) |
| 10 | `testing.md` | 3.5k | L2 | `paths: ["**/tests/**", ...]` | 3.0k (path-scoped) |
| 11 | `code-search.md` | 2.4k | L2 | `paths: ["**/*.py", "**/*.ts", ...]` | 2.0k (path-scoped) |
| 12 | `sprint-pack-adr-gate.md` | 3.0k | L1 or L2 | `paths: ["docs/sprints/**", "docs/adr/**", ".claude/plans/**"]` | 2.5k |
| 13 | `plan-review.md` | 2.9k | L3 | `plan-reviewer` agent body に統合 | 削除 |
| 14 | `branch-and-pr-workflow.md` | 4.6k | L3 or L4 | new `branch-pr-workflow` skill or reference | 削除 |
| 15 | `codex-pr-review-checklist.md` | 6.3k | L4 | `.claude/scripts/codex_pr_full_review.sh` 同梱 reference | 削除 (helper の README に) |
| 16 | `codex-usage-policy.md` | 2.6k | L1 (圧縮) | 維持 (Codex は常時必要) | 2.0k |
| 17 | `codex-multi-round-workflow.md` | 1.8k | L4 | `.claude/reference/codex-workflow-knowledge.md` | 削除 |
| 18 | `codex-output-contract.md` | 2.6k | L4 | `.claude/reference/codex-output-contract.md` | 削除 |
| 19 | `user-preferences.md` | 2.6k | L1 (圧縮、§6.5.0 と統合) | core.md または `.claude/CLAUDE.md §2` に統合 | 削除 |
| 20 | `multi-agent-orchestration.md` | 4.0k | L4 | `.claude/reference/multi-agent-orchestration-draft.md` (P0.1+ 着手時 rule 化) | 削除 |

**結果**: 常時 load 8 件 (L1) + path-scoped 4 件 (L2) + L3/L4 移送 8 件 = 12 件分の `~67k → ~22k` 削減 (約 45k 削減、67% 削減)。

---

## 5. 移行計画 (2 stage / 5 Phase)

各 Phase は **独立 PR**、stage 1 / stage 2 も間に **1-2 週間の運用試験 gate** を挟む。**全 Phase は Claude 自身が実装** (Codex 委譲なし、CRITICAL invariant を含むため意図せぬ drift / 削除を防ぐ)。Codex は **本 plan の polish 段階のみ** codex-all-loops --mode=plan で使用。

### Stage 1 (conservative、目標 80k token、本 plan 初回 PR scope)

#### Phase A: 重複削除 (CLAUDE.md §6.5 ↔ rules/ 統合) [1 day、Claude 自身]

- CLAUDE.md §6.5.0-§6.5.9 と `.claude/rules/{codex-usage-policy, branch-and-pr-workflow, user-preferences, codex-pr-review-checklist}.md` の重複を機械的に diff し、**rules/ 側を正本**として CLAUDE.md は summary + link のみに圧縮。
- 効果: CLAUDE.md 29k → 18-20k (約 10k 削減)。
- 手順: (1) 重複箇所を grep で列挙 → (2) 各箇所について「rules/ 側に網羅されているか」を Read で逐次確認 → (3) CLAUDE.md 側を 3-5 行 summary + `→ 正本: .claude/rules/<name>.md` link に置換。
- 検証: `grep -nE "AgentRun.*16|payload_data_class|allowed_data_class|atomic claim|tenant_id|Hard Gate"` で不変条件記述が rules/ 側に残存することを確認、CLAUDE.md でも 1 行 summary が残ることを確認。
- リスク: §6.5 内の「絶対教訓」「品質 vs 速度」等の user 明示語彙を意図せず削除する → Edit 前後で当該行を Read で抜粋して diff 確認、L1 user-preferences 統合先で再確認。

#### Phase B: rules/ frontmatter `paths` 設定 (L2 化) [0.5 day、Claude 自身]

- §3.2 の L2 候補 (`rendering`, `testing`, `code-search`, `sprint-pack-adr-gate`) に frontmatter 追加。
- paths は **広めに設定** (例: `rendering.md` は `frontend/**` + `docs/基本設計/UI*.md` + `docs/sprints/SP-009_*.md` + `docs/sprints/SP-010_*.md` を含める) して漏れを防ぐ。
- 検証: 各 rule の `head -10` で frontmatter syntax 確認、新 session を `frontend/page.tsx` 編集 context で開始して `/context` 計測 → `rendering.md` が context に含まれるか確認、逆に `backend/app/main.py` 編集 context では含まれないことを確認。
- リスク: paths 仕様が想定と異なり L1 系まで条件 load 化されて事故 → L1 (core / instincts / secretbroker / provider-compliance / agentrun-state-machine / cross-source-enum / server-owned / ai-output-boundary) には **絶対に paths を設定しない**、L2 のみに限定。

#### Phase C: L4 reference 化 (5 件、削除) [0.5 day、Claude 自身]

- `codex-multi-round-workflow.md`, `codex-output-contract.md`, `multi-agent-orchestration.md` → `.claude/reference/` に `git mv`
- `codex-pr-review-checklist.md` → `.claude/scripts/codex_pr_full_review.README.md` に内容移送、rule 削除
- `user-preferences.md` → CLAUDE.md §2 / core.md に統合後削除 (絶対教訓・品質 vs 速度・PR/merge 責務分離は CLAUDE.md §2 に統合、過去の事故/教訓 table は `.claude/reference/` に保存)
- 検証: `grep -r "rules/codex-multi-round\|rules/codex-output\|rules/multi-agent\|rules/codex-pr-review\|rules/user-preferences" .claude/ docs/` で全参照リンクが reference/ や scripts/ に書き換わっていることを確認。
- リスク: reference/ に移送した後 Claude が忘れて参照しない → CLAUDE.md / 関連 rules から `→ .claude/reference/<name>.md` link を必ず張る、reference index (例: `.claude/reference/README.md`) を作成。

### Stage 1 → Stage 2 移行 gate (1-2 週間運用試験)

stage 1 完了後、stage 2 着手前に以下を観測:

- [ ] path-scoped 化した rule が想定通り load されている (新 session で `/context` 計測 + frontend / backend / docs / migration の各 session で確認)
- [ ] 不変条件違反 commit が発生していない (`grep -r "AgentRun.*16\|atomic claim\|tenant_id"` で 1-2 週間の commit 履歴を確認、違反 commit 0 件)
- [ ] rule ↔ CLAUDE.md drift が起きていない (CLAUDE.md §2 と rules/ L1 8 件の内容整合確認)
- [ ] Codex PR review で「rule 違反検出漏れ」がない (1-2 週間の Codex auto-review finding 内容を確認)

**いずれかに違反 / drift があれば stage 2 を保留** し、まず path 設定や reference 移送先を調整する PR を起票。

### Stage 2 (aggressive、目標 35-50k token、stage 1 から 1-2 週間後の追加 PR scope)

#### Phase D: L3 skill / agent 統合 [1 day、Claude 自身]

- `plan-review.md` → `plan-reviewer` agent body に統合、rule 削除
- `branch-and-pr-workflow.md` → new `.claude/skills/branch-pr-workflow/SKILL.md` (description 50 行 + body 残り全部)、rule 削除
- 検証: agent / skill 起動 dry-run、frontmatter syntax 確認、description match 確認 (例: PR 起票時に skill auto-invoke trigger が機能するか観測)。
- リスク: skill 化した rule の invocation 忘れ → skill description で「PR / worktree 操作前に必ず invoke」明記、CLAUDE.md §作業ルールから link、PR 起票時の checklist に組み込む。

#### Phase E: L1 圧縮 + `~/.claude/CLAUDE.md` 整理 [1 day、Claude 自身]

- L1 8 件を §3.1 に従って圧縮 (合計 25.1k → 20.5k、~4.6k 削減)。重複削除 / 例示縮減 / 冗長な「禁止」リスト統合のみ、CRITICAL 不変条件は触らない。
- `~/.claude/CLAUDE.md` の Neovim 詳細・nb 詳細・MoltBot 詳細・Discord 詳細・Tailnet 機械 table・主要パス table を `~/.claude/reference/{neovim, nb, moltbot, discord, tailnet, paths}.md` に分離
- user-global CLAUDE.md は「全 project 共通の workflow 原則」(コード検索 / 曖昧さ / JSON / Codex / Worktree の 5 ルール + Codex 連携詳細 + 失敗保護) のみに絞り、150 行 / 5k token 程度に。
- **dotfiles 連動の別 PR** (`/Users/tohga/dotfiles/editor/claude-code/claude/CLAUDE.md` + `.../reference/` 群): TaskManagedAI repo PR とは別。
- 検証: 新 session で `/context` 計測、Memory files 合計 35-50k 達成確認。`~/.claude/CLAUDE.md` から削除した内容を必要時に Read できるか reference path を確認。
- リスク: user-global から削除した内容が他 project session で必要だが load されない → reference/ に明確な index を置き、`~/.claude/CLAUDE.md` 冒頭から「TaskManagedAI 等で Neovim を使う場合は `~/.claude/reference/neovim.md` を Read」と明記。

---

## 6. リスク・軽減策

| # | リスク | severity | 軽減策 |
|---:|---|---|---|
| R1 | **CRITICAL invariant 喪失**: 圧縮過程で AgentRun 16 状態 / SecretBroker atomic claim 等の文言を意図せず削除 | CRITICAL | L1 8 件は **diff レビュー必須**、機械的削減ではなく Codex multi-round review (codex-all-loops mode=plan) で finding clean まで polish |
| R2 | **path-scoped 漏れによる事故**: `rendering.md` を `frontend/**` 限定にしたが、`docs/` 内の frontend 仕様記述で参照されず違反 commit | HIGH | paths 設定は **広めに** (例: `docs/基本設計/UI*.md` も含める)、初回 1 week は monitoring (Sprint 9 着手時に rule 違反 commit 発生有無確認) |
| R3 | **rule ↔ CLAUDE.md drift**: §6.5 を rules/ 側正本に移して CLAUDE.md は summary だけにしたが、Sprint 進行で CLAUDE.md だけ update されて rule に反映されない | MEDIUM | CLAUDE.md §6.5 summary 部分に **`正本: .claude/rules/<name>.md`** を明示、Codex PR review で drift 検出 |
| R4 | **skill 化した rule の起動忘れ**: `branch-and-pr-workflow` を skill 化したが PR 起票時に Claude が invoke 忘れ | MEDIUM | skill description で「PR / worktree 操作前に必ず invoke」明記、CLAUDE.md §作業ルールから link |
| R5 | **削減効果が限定的**: 公式 docs によれば `@import` は token 削減効果が薄い、`paths` も対応 session でしか効かない | LOW | conservative 目標 80k (30% 削減) を最低保証、aggressive 35k (70%) は追加削減策で達成 |
| R6 | **新 session で rule が load されない問題**: subdirectory rules の `paths` 仕様が想定と異なり、CRITICAL session で L1 すら load されない | HIGH | Phase B で **テスト session** を起こして `/context` 計測、L1 が常時 load される確認 |

---

## 7. rollback 計画

各 Phase 独立 PR にすることで、Phase 単位で revert 可能。

| Phase | rollback 手順 |
|---|---|
| Phase A | `git revert <PR-A-commit>` で CLAUDE.md §6.5 を復元 (rules/ 側削除はしないので消失リスクなし) |
| Phase B | frontmatter `paths` を削除する PR を起票 (`git revert` or 手動) |
| Phase C | `.claude/reference/` から `.claude/rules/` に file 移動し直す PR |
| Phase D | skill / agent から rule 内容を切り戻し |
| Phase E | dotfiles 側 `~/.claude/CLAUDE.md` を revert |

---

## 8. 検証

各 Phase 完了時に `/context` で memory files token 計測、Phase D 完了時の目標値達成を確認。

| 指標 | Phase A 後 | Phase B 後 | Phase C 後 | Phase D 後 | Phase E 後 |
|---|---:|---:|---:|---:|---:|
| Memory files 合計 | 105k (-10k) | 100k (-15k) | 92k (-23k) | 80k (-35k) | **50k (-65k)** |
| `.claude/CLAUDE.md` | 18k | 18k | 16k | 14k | 12k |
| rules/ 常時 load | 67k | 55k | 35k | 25k | 20k |
| `~/.claude/CLAUDE.md` | 15.3k | 15.3k | 15.3k | 15.3k | **5-10k** |

**Hard Gates / 不変条件 trace 検証**:

- Phase A-E 各完了時に `grep -nE "AgentRun.*16|payload_data_class|allowed_data_class|atomic claim|tenant_id"` で不変条件記述が L1 に残っていることを確認
- Codex adversarial review (codex-adversarial-loop) で「不変条件 trace 漏れ」探索

---

## 9. 想定外の落とし穴

- `.claude/rules/*.md` の **自動 subdirectory inline 機能**は Claude Code バージョン依存の可能性。`paths` frontmatter 仕様も version 依存の可能性 → Phase B 着手前に `claude --version` 記録 + 公式 changelog 確認推奨
- `@import` 構文を `<repo>/.claude/CLAUDE.md` から使う場合の相対パス解決基準が `.claude/` か `<repo>/` か未確認 → Phase A-D で使わず Phase E で確認後に判断
- subagent (例: `plan-reviewer`) に渡される CLAUDE.md は subagent 用に縮小されるかどうか公式 doc 未確認 → 観測ベース、subagent 報告の token usage で確認

---

## 10. 確定事項 (2026-05-17 user 確認結果反映)

| # | 項目 | 確定内容 |
|---:|---|---|
| 1 | **削減目標 / 方向性** | **段階適用 (Claude 判断)**。stage 1 = conservative 80k 目標 → 1-2 週間運用試験 → stage 2 = aggressive 35-50k 目標。「大事なものだから」の user 方針に従い慎重に進める。 |
| 2 | **適用範囲** | **project (`.claude/`) + user-global (`~/.claude/`) 両方**。user-global は dotfiles 連動の別 PR、本 PR (TaskManagedAI repo) とは別タイミング (stage 2 Phase E 着手時)。 |
| 3 | **codex-all-loops 起動** | **本 plan draft の polish にのみ使用** (codex-all-loops --mode=plan で codex-review-loop + codex-adversarial-loop)。R{N} clean まで polish → PR 起票 → user merge。 |
| 4 | **実装フェーズの executor** | **Phase A-E 全フェーズで Claude 自身が手作業実施**。Codex 委譲なし。理由: CLAUDE.md / rules / user-global は CRITICAL invariant (Hard Gates 7 / 不変条件 18) を含むため、Codex 委譲による意図せぬ削除 / drift / 文言改変リスクを完全排除。 |
| 5 | **dotfiles 連動 PR タイミング** | stage 2 Phase E (1-2 週間後) で `/Users/tohga/dotfiles/editor/claude-code/claude/` への変更を別 PR として起票。TaskManagedAI repo PR とは独立。 |
| 6 | **L3 skill 化の塩梅** | stage 2 Phase D で判断。`branch-and-pr-workflow` は新 skill 化、`plan-review` は `plan-reviewer` agent body 統合。stage 1 段階では触らない (運用試験で問題なければ stage 2 で実施)。 |

---

## 11. 関連参照

- 公式 doc: https://code.claude.com/docs/en/memory.md
- 公式 doc: https://code.claude.com/docs/en/skills.md
- 公式 doc: https://code.claude.com/docs/en/how-claude-code-works.md
- 本 repo: `.claude/CLAUDE.md` (project)、`~/.claude/CLAUDE.md` (user-global)、`.claude/rules/*.md` (20 件)、`.claude/reference/*.md` (11 件)
- 関連 rules (本 plan で扱う対象): `core.md` / `instincts.md` / `codex-usage-policy.md` / `branch-and-pr-workflow.md` / `user-preferences.md` / `multi-agent-orchestration.md` / 計 20 件
