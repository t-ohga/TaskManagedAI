# 04 Sprint Pack Candidates

## Candidate Allocation

| Candidate | Target Sprint / ADR | Deliverable | Verification |
|---|---|---|---|
| `pending_signals` / resume ledger | SP-004 Agent Runtime / ADR-00004 update | AgentRun resume reason, state_delta, pending signal list, resume event payload | state transition contract tests; stale approval invalidation tests |
| Provider structured output mapping | SP-005 Provider Adapter | provider-neutral structured output contract + mock parity fixtures。Gemini 変換は `config/provider_compliance.toml` の該当 feature が公式確認済みで、public-only 上限を超えない optional adapter mapping | mock adapter fixtures; schema mismatch negative tests; caller-supplied `allowed_data_class` reject |
| Tool / MCP registry | P0 Tool Registry / Read-only Gateway -> SP-014 network policies -> SP-015 Inter-Agent Communication -> SP-022 framework intake hardening | MCP server registry, tool schema hash, allowed_actions, approval_requirement, sandbox profile。P0 中は remote/network MCP deny-only | untrusted tool blocked; unknown MCP server blocked; raw tool output not trusted; network MCP unavailable until registry/policy accepted |
| SearchProviderAdapter | P0 backlog `BL-0113`〜`BL-0121` (`SP-010_research_evidence`, Sprint Pack 未作成) | `SearchRun`, `EvidenceSearchHit`, `raw_response_ref`, `normalized_hit`, `provider_request_fingerprint` | unit tests for request build and result parse; redaction test |
| GroundingSupport | P0 backlog `BL-0115`, `BL-0119`, `BL-0126` (`SP-010_research_evidence` / `SP-011_eval_harness`) | source URI/text/chunk refs, claim span, evidence link, citation verifier status | missing grounding metadata becomes `ungrounded`; citation coverage metric |
| Local hybrid retrieval | Memory / retrieval sprint, likely P0.1 | Postgres full-text + optional vector + metadata filter + RRF ranking policy | retrieval gold set with recall@k and path/error-string cases |
| Auto RAG Eval rewrite | P0 backlog `BL-0122`〜`BL-0130` (`SP-011_eval_harness`, Sprint Pack 未作成) | document sampling, chunking, clue generation, Q&A generation, critic review, human validation queue | seed determinism, reviewer disagreement, human validation required |
| Prompt / dataset / eval versioning | P0 backlog `BL-0122`〜`BL-0130` / P1 Eval UI | `prompt_versions`, `eval_datasets`, `eval_runs`, `eval_scores`, leaderboard view | dataset version immutable; eval result traceable to model/schema |
| Metadata-first observability | Observability / Audit | GenAI span metadata, no raw prompt default, token/cost/model/schema fingerprint | secret canary no raw payload; audit export redaction |
| Provider compliance follow-up | ADR-00010 / SP-005 | feature 単位 Matrix entry。既存 `gemini/generate_content` は public-only narrow adapter、Vertex Search / Agent Platform / Memory Bank / Code Execution は別 entry | matrix reason_code tests; provider blocked until verified; effective allowed data class recorded |
| Provider retry / timeout policy | SP-005 Provider Adapter + BudgetGuard | retryable status allowlist、attempt budget、timeout、jitter、idempotency key、provider-neutral transient error taxonomy | 429/500/502/503/504 retry fixtures; policy/validation error no-retry; cost budget not exceeded |
| Managed code execution / computer use gate | SP-0045 Tool Registry candidate + SP-007 Runner boundary + SP-022 intake hardening | feature records for provider-managed execution/browser; screenshot/DOM/output artifact class; human safety acknowledgement; sandbox profile | no direct execution; untrusted browser output cannot become instruction; destructive browser/action classes require approval |
| URL context / managed fetch gate | SP-010 Research Evidence + SP-014 Network Policy | URL trust classification、fetch allow/deny、source snapshot/hash、provider URL metadata ingestion | URL context unavailable until snapshot exists; missing citation metadata becomes ungrounded |
| Batch prediction / async provider job | P1 async provider job or P0.1 if high-value | `AsyncProviderJob`, input/output artifact refs, external storage deletion, completion signal, cost cap | orphan job detection; deletion/retention tests; data residency recorded |
| Multimodal Live API | P1 realtime intake / UI ADR | session audit、audio/video artifact policy、short-lived token handling、tool-call mixing gate | P0 blocked; no live API without retention and approval model |
| Responsible AI attack fixtures | SP-005.5 Output Validator + SP-011 Eval Harness | safety metadata schema, prompt/RAG/tool-output injection fixtures, DLP bypass examples, secret canary | safety filter is not approval; negative fixtures fail closed |
| Model Optimizer / provider routing | P1 provider routing / bake-off | `model_requested` / `model_resolved`, router decision metadata, cost/quality preference, compliance check per resolved model | resolved model recorded; unverified model blocked; eval bake-off before enablement |
| Custom embeddings / ranking | SP-010 Research Evidence + SP-011 Eval Harness | embedding model/dimension/task_type metadata, re-embedding policy, ranking policy version, ClearBox-inspired eval loop | retrieval gold set; dimension mismatch blocked; ranking policy version immutable |

