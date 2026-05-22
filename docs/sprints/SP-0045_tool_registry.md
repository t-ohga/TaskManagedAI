---
id: "SP-0045_tool_registry"
type: "heavy"
status: "ready"
sprint_no: 4.5
created_at: "2026-05-15"
updated_at: "2026-05-22"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00027](../adr/00027_tool_registry_security_boundary.md) (accepted、primary owner、SP-0045 batch A で co-accepted)"
  - "[ADR-00012](../adr/00012_hook_trust_boundary.md) (accepted、Hook Trust Boundary、SP-0045 Tool Registry の trust_tier server-resolved invariant prerequisite)"
planned_adr_refs:
  - "[ADR-00013](../adr/00013_remote_agent_extension.md) (proposed、Remote Agent Extension Point、Tool Registry の external MCP server boundary 参照)"
related_sprints:
  - "SP-005-5_output_validator (Output Validator core、Tool Registry とは独立 security boundary)"
  - "SP-007_runner_sandbox (runner_mutation_gateway、Tool Registry とは別 boundary)"
  - "SP-004_agent_runtime (ContextSnapshot.tool_manifest hash の registry source)"
risks:
  - "Tool Registry の allowed_actions enum drift (read/search を action_class 7 種に混入させる事故、R29 §3 D-003)"
  - "Tool Registry が tool_mutating_gateway_stub の deny-only invariant を侵犯 (mutating tool を allowed_actions に追加する経路)"
  - "trust_tier の caller-supplied 経路混入 (server-resolved only invariant、server-owned-boundary §1 違反)"
  - "Tool Registry version と prompt_pack_version / policy_pack_version の lockfile drift (ContextSnapshot 10 列 lock 機構と非同期)"
---

最終更新: 2026-05-22

## 目的

P0 / P0.1 で扱う MCP / external tool / local stdio tool を **機械可読 registry** で一元管理し、`allowed_actions` / `trust_tier` / `payload_data_class` の boundary を不変条件として強制する。本 Sprint Pack は **security boundary 独立**: SP-005-5 (Output Validator) への functional-near alias は禁止 (R29 R26 T-P2R1-012-residual 反映、SP-005-5 は output validation core、Tool Registry は tool authorization layer で目的が異なる)。

## 背景

- 修正まとめ統合計画 R29 (`../設計検討/修正まとめ統合計画.md`) §3.5.4 Pack inventory で `create_required = 1 件 (SP-0045)` を確定
- `docs/基本設計/03_AIオーケストレーション設計.md` (DD-03) ContextSnapshot 必須 10 カラムの 1 つ `tool_manifest` (tool registry version + tool allowlist hash) の registry source
- 修正まとめ 04 / 05 由来の `read/search` 系 action は **action_class enum 7 種に追加せず**、Tool Registry の `allowed_actions` 列に分離する (R29 §3 D-003 + R-04 reject 理由対応)
- P0 では `local|stdio` と read-only `search|fetch` 中心、書込系 MCP / 外部 tool は `tool_mutating_gateway_stub` で deny-only (CLAUDE.md §2 deny-by-default + §rules/ai-output-boundary.md §9 Gateway 境界)

## 対象外

- `tool_mutating_gateway_stub` の deny-only **本実装** (Sprint 4.5 既存 scope、本 Pack は registry definition のみ)
- repo 外 trusted hook wrapper の host-level 配置 (ADR-00012 は accepted、operator 配置は別 timing)
- 外部 MCP server 追加 path (P0.1 SP-018+ defer、本 Pack は P0 standard tool のみ registry 化)
- voice / Realtime tool 統合 (P1+ defer、ADR-00023 InteractionGateway 経由)

## 設計判断

