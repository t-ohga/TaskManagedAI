# 03 Adoption Decision

## Adopt Now As Design Inputs

| Decision ID | Adopt | Reason | Required gate |
|---|---|---|---|
| GMG-D-001 | `pending_signals` / resume trigger の概念 | AgentRun の `waiting_approval` / `blocked` / `provider_incomplete` からの再開説明力が上がる | SP-004 state transition tests |
| GMG-D-002 | structured output と function/tool schema の正規化 | ProviderAdapter の contract に直結 | SP-005 provider contract + OutputValidator |
| GMG-D-003 | MCP tool registry pattern | tool discovery / tool permission / audit を分離できる | ADR-00013 / SP-015 / SP-022 |
| GMG-D-004 | SearchProviderAdapter + EvidenceSearchHit DTO | Evidence retrieval を provider 非依存にできる | P0 backlog `BL-0113`-`BL-0121` (`SP-010_research_evidence`, Sprint Pack 未作成) |
| GMG-D-005 | GroundingSupport / citation trace | Claim と Evidence の接続を UI / Eval で説明できる | citation verifier + provenance hash |
| GMG-D-006 | Hybrid search + RRF | source sample は SKU / product name / proprietary codename 系の semantic-only 弱点を示す。Issue 番号、path、error text は TaskManagedAI 固有の類推ユースケース | local Postgres implementation first + TaskManagedAI retrieval gold set |
| GMG-D-007 | Retrieval / trajectory eval | agent 品質を回答だけでなく行動系列で測れる | Eval dataset version + deterministic fixtures |
| GMG-D-008 | metadata-first logging | audit と debugging を両立し、秘密情報露出を抑える | redaction + raw payload no-store tests |
| GMG-D-009 | prompt / dataset / eval versioning | provider bake-off と regression tracking に必要 | Eval Harness design |
| GMG-D-024 | bounded retry / timeout / retry budget | provider transient failure と rate limit を正常系から分離し、過剰 retry / runaway cost を防げる | retryable_status allowlist、attempt budget、timeout、idempotency、policy/validation error no-retry tests |
| GMG-D-025 | safety ratings / prompt-injection / RAG attack mitigation patterns | provider safety response、DLP bypass、tool/RAG injection を OutputValidator と Eval Harness の negative fixtures に落とせる | SafetyMetadata redaction、secret canary、RAG/tool-output injection fixtures |

## Defer

| Decision ID | Defer | Reason | Resume condition |
|---|---|---|---|
| GMG-D-010 | Gemini / Vertex / Agent Platform の provider 実利用拡大 | 既存 `gemini/generate_content` は public-only entry と SP-005 narrow adapter があるが、managed search / Agent Platform / Memory Bank / Code Execution / internal 以上の送信は provider compliance と費用・retention・data residency が未検証 | feature 単位 Matrix entry が `training_use=no`, retention 確定, `region_or_data_transfer=verified`, 必要 plan 確認済みで、ADR-00010 に従い effective allowed data class が確定していること。既存 public-only entry は Vertex / Agent Platform / managed search には適用不可 |
| GMG-D-011 | task-type embeddings | model 固有で再埋め込み戦略が必要 | embedding metadata schema と eval set 作成後 |
| GMG-D-012 | context caching 実利用 | cache は provider state で正本にならない | ContextSnapshot hash + cache TTL + stale invalidation 設計後 |
| GMG-D-013 | always-on memory / Memory Bank 的機能 | retention, revision, deletion, project boundary が先 | `memory_records` と audit/revision policy 実装後 |
| GMG-D-014 | Streamlit / Colab eval UI | TaskManagedAI の Next.js UI と二重管理になる | UI sprint で Next.js 管理画面へ吸収 |
| GMG-D-026 | provider-managed URL Context | provider fetch と evidence capture が一体化し、source snapshot と trust classification がないと監査できない | fetch policy、URL allow/deny、source snapshot hash、citation verifier、network policy |
| GMG-D-027 | Batch Prediction | async job、external storage output、large-volume cost、deletion/data residency が未設計 | async provider job ledger、input/output artifact retention、completion signal、cost cap |
| GMG-D-028 | Multimodal Live API | WebSocket、short-lived bearer token、audio/video retention、live tool calls が P0 provider adapter と別 surface | realtime intake ADR、audio/video retention、tool-call mixing gate、session audit |
| GMG-D-029 | provider-side Model Optimizer | provider が model routing を行うため、resolved model と compliance/eval trace なしでは audit が弱い | `model_resolved`、router decision metadata、cost/quality preference、eval bake-off、Matrix coverage |
| GMG-D-030 | custom embeddings / task-type embeddings の provider direct use | model/dimension/task_type/re-embedding strategy と eval がないと後戻りが重い | embedding metadata schema、dimension migration、re-embedding plan、retrieval gold set |

## Reject

| Decision ID | Reject | Reason |
|---|---|---|
| GMG-D-015 | Google ADK / Agent Engine を中核 runtime に固定 | TaskManagedAI は provider adapter / runner gateway 前提。中核を特定 cloud framework に固定しない |
| GMG-D-016 | regex JSON tool call extraction | 壊れやすく、security boundary にならない |
| GMG-D-017 | unauth Cloud Function / CORS `*` sample | Tailscale / auth / project boundary / audit と衝突 |
| GMG-D-018 | raw request/response logging 常時保存 | secret / PII / repo confidential 情報の漏えいリスクが高い |
| GMG-D-019 | 自動生成 benchmark を正解データとして扱う | human validation 前提。初期 seed としてのみ利用 |
| GMG-D-020 | provider grounding metadata を無検証で真実扱い | citation verifier と evidence snapshot が必要 |
| GMG-D-031 | Gemini Code Execution / Computer Use の direct use | provider-managed code/browser execution を Runner/Tool Gateway 外で許可すると、TaskManagedAI の approval、sandbox、audit、secret boundary を迂回する |
| GMG-D-032 | safety filter off / DLP-only / regex-only safety | source sample には safety filter を下げる実験や DLP bypass が含まれる。TaskManagedAI の安全境界にはならない |

## Reference Only

| Decision ID | Reference | Use |
|---|---|---|
| GMG-D-021 | `.gemini/styleguide.md` | SDK / model drift を見る参考。TaskManagedAI の provider compliance 正本にはしない |
| GMG-D-022 | `.github/linters/*` | notebook / sample repo の lint 参考。TaskManagedAI の lint policy は既存 stack 優先 |
| GMG-D-023 | `tools/llmevalkit` Streamlit implementation | 概念参考。UI と storage は TaskManagedAI に合わせて再実装 |
| GMG-D-033 | ClearBox custom ranking implementation | ranking policy / optimization loop の参考。Vertex backend 依存は local-first retrieval 実装後に再評価 |

## Implementation Blockers / Traceability Clarifications

- `SP-0045_tool_registry`, `SP-010_research_evidence`, `SP-011_eval_harness` は P0 backlog で参照されているが、この intake では Sprint Pack 本体を作らない。実装に入る前に heavy pack を作るか、既存 pack へ正式に統合する。
- `BL-*` は global P0 backlog ID と Sprint Pack-local ticket ID が衝突している。ここでの `BL-0113` などは global P0 backlog を指す。Sprint Pack 側に流すときは `P0-BL-*` / `SP005-BL-*` のような namespace か translation table を作る。
- この文書群は採用判断と gate の正本であり、managed Gemini feature の実利用許可ではない。実利用には ADR-00010、Provider Compliance Matrix、repo 固有 high-risk gate が必要。
