---
id: "ADR-00003"
title: "CLI artifact orchestration boundary: artifact schema / subprocess launcher / AgentRunEvent 拡張 / 採否判定 API / AI 出力直結禁止 lint"
status: "accepted"
date: "2026-05-12"
accepted_at: "2026-05-12"
authors:
  - "t-ohga"
related_sprints:
  - "SP-006_cli_artifact"
  - "SP-007_runner_sandbox"
  - "SP-013_remote_agent_extension"
supersedes: null
superseded_by: null
---

このテンプレの使い方: Sprint 6 の CLI artifact orchestration を ADR Gate Criteria #3 (API 契約 / event schema) に対応する形で固定する。`codex exec` / `claude -p` 等の CLI agent を domain に密結合せず、artifact schema + subprocess launcher + AgentRunEvent 拡張 + 採否判定 API + AI 出力直結禁止 lint の 5 boundary を確立する。Sprint 6 batch 1 着手前に proposed → accepted、Sprint 6 Exit までに review 欄を最終化する。

最終更新: 2026-05-24 (SP-009-5 Batch F2 で Newcomer Path dry-run intake API contract plan を append。前: SP-009-5 Batch E0 で Approval `request_revision` API contract plan を append)

## 背景

- 決定対象: CLI agent (`codex exec` / `claude -p` 等) を TaskManagedAI domain に密結合せず、安全な artifact + subprocess boundary として扱う API 契約 / event schema を固定する。
- 関連 Sprint: SP-006 (CLI artifact orchestration、本 ADR の実装対象)、SP-007 (Runner sandbox、CLI launcher が Sprint 7 RunnerAdapter に接続できる interface を本 ADR で定義)、SP-013 (Remote Agent Extension、Codex App Server / Claude Agent SDK の extension point note を本 ADR に含めるが P0.1+ 着手)。
- 前提 / 制約:
  - AI Output Boundary §1 (rules/ai-output-boundary.md): AI 出力を shell command / SQL / migration / workflow / external mutating tool / repo patch に直接接続する経路を絶対禁止。
  - Sprint 5.5 完成済 boundary: Output Validator (BL-0064/0067 続き) + Input Trust Layer (BL-0065/0066) + Approval 4 整合 (BL-0069)。CLI artifact は Sprint 5.5 boundary の **上層**で動作。
  - server-owned-boundary §1 + §3 (rules/server-owned-boundary.md): caller-supplied 経路 signature レベル物理削除 + Approval 4 整合 policy-independent enforcement。CLI artifact の `source_agent` / `payload_data_class` も同 invariant 適用。
  - tool_mutating_gateway_stub: P0 で MCP / 外部 tool 書込系 deny-only、本 Sprint 6 でも未変更 (Sprint 4.5 confirmed)。
  - runner_mutation_gateway: Sprint 7 で初実装、本 Sprint 6 では CLI launcher が Sprint 7 RunnerAdapter に接続できる interface 定義のみ。
  - artifact_kind: Sprint 5.5 batch 1 で確立した 6 種 (`plan` / `patch` / `evidence` / `citation` / `provider_continuation_ref` / `other`) を additive only で拡張、既存 6 種を破壊しない。
  - AgentRunEvent: Sprint 5.5 batch 1 で 22→25 拡張済、本 Sprint 6 で 25→?? に追加拡張 (CLI 関連 event_type)、5+ source 整合 (cross-source-enum-integrity §1) を維持。
- 該当 ADR Gate Criteria: **#3 (API 契約 / event schema)** + #4 (AI エージェント権限、CLI agent の subprocess 経路) + #5 (MCP / tool 権限、CLI launcher registry) + #6 (Secrets 管理、CLI env scrubbing) + #10 (Provider 系、CLI も agent provider の一種)。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: subprocess + artifact pattern (採用) | CLI agent を `CliArtifactAdapter` で抽象化、Markdown / JSON input artifact + allowlisted argv subprocess launcher + redacted stdout/stderr artifact + 採否判定 (adopt/reject/defer) + AI 出力直結禁止 lint。domain は CLI の具体コマンドを知らない | AI Output Boundary §1 と整合 / Sprint 5.5 Output Validator boundary の上層に乗る / `tool_mutating_gateway_stub` を変更しない / Sprint 7 Runner adapter に拡張可能 / Codex App Server / Claude Agent SDK との互換性は extension point note で確保 (ADR-00013) | subprocess process group / cancel propagation の実装複雑度 / Redis pub/sub 経由の signal 伝播 |
| B: direct CLI execution (`subprocess.run(shell=True, ...)`) | AI 出力を直接 shell command として実行、結果を AgentRun に保存 | 実装最小 | **AI Output Boundary §1 絶対禁止違反** (AI 出力 → command 直結)。Hard Gate AC-HARD-06 `dangerous_command_block` 違反。**reject** |
| C: managed library / SDK 取り込み (e.g. OpenAI Agents SDK / LangGraph) | 第三者 framework を採用、framework 内蔵の CLI integration を使う | community 整備済 | ADR-00020 (Framework Intake Checklist) 8 verify 違反 (License / Attribution / **No code embed** / Persistence 二重化 / External network deny / Telemetry off / Secret canary scan / tenant 境界)。ADR-00016 (Hermes pattern adoption only) と整合せず。**reject** |

