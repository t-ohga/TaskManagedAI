import { SkeletonCard } from "@/components/skeleton-card";

export default function RunsLoading() {
  return (
    <section aria-label="AI 実行読み込み中" className="grid gap-4" aria-busy="true">
      <div className="h-8 w-32 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
      <div className="grid gap-2">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </section>
  );
}
