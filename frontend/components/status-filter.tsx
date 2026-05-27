"use client";

import { useRouter, useSearchParams } from "next/navigation";

const STATUSES = [
  { value: "", label: "すべて" },
  { value: "open", label: "未着手" },
  { value: "in_progress", label: "進行中" },
  { value: "blocked", label: "ブロック" },
  { value: "review", label: "レビュー" },
  { value: "closed", label: "完了" },
  { value: "cancelled", label: "中止" },
];

export function StatusFilter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const current = searchParams.get("status") ?? "";

  function handleChange(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set("status", value);
    } else {
      params.delete("status");
    }
    router.push(`?${params.toString()}`);
  }

  return (
    <select
      value={current}
      onChange={(e) => handleChange(e.target.value)}
      className="rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none"
      aria-label="ステータスフィルター"
    >
      {STATUSES.map((s) => (
        <option key={s.value} value={s.value}>{s.label}</option>
      ))}
    </select>
  );
}