## 採用案

- 採用: **A (subprocess + artifact pattern)**
- 理由:
  - AI Output Boundary §1 (AI 出力 → command 直結禁止) を fail-closed で enforce 可能。
  - Sprint 5.5 で確立した Output Validator + Input Trust Layer + Approval 4 整合 invariant の上層に乗せる形が natural (CLI artifact は untrusted_content → validated_artifact → trusted_instruction 経路と整合)。
  - server-owned-boundary §1 を踏襲 (CLI input artifact の `source_agent` / `payload_data_class` は caller-supplied 経路 signature レベル物理削除)。
  - Sprint 7 Runner sandbox との互換性 (CLI launcher = Sprint 7 RunnerAdapter の特殊化)。
  - ADR-00013 (Remote Agent Extension Point) との整合 (Codex App Server / Claude Agent SDK の P0.1 拡張 path として extension point note を残す)。
- 実装 Sprint: **SP-006 (Sprint 6 CLI artifact)**、SP-007 (Runner sandbox、launcher の Sprint 7 拡張)、SP-013 (Remote Agent Extension、P0.1+)
- 実装対象ファイル:

### 5 boundary それぞれの実装対象 (Sprint 6 BL ticket trace)

| boundary | 実装対象 | BL-trace |
|---|---|---|
| **1. CLI artifact schema** | `backend/app/domain/cli_artifact/schema.py` (Pydantic + JSON Schema、Markdown frontmatter + JSON payload 両対応) + `backend/app/db/models/artifact.py` (artifact_kind 5 種追加: `cli_input` / `cli_stdout` / `cli_stderr` / `cli_exit` / `cli_result_summary`) | BL-0064 |
| **2. subprocess launcher** | `backend/app/services/cli_artifact/launcher.py` (allowlisted binary + argv 配列、shell string 禁止、scrubbed env、timeout / max_output_bytes / network policy) + `backend/app/services/cli_artifact/registry.py` (allowed binaries: `codex` / `claude` 等 + allowed args pattern + timeout default + env policy) | BL-0065 |
| **3. AgentRunEvent 拡張** | `backend/app/domain/agent_runtime/event_type.py` (25→拡張、新規 event_type: `cli_process_started` / `cli_process_completed` / `cli_output_redacted` / `cli_decision_recorded`、5+ source 整合) + migration (CHECK constraint 拡張) | BL-0066 + BL-0067 |
| **4. 採否判定 API** | `backend/app/services/cli_artifact/decision.py` (`adopt` / `reject` / `defer` decision API、artifact_hash + policy_version + repo_state + decided_by_actor binding) + `audit_event` 追加 (Sprint 11 で本実装、本 Sprint では service-layer skeleton) | BL-0068 |
| **5. AI 出力直結禁止 lint** | `backend/app/services/cli_artifact/direct_execution_lint.py` (artifact graph で `source=ai` → `command` / `SQL` / `workflow` / `repo_patch` の direct edge を reject、fail-closed) | BL-0069 |

(BL-0070 subprocess cancel propagation は 2. subprocess launcher の追加 method、Redis pub/sub + process group SIGTERM/SIGKILL)

### 実装ガイダンス

#### A. CLI artifact schema (Markdown + JSON 両対応)

- 必須 frontmatter / JSON fields: `run_id` (UUID) / `artifact_kind` (Literal 5 種) / `content_hash` (SHA-256 hex 64) / `payload_data_class` (Literal 4 種、Sprint 5.5 batch 1 と同) / `source_agent` (CLI binary name) / `schema_version` (semver)
- artifact_kind enum 5 種:
  - `cli_input`: CLI agent への input (Markdown / JSON)
  - `cli_stdout`: redacted stdout capture
  - `cli_stderr`: redacted stderr capture
  - `cli_exit`: exit code + signal + duration + timeout / cancelled metadata
  - `cli_result_summary`: 採否判定の前段、redacted summary
