# 05 Provider Adapter And Tool Boundary

## ProviderAdapter Delta

Gemini repository samples reinforce the current TaskManagedAI direction: provider-specific features must be normalized before they become project state.

## Proposed Provider Request Fields

| Field | Purpose |
|---|---|
| `provider` | `mock`, `openai`, `anthropic`, `gemini`, etc. |
| `api_or_feature` | `structured_output`, `tool_call`, `grounding`, `context_cache`, `search`, etc. |
| `model_requested` / `model_resolved` | requested model and resolved model |
| `schema_ref` / `schema_fingerprint` | Pydantic / JSON Schema source of truth |
| `payload_data_class` | server-owned classifier computed from artifact/context; caller/UI/provider supplied values are rejected |
| `context_snapshot_id` | source ContextSnapshot |
| `provider_request_fingerprint` | model / api version / sdk version / schema / policy fingerprint |
| `budget_context` | token / cost / wall-clock limit |
| `tool_manifest_ref` | allowed tool schema set |
| `retry_policy_ref` | retryable status allowlist, attempts, backoff, jitter, timeout, retry budget |
| `idempotency_key` | safe retry correlation for requests that can be retried |

`allowed_data_class` is never part of a trusted provider request input. It is resolved only from `config/provider_compliance.toml` through ADR-00010 rules. If `payload_data_class` is unset, caller-supplied, enum-invalid, or greater than the runtime `effective_allowed_data_class`, the provider call must be denied before sending.

## Proposed Provider Result Fields

| Field | Purpose |
|---|---|
| `status` | success, refusal, incomplete, validation_failed, budget_blocked, policy_blocked |
| `artifact_ref` | generated artifact, never raw provider payload inline |
| `usage` | token / cache / cost metadata |
| `tool_calls` | normalized tool call list |
| `grounding_support` | normalized citation / grounding refs, optional |
| `cache_metadata` | provider cache id/name, ttl, hit count if available |
| `safety_metadata_ref` | redacted safety metadata |
| `error_code` | provider-neutral error enum |
| `retry_observation` | attempts used, terminal status, retryable/non-retryable reason |

## Tool Boundary

Gemini / ADK / MCP samples show a useful model: tools are discovered from schemas and the model asks to call them. TaskManagedAI should adopt the shape, not the direct execution.

Required boundary:

1. Tool schema is registered in `Tool Registry`.
2. Tool schema hash is included in `ContextSnapshot.tool_manifest_hash`.
3. Provider output is parsed as structured tool call.
4. Policy Engine evaluates `action_class`, risk, actor, project, and approval requirement.
5. SecretBroker issues capability token only when needed.
6. Runner / MCP Gateway executes in sandbox.
7. Tool output is stored as artifact and classified as `untrusted_content` until validated.
8. Audit records only metadata, hashes, redacted excerpts, and artifact refs.

## MCP-Specific Rules

| Rule | Reason |
|---|---|
| MCP server allowlist required | arbitrary server execution is equivalent to arbitrary code/tool exposure |
| tool schema hash required | prevents stale approval and schema substitution |
| no regex extraction | tool calls must come from provider tool-call structure or validated JSON schema |
| no raw tool output as instruction | MCP output is `untrusted_content` |
| per-tool risk level | read-only research, repo write, secret access, publish/deploy are different classes |
| approval tied to fingerprint | approval must bind artifact hash, policy version, provider fingerprint, and action class |

## Destination Split

| Layer | What belongs there |
|---|---|
| P0 Tool Registry / Read-only Gateway | local read/search/fetch tool inventory, schema hash, risk class, no remote/network MCP by default |
| SP-014 network policy follow-up | `network_access` enum, `tool_network_policies`, web_fetch/docs_search deny-only until accepted |
| SP-015 Inter-Agent Communication | inter-agent message/tool result trust level, no raw tool output as instruction |
| SP-022 Framework Intake Hardening | external MCP/framework intake checklist, license/telemetry/network/secret/code execution review |

## Rejected Sample Patterns

- `npx` or third-party MCP server execution without allowlist and sandbox.
- CORS `*` unauth Cloud Function.
- raw request/response `print` or UI display.
- provider response directly triggering SQL, command, git, deploy, or MCP execution.
- role name as permission boundary.

## Practical Adoption

