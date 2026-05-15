# 00. Source Inventory

最終更新: 2026-05-14

## 1. 調査範囲

この文書は `/Users/tohga/sample/openai-realtime-agents` を調査し、TaskManagedAI に取り込める可能性がある設計 pattern と、取り込むべきでない demo 実装を分離するための inventory です。

今回は **実装しない** 方針のため、TaskManagedAI の backend / frontend / config / tests は変更していません。

## 2. サンプル repository の状態

- local path: `/Users/tohga/sample/openai-realtime-agents`
- commit: `94c9e91 security update (#124)`
- remote: `org-14957082@github.com:openai/openai-realtime-agents.git`
- app: Next.js + TypeScript
- package highlights:
  - `@openai/agents`: `^0.0.5`
  - `openai`: `^4.77.3`
  - `next`: `^15.3.1`
  - `react`: `^19.0.0`
  - `zod`: `^3.24.1`

## 3. サンプルが示す主な pattern

### Chat-Supervisor

README では、Realtime の chat agent が会話・簡単な情報収集を担当し、より強い text supervisor model が tool call と複雑な回答を担当する pattern と説明されています。

実装上は、`src/app/agentConfigs/chatSupervisor/index.ts` の `chatAgent` が `getNextResponseFromSupervisor` tool だけを直接呼べる junior agent として定義されています。`src/app/agentConfigs/chatSupervisor/supervisorAgent.ts` では、conversation history を `/api/responses` に送り、`gpt-4.1` supervisor が tool call と最終回答を行います。

TaskManagedAI への示唆:

- Realtime を「構造化 artifact 生成の本体」にせず、低遅延の intake / clarification UI として使える。
- supervisor 側は既存の `OpenAIResponsesAdapter` や Output Validator pipeline に寄せられる。
- ユーザー体験としては即時応答しつつ、難しい判断だけ高品質 model / structured workflow に送れる。

### Sequential Handoff

README では、specialized realtime agents を明示的な graph でつなぎ、intent に応じて handoff する pattern と説明されています。

実装上は、`src/app/agentConfigs/customerServiceRetail/index.ts` が authentication / returns / sales / simulatedHuman の handoff graph を構築しています。`returns.ts` では高リスク判断として `o4-mini` に escalation する例もあります。

TaskManagedAI への示唆:

- role 分割、handoff graph、specialist 表現は、将来の multi-agent UI / AI Society Visualization / inter-agent timeline の参考になる。
- ただし handoff は authorization ではない。TaskManagedAI では role と capability を分離し、human approval と gateway が正本になる。

### Output Guardrails

`src/app/agentConfigs/guardrails.ts` は `/api/responses` で guardrail classifier を呼び、moderation category を返します。README と実装から見るべき点は、pre-display enforcement ではなく、demo UI の post-hoc validation state display pattern です。transcript item が後から `PASS` / `FAIL` へ更新され、classifier failure は `tripwireTriggered: false` として扱われ得ます。

TaskManagedAI への示唆:

- UI 上で `IN_PROGRESS` / `PASS` / `FAIL` のように validation state を見せる pattern は有用。
- ただし classifier 失敗時に fail-open する実装は TaskManagedAI の Output Validator とは相容れない。TaskManagedAI では validator failure は fail-closed で扱う。

### Transcript + Event Log

README では、左側に transcript、右側に client/server event log、下部に VAD/PTT/audio/log 操作がある UI と説明されています。

TaskManagedAI への示唆:

- AgentRunEvent / AuditEvent / Approval / cost / policy decision / tool result を同一 timeline で見せる UI の reference として有用。
- ただし raw payload や PII/tool args を debug pane に出す場合は、redaction と権限が必須。

## 4. サンプル実装でそのまま取り込まないもの

### Client-side business logic / tool handling

`useRealtimeSession.ts` は browser で `RealtimeSession` を作り、`sendEvent` や push-to-talk event を直接送ります。demo としては妥当ですが、TaskManagedAI では tool execution、policy decision、approval、audit、session update は server-side control に寄せる必要があります。

### Unrestricted Responses proxy

`src/app/api/responses/route.ts` は request body をほぼそのまま `openai.responses.create` / `parse` に渡します。TaskManagedAI では operation-specific schema、model/param allowlist、budget、auth、CSRF、rate limit、Provider Compliance Gate を挟まない proxy は不可です。

### SecretBroker bypass

`src/app/api/session/route.ts` は `process.env.OPENAI_API_KEY` を使って realtime session を作ります。TaskManagedAI では SecretBroker capability token から provider credential を memory-only で redeem し、raw key を artifact / log / snapshot / approval / audit に出さない方針です。

### Debug event log token exposure