- 既存 6 種 (`plan` / `patch` / `evidence` / `citation` / `provider_continuation_ref` / `other`) は **不変** (additive only)、`artifacts_ck_kind` CHECK 制約を 6→11 種に拡張
- `payload_data_class` は Input Trust Layer (Sprint 5.5 batch 1 BL-0066) の `classify_payload_data_class` で算出、caller-supplied 経路 schema レベル物理削除

#### B. subprocess launcher (allowlisted argv + scrubbed env)

- `LauncherRequest` schema (Pydantic): `registry_key` (Literal、registry entry id) + `argv_suffix` (list[str]、allowed args pattern に match) + `input_artifact_ref` (UUID) + `timeout_seconds` (int、default = registry value) + `max_output_bytes` (int、default = registry value)
- `LauncherResult` schema: `exit_code` (int) + `signal` (str | None) + `duration_seconds` (float) + `timeout_reached` (bool) + `cancelled_by_actor_id` (UUID | None) + `stdout_artifact_ref` + `stderr_artifact_ref` + `redaction_metadata` (pattern hit kinds + counts、raw value なし)
- env scrubbing: baseline = `PATH` / `LANG` / `HOME` (system minimum) のみ、provider key / repo token / SOPS / age key / capability token 生値を **物理的に inject しない** assertion
- AI 出力 → command string 経路は **signature レベルで物理削除** (`LauncherRequest` に `shell` / `argv` / `command` field を露出させない、`registry_key` + `argv_suffix` のみ)
- registry entry 例 (`config/cli_registry.toml`):
  ```toml
  [[entries]]
  registry_key = "codex_exec"
  binary = "codex"
  allowed_argv_prefix = ["exec"]
  allowed_argv_suffix_patterns = ["--prompt-file=*", "--output-mode=*"]
  timeout_seconds_default = 600
  max_output_bytes = 1048576
  network_policy = "tailscale_only"  # Sprint 7 で本 enforce
  env_policy = "scrubbed_baseline"
  ```

#### C. AgentRunEvent 拡張 (5+ source 整合)

- 新規 event_type 4 種を追加 (25 → 29 拡張):
  - `cli_process_started`: launcher 起動時 (running → running、status 不変、metadata-only)
  - `cli_process_completed`: launcher 完了時 (status は exit_code mapping、AgentRun.status は別)
  - `cli_output_redacted`: redaction hit 時 (raw value なし、pattern 種別 + count のみ)
  - `cli_decision_recorded`: adopt / reject / defer 採否判定時
- 5+ source 更新 (cross-source-enum-integrity §1):
  - DB CHECK: `migrations/versions/00NN_p0_cli_event_type_29.py` で `agent_run_events.event_type` CHECK 拡張 (revision_id ≤30 chars、Sprint 5.5 migration 0011 pattern 踏襲)
  - ORM CheckConstraint: `backend/app/db/models/agent_run_event.py`
  - Python Literal: `backend/app/domain/agent_runtime/event_type.py`
  - Pydantic: `agent_run_event/schemas.py`
  - pytest: `tests/runtime/test_agent_run_events.py:EXPECTED_AGENT_RUN_EVENT_TYPES`
- 既存 25 種は **不変** (additive only)、Sprint 5.5 batch 1 で追加した 3 種 (`repair_exhausted` / `trust_level_promoted` / `trust_level_promotion_denied`) も維持

#### D. 採否判定 API (adopt / reject / defer)

- `CliDecisionRequest` schema: `artifact_ref` (UUID) + `decision` (Literal `adopt` / `reject` / `defer`) + `decided_by_actor_id` (UUID、CLI 出力を採否する actor) + `reason` (str、redacted summary)
- artifact 4 整合 binding (Sprint 5.5 BL-0069 pattern を踏襲):
  - `artifact_hash`: CLI output artifact の content_hash (SHA-256 hex 64)
  - `policy_version`: 採否時の policy pack version
  - `repo_state`: 採否時の repo HEAD commit SHA + branch
  - `decided_at`: 採否 timestamp
- self-decision invariant: AI が `decided_by_actor_id` を inject する経路を物理削除 (caller = orchestrator が actor を server 側で resolve)
- `adopt` 後も後続 gate (Output Validator / Approval / Runner / RepoProxy) を **bypass しない**: `adopt` は「CLI output を validated_artifact として後続に渡す」のみ、`trusted_instruction` 昇格は Sprint 5.5 BL-0069 の Approval 4 整合 経路

