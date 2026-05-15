# 00 Source Inventory

## Source Repo

| 項目 | 値 |
|---|---|
| local path | `/Users/tohga/sample/generative-ai` |
| remote | `git@github.com:GoogleCloudPlatform/generative-ai.git` |
| checked commit | `75873ec1` |
| license | Apache License 2.0 (`LICENSE`) |
| stated support level | README disclaimer: repository code is demonstrative and not an officially supported Google product |
| target output | `/Users/tohga/repo/TaskManagedAI/docs/設計検討/geminigithubから` |

## Top-Level Taxonomy

| Directory / file | 内容 | TaskManagedAI relevance |
|---|---|---|
| `gemini/` | Gemini API notebooks: function calling, structured output, context caching, evaluation, grounding, MCP, long context, orchestration, responsible AI, code execution, computer use, URL context, batch, live API, model optimizer | ProviderAdapter, Tool Gateway, Runner Gateway, Eval, ContextSnapshot |
| `agents/` | ADK / Agent Engine / long-running agent samples | AgentRun, pending signals, resume flow, multi-agent role split |
| `search/` | Vertex AI Search, RAG eval, Cloud Function, web app, ranking, user events, custom embeddings, custom ranking | Evidence search, SearchProviderAdapter, embedding metadata, ranking policy |
| `embeddings/` | vector search, hybrid search, task-type embeddings, anomaly sampling | local-first retrieval, vector/lexical hybrid, safety eval |
| `rag-grounding/` | RAG and grounding index | Evidence/citation design and RAG evaluation |
| `tools/llmevalkit/` | prompt management, dataset creation, evaluation, prompt optimization | prompt_versions, eval_runs, leaderboard |
| `sdk/retries/` | retry configuration examples | ProviderAdapter retry policy |
| `.gemini/styleguide.md` | repository style and model / SDK conventions | Reference only; not a final provider compliance source |
| `.github/linters/` | lint, gitleaks, markdown, notebook QA config | quality harness reference only |

## High-Value Evidence Paths

| Area | Evidence paths |
|---|---|
| Long-running agent / resume | `agents/adk/new-hire-onboarding/README.md`, `agents/adk/new-hire-onboarding/app/agent.py`, `agents/adk/new-hire-onboarding/app/resume_handler.py`, `agents/adk/new-hire-onboarding/app/live_onboarding.py`, `agents/adk/new-hire-onboarding/tests/eval/evalsets/onboarding_eval.json` |
| MCP / tool boundary | `gemini/mcp/intro_to_mcp.ipynb`, `gemini/mcp/adk_multiagent_mcp_app/main.py`, `gemini/mcp/mcp_orchestration_app/src/gemini_client.py` |
| Function/tool calling | `gemini/function-calling/README.md`, `gemini/function-calling/intro_function_calling.ipynb`, `gemini/function-calling/forced_function_calling.ipynb`, `gemini/function-calling/parallel_function_calling.ipynb` |
| Structured output | `gemini/controlled-generation/intro_controlled_generation.ipynb`, `search/auto-rag-eval/llm_utils.py` |
| Evaluation | `gemini/evaluation/*`, `agents/adk/new-hire-onboarding/tests/eval/eval_config.json`, `tools/llmevalkit/README.md` |
| Grounding / citations | `gemini/grounding/*`, `rag-grounding/README.md`, `search/web-app/vais_utils.py` |
| Search gateway | `search/cloud-function/python/vertex_ai_search_client.py`, `search/cloud-function/python/test_vertex_ai_search_client.py` |
| RAG benchmark generation | `search/auto-rag-eval/README.md`, `search/auto-rag-eval/main.py`, `search/auto-rag-eval/llm_utils.py`, `search/auto-rag-eval/transform_benchmark.py` |
| Hybrid retrieval | `embeddings/hybrid-search.ipynb`, `embeddings/task-type-embedding.ipynb` |
| Provider-managed execution / browser | `gemini/code-execution/intro_code_execution.ipynb`, `gemini/computer-use/intro_computer_use.ipynb`, `gemini/computer-use/web-agent/web_agent.py` |
| Responsible AI / prompt attack mitigation | `gemini/responsible-ai/README.md`, `gemini/responsible-ai/gemini_safety_ratings.ipynb`, `gemini/responsible-ai/gemini_prompt_attacks_mitigation_examples.ipynb`, `gemini/responsible-ai/react_rag_attacks_mitigations_examples.ipynb` |
| Managed fetch / batch / live | `gemini/url-context/intro_url_context.ipynb`, `gemini/batch-prediction/intro_batch_prediction.ipynb`, `gemini/batch-prediction/monitor_batch_prediction_gemini_api.ipynb`, `gemini/multimodal-live-api/intro_multimodal_live_api.ipynb` |
| Retry / model routing | `sdk/retries/configure_retries.ipynb`, `gemini/model-optimizer/intro_model_optimizer.ipynb` |
| Custom embeddings / custom ranking | `search/custom-embeddings/custom_embeddings.ipynb`, `search/custom-ranking/clearbox.ipynb` |
| Observability | `gemini/logging/intro_request_response_logging.ipynb`, `agents/adk/new-hire-onboarding/app/app_utils/telemetry.py`, `agents/adk/new-hire-onboarding/app/resume_handler.py` |
| Provider style / SDK drift | `.gemini/styleguide.md`, `sdk/retries/configure_retries.ipynb` |

## Evidence Path Resolution

All source evidence paths in this intake are resolved relative to:

```text
/Users/tohga/sample/generative-ai
commit 75873ec1cfd9a82ec98a76536fcc1f04642cccb3
```

When a source notebook is cited, the line number refers to the checked-out `.ipynb` JSON line in the local repository, not a rendered notebook cell number. `raw/evidence_index.md` is the durable re-check index for the most important findings.

## Official Current Surface Check

This intake is source-repo-based, but the product surface is moving. On 2026-05-14, official Google docs expose ADK and Agent Runtime under the Gemini Enterprise Agent Platform navigation, including Agent Runtime, Agent Gateway, sessions, Memory Bank, code execution, tracing, logging, monitoring, IAM identity, and Private Service Connect. The practical implication is not “use the managed platform now”; it is the opposite:

- treat Google managed agent services as feature-specific provider surfaces, not as TaskManagedAI's source of truth;
- verify each feature separately in Provider Compliance Matrix before any non-public data flow;
- keep TaskManagedAI's local AgentRun, ContextSnapshot, Tool Registry, approval, audit, and evidence model as the canonical state.

## Source Constraints

- この repo は notebook と demo sample が多く、production code として直接移植する前提ではない。
- Google Cloud / Vertex / Agent Platform に強く依存する例が多いため、TaskManagedAI の P0 では provider 非依存の抽象境界を先に作る。
- provider compliance はこの source repo だけでは確定できない。既存 `gemini/generate_content` public-only entry は narrow adapter 用であり、Vertex Search、Agent Platform Runtime、Memory Bank、Code Execution、managed grounding、internal 以上の送信には別 entry と ADR-00010 gate が必要。
- provider-managed code execution / computer use / URL context / batch prediction / live API は、通常の text generation ではなく別 feature surface として扱う。TaskManagedAI では、source repo の便利さよりも sandbox、human approval、artifact redaction、audit、network policy、retention verification を先に置く。
- sample には raw payload 表示、CORS `*`、unauth deploy、regex JSON extraction、in-memory / SQLite session など、TaskManagedAI の安全境界では採用不可の要素が含まれる。
