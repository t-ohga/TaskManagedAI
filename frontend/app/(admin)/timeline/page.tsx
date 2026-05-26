import Link from "next/link";
import type { Route } from "next";

import {
  getAgentRun,
  listAgentRuns,
  type AgentRunDetail,
  type AgentRunEvent,
} from "@/lib/api/agent-runs";
import {
  listApprovals,
  type ApprovalListItem,
} from "@/lib/api/approvals";
import { listAuditEvents, type AuditEvent } from "@/lib/api/audit";
import { BackendApiError } from "@/lib/api/client";
import {
  fetchKpiRollupOrFallback,
  type KpiRollupResponse,
  type KpiRollupResult,
} from "@/lib/api/eval-dashboard";
import { formatApprovalActionClass, formatRiskLevel } from "@/lib/i18n/approval-labels";

export const dynamic = "force-dynamic";

const RUN_LIMIT = 12;
const RUN_DETAIL_LIMIT = 6;
const AUDIT_LIMIT = 40;
const TIMELINE_LIMIT = 36;
const SENSITIVE_KEY_PATTERN =
  /(body|content|credential|password|prompt|raw|secret|text|token|value)/iu;

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
      threshold_reason: "timeline_fallback",
    },
    {
      kpi_id: "AC-KPI-02",
      metric_key: "time_to_merge",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "timeline_fallback",
    },
    {
      kpi_id: "AC-KPI-03",
      metric_key: "approval_wait_ms",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "timeline_fallback",
    },
    {
      kpi_id: "AC-KPI-04",
      metric_key: "citation_coverage",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "timeline_fallback",
    },
    {
      kpi_id: "AC-KPI-05",
      metric_key: "cost_per_completed_task",
      metric_value: null,
      threshold_met: false,
      threshold_reason: "timeline_fallback",
    },
  ],
  corpus_loads: [],
};

type SourceState<T> =
  | { kind: "ok"; data: T }
  | { kind: "error"; message: string };

type AgentSource = {
  runsTotal: number;
  details: AgentRunDetail[];
  detailFailures: number;
};

type TimelineState = {
  agents: SourceState<AgentSource>;
  audit: SourceState<{ events: AuditEvent[]; total: number }>;
  approvals: SourceState<ApprovalListItem[]>;
  kpi: SourceState<KpiRollupResult>;
};

type TimelineRow = {
  id: string;
  source: "agent" | "audit" | "approval";
  title: string;
  subtitle: string;
  occurredAt: string;
  href: string | null;
  safeKeys: string[];
  hiddenKeyCount: number;
  redactionStatus: string | null;
  tone: "default" | "attention" | "danger" | "success";
};

async function readTimelineState(): Promise<TimelineState> {
  const [agents, audit, approvals, kpi] = await Promise.all([
    readAgentSource(),
    readAuditSource(),
    readApprovalSource(),
    readKpiSource(),
  ]);
  return { agents, audit, approvals, kpi };
}

async function readAgentSource(): Promise<SourceState<AgentSource>> {
  try {
    const response = await listAgentRuns({ limit: RUN_LIMIT, offset: 0 });
    const detailResults = await Promise.allSettled(
      response.items.slice(0, RUN_DETAIL_LIMIT).map((run) => getAgentRun(run.id))
    );
    const details = detailResults
      .filter((result): result is PromiseFulfilledResult<AgentRunDetail> => {
        return result.status === "fulfilled";
      })
      .map((result) => result.value);

    return {
      kind: "ok",
      data: {
        runsTotal: response.total,
        details,
        detailFailures: detailResults.length - details.length,
      },
    };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error, "AI 実行イベントを取得できません") };
  }
}