#### E. AI 出力直結禁止 lint (artifact graph edge fail-closed)

- artifact graph: 各 artifact が `source` (provider / cli / human / system) + `target_action` (command / SQL / migration / workflow / external_tool / repo_patch / artifact_handoff) を持つ
- direct edge reject 条件:
  - `source=ai` (provider response / cli output) + `target_action` が `command` / `SQL` / `migration` / `workflow` / `external_tool` / `repo_patch` → fail-closed reject
  - 中間 `artifact_handoff` (Output Validator / Input Trust Layer / Approval) を経由した場合のみ allow
- AC-HARD-06 `dangerous_command_block` 接続 (本 Sprint 6 では service-layer lint、Sprint 7 Runner sandbox で本 enforce)

### テスト指針

#### Unit + contract test (DB-less)

- `tests/cli_artifact/test_artifact_contract.py` (BL-0064): Markdown / JSON schema validation + artifact_kind enum drift + content_hash sha256 hex regex
- `tests/cli_artifact/test_subprocess_launcher.py` (BL-0065): allowlisted argv enforcement / env scrubbing (provider key / SOPS / age key absence assertion) / timeout / max_output_bytes
- `tests/cli_artifact/test_stdout_stderr_redaction.py` (BL-0066): 21 prohibited keys × stdout/stderr surface = 42 sweep test (Sprint 5.5 BL-0068 pattern 踏襲) / 8 raw value regex patterns / canary pattern
- `tests/cli_artifact/test_exit_code_mapping.py` (BL-0067): exit_code 0 → success / 非 0 → failed / timeout → blocked + runtime_blocked / cancel → cancelled
- `tests/cli_artifact/test_decision_api.py` (BL-0068): adopt/reject/defer + 4 整合 hash binding + self-decision 禁止 (`extra="forbid"` + signature 削除)
- `tests/cli_artifact/test_direct_execution_lint.py` (BL-0069): 5 forbidden direct edge (command / SQL / migration / workflow / external_tool / repo_patch) すべて reject + handoff 経由 allow
- `tests/cli_artifact/test_cancel_propagation.py` (BL-0070): Redis pub/sub mock + SIGTERM/SIGKILL sequence + orphan process なし
- `tests/runtime/test_agent_run_events.py` (既存): EXPECTED_AGENT_RUN_EVENT_TYPES を 25 → 29 拡張

#### Integration test (DB あり、Sprint 7 / Sprint 11 で対応)

- `tests/cli_artifact/test_full_chain_integration.py`: CLI input → launcher → stdout/stderr → exit_code → decision → AgentRunEvent + audit_event を実 DB で end-to-end (Sprint 6 では skeleton、Sprint 7 Runner sandbox 着手時に full wire-up)

## 却下案

- **B: direct CLI execution (`subprocess.run(shell=True, ...)`)** : 却下理由 = AI Output Boundary §1 「AI 出力を shell command として直接実行しない」絶対禁止に正面違反。Hard Gate AC-HARD-06 `dangerous_command_block` (危険 command を Runner が拒否) も成立不可能。本案を採用すると Sprint 5.5 で確立した Output Validator + Input Trust Layer の意味がなくなる。
- **C: managed library / SDK 取り込み** : 却下理由 = ADR-00020 (Framework Intake Checklist) の 8 verify ([1] License / [2] Attribution / [3] **No code embed** / [4] Persistence 二重化 / [5] External network deny / [6] Telemetry off / [7] Secret canary scan / [8] tenant 境界) すべて Polyform Shield 等の embed 禁止 license / 二重 persistence layer / 外部 telemetry / secret canary scan 不整合の懸念。ADR-00016 (Hermes memory pattern adoption only) と整合せず。本 case では from-scratch 実装で十分 (CLI launcher は ~150 行 / artifact schema は ~50 行)。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| stdout / stderr の secret canary 漏洩 (raw provider key / capability token 生値が CLI 出力に含まれる) | `tests/cli_artifact/test_stdout_stderr_redaction.py` (21 prohibited keys × 2 surface + 8 regex patterns)、Sprint 11 Eval Harness で AC-HARD-02 `secret_canary_no_leak` fixture 接続 | Sprint 5.5 BL-0068 で確立した `_payload_secret_scan.py` 共通 scanner を流用 (DRY)、MappingProxyType / deepcopy / post_init re-scan の triple guard pattern を CLI artifact にも適用 |
| subprocess timeout / cancel propagation 不備 (orphan process が cancel 後に残存) | `tests/cli_artifact/test_cancel_propagation.py` + Sprint 11.5 Observability で OTel span 化 + Prometheus metric (cli_process_orphan_count) | Redis pub/sub から process group SIGTERM (default 5 sec grace) → SIGKILL、`tests/cli_artifact/test_cancel_propagation.py` で sequence 確認 |
| allowlisted argv の bypass (AI 出力が registry entry の args pattern を擦り抜けて `--dangerous-flag=...` を inject) | `tests/cli_artifact/test_subprocess_launcher.py` で registry pattern match + boundary fuzzing test + Codex adversarial review | registry の `allowed_argv_suffix_patterns` を `re.fullmatch` + `extra="forbid"` で fail-closed、AI 出力は `argv_suffix` field の string element のみ供給可能 (registry_key / binary は server-side 解決) |
| Codex App Server / Claude Agent SDK との extension point drift | ADR-00013 (Remote Agent Extension Point) と本 ADR-00003 の同期 check、Sprint Pack SP-013 着手時に integration test | 本 Sprint 6 では extension point note のみ残し、P0.1 SP-013 で full integration |
| artifact_kind 5 種 (`cli_*`) の cross-source enum drift (Python Literal / ORM / migration / pytest EXPECTED 不整合) | `tests/runtime/test_agent_run_events.py` + `tests/cli_artifact/test_artifact_kind_drift.py` を Sprint 6 で追加 | Sprint 5.5 batch 1 で確立した 5+ source 整合 pattern (cross-source-enum-integrity §1) を踏襲、migration revision_id ≤30 chars enforce |

