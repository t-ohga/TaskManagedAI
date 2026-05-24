import Link from "next/link";

import { BackendApiError } from "@/lib/api/client";
import {
  getAgentRun,
  listAgentRuns,
  type AgentRunDetail,
  type AgentRunEvent,
  type AgentRunListItem
} from "@/lib/api/agent-runs";
import {
  getRoleVisual,
  listRoleVisuals,
  ROLE_GROUP_LABELS,
  type RoleVisual
} from "@/lib/domain/role-icon";

export const dynamic = "force-dynamic";

const BOARD_RUN_LIMIT = 80;
const DETAIL_FETCH_LIMIT = 8;
const INTER_AGENT_EVENT_TYPES = new Set([
  "inter_agent_message_sent_ref",
  "inter_agent_message_consumed_ref"
]);
const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "provider_refused",
  "provider_incomplete",
  "validation_failed",
  "repair_exhausted"
]);
const SENSITIVE_PAYLOAD_KEY_PATTERN =
  /(body|content|credential|password|prompt|raw|secret|text|token)/iu;

type BoardState =
  | {
      kind: "ok";
      runs: AgentRunListItem[];
      total: number;
      details: AgentRunDetail[];
      detailFailures: number;
      interAgentEvents: InterAgentTimelineEvent[];
    }
  | { kind: "error"; message: string };

type RoleSummary = {
  visual: RoleVisual;
  total: number;
  active: number;
  blocked: number;
  completed: number;
  latestRun: AgentRunListItem | null;
};

type InterAgentTimelineEvent = {
  id: string;
  runId: string;
  eventType: string;
  seqNo: number;
  payloadKeys: string[];
  hiddenPayloadKeyCount: number;
  redactionStatus: string;
  createdAt: string;
};

async function readBoard(): Promise<BoardState> {
  try {
    const response = await listAgentRuns({ limit: BOARD_RUN_LIMIT, offset: 0 });
    const detailResults = await Promise.allSettled(
      response.items.slice(0, DETAIL_FETCH_LIMIT).map((run) => getAgentRun(run.id))
    );
    const details = detailResults
      .filter((result): result is PromiseFulfilledResult<AgentRunDetail> => {
        return result.status === "fulfilled";
      })
      .map((result) => result.value);

    return {
      kind: "ok",
      runs: response.items,
      total: response.total,
      details,
      detailFailures: detailResults.length - details.length,
      interAgentEvents: readInterAgentEvents(details)
    };
  } catch (error: unknown) {
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `バックエンドが ${error.status} を返しました: ${error.message}`
      };
    }
    const message =
      error instanceof Error ? error.message : "AI 組織ボードの取得に失敗しました。";
    return { kind: "error", message };
  }
}

export default async function AiSocietyBoardPage() {
  const state = await readBoard();

  return (
    <section aria-label="AI 組織ボード" className="grid gap-5">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理 / Orchestrator</p>
        <h1 className="text-3xl font-semibold tracking-normal">AI 組織ボード</h1>
        <p className="max-w-3xl text-sm text-muted">
          既存 AgentRun API だけを使い、role_id、status、event_type を read-only で表示します。
        </p>
      </header>

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">AI 組織ボードを表示できません</h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : (
        <BoardContents state={state} />
      )}
    </section>
  );
}

