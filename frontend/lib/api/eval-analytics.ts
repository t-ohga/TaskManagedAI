import { fetchBackendJson } from "@/lib/api/client";
import {
  KpiTimeseriesResponseSchema,
  ProviderBreakdownResponseSchema,
  type KpiTimeseriesResponse,
  type ProviderBreakdownResponse
} from "@/lib/domain/kpi-analytics";

/**
 * ADR-00051 (SP-026): KPI analytics の server fetch。`fetchBackendJson` は cache:no-store + session-bound。
 * fail-closed loader (取得失敗と「真の 0 件」を区別する discriminated union)。
 */

type TimeseriesRange = "week" | "month" | "quarter";

export type KpiTimeseriesLoad =
  | { ok: true; data: KpiTimeseriesResponse }
  | { ok: false };

export type ProviderBreakdownLoad =
  | { ok: true; data: ProviderBreakdownResponse }
  | { ok: false };

export async function loadKpiTimeseries(options: {
  range: TimeseriesRange;
  bucket?: "day" | "week";
  projectId?: string;
}): Promise<KpiTimeseriesLoad> {
  const params = new URLSearchParams();
  params.set("range", options.range);
  params.set("bucket", options.bucket ?? "day");
  if (options.projectId) params.set("project_id", options.projectId);
  const path = `/api/v1/eval/kpi_timeseries?${params.toString()}` as `/${string}`;
  try {
    return { ok: true, data: await fetchBackendJson(path, KpiTimeseriesResponseSchema) };
  } catch {
    return { ok: false };
  }
}

export async function loadProviderBreakdown(
  range: TimeseriesRange
): Promise<ProviderBreakdownLoad> {
  const path = `/api/v1/eval/provider_breakdown?range=${range}` as `/${string}`;
  try {
    return { ok: true, data: await fetchBackendJson(path, ProviderBreakdownResponseSchema) };
  } catch {
    return { ok: false };
  }
}
