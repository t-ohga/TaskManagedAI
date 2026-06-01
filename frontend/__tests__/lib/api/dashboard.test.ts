import { describe, expect, it } from "vitest";

import { foldTicketDisplayCounts } from "@/lib/api/dashboard";

describe("foldTicketDisplayCounts (ADR-00039 D-5 表示 bucket)", () => {
  it("in_progress = in_progress + blocked + review に折り畳む", () => {
    const out = foldTicketDisplayCounts([
      { status: "in_progress", count: 3 },
      { status: "blocked", count: 2 },
      { status: "review", count: 4 }
    ]);
    expect(out.in_progress).toBe(9);
    expect(out.open).toBe(0);
    expect(out.closed).toBe(0);
    expect(out.cancelled).toBe(0);
  });

  it("open / closed / cancelled はそのまま、未知 status は open に fallback", () => {
    const out = foldTicketDisplayCounts([
      { status: "open", count: 5 },
      { status: "closed", count: 7 },
      { status: "cancelled", count: 1 },
      { status: "weird_unknown", count: 2 }
    ]);
    expect(out.open).toBe(7); // 5 + 未知 2
    expect(out.closed).toBe(7);
    expect(out.cancelled).toBe(1);
    expect(out.in_progress).toBe(0);
  });

  it("4 bucket 合計が raw status_counts 合計 (ticket_total) と一致する (欠落・二重計上なし)", () => {
    const raw = [
      { status: "open", count: 5 },
      { status: "in_progress", count: 3 },
      { status: "blocked", count: 2 },
      { status: "review", count: 4 },
      { status: "closed", count: 7 },
      { status: "cancelled", count: 1 }
    ];
    const ticketTotal = raw.reduce((s, c) => s + c.count, 0);
    const out = foldTicketDisplayCounts(raw);
    const bucketTotal = out.open + out.in_progress + out.closed + out.cancelled;
    expect(bucketTotal).toBe(ticketTotal);
    expect(bucketTotal).toBe(22);
  });

  it("空入力は全 0 を返す", () => {
    expect(foldTicketDisplayCounts([])).toEqual({
      open: 0,
      in_progress: 0,
      closed: 0,
      cancelled: 0
    });
  });
});
