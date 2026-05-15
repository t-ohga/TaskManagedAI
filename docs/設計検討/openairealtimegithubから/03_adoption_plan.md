# 03. Adoption Plan

最終更新: 2026-05-14

## 1. 推奨方針

OpenAI Realtime Agents sample は、TaskManagedAI の P0 本体にすぐ入れる runtime ではありません。採用順は次のように段階化します。

1. **今すぐ採用するのは design / UI pattern のみ**。
2. **P0 中は structured ProviderAdapter / Output Validator / SecretBroker / Provider Matrix を優先**。
3. **P0.1 以降、sideband 前提の prototype として Realtime intake を検討**。
4. **Realtime MCP / mutating tools / direct browser business logic は後回しまたは拒否**。
5. **Realtime prototype は、text-only baseline と chained voice pipeline を計測で上回る場合だけ進める**。

## 2. Stage 0: 今回の成果

目的:

- サンプルの pattern を TaskManagedAI の文脈で整理する。
- 取り込めるものと取り込まないものを分ける。
- 将来実装前の gate を固定する。

成果物:

- このディレクトリの文書一式。

実装:

- なし。

## 3. Stage 1: Sprint 9 UI で先に取り込めるもの

### Candidate A: AgentRun timeline / event log UI

判定: `adopt`

内容:

- サンプルの transcript + event log UI を参考にする。
- TaskManagedAI では raw realtime event ではなく、AgentRunEvent / AuditEvent / Provider usage / Approval / Policy / Eval を timeline 化する。

価値:

- AI が何を見て、何を判断し、どこで承認待ちになったかを追いやすい。
- 「Deep Research から PR までを証拠・判断・承認・ログ・コスト・レビューとともに管理する」という中核価値に直結する。

注意:

- UI 都合で AgentRun status を増やさない。
- debug payload は redacted-by-default。
- Realtime sample 由来の transcript + event-log pattern は UI reference のみ。raw realtime payload、client secret response body、PII/tool args は表示しない。

### Candidate B: Guardrail / validation state display

判定: `adopt`

内容:

- `IN_PROGRESS` / `PASS` / `FAIL` のような状態表示を、TaskManagedAI の Output Validator / Policy Lint / Approval state に合わせて使う。

価値:

- ユーザーが「AI 出力がまだ検証前なのか、通ったのか、止まったのか」を理解できる。

注意:

- sample guardrail classifier は Output Validator の代替ではない。
- fail-open は不可。
- sample 実装は post-hoc state display pattern として読み、pre-display enforcement としては扱わない。

### Candidate C: Handoff graph visualization

判定: `adopt` as conceptual UI

内容:

- specialist agent handoff を、TaskManagedAI の role transition / reviewer routing / inter-agent timeline の表現に使う。

価値:

- 将来の AI Society Visualization や multi-agent orchestration UI に接続しやすい。

注意:

- role は authorization ではない。
- capability は gateway / policy / approval が正本。

### Sprint 9 UI addendum

対象 Sprint Pack:

- `docs/sprints/SP-009_p0_ui_pack.md`

Owner role:

- `frontend UI`: timeline、validation state、redacted payload 表示。
- `backend event API`: AgentRunEvent / AuditEvent / Approval / Budget event の read API。
- `security-redaction review`: raw payload、secret-like value、provider response、tool args の redaction review。

Acceptance criteria:

- AgentRunEvent / AuditEvent / Approval / Budget / Eval を同一 timeline に表示する。
- raw provider payload、raw realtime payload、client secret response body、secret-like value は redacted-by-default。
- validator state は `pending` / `pass` / `blocked` で見える。
- Playwright E2E または component test で timeline、redaction、validator state を確認する。

## 4. Stage 2: P0.1 prototype 候補

### Candidate D0: Low-latency text intake baseline

判定: `adopt_first`

内容:

- Realtime を使わず、低遅延 text chat / form hybrid で task intake を行う。
- ProviderAdapter / Output Validator / Approval / Audit / Budget を既存 pipeline に乗せる。

