# External AI Concept + UI/UX Report Integration — 統合結論 (2026-05-12)

最終更新: 2026-05-12 (Claude + Codex orchestration、accepted decision として既存計画に反映する目的の design note)

## 1. 背景

ユーザーから 2026-05-12 に、以下 4 つの最新 OpenAI / Anthropic 概念 + 1 つの AI-UIUX レポートを TaskManagedAI に取り入れるべきか分析依頼があった:

### 4 URL (外部新概念)
1. **OpenAI Agents SDK の Skills 機能** (`SKILL.md + scripts/references/assets` + `AGENTS.md` if/then routing)
2. **OpenAI Symphony** (2026-04-27 公開、`github.com/openai/symphony`、Linear ticket → agent → human review、Elixir reference impl)
3. **WebSockets in Responses API** (40% latency 削減、Vercel/Cline/Cursor 採用済)
4. **Claude Managed Agents** (Dreaming + Outcomes + multi-agent orchestration、Research Preview / Public Beta)

### 1 レポート
- `docs/設計検討/AI統合タスク管理プラットフォームの最新UIUXと実装選定レポート.md` (253 行、Asana/ClickUp/Atlassian Rovo/Notion 比較 + OSS catalog + UI 4 面構成 + Plan Mode + 5 層評価)

Claude が単独結論 + Codex (gpt-5.5 deep-review xhigh) で 2 回 orchestration し、本 doc を **採用 / 既導入 / 不要・defer の正本** として固定する。

## 2. Executive Summary (確定)

TaskManagedAI の P0 vision は外部 4 概念 + 業界 UIUX ベストプラクティスに対して **かなり well-positioned**。**pivot 不要、Sprint 5.5 の Output Validator / Input Trust Layer 継続完遂が正解**。

取り入れる:
- **runtime ではなく UX と運用モデル**: Plan Mode、4 面 UI、Approval Queue、Execution Log、業務価値 dashboard、skill packaging 互換設計、Symphony 参照モデル

defer / 拒否:
- LangGraph / CrewAI / Letta / Dapr / WebSocket / Managed Agents / local LLM は **今すぐ本体導入しない**、ADR-00020 の pattern adoption / no code embed / 8 verify を通して段階評価

絶対遵守: AgentRun 16 状態 / ContextSnapshot 10 列 / human-only approval / Provider Compliance / SecretBroker / role ⊥ capability authorization

## 3. 5 軸統合判定 (Codex 確定)

| テーマ | 4 URL 結論 | UIUX レポート示唆 | TaskManagedAI 計画 | **統合判定** |
|---|---|---|---|---|
| Multi-agent orchestration | Symphony pattern 採用、reference impl skip | AI teammate / Plan Mode / 4 面 UI / イベント駆動 + 明示承認 | ADR-00014 (10 標準役職 + role ⊥ capability + human-only approval + lease/failover) | ✅ **既導入十分**。Symphony を ADR-00014 / SP-013 cross-reference 追加のみ |
| Skill packaging | Sprint 6 前後で採用推奨、runtime 丸ごとは defer | Notion skills 的 UX は参考 | `.claude/skills/` 39 個既存 + AGENTS.md | 🟡 **採用 (Sprint 6 前)**。`SKILL.md + scripts/references/assets + metadata routing` 互換設計、light Pack |
| WebSocket / latency optimization | P0 即時導入は defer、ProviderAdapter transport option | n/a | ADR-00013 WebSocket は別文脈、P0 は deny | 🔵 **P0 不採用**。P0 Acceptance 後 metrics で必要性確認 |
| Memory / Dreaming / persistent learning | local pattern として P1 / Wave 19+ | Letta memory-first、長期記憶 | ADR-00016 Hermes memory pattern adoption + memory_retrieval_artifacts 別 table | 🔵 **P1 local-first 採用**。ContextSnapshot 不変、別 table + sanitizer + canary scan |
| UI/UX 4 面構成 + Plan Mode + 業務価値 dashboard | URL 側スコープ外 | **強い示唆**: Board / Task Detail / Approval / Execution Log + approve/edit/reject + tools/citations/diffs/eval scores | P0 UI は Sprint 9 だが Pack 未整備 | 🟡 **採用 (最も不足領域)**。`SP-009_p0_ui_pack` 起票必須、新 status / 新 approval semantics は作らない |
| OSS framework intake (LangGraph / CrewAI / Letta / Dapr) | URL 側スコープ外 | 強い示唆 | ADR-00020 (8 verify + no code embed + persistence 二重化禁止 + telemetry off + tenant boundary) | ❌ **pattern adoption only**。PoC 候補評価は可、product import は ADR-00020 accepted + SP-022 CI が gate |
| Hybrid architecture (cloud LLM + on-prem retrieval) | URL 側スコープ外 | 推奨 | ADR-00021 Tailscale 閉域 + host-portable + Provider Compliance Matrix | ✅ **既導入十分**。P0 は cloud LLM + local DB/retrieval + Tailscale、local LLM は P1 で Matrix 拡張 |
| 5 層評価 + 業務価値メトリクス | URL 側スコープ外 | Unit / Integration / Workflow / Model eval / A/B / Production + 技術 + 業務価値 2 軸 dashboard | Hard Gates 7 + Quality KPIs 5 + Eval Harness | 🟡 **採用 (既存 KPI 接続)**。新 dashboard は DB / audit / AgentRunEvent を source of truth |

