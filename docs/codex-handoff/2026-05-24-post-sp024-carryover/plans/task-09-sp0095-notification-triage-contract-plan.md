# SP-009-5 Batch D Notification Triage Contract Plan

## Objective

Turn current in-app notifications into a minimal action-required triage queue without exposing raw payload values or adding approval revision semantics.

## Existing Surface

| layer | current behavior | gap |
|---|---|---|
| DB | `notification_events(event_type, payload, recipient_actor_id, read_at, created_at)` | no severity/action/due/snooze/resolved/dedupe fields |
| Repository | append, list, count unread, mark read | no actor-owned resolve/snooze transitions |
| API | list returns raw `payload`; mark-read mutates `read_at` | no redacted triage response; no state filter |
| UI | `/notifications` shows event type, created time, mark-read | no action-required priority/due view |
| Tests | recipient ownership, badge count, mark-read | no lifecycle/dedupe/redaction tests |

## Data Contract

Add columns to `notification_events`:

| column | type | null/default | rule |
|---|---|---|---|
| `severity` | text | not null default `info` | enum: `info`, `low`, `medium`, `high`, `critical` |
| `required_action` | text | not null default `acknowledge` | enum: `acknowledge`, `review_approval`, `inspect_run`, `resolve_blocker`, `external_followup` |
| `due_at` | timestamptz | nullable | optional SLA target |
| `snoozed_until` | timestamptz | nullable | must be future when set by API |
| `resolved_at` | timestamptz | nullable | terminal for triage lifecycle |
| `resolved_by_actor_id` | uuid | nullable | composite FK to `actors(tenant_id, id)`; required when `resolved_at` is set |
| `dedupe_key` | text | nullable | server-computed; public API never accepts caller-supplied value |

Indexes/constraints:

- `notification_events_ck_severity`
- `notification_events_ck_required_action`
- `notification_events_ck_resolved_consistency`: `resolved_at` and `resolved_by_actor_id` both null or both non-null.
- `notification_events_idx_triage_open`: `(tenant_id, recipient_actor_id, severity, due_at, created_at)` where `resolved_at is null`.
- `notification_events_uq_open_dedupe`: unique `(tenant_id, recipient_actor_id, dedupe_key)` where `dedupe_key is not null and resolved_at is null`.

## API Contract

Keep existing endpoints for compatibility:

- `GET /api/v1/notifications`
- `GET /api/v1/notifications/badge_count`
- `POST /api/v1/notifications/{id}/mark_read`

Add triage endpoints:

| endpoint | request | response | invariant |
|---|---|---|---|
| `GET /api/v1/notifications/triage?state=open|snoozed|resolved|all` | query only | `NotificationTriageItem[]` | actor owns recipient scope |
| `POST /api/v1/notifications/{id}/snooze` | `{ "snoozed_until": ISO8601 }` | `NotificationTriageItem` | future timestamp, max 30 days |
| `POST /api/v1/notifications/{id}/resolve` | `{ "resolution_note": string | null }` | `NotificationTriageItem` | current actor becomes resolver |

`NotificationTriageItem`:

```python
class NotificationTriageItem(BaseModel):
    id: UUID
    event_type: str
    payload_keys: list[str]
    payload_redaction_status: Literal["keys_only"]
    severity: Literal["info", "low", "medium", "high", "critical"]
    required_action: Literal[
        "acknowledge",
        "review_approval",
        "inspect_run",
        "resolve_blocker",
        "external_followup",
    ]
    due_at: datetime | None
    snoozed_until: datetime | None
    resolved_at: datetime | None
    resolved_by_actor_id: UUID | None
    read_at: datetime | None
    created_at: datetime
```

The triage response never includes `payload` or raw payload values.

## UI Contract

Update `/notifications` after D1:

- Tabs or segmented control: Open / Snoozed / Resolved / All.
- Primary sort: unresolved first, severity desc, due_at asc, created_at desc.
- Card fields: severity, required_action, due/delay state, event_type, payload key names, created_at.
- Actions: mark read, snooze, resolve.
- No bulk action in P0.1.

## Audit Contract

Resolve and snooze operations append `audit_events` with open-string event types:

- `notification_snoozed`
- `notification_resolved`

Payload keys only:

- `notification_id`
- `event_type`
- `severity`
- `required_action`
- `snoozed_until` or `resolved_at`

No raw notification payload value is copied into audit payload.

## Verification Plan

- `uv run ruff check backend/app/api/notifications.py backend/app/repositories/notification_event.py backend/app/db/models/notification_event.py tests/api/test_notifications.py tests/db/test_schema_introspection.py`
- `uv run mypy backend/app/api/notifications.py backend/app/repositories/notification_event.py backend/app/db/models/notification_event.py`
- `uv run pytest tests/api/test_notifications.py tests/db/test_schema_introspection.py -q`
- Migration verification:
  - `uv run alembic upgrade head`
  - `uv run alembic downgrade -1`
  - `uv run alembic upgrade head`
  - `uv run alembic current`
- Frontend D2:
  - targeted Vitest for notification schema/component/page
  - `corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit`
  - touched-file eslint
  - full frontend test/lint
  - desktop/mobile browser smoke

## Rollback

1. Revert D2 UI first; old `/notifications` list/mark-read remains compatible.
2. Revert D1 API/repository code.
3. Run `uv run alembic downgrade -1` to drop additive triage columns/indexes/constraints.
4. Verify old notification tests and badge count behavior.

## Open Decisions

- Whether to keep `GET /api/v1/notifications` raw payload response indefinitely or deprecate it after triage clients move to the redacted endpoint.
- Whether `severity` should be service-supplied or derived from `event_type`. D1 should support service-supplied with safe defaults.
