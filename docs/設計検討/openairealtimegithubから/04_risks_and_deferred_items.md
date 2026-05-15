# 04. Risks And Deferred Items

最終更新: 2026-05-14

## 1. Gate decision

現時点の判定は次です。

- 文書化・設計検討: `PASS`
- P0 への runtime 実装: `BLOCK`
- P0.1 以降の prototype: `WARN` with gates

理由は、Realtime voice / WebRTC / sideband / tool execution / audio retention が、Provider Compliance、SecretBroker、Output Validator、Approval、Budget、Network boundary を同時に拡張するためです。

## 2. Critical risks

### 2.1 Browser-side business logic

リスク:

- browser は untrusted client です。
- sample は demo として browser 側に `RealtimeSession`、tool handling、session event handling が寄っています。

TaskManagedAI での判断:

- product pattern としては reject。
- browser は audio I/O と最小 UI event に限定。
- sideband backend が tool / policy / approval / audit を担当。
- browser-supplied `session.update`、`response.tools`、`function_call_output`、`mcp_approval_response`、tool result、retention/tracing/model/tool config は拒否する。

### 2.2 Unrestricted API proxy

リスク:

- `/api/responses` のような任意 body proxy は、model / tool / schema / store / budget / payload data class / safety settings を client に渡しすぎます。

TaskManagedAI での判断:

- reject。
- operation-specific endpoint / schema / allowlist / ProviderAdapter を通す。
- `store:false` 方針や ZDR/MAM 条件は Provider Matrix で固定。

### 2.3 SecretBroker bypass

リスク:

- demo の `process.env.OPENAI_API_KEY` 直読みは簡単ですが、TaskManagedAI の SecretBroker invariant を弱めます。

TaskManagedAI での判断:

- reject as product implementation.
- standard key は SecretBroker redeem 経由。
- WebRTC session は authenticated backend が unified `/v1/realtime/calls` で作成することを第一候補にする。ephemeral client secret flow を使う場合も authenticated backend endpoint のみが mint する。
- raw key and raw secret-like values are never stored in artifacts, logs, snapshots, approvals, or audit payloads.
- sample event log は session token response をそのまま表示し得るため、TaskManagedAI では token body を UI/event/audit に残さず fingerprint のみ保存する。

### 2.4 Browser-supplied session config

リスク:

- browser が model、tools、instructions、output modality、retention、tracing、MCP config を送れる設計にすると、Provider Matrix、BudgetGuard、Tool/MCP gateway、approval を迂回します。

TaskManagedAI での判断:

- reject。
- backend が AgentRun policy から canonical `RealtimeSessionConfig` を構築する。
- minted client secret は actor/run/origin/provider request fingerprint/max duration/modality/tool policy に bind する。
- browser-originated forbidden config は reject または sideband policy で上書きする。

### 2.5 Audio / transcript retention

リスク:

- 音声には PII、秘密情報、未整理の要件、社外情報が含まれやすい。
- sample は録音と download が demo feature として存在します。
- 「transcript only」を、OpenAI に audio を送らないという意味に誤読しやすい。

TaskManagedAI での判断:

- no P0.
- recording off default。
- TaskManagedAI が永続保存するのは redacted transcript only。live audio は OpenAI Realtime に送信され得るため、音声送信同意、Provider Matrix allowance、retention/deletion policy が必要。

### 2.6 Guardrail fail-open

リスク:

- sample guardrail は classifier 失敗時に `tripwireTriggered: false` を返します。

TaskManagedAI での判断:

- reject。
- validator failure is fail-closed。
- UI state pattern のみ参考にする。

## 3. High risks

### 3.1 Structured artifact contract 未確認

`gpt-realtime-2` は realtime voice、reasoning effort、tool use を support します。ただし current model page だけでは、TaskManagedAI の `ProviderAdapter` が要求する strict structured output schema contract を満たす根拠は確認できません。

TaskManagedAI の ProviderAdapter は structured schema と typed artifact を正本にするため、Realtime model を artifact generator 本体にするのは不適切です。将来この前提を変える場合は、公式 docs 再確認と contract test を ADR gate に入れます。

### 3.2 Realtime MCP tool execution

Realtime MCP tools は Realtime API 側が remote tool を実行できます。これは gateway / audit / approval を TaskManagedAI backend に集約する方針と衝突しやすいです。

当面:

- direct Realtime MCP execution は reject until Tool/MCP gateway accepted。
- public docs など synthetic/public data だけを使う research に限定する。
- read-only であっても、TaskManagedAI gateway が auth、audit、retention、prompt-injection check、approval を仲介できるまで product pattern にはしない。

### 3.3 Budget blow-up

Realtime session では以下が連鎖します。

- audio input/output tokens
- text tokens
- transcription
- supervisor Responses calls
- guardrail calls
- tool calls
- session duration
- parallel sessions

BudgetGuard は token だけでは足りません。audio seconds、session count、parallel cap、kill switch、per-AgentRun attribution が必要です。

最小 cap:

- model allowlist
- audio input/output token cap
- image token cap = 0 until separate review
- max session seconds / idle timeout
- max parallel sessions per actor/project
- supervisor / guardrail / transcription call cap
- per-AgentRun cost attribution
- global kill switch

### 3.4 Network exposure

Realtime WebRTC は browser から OpenAI への media/control path を含みます。Tailscale-only UI でも、OpenAI への egress、Origin、CSRF、WS hijack、rate limit、session binding を別途設計する必要があります。

