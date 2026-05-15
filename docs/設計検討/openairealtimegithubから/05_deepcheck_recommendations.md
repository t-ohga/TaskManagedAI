# 05. Deepcheck Recommendations

最終更新: 2026-05-14

## 1. 結論

前回までの大方針、つまり OpenAI Realtime Agents sample を TaskManagedAI に runtime として丸ごと移植せず、低遅延 intake / UI / orchestration pattern として採用する判断は妥当です。

ただし、より良い方向があります。Realtime を `ProviderAdapter` の亜種として考えるより、`InteractionGateway` または `RealtimeInteractionAdapter` という別境界で扱い、TaskManagedAI の既存 `ProviderAdapter` / Output Validator / Approval / Audit / SecretBroker / Remote Agent Gateway の前段に置く方が安全で拡張しやすいです。

最も重要な補正は、将来 topology の第一候補を browser が client secret で直接接続する形ではなく、backend が `/v1/realtime/calls` を作成する unified WebRTC interface + sideband control に寄せることです。TaskManagedAI は backend で canonical session config、Safety Identifier、Actor/AgentRun binding、BudgetGuard、Provider Matrix を固定する必要があるため、この形の方が設計思想に合います。

## 2. 追加で直した点

- `README.md`: 「次の 4 つ」と書きながら 5 項目ある表現を修正。
- `00_source_inventory.md` / `01_reusable_patterns.md` / `03_adoption_plan.md` / `04_risks_and_deferred_items.md`: `gpt-realtime-2` の Structured Outputs について断定しすぎていた表現を修正。現行 model page は realtime voice / reasoning effort / tool use を説明しますが、TaskManagedAI の strict structured output schema contract を満たす根拠までは確認できていません。
- `02_invariant_traceability.md` / `03_adoption_plan.md` / `04_risks_and_deferred_items.md`: Realtime WebRTC の第一候補を unified `/v1/realtime/calls` + backend sideband として明確化。ephemeral client secret flow は代替候補に下げました。

## 3. 根本的な改善案

### 3.1 InteractionGateway を切る

Realtime 導入時は `ProviderAdapter` を増やすのではなく、次の責務を持つ `InteractionGateway` を先に設計するのがよいです。

- browser / voice / realtime / text intake を `untrusted_content` として受ける。
- actor、principal、AgentRun、origin、CSRF/session、Provider Matrix row、BudgetGuard を binding する。
- Realtime session config は backend が canonical に構築し、browser-supplied model/tools/instructions/retention/tracing を受け取らない。
- transcript / event / tool request を TaskManagedAI の AgentRunEvent / artifact pipeline へ正規化する。
- canonical plan / patch / review / evidence artifact は既存 structured `ProviderAdapter` で作る。

これは ADR-00013 の Remote Agent Extension とかなり近いので、別物として孤立させず、remote agent gateway の派生 boundary として扱うのが自然です。

### 3.2 Realtime は Voice Plan Mode から始める

最初の有力ユースケースは「音声で実装を走らせる」ではなく、Voice Plan Mode です。

- タスクの目的、制約、完了条件、検証方法、rollback、承認条件を聞き取る。
- 不足 slot を埋める。
- 最後は structured supervisor が task draft を作る。
- 音声の「OK」は approval ではなく、明示 UI button の承認だけを正にする。

この使い方なら、Realtime の自然会話価値を試しつつ、TaskManagedAI の mutation / approval 境界を崩しません。

### 3.3 先に eval fixture を作る

Realtime prototype の前に、text-only intake と STT -> ProviderAdapter -> TTS と Realtime intake を同じ fixture で比較するべきです。

最低限の評価軸:

- `task_draft_acceptance_rate`
- slot completion rate
- task draft の平均修正回数
- p95 response latency
- cost per task / session
- approval misunderstanding count
- audit replayability
- browser forbidden event violation count

