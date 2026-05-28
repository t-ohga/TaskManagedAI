"use client";

import { useRouter, useSearchParams } from "next/navigation";

const RANGES = [
  { value: "", label: "全期間" },
  { value: "today", label: "今日" },
  { value: "week", label: "今週" },
  { value: "month", label: "今月" },
  { value: "quarter", label: "四半期" },
];

export function DateRangeFilter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const current = searchParams.get("range") ?? "";

  function handleChange(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set("range", value);
    } else {
      params.delete("range");
    }
    router.push(`?${params.toString()}`);
  }

  return (
    <select
      value={current}
      onChange={(e) => handleChange(e.target.value)}
      className="rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none"
      aria-label="期間フィルター"
    >
      {RANGES.map((r) => (
        <option key={r.value} value={r.value}>{r.label}</option>
      ))}
    </select>
  );
}
