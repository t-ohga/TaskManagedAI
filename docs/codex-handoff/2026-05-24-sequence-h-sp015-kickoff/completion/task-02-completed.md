# task-02 Completed: SP-015 Self-Plan-Review

## status

- status: completed
- completed_at: 2026-05-24
- branch:
  `codex/sequence-h-sp015-kickoff-2026-05-24`
- implementation: docs / plan gate only

## summary

SP-015 inter-agent communication の実装前計画をレビューし、
実装前に修正すべき drift を採用修正した。

主な修正:

- SP-015 / ADR-00018 の古い event_type 22→31 / event 28/29 表現を
  ADR-00004 current 37 event_type / event 34/35 に同期。
- accepted 済み ADR-00004 を SP-015 frontmatter の `adr_refs` に移送。
- ADR-00018 receiver eligibility SQL に `project_id` 条件を追加。
- ADR-00018 unique constraints に `project_id` を追加。
- `data_class` 表記を `payload_data_class` に統一。
- `12 fields` 表記を歴史的 shorthand とし、ADR-00018 §1 の exact
  column set を実装正本に指定。

## readiness

- unresolved CRITICAL: 0
- unresolved HIGH: 0
- task-03 status: READY

## verification

```bash
rg -n "event_type|inter_agent|28|31|37" \
  docs/adr/00004_agentrun_state_machine.md \
  docs/adr/00018_inter_agent_communication.md \
  docs/sprints/SP-015_inter_agent_communication.md

rg -n "data_class|payload_data_class|unique \\(tenant_id|project_id" \
  docs/adr/00018_inter_agent_communication.md \
  docs/sprints/SP-015_inter_agent_communication.md
```

Manual review result:

- ADR-00004 current source set: 37 event types.
- `inter_agent_message_sent_ref`: event 34.
- `inter_agent_message_consumed_ref`: event 35.
- SP-015 implementation must not allocate new AgentRunEvent event types unless
  a separate ADR/source-set update is made.

## findings

| id | severity | decision | result |
|---|---|---|---|
| T02-R1-001 | HIGH | adopt | Event numbering drift fixed. |
| T02-R1-002 | HIGH | adopt | Receiver eligibility project boundary fixed. |
| T02-R1-003 | HIGH | adopt | Unique constraints project boundary fixed. |
| T02-R1-004 | MEDIUM | adopt | `payload_data_class` naming fixed. |
| T02-R1-005 | MEDIUM | adopt | Exact column set clarified. |
| T02-R1-006 | LOW | defer | ADR-00018 acceptance deferred to kickoff / implementation PR. |
| T02-R2-001 | HIGH | adopt | Raw payload checks made task-03 gate. |
| T02-R2-002 | HIGH | adopt | trusted_instruction four-layer defense kept as task-03 gate. |
| T02-R2-003 | MEDIUM | adopt | Event type migration scope constrained. |
| T02-R2-004 | MEDIUM | adopt | sanitizer drift behavior kept as task-03 gate. |
| T02-R2-005 | MEDIUM | defer | Exact SecretBroker reason_code deferred to implementation. |

## next

Proceed to task-03 batch 0a:
`tasks/task-03-sp015-batch-0-inter-agent-message-core.md`.
