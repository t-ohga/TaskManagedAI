# task-04: SP-016 Inventory / Plan-Only

## scope

SP-016 UI CLI parity の準備調査。
本 task では code implementation をしない。

## inputs

- `docs/sprints/SP-016_ui_cli_parity.md`
- `docs/cli/README.md`
- `docs/sprints/SP-015_inter_agent_communication.md`
- `docs/adr/00015_ui_cli_parity.md`
- `docs/adr/00007_external_exposure.md`

## allowed work

- capability matrix の現状確認。
- SP-015 完了前に実装できない command を分類。
- CLI token / SecretBroker / Tailscale boundary の open question を列挙。
- SP-016 kickoff readiness を更新するための docs-only proposal。

## not allowed

- `tm` CLI implementation.
- api_capability_tokens migration.
- CLI auth endpoint.
- Tailscale grants change.
- parity contract test implementation.

## outputs

- `reviews/task-04-self-plan-review.md`
- `completion/task-04-completed.md`
- optional docs-only note if drift is found.

## DoD checklist

- [x] no code changes.
- [x] SP-016 dependency on SP-015 is explicit.
- [x] command inventory is current.
- [x] carry-over to SP-016 implementation is clear.
- [x] no SP-015 scope is duplicated.
