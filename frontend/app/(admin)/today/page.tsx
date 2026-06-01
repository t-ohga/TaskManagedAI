import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  listAgentRuns,
  type AgentRunListItem,
} from "@/lib/api/agent-runs";
import {
  listApprovals,
  type ApprovalListItem,
} from "@/lib/api/approvals";
import { BackendApiError } from "@/lib/api/client";
import {
  fetchKpiRollupOrFallback,
  type KpiRollupResponse,
  type KpiRollupResult,
} from "@/lib/api/eval-dashboard";
import { getCurrentProject, type CurrentProject } from "@/lib/api/session";
import { listTickets, type TicketRead } from "@/lib/api/tickets";
import {
  formatApprovalActionClass,
  formatRiskLevel,
} from "@/lib/i18n/approval-labels";
import {
  formatTicketPriority,
  formatTicketStatus,
} from "@/lib/i18n/ticket-labels";

export const dynamic = "force-dynamic";

const TICKET_LIMIT = 120;
const RUN_LIMIT = 80;
const ACTIVE_TICKET_STATUSES = new Set(["open", "in_progress", "blocked", "review"]);
const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "provider_refused",
  "provider_incomplete",
  "validation_failed",
  "repair_exhausted",
]);
const PRIORITY_RANK = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
} as const;

const KPI_FALLBACK: KpiRollupResponse = {
  kpi_count: 5,
  met_count: 0,
  failed_count: 5,
  p0_accept: false,
  fail_tolerance: 1,
  entries: [
    {
      kpi_id: "AC-KPI-01",
      metric_key: "acceptance_pass_rate",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "today_control_plane_fallback",
    },
    {
      kpi_id: "AC-KPI-02",
      metric_key: "time_to_merge",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "today_control_plane_fallback",
    },
    {
      kpi_id: "AC-KPI-03",
      metric_key: "approval_wait_ms",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "today_control_plane_fallback",
    },
    {
      kpi_id: "AC-KPI-04",
      metric_key: "citation_coverage",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "today_control_plane_fallback",
    },
    {
      kpi_id: "AC-KPI-05",
      metric_key: "cost_per_completed_task",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "today_control_plane_fallback",
    },
  ],
  corpus_loads: [],
};

type SourceState<T> =
  | { kind: "ok"; data: T }
  | { kind: "error"; message: string };

type TicketSource = {
  project: CurrentProject;
  tickets: TicketRead[];
  total: number;
};

type RunsSource = {
  runs: AgentRunListItem[];
  total: number;
};

type TodayState = {
  tickets: SourceState<TicketSource>;
  runs: SourceState<RunsSource>;
  approvals: SourceState<ApprovalListItem[]>;
  kpi: SourceState<KpiRollupResult>;
};

async function readTodayState(): Promise<TodayState> {
  const [tickets, runs, approvals, kpi] = await Promise.all([
    readTicketSource(),
    readRunsSource(),
    readApprovalSource(),
    readKpiSource(),
  ]);
  return { tickets, runs, approvals, kpi };
}

async function readTicketSource(): Promise<SourceState<TicketSource>> {
  try {
    const project = await getCurrentProject();
    const response = await listTickets(project.project_id, {
      limit: TICKET_LIMIT,
      offset: 0,
    });
    return {
      kind: "ok",
      data: {
        project,
        tickets: response.items,
        total: response.total,
      },
    };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error, "チケットを取得できません") };
  }
}

async function readRunsSource(): Promise<SourceState<RunsSource>> {
  try {
    const response = await listAgentRuns({ limit: RUN_LIMIT, offset: 0 });
    return {
      kind: "ok",
      data: {
        runs: response.items,
        total: response.total,
      },
    };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error, "AI 実行を取得できません") };
  }
}

async function readApprovalSource(): Promise<SourceState<ApprovalListItem[]>> {
  try {
    return { kind: "ok", data: await listApprovals({ status: "pending" }) };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error, "承認待ちを取得できません") };
  }
}

async function readKpiSource(): Promise<SourceState<KpiRollupResult>> {
  try {
    return { kind: "ok", data: await fetchKpiRollupOrFallback(KPI_FALLBACK) };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error, "KPI を取得できません") };
  }
}

