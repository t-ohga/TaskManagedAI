type BarChartProps = {
  data: { label: string; value: number }[];
  maxValue?: number;
  height?: number;
};

export function BarChart({ data, maxValue, height = 120 }: BarChartProps) {
  const max = maxValue ?? Math.max(...data.map((d) => d.value), 1);

  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">データなし</p>;
  }

  return (
    <div className="flex items-end gap-1" style={{ height }} aria-label="バーチャート">
      {data.map((d) => {
        const pct = (d.value / max) * 100;
        return (
          <div key={d.label} className="flex flex-1 flex-col items-center gap-1">
            <span className="text-[10px] font-semibold tabular-nums">{d.value}</span>
            <div className="flex w-full flex-1 items-end">
              <div
                className="w-full rounded-t bg-accent/70 transition-all"
                style={{ height: `${Math.max(pct, 4)}%` }}
              title={`${d.label}: ${d.value}`}
            />
            </div>
            <span className="text-[9px] text-muted-foreground">{d.label}</span>
          </div>
        );
      })}
    </div>
  );
}