## rollback 手順

1. **rollback trigger**: Sprint 6 実装中に CLI subprocess が secret leak / orphan process / argv bypass を起こした場合、または Sprint 6 Exit 後の Sprint 7 着手前 review で本 ADR の boundary 設計が機能しないと判明した場合。
2. **rollback step**:
   - **CLI artifact schema migration rollback**: `alembic downgrade` で artifact_kind CHECK 制約を 11 → 6 種に戻す + AgentRunEvent CHECK 制約を 29 → 25 種に戻す (既存 `cli_*` row は quarantine table または delete)
   - **subprocess launcher 削除**: `backend/app/services/cli_artifact/` directory 全削除、Sprint 5.5 boundary までに戻す
   - **採否判定 API 削除**: 関連 endpoint + service 削除、`adopt` / `reject` / `defer` decision を既存 Approval workflow (Sprint 3 / 5.5 BL-0069) で代替
   - **direct execution lint 削除**: 関連 service 削除、Sprint 7 Runner sandbox で本 enforce する形に変更
3. **verification after rollback**:
   - `uv run alembic check` で migration drift がないことを確認
   - `uv run pytest tests/cli_artifact/ -q` が全 skip (file 削除済) または fail-closed (skeleton)
   - Sprint 5.5 までの test 361 件が依然 pass
   - AgentRun 16 状態 / blocked_reason 3 種 / ContextSnapshot 10 列 / artifact_kind 6 種 / AgentRunEvent 25 種が rollback 後も整合

## Sprint 10 Research-to-Ticket adapter API contract 延長 (2026-05-13 update proposed)

本 section は **本 ADR の延長として扱う追加 API contract** であり、Sprint 10 で proposed → accepted 化する。base ADR (採用案 A: subprocess + artifact pattern) と同じ invariant (AI Output Boundary §1 / server-owned-boundary §1 / Approval 4 整合) を Research-to-Ticket adapter に適用する。

### Sprint 10 BL-0118: Research-to-Ticket adapter

**adapter の役割**: Research session (ResearchTask + Claims + Evidence) の結果を Ticket / Acceptance Criteria に **artifact 経由で promotion** する。AI が Research 結果を直接 Ticket DB に書き込むことは絶対禁止 (AI Output Boundary §1)。

#### server-owned 経路 (caller-supplied 経路 signature レベル物理削除)

- `artifact_hash`: server-side で `sha256(NFC-UTF8(JCS-canonical-JSON(research_promotion_payload)))` を再計算 (caller が指定する経路を signature から削除)
- `evidence_set_hash`: ADR-00002 §7.2 と同じ algorithm で server-side 再計算
- `payload_data_class`: Research session の payload metadata から事前算出 (caller-supplied 禁止、Provider Compliance Matrix §payload_data_class invariant)
- `provenance_json`: W3C PROV-DM minimal subset で validate (BL-0116)、Pydantic schema 不一致なら reject

