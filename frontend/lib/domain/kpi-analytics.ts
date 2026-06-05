import { z } from "zod";

/**
 * ADR-00051 (SP-026): KPI analytics drilldown の client-safe schema / 型 / 表示ヘルパー。
 *
 * **Client Component から import されるため `next/headers` 等 server-only 依存を持たない**。fetch は
 * `@/lib/api/eval-analytics` に分離。unit / threshold / direction は **backend authority** (本 module で
 * 再定義しない、F-009)。値は集計値のみ (secret なし)。
 */

export const KpiIdEnum = z.enum([
  "acceptance_pass_rate",
  "approval_wait_ms",
  "citation_coverage",
  "cost_per_completed_task",
  "time_to_merge"
]);
export type KpiId = z.infer<typeof KpiIdEnum>;

export const BucketStateEnum = z.enum([
  "measured",
  "no_denominator",
  "partial_unmeasured",
  "proxy"
]);
export type BucketState = z.infer<typeof BucketStateEnum>;

const KpiBucketSchema = z.object({
  bucket_start: z.string(),
  value: z.number().nullable(),
  state: BucketStateEnum,
  numerator_count: z.number().int().nullable(),
  denominator_count: z.number().int().nullable(),
  measured_count: z.number().int().nullable(),
  unmeasured_count: z.number().int().nullable()
});
export type KpiBucket = z.infer<typeof KpiBucketSchema>;

const KpiSeriesSchema = z.object({
  kpi_id: KpiIdEnum,
  unit: z.string(),
  threshold: z.number(),
  direction: z.enum(["higher_better", "lower_better"]),
  measurement_kind: z.enum(["measured", "proxy"]),
  buckets: z.array(KpiBucketSchema)
});
export type KpiSeries = z.infer<typeof KpiSeriesSchema>;

export const KpiTimeseriesResponseSchema = z.object({
  bucket: z.enum(["day", "week"]),
  range: z.enum(["week", "month", "quarter"]),
  project_id: z.string().uuid().nullable(),
  unattributed_approval_count: z.number().int(),
  series: z.array(KpiSeriesSchema)
});
export type KpiTimeseriesResponse = z.infer<typeof KpiTimeseriesResponseSchema>;

const ProviderBreakdownMetricSchema = z.object({
  metric_key: z.string(),
  run_count: z.number().int(),
  pass_rate: z.number().nullable(),
  median_score: z.number().nullable()
});

const ProviderBreakdownRowSchema = z.object({
  provider: z.string(),
  model: z.string(),
  metrics: z.array(ProviderBreakdownMetricSchema)
});

export const ProviderBreakdownResponseSchema = z.object({
  range: z.enum(["week", "month", "quarter"]),
  scope: z.literal("tenant"),
  project_filter_applied: z.literal(false),
  rows: z.array(ProviderBreakdownRowSchema)
});
export type ProviderBreakdownResponse = z.infer<typeof ProviderBreakdownResponseSchema>;

const KPI_LABELS: Record<KpiId, string> = {
  acceptance_pass_rate: "合格率",
  approval_wait_ms: "承認待ち",
  citation_coverage: "引用カバレッジ",
  cost_per_completed_task: "タスク単価",
  time_to_merge: "マージ時間 (代理)"
};

export function kpiLabel(kpiId: KpiId): string {
  return KPI_LABELS[kpiId];
}

/** range の UI ラベル (7d/30d/90d は week/month/quarter にマップ、F-006)。 */
export const RANGE_TABS = [
  { value: "week", label: "7日" },
  { value: "month", label: "30日" },
  { value: "quarter", label: "90日" }
] as const;

/**
 * KPI 値を unit に応じて整形 (backend unit authority に従う)。null は state 別文言で表示するため "" を返す。
 */
export function formatKpiValue(value: number | null, unit: string): string {
  if (value === null) return "";
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  if (unit === "usd") return `$${value.toFixed(3)}`;
  if (unit === "ms") {
    const hours = value / 3_600_000;
    if (hours >= 1) return `${hours.toFixed(1)}h`;
    const minutes = value / 60_000;
    return `${minutes.toFixed(1)}m`;
  }
  return String(value);
}

/** bucket の state に応じた表示文言 (0/null/proxy/未計測 を区別、F-008)。 */
export function bucketStateLabel(state: BucketState): string {
  switch (state) {
    case "measured":
      return "";
    case "no_denominator":
      return "対象データ無し";
    case "partial_unmeasured":
      return "一部未計測";
    case "proxy":
      return "代理指標";
  }
}

/** value と threshold/direction から閾値達成 tone を返す (達成=success / 未達=warn)。 */
export function thresholdTone(
  value: number | null,
  threshold: number,
  direction: "higher_better" | "lower_better"
): "success" | "warn" | "neutral" {
  if (value === null) return "neutral";
  const met = direction === "higher_better" ? value >= threshold : value <= threshold;
  return met ? "success" : "warn";
}
