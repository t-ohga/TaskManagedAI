---
id: "ADR-00023"
title: "InteractionGateway: Realtime / Computer Use / Gemini Code Execution 系の P0 runtime BLOCK + Provider Matrix candidate rows (blocked/defer design only)"
status: "proposed"
date: "2026-05-15"
accepted_at: null
authors:
  - "t-ohga"
related_sprints:
  - "SP-009"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-15 (QL-H Quality Loop run で R29 修正まとめ統合計画 §5 QL-H + P-10 + A-13 を ADR として proposed 化)

## 背景

- 決定対象: P0 で **Realtime 系 (OpenAI Realtime API / Anthropic Realtime / Computer Use / Gemini Code Execution direct / Sideband tool execution / Voice consent / 各種 Tracing direct)** の runtime intake を **BLOCK** する境界 (InteractionGateway) を定義する。Provider Matrix candidate rows として **blocked/defer status のみ** で記録し、runtime wiring を明示禁止する。
- 関連 Sprint: 本 ADR は **proposed のみ**、accepted 化は P0.1+ (Realtime prototype gate)。本 ADR は SP-009_p0_ui_pack の編集 (QL-E run) より前に proposed 化されている必要があり、SP-009 で Realtime UI を実装する経路を doc レベルで遮断する。
- 前提 / 制約:
  - **`.claude/CLAUDE.md` §2 #17 invariant 維持**: Realtime MCP direct / browser-supplied session config / voice "OK" approval / Gemini Code Execution direct use / Computer Use / unrestricted `/api/responses` proxy / raw payload logging は reject
  - **ADR Gate Criteria 11 種**: 本 ADR は #3 (API 契約 / event schema)、#5 (MCP / tool 権限)、#6 (Secrets 管理、Realtime session secret)、#10 (Provider 追加 / 切替) を trigger。**break-glass 対象外** (`.claude/rules/sprint-pack-adr-gate.md` §11)
  - **ADR-00010 (Provider Compliance Matrix v2、accepted) との関係**: Realtime 系 8 候補 row を Matrix 候補として記録、ただし全 row が `blocked` または `defer` status のみで admit、`zdr_eligible=conditional` で `condition_status=verified` の場合でも本 ADR の reject 条件が優先される
  - **ADR-00007 (External exposure、proposed) との関係**: Realtime 機能の多くは双方向 streaming session (WebSocket / SSE / WebRTC) を要し、Tailscale Serve / Funnel の外部公開境界に抵触する可能性があるため、本 ADR の Provider Matrix 制約と ADR-00007 の network 制約は両方 enforce
  - **本 ADR scope の制約**: 本 ADR は **blocked/defer design only**、runtime wiring 設計 (実 Adapter / WebSocket session / event stream / SecretBroker realtime token issue) は明示禁止。実装着手は P0.1+ で別 ADR 起票後にのみ進める

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: blocked/defer design only (採用) | Realtime 系 8 候補を Provider Matrix candidate rows として記録、全 row `blocked` or `defer` status のみ。runtime wiring 設計は明示禁止、P0.1+ で別 ADR 起票後 | P0 期間中の Realtime intake を doc レベルで遮断、SP-009 UI 編集時の経路混入を防ぐ。Matrix candidate として将来評価可能 | Realtime 機能の P0.1+ 実装着手が遅れる、SP-009 UI で transcript event-log reference のみ表示 |
| B: runtime wiring proposed | Realtime Adapter / session orchestration / event stream / SecretBroker realtime token issue を proposed として記録 | P0.1+ 実装着手の preparation が前進 | secret raw token / browser-supplied session config / voice consent UI の reject 条件と矛盾、§2 #17 invariant 違反のリスク高 |
| C: 部分 enable (text-only realtime + sideband disable) | text-only baseline + STT chained voice pipeline は enable、sideband tool execution / Computer Use は reject | 一部 Realtime 機能を P0 で実装可能 | text-only baseline と STT chained で十分か比較 fixture (D-01 resume condition) が未完、評価 evidence なしの partial enable は不適切 |
| D: 完全 reject (Matrix candidate rows なし) | 本 ADR を起票せず、Realtime 系を P0 scope 外として明示しない | 起票コストゼロ | Realtime 機能の defer 状態 が doc に残らず、SP-009 編集時に経路混入のリスク、P0.1+ 評価時の Matrix candidate 不在で議論再開コスト高 |

