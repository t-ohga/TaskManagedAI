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

  it("fetchKpiRollupOrFallback rethrows on 401 (auth failure not silent-fallback)", async () => {
    // Codex PR #91 R1 F-001 fix (P1): 401 auth error は operator が認識する必要があるため rethrow
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue(undefined); // no session cookie
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("Unauthorized", { status: 401 }),
    );
    await expect(fetchKpiRollupOrFallback(SKELETON_FALLBACK)).rejects.toThrow(/401/);
  });

  it("fetchKpiRollupOrFallback rethrows on 403 (permission failure not silent-fallback)", async () => {
    // Codex PR #91 R1 F-001 fix (P1): 403 forbidden も同様 rethrow (auth context invalid)
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("Forbidden", { status: 403 }),
    );
    await expect(fetchKpiRollupOrFallback(SKELETON_FALLBACK)).rejects.toThrow(/403/);
  });

  it("fetchKpiRollupOrFallback rethrows on raw exception (env misconfig)", async () => {
    // Codex PR #91 R1 F-004 fix (P2): config / runtime / env error は hidden しない rethrow
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new Error("INTERNAL_API_URL must be configured"),
    );
    await expect(fetchKpiRollupOrFallback(SKELETON_FALLBACK)).rejects.toThrow(
      "INTERNAL_API_URL must be configured",
    );
  });

  it("Zod schema rejects truncated entries (4 instead of 5)", async () => {
    // Codex PR #91 R1 F-002 fix (P2): cardinality enforce (length === 5)
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    const truncated = { ...VALID_RESPONSE, entries: VALID_RESPONSE.entries.slice(0, 4) };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(truncated), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    expect(result.fallbackReason).toBe("backend response schema mismatch");
  });

  it("Zod schema rejects duplicate KPI ids (e.g., AC-KPI-01 twice)", async () => {
    // Codex PR #91 R1 F-002 fix (P2): ID coverage invariant (each AC-KPI-01〜05 once)
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    const dup = {
      ...VALID_RESPONSE,
      entries: [
        VALID_RESPONSE.entries[0],
        VALID_RESPONSE.entries[0], // duplicate AC-KPI-01
        ...VALID_RESPONSE.entries.slice(2),
      ],
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(dup), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    expect(result.fallbackReason).toBe("backend response schema mismatch");
  });

  it("Zod schema rejects sum invariant violation (met + failed != kpi_count)", async () => {
    // Codex PR #91 R1 F-002 fix (P2): sum invariant from KpiRollupSummary contract
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    cookieMocks.get.mockReturnValue({ value: "session-cookie-value" });
    const invalid = { ...VALID_RESPONSE, met_count: 3, failed_count: 1 }; // sum=4 != kpi_count=5
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(invalid), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const result = await fetchKpiRollupOrFallback(SKELETON_FALLBACK);
    expect(result.source).toBe("skeleton_fallback");
    expect(result.fallbackReason).toBe("backend response schema mismatch");
  });
});
