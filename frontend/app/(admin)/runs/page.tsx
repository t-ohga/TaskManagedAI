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
      description="Sprint 9 BL-0106 skeleton。LangSmith inspired state graph、AgentOps inspired chronological events、server-owned ContextSnapshot metadata anchor を表示します。"
      eyebrow="管理 / AI 実行"
      regionLabel="AI 実行"
      title="AI 実行"
    >
      <KeyboardReadinessStrip current="Agent Runs" />

      <Panel
        description="CSS grid graph で AgentRun enum を固定 16 状態のまま表示し、normal path、terminal state、blocked node を確認しやすくします。"
        title="実行グラフ"
        titleId="agent-runs-execution-graph"
      >
        <AgentRunStateGraph />
      </Panel>

      <Panel
        description="blocked_reason は AgentRun status に追加せず、独立したサブ分類として表示します。"
        title="blocked_reason 固定セット"
        titleId="agent-runs-blocked-reasons"
      >
        <BlockedReasonList />
      </Panel>

      <Panel
        description="時系列 event row で run_queued、runner_started、runner_completed、repo_pr_opened を P0 observability 用に表示します。"
        title="AgentRunEvent タイムライン"
        titleId="agent-runs-event-timeline"
      >
        <AgentRunEventTimeline />
      </Panel>

      <Panel
        description="各 graph node は同じ immutable 10-column snapshot contract に対応します。この skeleton では値を意図的に展開しません。"
        title="ContextSnapshot metadata contract"
        titleId="agent-runs-context-snapshot"
      >
        <ContextSnapshotDefinitionList />
      </Panel>
    </AdminPageShell>
  );
}
