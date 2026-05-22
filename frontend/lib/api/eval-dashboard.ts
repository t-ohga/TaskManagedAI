/**
 * SP-022 T08 batch 6: Eval Dashboard backend API client.
 *
 * Provides typed fetch wrappers for the P0 Exit Dashboard:
 * - `GET /api/v1/eval/kpi-rollup` — Quality KPIs 5 with p0_accept verdict
 * - (future) `GET /api/v1/eval/hard-gates-rollup` — Hard Gates 7 (SP-013+)
 *
 * Implementation contract:
 * - Server Component only (uses `next/headers` cookie via `fetchBackendJson`)
 * - Zod schema validation at boundary (exact 5-KPI cardinality + ID coverage)
 * - Outage-only fallback (BackendApiError 5xx + ZodError); auth/config errors rethrow
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

// Codex PR #91 R1 F-002 fix (P2) + R2 F-002 fix (P2): backend は 5 KPI 固定。
// R2 fix で kpi_count を literal(5) で enforce (kpi_count=N が entries.length=5 と
// 一貫しない invariant violation を fail-closed)。
export const kpiRollupResponseSchema = z
  .object({
    kpi_count: z.literal(5),  // Codex PR #91 R2 F-002 fix (P2): backend KpiRollupSummary contract で常に 5
    met_count: z.number().int().nonnegative(),
    failed_count: z.number().int().nonnegative(),
    p0_accept: z.boolean(),
    fail_tolerance: z.number().int().nonnegative(),
    entries: z.array(kpiEntryResponseSchema).length(5),
    corpus_loads: z.array(corpusLoadResponseSchema),
  })
  .superRefine((data, ctx) => {
    // entries 5 件の kpi_id が AC-KPI-01〜05 を coverage (unique + complete)
    const ids = new Set(data.entries.map((e) => e.kpi_id));
    if (ids.size !== 5 || !KPI_ID_VALUES.every((id) => ids.has(id))) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `entries must contain exactly one of each KPI ID (AC-KPI-01〜05); got ${[
          ...ids,
        ]
          .sort()
          .join(",")}`,
      });
    }
    // sum invariant: met_count + failed_count == kpi_count (backend KpiRollupSummary contract)
    if (data.met_count + data.failed_count !== data.kpi_count) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `met_count + failed_count must equal kpi_count; got ${data.met_count}+${data.failed_count}!==${data.kpi_count}`,
      });
    }
    // Codex PR #91 R2 F-005 fix (P2): met_count / failed_count が entries[].threshold_met
    // と一貫しているか cross-check (data tampering / aggregation bug 検出)。
    const actualMet = data.entries.filter((e) => e.threshold_met).length;
    const actualFailed = data.entries.length - actualMet;
    if (data.met_count !== actualMet || data.failed_count !== actualFailed) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `met_count/failed_count must match entries threshold_met counts; declared=${data.met_count}/${data.failed_count}, actual=${actualMet}/${actualFailed}`,
      });
    }
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
 * **only on backend outage** (5xx / Zod schema mismatch).
 *
 * Codex PR #91 R1 F-001 + F-004 fix (P1/P2):
 * - 4xx (auth/permission/validation) → **rethrow** (operator が access failure を認識)
 * - 5xx (outage / endpoint skeleton 501 / corpus load fail 503) → skeleton fallback
 * - ZodError (schema mismatch) → skeleton fallback (sanitized reason)
 * - Other Error (config / runtime / env misconfig 等) → **rethrow** (env misconfig を hidden しない)
 *
 * @param skeletonFallback - static data shown when backend unavailable (outage only)
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
    // Codex PR #91 R1 F-001 fix (P1): outage-only fallback。4xx (auth/permission/
    // 400 validation) は operator が access failure を認識する必要があるため rethrow。
    if (err instanceof BackendApiError) {
      if (err.status >= 500 || err.status === 501) {
        return {
          source: "skeleton_fallback",
          data: skeletonFallback,
          fallbackReason: `backend returned status=${err.status}`,
        };
      }
      // 4xx → rethrow (auth/permission failure を hidden しない)
      throw err;
    }
    // Zod schema mismatch → fallback (backend が schema 違反 response、outage 扱い)
    if (err instanceof z.ZodError) {
      return {
        source: "skeleton_fallback",
        data: skeletonFallback,
        fallbackReason: "backend response schema mismatch",
      };
    }
    // Codex PR #91 R2 F-004 fix (P2): malformed JSON (SyntaxError) も outage 扱い
    // (backend が non-JSON response を返す = outage / proxy 障害)。
    if (err instanceof SyntaxError) {
      return {
        source: "skeleton_fallback",
        data: skeletonFallback,
        fallbackReason: "backend returned malformed JSON",
      };
    }
    // Codex PR #91 R2 F-001 fix (P1): network-level failure (DNS timeout /
    // ECONN refused / fetch failed) も outage。Node 18+ undici は `TypeError:
    // fetch failed` を投げ、原因は err.cause に格納される (ENOTFOUND /
    // ECONNREFUSED / ETIMEDOUT 等)。env misconfig (INTERNAL_API_URL undefined)
    // と区別するため、TypeError + cause 経路のみ fallback、他は rethrow。
    if (err instanceof TypeError && "cause" in err) {
      return {
        source: "skeleton_fallback",
        data: skeletonFallback,
        fallbackReason: "backend network unreachable",
      };
    }
    // Codex PR #91 R1 F-004 fix (P2): config / runtime / env misconfig (missing
    // INTERNAL_API_URL 等) は env error を hidden しないため rethrow。
    // raw exception text (DSN / credentials) を message に embed しない invariant は
    // fetchBackendJson 層で担保 (caller には rethrow される Error object のみ)。
    throw err;
  }
}
