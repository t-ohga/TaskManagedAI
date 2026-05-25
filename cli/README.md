# TaskManagedAI CLI

`tm` is the project-user CLI for SP-016 UI/CLI parity.

This package intentionally stores no raw operation token in the profile file. Runtime
operation tokens can be supplied through environment variables until keyring/SOPS
storage is wired in a later batch.

## Newcomer Path

SP-009-5 Batch F4 keeps `tm` as the canonical CLI spelling. The older `tmai`
spelling remains non-canonical and should not be used in new docs or tests.

Safe first-use commands:

```bash
tm context show
tm doctor
tm ticket intake --guided --purpose "Plan the first task" --expected-artifact "reviewed plan"
tm run plan --dry-run --purpose "Plan the first task" --expected-artifact "reviewed plan"
```

`tm ticket intake --guided` and `tm run plan --dry-run` call the response-only
dry-run onboarding endpoint. They do not create tickets, AgentRuns, approvals,
notifications, audit events, repository operations, provider calls, merges, or
deployments. Omitting `--guided` or `--dry-run` fails before any network request.
