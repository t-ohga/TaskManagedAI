# task-04 Self-Plan-Review: SP-016 Inventory / Plan-Only

## verdict

- task: SP-016 inventory / plan-only
- status: READY as inventory, NOT READY for implementation
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0

## scope reviewed

- `docs/sprints/SP-016_ui_cli_parity.md`
- `docs/cli/README.md`
- `docs/adr/00015_ui_cli_parity.md`
- `docs/adr/00007_external_exposure.md`
- `docs/sprints/SP-015_inter_agent_communication.md`

## inventory result

SP-016 can be prepared now, but implementation must wait for its own kickoff gate:

- SP-015 dependency is now satisfied by task-03 completion.
- ADR-00015 is still `proposed`.
- CLI canonical `tm` vs `tmai` remains unresolved.
- 13 capability matrix and SP016-T04 command module list have a drift:
  `message/audit/export/sprint` commands are listed as modules, but are not mapped to the 13 capability matrix.
- Tailscale `tag:taskhub-cli` must be treated as an external exposure diff if config changes are made.

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T04-R1-001 | HIGH | premature implementation | adopt | No CLI code, endpoint, migration, or grants change was made. |
| T04-R1-002 | HIGH | capability matrix drift | adopt | SP-016 now records the `message/audit/export/sprint` vs 13 capability mismatch as a pre-implementation blocker. |
| T04-R1-003 | MEDIUM | ADR status drift | adopt | ADR-00015 remains proposed; implementation must not start before acceptance. |
| T04-R1-004 | MEDIUM | CLI canonical ambiguity | adopt | U-04 `tm` vs `tmai` is recorded as a kickoff decision, not inferred. |
| T04-R1-005 | MEDIUM | SP-015 duplication | adopt | SP-016 note references SP-015 backend as dependency only; it does not duplicate SP-015 implementation scope. |

## kickoff checklist for SP-016 implementation

- [ ] Decide CLI canonical: `tm` or `tmai`.
- [ ] Accept ADR-00015 after updating token DDL / event schema / parity contract details.
- [ ] Resolve 13 capability matrix vs command-module drift.
- [ ] Keep `tm memory` disabled until SP-018 accepted.
- [ ] Treat `api_capability_tokens` as high-risk DB/API contract work.
- [ ] Add SecretBroker CLI token misuse and scope mismatch negatives separately from SP-015 token payload negative.
- [ ] Keep `taskhub` host/admin CLI separate from project-user CLI.

## verification

```bash
rg "Kickoff Inventory|SP015-T08|inter_agent_message_token_payload|message/audit/export/sprint" \
  docs/sprints/SP-016_ui_cli_parity.md \
  docs/sprints/SP-015_inter_agent_communication.md \
  docs/codex-handoff/2026-05-24-sequence-h-sp015-kickoff
# PASS: expected inventory markers found
```

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted docs-only blocker notes
- Task-04 can close as plan-only.
