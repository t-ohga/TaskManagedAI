import { MarkdownRenderer } from "@/components/markdown-renderer";

type TimelineEntry = {
  id: string;
  type: "comment" | "status_change" | "event";
  actor: string | null;
  body: string;
  created_at: string;
};

type ActivityTimelineProps = {
  entries: TimelineEntry[];
};

const TYPE_LABELS: Record<string, string> = {
  comment: "コメント",
  status_change: "ステータス変更",
  event: "イベント",
};

const TYPE_COLORS: Record<string, string> = {
  comment: "bg-blue-500",
  status_change: "bg-amber-500",
  event: "bg-gray-400",
};

export function ActivityTimeline({ entries }: ActivityTimelineProps) {
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        アクティビティはまだありません
      </p>
    );
  }

  return (
    <div className="grid gap-0" role="list" aria-label="アクティビティタイムライン">
      {entries.map((entry, i) => (
        <div key={entry.id} className="relative flex gap-3 pb-6" role="listitem">
          {i < entries.length - 1 && (
            <div className="absolute left-[7px] top-4 h-full w-px bg-line" aria-hidden="true" />
          )}
          <div className="relative z-10 mt-1 flex-shrink-0">
            <div className={`h-4 w-4 rounded-full ${TYPE_COLORS[entry.type] ?? "bg-gray-400"}`} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-medium text-ink">
                {entry.actor ? entry.actor.slice(0, 8) + "..." : "システム"}
              </span>
              <span>{TYPE_LABELS[entry.type] ?? entry.type}</span>
              <span>{new Date(entry.created_at).toLocaleString("ja-JP")}</span>
            </div>
            {entry.type === "comment" ? (
              <div className="mt-1">
                <MarkdownRenderer content={entry.body} />
              </div>
            ) : (
              <p className="mt-1 text-sm">{entry.body}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