- **registry source = `config/tool_registry.toml`** (Provider Compliance Matrix `config/provider_compliance.toml` と同 pattern、Pydantic + TOML loader)
- **`allowed_actions` enum 4 種 (P0 確定)**: `web_fetch` / `docs_search` / `code_grep` / `filesystem_read`
  - P0 deny (registry に entry しても block): `tool_write` / `repo_write` / `command_exec` (これらは `tool_mutating_gateway_stub` で deny-only + audit、`runner_mutation_gateway` を経由する別 boundary)
  - **action_class enum 7 種に追加しない** (`task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` は不変)
- **`trust_tier` 4 種 (DD-02 既存 enum 同期、provenance のみを表現、server-resolved only、R2 P2R1 F-P2R1-003 + R2 P2R2 F-P2R2-006 反映)**: `official` / `self_hosted` / `third_party` / `experimental`
  - **DD-02 (docs/基本設計/02_データモデル.md:522-523) の既存 `tool_registry.trust_tier` DB CHECK constraint と完全同期**、TOML/DB 二正本を禁止
  - caller-supplied 不可、server が registry から resolve、capability token issue 時に固定 (server-owned-boundary §1 準拠)
  - **`trust_tier` は provenance metadata のみ** (どの組織が tool を提供したか)、**直接 data-class 許可を意味しない**。data-class boundary は **`max_outgoing_data_class` per row が canonical** + server-resolved policy で combined evaluation (F-P2R2-006 で `official` 等が data-class 許可を意味する drift を防ぐ)
  - SP-0045 accepted 化前に DD-02 既存 enum を本 Pack 内 spec と同期 verify、drift があれば DD-02 update + SP-0045 同期 PR を同期 merge
- **`payload_data_class` boundary**: Tool Registry entry に `max_outgoing_data_class` (`public` / `internal` / `confidential` / `pii`) を明示、Provider Compliance Matrix 同様 ordinal 比較 (`public:0 < internal:1 < confidential:2 < pii:3`)
- **ContextSnapshot.tool_manifest hash の正本**: `(registry_version, sha256(tool_allowlist))` を tuple で hash 化、AgentRun 開始時に snapshot 固定 (DD-03 §ContextSnapshot)
- **registry version は lockfile pattern**: **ContextSnapshot の必須 10 列 (DD-03 / core.md §9 / agentrun-state-machine.md §11) は不変条件として固定、新規 11 列目追加なし**。`tool_manifest` 列の内部に `registry_version` + `sha256(tool_allowlist)` を tuple 保存することで lockfile pattern を実装
- **tool_manifest server-owned (caller-supplied 経路禁止、F-P2R1-005 反映)**: server が `config/tool_registry.toml` から `(registry_version, sha256(tool_allowlist))` tuple を再計算し、API endpoint Pydantic schema / service layer signature / ORM の 3 layer で caller-supplied tool_manifest を受け取らない (server-owned-boundary §2 準拠、signature レベル物理削除)
- **registry 起動前 fail-closed (F-P2R1-006 反映)**: `config/tool_registry.toml` の load / validate / version check が PASS しない限り `ToolAdapter` 起動不可、全 tool call は `tool_registry_unavailable` reason で deny、`tool_mutating_gateway_stub` は **deny-only state** のまま起動 (起動順 race を fail-closed で防ぐ)
- **tool → runner 経路 (F-P2R1-007 反映)**: tool-originated artifact が `runner_mutation_gateway` に渡る場合、registry の `registry_decision` event と `tool_manifest hash binding` を必須化、欠落時は `runner_mutation_gateway` 側も deny。registry boundary と runner boundary の **2 重 gate** で artifact origin laundering (tool-write を runner patch として再包装) を防ぐ

## 実装チケット