async function readAuditSource(): Promise<SourceState<{ events: AuditEvent[]; total: number }>> {
  try {
    const response = await listAuditEvents({ limit: AUDIT_LIMIT, offset: 0 });
    return { kind: "ok", data: { events: response.events, total: response.total } };
  } catch (error: unknown) {
    return { kind: "error", message: formatReadError(error, "監査イベントを取得できません") };
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

export default async function TimelinePage() {
  const state = await readTimelineState();
  const rows = buildTimelineRows(state).slice(0, TIMELINE_LIMIT);
  const errors = collectErrors(state);

  return (
    <section aria-label="Execution timeline" className="grid gap-5">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理 / P0.1</p>
        <h1 className="text-3xl font-semibold tracking-normal">実行タイムライン</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          AgentRun、監査、承認待ちを時系列で確認します。
        </p>
      </header>

      <TimelineSummary state={state} rowCount={rows.length} />

      {errors.length > 0 ? (
        <section
          aria-label="Timeline data source status"
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

      {state.agents.kind === "ok" && state.agents.data.detailFailures > 0 ? (
        <section role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">
            一部 AgentRun detail を取得できません
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            最新 {RUN_DETAIL_LIMIT} 件のうち {state.agents.data.detailFailures} 件を除外しました。
          </p>
        </section>
      ) : null}

      <section aria-label="Unified event rows" className="rounded-md border border-line bg-panel shadow-sm">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-lg font-semibold">Unified events</h2>
        </div>
        {rows.length === 0 ? (
          <p className="px-4 py-5 text-sm text-muted-foreground">表示できるイベントはありません。</p>
        ) : (
          <ol className="divide-y divide-line">
            {rows.map((row) => (
              <TimelineListItem key={row.id} row={row} />
            ))}
          </ol>
        )}
      </section>
    </section>
  );
}

function TimelineSummary({ rowCount, state }: { rowCount: number; state: TimelineState }) {
  const kpiValue = state.kpi.kind === "ok"
    ? `${state.kpi.data.data.met_count}/${state.kpi.data.data.kpi_count}`
    : "—";
  const kpiSource = state.kpi.kind === "ok" ? state.kpi.data.source : "unavailable";
  const auditCount = state.audit.kind === "ok" ? String(state.audit.data.events.length) : "—";
  const agentEventCount = state.agents.kind === "ok"
    ? String(state.agents.data.details.flatMap((detail) => detail.events).length)
    : "—";
  const approvalCount = state.approvals.kind === "ok" ? String(state.approvals.data.length) : "—";

  return (
    <dl aria-label="Timeline summary" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <MetricCard label="timeline_rows" value={String(rowCount)} detail="merged view" />
      <MetricCard label="agent_events" value={agentEventCount} detail="AgentRunEvent" />
      <MetricCard label="audit_events" value={auditCount} detail="AuditEvent" />
      <MetricCard label="pending_approvals" value={approvalCount} detail="Approval" />
      <MetricCard label="p0_kpis_met" value={kpiValue} detail={kpiSource} />
    </dl>
  );
}

function MetricCard({ detail, label, value }: { detail: string; label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panel p-4 shadow-sm">
      <dt className="font-mono text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-2 text-2xl font-semibold tracking-normal">{value}</dd>
      <dd className="mt-1 text-xs text-muted-foreground">{detail}</dd>
    </div>
  );
}

function TimelineListItem({ row }: { row: TimelineRow }) {
  return (
    <li className="grid gap-3 px-4 py-4 hover:bg-panel-muted md:grid-cols-[9rem_minmax(0,1fr)]">
      <div className="grid content-start gap-2">
        <span className={`w-fit rounded-md px-2 py-1 text-xs font-semibold ${toneClass(row.tone)}`}>
          {row.source}
        </span>
        <time className="font-mono text-xs text-muted-foreground" dateTime={row.occurredAt}>
          {formatDate(row.occurredAt)}
        </time>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {row.href ? (
            <Link
              className="break-all text-sm font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              href={row.href as Route}
            >
              {row.title}
            </Link>
          ) : (
            <h3 className="break-all text-sm font-semibold">{row.title}</h3>
          )}
          {row.redactionStatus ? (
            <span className="rounded-md bg-panel-muted px-2 py-1 text-xs text-muted-foreground">
              {row.redactionStatus}
            </span>
          ) : null}
        </div>
        <p className="mt-1 break-all text-sm text-muted-foreground">{row.subtitle}</p>
        {row.safeKeys.length > 0 || row.hiddenKeyCount > 0 ? (
          <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
            keys:{row.safeKeys.length > 0 ? row.safeKeys.join(", ") : "—"}
            {row.hiddenKeyCount > 0 ? ` / hidden_keys:${row.hiddenKeyCount}` : ""}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function buildTimelineRows(state: TimelineState): TimelineRow[] {
  const rows: TimelineRow[] = [];

  if (state.agents.kind === "ok") {
    for (const detail of state.agents.data.details) {
      for (const event of detail.events) {
        rows.push(agentEventRow(detail.id, event));
      }
    }
  }

  if (state.audit.kind === "ok") {
    rows.push(...state.audit.data.events.map(auditEventRow));
  }

  if (state.approvals.kind === "ok") {
    rows.push(...state.approvals.data.map(approvalRow));
  }

  return rows.sort((left, right) => right.occurredAt.localeCompare(left.occurredAt));
}

function agentEventRow(runId: string, event: AgentRunEvent): TimelineRow {
  const keys = sanitizePayloadKeys(event.payload_keys);
  return {
    id: `agent:${event.id}`,
    source: "agent",
    title: event.event_type,
    subtitle: `run:${runId} seq:${event.seq_no} actor:${event.actor_id}`,
    occurredAt: event.created_at,
    href: `/runs/${runId}`,
    safeKeys: keys.safe,
    hiddenKeyCount: keys.hidden,
    redactionStatus: event.payload_redaction_status,
    tone: toneForEvent(event.event_type),
  };
}

function auditEventRow(event: AuditEvent): TimelineRow {
  const keys = sanitizePayloadKeys(event.payload_keys);
  return {
    id: `audit:${event.id}`,
    source: "audit",
    title: event.event_type,
    subtitle: `actor:${event.actor_id ?? "—"} reason:${event.reason_code ?? "—"}`,
    occurredAt: event.created_at,
    href: "/audit",
    safeKeys: keys.safe,
    hiddenKeyCount: keys.hidden,
    redactionStatus: event.payload_redaction_status,
    tone: toneForEvent(event.event_type),
  };
}

function approvalRow(approval: ApprovalListItem): TimelineRow {
  return {
    id: `approval:${approval.id}`,
    source: "approval",
    title: formatApprovalActionClass(approval.action_class),
    subtitle: `${formatRiskLevel(approval.risk_level)} / ${approval.resource_ref}`,
    occurredAt: approval.requested_at,
    href: `/approvals/${approval.id}`,
    safeKeys: [],
    hiddenKeyCount: 0,
    redactionStatus: null,
    tone: approval.risk_level === "critical" || approval.risk_level === "high"
      ? "attention"
      : "default",
  };
}

function sanitizePayloadKeys(keys: string[]): { safe: string[]; hidden: number } {
  const safe = keys.filter((key) => !SENSITIVE_KEY_PATTERN.test(key)).slice(0, 6);
  return { safe, hidden: keys.length - safe.length };
}

function collectErrors(state: TimelineState): string[] {
  const errors: string[] = [];
  if (state.agents.kind === "error") errors.push(`agent_events: ${state.agents.message}`);
  if (state.audit.kind === "error") errors.push(`audit_events: ${state.audit.message}`);
  if (state.approvals.kind === "error") errors.push(`approvals: ${state.approvals.message}`);
  if (state.kpi.kind === "error") errors.push(`kpi: ${state.kpi.message}`);
  return errors;
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

function toneForEvent(eventType: string): TimelineRow["tone"] {
  if (eventType.includes("failed") || eventType.includes("blocked") || eventType.includes("denied")) {
    return "danger";
  }
  if (eventType.includes("approval") || eventType.includes("budget")) {
    return "attention";
  }
  if (eventType.includes("completed") || eventType.includes("validated")) {
    return "success";
  }
  return "default";
}

function toneClass(tone: TimelineRow["tone"]): string {
  switch (tone) {
    case "danger":
      return "bg-rose-100 text-rose-800";
    case "attention":
      return "bg-amber-100 text-attention";
    case "success":
      return "bg-emerald-100 text-emerald-800";
    default:
      return "bg-slate-100 text-slate-800";
  }
}