export default async function TodayPage() {
  const state = await readTodayState();
  const workTickets = state.tickets.kind === "ok"
    ? sortTickets(state.tickets.data.tickets.filter(isWorkTicket))
    : [];
  const inboxTickets = state.tickets.kind === "ok"
    ? sortTickets(state.tickets.data.tickets.filter(isInboxTicket))
    : [];
  const activeRuns = state.runs.kind === "ok"
    ? state.runs.data.runs.filter(isInProgressRun).slice(0, 8)
    : [];
  const queuedRuns = state.runs.kind === "ok"
    ? state.runs.data.runs.filter((run) => run.status === "queued").slice(0, 8)
    : [];
  const pendingApprovals = state.approvals.kind === "ok" ? state.approvals.data : [];
  const errors = collectErrors(state);

  return (
    <section aria-label="Today control plane" className="grid gap-5">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理 / P0.1</p>
        <h1 className="text-3xl font-semibold tracking-normal">Today / Inbox</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          今日の確認対象と未割当の入口を分けて表示します。
        </p>
      </header>

      <KpiStrip
        activeRuns={activeRuns.length}
        kpi={state.kpi}
        pendingApprovals={pendingApprovals.length}
        workTickets={workTickets.length}
      />

      {errors.length > 0 ? (
        <section
          aria-label="Today data source status"
          role="status"
          className="rounded-md border border-attention bg-amber-50 p-4"
        >
          <h2 className="text-base font-semibold text-attention">
            一部データを表示できません
          </h2>
          <ul className="mt-2 grid gap-1 text-sm text-muted-foreground">
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Lane
          title="今日の概要"
          subtitle={todaySubtitle(state.tickets)}
          count={workTickets.length + activeRuns.length + pendingApprovals.length}
        >
          <LaneGroup title="未完了チケット" emptyLabel="進行中のチケットはありません。">
            {workTickets.slice(0, 8).map((ticket) => (
              <TicketRow key={ticket.id} ticket={ticket} />
            ))}
          </LaneGroup>
          <LaneGroup title="実行中 AI" emptyLabel="進行中の AI 実行はありません。">
            {activeRuns.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </LaneGroup>
          <LaneGroup title="承認待ち" emptyLabel="承認待ちはありません。">
            {pendingApprovals.slice(0, 8).map((approval) => (
              <ApprovalRow key={approval.id} approval={approval} />
            ))}
          </LaneGroup>
        </Lane>

        <Lane
          title="受信箱"
          subtitle="未割当チケットと queued run"
          count={inboxTickets.length + queuedRuns.length}
        >
          <LaneGroup title="未割当チケット" emptyLabel="未割当チケットはありません。">
            {inboxTickets.slice(0, 10).map((ticket) => (
              <TicketRow key={ticket.id} ticket={ticket} />
            ))}
          </LaneGroup>
          <LaneGroup title="待機中 AI 実行" emptyLabel="queued の AI 実行はありません。">
            {queuedRuns.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </LaneGroup>
        </Lane>
      </div>
    </section>
  );
}

function KpiStrip({
  activeRuns,
  kpi,
  pendingApprovals,
  workTickets,
}: {
  activeRuns: number;
  kpi: SourceState<KpiRollupResult>;
  pendingApprovals: number;
  workTickets: number;
}) {
  const kpiValue = kpi.kind === "ok"
    ? `${kpi.data.data.met_count}/${kpi.data.data.kpi_count}`
    : "—";
  const kpiSource = kpi.kind === "ok" ? kpi.data.source : "unavailable";

  return (
    <dl aria-label="Today KPI strip" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard label="未完了チケット" value={String(workTickets)} detail="アクティブなチケット" />
      <MetricCard label="承認待ち" value={String(pendingApprovals)} detail="承認待ちキュー" />
      <MetricCard label="実行中AI" value={String(activeRuns)} detail="実行中のAI" />
      <MetricCard label="KPI達成" value={kpiValue} detail={kpiSource} />
    </dl>
  );
}

function MetricCard({
  detail,
  label,
  value,
}: {
  detail: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-line bg-panel p-4 shadow-sm">
      <dt className="font-mono text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-2 text-2xl font-semibold tracking-normal">{value}</dd>
      <dd className="mt-1 text-xs text-muted-foreground">{detail}</dd>
    </div>
  );
}

function Lane({
  children,
  count,
  subtitle,
  title,
}: {
  children: ReactNode;
  count: number;
  subtitle: string;
  title: string;
}) {
  return (
    <section
      aria-label={`${title} lane`}
      className="grid content-start gap-4 rounded-md border border-line bg-panel p-4 shadow-sm"
    >
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-normal">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <span className="rounded-md bg-panel-muted px-2 py-1 font-mono text-xs font-semibold text-muted-foreground">
          {count}
        </span>
      </header>
      <div className="grid gap-5">{children}</div>
    </section>
  );
}

function LaneGroup({
  children,
  emptyLabel,
  title,
}: {
  children: ReactNode;
  emptyLabel: string;
  title: string;
}) {
  const hasItems = Array.isArray(children) ? children.length > 0 : Boolean(children);

  return (
    <section className="grid gap-2" aria-label={title}>
      <h3 className="text-sm font-semibold text-muted-foreground">{title}</h3>
      {hasItems ? (
        <ul className="divide-y divide-line rounded-md border border-line">{children}</ul>
      ) : (
        <p className="rounded-md border border-line px-3 py-3 text-sm text-muted-foreground">{emptyLabel}</p>
      )}
    </section>
  );
}

function TicketRow({ ticket }: { ticket: TicketRead }) {
  return (
    <li className="grid gap-2 px-3 py-3 hover:bg-panel-muted">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/tickets/${ticket.id}` as Route}
          className="min-w-0 break-words text-sm font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          {ticket.title}
        </Link>
        <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${priorityClass(ticket.priority)}`}>
          {formatTicketPriority(ticket.priority)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="font-mono">{ticket.slug}</span>
        <span>{formatTicketStatus(ticket.status)}</span>
        <span>担当:{ticket.assignee_actor_id ?? "未割当"}</span>
        <span>更新:{formatDate(ticket.updated_at)}</span>
      </div>
    </li>
  );
}

function RunRow({ run }: { run: AgentRunListItem }) {
  return (
    <li className="grid gap-2 px-3 py-3 hover:bg-panel-muted">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/runs/${run.id}` as Route}
          className="break-all font-mono text-xs font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          {run.id}
        </Link>
        <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${runStatusClass(run.status)}`}>
          {run.status.replaceAll("_", " ")}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>役割: {run.role_id ?? "未割当"}</span>
        <span>進捗 #{run.progress_seq}</span>
        <span>最終更新: {run.last_progress_at ? formatDate(run.last_progress_at) : "—"}</span>
        {run.blocked_reason ? <span>ブロック: {run.blocked_reason}</span> : null}
      </div>
    </li>
  );
}

function ApprovalRow({ approval }: { approval: ApprovalListItem }) {
  return (
    <li className="grid gap-2 px-3 py-3 hover:bg-panel-muted">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/approvals/${approval.id}`}
          className="break-all text-sm font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        >
          {formatApprovalActionClass(approval.action_class)}
        </Link>
        <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${riskClass(approval.risk_level)}`}>
          {formatRiskLevel(approval.risk_level)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="break-all">対象: {approval.resource_ref}</span>
        <span>要求日時: {formatDate(approval.requested_at)}</span>
      </div>
    </li>
  );
}

function collectErrors(state: TodayState): string[] {
  const errors: string[] = [];
  if (state.tickets.kind === "error") errors.push(`tickets: ${state.tickets.message}`);
  if (state.runs.kind === "error") errors.push(`runs: ${state.runs.message}`);
  if (state.approvals.kind === "error") errors.push(`approvals: ${state.approvals.message}`);
  if (state.kpi.kind === "error") errors.push(`kpi: ${state.kpi.message}`);
  return errors;
}

function todaySubtitle(tickets: SourceState<TicketSource>): string {
  if (tickets.kind === "ok") {
    return `${tickets.data.project.name} / ${tickets.data.total} チケット`;
  }
  return "チケットデータを取得できません";
}

function isWorkTicket(ticket: TicketRead): boolean {
  return ACTIVE_TICKET_STATUSES.has(ticket.status);
}

function isInboxTicket(ticket: TicketRead): boolean {
  return isWorkTicket(ticket) && ticket.assignee_actor_id === null;
}

function isActiveRun(run: AgentRunListItem): boolean {
  return !TERMINAL_RUN_STATUSES.has(run.status);
}

function isInProgressRun(run: AgentRunListItem): boolean {
  return isActiveRun(run) && run.status !== "queued";
}

function sortTickets(tickets: TicketRead[]): TicketRead[] {
  return [...tickets].sort((left, right) => {
    const leftPriority = left.priority ? PRIORITY_RANK[left.priority] : 4;
    const rightPriority = right.priority ? PRIORITY_RANK[right.priority] : 4;
    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }
    return right.updated_at.localeCompare(left.updated_at);
  });
}

function formatReadError(error: unknown, fallback: string): string {
  if (error instanceof BackendApiError) {
    return `backend status=${error.status}`;
  }
  if (error instanceof Error && error.message.includes("INTERNAL_API_URL")) {
    return "frontend backend URL is not configured";
  }
  return fallback;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return iso;
  }
}

function priorityClass(priority: TicketRead["priority"]): string {
  switch (priority) {
    case "critical":
      return "bg-rose-100 text-rose-800";
    case "high":
      return "bg-orange-100 text-orange-800";
    case "medium":
      return "bg-yellow-100 text-yellow-800";
    case "low":
      return "bg-emerald-100 text-emerald-800";
    default:
      return "bg-slate-100 text-slate-800";
  }
}

function riskClass(risk: ApprovalListItem["risk_level"]): string {
  switch (risk) {
    case "critical":
      return "bg-rose-100 text-rose-800";
    case "high":
      return "bg-orange-100 text-orange-800";
    case "medium":
      return "bg-yellow-100 text-yellow-800";
    case "low":
      return "bg-emerald-100 text-emerald-800";
    default:
      return "bg-slate-100 text-slate-800";
  }
}

function runStatusClass(status: AgentRunListItem["status"]): string {
  switch (status) {
    case "blocked":
    case "failed":
    case "provider_refused":
    case "repair_exhausted":
      return "bg-rose-100 text-rose-800";
    case "waiting_approval":
    case "provider_incomplete":
      return "bg-amber-100 text-attention";
    case "completed":
      return "bg-emerald-100 text-emerald-800";
    case "running":
    case "gathering_context":
      return "bg-teal-50 text-accent";
    default:
      return "bg-slate-100 text-slate-800";
  }
}
