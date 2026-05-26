---
id: "SP-015_inter_agent_communication"
type: "heavy"
status: "completed"
sprint_no: 15
created_at: "2026-05-10"
updated_at: "2026-05-24"
completed_at: "2026-05-24"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # accepted、current event_type 37 already includes inter_agent_message_sent_ref / consumed_ref"
  - "[ADR-00018](../adr/00018_inter_agent_communication.md) # accepted at SP-015 kickoff (Criteria #2 + #3)"
planned_adr_refs: []
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
risks:
  - "PE-F-002 (atomic consume SQL の receiver eligibility 抜け)"
  - "PE-F-005 (sanitizer_version drift で stale memory 混入)"
  - "PE-F-014 (SecretBroker inter-agent message token payload negative case)"
---

最終更新: 2026-05-24 (batch 0a-0f 完了、test DB downgrade→upgrade PASS、frontmatter completed 化)

## 目的

inter_agent_messages 12 fields + atomic consume + replay/hijack defense + 3 trust_level + sanitizer pipeline + audit_events 3 種必須 payload + AgentRunEvent ref を P0.1 で完成させる。SP-014 の publisher stub を本実装に拡張する.

## 背景

- SP-013 で foundation table、SP-014 で orchestrator + 3 階層 + Tool Registry が完成
- 本 Sprint で agent 間「レビュー / 話し合う」場の DB / service / sanitizer / audit を仕上げる
- 既存 invariant (3 gateway / Approval 4 整合 + decider human-only / SecretBroker / Provider Compliance) すべて不変

## 対象外

- CLI tm message 表示 (SP-016)
- Web UI inter-agent timeline (SP-017)
- memory backend 連携 (SP-018)

## 設計判断

- **inter_agent_messages 本体 + audit_events cross-run + AgentRunEvent ref の 3 layer**: ADR-00018 §選択肢案 2 採用、message body は新 table、cross-run audit は既存 table に独立 event、各 run timeline は AgentRunEvent ref (raw payload なし)
- **12 fields 表記の扱い**: `12 fields` は歴史的 shorthand。実装時は ADR-00018 §1 の exact column set を正本にし、server-owned trusted refs / lifecycle fields / consume fields を落とさない
- **data class 命名**: Provider Compliance と同じ `payload_data_class` を正本名にし、`data_class` という短縮名を DB / API / audit payload に増やさない
- **atomic consume SQL の receiver eligibility (PE-F-002)**: receiver_kind=agent_run/role/broadcast ごとに direct child membership 検証を WHERE に含める
- **trusted_instruction promotion**: human approval 済 + server-owned refs 6 fields 完全揃い必須 (DB CHECK + service guard + Pydantic + test 4 重防御)
- **sanitizer_version 整合 (PE-F-005)**: SP-013 で投入済の sanitizer_policy_versions と一致確認、drift は stale_sanitizer deny or re-sanitize

## 実装チケット

- SP015-T01: inter_agent_messages table + 12 fields + 全 FK 複合 + 3 trust_level CHECK + atomic consume index
- SP015-T02: publisher service (sender) + sanitizer pipeline + secret canary scan + payload_data_class 算出
- SP015-T03: consumer service (receiver) + atomic consume SQL + receiver eligibility + replay/hijack defense
- SP015-T04: trust_level=trusted_instruction 4 重防御 (DB CHECK + service guard + Pydantic + test) + approval target 4 整合 verify
- SP015-T05: audit_events 3 種 (sent/consumed/denied) 必須 payload schema + assert_no_raw_secret_and_no_raw_message_body test helper
- SP015-T06: AgentRunEvent ref event 34/35 (inter_agent_message_sent_ref / consumed_ref) を current event_type 37 exact set として検証し、raw payload なしで append
- SP015-T07: backup/restore drill 拡張 (5 検証項目 = parent/child AgentRun FK + inter_agent_messages seq/hash/consume state + agent_roles soft-delete + memory_records source FK + audit_events correlation)
- SP015-T08: SecretBroker inter-agent message token payload negative case (PE-F-014 の 6 case のうち inter-agent 関連 1 つを SP-015 で must_ship)

## タスク一覧

