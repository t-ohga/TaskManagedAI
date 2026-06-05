import type { Route } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { BarChart } from "@/components/bar-chart";
import { getCurrentProjectId } from "@/lib/api/session";
import {
  loadKpiTimeseries,
  loadProviderBreakdown,
  type KpiTimeseriesLoad,
  type ProviderBreakdownLoad
} from "@/lib/api/eval-analytics";
import {
  RANGE_TABS,
  bucketStateLabel,
  formatKpiValue,
  kpiLabel,
  thresholdTone,
  type KpiSeries,
  type ProviderBreakdownResponse
} from "@/lib/domain/kpi-analytics";

export const dynamic = "force-dynamic";

type TimeseriesRange = "week" | "month" | "quarter";

const TONE_CLASS: Record<"success" | "warn" | "neutral", string> = {
  success: "text-green-700 dark:text-green-400",
  warn: "text-amber-700 dark:text-amber-400",
  neutral: "text-gray-500 dark:text-gray-400"
};

function resolveRange(value: string | undefined): TimeseriesRange {
  if (value === "week" || value === "month" || value === "quarter") return value;
  return "month";
}

function latestMeasuredValue(series: KpiSeries): number | null {
  for (let i = series.buckets.length - 1; i >= 0; i -= 1) {
    const b = series.buckets[i];
    if (b !== undefined && b.value !== null) return b.value;
  }
  return null;
}

function KpiSeriesCard({ series }: { series: KpiSeries }) {
  const latest = latestMeasuredValue(series);
  const tone = thresholdTone(latest, series.threshold, series.direction);
  const lastBucket = series.buckets.at(-1);
  const note = lastBucket ? bucketStateLabel(lastBucket.state) : "データ無し";
  const chartData = series.buckets
    .filter((b) => b.value !== null)
    .map((b) => ({ label: b.bucket_start.slice(5, 10), value: b.value as number }));

  return (
    <div className="rounded-md border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {kpiLabel(series.kpi_id)}
          {series.measurement_kind === "proxy" ? (
            <span className="ml-1 text-xs text-gray-400">(proxy)</span>
          ) : null}
        </h3>
        <span className={`text-lg font-bold ${TONE_CLASS[tone]}`}>
          {latest === null ? "—" : formatKpiValue(latest, series.unit)}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-gray-400">
        閾値: {formatKpiValue(series.threshold, series.unit)}（{series.direction === "higher_better" ? "以上" : "以下"}）
        {note ? ` · ${note}` : ""}
      </p>
      <div className="mt-3">
        {chartData.length > 0 ? (
          <BarChart data={chartData} />
        ) : (
          <p className="py-4 text-center text-xs text-gray-400">この期間のデータはありません</p>
        )}
      </div>
    </div>
  );
}

function ProviderBreakdownTable({ load }: { load: ProviderBreakdownLoad }) {
  if (!load.ok) {
    return (
      <p role="alert" className="text-sm text-red-700 dark:text-red-400">
        プロバイダ別集計の取得に失敗しました。
      </p>
    );
  }
  const data: ProviderBreakdownResponse = load.data;
  if (data.rows.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">eval 実行データがまだありません。</p>;
  }
  return (
    <div className="overflow-x-auto">
      <p className="mb-2 text-xs text-gray-400">tenant 全体の eval bake-off（プロジェクト絞り込み非適用）</p>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs text-gray-500 dark:border-gray-800 dark:text-gray-400">
            <th className="py-2 pr-4">プロバイダ</th>
            <th className="py-2 pr-4">モデル</th>
            <th className="py-2 pr-4">メトリクス</th>
            <th className="py-2 pr-4">実行数</th>
            <th className="py-2 pr-4">合格率</th>
            <th className="py-2">中央値スコア</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.flatMap((row) =>
            row.metrics.map((m) => (
              <tr
                key={`${row.provider}/${row.model}/${m.metric_key}`}
                className="border-b border-gray-100 text-gray-800 dark:border-gray-800 dark:text-gray-200"
              >
                <td className="py-1.5 pr-4 font-mono text-xs">{row.provider}</td>
                <td className="py-1.5 pr-4 font-mono text-xs">{row.model}</td>
                <td className="py-1.5 pr-4">{m.metric_key}</td>
                <td className="py-1.5 pr-4">{m.run_count}</td>
                <td className="py-1.5 pr-4">{m.pass_rate === null ? "—" : `${(m.pass_rate * 100).toFixed(1)}%`}</td>
                <td className="py-1.5">{m.median_score === null ? "—" : m.median_score.toFixed(3)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default async function AnalyticsPage({
  searchParams
}: {
  searchParams: Promise<{ range?: string; scope?: string }>;
}) {
  const sp = await searchParams;
  const range = resolveRange(sp.range);
  const scopeCurrent = sp.scope === "current";
  const projectId = scopeCurrent ? await getCurrentProjectId() : undefined;

  const timeseries: KpiTimeseriesLoad = await loadKpiTimeseries(
    projectId ? { range, projectId } : { range }
  );
  const providers: ProviderBreakdownLoad = await loadProviderBreakdown(range);

  const linkBase = (next: { range?: TimeseriesRange; scope?: string }): Route => {
    const params = new URLSearchParams();
    params.set("range", next.range ?? range);
    const scopeVal = next.scope ?? (scopeCurrent ? "current" : "all");
    if (scopeVal === "current") params.set("scope", "current");
    return `/eval-dashboard/analytics?${params.toString()}` as Route;
  };

  return (
    <section aria-label="KPI Analytics" className="grid gap-6">
      <PageHeader title="KPI 分析" description="運用実績の時系列推移（P0 Exit 判定の fixture KPI とは別軸）" />

      <div className="flex flex-wrap items-center gap-4">
        <nav aria-label="期間" className="flex gap-1">
          {RANGE_TABS.map((tab) => (
            <Link
              key={tab.value}
              href={linkBase({ range: tab.value })}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                range === tab.value
                  ? "bg-accent text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
        <nav aria-label="範囲" className="flex gap-1">
          <Link
            href={linkBase({ scope: "all" })}
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              !scopeCurrent
                ? "bg-accent text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            }`}
          >
            全プロジェクト
          </Link>
          <Link
            href={linkBase({ scope: "current" })}
            className={`rounded-md px-3 py-1 text-xs font-medium ${
              scopeCurrent
                ? "bg-accent text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            }`}
          >
            現プロジェクト
          </Link>
        </nav>
      </div>

      {!timeseries.ok ? (
        <div
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300"
        >
          KPI 時系列の取得に失敗しました。時間をおいて再読み込みしてください。
        </div>
      ) : (
        <>
          {timeseries.data.unattributed_approval_count > 0 ? (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              ※ run 未紐付の承認 {timeseries.data.unattributed_approval_count} 件はプロジェクト集計から除外されています。
            </p>
          ) : null}
          <div className="grid gap-4 md:grid-cols-2">
            {timeseries.data.series.map((series) => (
              <KpiSeriesCard key={series.kpi_id} series={series} />
            ))}
          </div>
        </>
      )}

      <div className="rounded-md border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
        <h2 className="mb-3 text-sm font-semibold text-gray-700 dark:text-gray-300">プロバイダ別 eval 結果</h2>
        <ProviderBreakdownTable load={providers} />
      </div>
    </section>
  );
}
