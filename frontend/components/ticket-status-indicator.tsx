type TicketStatus = "open" | "in_progress" | "blocked" | "review" | "closed" | "cancelled";

const TICKET_STATUS_CONFIG: Record<TicketStatus, { color: string; label: string }> = {
  open: { color: "bg-blue-500", label: "未着手" },
  in_progress: { color: "bg-amber-500", label: "進行中" },
  blocked: { color: "bg-orange-500", label: "ブロック" },
  review: { color: "bg-purple-500", label: "レビュー中" },
  closed: { color: "bg-emerald-500", label: "完了" },
  cancelled: { color: "bg-gray-400", label: "中止" },
};

export function TicketStatusIndicator({ status }: { status: string }) {
  const config = TICKET_STATUS_CONFIG[status as TicketStatus] ?? {
    color: "bg-gray-300",
    label: status,
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${config.color}`} aria-hidden="true" />
      <span className="text-xs font-medium">{config.label}</span>
    </span>
  );
}

export const TICKET_STATUSES = Object.keys(TICKET_STATUS_CONFIG) as TicketStatus[];
