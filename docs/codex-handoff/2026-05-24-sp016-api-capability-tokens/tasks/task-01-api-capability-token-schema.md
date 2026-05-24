---
id: "task-01-api-capability-token-schema"
status: "completed"
priority: "P0"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# Task 01: API Capability Token Schema

## Objective

Implement SP016-T01 as a narrow batch: table, model, migration, and schema tests for principal-bound API capability tokens.

## Scope

- Store token hash only.
- Bind actor, principal, optional project, device, action scope, auth context, request binding, TTL, `jti`, and revocation state.
- Enforce tenant-scoped composite foreign keys.
- Reject metadata with raw token / secret keys.

## Non-Goals

- No auth endpoint.
- No token issue/revoke service.
- No CLI entry point.
- No Tailscale config mutation.
