/**
 * Sprint 9 BL-0106 detail: Agent Run detail (P0 UI skeleton).
 *
 * AgentRunEvent timeline, 16-state graph, runner event metadata, and
 * ContextSnapshot references are rendered read-only. Runner and provider raw
 * payloads stay outside the DOM.
 */

import { notFound } from "next/navigation";

import { UUID_V1_TO_V5_PATTERN } from "../../_lib/route-id";
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

type AgentRunDetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function AgentRunDetailPage({
  params
}: AgentRunDetailPageProps) {
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
          AgentRun <code>{id}</code> の Sprint 9 BL-0106 detail skeleton です。
          timeline は時系列、append-only、かつ AC-HARD-02 に従って redaction 済みです。
        </>
      }
      eyebrow="管理 / AI 実行"
      regionLabel="AI 実行詳細"
      title="AI 実行詳細"
    >
      <KeyboardReadinessStrip current="Agent Runs" />

      <Panel
        description="AgentOps inspired event timeline で重要な run lifecycle event を seq_no 順に表示します。"
        title="AgentRunEvent 時系列タイムライン"
        titleId="run-detail-event-timeline"
      >
        <AgentRunEventTimeline />
      </Panel>

      <Panel
        description="LangSmith inspired graph view で 17 個目の status を追加せず、blocked_reason も status 化せずに 16 状態を表示します。"
        title="実行グラフ"
        titleId="run-detail-execution-graph"
      >
        <AgentRunStateGraph />
      </Panel>

      <Panel
        description="Runner events は bounded metadata のみを表示します。raw argv、raw stdout、raw stderr、secret 値、provider raw payload は除外します。"
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
              workspace_id、argv_basename、argv_hash、policy_version のみ。
            </dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt>
              <code className="font-mono text-xs font-semibold text-ink">
                runner_completed
              </code>
            </dt>
            <dd className="mt-2 text-xs leading-5 text-muted">
              exit_code、stdout_bytes、stderr_bytes、output_cap_exceeded、
              scrubbed_env_keys。
            </dd>
          </div>
          <div className="rounded-md border border-line bg-white p-3">
            <dt>
              <code className="font-mono text-xs font-semibold text-ink">
                runner_blocked
              </code>
            </dt>
            <dd className="mt-2 text-xs leading-5 text-muted">
              deny_category と reason_code のみ。status が blocked になる場合は
              runtime_blocked に対応します。
            </dd>
          </div>
        </dl>
      </Panel>

      <Panel
        description="ContextSnapshot reference を固定 10-column definition list として表示します。time-travel mutation なしで graph inspection を支えます。"
        title="ContextSnapshot 10 カラム"
        titleId="run-detail-context-snapshot"
      >
        <ContextSnapshotDefinitionList />
      </Panel>

      <Panel
        description="secret-bearing value を DOM に出さず、reviewer と E2E check が invariant を確認できるようにします。"
        title="raw secret 非表示 invariant"
        titleId="run-detail-secret-invariant"
      >
        <SecretBoundaryNotice title="AC-HARD-02 AgentRunEvent redaction" />
      </Panel>
    </AdminPageShell>
  );
}
