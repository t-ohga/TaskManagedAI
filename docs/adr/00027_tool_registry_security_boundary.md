---
id: "ADR-00027"
title: "Tool Registry Security Boundary"
status: "proposed"
created_at: "2026-05-15"
updated_at: "2026-05-15"
decision_target: "Tool Registry (`config/tool_registry.toml` + Pydantic loader + ContextSnapshot.tool_manifest 統合) の security boundary 定義"
sprint_ref:
  - "SP-0045_tool_registry"
adr_gate_criteria:
  - "#3 (API 契約 / event schema): registry loader API、`registry_decision` AgentRunEvent、`tool_payload_data_class_unset` / `tool_payload_data_class_exceeded` / `tool_registry_unavailable` audit reason_code"
  - "#5 (MCP / tool 権限): `allowed_actions` enum 4 種、`trust_tier` enum 4 種 (DD-02 同期、provenance のみ)、`max_outgoing_data_class` enum 4 種、`tool_mutating_gateway_stub` deny-only 維持"
co_accepted_with:
  - "SP-0045_tool_registry (本 Pack accepted 化と co-accepted)"
related_adrs:
  - "ADR-00012 (Hook Trust Boundary、proposed、Phase 5 prerequisite)"
  - "ADR-00013 (Remote Agent Extension Point、proposed、external MCP server boundary)"
  - "ADR-00002 (Core Data Model、proposed、ContextSnapshot 10 列 + DD-02 tool_registry trust_tier 4 種 既存定義)"
  - "ADR-00003 (AI Orchestration、proposed、AgentRunEvent event_type 31 → +N 拡張時の 5+ source 整合)"
---

最終更新: 2026-05-15

# ADR-00027: Tool Registry Security Boundary

## 1. 背景

Tool Registry は P0 / P0.1 で扱う MCP / external tool / local stdio tool を機械可読 registry で一元管理し、`allowed_actions` / `trust_tier` / `max_outgoing_data_class` の boundary を不変条件として強制する。SP-0045 (Tool Registry Sprint Pack) は本 ADR を **primary owner** として参照する。

修正まとめ統合計画 R29 §3.5.4 で `create_required = 1 件 (SP-0045)` が確定、R30 (QL-A run) で本 ADR が proposed 起票必須と確定 (R2 P2R2 F-P2R2-002 反映)。

## 2. 決定対象

1. `tool_registry.toml` schema の **primary owner** (SP-005-5 Output Validator とは独立 security boundary)
2. `trust_tier` enum の **semantic 固定**: provenance (どの組織が tool を提供したか) vs effective risk gate
3. `allowed_actions` enum 4 種の **action_class 7 種 + read/search 系混入禁止 invariant**
4. `max_outgoing_data_class` enum 4 種の **canonical data-class boundary** 化
5. `tool_manifest` server-owned invariant (ContextSnapshot 10 列に新規列追加なし、内部 tuple 保存)
6. registry 起動前 fail-closed (load 失敗時の `tool_registry_unavailable` deny)
7. tool → runner artifact 経路の registry_decision event + tool_manifest hash binding
8. audit reason_code 3 種 (`tool_payload_data_class_unset` / `tool_payload_data_class_exceeded` / `tool_registry_unavailable`)

## 3. 関連 Sprint / 前提

- SP-0045 (本 Sprint Pack、QL-A R30 で新規起票)
- SP-005-5 Output Validator (functional-near reuse / alias 禁止、security boundary 独立 invariant)
- SP-007 Runner Sandbox (`runner_mutation_gateway` は別 boundary、Tool Registry は authorization layer)
- Sprint 5+ で `config/tool_registry.toml` Pydantic loader 実装着手

## 4. 前提 / 制約

