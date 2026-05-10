# ハーネス v5 Wave 19-23 ロードマップ (Multi-Agent + Memory + Curation + Cron)

最終更新: 2026-05-10 (Phase D R1 rewrite + R2 進行中)

## 目的

ハーネス v5 (Wave 1-18) は **dotfiles レベルの skill / hook / rule / agents / reference**。Wave 19-23 は **TaskManagedAI と user-scope ハーネス連携 backend**を追加し、TaskManagedAI vision の「会社メタファー / multi-agent / 司令塔 / inter-agent communication / hermes 級 memory / 知見蓄積」を実現する。

## 関連 docs

- `docs/設計検討/phase-c-multi-agent-spec-draft.md` (Phase C 詳細仕様 draft)
- `docs/adr/00014_multi_agent_orchestration.md` (proposed)
- `docs/adr/00015_ui_cli_parity.md` (proposed)
- `docs/adr/00016_hermes_agent_integration_strategy.md` (proposed)
- `docs/adr/00018_inter_agent_communication.md` (proposed)
- `docs/adr/00019_role_taxonomy.md` (proposed)
- `docs/adr/00020_framework_intake_checklist.md` (Phase F で起票予定)
- Phase A-1 result: `~/.claude/local/codex-tasks/2026-05-10/hermes-deep-dive-a1/result.md`
- Phase B-1 result: `~/.claude/local/codex-tasks/2026-05-10/take-up-classification-b1/result.md`

## Wave 配置原則

- **Wave 19-22**: P1 (Sprint 17-20) で実装、TaskManagedAI memory / context / curation backend
- **Wave 23**: P1 後半 / P2 で実装、cron / routines (scheduled tasks)
- 取り込み方針: **pattern adoption only** (hermes-agent コード直接 embed 禁止、ADR-00016 準拠)
- license / persistence / external network / telemetry: ADR-00020 framework intake checklist で逐次 verify

## Wave 19: Memory Core

| 項目 | 内容 |
|---|---|
| **タイトル** | Memory Core (memory_records + memory_retrieval_artifacts + tsvector + GIN) |
| **取り込み source (pattern only)** | hermes-agent `agent/memory_manager.py` + `hermes_state.py` + `agent/sessiondb.py` |
| **取り込まない** | hermes 独自 SQLite persistence (kanban_db.py 系)、honcho/mem0/supermemory external API |
| **実装 Sprint** | SP-018 (memory backend integration、target 5/max 7 days) |
| **主要 deliverable** | (1) `memory_records` table 14 列 + 5 複合 FK + tsvector + GIN search、(2) `memory_retrieval_artifacts` table immutable artifact ref、(3) record_kind 5 種 enum 5+ source 整合、(4) sanitizer pipeline + redaction_status + sanitizer_version、(5) tenant/project boundary FK enforcement、(6) backup/restore drill 拡張 |
| **既存 invariant 保証** | ContextSnapshot 10 列不変、tool_manifest または evidence_set_hash 経由で memory_retrieval_artifacts 参照、raw memory text を AgentRun column に直接入れない |
| **AC-HARD trace** | AC-HARD-04 (backup/restore RPO≤24h, RTO≤4h、memory_records / memory_retrieval_artifacts を drill 対象に追加) |
| **AC-KPI trace** | AC-KPI-04 (citation_coverage、final adopted artifact のみ計測) |
| **rollback** | tenant_config で `memory_enabled=false`、CLI / UI / orchestrator から memory CRUD path deny |

## Wave 20: Memory Plugins (concept of multiple provider)

| 項目 | 内容 |
|---|---|
| **タイトル** | Memory Plugins (provider abstraction、internal 実装のみ) |
| **取り込み source (pattern only)** | hermes-agent `plugins/memory/honcho_provider.py` + `mem0_provider.py` + `supermemory_provider.py` の **interface concept のみ** |
| **取り込まない** | honcho/mem0/supermemory cloud API への HTTP 送信 (Tailscale-only invariant 違反、R-013) |
| **実装 Sprint** | SP-018 拡張 (Wave 19 と同 Sprint 内) |
| **主要 deliverable** | (1) provider abstraction (TaskManagedAI 内部のみ、外部 API 呼び出しなし)、(2) external HTTP egress を service layer で deny enforcement、(3) ProviderAdapter 経由のみで embedding 取得 (provider-compliance §6 通過必須) |
| **既存 invariant 保証** | Tailscale-only / external network deny / payload_data_class enforcement / secret canary scan |
| **rollback** | provider_enabled per-provider toggle |

## Wave 21: Context Layer

| 項目 | 内容 |
|---|---|
| **タイトル** | Context Layer (engine + compressor + references) |
| **取り込み source (pattern only)** | hermes-agent `agent/context_engine.py` + `context_compressor.py` + `context_references.py` |
| **取り込まない** | hermes 独自 ContextSnapshot 上書き (TaskManagedAI 既存 ContextSnapshot 10 列不変) |
| **実装 Sprint** | SP-018 拡張 |
| **主要 deliverable** | (1) memory retrieval → memory_retrieval_artifacts 別 table 経由で参照、(2) summarizer (artifact-derived、Pydantic typed)、(3) ContextSnapshot.tool_manifest または evidence_set_hash から retrieval_artifacts.id 参照、(4) trust_level=untrusted_content 強制 (memory-derived は常に untrusted) |
| **既存 invariant 保証** | ContextSnapshot 10 列 (`prompt_pack_version` / `prompt_pack_lock` / `policy_version` / `policy_pack_lock` / `repo_state` / `tool_manifest` / `evidence_set_hash` / `provider_continuation_ref` / `provider_request_fingerprint` / `snapshot_kind`) 完全不変 |
| **rollback** | context retrieval を tool_manifest から外す (memory_retrieval_artifacts は残し、参照のみ無効化) |

