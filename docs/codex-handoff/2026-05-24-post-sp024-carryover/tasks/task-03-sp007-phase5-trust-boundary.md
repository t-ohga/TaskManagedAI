# task-03: SP-007 Phase 5 Trust Boundary Plan

## Purpose

SP-007 is `done_with_phase5_defer`. The remaining work concerns repo-external trusted wrapper and trusted state movement. This is machine-local trust root work and must not be silently applied.

## Required Reads

1. `docs/sprints/SP-007_runner_sandbox.md`
2. `docs/adr/00012_hook_trust_boundary.md`
3. `.claude/hooks/` and `.codex/hooks.json`
4. `.claude/rules/codex-usage-policy.md`
5. `.claude/reference/` files that describe hook ownership and trust boundaries

## Output

Produce a plan that separates:

- repository documentation updates,
- testable in-repo helper code,
- repo-external file creation or modification,
- user-machine rollback steps.

## Planning Result (2026-05-24)

- Plan artifact: `../plans/task-03-sp007-phase5-trust-boundary-plan.md`
- Self-review artifact: `../reviews/task-03-sp007-phase5-plan-self-review.md`
- Verdict: `READY_FOR_PR`
- Boundary: no repo-external file creation, trusted-state migration, or `.claude/settings.json` switch is authorized by this planning artifact alone.

## Scope Rules

- Repo-external wrapper changes require explicit user confirmation at implementation time.
- In-repo tests and docs may be prepared first.
- Do not change `.claude/settings.json` or user-global trust roots without a rollback plan.
- Codex hook changes must be executable shell commands and must not rely on Claude-only variables.

## Verification Seed

```bash
.claude/hooks/sprint/check-sprint-pack-frontmatter.sh docs/sprints/SP-007_runner_sandbox.md
uv run pytest tests/harness -q
git diff --check
```
