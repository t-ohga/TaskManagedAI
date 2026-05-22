# task-01 batch 0d Self-Plan-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0d Tool Registry network enum + tool_network_policies
- protocol: `00-codex-behavior-guide.md` §3.1 Self-Plan-Review
- read inputs:
  - `docs/sprints/SP-014_orchestrator_agent.md`
  - `docs/adr/00027_tool_registry_security_boundary.md`
  - `docs/基本設計/02_データモデル.md`
  - existing migrations/models/tests

## Round 1 findings (structure)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-B0D-PLAN-R1-F001 | HIGH | ADR numbering | Startup prompt points to ADR-00021, but ADR-00021 already exists for host portable deployment. | adopt | Do not overwrite existing ADR; create ADR-00030 for Tool Registry network enum and reference ADR-00027. |
| SP014-B0D-PLAN-R1-F002 | HIGH | DB reality | `tool_registry` is documented in DD-02 but no migration/model exists in the current repo. | adopt | Create `tool_registry` with enum directly instead of a boolean migration, plus `tool_network_policies`. |
| SP014-B0D-PLAN-R1-F003 | MEDIUM | deny-only seed | Registering web_fetch/docs_search could be misread as network allow. | adopt | Seed both tools with `network_access='none'`, `manifest.deny_only=true`, and service guard denial. |
| SP014-B0D-PLAN-R1-F004 | MEDIUM | new tenant drift | Existing tenant seed alone leaves new tenants without default deny-only tool rows. | adopt | Add tenant trigger to seed web_fetch/docs_search for every new tenant. |

## Round 2 findings (adversarial)

| id | severity | category | symptom | judgment | implementation decision |
|---|---|---|---|---|---|
| SP014-B0D-PLAN-R2-F001 | HIGH | direct internet bypass | If `internet` is an enum value, a service could treat it as allow. | adopt | Service guard always denies `internet` in P0 with `tool_network_internet_denied`; test covers it. |
| SP014-B0D-PLAN-R2-F002 | HIGH | allowlist overmatch | Suffix or wildcard domain matching could allow `evil.example.com`. | adopt | Exact bare-domain matching only; URL path/scheme/port values are rejected. |
| SP014-B0D-PLAN-R2-F003 | MEDIUM | payload leak | Allowlist without data-class cap could leak confidential/PII payloads. | adopt | `payload_data_class_max` ordinal comparison and negative test for over-cap payload. |
| SP014-B0D-PLAN-R2-F004 | MEDIUM | provider ambiguity | Some network tools need provider binding but caller may omit it. | adopt | `provider_required` in `tool_network_policies`; service denies missing provider. |

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0 after adopted plan adjustments
- deferred findings: 0
- verdict: READY for batch 0d implementation