凡例: ✅ 既導入 / 🟡 採用 / 🔵 defer / ❌ 拒否

## 4. 即 BLOCK invariant 破壊リスク 5 件 (Codex 整理)

採用時に **絶対犯してはいけない設計ミス**:

1. **agent に権限を渡す** (role ⊥ capability authorization 違反、`docs/adr/00014_multi_agent_orchestration.md` §125-142)
2. **ContextSnapshot に memory を混ぜる** (ADR-00016 で `memory_retrieval_artifacts` 別 table 確定、`.claude/rules/core.md` §9)
3. **Provider Matrix を bypass する** (DD-04 §142-199、Provider Compliance 強制 invariant)
4. **SecretBroker を介さず secret を渡す** (`.claude/rules/secretbroker-boundary.md` §1)
5. **UI 都合で `policy_blocked` / `budget_blocked` / `runtime_blocked` を status enum に増やす** (status は 16 個固定、`blocked_reason` で表現)

## 5. 確定アクションリスト (Priority 順)

### Priority 1: Sprint 5.5 中 (Immediate)

| Action | 成果物 | 影響 invariant | 工数 | Gate |
|---|---|---|---:|---|
| SP-005.5 を継続完了 | Output Validator full pipeline + Input Trust Layer + repair retry + trust_level + payload_data_class 事前算出 | AgentRun 16 状態、ContextSnapshot 10 列、Provider Compliance 13 reason_code、SecretBroker raw secret 非保存 | XL | 既存 ADR-00004/00006/00009/00010 延長、新規 ADR なし |
| 新 runtime 採用禁止 decision を Review に記録 | Sprint 5.5 Review に「LangGraph/CrewAI/WebSocket/Managed SaaS は採用しない」 | P0 sealed guard、tool_mutating_gateway_stub、runner_mutation_gateway | S | light、Review 追記 |
| **本 doc 保存** (この file) | `docs/設計検討/2026-05-12_external_ai_concept_uiux_integration.md` | なし、doc-only | S | light |

### Priority 2: Sprint 6 着手前

| Action | 成果物 | 影響 invariant | 工数 | Gate |
|---|---|---|---:|---|
| Skill packaging boundary 設計 | `ADR-00023_skill_packaging_boundary.md` 候補 (新規) **または** SP-006 の `planned_adr_refs` に「skill packaging は P0 では metadata/artifact 接続のみ、script execution gate は後続」を追加 (どちらか一方を Sprint 6 着手前に必ず実施) | scripts 実行 gate なら Tool / MCP 権限、広範囲 refactor | M | doc-only は light、実行 hook / tool 権限追加なら ADR #5、5+ files なら #9 |
| SP-006 に skill I/O 接続 | CLI artifact `adopt / reject / defer` と skill result artifact を接続 | AI output direct execution 禁止、SecretBroker 非露出 | M | SP-006 の ADR-00003 #3 API/event schema gate |
| **Framework candidate ledger 作成** | `docs/citations/framework_pattern_candidates.md` (LangGraph/CrewAI/Letta/Dapr/AutoGen/Semantic Kernel/Dify/Flowise/OpenHands/TaskingAI の参考 pattern と import 禁止) | ADR-00020 no code embed、persistence 一本化、telemetry off | S-M | dependency 追加なしなら light、import / provider / tool 権限追加なら #4/#5/#10 |

