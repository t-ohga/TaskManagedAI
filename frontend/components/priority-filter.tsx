"use client";

import { useRouter, useSearchParams } from "next/navigation";

const PRIORITIES = [
  { value: "", label: "全優先度" },
  { value: "critical", label: "最優先" },
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
];

export function PriorityFilter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const current = searchParams.get("priority") ?? "";

  function handleChange(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set("priority", value);
    } else {
      params.delete("priority");
    }
    router.push(`?${params.toString()}`);
  }

  return (
    <select
      value={current}
      onChange={(e) => handleChange(e.target.value)}
      className="rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none"
      aria-label="優先度フィルター"
    >
      {PRIORITIES.map((p) => (
        <option key={p.value} value={p.value}>{p.label}</option>
      ))}
    </select>
  );
}
