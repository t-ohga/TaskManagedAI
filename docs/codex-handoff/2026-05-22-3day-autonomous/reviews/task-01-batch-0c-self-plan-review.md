# task-01 batch 0c Self-Plan-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0c policy_profile + ADR-00009 accepted update
- protocol: `00-codex-behavior-guide.md` §3.1 Self-Plan-Review
- read inputs:
  - `docs/codex-handoff/2026-05-22-3day-autonomous/tasks/task-01-sp014-batch-0-orchestrator.md`
  - `docs/sprints/SP-014_orchestrator_agent.md`
  - `docs/adr/00009_action_class_taxonomy.md`
  - batch 0b `review_artifacts` schema and guard

## Round 1 findings (structure)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-B0C-PLAN-R1-F001 | HIGH | tenant seed boundary | Existing tenant seed alone would not protect newly created tenants; `projects.policy_profile default 'default'` would fail FK for new tenants. | adopt | Seed existing tenants in migration and add an `after insert on tenants` trigger that creates the two profile rows and 14 action effect rows. |
| SP014-B0C-PLAN-R1-F002 | HIGH | server-owned-boundary | If `ProjectCreate.policy_profile` remains caller-supplied, a user can select `low_risk_auto_allow` and bypass intended server policy resolution. | adopt | Remove `policy_profile` from `ProjectCreate`, use `extra="forbid"`, and reject repository dict payloads containing `policy_profile`. |
| SP014-B0C-PLAN-R1-F003 | MEDIUM | traceability | `policy_decisions.decision` alone cannot explain whether profile resolution produced `allow`, `deny`, or `require_approval`. | adopt | Add `policy_profile`, `profile_resolved_effect`, and optional `required_review_artifact_id` FK to `review_artifacts`. |
| SP014-B0C-PLAN-R1-F004 | MEDIUM | seed drift | Migration SQL, Python resolver, and tests can drift on the exact 14 rows. | adopt | Add domain constants + seed helper + exact matrix test that verifies two profiles and 14 rows. |

## Round 2 findings (adversarial)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-B0C-PLAN-R2-F001 | HIGH | fail-open profile | Unknown profile or a missing action-effect row could accidentally default to allow. | adopt | Resolver fails closed to `deny` with explicit reason codes for unknown profile and missing seed row. |
| SP014-B0C-PLAN-R2-F002 | HIGH | review artifact bypass | Tier 2 allow without a review artifact reference would weaken batch 0b defenses. | adopt | `policy_decisions.required_review_artifact_id` has a tenant-scoped FK; resolver returns `require_review_artifact` so policy engine callers can enforce it. |
| SP014-B0C-PLAN-R2-F003 | MEDIUM | fixture mutation | A negative test deleting a seed row can poison later exact-seed tests in the same DB. | adopt | Mutating test restores canonical seed in `finally`; project fixture also reseeds profiles before inserts. |
| SP014-B0C-PLAN-R2-F004 | MEDIUM | doc drift | ADR-00009 and DD-02 still described `read/search` or proposed-only policy_profile semantics. | adopt | Update ADR-00009 accepted section, Sprint Pack refs, and DD-02 policy schema. |

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0 after adopted plan adjustments
- deferred findings: 0
- verdict: READY for batch 0c implementation
