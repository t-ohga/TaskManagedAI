import type { TicketPriority, TicketStatus } from "@/lib/api/tickets";

export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  open: "未着手",
  in_progress: "進行中",
  blocked: "ブロック中",
  review: "レビュー中",
  closed: "完了",
  cancelled: "キャンセル済み"
};

export const TICKET_PRIORITY_LABELS: Record<TicketPriority, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "緊急"
};

export function formatTicketStatus(status: TicketStatus): string {
  return `${TICKET_STATUS_LABELS[status]} (${status})`;
}

export function formatTicketPriority(priority: TicketPriority | null): string {
  return priority ? `${TICKET_PRIORITY_LABELS[priority]} (${priority})` : "(未指定)";
}