`src/app/App.tsx` は session token 取得時の response を `logServerEvent(data, "fetch_session_token_response")` に渡します。demo では便利ですが、response に `client_secret.value` が含まれる場合、UI event log / debug pane に ephemeral client secret が表示され得ます。

TaskManagedAI では、client secret response body を event / log / UI / audit / ContextSnapshot に保存しません。保存できるのは provider request fingerprint、mint operation id、actor/run binding、redacted summary だけです。

### Historical endpoint / model drift

サンプルの `src/app/api/session/route.ts` は `/v1/realtime/sessions` と `gpt-4o-realtime-preview-2025-06-03` を使います。一方、2026-05-14 時点の公式 docs では browser WebRTC path に `/v1/realtime/client_secrets` の ephemeral key flow、unified interface に `/v1/realtime/calls`、server-side controls に sideband connection が説明されています。

そのため、transport / session creation code は historical demo reference only とします。TaskManagedAI 実装時はサンプルコードを移植せず、current official WebRTC / client_secrets / calls / sideband docs から再設計します。

### Automatic recording and local download

`src/app/App.tsx` と `src/app/hooks/useAudioDownload.ts` には、接続時に remote audio + microphone audio を録音し、WAV download できる demo 機能があります。TaskManagedAI では録音 off default、明示同意、保存禁止または暗号化、TTL、download 権限、監査イベントが必要です。

## 5. 公式 OpenAI docs の現在値

確認日: 2026-05-14

- Voice agents: https://developers.openai.com/api/docs/guides/voice-agents
- Realtime WebRTC: https://developers.openai.com/api/docs/guides/realtime-webrtc
- Realtime WebSocket: https://developers.openai.com/api/docs/guides/realtime-websocket
- Server-side controls / sideband: https://developers.openai.com/api/docs/guides/realtime-server-controls
- Realtime MCP/tools: https://developers.openai.com/api/docs/guides/realtime-mcp
- Data controls: https://developers.openai.com/api/docs/guides/your-data
- `gpt-realtime`: https://developers.openai.com/api/docs/models/gpt-realtime
- `gpt-realtime-mini`: https://developers.openai.com/api/docs/models/gpt-realtime-mini

現在の公式 docs では、browser voice agent の代表経路は `RealtimeAgent` / `RealtimeSession` と WebRTC です。WebRTC 初期化には、developer-controlled backend が `/v1/realtime/calls` を作成する unified interface と、backend が `/v1/realtime/client_secrets` で ephemeral key / client secret を mint して browser が `/v1/realtime/calls` に接続する経路があります。TaskManagedAI では policy / audit / session config を backend で固定しやすい unified interface を第一候補にし、client secret flow は代替候補として扱います。standard API key は server-side のみに置き、`OpenAI-Safety-Identifier` は trusted backend で付与します。

また、公式 docs は tool use や business logic を server-side に残すための sideband control channel を説明しています。これは TaskManagedAI の境界設計と相性がよいです。

Realtime MCP/tools docs は、MCP tool が Realtime API 自身によって実行されることを説明しています。これは便利な一方、TaskManagedAI の Tool/MCP gateway、approval、audit、retention、prompt-injection check を迂回し得るため、直接採用しません。

重要な制約として、公式 Realtime model (`gpt-realtime` / `gpt-realtime-mini`) page は realtime voice、reasoning effort、tool use を説明していますが、TaskManagedAI の `ProviderAdapter` が必須にする strict structured output schema contract を満たす根拠はこの調査時点では確認できませんでした。したがって、Realtime model を canonical artifact 生成の本体や `ProviderAdapter` 置換にするのは不適切です。将来採用する場合も、current docs と contract test で structured artifact 生成の保証を確認してから別 ADR で扱います。

## 6. TaskManagedAI 側の前提

確認した主なファイル:

- `docs/基本設計/01_拡張境界とAdapter設計.md`
- `docs/基本設計/03_AIオーケストレーション設計.md`
- `config/provider_compliance.toml`
- `backend/app/domain/provider/request.py`
- `backend/app/services/providers/openai_responses.py`
- `docs/adr/00013_remote_agent_extension.md`
- `docs/設計検討/2026-05-12_external_ai_concept_uiux_integration.md`

重要な前提:

- ProviderAdapter は structured schema を受け取り、provider-specific response を artifact と AgentRun status に正規化する。
- AI output direct execution は禁止。
- AgentRun status は 16 個固定。
- `blocked` の理由は `blocked_reason` で表現し、status enum を増やさない。
- SecretBroker は raw secret 非露出の境界。
- Provider Compliance Matrix は provider / feature / payload data class を必ず判定する。
- 現在 Matrix には `openai/responses` はあるが、`openai/realtime` や `openai/realtime_client_secrets` はない。
