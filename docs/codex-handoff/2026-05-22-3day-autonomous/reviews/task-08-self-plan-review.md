# task-08 Self-Plan-Review

Date: 2026-05-22 JST

## Scope

- Documentation drift fix after task-01 through task-07 completion.
- Docs-only changes.
- Primary inventory:
  - AgentRun event_type wording and source paths
  - SP-014 Sprint Pack completion state
  - SP-012-9 historical skeleton wording vs current completed state
  - stale placeholder migration / schema / frontend enum paths

## Round 1 inventory

- `.claude/rules/agentrun-state-machine.md` already had the correct 28→37
  heading but still referenced placeholder migration and stale source paths.
- `docs/adr/00004_agentrun_state_machine.md` still treated the old Phase D/E
  31-type proposal as the live numbering path in some paragraphs.
- `docs/sprints/SP-014_orchestrator_agent.md` was still `status: ready`,
  lacked `completed_at`, and still used the old 31-type wording.
- `docs/sprints/SP-012-9_ui_wiring_completion.md` mixed historical PR #109
  state with current completed state.
- `docs/codex-handoff/.../tasks/*` and verification checklist still had
  outdated event_type wording or placeholder migration names.

## Adopt / defer

- T08-PLAN-F001 / HIGH / adopt:
  - finding: SP-014 Sprint Pack frontmatter did not reflect task-01 completion.
  - planned fix: mark completed, add `completed_at`, and add Review entries.
- T08-PLAN-F002 / HIGH / adopt:
  - finding: AgentRun event_type docs still mixed historical 31-type proposal
    with final accepted 28→37 numbering.
  - planned fix: make 28→37 current source explicit and keep older 22→25
    only as Sprint 5.5 history.
- T08-PLAN-F003 / MEDIUM / adopt:
  - finding: rules referenced placeholder source paths for the event_type 37
    migration.
  - planned fix: replace with implemented paths:
    `0025_sp014_event_type_37.py`,
    `backend/app/domain/agent_runtime/event_type.py`,
    `backend/app/schemas/agent_run_event.py`,
    `tests/runtime/test_agent_run_events.py`, and
    `frontend/lib/api/agent-runs.ts`.
- T08-PLAN-F004 / MEDIUM / adopt:
  - finding: SP-012-9 body still read like Tickets and Audit wiring were
    unclosed.
  - planned fix: mark those lines as historical kickoff snapshot and add current
    closure wording.
- T08-PLAN-F005 / MEDIUM / defer:
  - finding: repo-wide markdownlint still has large pre-existing line-length /
    heading style debt in older Sprint Packs.
  - reason: task-08 owns semantic drift, not whole-doc reformatting.

## Readiness gate

- CRITICAL: 0
- HIGH open: 0 after planned adoption
- status: READY for docs-only implementation
