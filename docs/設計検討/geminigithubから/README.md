# Gemini GitHub 取り込み調査

作成日: 2026-05-14

対象 source:

- `/Users/tohga/sample/generative-ai`
- Git remote: `git@github.com:GoogleCloudPlatform/generative-ai.git`
- 確認 commit: `75873ec1`

## 結論

TaskManagedAI に取り込むべきなのは、Google Cloud / Gemini の managed service 実装そのものではなく、次の設計パターンです。

| 優先 | 採用候補 | TaskManagedAI での受け皿 |
|---:|---|---|
| 1 | 長時間 agent の状態機械、承認待ち、外部イベント resume | `AgentRun`、`AgentRunEvent`、`approval_requests`、`pending_signals` |
| 2 | structured output / tool calling / function schema | `ProviderAdapter`、`ToolCall`、`ToolSchema`、`OutputValidator` |
| 3 | MCP tool boundary と tool registry | `MCP Gateway`、`Tool Registry`、Policy / Approval / Audit |
| 4 | grounding / citation / search result 正規化 | `EvidenceSource`、`EvidenceItem`、`EvidenceSearchHit`、`GroundingSupport` |
| 5 | RAG / retrieval / ranking eval | `RetrievalEvalRun`、`EvalRun`、`RankingPolicyVersion` |
| 5.5 | grounding / citation trace evaluation | `GroundingSupport`、`EvidenceItem`、`citation_coverage` |
| 6 | metadata-first logging / trace | `audit_events`、`AgentRunEvent`、OpenTelemetry metadata、raw payload redaction |
| 7 | context caching / long context のコスト最適化 | `ContextSnapshot` を正本にし、provider cache は補助 metadata |
| 8 | prompt / dataset / eval versioning | `prompt_versions`、`eval_datasets`、`eval_runs`、leaderboard UI |
| 9 | bounded retry / timeout / retry budget | `ProviderAdapter` preflight、BudgetGuard、provider-neutral error taxonomy |
| 10 | safety ratings / prompt-injection / RAG attack mitigation | `SafetyMetadataRef`、`OutputValidator`、Eval fixtures、secret canary |
| 11 | managed code execution / computer use / URL context / batch / live API の gate | `Tool Registry`、`Runner Gateway`、Network Policy、Provider Compliance Matrix |
| 12 | custom embeddings / custom ranking | local-first retrieval metadata、`RankingPolicyVersion`、retrieval gold set |

## 重要な判断

- Google ADK / Agent Engine / Vertex AI Search / RAG Engine は、TaskManagedAI の中核 runtime にはしない。
- 2026-05-14 時点の公式 docs では Agent Engine / Agent Platform 周辺の呼称と product surface が `Gemini Enterprise Agent Platform`、`Agent Runtime`、`Agent Gateway`、`Memory Bank` 側へ広がっている。本文中の `Agent Engine` / `Vertex` / `Agent Platform` は古い名前の固定ではなく、Google managed agent surface 全般を指すリスクカテゴリとして扱う。
- P0 は provider 非依存の DB / artifact / audit / policy boundary を正本にする。
- 既存 `config/provider_compliance.toml` には `gemini/generate_content` の public-only entry がある。これは SP-005 の Gemini structured output adapter だけを狭く扱う入口であり、Vertex Search、Agent Platform Runtime、Memory Bank、Code Execution、managed grounding、internal 以上の送信を許可するものではない。
- Gemini Code Execution、Computer Use、URL Context、Batch Prediction、Multimodal Live API、Model Optimizer は、それぞれ独立した provider feature として扱う。`gemini/generate_content` entry の拡張解釈で許可しない。
- provider-managed execution / browser / fetch / live / batch は、直接採用ではなく `Tool Registry`、`Runner Gateway`、Network Policy、Provider Compliance Matrix、human approval、artifact redaction が揃うまで defer / reject-as-direct-execution とする。
- Sprint Pack への接続は、global P0 backlog ID を正本にする。既存 Sprint Pack 内の local `BL-*` と ID が衝突する箇所、未作成の `SP-0045_tool_registry` / `SP-010_research_evidence` / `SP-011_eval_harness` は、実装前に namespace か translation table で解消する。
- Gemini / Google Cloud は `ProviderAdapter` と `SearchProviderAdapter` の実装候補として扱うが、feature 単位の Matrix entry と ADR-00010 gate が通るまで managed service 実利用は defer する。
- provider compliance、retention、training use、data residency、pricing はこの repository だけでは確定しない。採用前に公式情報、ADR-00010、`config/provider_compliance.toml` の feature 単位更新が必要。
- Cloud Function の unauth / CORS `*`、raw request/response 表示、regex JSON tool extraction、always-on memory agent、Streamlit/Colab UI は直接採用しない。

## ファイル構成

| ファイル | 内容 |
|---|---|
| `00_source_inventory.md` | 調査対象 repo の構成、確認した主要ファイル、制約 |
| `01_findings_normalized.md` | Gemini repo から抽出した finding 一覧 |
| `02_existing_surface_mapping.md` | finding と TaskManagedAI 既存設計面の対応 |
| `03_adoption_decision.md` | adopt / defer / reject / reference_only の最終判断 |
| `04_sprint_pack_candidates.md` | 実装候補を Sprint / ADR / gate に分配 |
| `05_provider_adapter_and_tool_boundary.md` | ProviderAdapter、MCP、Tool Registry への取り込み方 |
| `06_rag_evidence_eval_design.md` | RAG / Evidence / Eval への取り込み方 |
| `07_second_review_corrections.md` | 2 回目レビューで見つけた修正と反映結果 |
| `08_third_review_corrections.md` | 3 回目レビューで見つけた managed execution / safety / retry / ranking / traceability の修正 |
| `raw/README.md` | raw evidence の扱いと再調査手順 |
| `raw/evidence_index.md` | finding ごとの再検証用 source anchor |

## 推奨 Next Step

1. `03_adoption_decision.md` の `adopt` 項目を、実在 Sprint Pack がある SP-004 / SP-005 / SP-015 / SP-022 と、未作成 Sprint Pack だが P0 backlog 行がある `SP-010_research_evidence` / `SP-011_eval_harness` に分けて割り当てる。
2. Gemini / Google Cloud provider compliance は、feature 単位で公式 docs を再確認し、ADR-00010 と `config/provider_compliance.toml` を更新する。既存 `gemini/generate_content` entry は public-only で、managed search / Agent Platform / Memory Bank には適用しない。
3. RAG / evidence は Vertex AI Search へ寄せず、まず PostgreSQL + full-text + optional vector + ranking policy で local-first に作る。
4. 実装に入る前に、global P0 backlog ID と Sprint Pack-local ID の衝突、未作成 Sprint Pack (`SP-0045`, `SP-010`, `SP-011`) を正規化する。取り込み文書は候補と gate を示すだけで、この step を完了扱いにしない。