- SP0045-T01: `config/tool_registry.toml` schema design (Pydantic + TOML、Provider Compliance Matrix と同 pattern)、`registry_version` / `tools[]` (各 entry: `tool_key` / `transport` / `allowed_actions` / `trust_tier` / `max_outgoing_data_class` / `mcp_endpoint?` / `notes`)
- SP0045-T02: Registry loader + Pydantic validation (`backend/app/services/tool_registry/loader.py`)、enum 4 重防御 (Pydantic field validator + Python Literal + pytest EXPECTED + DB CHECK は Tool Registry table 化時)
- SP0045-T03: `allowed_actions` enum 4 種 + `trust_tier` 4 種 (DD-02 既存 4 種同期、F-P2R1-003) + `max_outgoing_data_class` 4 種を **cross-source 5+ source 整合** で固定 (cross-source-enum-integrity §1 準拠: Pydantic + Literal + pytest + frontend TS enum + docs + **DD-02 既存 `tool_registry.trust_tier` DB CHECK 同期**)
- SP0045-T04: `trust_tier` + `tool_manifest` server-resolved invariant の caller-supplied 経路禁止 test (`tests/services/tool_registry/test_trust_tier_server_owned.py` + `test_caller_supplied_tool_manifest_reject.py`、F-P2R1-005 反映)、signature レベル削除 verify
- SP0045-T05: ContextSnapshot.tool_manifest hash integration (DD-03 §ContextSnapshot 既存 10 列の `tool_manifest` 列定義に registry version + allowlist sha256 を保存)

## タスク一覧

- [ ] SP0045-T01〜T05 を順次実装 (Codex R1〜R{clean} multi-round)
- [ ] `config/tool_registry.toml` schema が `config/provider_compliance.toml` と pattern 一致
- [ ] enum 4 重防御 (Pydantic + Literal + pytest EXPECTED + docs) を全 enum (allowed_actions / trust_tier / max_outgoing_data_class) に適用
- [ ] caller-supplied `trust_tier` test が **deny** で PASS
- [ ] ContextSnapshot.tool_manifest hash spec が DD-03 と整合

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| `config/tool_registry.toml` schema + Pydantic loader | ○ | - |
| `allowed_actions` 4 種 enum + 5+ source 整合 | ○ | - |
| `trust_tier` 4 種 (DD-02 既存同期、F-P2R1-003) server-resolved + caller-supplied 経路禁止 + DD-02 同期 verify | ○ | - |
| `max_outgoing_data_class` 4 種 + Provider Compliance Matrix と独立 boundary | ○ | - |
| ContextSnapshot.tool_manifest hash spec (DD-03 update) | ○ | - |
| `tool_mutating_gateway_stub` deny-only invariant verify (P0 deny tools が registry にあっても block) | ○ | - |
| 外部 MCP server 追加 path | × | P0.1 SP-018+ |
| voice / Realtime tool 統合 | × | P1+ ADR-00023 InteractionGateway 経由 |
| Tool Registry frontend UI (admin) | × | P0.1 SP-016 carry-over |
| Tool Registry DB hardening (`allowed_actions` / `tool_versions`) | ○ | - |

## 受け入れ条件