function BoardContents({ state }: { state: Extract<BoardState, { kind: "ok" }> }) {
  const roleSummaries = summarizeRoles(state.runs);
  const activeCount = state.runs.filter((run) => isActiveRun(run)).length;
  const blockedCount = state.runs.filter((run) => run.status === "blocked").length;
  const populatedRoles = roleSummaries.filter((summary) => summary.total > 0).length;
  const unknownRoleRuns = state.runs.filter((run) => !getRoleVisual(run.role_id).standard);

  return (
    <>
      <dl aria-label="AI 組織ボード集計" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="active_runs" value={String(activeCount)} />
        <MetricCard label="blocked_runs" value={String(blockedCount)} />
        <MetricCard label="roles_with_runs" value={`${populatedRoles}/10`} />
        <MetricCard label="inter_agent_refs" value={String(state.interAgentEvents.length)} />
      </dl>

      {state.detailFailures > 0 ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">一部 timeline を取得できません</h2>
          <p className="mt-1 text-sm text-muted">
            最新 {DETAIL_FETCH_LIMIT} 件の detail fetch のうち {state.detailFailures} 件が失敗しました。
            role 集計は list API の値だけで表示しています。
          </p>
        </article>
      ) : null}

      <section aria-labelledby="role-board-heading" className="grid gap-3">
        <div>
          <h2 id="role-board-heading" className="text-xl font-semibold">
            role catalog
          </h2>
          <p className="mt-1 text-sm text-muted">
            10 standard roles を固定順で表示し、raw role_id を併記します。
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {roleSummaries.map((summary) => (
            <RoleCard key={summary.visual.rawId} summary={summary} />
          ))}
        </div>
      </section>

      {unknownRoleRuns.length > 0 ? (
        <section aria-labelledby="unknown-role-heading" className="grid gap-3">
          <div>
            <h2 id="unknown-role-heading" className="text-xl font-semibold">
              unknown role_id
            </h2>
            <p className="mt-1 text-sm text-muted">
              standard role catalog 外の値も raw id を隠さず表示します。
            </p>
          </div>
          <div className="overflow-x-auto rounded-lg border border-line bg-panel shadow-sm">
            <table className="min-w-full divide-y divide-line text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Run ID</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">role_id</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">role_scope</th>
                  <th scope="col" className="px-4 py-3 text-left font-medium">status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {unknownRoleRuns.map((run) => (
                  <tr key={run.id} className="align-top hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <RunLink runId={run.id} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {run.role_id ?? "unassigned"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-muted">
                      {run.role_scope ?? "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{run.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <InterAgentTimeline events={state.interAgentEvents} />
    </>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panel p-4 shadow-sm">
      <dt className="font-mono text-xs text-muted">{label}</dt>
      <dd className="mt-2 text-2xl font-semibold tracking-normal">{value}</dd>
    </div>
  );
}

function RoleCard({ summary }: { summary: RoleSummary }) {
  const { visual } = summary;
  return (
    <article
      aria-label={`${visual.label} ${visual.rawId}`}
      className="grid min-h-56 gap-4 rounded-md border border-line bg-panel p-4 shadow-sm"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="grid size-10 shrink-0 place-items-center rounded-md border border-line bg-slate-50 text-xl"
        >
          {visual.icon}
        </span>
        <div className="min-w-0">
          <h3 className="text-base font-semibold">{visual.label}</h3>
          <p className="break-all font-mono text-xs text-muted">{visual.rawId}</p>
        </div>
      </div>

      <p className="text-sm text-muted">{visual.description}</p>

      <dl className="grid grid-cols-4 gap-2 text-sm">
        <CompactMetric label="total" value={summary.total} />
        <CompactMetric label="active" value={summary.active} />
        <CompactMetric label="blocked" value={summary.blocked} />
        <CompactMetric label="done" value={summary.completed} />
      </dl>

      <div className="border-t border-line pt-3 text-xs">
        <p className="font-mono text-muted">
          group: {ROLE_GROUP_LABELS[visual.group]} ({visual.group})
        </p>
        {summary.latestRun ? (
          <div className="mt-2 grid gap-1">
            <p className="break-all">
              latest: <RunLink runId={summary.latestRun.id} />
            </p>
            <p className="break-all font-mono text-muted">
              status:{summary.latestRun.status} scope:{summary.latestRun.role_scope ?? "—"}
            </p>
          </div>
        ) : (
          <p className="mt-2 text-muted">latest: —</p>
        )}
      </div>
    </article>
  );
}

function CompactMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-line px-2 py-2">
      <dt className="font-mono text-[11px] text-muted">{label}</dt>
      <dd className="mt-1 font-semibold">{value}</dd>
    </div>
  );
}

function InterAgentTimeline({ events }: { events: InterAgentTimelineEvent[] }) {
  return (
    <section aria-labelledby="inter-agent-heading" className="grid gap-3">
      <div>
        <h2 id="inter-agent-heading" className="text-xl font-semibold">
          inter-agent ref timeline
        </h2>
        <p className="mt-1 text-sm text-muted">
          message body は表示せず、event_type と参照用 payload key だけを表示します。
        </p>
      </div>
      {events.length === 0 ? (
        <article className="rounded-md border border-line bg-panel p-4 text-sm text-muted">
          最新 {DETAIL_FETCH_LIMIT} 件の AgentRun detail に inter-agent ref event はありません。
        </article>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-panel shadow-sm">
          <table
            aria-label="inter-agent event_type、payload_keys、run_id"
            className="min-w-full divide-y divide-line text-sm"
          >
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 text-left font-medium">seq_no</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">event_type</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">Run ID</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">payload_keys</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">redaction</th>
                <th scope="col" className="px-4 py-3 text-left font-medium">created_at</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {events.map((event) => (
                <tr key={event.id} className="align-top hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs">{event.seqNo}</td>
                  <td className="px-4 py-3 font-mono text-xs">{event.eventType}</td>
                  <td className="px-4 py-3">
                    <RunLink runId={event.runId} />
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {event.payloadKeys.length > 0 ? event.payloadKeys.join(", ") : "—"}
                    {event.hiddenPayloadKeyCount > 0 ? (
                      <span className="ml-2 font-mono text-attention">
                        hidden_non_ref_keys:{event.hiddenPayloadKeyCount}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {event.redactionStatus}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                    {formatDate(event.createdAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RunLink({ runId }: { runId: string }) {
  return (
    <Link
      className="break-all font-mono text-xs font-semibold text-accent hover:underline"
      href={`/runs/${runId}`}
    >
      {runId}
    </Link>
  );
}

function summarizeRoles(runs: AgentRunListItem[]): RoleSummary[] {
  return listRoleVisuals().map((visual) => {
    const roleRuns = runs.filter((run) => run.role_id === visual.rawId);
    return {
      visual,
      total: roleRuns.length,
      active: roleRuns.filter((run) => isActiveRun(run)).length,
      blocked: roleRuns.filter((run) => run.status === "blocked").length,
      completed: roleRuns.filter((run) => run.status === "completed").length,
      latestRun: roleRuns[0] ?? null
    };
  });
}

function isActiveRun(run: AgentRunListItem): boolean {
  return !TERMINAL_STATUSES.has(run.status);
}

function readInterAgentEvents(details: AgentRunDetail[]): InterAgentTimelineEvent[] {
  return details
    .flatMap((detail) => {
      return detail.events
        .filter((event) => INTER_AGENT_EVENT_TYPES.has(event.event_type))
        .map((event) => toTimelineEvent(detail.id, event));
    })
    .sort((left, right) => {
      return Date.parse(right.createdAt) - Date.parse(left.createdAt) || right.seqNo - left.seqNo;
    });
}

function toTimelineEvent(runId: string, event: AgentRunEvent): InterAgentTimelineEvent {
  const payloadKeys = filterReferencePayloadKeys(event.payload_keys);
  return {
    id: event.id,
    runId,
    eventType: event.event_type,
    seqNo: event.seq_no,
    payloadKeys,
    hiddenPayloadKeyCount: event.payload_keys.length - payloadKeys.length,
    redactionStatus: event.payload_redaction_status,
    createdAt: event.created_at
  };
}

function filterReferencePayloadKeys(keys: string[]): string[] {
  return keys.filter((key) => {
    if (SENSITIVE_PAYLOAD_KEY_PATTERN.test(key)) {
      return false;
    }
    return (
      key === "seq_no" ||
      key === "payload_hash" ||
      key === "payload_keys" ||
      key.endsWith("_id") ||
      key.endsWith("_ids") ||
      key.endsWith("_ref") ||
      key.endsWith("_refs") ||
      key.endsWith("_hash") ||
      key.endsWith("_seq")
    );
  });
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return iso;
  }
}