- DD-02 (`docs/基本設計/02_データモデル.md:515-524`) の既存 `tool_registry.trust_tier` DB CHECK = `('official', 'self_hosted', 'third_party', 'experimental')` を **canonical** とする (TOML/DB 二正本禁止)
- 不変条件 #1 (AI 出力直結禁止) / #2 (deny-by-default) / #7 (用語不変) / #8 (ContextSnapshot 10 列) / #13 (server-owned boundary) / #17 (role ⊥ capability authorization) / #18 (SP-005-5 alias 不可) を遵守
- 本 ADR は SP-0045 と **co-accepted** が原則: SP-0045 accepted 化条件 = ADR-00027 status=accepted (または同一 PR で co-accepted)
- ADR-00027 が rejected / superseded / 未 accepted のいずれかに戻る場合、SP-0045 status を **`blocked`** へ戻し、SP0045-T01〜T05 / BL-0157 着手禁止

## 5. 選択肢

### 選択肢 A: `trust_tier` を provenance 固定 + `max_outgoing_data_class` per row が data-class 正本 (採用)

- `trust_tier` 4 種は **どの組織が tool を提供したか** の metadata
- データ送信上限は **`max_outgoing_data_class` per row** (`public` / `internal` / `confidential` / `pii` ordinal 比較)
- server-resolved policy で combined evaluation (registry entry が `experimental` tier かつ `max_outgoing_data_class >= confidential` を許可するには本 ADR update 必須)
- payload classification 未設定時は classification 前に deny (Provider Compliance Matrix §6 と fail-closed pattern)

### 選択肢 B: `effective_tool_risk` 別 field を導入

- `trust_tier` を provenance、`effective_tool_risk` を data-class gate に分離
- DB schema 変更必須 (DD-02 拡張)、本 PR scope (doc-only) を超える
- 実装 complexity 増

## 6. 採用案: 選択肢 A

選択肢 A を採用。理由:

- DD-02 既存 enum (provenance) を尊重 → 二正本禁止
- `max_outgoing_data_class` は既に Provider Compliance Matrix と同じ ordinal pattern、追加 enum 不要
- `trust_tier` の semantic を **provenance に固定** することで、F-P2R2-006 で発見した「`official` が直接 data-class 許可を意味する」drift を防ぐ
- ADR-00027 update で registry entry の `max_outgoing_data_class` 上限変更を **明示 ADR Gate** に通せる

## 7. 却下案: 選択肢 B (`effective_tool_risk` 別 field)

却下理由:

- DD-02 拡張 = ADR Gate Criteria #2 (DB schema) 該当、追加 ADR run 必須
- 実装 complexity 増、P0 scope に乗らない
- 選択肢 A で `max_outgoing_data_class` を canonical data-class boundary にすれば semantic 分離可能

## 8. リスク

- **provenance と effective risk の semantic mismatch**: 実装者が `trust_tier=official` を「無条件信頼」と誤解する経路 → SP-0045 受け入れ条件 + 本 ADR §6 で「`trust_tier` が data-class 許可を意味しない」を明文化
- **caller-supplied `tool_manifest` 経路**: server 再計算 invariant を signature レベルで削除 (server-owned-boundary §2)
- **registry 起動順 race**: `tool_registry.toml` load 失敗時の全 tool call deny を `tool_registry_unavailable` reason で audit
- **DD-02 既存 enum と TOML 二正本化**: SP-0045 accepted 化前に exact-set verify、drift PR は同期 merge

## 9. rollback 手順

- 本 ADR を `rejected` または `superseded` にする場合、SP-0045 status を **`blocked`** へ戻す (逆連動、F-P2R2-008 反映)
- SP-0045 status=blocked により SP0045-T01〜T05 / BL-0157 着手禁止
- `config/tool_registry.toml` schema が未実装の state でのみ rollback 可能
- 実装 Sprint 着手後 (Sprint 5+) の rollback は **ADR Gate Criteria #8 破壊的操作** 該当、別 ADR で扱う

## 10. enum source manifest (5+ source 整合、cross-source-enum-integrity §1 準拠)

