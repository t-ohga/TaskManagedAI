---
id: "task-01-sp016-kickoff-blockers-completed"
status: "completed"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# Completion: SP-016 Kickoff Blockers

## Completed

- ADR-00015 accepted at SP-016 kickoff blocker closure.
- CLI canonical fixed to `tm`; `tmai` remains future fallback only.
- SP-016 moved to `ready` with accepted ADR refs.
- 13 capability matrix drift resolved through non-parity command policy.
- `api_capability_tokens` DDL / lifecycle / deny audit plan fixed before implementation.
- Tailscale grants config mutation remains explicitly gated.
- Stale dogfooding test expectation for SP-013 status repaired.

## Verification

- `git diff --check`
- `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-016_ui_cli_parity.md`
- `uv run ruff check tests/cli/test_dogfooding_seed.py`
- `uv run mypy tests/cli/test_dogfooding_seed.py`
- `uv run pytest tests/cli/test_dogfooding_seed.py -q`
