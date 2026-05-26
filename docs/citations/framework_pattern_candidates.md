# Framework Pattern Candidates (TaskManagedAI: pattern adoption only、code embed 禁止)

最終更新: 2026-05-12 (Phase A integration)

## 1. 本 doc の目的

TaskManagedAI の外部 AI/agent framework に対する **「参考にする pattern」と「import / code embed しない」** の境界を明示固定する。`ADR-00020 (Framework Intake Checklist)` の **8 verify** + **No code embed** + **persistence 二重化禁止** + **telemetry off** + **tenant boundary** を本 ledger の正本ルールとする。

候補 framework は AI-UIUX レポート (`docs/設計検討/AI統合タスク管理プラットフォームの最新UIUXと実装選定レポート.md`) で挙げられた 10 個。

## 2. ADR-00020 8 verify (非規範 summary、正本は `docs/adr/00020_framework_intake_checklist.md` §3)

**本セクションは ADR-00020 の参照 summary であり、規範的な checklist は ADR-00020 と `SP-022_framework_intake_hardening.md` を正本とする**。本 ledger と ADR-00020 が drift した場合は **ADR-00020 が勝つ**。

1. **License**: Polyform Shield 等の embed 禁止 license 検出
2. **Attribution**: citation 義務化
3. **No code embed**: from-scratch 再実装、CI で `import <framework>` denylist
4. **Persistence 二重化なし**: PostgreSQL 一本化
5. **External network deny**: Tailscale-only enforcement
6. **Telemetry off**: TaskManagedAI audit_events に統合
7. **Secret canary scan**: memory store / retrieve
8. **Tenant/project boundary**: DB FK + service layer 4 重防御

## 3. Framework Candidate Table

| Framework | 種別 | 参考にする pattern | import / embed 禁止項目 | 衝突 invariant | TaskManagedAI 対応 |
|---|---|---|---|---|---|
| **LangGraph** | agent orchestration | human-in-the-loop graph + streaming + single/multi/hierarchical 制御 | Python package `langgraph` の import、独自 checkpoint store、LangSmith telemetry | persistence (LangGraph checkpointer vs PostgreSQL)、telemetry (LangSmith) | AgentRun 16 状態 + ContextSnapshot 10 列 + AgentRunEvent (append-only) で同等概念を独自実装済 |
| **CrewAI** | role-based multi-agent | crews + flows + guardrails + knowledge + observability + RBAC | Python `crewai` import、CrewAI Enterprise SaaS | role が capability を授与する設計 (CrewAI role → tool access)、CrewAI が approval decider | ADR-00014 の 10 standard role + role ⊥ capability authorization で原則固定 (role は metadata、authorization は capability token + action_class + gateway) |
| **AutoGen** | agent-to-agent conversation | conversable agents + human/tools/code 統合 | Python `autogen` import、Microsoft Research telemetry | persistence、agent 間 secret pass-through | ADR-00018 inter_agent_messages atomic consume + payload_hash + previous_hash chain で代替 |
| **Semantic Kernel** | .NET / enterprise integration | sequential / concurrent / handoff / group chat / magentic pattern | .NET runtime、Microsoft telemetry | スタック不一致 (TaskManagedAI は Python/TypeScript) | 概念のみ参照、Python 側で同等 pattern を AgentRunEvent + orchestrator service で実装 |
| **Dapr Agents** | durable execution framework | durable workflow + retries + state + observability + agents-as-tools | Dapr sidecar、独自 actor / workflow runtime、Dapr telemetry | persistence 二重化、K8s 前提 (single-VPS Docker Compose と不整合) | arq + PostgreSQL で代替、durable workflow が必要なら P1 で再評価 |
| **Dify** | LLM app / agent platform | visual workflow + Agent node + Function Calling / ReAct + knowledge | Dify SaaS hosted、Dify self-hosted runtime | スタック分離 (self-hosted Dify cluster と TaskManagedAI Docker Compose は別 lifecycle) | 内製 UI (Sprint 9) + Server Actions で代替 |
| **Flowise** | visual LLM workflow builder | AgentFlow V2 + multi-agent + ノード中心設計 | Flowise SaaS / self-hosted runtime | スタック分離 | 内製 UI で代替 |
| **Letta** | memory-first agent platform | persistent memory + memory hierarchy + stateful agents | Letta SaaS / OSS runtime、独自 memory storage | persistence 二重化 (Letta memory store vs PostgreSQL)、ContextSnapshot 混合禁止 | ADR-00016 Hermes memory pattern adoption + `memory_retrieval_artifacts` 別 table で P1 実装 |
| **OpenHands** | open platform for cloud coding agents | skills + micro-agents + sandbox + GitHub/GitLab/Slack/API 連携 | OpenHands runtime、独自 sandbox container | runner_mutation_gateway 境界 (TaskManagedAI Sprint 7 で実装) | 自前 Docker isolated runner + forbidden path / dangerous command で代替 |
| **TaskingAI** | unified model/tool API | plugin + async high concurrency + OpenAI-compatible API | TaskingAI runtime、独自 plugin store | Provider Compliance Matrix の bypass | ProviderAdapter (SP-005 完了済) + Provider Compliance Matrix で代替 |
| **Foundational Crypto (non-AI)** | cryptographic primitives | HMAC / SHA-256 / AES via `cryptography` PyPI package | N/A (stdlib-level dependency) | N/A | SOPS + age + SecretBroker で使用。pattern 参照ではなく dependency として管理 |