#### API contract (Pydantic schema)

```python
class ResearchToTicketPromotionRequest(BaseModel):
    model_config = {"extra": "forbid"}  # caller-supplied 経路を fail-closed reject

    tenant_id: int
    project_id: UUID
    research_task_id: UUID  # server-side で research_tasks(tenant_id, project_id, id) 検証
    target_ticket_action: Literal["create_new", "update_existing"]
    existing_ticket_id: UUID | None  # target_ticket_action="update_existing" の時のみ
    proposed_acceptance_criteria: list[ProposedAC]  # caller-supplied content (untrusted_content)

class ResearchToTicketPromotionResponse(BaseModel):
    artifact_hash: str  # server-owned 再計算済
    evidence_set_hash: str  # server-owned 再計算済 (ContextSnapshot 結線)
    payload_data_class: Literal["public", "internal", "confidential", "pii"]  # server-side 算出
    approval_request_id: UUID  # Approval 4 整合 binding (Sprint 3 BL-0037 へ陪席)
    agent_run_event: Literal["research_to_ticket_promotion_requested"]
```

#### Approval 4 整合 (server-owned-boundary §3)

Research-to-Ticket promotion は **必ず Approval workflow を経由** する。caller (Research session worker) が直接 Ticket を更新する経路は signature から物理削除:

- artifact_hash binding: server-side で promotion payload を hash
- policy_version: Approval 時の policy pack version snapshot
- provider_request_fingerprint: Research session を実行した provider の OperationContext canonical fingerprint
- action_class: `task_write` (Sprint 3 ADR-00009 action_class taxonomy)

#### AgentRunEvent 拡張 (additive、cross-source-enum-integrity §1 維持)

- `research_to_ticket_promotion_requested`: Adapter が Approval workflow に submit
- `research_to_ticket_promotion_approved`: Approval decided=approved → Ticket / AC INSERT or UPDATE
- `research_to_ticket_promotion_rejected`: Approval decided=rejected → no DB mutation

AgentRunEvent enum total: Sprint 6 で 29 → 32 (Sprint 10 で +3、5+ source 整合 (Python Literal / ORM CheckConstraint / migration CHECK / pytest EXPECTED / frontend Zod) で同期)。

#### audit_events payload

- `tenant_id` / `actor_id` / `run_id` / `research_task_id` / `evidence_set_hash` / `approval_request_id` / `trace_id` / `correlation_id` / `timestamp`
- raw provenance_json / raw evidence content は payload に含めず、`provenance_json_hash` / `evidence_content_hash` のみ記録 (AC-HARD-02 invariant、ADR-00002 §7.2 と整合)

#### ADR Gate Criteria 該当

- **#3 API contract** (Pydantic schema 新規追加)、**#4 AI エージェント権限** (Research → Ticket promotion 経路、Approval 必須)
- base ADR (Sprint 6 CLI artifact) と同じ invariant 適用のため、新規 ADR 起票ではなく **本 ADR 延長で proposed → accepted**
- Sprint 10 完了で `status` 維持 (既に accepted)、`最終更新` date を更新

#### rollback (Sprint 10 adapter)

1. Adapter コード削除 (`backend/app/services/research_evidence/promotion_adapter.py`)、DB 変更なし
2. AgentRunEvent enum を 32 → 29 に戻す (migration revision 1 件 down)
3. promotion endpoint を 410 Gone で返却、既存 Research session worker は manual review 経路に fallback

## SP-009-5 notification triage API contract extension (2026-05-24 planning note)

SP-009-5 Batch D は In-App Notification を action-required triage queue に拡張する。これは ADR Gate Criteria #2 (DB schema) と #3 (API contract / event schema) に該当するため、runtime 実装前に本 ADR update note と Sprint Pack plan を先に固定する。

### Scope

- Current `notification_events.payload` は raw JSON を保持するが、triage response は raw value を返さない。
- Existing endpoints (`GET /api/v1/notifications`, badge count, mark-read) は互換維持する。
- New triage endpoint は `payload_keys` + `payload_redaction_status="keys_only"` を返す。
- Public API は `dedupe_key` を受け取らない。dedupe は server-side service/repository でのみ算出する。

### Planned data contract

`notification_events` に以下の additive columns を追加する:

| column | rule |
|---|---|
| `severity` | `info` / `low` / `medium` / `high` / `critical`; default `info` |
| `required_action` | `acknowledge` / `review_approval` / `inspect_run` / `resolve_blocker` / `external_followup`; default `acknowledge` |
| `due_at` | optional SLA target |
| `snoozed_until` | optional future timestamp set by actor-owned API |
| `resolved_at` | terminal triage timestamp |
| `resolved_by_actor_id` | composite FK to `actors(tenant_id, id)`, required with `resolved_at` |
| `dedupe_key` | server-computed text, unique only among unresolved notifications for the same recipient |

### Planned API contract

- `GET /api/v1/notifications/triage?state=open|snoozed|resolved|all`
- `POST /api/v1/notifications/{id}/snooze`
- `POST /api/v1/notifications/{id}/resolve`

All mutation endpoints must verify `(tenant_id, recipient_actor_id=current_actor)` before update. Resolve binds `resolved_by_actor_id` to the current actor. Snooze rejects timestamps in the past and timestamps beyond the implementation-defined maximum window (planned default: 30 days).

### Audit/event contract

Snooze/resolve append audit events with metadata-only payloads:

- `notification_snoozed`
- `notification_resolved`

Payloads include `notification_id`, `event_type`, `severity`, `required_action`, and the new timestamp. They must not copy raw notification payload values.

### Verification

- DB migration up/down/up/current.
- API tests for open/snoozed/resolved/all filters, cross-actor 403, idempotent resolve, future-only snooze, and partial dedupe uniqueness.
- Frontend tests that assert raw notification payload values are absent from the DOM.

## SP-009-5 request_revision API contract extension (2026-05-24 planning note)

SP-009-5 Batch E introduces an Approval revision-request loop. This touches ADR Gate Criteria #3 (API contract) and is planned before runtime implementation because it changes approval mutation semantics.

### Scope

- The first implementation does **not** add `revision_requested` to `approval_requests.status`.
- Existing pending approval rows transition to `invalidated` when a human decider requests revision.
- A new additive `approval_revision_requests` table records the revision request, decision-packet snapshot, requester/decider boundary, and eventual supersession.
- Revised artifact submission creates a new approval request with fresh decision-packet hashes.

### Planned API contract

`POST /api/v1/approvals/{approval_id}/request_revision`

Request body:

```json
{
  "rationale": "Explain the required change without secrets."
}
```

Response body:

```json
{
  "approval": { "status": "invalidated" },
  "revision_request_id": "uuid"
}
```

Contract rules:

- only `pending` approvals can receive a revision request
- `rationale` is required, trimmed, max 2000 characters, and raw-secret scanned before persistence
- self-approval and delegated same-human revision requests are rejected
- callers cannot provide replacement approval ids, artifact hashes, diff hashes, policy versions, policy pack locks, provider request fingerprints, or stale event sequence values
- duplicate open revision requests for one approval are rejected until supersession is recorded

### Payload exposure boundary

Audit and notification payloads for `approval_revision_requested` are metadata-only. They may include approval id, revision request id, action class, resource ref, risk level, and boolean hash-presence flags. They must not copy raw `rationale`, raw artifact content, raw provider payload, or raw notification payload values.

### Verification

- API tests for pending success and non-pending 409 cases.
- self-approval / delegated same-human negative tests.
- raw-secret canary rejection before DB insert.
- audit and notification payload non-exposure tests.
- migration upgrade head / downgrade -1 / upgrade head / current.

## SP-009-5 Newcomer Path dry-run intake API contract extension (2026-05-24 planning note)

SP-009-5 Batch F2 introduces a guided intake dry-run endpoint for first-use onboarding. This is ADR Gate Criteria #3 (API contract) and #4 (AI agent authority) because the request describes a future AI-assisted action. The first implementation is response-only and must not create execution state.

### Scope

- F2 endpoint: `POST /api/v1/onboarding/dry_run_plan`
- F2 is deterministic and response-only.
- No ticket, AgentRun, approval, approval revision, notification, audit event, repository operation, provider call, capability token, merge, deploy, CLI command, or persisted onboarding state is created.
- F2 may mention a future approval requirement, but it cannot create an approval request.

### Request contract

The request uses `extra="forbid"` and accepts only:

- `purpose`
- `target_repo_ref`
- `expected_artifact`
- `allowed_action_class`
- `budget_cap`
- `due_at`
- `reviewer_actor_id`
- `starter_mode`

Forbidden request fields include `policy_profile`, `tenant_id`, `project_id`, `actor_id`, `approval_id`, `run_id`, raw provider payloads, repository tokens, capability tokens, and runtime handoff fields.

`allowed_action_class` is a requested upper bound, not the effective policy decision. F2 accepts only `read_only`, `task_write`, `repo_write`, and `pr_open`; it rejects `secret_access`, `merge`, `deploy`, and `provider_call` for first-run intake.