## Suggested Implementation Order

1. SP-004: add `pending_signals` concept as artifact/event metadata, not as new top-level state explosion.
2. SP-005: keep provider adapter contract provider-neutral; add Gemini mapping only after Matrix entry is verified.
3. SP-010: `docs/sprints/SP-010_research_evidence.md` は既存 Pack として存在するため、本 intake の Research / Evidence 候補 (local-first Evidence / Search DTOs、P0 backlog `BL-0113`〜`BL-0121`) を直接接続し、Gemini 取り込み内容を SP-010 must_ship / exit criteria へ反映する。
4. SP-011: `docs/sprints/SP-011_eval_harness.md` は既存 Pack として存在するため、本 intake の Eval 候補 (gold set, attack fixture, P0 backlog `BL-0122`〜`BL-0130`) を直接接続し、Gemini 取り込み内容を SP-011 must_ship / exit criteria へ反映する。
5. Tool/MCP: P0 Tool Registry / Read-only Gateway、SP-014 network_access enum、SP-015 inter-agent communication、SP-022 framework intake hardening に分解し、P0 中は remote/network MCP を deny-only にする。
6. Reliability / Safety: SP-005 と SP-005.5 に retry / timeout / safety metadata / injection fixtures を先に入れる。provider feature 拡大より先に、失敗時と攻撃時の観測可能性を作る。
7. Managed Gemini features: code execution、computer use、URL context、batch、live、model optimizer は Sprint 候補に残すが、P0 実装候補ではなく high-risk gate 待ちにする。

## Traceability Guardrails

- P0 backlog の global `BL-*` と Sprint Pack-local `BL-*` が重複しているため、実装前に ID namespace を決める。この intake では global backlog ID を `P0-BL-*` 相当として読む。
- `SP-0045_tool_registry`, `SP-010_research_evidence`, `SP-011_eval_harness` は **正本 Sprint Pack として既存** (Gemini レビュー後に作成済)。本 intake は backlog 迂回ではなく **既存 Pack へ直接接続** すること。Pack 内容と矛盾する取り込みは Pack 側の update PR を起票する。
- 取り込み文書は Sprint Pack の代替ではない。実装フェーズでは、各候補を Sprint Pack / ADR / Provider Compliance Matrix / test fixture へ再分解する。

## Explicit Non-Goals

- Do not introduce Google ADK as the orchestrator runtime.
- Do not add Vertex AI Search as the default retrieval backend in P0.
- Do not build Streamlit / Colab admin UI.
- Do not enable raw provider request/response logging by default.
- Do not make provider cache names or memory bank records source of truth.
- Do not allow Gemini managed code execution, computer use, URL context, batch prediction, or live API through the existing `gemini/generate_content` public-only Matrix entry.
- Do not treat provider safety ratings, DLP, or search grounding as final safety/evidence verification.