- [x] SP015-T01 inter_agent_messages table + exact column set + FK / CHECK / index + downgrade path
- [x] SP015-T02 publisher service + sanitizer pipeline + server-owned payload_data_class 算出
- [x] SP015-T03 consumer service + atomic consume SQL + receiver eligibility + replay/hijack defense
- [x] SP015-T04 trusted_instruction 4 重防御 + approval target 4 整合 negative cases
- [x] SP015-T05 audit_events 3 種必須 payload schema + no raw message body tests
- [x] SP015-T06 AgentRunEvent ref event 34/35 append + raw payload なし regression
- [x] SP015-T07 backup/restore drill 5 検証項目 regression
- [x] SP015-T08 SecretBroker inter-agent token payload negative case
- [x] ADR-00018 を proposed → accepted
- [x] ADR-00004 current event_type 37 exact set を再検証し、SP-015 では source set drift なし
- [x] migration `0030_sp015_inter_agent_messages.py` downgrade→upgrade PASS (`alembic check` は既知 `migrations/env.py target_metadata` debt として分離)
- [x] 100 並行 atomic consume → 1 件のみ成功 verify
- [x] replay 攻撃 fixture / hijack 攻撃 fixture 全件 deny
- [x] backup/restore drill 5 検証項目 verify

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| inter_agent_messages table 12 fields | ○ | - |
| atomic consume + replay/hijack defense | ○ | - |
| 3 trust_level + sanitizer pipeline | ○ | - |
| trusted_instruction 4 重防御 | ○ | - |
| 3 audit_events 必須 payload | ○ | - |
| AgentRunEvent ref event 34/35 (current 37 exact set) | ○ | - |
| backup/restore drill 5 項目 | ○ | - |
| SecretBroker inter-agent token payload negative | ○ | - |
| Web UI / CLI 表示 | × | SP-016 / SP-017 で実装 |

## 受け入れ条件

- 12 fields すべて NOT NULL / DEFAULT / CHECK 違反で reject
- 100 並行 atomic consume → 1 件のみ成功
- replay/hijack 全 negative fixture (cross-parent / cross-tenant / cross-project / sender 偽装 / seq_no gap / previous_hash mismatch / idempotency 重複 / expires 経過) 全件 deny
- trust_level=trusted_instruction 自動昇格試行 → 全件 reject
- approval target 4 整合 negative 6 case (artifact_hash / policy_version / fingerprint / action_class / approval_id / 期限切れ approval reuse) 全件 deny
- 3 audit_events の必須 payload 完全揃い + raw 値 (artifact 本体 / secret / capability token) 含まれない
- AgentRunEvent ref に raw payload なし (message_id + payload_hash + seq_no + sender_run_id + receiver_run_id + redaction_status のみ)
- backup/restore drill 5 項目 verify (RPO ≤ 24h, RTO ≤ 4h)

## 検証手順

```bash
uv run ruff check backend/app/services/inter_agent \
                  backend/app/schemas/inter_agent.py \
                  backend/app/db/models/inter_agent_message.py \
                  tests/inter_agent \
                  tests/audit/test_inter_agent_no_raw_payload.py \
                  tests/security/test_secretbroker_inter_agent_token.py \
                  tests/db/test_backup_restore_inter_agent.py \
                  tests/runtime/test_agent_run_events.py

PYTHONPATH=cli uv run mypy backend/app/services/inter_agent \
                             backend/app/schemas/inter_agent.py \
                             backend/app/db/models/inter_agent_message.py \
                             tests/inter_agent \
                             tests/audit/test_inter_agent_no_raw_payload.py \
                             tests/security/test_secretbroker_inter_agent_token.py \
                             tests/db/test_backup_restore_inter_agent.py \
                             tests/runtime/test_agent_run_events.py

PYTHONPATH=cli \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/test_12_fields_schema.py \
              tests/inter_agent/test_publisher_service.py \
              tests/inter_agent/test_consumer_service.py \
              tests/inter_agent/test_trusted_instruction.py \
              tests/audit/test_inter_agent_no_raw_payload.py \
              tests/security/test_secretbroker_inter_agent_token.py \
              tests/db/test_backup_restore_inter_agent.py \
              tests/runtime/test_agent_run_events.py -q

TASKMANAGEDAI_DATABASE_URL=<local test db> uv run alembic downgrade 0029_sp0045_tool_registry_core
TASKMANAGEDAI_DATABASE_URL=<local test db> uv run alembic upgrade head
TASKMANAGEDAI_DATABASE_URL=<local test db> uv run alembic current

# Known repository infrastructure debt until migrations/env.py provides target_metadata.
TASKMANAGEDAI_DATABASE_URL=<local test db> uv run alembic check
```

