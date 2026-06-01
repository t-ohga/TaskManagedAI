import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

// ADR-00039 D-5: tenant 内 active ticket の status 別集計 (backend SQL、limit 非依存)。
const TicketStatusCountSchema = z.object({
  status: z.string(),
  count: z.number().int()
});

export const TicketSummarySchema = z.object({
  ticket_total: z.number().int(),
  status_counts: z.array(TicketStatusCountSchema)
});

export type TicketSummary = z.infer<typeof TicketSummarySchema>;

export async function fetchTicketSummary(): Promise<TicketSummary> {
  return fetchBackendJson("/api/v1/me/ticket_summary", TicketSummarySchema);
}

export type TicketDisplayCounts = {
  open: number;
  in_progress: number;
  closed: number;
  cancelled: number;
};

// 表示 bucket 折り畳み (ADR-00039 R2): 既存 dashboard と同じ集約を維持する。
// in_progress = in_progress + blocked + review、open = open (+ 未知 status fallback)。
// どの status も必ずいずれかの bucket に入り、4 bucket 合計は ticket_total と一致する
// (欠落・二重計上しない)。
export function foldTicketDisplayCounts(
  statusCounts: readonly { status: string; count: number }[]
): TicketDisplayCounts {
  const display: TicketDisplayCounts = { open: 0, in_progress: 0, closed: 0, cancelled: 0 };
  for (const { status, count } of statusCounts) {
    if (status === "in_progress" || status === "blocked" || status === "review") {
      display.in_progress += count;
    } else if (status === "closed") {
      display.closed += count;
    } else if (status === "cancelled") {
      display.cancelled += count;
    } else {
      // open + 未知 status の fallback (既存 dashboard と同挙動)。
      display.open += count;
    }
  }
  return display;
}

// ADR-00039 C-4: AgentRun role_id facet (backend SQL、active-scope + 任意 status predicate)。
const RoleFacetEntrySchema = z.object({
  role_id: z.string(),
  count: z.number().int()
});

export const RoleFacetSchema = z.object({
  roles: z.array(RoleFacetEntrySchema),
  status: z.string().nullable()
});

export type RoleFacet = z.infer<typeof RoleFacetSchema>;

export async function fetchRoleFacet(status?: string): Promise<RoleFacet> {
  const path = status
    ? (`/api/v1/agent_runs/role_facet?status=${encodeURIComponent(status)}` as `/${string}`)
    : "/api/v1/agent_runs/role_facet";
  return fetchBackendJson(path, RoleFacetSchema);
}

// ADR-00040 D-3/D-4: AgentRun アクティビティ / コスト時系列 (date_trunc bucket、sparse)。
const ActivityBucketSchema = z.object({
  bucket_start: z.string(),
  run_count: z.number().int(),
  // measured run 0 件なら null (未計測)。0 に丸めず未計測として扱う。
  cost_usd: z.number().nullable(),
  measured_run_count: z.number().int(),
  unmeasured_run_count: z.number().int()
});

const ActivityBucketGranularitySchema = z.enum(["day", "week"]);
export type ActivityBucketGranularity = z.infer<typeof ActivityBucketGranularitySchema>;

export const ActivityTimeseriesSchema = z.object({
  buckets: z.array(ActivityBucketSchema),
  bucket: ActivityBucketGranularitySchema,
  range: z.string()
});

export type ActivityTimeseries = z.infer<typeof ActivityTimeseriesSchema>;

export async function fetchActivityTimeseries(
  bucket: ActivityBucketGranularity = "day",
  range = "month"
): Promise<ActivityTimeseries> {
  const path =
    `/api/v1/agent_runs/activity_timeseries?bucket=${bucket}&range=${encodeURIComponent(range)}` as `/${string}`;
  return fetchBackendJson(path, ActivityTimeseriesSchema);
}
