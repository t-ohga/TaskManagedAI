# task-03 self review: SP-007 Phase 5 Helper Code

## Scope

- Add repo-only manifest generation and trust-root verification helpers.
- Add `TASKMANAGEDAI_HOOK_STATE_DIR` support to Bash snapshot hooks.
- Add temp-home tests that do not read or write the real user trust root.

## Findings

| finding | severity | decision | result |
|---|---|---|---|
| Helper scripts might silently write into `~/.claude-trusted`. | HIGH | adopt | `regenerate-hook-manifest.sh` requires `--output` or `--stdout`; install remains a separate operator step. |
| Tests might mutate the real user HOME. | HIGH | adopt | Tests create a temp trust root and pass explicit `--trust-root` / `--state-root`; no real HOME paths are used. |
| Manifest verification could pass even if child hooks lose executable bits. | HIGH | adopt | Manifest generation rejects non-executable `.claude/hooks/**/*.sh`; verify checks wrapper executable bit. |
| Dispatcher state movement could be only partially implemented. | MEDIUM | adopt | Pre/Post scripts both honor `TASKMANAGEDAI_HOOK_STATE_DIR`, with repo-local default preserved until activation. |
| PostToolUse without a writable state dir could fall back unsafely. | MEDIUM | adopt | Post dispatcher now fails closed when the selected state dir is missing or unwritable. |

## Verification

- [x] `bash -n scripts/regenerate-hook-manifest.sh`
- [x] `bash -n scripts/verify-hook-trust-root.sh`
- [x] `bash -n .claude/hooks/system/pretool-bash-snapshot.sh`
- [x] `bash -n .claude/hooks/system/posttool-bash-file-dispatcher.sh`
- [x] `uv run pytest tests/harness/test_hook_trust_boundary.py -q`
- [x] `uv run ruff check tests/harness/test_hook_trust_boundary.py`
- [x] `PYTHONPATH=cli uv run mypy tests/harness/test_hook_trust_boundary.py`
- [x] `git diff --check`

## Verdict

`READY_FOR_PR`: repo-only Phase 5A/B helper scope is complete. Phase 5C remains blocked on explicit machine-local approval.
