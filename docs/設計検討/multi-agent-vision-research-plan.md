# TaskManagedAI Multi-Agent Vision Research Plan

> 作成日: 2026-05-10
> ステータス: 実装前 research フェーズ (6 Phase 計画)
> 関連 commit: `86e1035` (ADR-00013 Remote Agent Extension Point)
> 関連 memory: `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/project_taskmanagedai_vision_consolidation_plan.md`

## 背景

2026-05-10 にユーザーから直接確認された TaskManagedAI の真の vision を、実装前に **抜け漏れなく Codex で完全 research** してから PRD / ADR / Sprint Pack に反映するための計画書。

## 1. 確認済 vision (5 core 要件)

### 1.1 AI Society = 「会社」メタファー

TaskManagedAI = AI agent 集合体 = 一つの会社:

- **司令塔 (orchestrator / dispatcher)**: タスク分解 / 割り振り / 統合
- **専門エージェント群**: implementer / reviewer / tester / security_agent / researcher / observer / curator / ...
- **完全自律で運営される**

### 1.2 Multi-agent orchestration + 完全自律

| 観点 | 既存 (P0 Sprint 1-12) | 新 vision (P0.1+) |
|---|---|---|
| AgentRun 数 | 1 ticket = 1 AgentRun | **1 ticket = N AgentRun 並列** + 司令塔 |
| 起動 trigger | human approval | **司令塔自律判断** |
| エージェント間連携 | なし | **inter-agent communication** (レビューしあう / 話し合う) |
| 進捗管理 | 人間手動 | **司令塔自律 track** |

### 1.3 UI ↔ CLI parity

```
TaskManagedAI UI でできること = CLI でできること (完全対称)

UI 経由: Web UI でチケット board → AI society 視覚化 → 司令塔割り振り → 進捗
CLI 経由: 複数 terminal で AI agent 起動 → 司令塔 CLI で統合 → 同じ DB → UI でも見える
```

### 1.4 メモリー記録 (UI/CLI 両方)

- 自動: 司令塔がタスク完了時、知見を memory に蓄積
- 手動: ユーザー UI から「これを記録」操作
- backend: user-scope ハーネス v5 (hermes 級 memory: SessionDB FTS5 + curator + insights)

### 1.5 グラフィック / キャラクター (P2)

- 各 AI agent をキャラクター化 (Codex 画像生成 or default icon)
- 「会社」のメタファーを UI で視覚化
- エージェント間チャット / レビュー場所

## 2. 取り込み戦略 (前回 AskUserQuestion 確認済)

### user-scope ハーネス v5 = hermes 級 (絶対)

- Memory full layer (memory_manager + memory_provider + SessionDB FTS5 + honcho/mem0/supermemory)
- Context full layer (context_engine + context_compressor + context_references)
- Knowledge curation full (curator + insights)
- Cron / Routines (scheduled tasks + GitHub webhook + API trigger)

### 取り込まない

- TUI / Web UI (TaskManagedAI が UI/UX 層)
- packaging / I18n / release process
- gateway platforms (Telegram / Slack / WhatsApp 等)、Discord は MCP のまま

### 連携設計

- TaskManagedAI = UI/UX 層 + project scope auto-detect + task orchestration
- user-scope ハーネス v5 = memory backend
- 境界明確: domain code は TaskManagedAI、memory layer は user-scope

### Multi-machine sync

- skill / hook / rule: git 同期 (dotfiles)
- memory / session history: **local のみ、同期しない**
- 別 PC で git pull → 同じ skill で動作するが memory は別

## 3. 6 Phase Research 計画

### Phase A: Research deep dive (Codex multi-round)

**目的**: hermes-agent + 他参考 framework を網羅 research、取り込み判定の判断材料を完備。

| Round | 内容 | Skill | 状態 |
|---|---|---|---|
| **A-1** | hermes-agent 主要 module 完全 inventory | `codex-task` | 2026-05-10 起動済 (job: `b82jxnlgp`) |
| A-2 | Multi-agent framework research (MetaGPT / ChatDev / AutoGen / CrewAI / LangGraph + 公式 docs / paper) | `codex-task` | A-1 完了後 |
| A-3 | TaskManagedAI 文脈での適合判定 (Claude orchestration、両者統合した取り込み戦略 draft) | Claude | A-2 完了後 |

#### A-1 prompt 概要

