/**
 * SP-022 T08 batch 6: tests for eval-dashboard API client.
 *
 * Verifies:
 * - fetchKpiRollup: parses backend KpiRollupResponse via Zod schema
 * - fetchKpiRollupOrFallback: returns live data on 2xx
 * - fetchKpiRollupOrFallback: falls back to skeleton on 5xx (sanitized reason)
 * - fetchKpiRollupOrFallback: falls back to skeleton on schema mismatch
 * - fetchKpiRollupOrFallback: error reason does NOT leak raw exception text
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchKpiRollup,
  fetchKpiRollupOrFallback,
  type KpiRollupResponse,
} from "@/lib/api/eval-dashboard";

const cookieMocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: cookieMocks.get,
  })),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  cookieMocks.get.mockReset();
});

const VALID_RESPONSE: KpiRollupResponse = {
  kpi_count: 5,
  met_count: 4,
  failed_count: 1,
  p0_accept: true,
  fail_tolerance: 1,
  entries: [
    {
      kpi_id: "AC-KPI-01",
      metric_key: "acceptance_pass_rate",
      metric_value: 0.75,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-02",
      metric_key: "time_to_merge",
      metric_value: 1.0,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-03",
      metric_key: "approval_wait_ms",
      metric_value: 7200000,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
    {
      kpi_id: "AC-KPI-04",
      metric_key: "citation_coverage",
      metric_value: 0.6,
      threshold_met: false,
      threshold_reason: "below_threshold",
    },
    {
      kpi_id: "AC-KPI-05",
      metric_key: "cost_per_completed_task",
      metric_value: 0.3,
      threshold_met: true,
      threshold_reason: "threshold_met",
    },
  ],
  corpus_loads: [],
};

const SKELETON_FALLBACK: KpiRollupResponse = {
  ...VALID_RESPONSE,
  met_count: 5,
  failed_count: 0,
};

describe("eval-dashboard API client", () => {
  it("fetchKpiRollup parses backend KpiRollupResponse via Zod", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(VALID_RESPONSE), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchKpiRollup();
    expect(result.kpi_count).toBe(5);
    expect(result.met_count).toBe(4);
    expect(result.p0_accept).toBe(true);
    expect(result.entries).toHaveLength(5);
  });

  it("fetchKpiRollupOrFallback returns live data on 2xx", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(VALID_RESPONSE), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("live");
    expect(result.data.met_count).toBe(4);
    expect(result.fallbackReason).toBeUndefined();
  });

  it("fetchKpiRollupOrFallback falls back to skeleton on 503 with sanitized reason", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: { error_code: "kpi_corpus_load_failed" } }),
        { status: 503 },
      ),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    expect(result.data.met_count).toBe(5); // skeleton fallback value
    expect(result.fallbackReason).toBe("backend returned status=503");
  });

  it("fetchKpiRollupOrFallback falls back to skeleton on 501 (endpoint skeleton)", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("Not Implemented", { status: 501 }),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    expect(result.fallbackReason).toBe("backend returned status=501");
  });

  it("fetchKpiRollupOrFallback falls back on schema mismatch", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    // missing required `entries` field → Zod error
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ kpi_count: 5 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    expect(result.fallbackReason).toBe("backend response schema mismatch");
  });

  it("fetchKpiRollupOrFallback does NOT leak raw exception text in fallbackReason", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    // network error simulation (raw exception with sensitive message)
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new Error("postgresql://user:supersecret@host/db connection refused"),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    // sanitized: raw exception text (with credentials) NOT included
    expect(result.fallbackReason).toBe("backend fetch failed");
    expect(result.fallbackReason).not.toContain("supersecret");
    expect(result.fallbackReason).not.toContain("postgresql://");
  });
});