### Priority 3: Sprint 9 UI 着手時

| Action | 成果物 | 影響 invariant | 工数 | Gate |
|---|---|---|---:|---|
| **`SP-009_p0_ui_pack` 起票** | 4 面 UI (Board / Task Detail / Plan Approval / Execution Log) + Plan Mode (approve / edit / reject) | Approval Workflow、AgentRun 16 状態、blocked_reason 3 種 | M-L | read-only UI 中心なら light、edit が新 API/event 作るなら ADR #3/#4 |
| Approval Queue / Execution Log 実装方針 | tools / citations / diffs / eval scores / policy decision / audit refs を同一 timeline で表示 | AuditEvent / AgentRunEvent append-only 正本 | L | 既存 API 利用なら light、timeline API 追加なら #3 |
| 2 軸 dashboard 分離 | 業務価値 (acceptance/cost/cycle/approval) と技術監視 (p95/queue/error は Sprint 11.5 へ) | KPI source-of-truth、Provider usage、audit metrics | M-L | read-only dashboard は light、metric schema 追加なら #3 |

### Priority 4: P0.1 / Sprint 13+

| Action | 成果物 | 影響 invariant | 工数 | Gate |
|---|---|---|---:|---|
| **Symphony cross-reference 追加** | ADR-00014 / SP-013 に Symphony を「参照モデル」として追記 | role ⊥ capability、human-only approval、3 gateway | S | doc-only light、実装変更なし |
| SP-013-016 既存計画通り実施 | project_agent_roles、orchestrator、inter_agent_messages、UI↔CLI parity | DB schema、API/event、AI 権限、Tailscale-only | XL | ADR-00014/15/18/19 accepted 化、#1/#2/#3/#4/#7 |
| SP-017 実ファイル化 | AI Society Visualization / inter-agent timeline / role dashboard | UI/API 契約 | M plan / L impl | UI-only light、API/event 追加なら #3 |
| WebSocket transport 再評価 | ProviderAdapter 内部 option、Provider Matrix 行、budget metric | Provider Compliance、BudgetGuard、external exposure | M | #3/#7/#10、Secret token 扱うなら #6 |

### Priority 5: P1 / Wave 19+ / 商用化後

| Action | 成果物 | 影響 invariant | 工数 | Gate |
|---|---|---|---:|---|
| Hermes / Letta / Dreaming local-first | SP-018 / SP-020、memory_records、memory_retrieval_artifacts、curator、insights | ContextSnapshot 不変、memory raw secret 禁止、tenant/project FK | XL | ADR-00016 + #2/#4/#5 |
| local LLM provider 評価 | Ollama/vLLM/llama.cpp を local provider として Matrix 登録、gateway / RBAC 前段必須 | Provider Compliance、SecretBroker、host-portable | L-XL | #10、外部公開や GPU host 運用なら #7/#6 |
| Managed Agents SaaS 再評価 | Anthropic Managed Agents / OpenAI managed runtime の pricing, ZDR, export, audit, admin 権限を比較 | Provider Matrix、data retention、audit export | L | #4/#6/#7/#10 |
| Dapr durable framework 再評価 | queue / durable workflow が arq 限界を超えた場合だけ比較 | persistence 二重化、telemetry、tenant boundary | L-XL | ADR-00020 + #5/#9 |

## 6. 衝突 / 整合性チェック (Codex 確定)

- **LangGraph / CrewAI 推奨は ADR-00020 と衝突しない**。衝突するのは framework import / code embed / 独自 persistence / telemetry を product code に入れる場合だけ。現時点は pattern adoption と候補 ledger に留める
- **local LLM は Provider Compliance Matrix を通せば整合**。Matrix bypass は衝突。local provider 行は `retention=0d, training_use=no, zdr_eligible=n/a` 相当で開始、confidential 解禁は local-only ADR が必要
- **AI teammate metaphor は ADR-00014 と整合**。ただし「teammate」が権限主体になると衝突。role は metadata / dispatch hint、authorization は capability token + action_class + gateway が正本
- **Plan Mode は既存 Approval Workflow と整合**。`task_write` / `repo_write` は approval、承認後の差分変更は stale invalidation。agent が approval decider になる設計は不可
- **4 面 UI は P0 UI 要件と整合**。ただし UI 都合で status enum を増やすのは不可 (16 個固定)
- **WebSocket は transport 隠蔽なら整合**。public WebSocket / anonymous session / Origin 未検証 / capability token なしは ADR-00013 と衝突
- **dashboard は既存 Hard Gates / Quality KPIs と整合**。frontend event を KPI 正本にする設計は衝突、DB / AgentRunEvent / audit / provider usage を正本にする