## 4. 採用判定の枠組み

各 framework に対して以下 3 axis で判定する:

| 判定 | 意味 | 例 |
|---|---|---|
| 🟢 **pattern adoption** | 設計 / UX pattern を参考にして TaskManagedAI 独自実装 | LangGraph human-in-the-loop → AgentRun `waiting_approval` |
| 🟡 **PoC 候補** | 別 repo で PoC、product code には embed しない | LangGraph で agent loop の比較評価 (research only) |
| ❌ **product code 拒否** | `import <framework>` を CI で denylist | `import langgraph`, `from crewai import` 等 |

**現時点 (P0 期間) の判定**: 全 10 framework が 🟢 pattern adoption + ❌ product code 拒否。

## 5. Provider Compliance Matrix への影響

framework は **Provider ではない** (LLM provider は OpenAI / Anthropic / Gemini / Mock のみ)。LangGraph / CrewAI 等は LLM API の wrapper であり、Provider Compliance Matrix の対象外。

local LLM (Ollama / vLLM / llama.cpp) は **Provider** として将来 Matrix に行追加 (P1)。本 ledger とは別扱い。

## 6. ADR-00020 8 verify 検証手順 (新規 framework 候補が出た時)

新規 framework を候補に追加したい場合:

1. **License 検証**: Polyform Shield / GPL-strong-copyleft / commercial-only を CI で grep
2. **Attribution 義務化**: citation を本 ledger に追加
3. **No code embed 確認**: 該当 package を `import` する PR があれば PR review で BLOCK、CI で denylist (将来 SP-022 で実装)
4. **Persistence 検証**: framework 内蔵 store を使う設計が含まれていれば 拒否
5. **External network 検証**: Tailscale 閉域内で動作するか確認
6. **Telemetry off 検証**: 独自 telemetry endpoint を持つか確認、ある場合は無効化方法を明示
7. **Secret canary 検証**: framework が secret を log / artifact に出力する経路を grep
8. **Tenant/project boundary**: framework 内で tenant 概念があるか、TaskManagedAI tenant_id と整合するか確認

## 7. CI 化 (Sprint 6 / SP-022 で実装)

`SP-022_framework_intake_hardening.md` で以下 CI gate を実装予定:

- `import langgraph`, `from crewai import`, `import autogen`, `from letta import`, `import dapr`, `import dify`, `from flowise import`, `import openhands`, `import taskingai` を `backend/` / `frontend/` で grep → `pytest` / CI step で BLOCK
- ADR-00020 §3 (No code embed) の自動化

## 8. 関連 ADR / Sprint Pack

- ADR-00013 (Codex app-server / Claude Agent SDK extension point) — 外部 agent runtime との境界
- ADR-00014 (Multi-agent orchestration foundation) — role ⊥ capability authorization 不変
- ADR-00016 (Hermes memory) — Letta pattern の TaskManagedAI 適用
- ADR-00018 (Inter-agent communication) — AutoGen pattern の代替
- ADR-00020 (Framework intake checklist) — **本 ledger の正本ルール**
- SP-006 (CLI artifact) — Sprint 6、skill I/O 接続時
- SP-022 (Framework intake hardening) — CI 自動化

## 9. 改訂履歴

- 2026-05-12 初版 (Phase A integration、Claude + Codex orchestration)

## 10. References

各 framework の公式 doc / repository は UIUX レポート (`docs/設計検討/AI統合タスク管理プラットフォームの最新UIUXと実装選定レポート.md`) §「実務で参考になる製品とOSSカタログ」を参照。