目的:

- Realtime の価値を測るための low-risk baseline。
- voice consent、audio retention、browser media path を増やさずに task draft quality を先に測る。

必要 metrics:

- `task_draft_acceptance_rate`
- task draft の平均修正回数
- slot completion rate
- p95 response latency
- cost/task
- approval misunderstanding count

### Candidate D: Realtime task intake

判定: `prototype_later`

内容:

- ユーザーが音声または低遅延チャットで task の目的、制約、検証方法、承認条件を話す。
- Realtime agent は不足情報の収集に限定する。
- supervisor は existing ProviderAdapter / structured schema で task draft を作る。

最小 scope:

- private / Tailscale-only。
- feature flag。
- audio recording off default。
- TaskManagedAI が永続保存するのは redacted transcript only。live audio は OpenAI Realtime に送信され得るため、音声送信同意、Provider Matrix allowance、retention/deletion policy を先に確定する。
- no mutating tools。
- no repo write。
- no external notification。
- text/audio only。image/screen/camera/file input は disabled。
- browser は media transport と bridge-approved user input event のみ。

必要 gate:

- Provider Matrix Realtime rows.
- SecretBroker-mediated client secret minting.
- Prefer backend-created unified `/v1/realtime/calls`; use client secret minting only as a secondary topology when token exposure and config binding are acceptable.
- Sideband server control.
- Output Validator fail-closed.
- data retention / consent policy.
- budget cap and kill switch.
- Alternative ROI gate: text-only baseline と STT -> ProviderAdapter -> TTS を、task quality / latency / cost / consent burden / auditability で上回る。

### Candidate E: Realtime review session

判定: `prototype_later`

内容:

- 生成された plan / diff / review result について、ユーザーが音声で質問し、AI が artifact を引用しながら回答する。

価値:

- 承認前の説明責任が上がる。
- 長い plan / review の理解負荷を下げる。

制約:

- 回答は read-only。
- 承認操作は通常 UI の explicit action。
- 音声での「OK」は approval decision として扱わない。
- audio output は default disabled。必要性と cost/privacy を別途評価する。

### Prototype admission benchmark

Realtime prototype に進む前に、同じ task-intake fixture で 3 案を比較します。

| Option | Must measure | Stop condition |
|---|---|---|
| Text-only low-latency intake | `task_draft_acceptance_rate`, 修正回数, p95 latency, cost/task | これで十分なら Realtime は延期 |
| STT -> ProviderAdapter -> TTS | voice UX、audit replayability、latency、cost/session、consent burden | Realtime 優位がなければ chained pipeline を優先 |
| Realtime sideband intake | 上記すべて + sideband reliability + browser event violation count | approval misunderstanding が 1 件でも出る、または cost cap 超過なら stop |

## 5. Stage 3: P0.1 multi-agent 以降

### Candidate F: Sequential handoff as orchestration metadata

判定: `prototype_later`

内容:

- Researcher / Planner / Reviewer / Implementer / Verifier などの role transition を graph として保存・表示する。
- handoff は event metadata として扱い、capability とは分離する。

必要 gate:

- ADR-00014 / ADR-00018 / role taxonomy の accepted 化。
- inter_agent_messages / AgentRunEvent contract。
- role-to-capability non-equivalence の contract test。

### Candidate G: Sideband bridge

判定: `prototype_later`

内容:

- browser WebRTC session と backend sideband control を組み合わせる。
- backend が tool response / instruction update / policy decision / audit を担当する。
- browser SDP は backend に送り、backend が canonical session config と合わせて `/v1/realtime/calls` を作る unified interface を第一候補にする。

必要 gate:

