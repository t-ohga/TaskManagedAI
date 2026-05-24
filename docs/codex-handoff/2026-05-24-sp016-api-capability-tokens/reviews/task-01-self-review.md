---
id: "task-01-api-capability-token-schema-self-review"
status: "completed"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# Self Review: API Capability Token Schema

## Findings

| id | severity | finding | disposition |
|---|---|---|---|
| SR-001 | HIGH | Token table could accidentally store bearer token material. | Adopted: no raw token column; only `token_hash` with SHA-256 check. |
| SR-002 | HIGH | Principal binding could be cross-actor if FK used `(tenant_id, principal_id)` only. | Adopted: composite FK uses `(tenant_id, actor_id, principal_id)`. |
| SR-003 | MEDIUM | Scope array could be empty or contain non-string elements. | Adopted: JSONB non-empty array + string-element checks. |
| SR-004 | MEDIUM | Token lifecycle could allow revoked rows without timestamp or issued rows with timestamp. | Adopted: `status` + `revoked_at` consistency check. |
| SR-005 | MEDIUM | Metadata could leak raw token / secret keys. | Adopted: DB-level JSONPath metadata denylist. |

## Result

CRITICAL=0 / HIGH=0 after adopted fixes.
