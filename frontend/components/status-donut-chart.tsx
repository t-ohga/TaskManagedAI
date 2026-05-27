type StatusCount = {
  label: string;
  count: number;
  color: string;
};

type StatusDonutChartProps = {
  data: StatusCount[];
  size?: number;
};

export function StatusDonutChart({ data, size = 120 }: StatusDonutChartProps) {
  const total = data.reduce((s, d) => s + d.count, 0);
  if (total === 0) {
    return (
      <div className="flex items-center justify-center" style={{ width: size, height: size }}>
        <span className="text-xs text-muted-foreground">データなし</span>
      </div>
    );
  }

  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  let offset = 0;

  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label="ステータス分布">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--tm-line)" strokeWidth="12" />
        {data.filter((d) => d.count > 0).map((d) => {
          const pct = d.count / total;
          const dash = circumference * pct;
          const gap = circumference - dash;
          const currentOffset = offset;
          offset += dash;
          return (
            <circle
              key={d.label}
              cx={cx}
              cy={cy}
              r={r}
              fill="none"
              stroke={d.color}
              strokeWidth="12"
              strokeDasharray={`${dash} ${gap}`}
              strokeDashoffset={-currentOffset}
              transform={`rotate(-90 ${cx} ${cy})`}
            />
          );
        })}
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" className="text-lg font-bold" fill="var(--tm-ink)">
          {total}
        </text>
      </svg>
      <div className="grid gap-1">
        {data.filter((d) => d.count > 0).map((d) => (
          <div key={d.label} className="flex items-center gap-2 text-xs">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: d.color }} />
            <span className="text-muted-foreground">{d.label}</span>
            <span className="font-semibold">{d.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