## レビュー観点

- atomic consume SQL の WHERE が tenant/project/parent_run scope + receiver eligibility を完全表現
- `(tenant_id, project_id, parent_run_id, seq_no/idempotency_key)` の unique constraint で project boundary を落とさない
- previous_hash chain validation が consume ごとに strict 一致確認
- audit_events payload schema が 5+ source (DB CHECK + ORM + Pydantic + pytest + frontend (SP-017)) 整合
- AgentRunEvent ref と audit_events の責務分担明確化、raw payload 重複なし
- sanitizer_version drift 時の stale_sanitizer deny / re-sanitize 経路が完全実装

## 残リスク

- PE-F-005 sanitizer_version drift は SP-018 で memory backend 統合時に再検証
- SecretBroker 6 negative case のうち SP-015 で実装するのは inter-agent message token payload のみ、残り 5 case は SP-014 (orchestrator) と SP-016 (CLI) で実装
- broadcast の max_children 連動上限は orchestrator (SP-014) が enforce、SP-015 では publish 時に check のみ

## 次スプリント候補

- SP-016 UI ↔ CLI parity (`tm message list` 等)

## 関連 ADR

- ADR-00018 (Inter-Agent Communication Protocol) — proposed → accepted at SP-015 kickoff
- ADR-00004 (AgentRun state machine) — accepted。SP-014 で current event_type 37 に同期済み、SP-015 は event 34/35 を再利用
- ADR-00014 (関連)

## Review

### 2026-05-24 batch 0a

- `inter_agent_messages` DB schema / ORM model / Alembic migration / static schema test を追加。
- `payload_data_class` を正本名として採用し、旧 `data_class` は未導入。
- `(tenant_id, project_id, parent_run_id, seq_no/idempotency_key)` unique、project-scoped AgentRun / Artifact FK、receiver_kind fail-closed target CHECK、trusted_instruction server-owned refs CHECK を実装。
- `alembic check` は既存 `migrations/env.py target_metadata = None` により autogenerate 不可のため、test DB で downgrade→upgrade→current head と `tests/db/test_schema_introspection.py` を migration quality signal とした。

### 2026-05-24 batch 0b

- `InterAgentPublishRequest` / `InterAgentPublisherService` / sanitizer pipeline を追加。
- `payload_data_class` と `trust_level` は caller-facing schema から除外し、`payload_data_class` は classifier output、`trust_level` は batch 0b では `untrusted_content` 固定とした。
- Message body は canonical JSON artifact (`exportable=false`) に保存し、`inter_agent_messages` は `artifact_ref` + `payload_hash` の ref-only metadata を保持する。
- sanitizer は raw secret / canary scan に加え、`payload_data_class` / `trust_level` / approval refs / action_class など server-owned claim key を payload 内から reject する。
- Parent stream ごとに PostgreSQL advisory transaction lock を取り、`seq_no` と `previous_hash` chain を生成する。

### 2026-05-24 batch 0c

- `InterAgentConsumeRequest` / `InterAgentConsumerService` を追加。
- `consume` は `UPDATE inter_agent_messages ... WHERE ... RETURNING` の 1 statement で `consumed_at` / `consumed_by_run_id` を確定し、同時 consume は 1 件だけ成功する。
- receiver eligibility は direct agent_run / role / broadcast の 3 branch で、tenant/project/parent_run + child membership を SQL WHERE に含めた。
- replay/hijack defense として `already_consumed` / `expired` / `sender_self_consume` / `previous_hash_mismatch` / `receiver_ineligible` を分類し、DB-backed negative tests で固定。
- 100 並行 consume test で成功 1 / already_consumed 99 を確認。

### 2026-05-24 batch 0d