### 3.5 Endpoint / model drift

サンプルは historical demo code として `/v1/realtime/sessions` と preview model を使います。公式 docs の current path は WebRTC / client secrets / calls / sideband を含むため、TaskManagedAI 実装では sample code を移植しません。

当面:

- implementation ADR 作成時に公式 docs、SDK version、model capabilities、pricing、data controls を再確認する。
- `gpt-realtime-2` が TaskManagedAI の structured artifact contract を満たすか再確認し、満たす証拠と contract test がない限り ProviderAdapter replacement として扱わない。

### 3.6 Realtime tracing residency

OpenAI data controls docs では `/v1/realtime` tracing が EU data residency compliant ではないと説明されています。

当面:

- tracing は separate Provider Matrix row。
- default disabled。
- confidential / PII / Japan/EU residency が絡む payload は、ZDR/MAM、region、trace redaction、trace retention が確認できるまで不可。

## 4. Deferred items

| Item | Status | Resume condition |
|---|---|---|
| Realtime task intake prototype | `defer` | Provider Matrix / SecretBroker / sideband / retention / budget gates complete |
| Voice review session | `defer` | read-only review UI and consent policy complete |
| Realtime MCP direct execution | `reject` | Tool/MCP gateway can mediate auth, audit, retention, prompt-injection checks, approval |
| Realtime MCP public-doc-only research | `defer` | synthetic/public data only, no tenant/repo/credential payload |
| Audio recording | `defer` | consent, TTL, encryption, download permission, deletion policy complete |
| Realtime ProviderAdapter transport | `defer` | need proven latency requirement and separate interaction adapter design |
| Browser direct WebRTC production UI | `defer` | sideband architecture and network gate complete |
| Realtime tracing | `defer` | data residency/ZDR/MAM/trace redaction/retention verified |
| Image/screen realtime input | `defer` | separate Provider Matrix and privacy review complete |

## 4.5 Policy destination before implementation

Realtime の retention / consent / cost は open question のまま implementation に進めません。正式な落とし先は次の通りです。

| Policy area | Destination | Minimum content |
|---|---|---|
| Provider data handling | ADR-00010 update または ADR-00023 data-handling section | `/v1/realtime`、`/v1/realtime/calls`、`/v1/realtime/client_secrets`、transcription、sideband、tracing の Matrix row、ZDR/MAM、region、application state、abuse monitoring retention |
| Audio / transcript retention | ADR-00023 + `docs/基本設計/07_可観測性設計.md` update | raw audio recording 可否、redacted transcript TTL、delete path、download/replay 権限、audit export 可否 |
| Cost / BudgetGuard | SP-010 or SP-011 Eval Harness + BudgetGuard ADR/update | session seconds、audio input/output tokens、transcription usage、`response.done.usage`、parallel sessions、idle timeout、global kill switch |
| Tracing / observability | `docs/基本設計/07_可観測性設計.md` update | Realtime tracing default disabled、trace retention、region/residency constraints、redaction and export policy |

Until these destinations exist and are reviewed, Realtime voice implementation remains `defer`.

## 5. Rejected items

| Item | Reason |
|---|---|
| Copying sample `/api/responses` proxy | bypasses ProviderAdapter, schema, policy, auth, CSRF, budget |
| Client-side mutating tool execution | violates AI output boundary and approval workflow |
| Secret key in browser or exportable artifact | violates SecretBroker |
| Realtime output as direct task/patch/review object | violates structured artifact pipeline |
| Audio recording on by default | privacy and retention risk |
| Handoff as authorization | role and capability must remain separate |
| Guardrail fail-open | incompatible with Output Validator |

## 6. Open questions before implementation

1. Does TaskManagedAI need voice input, or is low-latency text intake enough?
2. Should audio ever be stored, or should only redacted transcript artifacts remain?
3. What payload data class is allowed for Realtime audio/transcript?
4. Is OpenAI project-level ZDR/MAM configured for the intended project?
5. Should Realtime be available only over Tailscale admin UI?
6. What is the maximum session duration and per-run cost cap?
7. Can approval ever be initiated from voice, or only from explicit UI buttons?
8. What minimum audit data is required to reproduce a realtime session without storing raw audio?
9. Does Realtime beat text-only intake or STT -> ProviderAdapter -> TTS on task draft acceptance, correction count, p95 latency, cost/session, and auditability?
10. Should Realtime tracing ever be enabled, and for which payload data class?

## 7. Rollback / kill-switch expectations

If Realtime is later implemented, it needs a simple operational rollback path:

- disable feature flag;
- stop minting realtime client secrets;
- revoke provider capability token;
- deny sideband bridge routes;
- set BudgetGuard realtime cap to zero;
- preserve audit trail and final session summaries;
- delete non-retained audio/transcript data according to retention policy.

Stop triggers:

- ZDR/MAM 未確認。
- payload_data_class 未算出。
- sideband unavailable。
- cost cap / session cap / parallel cap 超過。
- CSRF/origin/session binding failure。
- retention policy 未承認。
- browser supplied forbidden session config。
- direct Realtime MCP requested for tenant/repo/credential data。
- audio/image/screen modality outside allowlist。

Rollback verification:

- feature flag disabled。
- session initialization endpoint denies new `/v1/realtime/calls` creation and new client secrets。
- sideband route denies control channel creation。
- BudgetGuard realtime cap is zero。
- rollback AuditEvent recorded。
- non-retained audio/transcript deleted per approved policy。
