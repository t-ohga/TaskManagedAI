# 02 Existing Surface Mapping

## Mapping Summary

| Gemini finding | Existing TaskManagedAI surface | Mapping |
|---|---|---|
| GMG-F-001 / F-002 | `docs/基本設計/03_AIオーケストレーション設計.md`, ADR-00004, SP-004 | `pending_signals` と resume event を AgentRun lifecycle に追加検討する |
| GMG-F-003 | ADR-00014, `phase-c-multi-agent-spec-draft.md`, SP-013 / SP-014 / SP-015 | role は dispatch hint、権限は Policy / Approval / SecretBroker / Gateway に限定 |
| GMG-F-004 | SP-005 Provider Adapter, SP-005.5 Output Validator | provider-specific structured output を Pydantic / JSON Schema 正本に変換 |
| GMG-F-005 / F-006 | P0 Tool Registry / Read-only Gateway, ADR-00013 Remote Agent Extension, ADR-00018 Inter-Agent Communication, SP-014, SP-015, SP-022 | MCP は Gateway 経由。P0 中は remote/network MCP は deny-only、schema discovery は registry 入り前提、regex tool extraction は reject |
| GMG-F-007 / F-008 | `task機能検討.md`, ADR-00002, P0 backlog `BL-0113`〜`BL-0121` (`SP-010_research_evidence`, Sprint Pack 未作成) | Search result を `EvidenceSearchHit`、grounding を `GroundingSupport` へ正規化 |
| GMG-F-009 | `docs/基本設計/04_セキュリティ_権限_監査設計.md`, P0 backlog `BL-0122`〜`BL-0130` (`SP-011_eval_harness`, Sprint Pack 未作成), SP-012 | research eval set を生成 / 評価する |
| GMG-F-012 | P0 backlog `BL-0122`〜`BL-0130` (`SP-011_eval_harness`, Sprint Pack 未作成), SP-012 | retrieval / ranking を recall@k、precision@k、NDCG で評価する。citation coverage は GMG-F-008 の grounding / evidence trace 側へ接続する |
| GMG-F-010 / F-011 | `harness-v5-wave-19-23-roadmap.md`, memory / retrieval roadmap, P0 backlog `BL-0119` / `BL-0126` | local-first hybrid retrieval と embedding metadata を設計へ反映 |
| GMG-F-013 | ContextSnapshot 10 カラム、SP-004 | provider cache は continuation / optimization metadata、正本ではない |
| GMG-F-014 | `docs/基本設計/07_可観測性設計.md`, audit events | prompt/response raw logging ではなく metadata-first trace |
| GMG-F-015 | Eval Harness, SP-011, Provider bake-off deferred items | prompt / dataset / eval versioning を P0.1/P1 に接続 |
| GMG-F-016 / F-017 / F-018 | SP-022 framework intake hardening, ADR-00020 | framework / managed service / memory agent の取り込み gate と reject criteria |
| GMG-F-019 | Tool Registry, Runner Gateway, SP-0045 candidate, SP-007 Runner boundary, SP-022 framework intake hardening | provider-managed code execution / browser action は direct execution として reject。将来採用する場合も screenshot/DOM/output artifacts、safety acknowledgement、approval、sandbox、audit を必須にする |
| GMG-F-020 | SP-005.5 Output Validator, SP-011 Eval Harness, SecretBroker canary checks, Policy / Approval | safety ratings を redacted metadata として保存し、prompt/RAG/tool-output injection と DLP bypass を negative fixtures にする。provider safety filter は補助であり approval ではない |
| GMG-F-021 | SP-010 Research Evidence, SP-014 network policy, Evidence snapshot / citation verifier | URL Context は provider fetch と prompt context injection を混ぜるため、source snapshot/hash/fetch policy なしでは evidence 正本にしない |
| GMG-F-022 | AgentRun async job/event model, budget/cost ledger, artifact storage/deletion policy | Batch Prediction は async provider job と external output storage を扱う別 surface。completion signal と deletion policy が先 |
| GMG-F-023 | Future realtime intake / UI, Provider Compliance Matrix, Tool Gateway | Multimodal Live API は P0 out-of-scope。audio/video retention、bearer token、live tool-call mixing の設計が必要 |
| GMG-F-024 | SP-005 Provider Adapter, BudgetGuard, Observability | bounded retry、timeout、429/5xx handling、retry budget、idempotency key を provider-neutral request/result に加える |
| GMG-F-025 | Provider routing / bake-off roadmap, Eval Harness, Provider Compliance Matrix | provider-side model optimizer は resolved model と compliance/eval/cost trace なしでは採用しない |
| GMG-F-026 / F-027 | SP-010 Research Evidence, SP-011 Eval Harness, local retrieval roadmap | custom embeddings / ranking は local-first metadata と ranking policy eval に転用。Vertex/ClearBox backend は reference/defer |

## Existing Invariants To Preserve

| Invariant | Impact on Gemini intake |
|---|---|
| AgentRun 16 状態 + blocked サブ 3 | Gemini sample の state machine は参考にするが、TaskManagedAI の状態 enum は勝手に置換しない |
| ContextSnapshot 10 カラム | provider cache / long context / memory bank は ContextSnapshot を置換しない |
| Provider Compliance Matrix | 既存 `gemini/generate_content` は public-only。Vertex Search / Agent Platform / Memory Bank / Code Execution / managed grounding は feature 単位 Matrix 未検証なら送信しない |
| SecretBroker atomic claim | MCP tool / external provider / search API に raw secret を渡さない |
| Approval human-only decider | reviewer / orchestrator / subagent は approval decider にならない |
| Tool / Runner gateways | code execution、MCP、Cloud Function、external search は gateway 外で実行しない |
| tenant/project boundary | Evidence / Search / Eval / Memory は project_id を持つか service guard で project 境界を守る |
| Backlog traceability | global P0 backlog ID を正本にする。Sprint Pack-local `BL-*` と ID が衝突する箇所は、実装前に namespace か translation table を作る |

## Design Surfaces Needing Updates

| Surface | Proposed update |
|---|---|
| ProviderAdapter | Gemini structured output、tool call、cache metadata、usage、safety metadata を provider-neutral result に正規化 |
| Tool Registry | P0 Tool Registry / Read-only Gateway に MCP server / tool schema / risk_level / allowed_actions / approval_requirement / sandbox profile を保存。P0.1 で SP-014 network_access enum + tool_network_policies、SP-015 inter-agent communication、SP-022 framework intake hardening に拡張 |
| Evidence model | `EvidenceSearchHit`, `GroundingSupport`, `RetrievalQuery`, `RankingPolicyVersion` は `06_rag_evidence_eval_design.md` の差分表に従い、既存 table extension / artifact schema / defer に分類してから実装 |
| Eval Harness | `tool_trajectory`, `retrieval_recall`, `retrieval_precision`, `ranking_ndcg`, `citation_coverage`, `approval_gate_compliance`, `secret_canary_no_leak` を metrics として扱う。`citation_coverage` は grounding/evidence trace の metric として扱い、retrieval/ranking notebook 由来の metric と混同しない |
| UI Execution Log | request fingerprint、search query、top-k、ranking policy、grounding chunks、review verdict を表示 |
| Audit | raw request/response ではなく、redacted payload hash、metadata、provider_request_fingerprint を保存 |
| Provider reliability | retryable status、timeout、attempts、jitter、retry budget、idempotency key、non-retryable policy/validation error を provider-neutral に記録 |
| Managed feature gates | code execution、computer use、URL context、batch prediction、live API、model optimizer を feature 単位で Matrix / ADR / approval に通す |
