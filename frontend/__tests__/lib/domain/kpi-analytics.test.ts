import { describe, expect, it } from "vitest";

import {
  KpiIdEnum,
  KpiTimeseriesResponseSchema,
  bucketStateLabel,
  formatKpiValue,
  kpiLabel,
  thresholdTone
} from "@/lib/domain/kpi-analytics";

const EXPECTED_KPI_IDS = [
  "acceptance_pass_rate",
  "approval_wait_ms",
  "citation_coverage",
  "cost_per_completed_task",
  "time_to_merge"
] as const;

describe("KPI enum integrity (5+ source 整合)", () => {
  it("matches backend KPI ids", () => {
    expect(new Set(KpiIdEnum.options)).toEqual(new Set(EXPECTED_KPI_IDS));
  });
  it("has a label for every kpi", () => {
    for (const id of EXPECTED_KPI_IDS) expect(kpiLabel(id)).not.toBe("");
  });
});

describe("formatKpiValue (backend unit authority)", () => {
  it("formats ratio as percent", () => {
    expect(formatKpiValue(0.6, "ratio")).toBe("60.0%");
  });
  it("formats usd", () => {
    expect(formatKpiValue(0.5, "usd")).toBe("$0.500");
  });
  it("formats ms as hours when >= 1h", () => {
    expect(formatKpiValue(7_200_000, "ms")).toBe("2.0h");
  });
  it("formats ms as minutes when < 1h", () => {
    expect(formatKpiValue(120_000, "ms")).toBe("2.0m");
  });
  it("returns empty for null (state 別文言で表示するため)", () => {
    expect(formatKpiValue(null, "ratio")).toBe("");
  });
});

describe("bucketStateLabel distinguishes 0/null/proxy/未計測 (F-008)", () => {
  it("measured has no note", () => {
    expect(bucketStateLabel("measured")).toBe("");
  });
  it("no_denominator / partial_unmeasured / proxy are distinct labels", () => {
    expect(bucketStateLabel("no_denominator")).toBe("対象データ無し");
    expect(bucketStateLabel("partial_unmeasured")).toBe("一部未計測");
    expect(bucketStateLabel("proxy")).toBe("代理指標");
  });
});

describe("thresholdTone", () => {
  it("higher_better met -> success", () => {
    expect(thresholdTone(0.95, 0.9, "higher_better")).toBe("success");
  });
  it("higher_better unmet -> warn", () => {
    expect(thresholdTone(0.5, 0.9, "higher_better")).toBe("warn");
  });
  it("lower_better met -> success", () => {
    expect(thresholdTone(0.3, 0.5, "lower_better")).toBe("success");
  });
  it("null -> neutral", () => {
    expect(thresholdTone(null, 0.9, "higher_better")).toBe("neutral");
  });
});

describe("KpiTimeseriesResponseSchema", () => {
  it("parses a valid response with null + state buckets", () => {
    const parsed = KpiTimeseriesResponseSchema.parse({
      bucket: "day",
      range: "month",
      project_id: null,
      unattributed_approval_count: 0,
      series: [
        {
          kpi_id: "cost_per_completed_task",
          unit: "usd",
          threshold: 0.5,
          direction: "lower_better",
          measurement_kind: "measured",
          buckets: [
            {
              bucket_start: "2026-06-01T00:00:00Z",
              value: 0.42,
              state: "measured",
              numerator_count: null,
              denominator_count: 3,
              measured_count: 3,
              unmeasured_count: 0
            },
            {
              bucket_start: "2026-06-02T00:00:00Z",
              value: null,
              state: "no_denominator",
              numerator_count: null,
              denominator_count: 0,
              measured_count: 0,
              unmeasured_count: 0
            }
          ]
        }
      ]
    });
    expect(parsed.series[0]?.buckets[1]?.state).toBe("no_denominator");
  });

  it("rejects an unknown kpi_id (drift guard)", () => {
    expect(() =>
      KpiTimeseriesResponseSchema.parse({
        bucket: "day",
        range: "month",
        project_id: null,
        unattributed_approval_count: 0,
        series: [
          {
            kpi_id: "unknown_kpi",
            unit: "usd",
            threshold: 0.5,
            direction: "lower_better",
            measurement_kind: "measured",
            buckets: []
          }
        ]
      })
    ).toThrow();
  });
});
