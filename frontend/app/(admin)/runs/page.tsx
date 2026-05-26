/**
 * Sprint 9 BL-0106: Agent Runs timeline (P0 UI skeleton).
 *
 * Server Component display only. AgentRun 16 states and blocked_reason 3
 * categories stay fixed; this page visualizes them without adding dispatcher
 * behavior or caller-supplied execution paths.
 */

import {
  AdminPageShell,
  AgentRunEventTimeline,
  AgentRunStateGraph,
  BlockedReasonList,
  ContextSnapshotDefinitionList,
  KeyboardReadinessStrip,
  Panel
} from "../_components/sprint9-admin-ui";

export const dynamic = "force-dynamic";

export default function AgentRunsPage() {
  return (
    <AdminPageShell
      description="Sprint 9 BL-0106 skeleton with LangSmith inspired state graph, AgentOps inspired chronological events, and server-owned ContextSnapshot metadata anchors."
      eyebrow="Admin / Runs"
      regionLabel="Agent Runs"
      title="Agent Runs"
    >
      <KeyboardReadinessStrip current="Agent Runs" />

      <Panel
        description="CSS grid graph keeps the AgentRun enum at exactly 16 states while making the normal path, terminal states, and blocked node scannable."
        title="Execution graph"
        titleId="agent-runs-execution-graph"
      >
        <AgentRunStateGraph />
      </Panel>

      <Panel
        description="blocked_reason is rendered as a separate sub-category list, not as additional AgentRun statuses."
        title="blocked_reason fixed set"
        titleId="agent-runs-blocked-reasons"
      >
        <BlockedReasonList />
      </Panel>

      <Panel
        description="Chronological event rows keep run_queued, runner_started, runner_completed, and repo_pr_opened visible for P0 observability."
        title="AgentRunEvent timeline"
        titleId="agent-runs-event-timeline"
      >
        <AgentRunEventTimeline />
      </Panel>

      <Panel
        description="Each graph node links conceptually to the same immutable 10-column snapshot contract. Values are intentionally not expanded in this skeleton."
        title="ContextSnapshot metadata contract"
        titleId="agent-runs-context-snapshot"
      >
        <ContextSnapshotDefinitionList />
      </Panel>
    </AdminPageShell>
  );
}