- `TrustedInstructionGrant` と `publish_trusted_instruction` を追加。
- caller-facing `InterAgentPublishRequest` は引き続き `trust_level` / `approval_request_id` / `action_class` 等を受け取らない。
- trusted_instruction は内部 grant が `ApprovalRequest(status='approved')`、human decider、source Artifact project boundary、artifact_hash / policy_version / provider_request_fingerprint / action_class の完全一致を満たす場合のみ作成可能。
- action_class は inter-agent trusted subset (`task_write` / `repo_write` / `pr_open` / `secret_access` / `provider_call`) に限定し、`merge` / `deploy` は拒否。
- approval binding mismatch / unknown approval / expired approval reuse / source artifact hash mismatch / forbidden action class を DB-backed tests で固定。

### 2026-05-24 batch 0e

- `InterAgentEventWriter` を追加し、publish 成功時に `inter_agent_message_sent` audit event と `inter_agent_message_sent_ref` AgentRunEvent を append する。
- consume 成功時に `inter_agent_message_consumed` audit event と `inter_agent_message_consumed_ref` AgentRunEvent を append し、consume deny 時は `inter_agent_message_denied` audit event を append する。
- audit consumed / denied の message id は SHA-256 hash のみ保持し、message body / artifact body / payload / content keys は writer boundary で reject する。
- AgentRunEvent ref payload は `message_id` / `payload_hash` / `seq_no` / `sender_run_id` / `receiver_run_id` / `redaction_status` のみで固定した。
- `tests/audit/test_inter_agent_no_raw_payload.py` で sent / consumed / denied audit payload、sent_ref / consumed_ref AgentRunEvent payload、raw body sentinel 非混入を DB-backed regression として固定した。

### 2026-05-24 batch 0f

- `InterAgentEventWriter` の audit events に message id hash ベースの `correlation_id` を追加し、backup/restore 後に sent/consumed audit を同一 message 系列として検証できるようにした。
- `tests/db/test_backup_restore_inter_agent.py` を追加し、parent/child AgentRun FK、`inter_agent_messages` seq/hash/consume state、`project_agent_roles.deprecated_at` soft-delete、`memory_records` source FK の applicable guard、audit_events correlation を DB-backed regression として固定した。
- sanitizer に `InterAgentPayloadRejected(reason_code=...)` を追加し、SecretBroker capability token pass-through を `inter_agent_message_token_payload` として分類する。
- publish 時に SecretBroker token payload を検出した場合は message/artifact/run event を作らず、`inter_agent_message_denied` audit event だけを ref-only で残す。
- `tests/security/test_secretbroker_inter_agent_token.py` で reason_code exactness、raw token 非露出、message/artifact/run event 非作成を固定した。

### 2026-05-24 closeout verification

- `uv run ruff check backend/app/services/inter_agent backend/app/schemas/inter_agent.py backend/app/db/models/inter_agent_message.py tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py tests/security/test_secretbroker_inter_agent_token.py tests/db/test_backup_restore_inter_agent.py tests/runtime/test_agent_run_events.py` PASS。
- `PYTHONPATH=cli uv run mypy backend/app/services/inter_agent backend/app/schemas/inter_agent.py backend/app/db/models/inter_agent_message.py tests/inter_agent tests/audit/test_inter_agent_no_raw_payload.py tests/security/test_secretbroker_inter_agent_token.py tests/db/test_backup_restore_inter_agent.py tests/runtime/test_agent_run_events.py` PASS。
- `PYTHONPATH=cli TASKMANAGEDAI_DATABASE_URL=<local test db> TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/inter_agent/test_12_fields_schema.py tests/inter_agent/test_publisher_service.py tests/inter_agent/test_consumer_service.py tests/inter_agent/test_trusted_instruction.py tests/audit/test_inter_agent_no_raw_payload.py tests/security/test_secretbroker_inter_agent_token.py tests/db/test_backup_restore_inter_agent.py tests/runtime/test_agent_run_events.py -q` PASS (`69 passed`)。
- `TASKMANAGEDAI_DATABASE_URL=<local test db> uv run alembic downgrade 0029_sp0045_tool_registry_core` → `uv run alembic upgrade head` → `uv run alembic current` PASS (`0031_sp016_api_capability_tokens (head)`)。
- `TASKMANAGEDAI_DATABASE_URL=<local test db> uv run alembic check` は既知 infrastructure debt (`migrations/env.py` が `target_metadata` を context に渡していない) で失敗。SP-015 migration 自体の downgrade→upgrade は PASS 済みのため、Sprint 完了判定では carry-over として分離する。
