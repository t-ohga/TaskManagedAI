# task-01 batch 0b Self-Plan-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0b review_artifacts 4 重防御
- protocol: `00-codex-behavior-guide.md` §3.1 Self-Plan-Review
- read inputs:
  - `docs/codex-handoff/2026-05-22-3day-autonomous/tasks/task-01-sp014-batch-0-orchestrator.md`
  - `docs/adr/00014_multi_agent_orchestration.md` §5-§6
  - `docs/adr/00009_action_class_taxonomy.md`
  - `docs/設計検討/phase-c-multi-agent-spec-draft.md` §3.3
  - existing `agent_runs`, `artifacts`, and SP-013 multi-agent migrations

## Round 1 findings (structure)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-B0B-PLAN-R1-F001 | HIGH | FK boundary | ADR-00014 SQL still shows artifact FKs as `(tenant_id, artifact_id)`, but SP-013 has already materialized `artifacts.project_id` and added `(tenant_id, project_id, id)` unique. | adopt | Use strict project-bound artifact FKs in the migration and ORM from the start. |
| SP014-B0B-PLAN-R1-F002 | HIGH | policy binding | The handoff only names `artifact_hash + action_class`, while PE-F-003 also requires `policy_version + provider_request_fingerprint` binding. | adopt | Add `target_artifact_hash`, `policy_version`, and `provider_request_fingerprint_hash` to `review_artifacts`; service guard verifies those values against the target artifact policy input payload. |
| SP014-B0B-PLAN-R1-F003 | MEDIUM | server-owned-boundary | API-facing input must not accept tenant_id/project_id or reviewer role claims. | adopt | Pydantic create schema excludes tenant/project/role fields; service resolves tenant/project via arguments and role from `agent_runs`. |
| SP014-B0B-PLAN-R1-F004 | MEDIUM | enum drift | review_artifacts uses only four action classes, not the full ADR-00009 seven. | adopt | Add a dedicated `ReviewArtifactActionClass` Literal/frozenset and assert it remains a subset of ADR-00009 `ALL_ACTION_CLASSES`. |

## Round 2 findings (adversarial)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-B0B-PLAN-R2-F001 | HIGH | approval bypass | If reviewer_run can be requester_run or a non-reviewer role, Tier 2 could self-review and bypass human approval semantics. | adopt | DB CHECK enforces `reviewer_run_id <> requester_run_id`; service guard requires reviewer role_id=`reviewer`, role_scope=`global`, and same parent run. |
| SP014-B0B-PLAN-R2-F002 | HIGH | cross-project artifact | Without project-bound artifact FKs/service guard, a review in project A could validate an artifact from project B. | adopt | DB FKs target `(tenant_id, project_id, id)` and service queries artifacts inside the same tenant/project boundary only. |
| SP014-B0B-PLAN-R2-F003 | MEDIUM | weak assertion | A test that only checks table existence would not prove the four-layer defense. | adopt | Add negative tests for DB CHECK, Pydantic `extra=forbid`/enum, service hash/action binding, reviewer role, requester identity, and cross-project artifact reference. |
| SP014-B0B-PLAN-R2-F004 | MEDIUM | trust-level drift | A reviewer could point `review_artifact_id` at unvalidated content. | adopt | Service guard requires the review artifact row itself to have `trust_level='validated_artifact'`. |

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0 after adopted plan adjustments
- deferred findings: 0
- verdict: READY for batch 0b implementation
