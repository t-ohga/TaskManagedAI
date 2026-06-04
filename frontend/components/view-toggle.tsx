"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

type ViewToggleProps = {
  currentView: "kanban" | "list";
};

export function ViewToggle({ currentView }: ViewToggleProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const toggle = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("view", currentView === "kanban" ? "list" : "kanban");
    router.push(`/tickets?${params.toString()}`);
  }, [currentView, router, searchParams]);

  return (
    <div className="flex items-center rounded-md border border-line bg-panel">
      <button
        type="button"
        onClick={() => { if (currentView !== "kanban") toggle(); }}
        className={`rounded-l-md px-3 py-1.5 text-xs font-medium transition-colors ${
          currentView === "kanban"
            ? "bg-accent text-white"
            : "text-muted-foreground hover:bg-slate-50 dark:hover:bg-slate-800"
        }`}
        aria-pressed={currentView === "kanban"}
      >
        看板
      </button>
      <button
        type="button"
        onClick={() => { if (currentView !== "list") toggle(); }}
        className={`rounded-r-md px-3 py-1.5 text-xs font-medium transition-colors ${
          currentView === "list"
            ? "bg-accent text-white"
            : "text-muted-foreground hover:bg-slate-50 dark:hover:bg-slate-800"
        }`}
        aria-pressed={currentView === "list"}
      >
        リスト
      </button>
    </div>
  );
}
