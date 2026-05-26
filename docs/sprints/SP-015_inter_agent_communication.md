---
id: "SP-015_inter_agent_communication"
type: "heavy"
status: "draft"
sprint_no: 15
created_at: "2026-05-10"
updated_at: "2026-05-10"
target_days: 3
max_days: 5
adr_refs: []
planned_adr_refs:
  - "[ADR-00018](../adr/00018_inter_agent_communication.md) # SP-015 着手時に proposed → accepted (Criteria #2 + #3)"
  - "[ADR-00004 update](../adr/00004_agentrun_state_machine.md) # event_type 22→31 + audit_events payload schema (Criteria #3)"
related_sprints:
  - "SP-013_multi_agent_orchestration"
  - "SP-014_orchestrator_agent"
risks:
  - "PE-F-002 (atomic consume SQL の receiver eligibility 抜け)"
  - "PE-F-005 (sanitizer_version drift で stale memory 混入)"
  - "PE-F-014 (SecretBroker inter-agent message token payload negative case)"
---

最終更新: 2026-05-10

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
- **atomic consume SQL の receiver eligibility (PE-F-002)**: receiver_kind=agent_run/role/broadcast ごとに direct child membership 検証を WHERE に含める
- **trusted_instruction promotion**: human approval 済 + server-owned refs 6 fields 完全揃い必須 (DB CHECK + service guard + Pydantic + test 4 重防御)
- **sanitizer_version 整合 (PE-F-005)**: SP-013 で投入済の sanitizer_policy_versions と一致確認、drift は stale_sanitizer deny or re-sanitize

## 実装チケット

- SP015-T01: inter_agent_messages table + 12 fields + 全 FK 複合 + 3 trust_level CHECK + atomic consume index
- SP015-T02: publisher service (sender) + sanitizer pipeline + secret canary scan + payload_data_class 算出
- SP015-T03: consumer service (receiver) + atomic consume SQL + receiver eligibility + replay/hijack defense
- SP015-T04: trust_level=trusted_instruction 4 重防御 (DB CHECK + service guard + Pydantic + test) + approval target 4 整合 verify
- SP015-T05: audit_events 3 種 (sent/consumed/denied) 必須 payload schema + assert_no_raw_secret_and_no_raw_message_body test helper
- SP015-T06: AgentRunEvent ref event 28/29 (inter_agent_message_sent_ref / consumed_ref) 追加 (event_type 31 exact set 内)
- SP015-T07: backup/restore drill 拡張 (5 検証項目 = parent/child AgentRun FK + inter_agent_messages seq/hash/consume state + agent_roles soft-delete + memory_records source FK + audit_events correlation)
- SP015-T08: SecretBroker inter-agent message token payload negative case (PE-F-014 の 6 case のうち inter-agent 関連 1 つを SP-015 で must_ship)

## タスク一覧

- [ ] SP015-T01-T08 を順次実装
- [ ] ADR-00018 + ADR-00004 update を proposed → accepted
- [ ] migration `00NN_p0_1_inter_agent_messages.py` + `alembic check` PASS
- [ ] 100 並行 atomic consume → 1 件のみ成功 verify
- [ ] replay 攻撃 fixture / hijack 攻撃 fixture 全件 deny
- [ ] backup/restore drill 5 検証項目 verify

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| inter_agent_messages table 12 fields | ○ | - |
| atomic consume + replay/hijack defense | ○ | - |
| 3 trust_level + sanitizer pipeline | ○ | - |
| trusted_instruction 4 重防御 | ○ | - |
| 3 audit_events 必須 payload | ○ | - |
| AgentRunEvent ref event 28/29 | ○ | - |
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
uv run pytest tests/inter_agent/test_12_fields_schema.py \
              tests/inter_agent/test_atomic_consume.py \
              tests/inter_agent/test_replay_protection.py \
              tests/inter_agent/test_hijack_protection.py \
              tests/inter_agent/test_3_trust_level.py \
              tests/inter_agent/test_sanitizer_pipeline.py \
              tests/inter_agent/test_audit_events.py \
              tests/audit/test_inter_agent_no_raw_payload.py \
              tests/security/test_secretbroker_inter_agent_token.py \
              tests/db/test_backup_restore_inter_agent.py \
              tests/agent_runtime/test_event_type_enum.py -q

uv run alembic check && uv run alembic upgrade head
```

## レビュー観点

- atomic consume SQL の WHERE が tenant/project/parent_run scope + receiver eligibility を完全表現
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
- ADR-00004 update (event_type 22→31) — 同上
- ADR-00014 (関連)

## Review

(SP-015 完了時に追記)