- `config/tool_registry.toml` が Pydantic model で load + validate PASS
- `allowed_actions` enum 4 種が cross-source 5+ source 整合 test で PASS (Pydantic / Literal / pytest EXPECTED / docs / frontend TS [P0.1+])
- `trust_tier` を caller が指定する経路が **signature レベルで物理削除** (server-owned-boundary §1)、API endpoint Pydantic schema / service layer / ORM の 3 layer で reject
- **payload classification 未設定 / invalid / pending の Tool call は classification 前に deny** (`tool_payload_data_class_unset` reason_code、F-P2R1-004 反映、Provider Compliance Matrix §6 と同じ fail-closed pattern)、classification 完了後のみ ordinal 比較
- `payload_data_class > max_outgoing_data_class` の Tool call が deny + audit event (`tool_payload_data_class_exceeded` reason_code、Provider Compliance Matrix と同じ ordinal 比較方向: payload が registry の max 上限を超えたら deny)
- **registry 起動前 / load 失敗 / version mismatch 時の全 tool call が `tool_registry_unavailable` reason で deny** (F-P2R1-006 反映、fail-closed invariant)
- **tool-originated artifact が runner_mutation_gateway へ渡る場合、registry_decision event + tool_manifest hash binding が記録されていない場合は runner 側も deny** (F-P2R1-007 反映、artifact origin laundering 防止の 4 quadrant verify: tool allow + runner allow / tool allow + runner deny / tool deny + runner deny / **tool-originated direct → runner deny**)
- **caller-supplied tool_manifest を受け取る経路の signature レベル削除 verify** (F-P2R1-005 反映、`tests/services/tool_registry/test_caller_supplied_tool_manifest_reject.py`)
- **`trust_tier` は provenance のみを表現** (DD-02 既存定義に固定、F-P2R2-006 反映): `official` / `self_hosted` / `third_party` / `experimental` は **どの組織が tool を提供したか** を分類する metadata で、**直接 data-class 許可を意味しない**。送信上限の判定は **`max_outgoing_data_class` per row のみが canonical** な data-class boundary、`server-resolved policy` で combined evaluation。registry entry 編集で `experimental` tier に `max_outgoing_data_class > public` を許可する設定は ADR-00027 update 必須 (provenance と effective risk の分離)
- action_class enum 7 種に新規追加 0 件 (`task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` は不変)
- ContextSnapshot.tool_manifest が `(registry_version, sha256(tool_allowlist))` tuple で snapshot 固定
- AC-HARD-07 (prompt_injection_resist): untrusted_content が `trust_tier` (DD-02 4 種 `official/self_hosted/third_party/experimental`) を **caller-supplied 経路で書き換える / より上位 provenance への昇格を試みる** 経路が deny (server-resolved invariant、F-P2R2-001 + F-P2R2-006 反映)

## 検証手順

```bash
# Schema validation
uv run python -m backend.app.services.tool_registry.loader --validate config/tool_registry.toml

# Cross-source enum 5+ source 整合
uv run pytest tests/services/tool_registry/test_allowed_actions_enum_integrity.py -q
uv run pytest tests/services/tool_registry/test_trust_tier_enum_integrity.py -q
uv run pytest tests/services/tool_registry/test_max_outgoing_data_class_enum_integrity.py -q

# Server-owned boundary (caller-supplied 経路禁止)
uv run pytest tests/services/tool_registry/test_trust_tier_server_owned.py -q

# Boundary enforcement
uv run pytest tests/services/tool_registry/test_max_outgoing_data_class_deny.py -q
uv run pytest tests/services/tool_registry/test_experimental_max_outgoing_data_class_deny.py -q
uv run pytest tests/services/tool_registry/test_provenance_trust_tier_server_owned.py -q

# action_class 7 種不変
uv run pytest tests/policy/test_action_class_enum_invariant.py -q

# AC-HARD-07 (prompt_injection_resist) Tool Registry fixture
uv run pytest eval/security/prompt_injection/test_tool_registry_trust_tier_promotion_deny.py -q

# ContextSnapshot.tool_manifest integration
uv run pytest tests/agent_runtime/test_context_snapshot_tool_manifest.py -q
```

## レビュー観点

- **SP-005-5_output_validator への alias / functional-near reuse / related_sprints 経由の依存代替が 0 件**で、Tool Registry が独立 Pack として扱われている (R29 R26 T-P2R1-012-residual、security boundary 独立 invariant 機械検証項目)
- `allowed_actions` enum に **read/search 以外** (write 系) が混入していない (R29 §3 D-003)
- `trust_tier` が **caller-supplied** で受け取れる経路が 0 件 (signature / Pydantic schema / service layer / ORM の 3 layer で削除)
- `tool_mutating_gateway_stub` の deny-only invariant が registry の `allowed_actions` 列で再強制されていない (registry は authorization layer、gateway は execution boundary、layer 分離)
- ContextSnapshot.tool_manifest hash が `prompt_pack_lock` / `policy_pack_lock` と同 pattern (registry_version + sha256(allowlist) tuple)
- Tool Registry version 更新時に既存 AgentRun が **immutable** で保存される (snapshot は run 開始時固定、registry update は新 run のみ反映)
- `payload_data_class > max_outgoing_data_class` deny 時の audit event が raw secret / raw tool payload を含まない

