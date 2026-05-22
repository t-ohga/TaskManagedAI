import { describe, expect, it } from "vitest";

import {
  formatTicketPriority,
  formatTicketStatus,
  TICKET_PRIORITY_LABELS,
  TICKET_STATUS_LABELS
} from "@/lib/i18n/ticket-labels";

describe("ticket i18n labels", () => {
  it("keeps every ticket status value visible with a Japanese label", () => {
    expect(TICKET_STATUS_LABELS).toEqual({
      open: "未着手",
      in_progress: "進行中",
      blocked: "ブロック中",
      review: "レビュー中",
      closed: "完了",
      cancelled: "キャンセル済み"
    });
    expect(formatTicketStatus("in_progress")).toBe("進行中 (in_progress)");
  });

  it("keeps every ticket priority value visible with a Japanese label", () => {
    expect(TICKET_PRIORITY_LABELS).toEqual({
      low: "低",
      medium: "中",
      high: "高",
      critical: "緊急"
    });
    expect(formatTicketPriority("critical")).toBe("緊急 (critical)");
    expect(formatTicketPriority(null)).toBe("(未指定)");
  });
});
