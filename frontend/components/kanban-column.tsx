import type { ReactNode } from "react";

type KanbanColumnProps = {
  title: string;
  count: number;
  color: string;
  children: ReactNode;
};

export function KanbanColumn({ title, count, color, children }: KanbanColumnProps) {
  return (
    <div className="flex min-h-[300px] flex-col rounded-lg border border-line bg-canvas">
      <div className={`flex items-center justify-between rounded-t-lg border-b border-line px-4 py-3 ${color}`}>
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full bg-white/80 px-2 py-0.5 text-xs font-medium">
          {count}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        {count === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            チケットはありません
          </p>
        ) : (
          children
        )}
      </div>
    </div>
  );
}