## 残リスク

- registry TOML の手動編集 risk: PR review で `registry_version` bump + alias map 整合を verify、CI で `tool_registry.toml` 変更時に lint + schema test 必須
- `tool_mutating_gateway_stub` vs Tool Registry の **layer 分離 drift**: gateway は execution boundary (deny actual call)、registry は authorization layer (deny by config)、両者を混同すると bypass 経路発生 → integration test で「registry allow + gateway deny」「registry deny + gateway allow」の 4 quadrant verify
- ContextSnapshot.tool_manifest と Provider Compliance Matrix lockfile の **二重管理 risk**: provider call では Matrix 優先、tool call では registry 優先、両者の境界を AgentRun timeline event で明示
- P0.1 で external MCP server 追加時の **trust_tier promotion path 不在**: 本 Pack は P0 standard tool のみ registry 化、P0.1 で trust_tier promotion ADR が必要 (SP-018 候補)

## 次スプリント候補 (R2 P2R1 F-P2R1-014 反映: SP-018 は既存 Hermes memory sprint 予約済、新規番号で起票)

- **P0.1 新規番号で起票 (SP-018 不可)**: external MCP server boundary + trust_tier promotion ADR (DD-02 既存 4 種に加えて新 trust_tier 拡張時の ADR)
- **P0.1 新規番号で起票 (SP-018 不可)**: Tool Registry DB table 化 + frontend admin UI (SP-013+ multi-agent 系とは独立)

## Owner / DoD / rollback (R29 QL-A verification 要件、F-R1-008 反映)

### Owner

- area: security boundary (Tool authorization layer、SP-005-5 Output Validator とは独立)
- responsible: backend service tier (`backend/app/services/tool_registry/` 配下)
- review: Hard Gates / Security Council (ADR-00012 accepted 化と同期)

### Definition of Done (DoD)

- frontmatter 12 fields 完備 (heavy Pack 要件)
- `allowed_actions` 4 種 / `trust_tier` 4 種 (DD-02 既存同期、F-P2R1-003 反映) / `max_outgoing_data_class` 4 種 すべてが cross-source 5+ source 整合 spec で記述 (cross-source-enum-integrity §1)、`trust_tier` 5+ source manifest に **DD-02 既存 `tool_registry.trust_tier` DB CHECK** を含む (TOML/DB 二正本禁止)
- caller-supplied `trust_tier` / `tool_manifest` (`(registry_version, sha256(tool_allowlist))` tuple) 経路の signature レベル削除 spec が明記 (server-owned-boundary §1-§2、F-P2R1-005 反映)
- payload classification 未設定 / invalid / pending の tool call が classification 前に deny (`tool_payload_data_class_unset`、F-P2R1-004 反映)
- registry 起動前 / load 失敗 / version mismatch 時の全 tool call が `tool_registry_unavailable` reason で deny (fail-closed、F-P2R1-006 反映)
- tool-originated artifact が runner_mutation_gateway へ渡る場合の registry_decision event + tool_manifest hash binding 必須化 spec (4 quadrant verify、F-P2R1-007 反映)
- ContextSnapshot.tool_manifest 統合 spec が DD-03 既存 10 列を変更しない方針で記述 (F-R1-003)
- レビュー観点に SP-005-5 alias 禁止 verify 項目 (F-R1-007)
- planned_adr_refs に存在 ADR file (`00013_remote_agent_extension.md`) が指定 (F-R1-001)
- **本 Pack accepted 化条件 (F-P2R1-002 + F-P2R1-017 + F-P2R2-002 + F-P2R2-008 反映、heavy Pack ADR Gate 強化)**:
  1. `docs/adr/00027_tool_registry_security_boundary.md` が **実在 file として存在し、status: `accepted`、または SP-0045 と同一 PR で co-accepted** (proposed のみでは Pack accepted 化不可、F-P2R2-008 反映で逆連動防止)
  2. ADR-00027 が **ADR Gate Criteria #3 (API/event schema) + #5 (MCP/tool 権限) section を持ち**、**採用案 / 却下案 / rollback / enum source manifest (5+ source、DD-02 既存 trust_tier 同期 verify を含む) / server-owned boundary checklist (trust_tier + tool_manifest signature 削除 verify) / registry 起動前 fail-closed spec** を全て含む (F-P2R1-017 反映)
  3. ADR-00027 は SP-0045 batch A で accepted 化済み。今後 rejected / superseded / 未 accepted に戻る場合、SP-0045 status を即 `blocked` へ戻し、SP0045-T01〜T05 / BL-0054〜0061 / BL-0157 着手禁止 (逆連動、F-P2R2-008 反映)
  4. `planned_adr_refs` だけでは Pack accepted 化不可、`adr_refs` (non-empty) に ADR-00027 が登録されている必要あり (heavy Pack frontmatter ADR Gate 非空要件、F-P2R2-002 反映)