| enum | source 1: Pydantic | source 2: Python Literal | source 3: pytest EXPECTED | source 4: docs | source 5: DD-02 / DB CHECK | source 6 (P0.1+): frontend TS |
|---|---|---|---|---|---|---|
| `allowed_actions` (4 種: `web_fetch` / `docs_search` / `code_grep` / `filesystem_read`) | `backend/app/services/tool_registry/schemas.py` (P0.1+ 実装 Sprint) | `tool_registry/enums.py` | `tests/services/tool_registry/test_allowed_actions_enum_integrity.py` | SP-0045 + ADR-00027 | (P0.1+ で `tool_registry` DB table 化時に DB CHECK) | `frontend/lib/domain/tool-registry.ts` (P0.1+) |
| `trust_tier` (4 種: `official` / `self_hosted` / `third_party` / `experimental`) | 同上 (`schemas.py`) | 同上 (`enums.py`) | `test_trust_tier_enum_integrity.py` + `test_provenance_trust_tier_server_owned.py` | SP-0045 + ADR-00027 + DD-02 §tool_registry | **DD-02 `tool_registry.trust_tier` DB CHECK = `('official', 'self_hosted', 'third_party', 'experimental')` (canonical、既存)** | 同上 (P0.1+) |
| `max_outgoing_data_class` (4 種: `public` / `internal` / `confidential` / `pii`) | 同上 | 同上 | `test_max_outgoing_data_class_enum_integrity.py` + `test_experimental_max_outgoing_data_class_deny.py` | SP-0045 + ADR-00027 | (Provider Compliance Matrix と同 ordinal、独立 boundary) | 同上 (P0.1+) |

## 11. server-owned boundary checklist (server-owned-boundary §1-§2 準拠)

- [ ] `trust_tier` は server が registry TOML から resolve、API endpoint Pydantic schema / service layer signature / ORM の 3 layer で caller-supplied reject
- [ ] `tool_manifest` ContextSnapshot 列の `(registry_version, sha256(tool_allowlist))` tuple は **server が再計算**、API endpoint で caller-supplied tool_manifest を受け取らない (signature レベル物理削除)
- [ ] `payload_data_class` は request / artifact metadata から事前算出、Tool call 入口で classification 未設定 / invalid / pending を `tool_payload_data_class_unset` deny
- [ ] registry version 更新時の既存 AgentRun は **immutable** で保存 (snapshot は run 開始時固定)
- [ ] tool-originated artifact が `runner_mutation_gateway` に渡る場合、`registry_decision` AgentRunEvent + tool_manifest hash binding が記録されていなければ runner 側も deny (4 quadrant: tool allow + runner allow / tool allow + runner deny / tool deny + runner deny / **tool-originated direct → runner deny**)

## 12. ADR Gate Criteria 該当 section

### Criteria #3 (API 契約 / event schema)

- 新規 audit reason_code 3 種 (`tool_payload_data_class_unset` / `tool_payload_data_class_exceeded` / `tool_registry_unavailable`) を `agent_run_events` table の payload に追加
- 新規 AgentRunEvent event_type `registry_decision` を 5+ source manifest で整合 (Pydantic + Literal + pytest + frontend + DB CHECK、agent_run_event_types §6.1 で event_type count 拡張時に同期)
- `registry_decision` event payload schema: `(tool_name, allowed_actions, trust_tier, max_outgoing_data_class, payload_data_class, decision, reason_code, registry_version, tool_manifest_hash)`

### Criteria #5 (MCP / tool 権限)

- `allowed_actions` 4 種 (`web_fetch` / `docs_search` / `code_grep` / `filesystem_read`) + P0 deny 3 種 (`tool_write` / `repo_write` / `command_exec`) は **action_class 7 種 enum と物理分離** (action_class enum に追加禁止)
- `tool_mutating_gateway_stub` の deny-only invariant 維持 (P0 mutating tool call は全 deny + audit)
- external MCP server 追加 path は P0.1 別 ADR で扱う (ADR-00013 reference)

## 13. 関連メモ

- 本 ADR は QL-A R30 で proposed 起票 (R2 P2R2 F-P2R2-002 反映)
- SP-0045 (Tool Registry Sprint Pack) と co-accepted が原則
- 採用案 A は F-P2R2-006 (trust_tier semantic mismatch) を解消
- enum source manifest は F-P2R1-003 (TOML/DB 二正本) を解消
- server-owned boundary checklist は F-P2R1-005 (caller-supplied tool_manifest) と F-P2R2-005 (caller-supplied lineage hash chain) を解消
- 本 ADR が rejected / superseded で SP-0045 を blocked へ戻す逆連動は F-P2R2-008 反映
