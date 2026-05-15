/**
 * Sprint 9 BL-0106 detail: Agent Run detail (P0 UI skeleton).
 *
 * AgentRunEvent timeline, 16-state graph, runner event metadata, and
 * ContextSnapshot references are rendered read-only. Runner and provider raw
 * payloads stay outside the DOM.
 */

import { notFound } from "next/navigation";

import {
  AdminPageShell,
  AgentRunEventTimeline,
  AgentRunStateGraph,
  ContextSnapshotDefinitionList,
  KeyboardReadinessStrip,
  Panel,
  SecretBoundaryNotice
} from "../../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

// F-P2R1-007 fix: validate dynamic route id as UUID v1-v5 before rendering, so
// arbitrary caller-supplied strings cannot reach downstream API/data layers
// through the same entry point (server-owned-boundary invariant).
const AGENT_RUN_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

type AgentRunDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function AgentRunDetailPage({
  params
}: AgentRunDetailPageProps) {
  const { id } = await params;

  if (!id || !AGENT_RUN_ID_PATTERN.test(id)) {
    notFound();
  }

  return (
    <AdminPageShell
      description={
        <>
          Sprint 9 BL-0106 detail skeleton for AgentRun <code>{id}</code>. The
          timeline is chronological, append-only, and redacted according to
          AC-HARD-02.
        </>
      }
      eyebrow="Admin / AgentRun"
      regionLabel="Agent Run detail"
      title="Agent Run detail"
    >
      <KeyboardReadinessStrip current="Agent Runs" />

      <Panel
        description="AgentOps inspired event timeline shows the important run lifecycle events in seq_no order."
        title="Chronological AgentRunEvent timeline"
        titleId="run-detail-event-timeline"
      >
        <AgentRunEventTimeline />
      </Panel>

      <Panel
        description="LangSmith inspired graph view keeps all 16 AgentRun states visible without adding a 17th status or converting blocked_reason into statuses."
        title="Execution graph"
        titleId="run-detail-execution-graph"
      >
        <AgentRunStateGraph />
      </Panel>

      <Panel
        description="Runner events expose bounded metadata only. Raw argv, raw stdout, raw stderr, secret values, and provider raw payloads are excluded."
        title="Sprint 7 runner event integration"
        titleId="run-detail-runner-events"
      >
        <dl className="grid gap-2 md:grid-cols-3">
          <div className="rounded-md border border-line bg-white p-3">
            <dt>
              <code className="font-mono text-xs font-semibold text-ink">
                runner_started
              </code>
            </dt>
            <dd className="mt-2 text-xs leading-5 text-muted">
              workspace_id, argv_basename, argv_hash, and policy_version only.
            </dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt>
              <code className="font-mono text-xs font-semibold text-ink">
                runner_completed
              </code>
            </dt>
            <dd className="mt-2 text-xs leading-5 text-muted">
              exit_code, stdout_bytes, stderr_bytes, output_cap_exceeded, and
              scrubbed_env_keys.
            </dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt>
              <code className="font-mono text-xs font-semibold text-ink">
                runner_blocked
              </code>
            </dt>
            <dd className="mt-2 text-xs leading-5 text-muted">
              deny_category and reason_code only; maps to runtime_blocked when status
              becomes blocked.
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="ContextSnapshot references are shown as a fixed 10-column definition list. This supports graph inspection without time-travel mutation."
        title="ContextSnapshot 10 columns"
        titleId="run-detail-context-snapshot"
      >
        <ContextSnapshotDefinitionList />
      </Panel>

      <Panel
        description="The invariant is visible for reviewers and E2E checks while keeping all secret-bearing values out of the DOM."
        title="No raw secret invariant"
        titleId="run-detail-secret-invariant"
      >
        <SecretBoundaryNotice title="AC-HARD-02 AgentRunEvent redaction" />
      </Panel>
    </AdminPageShell>
  );
}
