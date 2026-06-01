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
  const segments = data.filter((d) => d.count > 0);
  // 各セグメントの dash 長と開始 offset (= 自身より前の dash の総和) を arc オブジェクト配列に
  // 事前計算する。render 中に let 変数を map 内で += する mutation を避けるための prefix-sum
  // (react-hooks/immutability)。index access ではなく値を持つ配列を map する。
  const arcs = segments.map((d, i, arr) => {
    const dash = circumference * (d.count / total);
    const offset = arr
      .slice(0, i)
      .reduce((sum, prev) => sum + circumference * (prev.count / total), 0);
    return { label: d.label, color: d.color, dash, gap: circumference - dash, offset };
  });

  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label="ステータス分布">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--tm-line)" strokeWidth="12" />
        {arcs.map((arc) => (
          <circle
            key={arc.label}
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke={arc.color}
            strokeWidth="12"
            strokeDasharray={`${arc.dash} ${arc.gap}`}
            strokeDashoffset={-arc.offset}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        ))}
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
