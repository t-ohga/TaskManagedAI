import type { TagColor } from "@/lib/domain/tag";

/**
 * ADR-00044 (A-5): tag を色付き chip で表示する pure presentation component。
 *
 * Tailwind は JIT purge で動的 class 名 (`bg-${color}-100` 等) を除去するため、
 * palette 9 色を完全な class 名で静的 mapping する。TagColor (backend 由来 enum) を
 * key にするので、palette が drift した場合は型エラーで検出される。
 */
const TAG_COLOR_CLASSES: Record<TagColor, string> = {
  slate: "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700",
  red: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700",
  orange: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 border-orange-300 dark:border-orange-700",
  amber: "bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 border-amber-300 dark:border-amber-700",
  green: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300 border-green-300 dark:border-green-700",
  teal: "bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300 border-teal-300 dark:border-teal-700",
  blue: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 border-blue-300 dark:border-blue-700",
  purple: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 border-purple-300 dark:border-purple-700",
  pink: "bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300 border-pink-300 dark:border-pink-700"
};

export function TagChip({
  name,
  color,
  className = ""
}: {
  name: string;
  color: TagColor;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex max-w-full items-center truncate rounded-full border px-2 py-0.5 text-xs font-medium ${TAG_COLOR_CLASSES[color]} ${className}`}
      title={name}
    >
      {name}
    </span>
  );
}