## 採用案

- 採用: **A: blocked/defer design only**。
- 理由:
  - `.claude/CLAUDE.md §2 #17` invariant (Realtime/Gemini direct 不可、voice "OK" approval 不可、raw payload logging 不可) を Provider Matrix candidate rows level で enforce
  - SP-009 UI 編集 (QL-E run) 時に Realtime 機能の経路混入を doc レベルで遮断
  - Matrix candidate として将来評価可能、P0.1+ で別 ADR 起票後の prototype gate で resume condition (D-01: text-only baseline + STT chained voice pipeline 比較 fixture 完成) を satisfy したら個別 row を `defer` → `verified` に昇格可
  - runtime wiring 設計禁止により、本 ADR が「次は accepted」と読まれ実装に進むリスクを fail-closed で防ぐ
- 実装 Sprint: 本 ADR は **proposed のみ**。accepted 化は P0.1+ (Realtime prototype gate)、その時点で別 ADR (ADR-00029 候補? proposed) で runtime wiring 設計を起票してから本 ADR-00023 accepted。
- 実装対象ファイル: **本 run で実装対象 file なし** (doc-only、ADR file 新規起票のみ)。runtime wiring 設計 file (Adapter / session orchestration / event stream / SecretBroker realtime token 等) は本 ADR scope 外。
- 実装ガイダンス: 本 ADR §13 runtime wiring 禁止文言 + Provider Matrix candidate rows 8 行で完結。
- ADR Gate Criteria 該当: #3 (API 契約) + #5 (MCP / tool 権限) + #6 (Secrets 管理) + #10 (Provider 追加 / 切替) の 4 種同時 trigger。

## 却下案

- **B (runtime wiring proposed)**: secret raw token + browser-supplied session config + voice consent UI の reject 条件と矛盾、§2 #17 invariant 違反のリスク高。
- **C (部分 enable)**: text-only baseline と STT chained voice pipeline の比較 fixture (D-01 resume condition) が未完。評価 evidence なしの partial enable は acceptance criteria を満たさない。
- **D (完全 reject、起票なし)**: Realtime defer 状態が doc に残らず、SP-009 編集時に経路混入リスク + P0.1+ 評価時の議論再開コスト高。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| ADR proposed 起票が「次は accepted」と読まれ runtime wiring に進む | 本 ADR §13 runtime wiring 禁止文言 + Matrix candidate rows 全 status `blocked` or `defer` のみ admit | 本 ADR の status は **proposed 維持**、Matrix candidate rows の status 列は CI lint で `blocked` or `defer` 以外を reject (P0.1+ で実装) |
| SP-009 UI 編集時に Realtime 機能 (Sideband / Voice consent / Computer Use 等) の経路混入 | QL-E run で SP-009 must_ship delta を編集する時、本 ADR-00023 candidate rows 8 行を必須 cross-reference | SP-009 acceptance spec に「Realtime 機能の runtime wiring は本 ADR-00023 status=accepted 後にのみ着手」を明記 |
| Provider Matrix candidate rows 8 行で status が `verified` 等に誤昇格 | Provider Compliance Matrix lint test (ADR-00010 §機械判定 invariant) | 本 ADR の 8 候補 row は **`blocked` or `defer` のみ admit**、Matrix lint で `verified` / `partial` 等の status を reject |
| Realtime secret (session token / WebRTC ICE config / voice consent record) が SecretBroker に漏れる | SecretBroker raw secret 非保存 invariant (ADR-00006) | 本 ADR は runtime wiring 禁止のため、Realtime secret issue path も本 ADR scope 外、P0.1+ で別 ADR で SecretBroker integration を設計 |
| `.claude/CLAUDE.md §2 #17` invariant drift | rules level invariant trace + Matrix candidate rows binding | 本 ADR §13 で §2 #17 invariant 8 項目 (Realtime MCP direct / browser-supplied session config / voice "OK" approval / Gemini Code Execution direct / Computer Use / unrestricted `/api/responses` proxy / raw payload logging) を **明示 reject list** として記録 |
| browser-supplied session config が `/v1/realtime/calls` 等で直接受信される | Provider Matrix candidate row `client_secrets` の status=blocked + ADR §13 wording | browser から direct session config を受信する経路は本 ADR で permanent reject、backend sideband + server-mediated secret only |
| voice "OK" を approval として扱う UI | SP-009 UI 編集時の approval flow 設計 cross-reference | voice 認識による approval 判定は §2 #2 invariant (decider human-only、explicit UI approval) と矛盾、本 ADR で permanent reject |
| Gemini Code Execution / Computer Use direct invocation | Tool Registry deny-only + 本 ADR Matrix row reject | mutating tool は P0 deny-only (SP-0045 Tool Registry security boundary)、Computer Use / Gemini Code Execution は本 ADR で permanent reject |