### Effective action contract

- `starter_mode=research_only` -> effective `read_only`, `approval_required=false`
- `starter_mode=plan_only` -> effective `read_only`, `approval_required=false`
- `starter_mode=draft_pr_requires_approval` + upper bound `read_only` -> effective `read_only`
- `starter_mode=draft_pr_requires_approval` + upper bound `task_write|repo_write|pr_open` -> resolve through the existing autonomy policy engine with runtime disabled

`read_only` is a dry-run-only sentinel and is not added to the canonical 7-value `ActionClass` enum.

### Response contract

The response contains a `dry_run_plan` with:

- requested and effective action class
- policy effect
- approval requirement
- risk level
- estimated cost string
- rollback plan
- test plan
- blocked reasons
- next safe routes
- `would_create` booleans, all `false` in F2

The response must not include raw prompt text beyond validated user-visible fields, raw provider payloads, raw secrets, raw tokens, capability tokens, raw logs, or stack details. Raw-secret canaries in text request fields are rejected before response construction.

### Verification

- schema tests for `extra="forbid"` and rejected ownership/runtime fields
- policy negative tests for mutating first-run classes under runtime disabled
- raw-secret canary rejection for every text input field
- no-mutation regression counts for tickets, AgentRuns, approvals, approval revisions, notifications, and audit events
- response redaction tests for prohibited raw keys and token/log surfaces

### F2b implementation note (2026-05-24)

Batch F2b implemented the contract as `POST /api/v1/onboarding/dry_run_plan` with backend schema/service/API tests. The implementation remains response-only: all `would_create` fields are false, mutating candidates resolve through the autonomy policy engine with `runtime_enabled=false`, raw-secret canaries are rejected before response construction, and no migration is required.

## Sprint 11.5 batch 0 update note (2026-05-17 accepted)

Sprint 11.5 batch 0 (BL-0131 OTel + BL-0132 Prometheus) で Prometheus metrics 用 `/metrics` endpoint を追加。本 update は既存 API contract への **append のみ**、新規 ADR 起票ではない。`sprint-pack-adr-gate.md §10 break-glass #3 は対象外`、実装着手前 (commit 段階) に本 update note を accepted 化済。

### 追加 endpoint

- `GET /metrics` (response: Prometheus text exposition format)
  - **Tailscale 内部のみ accessible**: `PrometheusMetricsAccessGuard` middleware が IP allowlist (127.0.0.0/8 + ::1/128 + 100.64.0.0/10 Tailscale CGNAT) を強制、その他は 403 Forbidden
  - **OpenAPI から除外**: `include_in_schema=False`、external API consumer から hidden
  - **deny-by-default 2 layer 防御**: (1) 既存 127.0.0.1 bind (`docker-compose.yml`) + (2) middleware IP allowlist で production 0.0.0.0 bind 経由の regression を防ぐ
  - `X-Forwarded-For` 不信頼: reverse proxy 前提の trust boundary を持ち込まない

### CRITICAL invariant trace

- **deny-by-default** (`core.md §6`): 2 layer 防御 ✅
- **SecretBroker boundary**: metric label / description に raw secret を含めない、`_payload_secret_scan.assert_no_raw_secret` (Sprint 4 既確立) を import で single source 化 ✅
- **Provider Compliance 3 dimension**: `payload_data_class` / `allowed_data_class` / `effective_allowed_data_class` を別 label (合算禁止)、`DATA_CLASS_ORDINAL` mapping (public:0 / internal:1 / confidential:2 / pii:3) import で 5+ source 整合 ✅
- **5+ source enum integrity**: `gateway_kind` (tool / runner) は `ai-output-boundary.md §9` enum source と一致 ✅

### rollback

- 本 batch PR (`worktree-sprint-SP-011-5-batch-0-otel-prometheus`) revert で `/metrics` endpoint + middleware + observability module 全削除
- pyproject.toml の opentelemetry / prometheus-client dependency 削除、`uv lock` 再生成、`uv sync` 再実行
- `docker-compose.observability.yml` profile は batch 1 で導入予定のため、本 batch では既存 compose 不変、rollback 簡潔

### 次 Sprint 連携

- Sprint 11.5 batch 1 (BL-0133 Loki + BL-0134 Grafana): `/metrics` を scrape して Grafana dashboard で visualisation
- Sprint 12: host migration drill で `/metrics` endpoint が Mac / Linux / VPS 各 host で reachable (Tailscale 経由) を verify
