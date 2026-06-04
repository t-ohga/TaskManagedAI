export function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-lg border border-line bg-panel p-4">
      <div className="h-4 w-3/4 rounded bg-gray-200 dark:bg-gray-700" />
      <div className="mt-2 h-3 w-1/2 rounded bg-gray-200 dark:bg-gray-700" />
      <div className="mt-3 flex gap-2">
        <div className="h-5 w-16 rounded-full bg-gray-200 dark:bg-gray-700" />
        <div className="h-5 w-12 rounded-full bg-gray-200 dark:bg-gray-700" />
      </div>
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="animate-pulse rounded-lg border border-line">
      <div className="border-b border-line bg-slate-50 dark:bg-slate-800 px-4 py-3">
        <div className="h-4 w-1/3 rounded bg-gray-200 dark:bg-gray-700" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 border-b border-line px-4 py-3">
          <div className="h-3 w-24 rounded bg-gray-200 dark:bg-gray-700" />
          <div className="h-3 w-32 rounded bg-gray-200 dark:bg-gray-700" />
          <div className="h-3 w-20 rounded bg-gray-200 dark:bg-gray-700" />
        </div>
      ))}
    </div>
  );
}