## rollback 手順

### 運用 rollback (Realtime UI / runtime 経路混入の問題発見)

本 ADR は **proposed のみ + runtime wiring 禁止**のため、運用 rollback は基本的に発生しない。ただし、SP-009 UI 編集 (QL-E run) で Realtime UI が誤って実装された場合:

1. SP-009 UI で Realtime 機能関連の route / component を `feature_flag=disabled` で immediate disable
2. Provider Matrix candidate rows 8 行を再確認、全 row が `blocked` or `defer` status であることを verify
3. `.claude/CLAUDE.md §2 #17` invariant trace を再 lint、違反 path があれば immediate revert
4. 本 ADR §13 runtime wiring 禁止文言を Sprint Pack acceptance spec に再 cross-reference

### Migration rollback (本 ADR scope 外)

本 ADR は doc-only、code / schema / migration 変更なし。migration rollback 不要。

### ADR-00023 自体の rollback (proposed → 取下げ)

本 ADR が P0.1+ で accepted 化されず取下げに至った場合 (例: Realtime 機能を完全に P1+ scope 外と決定):

1. `status: rejected` に変更、`superseded_by` に代替 ADR を記録 (例: ADR-00029 候補 Realtime P1+ defer)
2. Provider Matrix candidate rows 8 行を Matrix から削除、または `permanent_reject` status で残す
3. SP-009 UI から Realtime 機能関連の transcript event-log reference 等の placeholder を削除

### Section 13: runtime wiring 禁止文言 (本 ADR の core invariant)

本 ADR が proposed status の間、以下 8 項目の **runtime wiring 設計・実装は permanent reject**:

1. **Realtime MCP direct invocation**: MCP server を Realtime session 内で direct invocation する経路は reject、必ず backend sideband 経由
2. **Browser-supplied session config**: browser から direct に session config (model / system prompt / tool list / temperature 等) を受信する経路は reject、backend server-mediated only
3. **Voice "OK" approval**: voice 認識による approval 判定 (例: "OK" 発声で承認) は §2 #2 invariant (decider human-only、explicit UI approval) と矛盾、permanent reject
4. **Gemini Code Execution direct use**: Gemini API の code_execution tool を direct invocation する経路は reject、必ず Runner sandbox 経由 (SP-007)
5. **Computer Use**: Anthropic Computer Use tool (screen capture / mouse / keyboard) は P0 で permanent reject、P1+ で別 ADR + dedicated sandbox 設計が必要
6. **Unrestricted `/api/responses` proxy**: OpenAI Responses API を unrestricted proxy で公開する経路は reject、必ず Provider Adapter + Compliance Gate 経由
7. **Raw payload logging**: Realtime session の raw payload (audio / transcript / tool call result) を log に保存する経路は reject、redacted summary + structured event のみ
8. **Sideband tool execution without server mediation**: Realtime session 中の sideband tool execution が server (Provider Adapter / Tool Registry) を bypass する経路は reject

本 8 項目は `.claude/CLAUDE.md §2 #17` invariant の延長。本 ADR が proposed → accepted 昇格時も、本 8 項目の reject 条件は **永続的に維持**、accepted 化に伴って解禁する path はない。

## Provider Compliance Matrix candidate rows (8 行、本 ADR で proposed、全 row blocked/defer status のみ admit)

ADR-00010 (Provider Compliance Matrix v2、accepted) と整合する Matrix candidate rows draft。**本 ADR が proposed の間、各 row は `blocked` または `defer` status のみ admit**、`verified` / `partial` 等への昇格は本 ADR accepted 化 + 個別 prototype gate (D-01〜D-05 resume condition) 完了後にのみ可能。

