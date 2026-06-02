import type { TagColor } from "@/lib/domain/tag";

/**
 * ADR-00044 (A-5): tag を色付き chip で表示する pure presentation component。
 *
 * Tailwind は JIT purge で動的 class 名 (`bg-${color}-100` 等) を除去するため、
 * palette 9 色を完全な class 名で静的 mapping する。TagColor (backend 由来 enum) を
 * key にするので、palette が drift した場合は型エラーで検出される。
 */
const TAG_COLOR_CLASSES: Record<TagColor, string> = {
  slate: "bg-slate-100 text-slate-700 border-slate-300",
  red: "bg-red-100 text-red-700 border-red-300",
  orange: "bg-orange-100 text-orange-700 border-orange-300",
  amber: "bg-amber-100 text-amber-800 border-amber-300",
  green: "bg-green-100 text-green-700 border-green-300",
  teal: "bg-teal-100 text-teal-700 border-teal-300",
  blue: "bg-blue-100 text-blue-700 border-blue-300",
  purple: "bg-purple-100 text-purple-700 border-purple-300",
  pink: "bg-pink-100 text-pink-700 border-pink-300"
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
