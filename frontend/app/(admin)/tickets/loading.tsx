import { SkeletonCard } from "@/components/skeleton-card";

export default function TicketsLoading() {
  return (
    <section aria-label="チケット読み込み中" className="grid gap-4" aria-busy="true">
      <div className="h-8 w-32 animate-pulse rounded bg-gray-200" />
      <div className="grid gap-4 lg:grid-cols-3">
        {["todo", "active", "done"].map((col) => (
          <div key={col} className="grid gap-2">
            <div className="h-10 animate-pulse rounded-lg bg-gray-100" />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ))}
      </div>
    </section>
  );
}
