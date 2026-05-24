---
id: "sp016-kickoff-blockers-completion-report"
status: "completed"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# SP-016 Kickoff Blocker Closure Report

## Summary

SP-016 is now implementation-ready as a plan: ADR-00015 is accepted, `tm` is canonical, non-parity commands are scoped out of the 13 parity contract, `api_capability_tokens` implementation constraints are fixed, and Tailscale config changes remain behind the external-exposure gate.

## Changed Files

- `docs/adr/00015_ui_cli_parity.md`
- `docs/cli/README.md`
- `docs/sprints/SP-016_ui_cli_parity.md`
- `tests/cli/test_dogfooding_seed.py`

## Verification

- PASS: `git diff --check`
- PASS: `.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-016_ui_cli_parity.md`
- PASS: `uv run ruff check tests/cli/test_dogfooding_seed.py`
- PASS: `uv run mypy tests/cli/test_dogfooding_seed.py`
- PASS: `uv run pytest tests/cli/test_dogfooding_seed.py -q` (`24 passed`)

## Next

Start SP-016 implementation in a separate branch from latest `main`: migration `0031_sp016_api_capability_tokens.py`, CLI auth endpoint, `cli/tm` entry point, and parity contract tests.