`/Users/tohga/.claude/local/codex-tasks/2026-05-10/hermes-deep-dive-a1/prompt.md`:

調査対象:
- agent/ (memory_manager / memory_provider / context_engine / context_compressor / curator / insights / 各 adapter)
- hermes_state.py (SessionDB)
- model_tools.py / toolsets.py / tools/
- plugins/memory/ (honcho / mem0 / supermemory)
- plugins/context_engine/ / observability/ / kanban/ / hermes-achievements/
- cron/ / gateway/ / acp_adapter/
- run_agent.py (12k LOC) / cli.py (11k LOC) / batch_runner.py (56k)
- hermes_cli/ / optional-skills/ / skills/

各 module の出力: name / role / key_features / dependencies / loc / license_clean / task_managed_ai_fit_score / adoption_verdict (as-is/brush-up/optimize/skip) / adoption_rationale / multi_agent_relevance / concerns

特別フォーカス:
- plugins/kanban (multi-agent board dispatcher = 我々の司令塔候補)
- batch_runner.py (parallel agent)
- agent/curator.py (knowledge curation)
- agent/insights.py (insight generation)

#### A-2 prompt 案 (A-1 完了後)

調査対象:
- MetaGPT (https://github.com/geekan/MetaGPT) - software company simulation (CEO/PM/Engineer/Architect/QA)
- ChatDev (https://github.com/OpenBMB/ChatDev) - virtual software company
- Microsoft AutoGen (https://github.com/microsoft/autogen) - multi-agent conversation
- CrewAI (https://github.com/joaomdmoura/crewAI) - role-based multi-agent
- LangGraph (https://langchain-ai.github.io/langgraph/) - agent orchestration graph
- OpenAI Swarm (https://github.com/openai/swarm) - lightweight multi-agent
- AutoGPT / BabyAGI - 自律 agent
- Anthropic Computer Use - agent + tool use

各 framework で抽出:
- 役職 / role taxonomy 定義方法
- 司令塔 (orchestrator / dispatcher) パターン
- Inter-agent communication 機構
- 完全自律 (autonomous) の境界設計
- 「会社メタファー」「組織」「team」概念

### Phase B: 取り込み 4 分類判定 (Codex Round 4-5)

| Round | 内容 | Skill |
|---|---|---|
| B-1 | 取り込み 4 分類 + 判断根拠 | `codex-second-opinion` |
| B-2 | 4 分類の妥当性検証 (LICENSE / 依存 / 既存 boundary 衝突) | `codex-adversarial-review` |

### Phase C: TaskManagedAI 新 vision 詳細仕様 draft (Claude)

#### C-1: 役職定義 (Multi-agent role taxonomy)

固定役職: orchestrator / implementer / reviewer / tester / security_agent / researcher / observer / curator / dispatcher / ...
カスタム役職: ユーザーが追加可能

#### C-2: エージェント間会話場 (Inter-agent communication)

3 案を比較:
- 案 1: AgentRunEvent 拡張 (`inter_run_messages` event_type)
- 案 2: 新 entity `inter_agent_messages` table
- 案 3: hermes plugins/kanban を取り込み + adapt

採用判断 → ADR-00014 で固定。

#### C-3: 完全自律性の境界

- 自律 OK: ロー リスク (typo / docs / test 追加)
- approval 必要: 高リスク (DB schema / Provider 切替 / merge)
- 中間: 司令塔判断 (リスク評価 → policy auto-approve or human 承認)
- ADR-00009 (Action class taxonomy) 拡張: `orchestrator_dispatch` / `inter_agent_message` / `auto_approve_low_risk`

#### C-4: UI ↔ CLI parity 仕様

- 全機能 UI / CLI 両方から操作可能
- 同じ DB に記録
- CLI tool 名: `taskhub` または `tm` (要決定)
- Web UI Sprint 9 から拡張、CLI Sprint 16 で実装

#### C-5: メモリー記録の手動 / 自動切り替え

### Phase D: 既存設計との整合チェック (Codex Round 6)

`codex-plan-review` で:
- 既存 ADR (00001-00013) との衝突
- Hard Gates 7 / KPIs 5 への影響
- Sprint Pack (SP-000-007) との整合
- Provider Compliance / SecretBroker / AgentRun / runner_mutation_gateway 衝突
- ADR Gate Criteria 11 種すべてに照合

### Phase E: Adversarial review (Codex Round 7)

`codex-adversarial-review` で:
- security 欠陥 (Codex token 漏洩 / agent 権限昇格 / inter-agent message hijack)
- race condition (multi-agent 並列 deadlock / data race)
- edge case (司令塔死亡時 fail-over / agent 暴走 / loop)
- scope creep (P0 影響)
- LICENSE risk

### Phase F: 全体まとめ + 反映 (Claude)

#### 作成物

1. PRD-00 / 01 update (vision section 追加)
2. ADR-00014 (Multi-Agent Orchestration Architecture)
3. ADR-00015 (UI ↔ CLI Parity Boundary)
4. ADR-00016 (Hermes-Agent Integration Strategy)
5. ADR-00017 (AI Society Visualization)
6. (必要なら) ADR-00018 (Inter-agent Communication) / ADR-00019 (Role Taxonomy)
7. 新規 Sprint Pack 草案 SP-013 〜 SP-022
8. ハーネス v5 新規 Wave 19-23 ロードマップ
9. 取り込み 4 分類 一覧
10. 既存 ADR 00004/09/13 update + rules update

## 4. 想定 Sprint ロードマップ

### P0.1 Sprint 13-16 (multi-agent must_ship)

| Sprint | タイトル | target/max | must_ship |
|---|---|---|---|
| SP-013 | Multi-Agent Orchestration Foundation | 5/7 days | parent/child AgentRun + agent_team table + role taxonomy |
| SP-014 | Orchestrator Agent (司令塔) | 4/6 days | dispatcher + risk assessment + auto-approval policy |
| SP-015 | Inter-Agent Communication | 3/5 days | inter_agent_messages + AgentRunEvent 拡張 |
| SP-016 | UI ↔ CLI Parity (CLI tool 実装) | 4/6 days | taskhub/tm CLI + Web UI 同等操作 |

### P1 Sprint 17-20 (AI Society + memory 統合)

| Sprint | タイトル | target/max | must_ship |
|---|---|---|---|
| SP-017 | AI Society Visualization (UI 拡張) | 3/4 days | チケット board + agent role 視覚化 + 進捗 |
| SP-018 | Hermes Memory + Cron + Routines 統合 | 5/7 days | user-scope memory backend 連携 + cron / GitHub webhook |
| SP-019 | Project Scope Auto-Discovery | 3/5 days | task の project 自動判別 + boundary enforcement |
| SP-020 | 知見蓄積 + retrieval 自動化 | 3/5 days | UI/CLI 両方から記録、司令塔 auto-retrieve |

### P2 Sprint 21+ (キャラクター / 公開準備)

| Sprint | タイトル | target/max | must_ship |
|---|---|---|---|
| SP-021 | AI Character Generation (Codex 画像生成) | 1/2 days | 各 agent キャラクター icon |
| SP-022+ | 公開準備 (個人用ライセンス / docs) | TBD | TBD |

## 5. ハーネス v5 新規 Wave (P0 並行 or P0 完了後)

| Wave | タイトル | 取り込み source |
|---|---|---|
| Wave 19 | Memory Core (memory_manager + SessionDB FTS5) | hermes-agent agent/memory_manager.py + hermes_state.py |
| Wave 20 | Memory Plugins (honcho + mem0 + supermemory) | hermes-agent plugins/memory/ |
| Wave 21 | Context Layer (engine + compressor + references) | hermes-agent agent/context_*.py |
| Wave 22 | Knowledge Curation (curator + insights) | hermes-agent agent/curator.py + insights.py |
| Wave 23 | Cron + Routines | hermes-agent cron/ |

## 6. 既存設計との Gap 分析

### 6.1 既存設計に**足りない** (新規実装が必要)

| 機能 | 既存 | 新 vision で必要 |
|---|---|---|
| Multi-agent orchestration | なし (single AgentRun) | parent_run_id / child_run_id + agent_team table + inter_agent_messages |
| 司令塔 actor | actor_type 5 種 | 新 actor_type=`orchestrator` |
| Inter-agent communication | AgentRunEvent は run 内のみ | inter_run_messages event_type + 新 entity |
| 完全自律 trigger | approval 必須 | policy で自律判断可能な action class |
| UI ↔ CLI parity | UI 未実装、CLI 未計画 | 初期から parity で定義 |
| Memory 記録 | ContextSnapshot 10 列 | user-scope memory provider 連携 |
| キャラクター | なし | P2 で追加 |

### 6.2 既存設計が**support** (拡張で対応可能)

| 機能 | 既存 | 拡張ポイント |
|---|---|---|
| AgentRun 16 状態 | single-agent | multi-agent run semantics 追加 |
| ContextSnapshot 10 列 | 再現性 contract | inter-agent shared context |
| Provider Compliance v2 | provider 単位 | agent role 単位 compliance check |
| SecretBroker | secret 単位 atomic claim | agent 間 secret pass-through 禁止強化 |
| Approval Workflow | requester / decider 分離 | 司令塔 actor からの自動 approval |
| audit (AgentRunEvent) | run 内 event | inter-run event 追加 |

## 7. 既存 ADR / rules update 必要箇所

### 7.1 既存 ADR update

- ADR-00004 (AgentRun state machine): parent/child run 関係 + multi-agent run semantics
- ADR-00009 (Action class taxonomy): `orchestrator_dispatch` / `inter_agent_message` / `auto_approve_low_risk` 追加
- ADR-00006 (Secrets management): agent 間 secret pass-through 禁止強化
- ADR-00013 (Remote agent extension): orchestrator agent との関係 update

### 7.2 既存 rules update

- `.claude/rules/agentrun-state-machine.md`: multi-agent run section
- `.claude/rules/ai-output-boundary.md`: inter-agent communication boundary
- 新規 `.claude/reference/multi-agent-orchestration-draft.md`: orchestrator + 専門 agent + inter-run protocol

## 8. 次のアクション

### 8.1 今 session 中

- A-1 result parse → A-2 prompt 作成 → A-2 起動 (background)
- A-2 完了後 → A-3 (Claude が 2 source 統合) draft
- 別 session への引き継ぎ準備

### 8.2 別 session で継続 (Phase B-F)

- Phase B-1 (4 分類判定) → B-2 (adversarial)
- Phase C (詳細仕様 draft、Claude)
- Phase D (整合チェック、codex-plan-review)
- Phase E (adversarial review)
- Phase F (反映: PRD update + ADR-00014/15/16/17 + Sprint Pack 新規 SP-013-022)

### 8.3 Phase F 完了後

- Sprint 5.5 (Output Validator) 着手 (P0 並行進行 = 案 B)
- Sprint 7 前に Wave 14 (hook trust tier) 実装
- P0 完了 (Sprint 12) 後に ADR-00014/15/16/17 accepted 化 + SP-013-022 着手

## 9. 重要な User 指示記録 (2026-05-10)

1. 配布目的なし、ただし「公開できるようにもしてほしい」(個人 + 自分の他端末)
2. マルチマシン対応: git で同期、別 PC で同じ動作 (skill/hook/rule のみ、memory は local)
3. 完全自律性: 外部 trigger 不要、Discord 等は使わない
4. 司令塔 + 専門 agent: 役職指定可能、エージェント間会話場
5. UI ↔ CLI parity: どっちでやっても変わらない動き
6. キャラクター / Graphic: P2 で OK、Codex 画像生成 or 適当な default
7. TaskManagedAI = UI/UX 層: hermes-agent backend を user-scope ハーネス v5 で活用
8. **「実装する前に計画を完璧に詰める」**: Codex を多数使って抜け漏れなく
9. hermes-agent: 会社メタファー / multi-agent / 司令塔 / inter-agent は **おそらく hermes に存在しない**ので、別途 research 必要 (MetaGPT / ChatDev / AutoGen / CrewAI / LangGraph 等)
10. commit 範囲 (今 session): ADR-00013 のみ commit + 計画は memory + docs に記録

## 10. 関連ファイル

- `~/.claude/local/codex-tasks/2026-05-10/hermes-deep-dive-a1/` (Phase A-1 起動中)
- `~/.claude/local/codex-reviews/2026-05-10/TaskManagedAI/` (R1 Codex review for ADR-00013)
- `docs/adr/00013_remote_agent_extension.md` (commit `86e1035`、proposed)
- `docs/sprints/SP-006_cli_artifact.md` (frontmatter drift 修正済 commit `86e1035`)
- 計画書 (このファイル) + memory file (`project_taskmanagedai_vision_consolidation_plan.md`)
