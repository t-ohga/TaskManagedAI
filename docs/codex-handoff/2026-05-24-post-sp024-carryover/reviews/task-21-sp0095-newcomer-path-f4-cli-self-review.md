# task-21 SP-009-5 Batch F4 CLI Self Review

## Scope Reviewed

- `tm` command registry.
- New read-only `context` and `doctor` commands.
- New response-only onboarding dry-run CLI wiring.
- CLI capability classification and tests.
- CLI README newcomer path notes.

## Findings

| finding | severity | decision | resolution |
|---|---|---|---|
| New `context_show`, `doctor`, and `onboarding_dry_run` capabilities could be treated as mutating because they are outside the SP-016 13-capability matrix. | HIGH | adopt | Added them to `READ_ONLY_CAPABILITIES` while keeping `ALL_CAPABILITIES` unchanged. |
| `tm run plan` without an explicit dry-run flag could imply a real AgentRun start. | HIGH | adopt | `--dry-run` is required by argparse; missing it exits before a request is built. |
| `tm ticket intake` could look like ticket creation. | MEDIUM | adopt | `--guided` is required and maps only to the response-only onboarding dry-run endpoint. |
| CLI docs could drift back to stale `tmai` wording. | MEDIUM | adopt | `cli/README.md` states `tm` is canonical and `tmai` is non-canonical. |

## Invariant Checklist

- [x] No ticket, AgentRun, approval, approval revision, notification, audit, repository operation, provider call, capability token, merge, deploy, or persisted onboarding state is created by F4.
- [x] New onboarding CLI commands use the response-only dry-run endpoint.
- [x] Missing `--dry-run` / `--guided` fails before network.
- [x] `secret_access`, `merge`, `deploy`, and `provider_call` remain approval-gated by existing capability policy.
- [x] Raw operation tokens remain runtime-only and redacted in output.

## Verification

- passed: `uv run ruff check cli/tm tests/cli/test_tm_cli_foundation.py`
- passed: `PYTHONPATH=cli uv run mypy cli/tm tests/cli/test_tm_cli_foundation.py`
- passed: `uv run pytest tests/cli/test_tm_cli_foundation.py -q` (`45 passed`)

## Residual

- F5 closeout was closed by task-22.