## 7. 残リスク / 注意点

1. **UI scope creep**: 4 面 UI + Plan Mode + dashboard は価値が大きいが、Sprint 9 の 6/9 day 枠を超えやすい。P0 は read-only / approval-centered に絞り、bulk action、policy editor、analytics drill-down は P1 に送る
2. **Framework full embed 誘惑**: UIUX レポートの OSS catalog は強いが、TaskManagedAI では ADR-00020 の no code embed が正本。PoC と product code を分ける
3. **Vendor spec drift**: Symphony、Managed Agents、Responses WebSocket は仕様・提供形態・価格・ZDR 条件が変わる。本 doc の source of truth は 2026-05-12 時点の Claude/Codex web search 結果
4. **Local LLM 工数過小評価**: vLLM / llama.cpp はトークン課金を下げても、GPU、監視、モデル更新、RBAC、gateway、eval、incident 対応が増える。P0 には入れない
5. **計画不足 Pack**: `SP-009_p0_ui_pack.md` は本 Phase A で light skeleton 起票済 (実装前に heavy 化 + ADR-00003 起票 + 依存 Pack 実体確認が必要)。`SP-008_github_app_repoproxy` / `SP-010_eval_harness` / `SP-011_5_observability` / `SP-017〜SP-021` の Sprint Pack 実ファイルは未作成、ADR には方向があるが、実装前 gate として Pack 化が必要
6. **invariant 破壊リスク 5 件は即 BLOCK**: §4 参照

## 8. 関連 ADR / Sprint Pack

- ADR-00013 (Codex app-server / Claude Agent SDK extension point)
- ADR-00014 (10 standard role + lease/failover + human-only approval + remote_agent_gateway 連動)
- ADR-00015 (UI/CLI parity)
- ADR-00016 (Hermes memory pattern adoption)
- ADR-00017 (AI Society Visualization)
- ADR-00018 (Inter-agent communication)
- ADR-00019 (Role taxonomy)
- ADR-00020 (Framework intake checklist 8 verify)
- ADR-00021 (Host-portable deployment)
- SP-005-5 (Output Validator、現在進行)
- SP-006 (CLI artifact、Sprint 6)
- SP-009 (P0 UI、本 doc で起票推奨)
- SP-013-022 (P0.1 multi-agent)

## 9. Source of Truth

- 4 URL 採用判定: `~/.claude/local/codex-tasks/2026-05-12/oai-anthropic-4-url-adoption-audit/result.md`
- 全体オーケストレーション結論: `~/.claude/local/codex-tasks/2026-05-12/overall-orchestration-conclusion/result.md`
- UIUX レポート: `docs/設計検討/AI統合タスク管理プラットフォームの最新UIUXと実装選定レポート.md`
- 本 doc: `docs/設計検討/2026-05-12_external_ai_concept_uiux_integration.md` (この file)

## 10. 「明日からどう動くか」

1. **今すぐ**: Sprint 5.5 batch 実装着手 (BL-0064〜0071、Output Validator + Input Trust Layer)。新規 runtime 採用なし
2. **Sprint 5.5 完遂後 → Sprint 6 着手前**: Skill routing 軽量化 light Pack 0.5 day + Framework candidate ledger 0.5 day
3. **Sprint 9 P0 UI 着手時**: 本 doc を Pack 必読資料に追加、UI 4 面 + Plan Mode を design に吸収、scope を read-only / approval-centered に絞る
4. **P0.1 Sprint 13 着手時**: ADR-00014 に Symphony spec cross-reference を 0.5 day で追記
5. **P1 / Wave 19+**: Hermes memory + Outcomes rubric + local LLM + Managed Agents 再評価
