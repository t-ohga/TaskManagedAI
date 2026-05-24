# task-05: SP-009-5 Split Docs

## Purpose

Split the SP-009 deferred UI surfaces into an explicit P0.1 Sprint Pack before any additional UI or approval-state implementation starts.

## Current Evidence

- SP-009 is still `partial_skeleton`.
- PRs #224/#225 closed route reconciliation and contract/redaction test cleanup, but not golden E2E, DOM secret scan, PayloadDataClass/future AuditEventType registry drift, or SP-009-5 scope split.
- SP-009 QL-E already reserved Today/Inbox, unified timeline, notification triage, minimal KPI strip, Newcomer Path, and `request_revision` as U-02 / U-03 gated P0.1 candidates.

## Scope

- Create `docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md`.
- Update the sprint registry, SP-009 cross-reference, P0 backlog, current-state handoff, and task matrix.
- Keep the change docs-only; do not add migrations, API routes, UI code, or approval state transitions.

## Non-Goals

- No code changes.
- No DB migration.
- No `request_revision` implementation.
- No notification triage schema or lifecycle implementation.
- No SP-009 status promotion to `completed`.

## Verification

```bash
ruby -e 'require "yaml"; require "date"; YAML.safe_load(File.read("docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md"), permitted_classes: [Date], aliases: true); puts "ok"'
printf '{"tool_input":{"file_path":"%s"}}\n' "$(pwd)/docs/sprints/SP-009-5_p0_ui_deferred_surfaces.md" | .claude/hooks/sprint/check-sprint-pack-frontmatter.sh
rg -n "SP-009-5_p0_ui_deferred_surfaces|SP-009-5" docs/sprints docs/実装計画 docs/codex-handoff/2026-05-24-post-sp024-carryover
git diff --check
```