### Rollback condition

- `git diff docs/sprints/SP-0045_tool_registry.md` で単独 revert 可能 (本 Pack 新規起票分のみ)
- README.md の registry §3.1 inventory 行と §3.3 Missing Pack creation policy も同一 PR の revert 対象に含む (`create_required` 行が registry 化されない状態へ戻る)
- `config/tool_registry.toml` schema / loader の rollback は同一 PR revert で可能
- DB migration 着手後の rollback は ADR-00012 (Hook Trust Boundary) accepted 化との依存関係も考慮、別 ADR で破壊的操作 (ADR Gate Criteria #8) として扱う

### Post-rollback verification

- registry alias map で SP-0045 が `create_required` のまま (実 file 不在) に戻り、PLAN-01 から SP-0045 を参照する BL- が drift とみなされる状態を Sprint Pack DoD で機械検出可能
- 既存 4 Pack (SP-008 / SP-010 / SP-011 / SP-011-5) と SP-005-5 の security boundary 影響なし (本 Pack 独立)
- Provider Compliance Matrix / SecretBroker / Runner sandbox の各 boundary に変更なし

## 関連 ADR

- **ADR-00027 (Tool Registry Security Boundary、accepted、primary owner)**: `allowed_actions` 4 種 / `trust_tier` 4 種 (DD-02 既存同期、F-P2R1-003) / `max_outgoing_data_class` 4 種 enum / `tool_manifest` ContextSnapshot 統合 (server-owned、F-P2R1-005) / registry 起動前 fail-closed (F-P2R1-006) / tool→runner artifact origin laundering 防止 (F-P2R1-007) / `tool_payload_data_class_exceeded` `tool_payload_data_class_unset` `tool_registry_unavailable` 等 audit reason_code を primary contract として所有。ADR Gate Criteria #5 (MCP/tool 権限) + #3 (API/event schema) 該当。
- ADR-00012 (Hook Trust Boundary、accepted): Tool Registry security boundary の prerequisite
- ADR-00013 (Remote Agent Extension Point、proposed): Codex app-server / Claude Agent SDK boundary、Tool Registry の external MCP server entry の reference
- ADR-00002 (Core Data Model、proposed): ContextSnapshot 10 列の `tool_manifest` 列定義
- ADR-00003 (AI Orchestration、proposed): AgentRun event_type に `tool_*` 系 event 追加時の 5+ source 整合

## Review

(SP-0045 完了時に追記)
