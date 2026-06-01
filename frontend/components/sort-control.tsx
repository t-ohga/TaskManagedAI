"use client";

import { useRouter, useSearchParams } from "next/navigation";

// C-3 (UI 監査 fix): ソートロジックは tickets/page.tsx に実装済だが発火 UI control が無く
// URL 手動編集でしか動かなかった。`sort` searchParam を設定する select を提供する。
const SORT_OPTIONS = [
  { value: "created_desc", label: "作成日（新しい順）" },
  { value: "priority", label: "優先度" },
  { value: "title", label: "タイトル" },
  { value: "status", label: "ステータス" },
];

export function SortControl() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const current = searchParams.get("sort") ?? "created_desc";

  function handleChange(value: string) {
    const params = new URLSearchParams(searchParams.toString());
    if (value && value !== "created_desc") {
      params.set("sort", value);
    } else {
      params.delete("sort");
    }
    router.push(`?${params.toString()}`);
  }

  return (
    <select
      value={current}
      onChange={(event) => handleChange(event.target.value)}
      className="rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none"
      aria-label="並び替え"
    >
      {SORT_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