## Wave 22: Knowledge Curation (curator + insights)

| 項目 | 内容 |
|---|---|
| **タイトル** | Knowledge Curation (curator + insights、低価値 archive + insight 抽出) |
| **取り込み source (pattern only)** | hermes-agent `agent/curator.py` + `agent/insights.py` |
| **取り込まない** | hermes 独自 archive policy / external insight publishing |
| **実装 Sprint** | SP-020 (curator + insights integration、target 3/max 5 days) |
| **主要 deliverable** | (1) 完了 run から学び抽出 (auto_completion / auto_failure / auto_review_finding record_kind の自動生成)、(2) 低価値 memory 自動 archive (relevance_score + 経過時間 + manual_user vs auto の重み)、(3) insight 集計 view (UI dashboard 用、CLI も parity)、(4) tenant_config で auto_curate enable/disable per record_kind |
| **既存 invariant 保証** | memory_records.archived_at 経過後の retrieval から除外、cross-tenant insight reject |
| **AC-KPI trace** | AC-KPI-04 (citation_coverage 改善)、AC-KPI-05 (cost_per_completed_task の learning curve 計測) |
| **rollback** | tenant_config で `curator_enabled=false`、archive 自動化を停止 (手動 archive のみ) |

## Wave 23: Cron + Routines

| 項目 | 内容 |
|---|---|
| **タイトル** | Cron + Routines (scheduled tasks + GitHub webhook + API trigger) |
| **取り込み source (pattern only)** | hermes-agent `cron/` + `gateway/` の concept (但し具体的 gateway は除外、TaskManagedAI 既存 RepoProxy / Tailscale 経由のみ) |
| **取り込まない** | Discord / external messaging gateway (TaskManagedAI vision の「外部 trigger 不要」と整合)、external observability platform (Loki / Prometheus は TaskManagedAI 既存 plan で別途) |
| **実装 Sprint** | P1 後半 / P2 (SP-022 以降、target 4/max 6 days) |
| **主要 deliverable** | (1) tenant/project scope の cron daemon (systemd timer + arq)、(2) GitHub webhook 連携 (Tailscale 経由のみ、existing RepoProxy 拡張)、(3) routine task abstraction (orchestrator が自律 trigger)、(4) max_concurrent / max_runtime / budget per cron entry、(5) audit_events `cron_triggered` |
| **既存 invariant 保証** | Tailscale-only / external trigger は GitHub Tailscale Action のみ / network deny-by-default |
| **rollback** | systemd `disable taskmanagedai-cron`、cron daemon 停止 |

## Wave 19-23 共通 framework intake checklist (ADR-00020 準拠)

各 Wave の取り込み判断時に以下を verify:

| # | 検査項目 | 通過条件 |
|---|---|---|
| 1 | License | hermes-agent の LICENSE が pattern adoption (concept 引用) と attribution 義務化を許容するか |
| 2 | Attribution | 各 Wave で `docs/citations/hermes_pattern_adoption.md` に出典 (commit hash + file path + concept 説明) を記録 |
| 3 | No code embed | hermes コードを直接 copy しない、from-scratch 再実装、参考のみ (CI で `import hermes_agent` denylist) |
| 4 | Persistence | 独自 SQLite (kanban_db.py 系) を持ち込まない、PostgreSQL 一本化 |
| 5 | External network | external API (honcho cloud / mem0 SaaS / supermemory.ai) への送信 deny、internal-only enforcement |
| 6 | Telemetry off | hermes 独自 telemetry / observability publishing を deny、TaskManagedAI 既存 audit_events に統合 |
| 7 | Secret canary | memory store / retrieve で secret canary scan 必須 (provider-compliance §8 と同等) |
| 8 | tenant/project boundary | DB 複合 FK + service layer 4 重防御で multi-tenant cross-talk reject |

## Wave 19-23 と P0/P0.1/P1 sealing

- **P0 (Sprint 1-12)**: Wave 19-23 由来の implementation path 追加禁止 (Phase C §1.6 P0 sealed CI guard、rg denylist で enforce)
- **P0.1 (Sprint 13-16)**: Wave 19-23 はまだ実装しない、P0.1 は multi-agent foundation のみ
- **P1 (Sprint 17-20)**: Wave 19-22 を SP-018 / SP-020 で実装 (memory + context + curation)
- **P1 後半 / P2 (SP-022+)**: Wave 23 (cron + routines) を実装

## 関連 file 作成計画 (Phase F で実施)

- `docs/citations/hermes_pattern_adoption.md` (Wave 19 着手時に新規作成、各 Wave で patch 拡張)
- `docs/adr/00020_framework_intake_checklist.md` (Phase F で起票)
- `docs/sprints/SP-018_hermes_memory_integration.md` (Phase F で heavy Pack 起票)
- `docs/sprints/SP-020_curator_insights_integration.md` (Phase F で heavy Pack 起票)
- `tests/memory/*` 各 contract / negative test (Wave 19 実装時)
- `eval/multi_agent/memory_secret_canary/` (Wave 19 実装時、AC-HARD 候補 fixture)
- `eval/multi_agent/memory_cross_tenant/` (Wave 19 実装時、AC-HARD-03 連動)

## 改訂履歴

| 日付 | 内容 |
|---|---|
| 2026-05-10 | Phase C draft Phase D R1 rewrite 後の Wave 19-23 ロードマップ初版 |
