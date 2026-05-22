/**
 * SP-022 T08 batch 6: Eval Dashboard backend API client.
 *
 * Provides typed fetch wrappers for the P0 Exit Dashboard:
 * - `GET /api/v1/eval/kpi-rollup` — Quality KPIs 5 with p0_accept verdict
 * - (future) `GET /api/v1/eval/hard-gates-rollup` — Hard Gates 7 (SP-013+)
 *
 * Implementation contract:
 * - Server Component only (uses `next/headers` cookie via `fetchBackendJson`)
 * - Zod schema validation at boundary (drop invalid responses)
 * - Graceful fallback on BackendApiError (caller can render skeleton view)
 * - No raw secret / token / DSN credential in error messages
 */
import { z } from "zod";

import { BackendApiError, fetchBackendJson } from "@/lib/api/client";

// === Schema (1:1 with backend Pydantic KpiRollupResponse) ===

const KPI_ID_VALUES = [
  "AC-KPI-01",
  "AC-KPI-02",
  "AC-KPI-03",
  "AC-KPI-04",
  "AC-KPI-05",
] as const;

export const kpiEntryResponseSchema = z.object({
  kpi_id: z.enum(KPI_ID_VALUES),
  metric_key: z.string().min(1),
  metric_value: z.number().nullable(),
  threshold_met: z.boolean(),
  threshold_reason: z.string().nullable(),
});

export const corpusLoadResponseSchema = z.object({
  kpi_id: z.string().min(1),
  dataset_key: z.string().min(1),
  dataset_version: z.string().min(1),
  fixture_count: z.number().int().nonnegative(),
});

export const kpiRollupResponseSchema = z.object({
  kpi_count: z.number().int().nonnegative(),
  met_count: z.number().int().nonnegative(),
  failed_count: z.number().int().nonnegative(),
  p0_accept: z.boolean(),
  fail_tolerance: z.number().int().nonnegative(),
  entries: z.array(kpiEntryResponseSchema),
  corpus_loads: z.array(corpusLoadResponseSchema),
});

export type KpiEntryResponse = z.infer<typeof kpiEntryResponseSchema>;
export type CorpusLoadResponse = z.infer<typeof corpusLoadResponseSchema>;
export type KpiRollupResponse = z.infer<typeof kpiRollupResponseSchema>;

// === Fetch wrapper ===

/**
 * Fetch KPI rollup from backend (`GET /api/v1/eval/kpi-rollup`).
 *
 * @returns `KpiRollupResponse` parsed via Zod
 * @throws `BackendApiError` on non-2xx (caller handles fallback)
 * @throws `ZodError` if backend payload doesn't match schema (caller treats as fetch failure)
 */
export async function fetchKpiRollup(): Promise<KpiRollupResponse> {
  return fetchBackendJson("/api/v1/eval/kpi-rollup", kpiRollupResponseSchema);
}

// === Live-or-skeleton helper ===

/**
 * Live-or-skeleton wrapper: fetch live KPI rollup, fall back to skeleton
 * data when backend returns 503 (corpus load fail) or 501 (endpoint skeleton).
 *
 * SP-022 T08 batch 6: dashboard wires this to display live data when backend
 * is available, otherwise shows the static skeleton from Sprint 12 batch 9.
 *
 * @param skeletonFallback - static data shown when backend unavailable
 * @returns `{ source: "live" | "skeleton_fallback", data: KpiRollupResponse, fallbackReason?: string }`
 */
export type KpiRollupSource = "live" | "skeleton_fallback";

export type KpiRollupResult = {
  readonly source: KpiRollupSource;
  readonly data: KpiRollupResponse;
  readonly fallbackReason?: string;
};

export async function fetchKpiRollupOrFallback(
  skeletonFallback: KpiRollupResponse,
): Promise<KpiRollupResult> {
  try {
    const live = await fetchKpiRollup();
    return { source: "live", data: live };
  } catch (err) {
    let reason: string;
    if (err instanceof BackendApiError) {
      // Sanitize: only embed status code, not full message (may include URL/DSN)
      reason = `backend returned status=${err.status}`;
    } else if (err instanceof z.ZodError) {
      reason = "backend response schema mismatch";
    } else {
      // Don't leak raw exception text (may include DSN/credentials)
      reason = "backend fetch failed";
    }
    return {
      source: "skeleton_fallback",
      data: skeletonFallback,
      fallbackReason: reason,
    };
  }
}