この比較で明確に上回らないなら、Realtime runtime は延期でよいです。

## 4. 採用すべきでないもの

- sample の `/api/responses` proxy。TaskManagedAI の ProviderAdapter、schema、budget、payload data class、auth を迂回します。
- browser-side tool execution / business logic。tool result、`function_call_output`、`mcp_approval_response`、`session.update`、`response.tools` は server-only にするべきです。
- Realtime MCP direct execution。公式 docs 上は可能ですが、Realtime API 自身が remote MCP を実行するため、TaskManagedAI の Tool/MCP gateway、approval、audit、retention を迂回しやすいです。
- audio recording / download on default。録音は別途 consent、TTL、暗号化、download permission、削除 policy が必要です。
- Realtime model を structured `ProviderAdapter` 置換にすること。公式 docs と contract test で strict structured artifact contract が確認できるまでは不可です。

## 5. 推奨ロードマップ

1. P0: Realtime runtime は入れない。Sprint 9 UI では transcript / event log / validation state の表示 pattern だけ取り込む。
2. P0.1 planning: `InteractionGateway` ADR を作る。ADR-00013 の canonical pipeline、capability-class deny、secret redaction、approval binding を流用する。
3. P0.1 prototype 入口: text-only intake baseline と STT -> ProviderAdapter -> TTS fixture を先に作る。
4. Realtime prototype: unified `/v1/realtime/calls` + backend sideband、text output default、no MCP direct、no mutating tools、audio recording off default、private/Tailscale-only、kill switch あり。
5. P1: Tool/MCP gateway が成熟してから read-only Realtime MCP research を再評価する。tenant/repo/credential payload は引き続き禁止。

## 5.5 Review remediation

追加レビューで出た WARN は次のように扱います。

| Finding | Resolution |
|---|---|
| `InteractionGateway` の正式な設計先が弱い | 正名を `InteractionGateway` に固定し、OpenAI Realtime adapter を `RealtimeInteractionAdapter`、transport 実装を `RealtimeSessionBridge` と呼ぶ。P0.1 で `ADR-00023 Interaction Gateway / Realtime Intake` を起票し、ADR-00013 の派生 boundary として扱う |
| eval fixture destination が未確定 | `06_eval_fixture_plan.md` を追加し、将来の実体保存先を `eval/interaction/realtime_intake/`、テスト保存先を `tests/eval/test_realtime_intake_loader.py` とする |
| retention / consent / cost の policy destination が曖昧 | ADR-00010 update または ADR-00023 data-handling section、`docs/基本設計/07_可観測性設計.md` update、BudgetGuard / Eval Harness への分担を `04_risks_and_deferred_items.md` に固定 |
| SP-009 の参照が adoption plan に偏る | SP-009 の関連 Doc に invariant traceability / risks / deepcheck / eval fixture plan を追加 |

## 6. 参照した主な根拠

- OpenAI Realtime Agents sample: `/Users/tohga/sample/openai-realtime-agents`
- TaskManagedAI Provider boundary: `docs/基本設計/01_拡張境界とAdapter設計.md`
- TaskManagedAI orchestration boundary: `docs/基本設計/03_AIオーケストレーション設計.md`
- Remote Agent extension point: `docs/adr/00013_remote_agent_extension.md`
- OpenAI Realtime WebRTC docs: https://developers.openai.com/api/docs/guides/realtime-webrtc
- OpenAI Realtime server-side controls / sideband docs: https://developers.openai.com/api/docs/guides/realtime-server-controls
- OpenAI Realtime MCP/tools docs: https://developers.openai.com/api/docs/guides/realtime-mcp
- OpenAI Realtime costs docs: https://developers.openai.com/api/docs/guides/realtime-costs
- OpenAI data controls docs: https://developers.openai.com/api/docs/guides/your-data
- `gpt-realtime-2` model page: https://developers.openai.com/api/docs/models/gpt-realtime-2
