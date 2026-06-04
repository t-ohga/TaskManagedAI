"use client";

import { useRouter, useSearchParams } from "next/navigation";

type Project = {
  id: string;
  slug: string;
  name: string;
};

type ProjectTabProps = {
  projects: Project[];
};

export function ProjectTab({ projects }: ProjectTabProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const current = searchParams.get("project") ?? "all";

  function handleSelect(slug: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("project", slug);
    router.push(`?${params.toString()}`);
  }

  return (
    <div className="flex flex-wrap gap-1 border-b border-line pb-2" role="tablist" aria-label="プロジェクト切替">
      <button
        role="tab"
        aria-selected={current === "all"}
        onClick={() => handleSelect("all")}
        className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
          current === "all"
            ? "bg-accent text-white"
            : "text-muted-foreground hover:bg-slate-100 dark:hover:bg-slate-800"
        }`}
        type="button"
      >
        全プロジェクト
      </button>
      {projects.map((p) => (
        <button
          key={p.id}
          role="tab"
          aria-selected={current === p.slug}
          onClick={() => handleSelect(p.slug)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            current === p.slug
              ? "bg-accent text-white"
              : "text-muted-foreground hover:bg-slate-100 dark:hover:bg-slate-800"
          }`}
          type="button"
        >
          {p.name}
        </button>
      ))}
    </div>
  );
}
