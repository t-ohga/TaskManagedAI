/**
 * Sprint 9 BL-0104: Ticket detail (P0 UI skeleton).
 *
 * Acceptance Criteria, evidence, AgentRun mapping, and ContextSnapshot metadata
 * are rendered as server-owned display surfaces. AI output remains candidate
 * artifact material until approval flow accepts it.
 */

import { notFound } from "next/navigation";

import { UUID_V1_TO_V5_PATTERN } from "../../_lib/route-id";
import {
  AdminPageShell,
  ContextSnapshotDefinitionList,
  KeyboardReadinessStrip,
  Panel,
  SecretBoundaryNotice
} from "../../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

type TicketDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function TicketDetailPage({ params }: TicketDetailPageProps) {
  const { id } = await params;

  // F-P2R1-007 + F-P3R1-006: shared UUID v1-v5 guard prevents caller-supplied
  // path values from reaching downstream layers (server-owned-boundary).
  if (!id || !UUID_V1_TO_V5_PATTERN.test(id)) {
    notFound();
  }

  return (
    <AdminPageShell
      description={
        <>
          Sprint 9 BL-0104 skeleton for ticket <code>{id}</code>. The page keeps
          Acceptance Criteria, evidence, AgentRun mapping, and ContextSnapshot 10
          columns visible without exposing raw snapshot values.
        </>
      }
      eyebrow="Admin / Ticket"
      regionLabel="Ticket detail"
      title="Ticket detail"
    >
      <KeyboardReadinessStrip current="Tickets" />

      <Panel
        description="Acceptance Criteria are operator-facing requirements. EvalResult and approval binding remain server-side."
        title="Acceptance Criteria"
        titleId="ticket-detail-acceptance-criteria"
      >
        <ol className="grid gap-2 text-sm text-muted">
          <li className="rounded-md border border-line bg-white p-3">
            AC-001: Ticket scope, action class, and reviewer-visible risk summary are
            resolved inside the project boundary.
          </li>
          <li className="rounded-md border border-line bg-white p-3">
            AC-002: AI generated artifact stays candidate output until approval binding
            succeeds.
          </li>
          <li className="rounded-md border border-line bg-white p-3">
            AC-HARD-02: secret values and provider raw payloads are excluded from
            evidence display.
          </li>
        </ol>
      </Panel>

      <Panel
        description="Evidence is represented through stable hashes and citation IDs. The UI does not fetch external raw source bodies in this skeleton."
        title="Evidence / Claim / Citation"
        titleId="ticket-detail-evidence"
      >
        <dl className="grid gap-2 md:grid-cols-3">
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              claim_id
            </dt>
            <dd className="mt-2 font-mono text-xs text-ink">claim.ticket.scope.p0</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              source binding
            </dt>
            <dd className="mt-2 font-mono text-xs text-ink">source_id + citation hash</dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt className="text-xs font-semibold uppercase tracking-normal text-muted">
              evidence_set_hash
            </dt>
            <dd className="mt-2 text-sm text-muted">
              fixed in ContextSnapshot, raw source body omitted.
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="Ticket to AgentRun remains a 1:N server-owned mapping. status and blocked_reason are not collapsed into a single enum."
        title="AgentRun Mapping"
        titleId="ticket-detail-agentrun-mapping"
      >
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
            <caption className="sr-only">
              Ticket to AgentRun mapping with status and blocked_reason separated.
            </caption>
            <thead className="bg-slate-50 text-xs uppercase tracking-normal text-muted">
              <tr>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  run_ref
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  status
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  blocked_reason
                </th>
                <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
                  approval invariant
                </th>
              </tr>
            </thead>
            <tbody>
              <tr className="align-top">
                <th scope="row" className="border-b border-line px-3 py-2">
                  <code className="font-mono text-xs text-ink">agent_run.latest</code>
                </th>
                <td className="border-b border-line px-3 py-2">
                  <code className="font-mono text-xs text-ink">waiting_approval</code>
                </td>
                <td className="border-b border-line px-3 py-2 text-muted">null unless blocked</td>
                <td className="border-b border-line px-3 py-2 text-muted">
                  requester actor cannot approve own artifact.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        description="Vault / Doppler inspired metadata layout: 10 fixed ContextSnapshot columns, structured as a definition list, with raw values omitted."
        title="ContextSnapshot 10 columns"
        titleId="ticket-detail-context-snapshot"
      >
        <ContextSnapshotDefinitionList />
      </Panel>

      <Panel
        description="Provider continuation and request fingerprint are references for binding and replay safety, not raw provider payload display."
        title="Secret and provider payload boundary"
        titleId="ticket-detail-secret-boundary"
      >
        <SecretBoundaryNotice title="Ticket detail SecretBroker boundary" />
      </Panel>
    </AdminPageShell>
  );
}