- `ADR-00023 Interaction Gateway / Realtime Intake` proposed 起票。`InteractionGateway` を domain boundary、`RealtimeInteractionAdapter` を OpenAI Realtime adapter、`RealtimeSessionBridge` を transport 実装名として使う。
- ADR-00013 Remote Agent Extension の canonical pipeline、capability-class deny、SecretBroker redaction、Approval Workflow binding との crosswalk。
- authenticated TaskManagedAI session。
- Origin allowlist。
- CSRF / WS hijack protection。
- per-AgentRun short-lived capability token。
- rate limit。
- audit event。
- SecretBroker integration。
- backend が AgentRun policy から canonical `RealtimeSessionConfig` を構築し、browser-supplied model/tools/instructions/output_modalities/retention/tracing を拒否する。
- call id または minted client secret は actor/run/origin/provider_request_fingerprint/max_duration/modality/tool policy に bind する。
- 実装時は sample の `/v1/realtime/sessions` コードではなく、current official WebRTC / `/v1/realtime/calls` / client_secrets / sideband docs から再設計する。

## 6. Stage 4: P1 以降に再評価

### Candidate H: Realtime MCP read-only connector

判定: `reject_direct` / `research_only`

内容:

- Realtime API から remote MCP tool を使う可能性を検討する。

P1 まで待つ理由:

- Realtime MCP は OpenAI 側が tool execution を行うため、TaskManagedAI gateway / audit / approval と衝突しやすい。
- remote MCP server の data retention / auth / logging が別 provider boundary になる。
- MCP output が prompt-injection surface になり、TaskManagedAI の Input Trust Layer を通す必要がある。

採用可能性:

- direct Realtime MCP execution は、TaskManagedAI Tool/MCP gateway が auth、audit、retention、prompt-injection check、approval を仲介できるまで product では不可。
- public docs など synthetic/public data だけを使う research は可能。
- read-only connector でも tool allowlist、one-response-only、no tenant/repo/credential payload、strict approval for any external side effect が必要。

### Candidate I: Realtime ProviderAdapter transport option

判定: `defer`

内容:

- ProviderAdapter とは別に、低遅延 streaming / realtime transport を扱う adapter を検討する。

注意:

- `gpt-realtime-2` の current model page は realtime voice、reasoning effort、tool use を説明しているが、TaskManagedAI の strict structured output schema contract を満たす根拠は確認できていないため、canonical structured artifact 生成には使わない。
- 使う場合は interaction adapter / session bridge として分離する。

## 7. 推奨 backlog

| Priority | Item | Type | Gate |
|---:|---|---|---|
| 1 | Sprint 9 UI timeline に transcript/event-log pattern を反映 | UI design | no Realtime runtime needed |
| 2 | Output Validator state display を UI design に反映 | UI design | Output Validator existing gates |
| 3 | Low-latency text intake baseline | prototype plan | existing ProviderAdapter / Output Validator |
| 4 | Chained STT -> ProviderAdapter -> TTS comparison plan | design only | voice value hypothesis |
| 5 | `ADR-00023 Interaction Gateway / Realtime Intake` draft | ADR | ADR-00013 crosswalk / Provider Matrix / SecretBroker / network / data retention |
| 6 | `openai/realtime` Provider Matrix candidate rows | design only | official docs re-verify |
| 7 | Realtime intake eval fixture plan | eval design | `eval/interaction/realtime_intake/` / SP-010 or SP-011 Eval Harness |
| 8 | Sideband bridge architecture note | design only | ADR-00013 alignment |
| 9 | Realtime task intake prototype plan | prototype plan | P0.1 only + ROI gate |
| 10 | Voice consent / retention / cost policy | policy design | ADR-00010 update or ADR-00023 data handling section before any audio |
| 11 | Realtime MCP public-doc-only research | research | P1 / Tool gateway |

## 8. 直近でやらないこと

- Product code への `@openai/agents` 追加。
- frontend に Realtime WebRTC UI を入れる。
- `/api/responses` proxy を増やす。
- `config/provider_compliance.toml` へ未検証 row を追加する。
- audio recording を入れる。
- Realtime MCP tools を有効化する。
- Realtime model を ProviderAdapter の代替にする。
- browser から `session.update` / `response.tools` / `function_call_output` / `mcp_approval_response` を受け付ける。