For P0, Gemini-specific adapter support should remain narrow:

- structured output path,
- status mapping,
- usage/fingerprint recording,
- compliance preflight,
- deterministic mock parity tests.

The existing `gemini/generate_content` Matrix entry is public-only and supports only narrow adapter experiments. Grounding, context caching, managed search, live API, Memory Bank, Agent Platform Runtime, and code execution should remain gated until their data handling, retention, region, pricing, and audit properties are verified as separate features.

## Provider Reliability Policy

The `sdk/retries/configure_retries.ipynb` sample is useful because it treats retry behavior as configuration, not as ad-hoc caller logic. TaskManagedAI should adopt the same shape in a provider-neutral way.

| Policy element | TaskManagedAI requirement |
|---|---|
| retryable status | explicit allowlist such as 429 / 500 / 502 / 503 / 504; provider-specific mappings normalize to a shared transient enum |
| no-retry status | policy_blocked, validation_failed, approval_required, schema_mismatch, data_class_denied, user_cancelled |
| budget | retries consume token/cost/wall-clock budget and stop before BudgetGuard is violated |
| timeout | per-attempt timeout and total operation deadline are both recorded |
| jitter/backoff | bounded exponential backoff with jitter; no unbounded loops |
| idempotency | retry only when request semantics are safe or an idempotency key is present |
| observability | each attempt records metadata, not raw prompt/response content |

## Managed Feature Gates

| Gemini surface | Default decision | Required TaskManagedAI gate before use |
|---|---|---|
| Code Execution | reject as direct execution | Runner Gateway, sandbox profile, allowed code policy, artifact capture, approval for non-read-only work, Provider Compliance Matrix entry |
| Computer Use | reject as direct browser/action execution | dedicated controlled browser/VM, screenshot/DOM/action artifacts, safety acknowledgement, per-action approval policy, audit trail |
| URL Context | defer | URL allow/deny policy, source snapshot/hash, retrieval metadata, citation verifier, network policy |
| Batch Prediction | defer | async job ledger, input/output artifact refs, deletion/retention policy, cost cap, completion signal |
| Multimodal Live API | defer high-risk | realtime session ADR, short-lived token handling, audio/video retention, live tool-call gate, session audit |
| Model Optimizer | defer | resolved model trace, per-model compliance, cost/quality preference log, eval bake-off evidence |

These surfaces must not be enabled by interpreting `gemini/generate_content` broadly. Each surface changes the threat model and needs its own matrix row and test fixtures.

## Computer Use / Code Execution Artifacts

If a future Sprint chooses to support provider-managed execution or browser actions, the minimum artifact model is:

```json
{
  "feature": "computer_use|code_execution",
  "environment_ref": "sandbox profile or controlled browser profile",
  "input_artifact_ref": "redacted prompt/screenshot/context",
  "action_trace_ref": "normalized code cells or browser actions",
  "output_artifact_ref": "stdout/stderr/screenshot/dom/result",
  "safety_decision": "allowed|required_confirmation|blocked",
  "approval_ref": "nullable approval request id",
  "trust_level": "untrusted_content",
  "audit_event_id": "uuid"
}
```

Tool/browser/code outputs remain untrusted. They cannot be reintroduced into prompts, shell commands, SQL, git, deploy, or external publishing without sanitization and policy evaluation.

## Responsible AI Boundary

The responsible-ai notebooks are useful because they expose both the safety metadata path and examples where superficial protections can be bypassed. The adoption rule is:

- store provider safety ratings as redacted `SafetyMetadataRef`, not as final approval;
- create negative fixtures for prompt injection, RAG injection, tool-output injection, and secret canary leakage;
- reject safety filter disabling as a production pattern;
- do not treat DLP or regex detection as sufficient by itself;
- make `OutputValidator` and Policy Engine decide pass/fail from TaskManagedAI rules.

## Model Routing / Optimizer Boundary

Provider-side model optimization can be useful only after TaskManagedAI can explain what actually ran.

Minimum metadata before use:

- `model_requested`, `model_resolved`, provider router/version, and cost/quality preference;
- compliance result for the resolved model/feature, not just the requested provider;
- eval bake-off evidence for the task class;
- fallback behavior when the provider routes to an unverified model;
- audit event that binds router decision, schema fingerprint, and budget context.