| # | provider | api_or_feature | status | reason | resume_condition |
|---:|---|---|---|---|---|
| 1 | openai | realtime_unified_calls | **blocked** | `.claude/CLAUDE.md §2 #17`: unrestricted Realtime unified calls は reject、browser-supplied session config + server-mediated boundary 両立未完 | text-only baseline + STT chained voice pipeline 比較 fixture 完成 + browser supply 経路の server-mediated 化 (D-01 resume) |
| 2 | openai | realtime_client_secrets | **blocked** | browser-supplied session secret は reject、§2 #17 with browser config invariant 違反 | server-mediated secret issue + SecretBroker realtime token boundary 設計完了 (P0.1+ 別 ADR) |
| 3 | openai | realtime_session_audio | **defer** | voice intake は `.claude/CLAUDE.md §2 #17` voice consent invariant に抵触可能性、P0.1+ で voice consent UI 設計が必要 | voice consent UI + retention policy + ZDR conditional verified 全 satisfy (D-02 resume) |
| 4 | openai | realtime_transcription | **defer** | transcription は session_audio の subset、独立評価が必要 | STT chained voice pipeline 比較 fixture 完成 (D-01 resume の subset) |
| 5 | openai | realtime_sideband_tool_execution | **blocked** | server mediation なしの sideband tool execution は §2 #17 reject、Tool Registry deny-only 経路を bypass | server-mediated sideband + Tool Registry allowlist + SecretBroker capability binding 設計完了 (P0.1+) |
| 6 | openai | realtime_tracing | **defer** | data residency / ZDR / trace retention 未確認 | separate Matrix row + default disabled + ZDR conditional verified (D-04 resume) |
| 7 | openai | responses_supervisor | **defer** | unrestricted `/api/responses` proxy は §2 #17 reject、supervisor role での restricted use は P0.1+ で評価 | Provider Adapter + Compliance Gate 経由の restricted access + role-based audit 設計完了 (P0.1+ 別 ADR) |
| 8 | openai | responses_guardrail | **defer** | unrestricted `/api/responses` proxy は §2 #17 reject、guardrail layer での restricted use は P0.1+ で評価 | supervisor row と同じく restricted access design (P0.1+) |

(同等の Anthropic Realtime / Gemini Live API 等の candidate rows は本 ADR scope 外、provider 別の追加 ADR で記録。本 ADR は OpenAI Realtime / Responses 系を representative として 8 行 draft、他 provider への extension pattern は ADR-00010 の Matrix lint + 個別 row 追加で対応)

## 関連 ADR

- ADR-00010 (Provider Compliance Matrix v2、accepted): 本 ADR の Provider Matrix candidate rows 8 行と整合、`zdr_eligible` / `training_use` / `retention` / `region` / `plan_required` 列の機械判定 invariant を継承
- ADR-00007 (External exposure、proposed): Realtime 機能の double-direction streaming session は本 ADR で blocked、Tailscale Serve / Funnel boundary とも整合
- ADR-00006 (SecretBroker、accepted): Realtime session secret / WebRTC ICE config / voice consent record の boundary、本 ADR runtime wiring 禁止により Realtime secret path は本 ADR scope 外
- ADR-00014 (Multi-Agent Orchestration、proposed): Realtime session を multi-agent context で使う場合、本 ADR と multi-agent role taxonomy の cross-reference が必要 (P0.1+ で別 ADR で議論)
- SP-009_p0_ui_pack (本 ADR で transcript event-log reference のみ表示、runtime wiring 禁止)
- SP-0045_tool_registry (QL-A で proposed 起票済、本 ADR の sideband tool execution reject と整合)

## 関連資料

- `docs/設計検討/修正まとめ統合計画.md §5 QL-H` (R29 plan、本 ADR の source spec)
- `docs/設計検討/修正まとめ統合計画.md §3.1 A-13` (Realtime P0 BLOCK)
- `docs/設計検討/修正まとめ統合計画.md §3.3 D-01〜D-05` (Realtime defer 集合、本 Matrix candidate rows と整合)
- `docs/設計検討/修正まとめ統合計画.md §2 #17` (Realtime/Gemini direct 不可 invariant、本 ADR §13 reject list の根拠)
- `.claude/rules/provider-compliance.md` (Matrix 機械判定 invariant、本 ADR candidate rows と整合)
- `.claude/rules/secretbroker-boundary.md` (Realtime secret boundary、本 ADR runtime wiring 禁止により本 ADR scope 外)
